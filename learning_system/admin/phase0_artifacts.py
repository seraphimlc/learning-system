"""Build and freeze the v20 Phase 0 slot artifacts.

The builder is intentionally fail-closed. A partial set of reviewed briefs is
useful diagnostic evidence, but it is not an inventory and cannot authorize
question generation.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import slot_brief_generation, slot_brief_inventory, slot_brief_review
from . import slot_manifest, slot_portfolio_review, v20_bank_namespace
from .slot_architecture import (
    architecture_content_digest,
    graph_content_digest,
    load_and_validate,
    load_graph,
)
from .v20_receipts import canonical_json, sha256_json


INVENTORY_PATH = "data/question_banks/v20/slot_briefs_v20.json"
SUMMARY_PATH = "data/question_banks/v20/slot_review_summary_v20.json"
SLOT_MANIFEST_PATH = "data/question_banks/v20/slot_manifest_v20.json"
SLOT_MANIFEST_SHA_PATH = "data/question_banks/v20/slot_manifest_v20.sha256"
PORTFOLIO_RECEIPTS_DIR = "data/question_banks/v20/slot_portfolio_review_receipts"
PHASE0_REPORT_PATH = "data/question_banks/v20/phase0_gate_report_v20.json"
SUMMARY_SCHEMA_VERSION = "question-slot-review-summary.v20"


class Phase0ArtifactError(ValueError):
    def __init__(self, message: str, *, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase0ArtifactError(f"unable to load artifact: {path}") from exc
    if not isinstance(value, dict):
        raise Phase0ArtifactError(f"artifact must be a JSON object: {path}")
    return value


def _paths(root: Path) -> dict[str, Path]:
    base = root / "data/question_banks/v20"
    return {
        "graph": root / "data/knowledge_graphs/math/math_knowledge_graph_v2.json",
        "architecture": base / "slot_architecture_v20.json",
        "contract": base / "slot_brief_generation_contract_v20.json",
        "review_policy": base / "slot_brief_review_policy_v20.json",
        "architecture_review_policy": base / "slot_architecture_review_policy_v20.json",
        "briefs": base / "slot_brief_reviewed",
        "brief_receipts": base / "slot_brief_review_receipts",
        "brief_packets": base / "slot_brief_review_packets",
        "portfolio_receipts": base / "slot_portfolio_review_receipts",
    }


def _expected_plans(root: Path, architecture: dict[str, Any], graph: dict[str, Any], contract: dict[str, Any], review_policy_sha256: str) -> dict[str, dict[str, Any]]:
    queue = slot_brief_generation.build_queue(
        architecture=architecture,
        graph=graph,
        contract=contract,
        review_policy_sha256=review_policy_sha256,
    )
    return {plan["slot_id"]: plan for plan in queue["plans"]}


def _brief_artifact_for_receipt(
    paths: dict[str, Path],
    *,
    receipt: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
) -> dict[str, Any] | None:
    """Find the exact brief version a review receipt claims to review.

    A rejected attempt remains part of the append-only evidence trail. It must
    be checked against its own draft, not against the slot's later REVIEWED
    brief, otherwise a valid repair history is reported as corrupted.
    """
    candidates = list(paths["briefs"].glob(f"{receipt['slot_id']}*.json"))
    candidates.extend(paths["briefs"].parent.joinpath("slot_brief_drafts").glob(f"{receipt['slot_id']}*.json"))
    matches: list[dict[str, Any]] = []
    for path in sorted(candidates):
        try:
            brief = slot_brief_inventory.validate_brief(
                _load_json(path),
                graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
                graph=graph,
                architecture=architecture,
                contract=contract,
                review_policy_sha256=review_policy_sha256,
            )
        except (OSError, ValueError, slot_brief_inventory.SlotBriefInventoryError):
            continue
        if brief["slot_id"] == receipt["slot_id"] and slot_brief_review.brief_content_digest(brief) == receipt["brief_sha256"]:
            matches.append(brief)
    return matches[0] if matches else None


def _reviewed_briefs_and_receipts(
    root: Path,
    *,
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    review_policy: dict[str, Any],
    expected_slot_ids: set[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    paths = _paths(root)
    policy_sha = slot_brief_review.policy_digest(review_policy)
    briefs: dict[str, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    for path in sorted(paths["briefs"].glob("*.json")):
        try:
            brief = _load_json(path)
            if brief.get("status") != "REVIEWED":
                raise ValueError("brief is not REVIEWED")
            brief = slot_brief_inventory.validate_brief(
                brief,
                graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
                graph=graph,
                architecture=architecture,
                contract=contract,
                review_policy_sha256=policy_sha,
            )
            slot_id = brief["slot_id"]
            if slot_id in briefs:
                raise ValueError("duplicate reviewed slot_id")
            briefs[slot_id] = brief
        except (OSError, ValueError, slot_brief_inventory.SlotBriefInventoryError) as exc:
            invalid.append({"path": str(path), "reason": str(exc)})

    receipts_by_slot: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(paths["brief_receipts"].glob("*.json")):
        try:
            receipt = slot_brief_review.validate_review_receipt(_load_json(path))
            slot_brief_review.assert_raw_response_artifact(receipt, base_dir=paths["briefs"].parent)
            brief_for_receipt = _brief_artifact_for_receipt(
                paths,
                receipt=receipt,
                architecture=architecture,
                graph=graph,
                contract=contract,
                review_policy_sha256=policy_sha,
            )
            if brief_for_receipt is None:
                raise slot_brief_review.SlotBriefReviewError(
                    "review receipt has no matching brief artifact"
                )
            slot_brief_review.assert_review_packet_artifact(
                receipt, brief=brief_for_receipt, packet_dir=paths["brief_packets"]
            )
            receipts_by_slot.setdefault(receipt["slot_id"], []).append(receipt)
        except (OSError, ValueError, slot_brief_review.SlotBriefReviewError) as exc:
            invalid.append({"path": str(path), "reason": str(exc)})
    for slot_id, receipts in receipts_by_slot.items():
        brief = briefs.get(slot_id)
        if brief is None:
            if expected_slot_ids is None or slot_id not in expected_slot_ids:
                invalid.append({"slot_id": slot_id, "reason": "review receipt has no planned slot"})
            continue
        try:
            current_receipts = [
                receipt
                for receipt in receipts
                if receipt["brief_sha256"] == slot_brief_review.brief_content_digest(brief)
            ]
            slot_brief_review.assert_reviewed_brief_evidence(
                brief=brief,
                architecture=architecture,
                graph=graph,
                policy=review_policy,
                receipts=current_receipts,
            )
        except (ValueError, slot_brief_review.SlotBriefReviewError) as exc:
            invalid.append({"slot_id": slot_id, "reason": str(exc)})
    return briefs, receipts_by_slot, invalid


def _build_inventory(
    *,
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
    briefs: dict[str, dict[str, Any]],
    expected_slot_ids: set[str],
) -> dict[str, Any]:
    if set(briefs) != expected_slot_ids:
        missing = sorted(expected_slot_ids - set(briefs))
        extra = sorted(set(briefs) - expected_slot_ids)
        raise Phase0ArtifactError(
            "slot brief inventory is incomplete",
            report={"missing_slot_ids": missing, "unexpected_slot_ids": extra},
        )
    slots = [briefs[slot_id] for slot_id in sorted(briefs)]
    inventory = {
        "schema_version": slot_brief_inventory.INVENTORY_SCHEMA_VERSION,
        "status": "REVIEWED",
        "architecture_sha256": architecture_content_digest(architecture),
        "graph_sha256": graph_content_digest(graph),
        "review_policy_sha256": review_policy_sha256,
        "generation_contract_sha256": slot_brief_inventory.contract_digest(contract),
        "planned_slot_count": architecture["capacity"]["planned_slot_count"],
        "slots": slots,
        "inventory_sha256": "",
    }
    inventory["inventory_sha256"] = slot_brief_inventory.inventory_digest(inventory)
    return slot_brief_inventory.validate_inventory(
        inventory,
        architecture=architecture,
        graph=graph,
        contract=contract,
        review_policy_sha256=review_policy_sha256,
    )


def _build_review_summary(
    *,
    inventory: dict[str, Any],
    receipts_by_slot: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    slots = []
    for brief in inventory["slots"]:
        receipts = sorted(receipts_by_slot.get(brief["slot_id"], []), key=lambda item: item["receipt_id"])
        if not receipts:
            raise Phase0ArtifactError(
                f"missing slot review receipts: {brief['slot_id']}",
                report={"missing_review_receipts": [brief["slot_id"]]},
            )
        expected_ids = set(brief["review_evidence"]["receipt_ids"])
        actual_ids = {receipt["receipt_id"] for receipt in receipts}
        if actual_ids != expected_ids:
            raise Phase0ArtifactError(
                f"slot review evidence mismatch: {brief['slot_id']}",
                report={"slot_id": brief["slot_id"], "expected_receipt_ids": sorted(expected_ids), "actual_receipt_ids": sorted(actual_ids)},
            )
        slots.append(
            {
                "slot_id": brief["slot_id"],
                "brief_sha256": brief["brief_sha256"],
                "review_receipt_set_sha256": brief["review_evidence"]["receipt_set_sha256"],
                "receipt_ids": sorted(actual_ids),
                "verdicts": sorted({receipt["verdict"] for receipt in receipts}),
            }
        )
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "status": "REVIEWED",
        "inventory_sha256": inventory["inventory_sha256"],
        "architecture_sha256": inventory["architecture_sha256"],
        "graph_sha256": inventory["graph_sha256"],
        "review_policy_sha256": inventory["review_policy_sha256"],
        "planned_slot_count": inventory["planned_slot_count"],
        "slots": slots,
        "summary_sha256": "",
    }
    summary["summary_sha256"] = sha256_json({key: value for key, value in summary.items() if key != "summary_sha256"})
    return summary


def collect_phase0_report(project_root: Path | str) -> dict[str, Any]:
    """Return a diagnostic report without creating authorization artifacts."""
    root = Path(project_root)
    paths = _paths(root)
    try:
        graph = load_graph(paths["graph"])
        architecture = load_and_validate(paths["architecture"], paths["graph"])
        contract = slot_brief_inventory.validate_contract(_load_json(paths["contract"]))
        review_policy = slot_brief_review.load_policy(paths["review_policy"])
        review_policy_sha = slot_brief_review.policy_digest(review_policy)
        plans = _expected_plans(root, architecture, graph, contract, review_policy_sha)
        briefs, receipts_by_slot, invalid = _reviewed_briefs_and_receipts(
            root,
            architecture=architecture,
            graph=graph,
            contract=contract,
            review_policy=review_policy,
            expected_slot_ids=set(plans),
        )
        missing = sorted(set(plans) - set(briefs))
        unexpected = sorted(set(briefs) - set(plans))
        missing_review_receipts = sorted(
            slot_id for slot_id in briefs if not receipts_by_slot.get(slot_id)
        )
        portfolio_roles: set[str] = set()
        portfolio_invalid: list[str] = []
        for path in sorted(paths["portfolio_receipts"].glob("*.json")):
            try:
                portfolio_roles.add(
                    slot_portfolio_review.validate_portfolio_receipt(_load_json(path))["reviewer_role"]
                )
            except (OSError, ValueError, slot_portfolio_review.SlotPortfolioReviewError) as exc:
                portfolio_invalid.append(f"{path}: {exc}")
        portfolio_ready = portfolio_roles == slot_portfolio_review.REQUIRED_ROLES and not portfolio_invalid
        gate_ready = not missing and not unexpected and not missing_review_receipts and not invalid and portfolio_ready
        next_gate = (
            "freeze_manifest"
            if gate_ready
            else (
                "portfolio_review"
                if not missing and not unexpected and not missing_review_receipts and not invalid
                else "complete_or_repair_slot_briefs"
            )
        )
        report = {
            "schema_version": "question-bank-v20-phase0-gate-report.v1",
            "status": "PASS" if gate_ready else "BLOCKED",
            "planned_slot_count": len(plans),
            "reviewed_brief_count": len(briefs),
            "review_receipt_slot_count": len(receipts_by_slot),
            "missing_slot_ids": missing,
            "unexpected_slot_ids": unexpected,
            "missing_review_receipt_slots": missing_review_receipts,
            "invalid_evidence": invalid,
            "portfolio_receipt_count": len(list(paths["portfolio_receipts"].glob("*.json"))),
            "portfolio_roles": sorted(portfolio_roles),
            "portfolio_invalid": portfolio_invalid,
            "next_gate": next_gate,
        }
        return report
    except Phase0ArtifactError as exc:
        return {
            "schema_version": "question-bank-v20-phase0-gate-report.v1",
            "status": "BLOCKED",
            "error": str(exc),
            **exc.report,
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {
            "schema_version": "question-bank-v20-phase0-gate-report.v1",
            "status": "BLOCKED",
            "error": str(exc),
        }


def build_and_freeze_phase0_artifacts(project_root: Path | str) -> dict[str, Any]:
    """Build all Phase 0 artifacts only after every gate is satisfied.

    The function never writes a partial inventory or a non-authorizing manifest.
    """
    root = Path(project_root)
    report = collect_phase0_report(root)
    if report.get("status") != "PASS":
        raise Phase0ArtifactError("Phase 0 is not complete", report=report)

    paths = _paths(root)
    graph = load_graph(paths["graph"])
    architecture = load_and_validate(paths["architecture"], paths["graph"])
    contract = slot_brief_inventory.validate_contract(_load_json(paths["contract"]))
    review_policy = slot_brief_review.load_policy(paths["review_policy"])
    review_policy_sha = slot_brief_review.policy_digest(review_policy)
    plans = _expected_plans(root, architecture, graph, contract, review_policy_sha)
    briefs, receipts_by_slot, invalid = _reviewed_briefs_and_receipts(
        root,
        architecture=architecture,
        graph=graph,
        contract=contract,
        review_policy=review_policy,
        expected_slot_ids=set(plans),
    )
    if invalid:
        raise Phase0ArtifactError("invalid Phase 0 evidence", report={"invalid_evidence": invalid})
    inventory = _build_inventory(
        architecture=architecture,
        graph=graph,
        contract=contract,
        review_policy_sha256=review_policy_sha,
        briefs=briefs,
        expected_slot_ids=set(plans),
    )
    summary = _build_review_summary(inventory=inventory, receipts_by_slot=receipts_by_slot)
    portfolio_receipts = [
        slot_portfolio_review.validate_portfolio_receipt(_load_json(path))
        for path in sorted(paths["portfolio_receipts"].glob("*.json"))
    ]
    slot_portfolio_review.assert_portfolio_review_ready(
        inventory=inventory,
        architecture=architecture,
        graph=graph,
        review_policy_sha256=review_policy_sha,
        receipts=portfolio_receipts,
    )
    slots = [
        {
            "slot_id": brief["slot_id"],
            "brief_sha256": brief["brief_sha256"],
            "review_receipt_set_sha256": brief["review_evidence"]["receipt_set_sha256"],
        }
        for brief in inventory["slots"]
    ]
    reviewed_manifest = slot_manifest.build_slot_manifest(
        status="REVIEWED",
        planned_slot_count=inventory["planned_slot_count"],
        graph_sha256=inventory["graph_sha256"],
        architecture_sha256=inventory["architecture_sha256"],
        brief_inventory_sha256=inventory["inventory_sha256"],
        review_policy_sha256=review_policy_sha,
        distribution_matrix_sha256=sha256_json(architecture["distribution_matrix"]),
        slots=slots,
    )
    frozen_manifest = slot_manifest.build_slot_manifest(
        status="FROZEN",
        planned_slot_count=reviewed_manifest["planned_slot_count"],
        graph_sha256=reviewed_manifest["graph_sha256"],
        architecture_sha256=reviewed_manifest["architecture_sha256"],
        brief_inventory_sha256=reviewed_manifest["brief_inventory_sha256"],
        review_policy_sha256=reviewed_manifest["review_policy_sha256"],
        distribution_matrix_sha256=reviewed_manifest["distribution_matrix_sha256"],
        slots=reviewed_manifest["slots"],
    )
    slot_manifest.assert_slot_manifest_transition(reviewed_manifest, frozen_manifest)
    outer_reviewed = v20_bank_namespace.build_manifest(
        status="REVIEWED",
        planned_slot_count=inventory["planned_slot_count"],
        graph_version=architecture["graph_source"]["version"],
        graph_sha256=inventory["graph_sha256"],
        architecture_sha256=inventory["architecture_sha256"],
    )
    outer_frozen = v20_bank_namespace.build_manifest(
        status="FROZEN",
        planned_slot_count=inventory["planned_slot_count"],
        graph_version=architecture["graph_source"]["version"],
        graph_sha256=inventory["graph_sha256"],
        architecture_sha256=inventory["architecture_sha256"],
        slot_manifest_sha256=frozen_manifest["slot_manifest_sha256"],
    )
    v20_bank_namespace.assert_manifest_transition(outer_reviewed, outer_frozen)
    for relative, value in ((INVENTORY_PATH, inventory), (SUMMARY_PATH, summary), (SLOT_MANIFEST_PATH, frozen_manifest)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    (root / SLOT_MANIFEST_SHA_PATH).write_text(frozen_manifest["slot_manifest_sha256"] + "\n", encoding="utf-8")
    outer_path = root / v20_bank_namespace.V20_NAMESPACE / "question_bank_manifest_v20.json"
    outer_path.write_text(canonical_json(outer_frozen) + "\n", encoding="utf-8")
    return {
        "status": "FROZEN",
        "manifest": frozen_manifest,
        "outer_manifest": outer_frozen,
        "inventory": inventory,
        "summary": summary,
    }
