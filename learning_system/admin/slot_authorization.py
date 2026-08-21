"""Independent authorization for one reviewed v20 question slot.

Full-bank activation remains a separate, stricter transaction. This contract
lets a reviewed slot produce one concrete question while the rest of the
inventory is still being designed or reviewed.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import slot_architecture, slot_brief_inventory, slot_brief_review
from .slot_architecture_review import load_policy as load_architecture_review_policy
from .slot_architecture_review import validate_review_receipt as validate_architecture_receipt
from .v20_receipts import SHA256_PATTERN, sha256_json


SCHEMA_VERSION = "question-slot-authorization.v20"
AUTHORIZATION_KIND = "reviewed_slot_concrete_production"
CONCRETE_POLICY = {
    "schema_version": "question-concrete-production-policy.v20",
    "one_slot_one_candidate_version": True,
    "generation_is_single_question": True,
    "review_route_is_brief_risk_driven": True,
    "staging_is_serial_and_append_only": True,
}


class SlotAuthorizationError(PermissionError):
    pass


def concrete_policy_digest() -> str:
    return sha256_json(CONCRETE_POLICY)


def authorization_digest(authorization: dict[str, Any]) -> str:
    return sha256_json(
        {key: value for key, value in authorization.items() if key != "authorization_digest"}
    )


def validate_authorization(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "authorization_kind", "campaign_id", "slot_id",
        "operation_key", "brief_sha256", "brief_review_receipt_set_sha256",
        "graph_sha256", "architecture_sha256", "review_policy_sha256",
        "concrete_policy_sha256", "authorization_digest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise SlotAuthorizationError("slot authorization fields are incomplete or unknown")
    if value["schema_version"] != SCHEMA_VERSION or value["authorization_kind"] != AUTHORIZATION_KIND:
        raise SlotAuthorizationError("unsupported slot authorization")
    for field in fields - {
        "schema_version", "authorization_kind", "campaign_id", "slot_id",
        "operation_key", "authorization_digest",
    }:
        if not isinstance(value[field], str) or not SHA256_PATTERN.fullmatch(value[field]):
            raise SlotAuthorizationError(f"slot authorization {field} is invalid")
    for field in ("campaign_id", "slot_id", "operation_key", "authorization_digest"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise SlotAuthorizationError(f"slot authorization {field} is required")
    if value["operation_key"] != f"v20:{value['slot_id']}":
        raise SlotAuthorizationError("slot authorization operation key is invalid")
    if value["concrete_policy_sha256"] != concrete_policy_digest():
        raise SlotAuthorizationError("slot authorization concrete policy is stale")
    if value["authorization_digest"] != authorization_digest(value):
        raise SlotAuthorizationError("slot authorization digest does not match content")
    return deepcopy(value)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotAuthorizationError(f"unable to load authorization artifact: {path}") from exc
    if not isinstance(value, dict):
        raise SlotAuthorizationError(f"authorization artifact must be an object: {path}")
    return value


def _brief_receipts(root: Path, slot_id: str, brief_sha256: str) -> list[dict[str, Any]]:
    directory = root / "data/question_banks/v20/slot_brief_review_receipts"
    receipts: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        receipt = slot_brief_review.validate_review_receipt(_load_json(path))
        if receipt["slot_id"] == slot_id and receipt["brief_sha256"] == brief_sha256:
            receipts.append(receipt)
    return receipts


def authorize_slot(
    project_root: Path | str,
    slot_id: str,
    *,
    campaign_id: str = "v20-slot-production",
) -> dict[str, Any]:
    """Build and validate an authorization for exactly one reviewed slot."""
    root = Path(project_root)
    if not isinstance(slot_id, str) or not slot_id.strip():
        raise SlotAuthorizationError("slot_id is required")

    graph_path = root / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
    architecture_path = root / "data/question_banks/v20/slot_architecture_v20.json"
    architecture = slot_architecture.load_and_validate(architecture_path, graph_path)
    graph = slot_architecture.load_graph(graph_path)
    architecture_policy = load_architecture_review_policy(
        root / "data/question_banks/v20/slot_architecture_review_policy_v20.json"
    )
    architecture_receipts = [
        validate_architecture_receipt(_load_json(path))
        for path in sorted((root / "data/question_banks/v20/slot_architecture_receipts").glob("*.json"))
    ]
    try:
        slot_architecture.assert_brief_authorized(
            architecture,
            graph=graph,
            policy=architecture_policy,
            receipts=architecture_receipts,
        )
    except Exception as exc:
        raise SlotAuthorizationError("architecture review evidence is not accepted") from exc

    brief_path = root / "data/question_banks/v20/slot_brief_reviewed" / f"{slot_id}.json"
    brief = _load_json(brief_path)
    review_policy = slot_brief_review.load_policy(
        root / "data/question_banks/v20/slot_brief_review_policy_v20.json"
    )
    contract = slot_brief_inventory.validate_contract(
        _load_json(root / "data/question_banks/v20/slot_brief_generation_contract_v20.json")
    )
    graph_digest = slot_architecture.graph_content_digest(graph)
    architecture_digest = slot_architecture.architecture_content_digest(architecture)
    review_policy_sha256 = slot_brief_review.policy_digest(review_policy)
    try:
        slot_brief_inventory.validate_brief(
            brief,
            graph_node_ids=slot_brief_inventory.load_graph_node_ids_from_graph(graph),
            architecture=architecture,
            graph=graph,
            contract=contract,
            review_policy_sha256=review_policy_sha256,
        )
        receipts = _brief_receipts(root, slot_id, brief["brief_sha256"])
        slot_brief_review.assert_reviewed_brief_evidence(
            brief=brief,
            architecture=architecture,
            graph=graph,
            policy=review_policy,
            receipts=receipts,
        )
    except Exception as exc:
        raise SlotAuthorizationError(f"reviewed brief evidence is not accepted for {slot_id}") from exc

    lineage = brief.get("lineage")
    if not isinstance(lineage, dict):
        raise SlotAuthorizationError("reviewed brief lineage is missing")
    if lineage.get("graph_sha256") != graph_digest or lineage.get("architecture_sha256") != architecture_digest:
        raise SlotAuthorizationError("reviewed brief graph or architecture lineage is stale")
    authorization = {
        "schema_version": SCHEMA_VERSION,
        "authorization_kind": AUTHORIZATION_KIND,
        "campaign_id": campaign_id,
        "slot_id": slot_id,
        "operation_key": f"v20:{slot_id}",
        "brief_sha256": brief["brief_sha256"],
        "brief_review_receipt_set_sha256": brief["review_evidence"]["receipt_set_sha256"],
        "graph_sha256": graph_digest,
        "architecture_sha256": architecture_digest,
        "review_policy_sha256": review_policy_sha256,
        "concrete_policy_sha256": concrete_policy_digest(),
        "authorization_digest": "",
    }
    authorization["authorization_digest"] = authorization_digest(authorization)
    return validate_authorization(authorization)


def assert_slot_authorized(
    authorization: dict[str, Any], *, project_root: Path | str, brief: dict[str, Any]
) -> dict[str, Any]:
    """Rebuild current evidence and reject a stale or cross-slot authorization."""
    checked = validate_authorization(authorization)
    if checked["slot_id"] != brief.get("slot_id") or checked["brief_sha256"] != brief.get("brief_sha256"):
        raise SlotAuthorizationError("slot authorization does not match brief")
    current = authorize_slot(project_root, checked["slot_id"], campaign_id=checked["campaign_id"])
    if current != checked:
        raise SlotAuthorizationError("slot authorization is stale or has been tampered with")
    return checked


def as_production_manifest(authorization: dict[str, Any]) -> dict[str, Any]:
    """Expose the slot authorization digest through the existing identity field."""
    checked = validate_authorization(authorization)
    return {
        "manifest_sha256": checked["authorization_digest"],
        "slot_manifest_sha256": checked["authorization_digest"],
        "slot_authorization": checked,
    }
