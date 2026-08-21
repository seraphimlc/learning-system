"""Whole-inventory review contract for v20 slot briefs."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .slot_architecture import architecture_content_digest, graph_content_digest
from .slot_brief_inventory import inventory_digest
from .v20_receipts import SHA256_PATTERN, canonical_json, sha256_json


PORTFOLIO_SCHEMA_VERSION = "question-slot-portfolio-review-receipt.v20"
REQUIRED_ROLES = frozenset(
    {"math_education_architect", "assessment_architect", "child_learning_reviewer"}
)
VERDICTS = frozenset({"PASS", "PASS_WITH_SCOPE", "NEEDS_FIX"})
RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "review_scope",
        "reviewer_role",
        "inventory_sha256",
        "architecture_sha256",
        "graph_sha256",
        "review_policy_sha256",
        "slot_set_sha256",
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


class SlotPortfolioReviewError(ValueError):
    pass


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SlotPortfolioReviewError(f"{field} must be nonempty")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise SlotPortfolioReviewError(f"{field} must be a SHA-256 digest")
    return value


def slot_set_digest(inventory: dict[str, Any]) -> str:
    slots = inventory.get("slots")
    if not isinstance(slots, list):
        raise SlotPortfolioReviewError("portfolio inventory slots must be a list")
    normalized = []
    for slot in slots:
        if not isinstance(slot, dict):
            raise SlotPortfolioReviewError("portfolio slot must be an object")
        for field in ("slot_id", "brief_sha256", "review_receipt_set_sha256"):
            _text(slot.get(field), f"slot.{field}")
        normalized.append(
            {
                "slot_id": slot["slot_id"],
                "brief_sha256": slot["brief_sha256"],
                "review_receipt_set_sha256": slot["review_receipt_set_sha256"],
            }
        )
    return sha256_json(sorted(normalized, key=lambda item: item["slot_id"]))


def build_portfolio_receipt(
    *,
    inventory: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    review_policy_sha256: str,
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
    if reviewer_role not in REQUIRED_ROLES:
        raise SlotPortfolioReviewError("unknown portfolio reviewer role")
    if verdict not in VERDICTS:
        raise SlotPortfolioReviewError("invalid portfolio verdict")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)):
        raise SlotPortfolioReviewError("portfolio confidence is invalid")
    if not 0 <= float(confidence) <= 1:
        raise SlotPortfolioReviewError("portfolio confidence is out of range")
    for field, value in {
        "review_policy_sha256": review_policy_sha256,
        "input_packet_sha256": input_packet_sha256,
        "raw_response_sha256": raw_response_sha256,
    }.items():
        _sha(value, field)
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise SlotPortfolioReviewError("portfolio findings must be objects")
    receipt = {
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "receipt_id": receipt_id or "",
        "review_scope": "slot_portfolio",
        "reviewer_role": reviewer_role,
        "inventory_sha256": inventory_digest(inventory),
        "architecture_sha256": architecture_content_digest(architecture),
        "graph_sha256": graph_content_digest(graph),
        "review_policy_sha256": review_policy_sha256,
        "slot_set_sha256": slot_set_digest(inventory),
        "input_packet_sha256": input_packet_sha256,
        "invocation_id": _text(invocation_id, "invocation_id"),
        "raw_response_ref": _text(raw_response_ref, "raw_response_ref"),
        "raw_response_sha256": raw_response_sha256,
        "created_at": _text(created_at, "created_at"),
        "tool_version": _text(tool_version, "tool_version"),
        "verdict": verdict,
        "confidence": float(confidence),
        "findings": deepcopy(findings),
    }
    receipt["receipt_id"] = receipt["receipt_id"] or "portfolio-review-" + sha256_json(
        {"role": reviewer_role, "invocation": invocation_id}
    )[:24]
    receipt["receipt_digest_sha256"] = sha256_json(receipt)
    return receipt


def validate_portfolio_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise SlotPortfolioReviewError("portfolio receipt fields are incomplete or unknown")
    if receipt["schema_version"] != PORTFOLIO_SCHEMA_VERSION:
        raise SlotPortfolioReviewError("unsupported portfolio receipt")
    if receipt["review_scope"] != "slot_portfolio":
        raise SlotPortfolioReviewError("portfolio receipt scope is invalid")
    if receipt["reviewer_role"] not in REQUIRED_ROLES:
        raise SlotPortfolioReviewError("portfolio reviewer role is invalid")
    for field in (
        "inventory_sha256",
        "architecture_sha256",
        "graph_sha256",
        "review_policy_sha256",
        "slot_set_sha256",
        "input_packet_sha256",
        "raw_response_sha256",
        "receipt_digest_sha256",
    ):
        _sha(receipt[field], field)
    for field in ("receipt_id", "invocation_id", "raw_response_ref", "created_at", "tool_version"):
        _text(receipt[field], field)
    if receipt["verdict"] not in VERDICTS:
        raise SlotPortfolioReviewError("portfolio verdict is invalid")
    if isinstance(receipt["confidence"], bool) or not isinstance(receipt["confidence"], (int, float)) or not math.isfinite(float(receipt["confidence"])):
        raise SlotPortfolioReviewError("portfolio confidence is invalid")
    if not 0 <= float(receipt["confidence"]) <= 1:
        raise SlotPortfolioReviewError("portfolio confidence is out of range")
    if not isinstance(receipt["findings"], list) or any(not isinstance(item, dict) for item in receipt["findings"]):
        raise SlotPortfolioReviewError("portfolio findings are invalid")
    claimed = receipt["receipt_digest_sha256"]
    if claimed != sha256_json({key: value for key, value in receipt.items() if key != "receipt_digest_sha256"}):
        raise SlotPortfolioReviewError("portfolio receipt digest does not match content")
    return deepcopy(receipt)


def assert_portfolio_review_ready(
    *,
    inventory: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    review_policy_sha256: str,
    receipts: list[dict[str, Any]],
) -> None:
    if inventory.get("status") not in {"REVIEWED", "FROZEN"}:
        raise SlotPortfolioReviewError("slot portfolio must be REVIEWED before portfolio acceptance")
    expected = {
        "inventory_sha256": inventory_digest(inventory),
        "architecture_sha256": architecture_content_digest(architecture),
        "graph_sha256": graph_content_digest(graph),
        "review_policy_sha256": review_policy_sha256,
        "slot_set_sha256": slot_set_digest(inventory),
    }
    if not isinstance(receipts, list):
        raise SlotPortfolioReviewError("portfolio receipts must be a list")
    validated = [validate_portfolio_receipt(receipt) for receipt in receipts]
    by_role: dict[str, dict[str, Any]] = {}
    invocations: set[str] = set()
    for receipt in validated:
        if any(receipt[field] != value for field, value in expected.items()):
            raise SlotPortfolioReviewError("portfolio receipt lineage is stale")
        if receipt["reviewer_role"] in by_role:
            raise SlotPortfolioReviewError("portfolio reviewer roles must be unique")
        if receipt["invocation_id"] in invocations:
            raise SlotPortfolioReviewError("portfolio invocations must be distinct")
        if receipt["verdict"] not in {"PASS", "PASS_WITH_SCOPE"}:
            raise SlotPortfolioReviewError("portfolio review has not passed unanimously")
        if receipt["confidence"] < 0.86:
            raise SlotPortfolioReviewError("portfolio confidence is below policy")
        if any(item.get("severity") in {"P0", "P1"} for item in receipt["findings"]):
            raise SlotPortfolioReviewError("portfolio review contains a P0/P1 finding")
        by_role[receipt["reviewer_role"]] = receipt
        invocations.add(receipt["invocation_id"])
    if set(by_role) != REQUIRED_ROLES:
        raise SlotPortfolioReviewError("all three portfolio review lenses are required")
