"""Strict frozen slot-manifest contract used by v20 project authorization."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .v20_receipts import SHA256_PATTERN, sha256_json


SLOT_MANIFEST_SCHEMA_VERSION = "question-slot-manifest.v20"
SLOT_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "planned_slot_count",
        "graph_sha256",
        "architecture_sha256",
        "brief_inventory_sha256",
        "review_policy_sha256",
        "distribution_matrix_sha256",
        "slots",
        "slot_manifest_sha256",
    }
)
STATUSES = frozenset({"DRAFT", "REVIEWED", "FROZEN"})


class SlotManifestError(ValueError):
    pass


def slot_manifest_digest(manifest: dict[str, Any]) -> str:
    return sha256_json(
        {key: value for key, value in manifest.items() if key != "slot_manifest_sha256"}
    )


def validate_slot_manifest(manifest: Any, *, require_frozen: bool = False) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != SLOT_MANIFEST_FIELDS:
        raise SlotManifestError("slot manifest fields are incomplete or unknown")
    if manifest["schema_version"] != SLOT_MANIFEST_SCHEMA_VERSION:
        raise SlotManifestError("unsupported slot manifest schema")
    status = manifest["status"]
    if status not in STATUSES:
        raise SlotManifestError("slot manifest status is invalid")
    if require_frozen and status != "FROZEN":
        raise SlotManifestError("slot manifest must be FROZEN")
    count = manifest["planned_slot_count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 900 <= count <= 1100:
        raise SlotManifestError("slot manifest planned_slot_count is out of range")
    for field in ("graph_sha256", "architecture_sha256"):
        if not isinstance(manifest[field], str) or not SHA256_PATTERN.fullmatch(manifest[field]):
            raise SlotManifestError(f"slot manifest {field} is invalid")
    for field in (
        "brief_inventory_sha256",
        "review_policy_sha256",
        "distribution_matrix_sha256",
    ):
        if not isinstance(manifest[field], str) or not SHA256_PATTERN.fullmatch(manifest[field]):
            raise SlotManifestError(f"slot manifest {field} is invalid")
    slots = manifest["slots"]
    if not isinstance(slots, list) or len(slots) != count:
        raise SlotManifestError("slot manifest slots count does not match planned count")
    slot_ids: list[str] = []
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != {
            "slot_id",
            "brief_sha256",
            "review_receipt_set_sha256",
        }:
            raise SlotManifestError("slot manifest slot evidence is incomplete or unknown")
        slot_id = slot["slot_id"]
        if not isinstance(slot_id, str) or not slot_id.strip():
            raise SlotManifestError("slot manifest slot_id must be nonempty")
        for field in ("brief_sha256", "review_receipt_set_sha256"):
            if not isinstance(slot[field], str) or not SHA256_PATTERN.fullmatch(slot[field]):
                raise SlotManifestError(f"slot manifest slot {field} is invalid")
        slot_ids.append(slot_id)
    if len(set(slot_ids)) != len(slot_ids):
        raise SlotManifestError("slot manifest slot_ids must be unique")
    claimed = manifest["slot_manifest_sha256"]
    if not isinstance(claimed, str) or not SHA256_PATTERN.fullmatch(claimed):
        raise SlotManifestError("slot_manifest_sha256 is invalid")
    if claimed != slot_manifest_digest(manifest):
        raise SlotManifestError("slot_manifest_sha256 does not match content")
    return deepcopy(manifest)


def load_slot_manifest(path: Path | str, *, require_frozen: bool = False) -> dict[str, Any]:
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotManifestError(f"unable to load slot manifest: {path}") from exc
    return validate_slot_manifest(manifest, require_frozen=require_frozen)


def build_slot_manifest(
    *,
    status: str,
    planned_slot_count: int,
    graph_sha256: str,
    architecture_sha256: str,
    brief_inventory_sha256: str,
    review_policy_sha256: str,
    distribution_matrix_sha256: str,
    slots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a manifest from already validated Phase 0 evidence.

    This function deliberately does not infer completeness. Callers must first
    validate the inventory and review receipts, then choose the lifecycle state.
    """
    manifest = {
        "schema_version": SLOT_MANIFEST_SCHEMA_VERSION,
        "status": status,
        "planned_slot_count": planned_slot_count,
        "graph_sha256": graph_sha256,
        "architecture_sha256": architecture_sha256,
        "brief_inventory_sha256": brief_inventory_sha256,
        "review_policy_sha256": review_policy_sha256,
        "distribution_matrix_sha256": distribution_matrix_sha256,
        "slots": deepcopy(slots),
        "slot_manifest_sha256": "",
    }
    manifest["slot_manifest_sha256"] = slot_manifest_digest(manifest)
    return validate_slot_manifest(manifest)


def assert_slot_manifest_transition(
    current: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any]:
    """Allow only DRAFT -> REVIEWED -> FROZEN without changing evidence."""
    current = validate_slot_manifest(current)
    target = validate_slot_manifest(target)
    allowed = {"DRAFT": "REVIEWED", "REVIEWED": "FROZEN"}
    if allowed.get(current["status"]) != target["status"]:
        raise SlotManifestError(
            f"illegal slot manifest transition: {current['status']} -> {target['status']}"
        )
    immutable_fields = (
        "planned_slot_count",
        "graph_sha256",
        "architecture_sha256",
        "brief_inventory_sha256",
        "review_policy_sha256",
        "distribution_matrix_sha256",
        "slots",
    )
    for field in immutable_fields:
        if current[field] != target[field]:
            raise SlotManifestError(f"slot manifest {field} cannot change during transition")
    return target
