"""Fail-closed architecture review receipts for question-bank v20."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .slot_architecture import (
    SlotArchitectureError,
    architecture_content_digest,
    graph_content_digest,
    validate_architecture,
)
from .v20_receipts import SHA256_PATTERN, canonical_json, sha256_json


REVIEW_SCHEMA_VERSION = "question-slot-architecture-review-receipt.v20"
POLICY_SCHEMA_VERSION = "question-slot-architecture-review-policy.v20"
REVIEW_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "architecture_digest_sha256",
        "graph_digest_sha256",
        "policy_digest_sha256",
        "reviewer_role",
        "invocation_id",
        "input_packet_sha256",
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
REVIEW_ROLES = frozenset(
    {
        "math_education_architect",
        "assessment_architect",
        "child_learning_reviewer",
    }
)
VERDICTS = frozenset({"PASS", "PASS_WITH_SCOPE", "NEEDS_FIX"})


class ArchitectureReviewError(ValueError):
    """Raised when architecture review evidence is missing or inconsistent."""


def load_policy(path: Path | str) -> dict[str, Any]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchitectureReviewError(f"unable to load review policy: {path}") from exc
    return validate_policy(policy)


def validate_policy(policy: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "policy_version",
        "required_lenses",
        "accepted_verdicts",
        "rejected_verdicts",
        "minimum_confidence",
        "require_distinct_invocations",
        "require_exactly_one_receipt_per_lens",
        "review_is_unanimous",
    }
    if not isinstance(policy, dict) or set(policy) != required:
        raise ArchitectureReviewError("review policy fields are incomplete or unknown")
    if policy["schema_version"] != POLICY_SCHEMA_VERSION:
        raise ArchitectureReviewError("unsupported architecture review policy")
    if not isinstance(policy["policy_version"], str) or not policy["policy_version"].strip():
        raise ArchitectureReviewError("policy_version must be nonempty")
    if (
        not isinstance(policy["required_lenses"], list)
        or len(policy["required_lenses"]) != len(REVIEW_ROLES)
        or set(policy["required_lenses"]) != REVIEW_ROLES
    ):
        raise ArchitectureReviewError("required_lenses must contain the three approved lenses")
    if set(policy["accepted_verdicts"]) != {"PASS", "PASS_WITH_SCOPE"}:
        raise ArchitectureReviewError("accepted_verdicts must allow PASS and PASS_WITH_SCOPE")
    if set(policy["rejected_verdicts"]) != {"NEEDS_FIX"}:
        raise ArchitectureReviewError("rejected_verdicts must contain NEEDS_FIX")
    confidence = policy["minimum_confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ArchitectureReviewError("minimum_confidence must be numeric")
    if not math.isfinite(float(confidence)):
        raise ArchitectureReviewError("minimum_confidence must be finite")
    if not 0 <= float(confidence) <= 1:
        raise ArchitectureReviewError("minimum_confidence must be between zero and one")
    for key in (
        "require_distinct_invocations",
        "require_exactly_one_receipt_per_lens",
        "review_is_unanimous",
    ):
        if policy[key] is not True:
            raise ArchitectureReviewError(f"{key} must be true")
    return deepcopy(policy)


def policy_digest(policy: dict[str, Any]) -> str:
    return sha256_json(validate_policy(policy))


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArchitectureReviewError(f"{field} must be nonempty")
    return value


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ArchitectureReviewError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_receipt_id(value: Any) -> str:
    value = _require_text(value, "receipt_id")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ArchitectureReviewError("receipt_id must be a safe filename component")
    return value


def build_review_receipt(
    *,
    architecture: dict[str, Any],
    graph: dict[str, Any],
    policy: dict[str, Any],
    reviewer_role: str,
    invocation_id: str,
    raw_response_sha256: str,
    verdict: str,
    confidence: float,
    findings: list[dict[str, Any]],
    input_packet_sha256: str,
    raw_response_ref: str,
    created_at: str,
    tool_version: str,
    receipt_id: str = "",
) -> dict[str, Any]:
    validate_policy(policy)
    if reviewer_role not in REVIEW_ROLES:
        raise ArchitectureReviewError("reviewer_role is not an approved architecture lens")
    verdict = _require_text(verdict, "verdict")
    if verdict not in VERDICTS:
        raise ArchitectureReviewError("unsupported architecture review verdict")
    invocation_id = _require_text(invocation_id, "invocation_id")
    raw_response_sha256 = _require_sha256(raw_response_sha256, "raw_response_sha256")
    input_packet_sha256 = _require_sha256(input_packet_sha256, "input_packet_sha256")
    raw_response_ref = _require_text(raw_response_ref, "raw_response_ref")
    created_at = _require_text(created_at, "created_at")
    tool_version = _require_text(tool_version, "tool_version")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ArchitectureReviewError("confidence must be numeric")
    if not math.isfinite(float(confidence)):
        raise ArchitectureReviewError("confidence must be finite")
    if not 0 <= float(confidence) <= 1:
        raise ArchitectureReviewError("confidence must be between zero and one")
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise ArchitectureReviewError("findings must be a list of objects")
    receipt = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "receipt_id": _require_receipt_id(receipt_id) if receipt_id else "",
        "architecture_digest_sha256": architecture_content_digest(architecture),
        "graph_digest_sha256": graph_content_digest(graph),
        "policy_digest_sha256": policy_digest(policy),
        "reviewer_role": reviewer_role,
        "invocation_id": invocation_id,
        "input_packet_sha256": input_packet_sha256,
        "raw_response_ref": raw_response_ref,
        "raw_response_sha256": raw_response_sha256,
        "created_at": created_at,
        "tool_version": tool_version,
        "verdict": verdict,
        "confidence": float(confidence),
        "findings": deepcopy(findings),
    }
    if not receipt["receipt_id"]:
        receipt["receipt_id"] = "architecture-" + sha256_json(
            {"role": reviewer_role, "invocation": invocation_id}
        )[:24]
    receipt["receipt_digest_sha256"] = sha256_json(receipt)
    return receipt


def validate_review_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or set(receipt) != REVIEW_RECEIPT_FIELDS:
        raise ArchitectureReviewError("architecture review receipt fields are incomplete or unknown")
    if receipt["schema_version"] != REVIEW_SCHEMA_VERSION:
        raise ArchitectureReviewError("unsupported architecture review receipt")
    _require_receipt_id(receipt["receipt_id"])
    for field in (
        "architecture_digest_sha256",
        "graph_digest_sha256",
        "policy_digest_sha256",
        "input_packet_sha256",
        "raw_response_sha256",
    ):
        _require_sha256(receipt[field], field)
    if receipt["reviewer_role"] not in REVIEW_ROLES:
        raise ArchitectureReviewError("unknown architecture reviewer role")
    _require_text(receipt["invocation_id"], "invocation_id")
    _require_sha256(receipt["input_packet_sha256"], "input_packet_sha256")
    _require_text(receipt["raw_response_ref"], "raw_response_ref")
    _require_text(receipt["created_at"], "created_at")
    _require_text(receipt["tool_version"], "tool_version")
    if receipt["verdict"] not in VERDICTS:
        raise ArchitectureReviewError("unsupported architecture review verdict")
    confidence = receipt["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ArchitectureReviewError("confidence must be numeric")
    if not math.isfinite(float(confidence)):
        raise ArchitectureReviewError("confidence must be finite")
    if not 0 <= float(confidence) <= 1:
        raise ArchitectureReviewError("confidence must be between zero and one")
    if not isinstance(receipt["findings"], list) or any(
        not isinstance(item, dict) for item in receipt["findings"]
    ):
        raise ArchitectureReviewError("findings must be a list of objects")
    claimed = _require_sha256(receipt["receipt_digest_sha256"], "receipt_digest_sha256")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest_sha256"}
    if claimed != sha256_json(body):
        raise ArchitectureReviewError("receipt_digest_sha256 does not match canonical content")
    return deepcopy(receipt)


def assert_review_ready(
    *,
    architecture: dict[str, Any],
    graph: dict[str, Any],
    policy: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> None:
    """Require one accepted, high-confidence receipt from every lens."""
    validate_policy(policy)
    validate_architecture(
        architecture,
        graph_node_ids={str(node["id"]) for node in graph.get("nodes", [])},
        graph_prerequisite_edges=graph.get("prerequisite_edges"),
        graph_digest=expected_graph_digest(graph),
    )
    expected_architecture = architecture_content_digest(architecture)
    expected_graph = graph_content_digest(graph)
    expected_policy = policy_digest(policy)
    if not isinstance(receipts, list):
        raise ArchitectureReviewError("architecture review receipts must be a list")
    validated = [validate_review_receipt(receipt) for receipt in receipts]
    by_role: dict[str, dict[str, Any]] = {}
    invocations: set[str] = set()
    for receipt in validated:
        if receipt["architecture_digest_sha256"] != expected_architecture:
            raise ArchitectureReviewError("review receipt architecture digest mismatch")
        if receipt["graph_digest_sha256"] != expected_graph:
            raise ArchitectureReviewError("review receipt graph digest mismatch")
        if receipt["policy_digest_sha256"] != expected_policy:
            raise ArchitectureReviewError("review receipt policy digest mismatch")
        role = receipt["reviewer_role"]
        if role in by_role:
            raise ArchitectureReviewError("duplicate architecture review lens")
        if receipt["invocation_id"] in invocations:
            raise ArchitectureReviewError("architecture reviews must use distinct invocations")
        by_role[role] = receipt
        invocations.add(receipt["invocation_id"])
    required = set(policy["required_lenses"])
    if set(by_role) != required:
        raise ArchitectureReviewError("all three architecture review lenses are required")
    minimum = float(policy["minimum_confidence"])
    for receipt in validated:
        if receipt["verdict"] not in set(policy["accepted_verdicts"]):
            raise ArchitectureReviewError("architecture review has not passed unanimously")
        if receipt["confidence"] < minimum:
            raise ArchitectureReviewError("architecture review confidence is below policy minimum")


def expected_graph_digest(graph: dict[str, Any]) -> str:
    return graph_content_digest(graph)


def review_set_digest(receipts: list[dict[str, Any]]) -> str:
    validated = [validate_review_receipt(receipt) for receipt in receipts]
    return sha256_json(
        [
            {
                "receipt_id": receipt["receipt_id"],
                "receipt_digest_sha256": receipt["receipt_digest_sha256"],
            }
            for receipt in sorted(validated, key=lambda item: item["receipt_id"])
        ]
    )


def assert_reviewed_artifact(
    *,
    architecture: dict[str, Any],
    graph: dict[str, Any],
    policy: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> None:
    if architecture.get("status") not in {"REVIEWED", "FROZEN"}:
        raise ArchitectureReviewError("architecture is not reviewed")
    evidence = architecture.get("review_evidence")
    if not isinstance(evidence, dict):
        raise ArchitectureReviewError("review evidence is missing")
    assert_review_ready(
        architecture=architecture,
        graph=graph,
        policy=policy,
        receipts=receipts,
    )
    validated = [validate_review_receipt(receipt) for receipt in receipts]
    if evidence.get("receipt_set_sha256") != review_set_digest(validated):
        raise ArchitectureReviewError("review receipt set digest mismatch")
    expected_ids = sorted(receipt["receipt_id"] for receipt in validated)
    if evidence.get("receipt_ids") != expected_ids:
        raise ArchitectureReviewError("review receipt set membership mismatch")
    if evidence.get("architecture_digest_sha256") != architecture_content_digest(architecture):
        raise ArchitectureReviewError("review evidence architecture digest mismatch")
    if evidence.get("graph_digest_sha256") != validated[0]["graph_digest_sha256"]:
        raise ArchitectureReviewError("review evidence graph digest mismatch")
    if evidence.get("policy_digest_sha256") != validated[0]["policy_digest_sha256"]:
        raise ArchitectureReviewError("review evidence policy digest mismatch")
    if len(expected_ids) != len(set(expected_ids)):
        raise ArchitectureReviewError("review receipt set contains duplicate receipt ids")


def mark_reviewed(
    *,
    architecture: dict[str, Any],
    graph: dict[str, Any],
    policy: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a reviewed architecture only after all review evidence passes."""
    if architecture.get("status") != "DRAFT":
        raise ArchitectureReviewError("only DRAFT architecture can transition to REVIEWED")
    assert_review_ready(
        architecture=architecture,
        graph=graph,
        policy=policy,
        receipts=receipts,
    )
    reviewed = deepcopy(architecture)
    reviewed["status"] = "REVIEWED"
    reviewed["review_evidence"] = {
        "receipt_set_sha256": review_set_digest(receipts),
        "receipt_ids": sorted(receipt["receipt_id"] for receipt in receipts),
        "architecture_digest_sha256": architecture_content_digest(architecture),
        "graph_digest_sha256": graph_content_digest(graph),
        "policy_digest_sha256": policy_digest(policy),
    }
    assert_reviewed_artifact(
        architecture=reviewed,
        graph=graph,
        policy=policy,
        receipts=receipts,
    )
    return reviewed


class AppendOnlyArchitectureReviewStore:
    """Persist review evidence with exclusive file creation."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def append(self, receipt: dict[str, Any]) -> Path:
        receipt = validate_review_receipt(receipt)
        self.directory.mkdir(parents=True, exist_ok=True)
        logical_identity = (
            receipt["architecture_digest_sha256"],
            receipt["graph_digest_sha256"],
            receipt["policy_digest_sha256"],
            receipt["reviewer_role"],
            receipt["invocation_id"],
        )
        for existing_path in self.directory.glob("*.json"):
            try:
                existing = validate_review_receipt(
                    json.loads(existing_path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, ArchitectureReviewError) as exc:
                raise ArchitectureReviewError(
                    f"corrupt architecture review receipt store: {existing_path}"
                ) from exc
            existing_identity = (
                existing["architecture_digest_sha256"],
                existing["graph_digest_sha256"],
                existing["policy_digest_sha256"],
                existing["reviewer_role"],
                existing["invocation_id"],
            )
            if existing_identity == logical_identity:
                raise FileExistsError("duplicate architecture review invocation")
        claim_id = sha256_json(logical_identity)
        claim_path = self.directory / f"identity-{claim_id}.claim"
        try:
            with claim_path.open("x", encoding="utf-8") as handle:
                handle.write(canonical_json(logical_identity))
                handle.write("\n")
        except FileExistsError as exc:
            raise FileExistsError("duplicate architecture review invocation") from exc
        path = self.directory / (
            f"{receipt['reviewer_role']}-{receipt['receipt_id']}-"
            f"{receipt['receipt_digest_sha256'][:16]}.json"
        )
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(canonical_json(receipt))
                handle.write("\n")
        except Exception:
            claim_path.unlink(missing_ok=True)
            raise
        return path
