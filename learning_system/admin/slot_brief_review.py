"""Receipt and gate contract for v20 slot-brief review."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .slot_architecture import architecture_content_digest, graph_content_digest
from .slot_architecture_review import assert_reviewed_artifact
from .slot_brief_inventory import (
    BRIEF_SCHEMA_VERSION,
    SlotBriefInventoryError,
    load_graph_node_ids_from_graph,
    validate_brief,
)
from .v20_receipts import SHA256_PATTERN, canonical_json, sha256_json


REVIEW_SCHEMA_VERSION = "question-slot-brief-review-receipt.v20"
POLICY_SCHEMA_VERSION = "question-slot-brief-review-policy.v20"
RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "review_scope",
        "slot_id",
        "review_kind",
        "review_focus",
        "reviewer_role",
        "brief_sha256",
        "architecture_sha256",
        "graph_sha256",
        "policy_sha256",
        "input_packet_sha256",
        "invocation_id",
        "raw_response_ref",
        "raw_response_sha256",
        "created_at",
        "tool_version",
        "verdict",
        "confidence",
        "findings",
        "receipt_digest_sha256",
    }
)
VERDICTS = frozenset({"PASS", "PASS_WITH_SCOPE", "NEEDS_FIX"})
REVIEW_KINDS = frozenset({"lead_consistency", "targeted_critic"})
REVIEW_ROLES = frozenset(
    {
        "slot_lead_consistency",
        "math_education_architect",
        "assessment_architect",
        "child_learning_reviewer",
        "collision_reviewer",
    }
)
FINDING_FIELDS = frozenset({"code", "severity", "detail", "recommendation"})


class SlotBriefReviewError(ValueError):
    pass


def load_policy(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotBriefReviewError(f"unable to load slot review policy: {path}") from exc
    return validate_policy(value)


def validate_policy(policy: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "policy_version",
        "accepted_verdicts",
        "rejected_verdicts",
        "minimum_confidence",
        "lead",
        "targeted_critic",
        "receipt_rules",
    }
    if not isinstance(policy, dict) or set(policy) != required:
        raise SlotBriefReviewError("slot review policy fields are incomplete or unknown")
    if policy["schema_version"] != POLICY_SCHEMA_VERSION:
        raise SlotBriefReviewError("unsupported slot review policy")
    if set(policy["accepted_verdicts"]) != {"PASS", "PASS_WITH_SCOPE"}:
        raise SlotBriefReviewError("slot review accepted verdicts are invalid")
    if set(policy["rejected_verdicts"]) != {"NEEDS_FIX"}:
        raise SlotBriefReviewError("slot review rejected verdicts are invalid")
    confidence = policy["minimum_confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)):
        raise SlotBriefReviewError("slot review minimum confidence is invalid")
    if not 0 <= float(confidence) <= 1:
        raise SlotBriefReviewError("slot review minimum confidence is out of range")
    if policy["lead"] != {
        "required": True,
        "exactly_one_per_slot": True,
        "review_kind": "lead_consistency",
    }:
        raise SlotBriefReviewError("lead review policy is invalid")
    targeted = policy["targeted_critic"]
    if not isinstance(targeted, dict) or targeted.get("review_kind") != "targeted_critic":
        raise SlotBriefReviewError("targeted critic policy is invalid")
    rules = policy["receipt_rules"]
    if not isinstance(rules, dict) or any(rules.get(key) is not True for key in (
        "distinct_invocation_required",
        "all_hashes_must_match_current_artifacts",
        "brief_only_no_concrete_question",
    )):
        raise SlotBriefReviewError("slot review receipt rules are invalid")
    return deepcopy(policy)


def policy_digest(policy: dict[str, Any]) -> str:
    return sha256_json(validate_policy(policy))


def validate_findings(findings: Any) -> list[dict[str, str]]:
    if not isinstance(findings, list) or any(
        not isinstance(item, dict) or set(item) != FINDING_FIELDS
        or any(not isinstance(item[field], str) for field in FINDING_FIELDS)
        for item in findings
    ):
        raise SlotBriefReviewError("review findings must use the strict finding schema")
    return deepcopy(findings)


def brief_content_digest(brief: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in brief.items()
            if key not in {"brief_sha256", "status", "review_evidence"}
        }
    )


def _review_evidence_shape(brief: dict[str, Any]) -> dict[str, Any]:
    evidence = brief.get("review_evidence")
    if not isinstance(evidence, dict) or set(evidence) != {"receipt_set_sha256", "receipt_ids"}:
        raise SlotBriefReviewError("brief review evidence is incomplete or unknown")
    receipt_set = evidence["receipt_set_sha256"]
    receipt_ids = evidence["receipt_ids"]
    if receipt_set != "" and not SHA256_PATTERN.fullmatch(receipt_set):
        raise SlotBriefReviewError("brief review evidence receipt set digest is invalid")
    if not isinstance(receipt_ids, list) or any(not isinstance(item, str) or not item.strip() for item in receipt_ids):
        raise SlotBriefReviewError("brief review evidence receipt ids are invalid")
    if brief.get("status") == "DRAFT" and (receipt_set or receipt_ids):
        raise SlotBriefReviewError("DRAFT brief cannot contain review evidence")
    if brief.get("status") == "REVIEWED" and (not receipt_set or not receipt_ids):
        raise SlotBriefReviewError("REVIEWED brief requires review evidence")
    return deepcopy(evidence)


def _has_hard_blocker(receipt: dict[str, Any]) -> bool:
    return any(item.get("severity") in {"P0", "P1"} for item in receipt["findings"])


def _targeted_critic_reasons(brief: dict[str, Any]) -> set[str]:
    design = brief["design"]
    reasons: set[str] = set()
    if design["risk_tier"] in {"R2", "R3"}:
        reasons.add("risk_tier_R2_or_R3")
    if design["response_modality"] == "visual_interactive":
        reasons.add("visual_or_external_resource")
    if design["review_route_class"] in {"targeted_critic", "collision_escalation", "coverage_escalation"}:
        reasons.add("collision_or_coverage_escalation")
    return reasons


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SlotBriefReviewError(f"{field} must be nonempty")
    return value


def _safe_receipt_id(value: Any) -> str:
    value = _text(value, "receipt_id")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise SlotBriefReviewError("receipt_id must be a safe filename component")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise SlotBriefReviewError(f"{field} must be a SHA-256 digest")
    return value


def build_review_receipt(
    *,
    brief: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    policy: dict[str, Any],
    review_kind: str,
    review_focus: str,
    reviewer_role: str,
    invocation_id: str,
    input_packet_sha256: str,
    raw_response_ref: str,
    raw_response_sha256: str,
    created_at: str,
    tool_version: str,
    verdict: str,
    confidence: float,
    findings: list[dict[str, Any]],
    receipt_id: str = "",
) -> dict[str, Any]:
    validate_policy(policy)
    if review_kind not in REVIEW_KINDS or reviewer_role not in REVIEW_ROLES:
        raise SlotBriefReviewError("invalid slot review kind or role")
    if review_kind == "lead_consistency" and reviewer_role != "slot_lead_consistency":
        raise SlotBriefReviewError("lead consistency must use the lead reviewer role")
    if review_kind == "targeted_critic" and reviewer_role == "slot_lead_consistency":
        raise SlotBriefReviewError("lead role cannot emit targeted critic receipt")
    if verdict not in VERDICTS:
        raise SlotBriefReviewError("invalid slot review verdict")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)):
        raise SlotBriefReviewError("slot review confidence is invalid")
    if not 0 <= float(confidence) <= 1:
        raise SlotBriefReviewError("slot review confidence is out of range")
    validate_findings(findings)
    _text(brief["slot_id"], "slot_id")
    _sha(input_packet_sha256, "input_packet_sha256")
    _sha(raw_response_sha256, "raw_response_sha256")
    _text(raw_response_ref, "raw_response_ref")
    _text(created_at, "created_at")
    _text(tool_version, "tool_version")
    receipt = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "receipt_id": receipt_id or "",
        "review_scope": "slot_brief_only",
        "slot_id": brief["slot_id"],
        "review_kind": review_kind,
        "review_focus": _text(review_focus, "review_focus"),
        "reviewer_role": reviewer_role,
        "brief_sha256": brief_content_digest(brief),
        "architecture_sha256": architecture_content_digest(architecture),
        "graph_sha256": graph_content_digest(graph),
        "policy_sha256": policy_digest(policy),
        "input_packet_sha256": input_packet_sha256,
        "invocation_id": _text(invocation_id, "invocation_id"),
        "raw_response_ref": raw_response_ref,
        "raw_response_sha256": raw_response_sha256,
        "created_at": created_at,
        "tool_version": tool_version,
        "verdict": verdict,
        "confidence": float(confidence),
        "findings": deepcopy(findings),
    }
    if not receipt["receipt_id"]:
        receipt["receipt_id"] = "brief-review-" + sha256_json(
            {"slot_id": brief["slot_id"], "role": reviewer_role, "invocation": invocation_id}
        )[:24]
    receipt["receipt_digest_sha256"] = sha256_json(receipt)
    return receipt


def validate_review_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise SlotBriefReviewError("slot review receipt fields are incomplete or unknown")
    if receipt["schema_version"] != REVIEW_SCHEMA_VERSION:
        raise SlotBriefReviewError("unsupported slot brief review receipt")
    _safe_receipt_id(receipt["receipt_id"])
    _text(receipt["review_scope"], "review_scope")
    if receipt["review_scope"] != "slot_brief_only":
        raise SlotBriefReviewError("review receipt scope is invalid")
    if receipt["review_kind"] not in REVIEW_KINDS or receipt["reviewer_role"] not in REVIEW_ROLES:
        raise SlotBriefReviewError("review receipt kind or role is invalid")
    if receipt["review_kind"] == "lead_consistency" and receipt["reviewer_role"] != "slot_lead_consistency":
        raise SlotBriefReviewError("lead consistency must use the lead reviewer role")
    if receipt["review_kind"] == "targeted_critic" and receipt["reviewer_role"] == "slot_lead_consistency":
        raise SlotBriefReviewError("lead role cannot emit targeted critic receipt")
    for field in (
        "brief_sha256",
        "architecture_sha256",
        "graph_sha256",
        "policy_sha256",
        "input_packet_sha256",
        "raw_response_sha256",
    ):
        _sha(receipt[field], field)
    for field in ("slot_id", "review_focus", "invocation_id", "raw_response_ref", "created_at", "tool_version"):
        _text(receipt[field], field)
    if receipt["verdict"] not in VERDICTS:
        raise SlotBriefReviewError("review receipt verdict is invalid")
    if isinstance(receipt["confidence"], bool) or not isinstance(receipt["confidence"], (int, float)) or not math.isfinite(float(receipt["confidence"])):
        raise SlotBriefReviewError("review receipt confidence is invalid")
    if not 0 <= float(receipt["confidence"]) <= 1:
        raise SlotBriefReviewError("review receipt confidence is out of range")
    validate_findings(receipt["findings"])
    claimed = _sha(receipt["receipt_digest_sha256"], "receipt_digest_sha256")
    if claimed != sha256_json({key: value for key, value in receipt.items() if key != "receipt_digest_sha256"}):
        raise SlotBriefReviewError("review receipt digest does not match content")
    return deepcopy(receipt)


def assert_raw_response_artifact(receipt: dict[str, Any], *, base_dir: Path | str) -> None:
    """Verify that a receipt points to an intact immutable raw response."""
    checked = validate_review_receipt(receipt)
    base = Path(base_dir).resolve()
    raw_ref = Path(checked["raw_response_ref"])
    raw_path = (base / raw_ref).resolve()
    # Older v20 receipts used a project-relative path. Keep the path
    # resolution explicit and bounded while accepting that already-persisted
    # artifact form; new receipts remain base-relative.
    if not raw_path.exists() and raw_ref.parts[:4] == ("data", "question_banks", "v20", "slot_brief_review_raw"):
        raw_path = (base.parents[2] / raw_ref).resolve()
    try:
        raw_path.relative_to(base)
    except ValueError as exc:
        raise SlotBriefReviewError("review receipt raw response escapes v20 namespace") from exc
    try:
        artifact = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotBriefReviewError("review receipt raw response artifact is missing or invalid") from exc
    if not isinstance(artifact, dict) or set(artifact) != {
        "schema_version", "slot_id", "attempt", "stage", "input_packet_sha256", "response_sha256", "response"
    }:
        raise SlotBriefReviewError("review receipt raw response artifact shape is invalid")
    if artifact["slot_id"] != checked["slot_id"]:
        raise SlotBriefReviewError("review receipt raw response slot mismatch")
    if artifact["input_packet_sha256"] != checked["input_packet_sha256"]:
        raise SlotBriefReviewError("review receipt raw response packet mismatch")
    if artifact["response_sha256"] != checked["raw_response_sha256"]:
        raise SlotBriefReviewError("review receipt raw response digest mismatch")
    if sha256_json(artifact["response"]) != checked["raw_response_sha256"]:
        raise SlotBriefReviewError("review receipt raw response content was altered")


def assert_review_packet_artifact(
    receipt: dict[str, Any], *, brief: dict[str, Any], packet_dir: Path | str
) -> None:
    """Verify receipt packet hash, role, focus and brief content together."""
    checked = validate_review_receipt(receipt)
    directory = Path(packet_dir).resolve()
    expected_brief_digest = brief_content_digest(brief)
    for path in directory.glob(f"{checked['slot_id']}-*.json"):
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if sha256_json(packet) != checked["input_packet_sha256"]:
            continue
        if not isinstance(packet, dict) or packet.get("reviewer_role") != checked["reviewer_role"]:
            continue
        if packet.get("review_focus") != checked["review_focus"]:
            continue
        packet_brief = packet.get("brief")
        if not isinstance(packet_brief, dict) or brief_content_digest(packet_brief) != expected_brief_digest:
            continue
        return
    raise SlotBriefReviewError("review receipt packet content is missing or not bound to the brief")


def assert_brief_review_ready(
    *,
    brief: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    policy: dict[str, Any],
    review_policy_sha256: str,
    receipts: list[dict[str, Any]],
    architecture_review_policy: dict[str, Any],
    architecture_receipts: list[dict[str, Any]],
) -> None:
    if brief["status"] != "DRAFT":
        raise SlotBriefReviewError("only DRAFT brief can enter review")
    if review_policy_sha256 != policy_digest(policy):
        raise SlotBriefReviewError("slot review policy hash does not match policy")
    if architecture.get("status") not in {"REVIEWED", "FROZEN"}:
        raise SlotBriefReviewError("reviewed architecture is required")
    try:
        assert_reviewed_artifact(
            architecture=architecture,
            graph=graph,
            policy=architecture_review_policy,
            receipts=architecture_receipts,
        )
    except Exception as exc:
        raise SlotBriefReviewError("architecture review evidence is not valid") from exc
    validate_brief(
        brief,
        graph_node_ids=load_graph_node_ids_from_graph(graph),
        graph=graph,
        architecture=architecture,
        contract=contract,
        review_policy_sha256=review_policy_sha256,
    )
    _review_evidence_shape(brief)
    expected = {
        "brief_sha256": brief_content_digest(brief),
        "architecture_sha256": architecture_content_digest(architecture),
        "graph_sha256": graph_content_digest(graph),
        "policy_sha256": policy_digest(policy),
    }
    if not isinstance(receipts, list) or not receipts:
        raise SlotBriefReviewError("exactly one lead consistency receipt is required")
    validated = [validate_review_receipt(receipt) for receipt in receipts]
    for receipt in validated:
        for field, value in expected.items():
            if receipt[field] != value:
                raise SlotBriefReviewError(f"brief review {field} is stale")
        if receipt["slot_id"] != brief["slot_id"]:
            raise SlotBriefReviewError("brief review slot_id mismatch")
        if receipt["confidence"] < float(policy["minimum_confidence"]):
            raise SlotBriefReviewError("brief review confidence is below policy")
        if receipt["verdict"] not in set(policy["accepted_verdicts"]):
            raise SlotBriefReviewError("brief review has not passed")
        if _has_hard_blocker(receipt):
            raise SlotBriefReviewError("brief review contains a P0/P1 finding")
    leads = [receipt for receipt in validated if receipt["review_kind"] == "lead_consistency"]
    if len(leads) != 1 or leads[0]["reviewer_role"] != "slot_lead_consistency":
        raise SlotBriefReviewError("exactly one lead consistency receipt is required")
    invocations = [receipt["invocation_id"] for receipt in validated]
    if len(invocations) != len(set(invocations)):
        raise SlotBriefReviewError("brief review invocations must be distinct")
    if len({receipt["receipt_id"] for receipt in validated}) != len(validated):
        raise SlotBriefReviewError("brief review receipt ids must be unique")
    targeted = [receipt for receipt in validated if receipt["review_kind"] == "targeted_critic"]
    required_reasons = _targeted_critic_reasons(brief)
    if leads[0]["confidence"] < 0.90:
        required_reasons.add("lead_uncertainty")
    if required_reasons and not targeted:
        raise SlotBriefReviewError(
            "targeted critic receipt is required: " + ",".join(sorted(required_reasons))
        )


def mark_brief_reviewed(**kwargs: Any) -> dict[str, Any]:
    assert_brief_review_ready(**kwargs)
    reviewed = deepcopy(kwargs["brief"])
    reviewed["status"] = "REVIEWED"
    receipts = [validate_review_receipt(receipt) for receipt in kwargs["receipts"]]
    reviewed["review_evidence"] = {
        "receipt_set_sha256": sha256_json(
            [
                {
                    "receipt_id": receipt["receipt_id"],
                    "receipt_digest_sha256": receipt["receipt_digest_sha256"],
                }
                for receipt in sorted(receipts, key=lambda item: item["receipt_id"])
            ]
        ),
        "receipt_ids": sorted(receipt["receipt_id"] for receipt in receipts),
    }
    reviewed["brief_sha256"] = brief_content_digest(reviewed)
    return reviewed


def assert_reviewed_brief_evidence(
    *,
    brief: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    policy: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> None:
    """Re-verify an already REVIEWED brief before inventory or freeze.

    This is intentionally separate from ``assert_brief_review_ready`` because
    the latter accepts only a DRAFT entering review. Freeze-time authorization
    must validate the persisted REVIEWED evidence again.
    """
    validate_policy(policy)
    if brief.get("status") != "REVIEWED":
        raise SlotBriefReviewError("brief must be REVIEWED")
    evidence = _review_evidence_shape(brief)
    expected = {
        "brief_sha256": brief_content_digest(brief),
        "architecture_sha256": architecture_content_digest(architecture),
        "graph_sha256": graph_content_digest(graph),
        "policy_sha256": policy_digest(policy),
    }
    validated = [validate_review_receipt(receipt) for receipt in receipts]
    if not validated:
        raise SlotBriefReviewError("reviewed brief requires review receipts")
    for receipt in validated:
        for field, value in expected.items():
            if receipt[field] != value:
                raise SlotBriefReviewError(f"reviewed brief {field} is stale")
        if receipt["slot_id"] != brief["slot_id"]:
            raise SlotBriefReviewError("reviewed brief receipt slot mismatch")
        if receipt["confidence"] < float(policy["minimum_confidence"]):
            raise SlotBriefReviewError("reviewed brief confidence is below policy")
        if receipt["verdict"] not in set(policy["accepted_verdicts"]):
            raise SlotBriefReviewError("reviewed brief receipt has not passed")
        if _has_hard_blocker(receipt):
            raise SlotBriefReviewError("reviewed brief receipt contains a P0/P1 finding")
    leads = [receipt for receipt in validated if receipt["review_kind"] == "lead_consistency"]
    if len(leads) != 1 or leads[0]["reviewer_role"] != "slot_lead_consistency":
        raise SlotBriefReviewError("exactly one lead consistency receipt is required")
    if len({receipt["invocation_id"] for receipt in validated}) != len(validated):
        raise SlotBriefReviewError("reviewed brief invocations must be distinct")
    if len({receipt["receipt_id"] for receipt in validated}) != len(validated):
        raise SlotBriefReviewError("reviewed brief receipt ids must be unique")
    required_reasons = _targeted_critic_reasons(brief)
    if leads[0]["confidence"] < 0.90:
        required_reasons.add("lead_uncertainty")
    targeted = [receipt for receipt in validated if receipt["review_kind"] == "targeted_critic"]
    if required_reasons and not targeted:
        raise SlotBriefReviewError(
            "targeted critic receipt is required: " + ",".join(sorted(required_reasons))
        )
    actual_receipt_set = sha256_json(
        [
            {
                "receipt_id": receipt["receipt_id"],
                "receipt_digest_sha256": receipt["receipt_digest_sha256"],
            }
            for receipt in sorted(validated, key=lambda item: item["receipt_id"])
        ]
    )
    if evidence["receipt_set_sha256"] != actual_receipt_set:
        raise SlotBriefReviewError("reviewed brief receipt set digest is stale")
    if set(evidence["receipt_ids"]) != {receipt["receipt_id"] for receipt in validated}:
        raise SlotBriefReviewError("reviewed brief receipt ids do not match evidence")


class AppendOnlySlotBriefReviewStore:
    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def append(self, receipt: dict[str, Any]) -> Path:
        receipt = validate_review_receipt(receipt)
        self.directory.mkdir(parents=True, exist_ok=True)
        logical_identity = (
            receipt["brief_sha256"],
            receipt["architecture_sha256"],
            receipt["graph_sha256"],
            receipt["policy_sha256"],
            receipt["slot_id"],
            receipt["review_kind"],
            receipt["reviewer_role"],
            receipt["invocation_id"],
        )
        for existing_path in self.directory.glob("*.json"):
            try:
                existing = validate_review_receipt(
                    json.loads(existing_path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, SlotBriefReviewError) as exc:
                raise SlotBriefReviewError(
                    f"corrupt slot brief review receipt store: {existing_path}"
                ) from exc
            existing_identity = (
                existing["brief_sha256"],
                existing["architecture_sha256"],
                existing["graph_sha256"],
                existing["policy_sha256"],
                existing["slot_id"],
                existing["review_kind"],
                existing["reviewer_role"],
                existing["invocation_id"],
            )
            if existing_identity == logical_identity:
                raise FileExistsError("duplicate slot brief review invocation")
        # The final receipt path is the concurrency key. A separate claim file
        # could survive a process crash between claim and receipt publication
        # and permanently block recovery.
        path = self.directory / f"identity-{sha256_json(logical_identity)}.json"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(canonical_json(receipt))
                handle.write("\n")
        except FileExistsError as exc:
            raise FileExistsError("duplicate slot brief review invocation") from exc
        return path
