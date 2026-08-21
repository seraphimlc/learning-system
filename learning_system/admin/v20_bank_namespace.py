"""Fail-closed namespace and manifest contracts for question-bank v20."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .v20_receipts import SHA256_PATTERN, canonical_json, sha256_json


V20_SCHEMA_VERSION = "question-bank-manifest.v20"
V20_BANK_VERSION = "v20"
V20_NAMESPACE = "data/question_banks/v20"
MIN_PLANNED_SLOT_COUNT = 900
MAX_PLANNED_SLOT_COUNT = 1100
MANIFEST_STATUSES = frozenset({"DRAFT", "REVIEWED", "FROZEN"})
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "bank_version",
        "namespace",
        "manifest_id",
        "status",
        "planned_slot_count",
        "graph_version",
        "graph_sha256",
        "architecture_sha256",
        "slot_manifest_sha256",
        "manifest_sha256",
    }
)
AUTHORIZATION_OPERATIONS = frozenset(
    {"queue", "candidate", "concrete_generation"}
)


class ManifestAuthorizationError(PermissionError):
    pass


def manifest_path(project_root: Path | str) -> Path:
    return Path(project_root) / V20_NAMESPACE / "question_bank_manifest_v20.json"


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _require_sha256_or_empty(value: Any, field: str) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be empty or a lowercase SHA-256 digest")
    return value


def _manifest_body(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }


def manifest_digest(manifest: dict[str, Any]) -> str:
    return sha256_json(_manifest_body(manifest))


def build_manifest(
    *,
    status: str = "DRAFT",
    planned_slot_count: int = 960,
    graph_version: str = "math_knowledge_graph_v2",
    graph_sha256: str = "",
    architecture_sha256: str = "",
    slot_manifest_sha256: str = "",
    manifest_id: str = "question-bank-manifest-v20",
) -> dict[str, Any]:
    manifest = {
        "schema_version": V20_SCHEMA_VERSION,
        "bank_version": V20_BANK_VERSION,
        "namespace": V20_NAMESPACE,
        "manifest_id": manifest_id,
        "status": status,
        "planned_slot_count": planned_slot_count,
        "graph_version": graph_version,
        "graph_sha256": graph_sha256,
        "architecture_sha256": architecture_sha256,
        "slot_manifest_sha256": slot_manifest_sha256,
        "manifest_sha256": "",
    }
    validate_manifest(manifest, require_digest=False)
    if status == "FROZEN":
        for field in ("slot_manifest_sha256", "graph_sha256", "architecture_sha256"):
            if not manifest[field]:
                raise ValueError(f"FROZEN manifest requires {field}")
    manifest["manifest_sha256"] = manifest_digest(manifest)
    return manifest


def validate_manifest(
    manifest: Any,
    *,
    require_digest: bool = True,
) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ValueError("v20 manifest fields are incomplete or contain unknown fields")
    if manifest["schema_version"] != V20_SCHEMA_VERSION:
        raise ValueError("unsupported v20 manifest schema version")
    if manifest["bank_version"] != V20_BANK_VERSION:
        raise ValueError("v20 manifest bank_version mismatch")
    if manifest["namespace"] != V20_NAMESPACE:
        raise ValueError("v20 manifest namespace mismatch")
    _require_text(manifest["manifest_id"], "manifest_id")
    if manifest["status"] not in MANIFEST_STATUSES:
        raise ValueError("v20 manifest status must be DRAFT, REVIEWED or FROZEN")
    count = manifest["planned_slot_count"]
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError("planned_slot_count must be an integer")
    if not MIN_PLANNED_SLOT_COUNT <= count <= MAX_PLANNED_SLOT_COUNT:
        raise ValueError("planned_slot_count must be between 900 and 1100")
    _require_text(manifest["graph_version"], "graph_version")
    _require_sha256_or_empty(manifest["graph_sha256"], "graph_sha256")
    _require_sha256_or_empty(manifest["architecture_sha256"], "architecture_sha256")
    _require_sha256_or_empty(manifest["slot_manifest_sha256"], "slot_manifest_sha256")
    if manifest["status"] == "FROZEN":
        for field in ("slot_manifest_sha256", "graph_sha256", "architecture_sha256"):
            if not manifest[field]:
                raise ValueError(f"FROZEN manifest requires {field}")
    if require_digest:
        claimed = manifest["manifest_sha256"]
        if not isinstance(claimed, str) or not SHA256_PATTERN.fullmatch(claimed):
            raise ValueError("manifest_sha256 must be a lowercase SHA-256 digest")
        if claimed != manifest_digest(manifest):
            raise ValueError("manifest_sha256 does not match canonical manifest content")
    return deepcopy(manifest)


def load_manifest(path: Path | str) -> dict[str, Any]:
    manifest_path_value = Path(path)
    try:
        manifest = json.loads(manifest_path_value.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load v20 manifest: {manifest_path_value}") from exc
    return validate_manifest(manifest)


def assert_authorized(
    manifest: dict[str, Any],
    operation: str,
    *,
    expected_graph_sha256: str | None = None,
    expected_architecture_sha256: str | None = None,
    expected_slot_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    if operation not in AUTHORIZATION_OPERATIONS:
        raise ValueError(f"unsupported v20 authorization operation: {operation}")
    validated = validate_manifest(manifest)
    if validated["status"] != "FROZEN":
        raise ManifestAuthorizationError(
            f"v20 {operation} authorization requires a FROZEN manifest"
        )
    expected = {
        "graph_sha256": expected_graph_sha256,
        "architecture_sha256": expected_architecture_sha256,
        "slot_manifest_sha256": expected_slot_manifest_sha256,
    }
    for field, actual_expected in expected.items():
        if actual_expected is None:
            raise ManifestAuthorizationError(
                f"v20 {operation} authorization requires {field} from the real artifact"
            )
        if not isinstance(actual_expected, str) or not SHA256_PATTERN.fullmatch(actual_expected):
            raise ManifestAuthorizationError(f"invalid expected {field}")
        if validated[field] != actual_expected:
            raise ManifestAuthorizationError(f"v20 manifest {field} does not match artifact")
    return validated


def project_artifact_contract(project_root: Path | str) -> dict[str, Any]:
    """Load and cross-check every artifact required for production authorization."""
    root = Path(project_root)
    graph_path = root / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
    architecture_path = root / V20_NAMESPACE / "slot_architecture_v20.json"
    slot_manifest_path = root / V20_NAMESPACE / "slot_manifest_v20.json"
    brief_inventory_path = root / V20_NAMESPACE / "slot_briefs_v20.json"
    slot_review_summary_path = root / V20_NAMESPACE / "slot_review_summary_v20.json"
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        architecture = json.loads(architecture_path.read_text(encoding="utf-8"))
        slot_manifest = json.loads(slot_manifest_path.read_text(encoding="utf-8"))
        brief_inventory = json.loads(brief_inventory_path.read_text(encoding="utf-8"))
        slot_review_summary = json.loads(slot_review_summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestAuthorizationError(
            "real v20 graph, architecture and slot manifest artifacts are required"
        ) from exc
    from .slot_architecture import load_and_validate, architecture_content_digest, graph_content_digest
    from .slot_architecture_review import (
        ArchitectureReviewError,
        assert_reviewed_artifact,
        load_policy,
        policy_digest,
        validate_review_receipt,
    )
    from .slot_manifest import load_slot_manifest, slot_manifest_digest
    from . import slot_brief_inventory, slot_brief_review, slot_portfolio_review

    try:
        validated_architecture = load_and_validate(architecture_path, graph_path)
        validated_slot_manifest = load_slot_manifest(slot_manifest_path, require_frozen=True)
        contract = slot_brief_inventory.validate_contract(
            json.loads((root / V20_NAMESPACE / "slot_brief_generation_contract_v20.json").read_text(encoding="utf-8"))
        )
        slot_review_policy = slot_brief_review.load_policy(
            root / V20_NAMESPACE / "slot_brief_review_policy_v20.json"
        )
        slot_review_policy_sha = slot_brief_review.policy_digest(slot_review_policy)
        validated_inventory = slot_brief_inventory.validate_inventory(
            brief_inventory,
            architecture=validated_architecture,
            graph=graph,
            contract=contract,
            review_policy_sha256=slot_review_policy_sha,
        )
        if validated_inventory["status"] not in {"REVIEWED", "FROZEN"}:
            raise ManifestAuthorizationError("slot brief inventory must be REVIEWED before authorization")
        slot_receipt_dir = root / V20_NAMESPACE / "slot_brief_review_receipts"
        slot_receipts_by_id: dict[str, list[dict[str, Any]]] = {}
        for slot_receipt_path in sorted(slot_receipt_dir.glob("*.json")):
            slot_receipt = slot_brief_review.validate_review_receipt(
                json.loads(slot_receipt_path.read_text(encoding="utf-8"))
            )
            slot_receipts_by_id.setdefault(slot_receipt["slot_id"], []).append(slot_receipt)
        inventory_slot_ids = {brief["slot_id"] for brief in validated_inventory["slots"]}
        receipt_slot_ids = set(slot_receipts_by_id)
        if receipt_slot_ids != inventory_slot_ids:
            raise ManifestAuthorizationError(
                "slot review receipt slot set must exactly match reviewed brief inventory"
            )
        for brief in validated_inventory["slots"]:
            slot_brief_review.assert_reviewed_brief_evidence(
                brief=brief,
                architecture=validated_architecture,
                graph=graph,
                policy=slot_review_policy,
                receipts=slot_receipts_by_id.get(brief["slot_id"], []),
            )
        policy = load_policy(root / V20_NAMESPACE / "slot_architecture_review_policy_v20.json")
        receipt_dir = root / V20_NAMESPACE / "slot_architecture_receipts"
        receipt_paths = sorted(receipt_dir.glob("*.json"))
        receipts = [
            validate_review_receipt(json.loads(path.read_text(encoding="utf-8")))
            for path in receipt_paths
        ]
        assert_reviewed_artifact(
            architecture=validated_architecture,
            graph=graph,
            policy=policy,
            receipts=receipts,
        )
    except (OSError, json.JSONDecodeError, ValueError, ArchitectureReviewError) as exc:
        raise ManifestAuthorizationError(
            "architecture receipts and frozen slot manifest must pass full validation"
        ) from exc

    architecture_digest = architecture_content_digest(validated_architecture)
    graph_digest = graph_content_digest(graph)
    slot_manifest_digest_value = slot_manifest_digest(validated_slot_manifest)
    if validated_slot_manifest["architecture_sha256"] != architecture_digest:
        raise ManifestAuthorizationError("slot manifest architecture binding is stale")
    if validated_slot_manifest["graph_sha256"] != graph_digest:
        raise ManifestAuthorizationError("slot manifest graph binding is stale")
    if validated_slot_manifest["planned_slot_count"] != validated_architecture["capacity"]["planned_slot_count"]:
        raise ManifestAuthorizationError("slot manifest and architecture counts do not match")
    if sha256_json(brief_inventory) != validated_slot_manifest["brief_inventory_sha256"]:
        raise ManifestAuthorizationError("slot brief inventory binding is stale")
    if policy_digest(slot_review_policy) != validated_slot_manifest["review_policy_sha256"]:
        raise ManifestAuthorizationError("slot review policy binding is stale")
    if sha256_json(validated_architecture["distribution_matrix"]) != validated_slot_manifest["distribution_matrix_sha256"]:
        raise ManifestAuthorizationError("slot distribution matrix binding is stale")
    summary_slots = slot_review_summary.get("slots") if isinstance(slot_review_summary, dict) else None
    if not isinstance(slot_review_summary, dict) or slot_review_summary.get("schema_version") != "question-slot-review-summary.v20":
        raise ManifestAuthorizationError("slot review summary schema is invalid")
    summary_claimed = slot_review_summary.get("summary_sha256")
    if summary_claimed != sha256_json({key: value for key, value in slot_review_summary.items() if key != "summary_sha256"}):
        raise ManifestAuthorizationError("slot review summary digest is stale")
    if slot_review_summary.get("inventory_sha256") != validated_inventory["inventory_sha256"]:
        raise ManifestAuthorizationError("slot review summary inventory binding is stale")
    if not isinstance(summary_slots, list) or len(summary_slots) != validated_slot_manifest["planned_slot_count"]:
        raise ManifestAuthorizationError("slot review summary is incomplete")
    expected_slot_evidence = {
        (slot["slot_id"], slot["brief_sha256"], slot["review_receipt_set_sha256"])
        for slot in validated_slot_manifest["slots"]
    }
    actual_slot_evidence = {
        (slot.get("slot_id"), slot.get("brief_sha256"), slot.get("review_receipt_set_sha256"))
        for slot in summary_slots
        if isinstance(slot, dict)
    }
    if actual_slot_evidence != expected_slot_evidence:
        raise ManifestAuthorizationError("slot review summary does not match slot evidence")
    portfolio_dir = root / V20_NAMESPACE / "slot_portfolio_review_receipts"
    portfolio_receipts = [
        slot_portfolio_review.validate_portfolio_receipt(
            json.loads(path.read_text(encoding="utf-8"))
        )
        for path in sorted(portfolio_dir.glob("*.json"))
    ]
    try:
        slot_portfolio_review.assert_portfolio_review_ready(
            inventory=validated_inventory,
            architecture=validated_architecture,
            graph=graph,
            review_policy_sha256=slot_review_policy_sha,
            receipts=portfolio_receipts,
        )
    except (ValueError, slot_portfolio_review.SlotPortfolioReviewError) as exc:
        raise ManifestAuthorizationError("slot portfolio review is not accepted") from exc

    return {
        "graph_sha256": graph_digest,
        "architecture_sha256": architecture_digest,
        "slot_manifest_sha256": slot_manifest_digest_value,
        "planned_slot_count": validated_slot_manifest["planned_slot_count"],
        "graph_version": validated_architecture["graph_source"]["version"],
    }


def project_artifact_hashes(project_root: Path | str) -> dict[str, str]:
    contract = project_artifact_contract(project_root)
    return {
        key: contract[key]
        for key in ("graph_sha256", "architecture_sha256", "slot_manifest_sha256")
    }


def assert_project_authorized(
    manifest: dict[str, Any],
    operation: str,
    project_root: Path | str,
) -> dict[str, Any]:
    """Authorize only against hashes read from the current project checkout."""
    contract = project_artifact_contract(project_root)
    validated = assert_authorized(
        manifest,
        operation,
        expected_graph_sha256=contract["graph_sha256"],
        expected_architecture_sha256=contract["architecture_sha256"],
        expected_slot_manifest_sha256=contract["slot_manifest_sha256"],
    )
    if validated["planned_slot_count"] != contract["planned_slot_count"]:
        raise ManifestAuthorizationError("outer manifest and slot manifest counts do not match")
    if validated["graph_version"] != contract["graph_version"]:
        raise ManifestAuthorizationError("outer manifest and architecture graph versions differ")
    return validated


def authorize_queue(manifest: dict[str, Any], project_root: Path | str) -> dict[str, Any]:
    return assert_project_authorized(manifest, "queue", project_root)


def authorize_candidate(manifest: dict[str, Any], project_root: Path | str) -> dict[str, Any]:
    return assert_project_authorized(manifest, "candidate", project_root)


def authorize_concrete_generation(manifest: dict[str, Any], project_root: Path | str) -> dict[str, Any]:
    return assert_project_authorized(manifest, "concrete_generation", project_root)


def is_authorized(manifest: dict[str, Any], operation: str, **expected: str) -> bool:
    try:
        assert_authorized(manifest, operation, **expected)
    except (ManifestAuthorizationError, ValueError):
        return False
    return True


def assert_manifest_transition(current: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Allow only the linear manifest lifecycle."""
    current = validate_manifest(current)
    target = validate_manifest(target)
    allowed = {"DRAFT": "REVIEWED", "REVIEWED": "FROZEN"}
    if allowed.get(current["status"]) != target["status"]:
        raise ManifestAuthorizationError(
            f"illegal v20 manifest transition: {current['status']} -> {target['status']}"
        )
    if current["manifest_id"] != target["manifest_id"]:
        raise ManifestAuthorizationError("manifest identity cannot change during transition")
    immutable_fields = (
        "bank_version",
        "namespace",
        "planned_slot_count",
        "graph_version",
        "graph_sha256",
        "architecture_sha256",
    )
    for field in immutable_fields:
        if current[field] != target[field]:
            raise ManifestAuthorizationError(
                f"manifest {field} cannot change during lifecycle transition"
            )
    return target
