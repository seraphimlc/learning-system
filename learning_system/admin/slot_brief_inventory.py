"""Validation for the independent v20 slot-brief inventory."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .slot_architecture import (
    SlotArchitectureError,
    architecture_content_digest,
    graph_content_digest,
    load_graph,
    load_graph_node_ids,
    validate_architecture,
)
from .v20_receipts import SHA256_PATTERN, sha256_json


BRIEF_SCHEMA_VERSION = "question-slot-brief.v20"
INVENTORY_SCHEMA_VERSION = "question-slot-brief-inventory.v20"
CONTRACT_SCHEMA_VERSION = "question-slot-brief-generation-contract.v20"
INVENTORY_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "architecture_sha256",
        "graph_sha256",
        "review_policy_sha256",
        "generation_contract_sha256",
        "planned_slot_count",
        "slots",
        "inventory_sha256",
    }
)
BRIEF_FIELDS = frozenset(
    {
        "schema_version",
        "slot_id",
        "brief_version",
        "operation_key",
        "status",
        "lineage",
        "allocation",
        "graph_binding",
        "design",
        "measurement_intent",
        "variation_policy",
        "collision",
        "answer_contract_shape",
        "visual_authority",
        "review_evidence",
        "brief_sha256",
    }
)
STATUSES = frozenset({"DRAFT", "REVIEWED", "FROZEN"})
ALLOCATION_BUCKETS = frozenset(
    {
        "node_local_base",
        "high_impact_deepening",
        "cross_node_transfer",
        "application_context",
        "visual_interactive",
    }
)
FORBIDDEN_CONCRETE_KEYS = frozenset(
    {
        "question",
        "question_text",
        "stem",
        "prompt",
        "answer",
        "standard_answer",
        "solution",
        "scoring_points",
        "options",
        "numbers",
        "final_answer",
        "rubric",
        "candidate",
        "concrete_instance",
    }
)


class SlotBriefInventoryError(ValueError):
    pass


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotBriefInventoryError(f"unable to load JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SlotBriefInventoryError("expected a JSON object")
    return value


def contract_digest(contract: dict[str, Any]) -> str:
    return sha256_json(contract)


def inventory_digest(inventory: dict[str, Any]) -> str:
    return sha256_json(
        {key: value for key, value in inventory.items() if key != "inventory_sha256"}
    )


def brief_digest(brief: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in brief.items()
            if key not in {"brief_sha256", "status", "review_evidence"}
        }
    )


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SlotBriefInventoryError(f"{field} must be a nonempty string")


def _require_list(value: Any, field: str) -> None:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise SlotBriefInventoryError(f"{field} must be a nonempty list of strings")


def _reject_concrete_keys(value: Any, *, path: str = "brief") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_CONCRETE_KEYS:
                raise SlotBriefInventoryError(f"brief contains concrete question field: {path}.{key}")
            _reject_concrete_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_concrete_keys(nested, path=f"{path}[{index}]")


def build_slot_identity(ordinal: int) -> tuple[str, str]:
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise SlotBriefInventoryError("slot ordinal must be a positive integer")
    slot_id = f"V20-SLOT-{ordinal:04d}"
    return slot_id, f"v20:{slot_id}"


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise SlotBriefInventoryError("generation contract must be an object")
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise SlotBriefInventoryError("unsupported slot brief generation contract")
    for field in ("required_semantic_fields", "required_runtime_fields", "forbidden_concrete_fields"):
        _require_list(contract.get(field), field)
    semantic_bindings = contract.get("semantic_field_bindings")
    if not isinstance(semantic_bindings, dict) or set(semantic_bindings) != set(contract["required_semantic_fields"]):
        raise SlotBriefInventoryError("generation contract semantic bindings are incomplete")
    runtime_bindings = contract.get("runtime_field_bindings")
    if not isinstance(runtime_bindings, dict) or set(runtime_bindings) != set(contract["required_runtime_fields"]):
        raise SlotBriefInventoryError("generation contract runtime bindings are incomplete")
    if contract.get("production_mode") != "single_slot_model_generation":
        raise SlotBriefInventoryError("unsupported slot brief production mode")
    if contract.get("brief_schema_version") != BRIEF_SCHEMA_VERSION:
        raise SlotBriefInventoryError("generation contract brief schema mismatch")
    if contract.get("brief_is_not_a_question") is not True:
        raise SlotBriefInventoryError("brief contract must prohibit concrete questions")
    if contract.get("visual_without_authority") != "conditional_only":
        raise SlotBriefInventoryError("visual brief policy must be conditional_only")
    return deepcopy(contract)


def validate_brief(
    brief: Any,
    *,
    graph_node_ids: set[str],
    graph: dict[str, Any],
    architecture: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
) -> dict[str, Any]:
    if not isinstance(brief, dict):
        raise SlotBriefInventoryError("brief must be an object")
    _reject_concrete_keys(brief)
    if set(brief) != BRIEF_FIELDS:
        raise SlotBriefInventoryError("brief fields are incomplete or unknown")
    if brief["schema_version"] != BRIEF_SCHEMA_VERSION:
        raise SlotBriefInventoryError("unsupported slot brief schema")
    slot_id = brief["slot_id"]
    operation_key = brief["operation_key"]
    _require_text(slot_id, "slot_id")
    if not slot_id.startswith("V20-SLOT-"):
        raise SlotBriefInventoryError("slot_id must use the v20 slot namespace")
    if operation_key != f"v20:{slot_id}":
        raise SlotBriefInventoryError("operation_key must be derived from slot_id")
    version = brief["brief_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SlotBriefInventoryError("brief_version must be a positive integer")
    if brief["status"] not in STATUSES:
        raise SlotBriefInventoryError("brief status is invalid")
    review_evidence = brief["review_evidence"]
    if not isinstance(review_evidence, dict) or set(review_evidence) != {
        "receipt_set_sha256",
        "receipt_ids",
    }:
        raise SlotBriefInventoryError("brief review evidence is incomplete or unknown")
    if review_evidence["receipt_set_sha256"] != "" and not SHA256_PATTERN.fullmatch(
        review_evidence["receipt_set_sha256"]
    ):
        raise SlotBriefInventoryError("brief review evidence receipt set digest is invalid")
    if not isinstance(review_evidence["receipt_ids"], list) or any(
        not isinstance(item, str) or not item.strip() for item in review_evidence["receipt_ids"]
    ):
        raise SlotBriefInventoryError("brief review evidence receipt ids are invalid")
    if brief["status"] == "DRAFT" and (
        review_evidence["receipt_set_sha256"] or review_evidence["receipt_ids"]
    ):
        raise SlotBriefInventoryError("DRAFT brief cannot contain review evidence")
    if brief["status"] == "REVIEWED" and (
        not review_evidence["receipt_set_sha256"] or not review_evidence["receipt_ids"]
    ):
        raise SlotBriefInventoryError("REVIEWED brief requires review evidence")
    lineage = brief["lineage"]
    if not isinstance(lineage, dict) or set(lineage) != {
        "architecture_sha256",
        "graph_version",
        "graph_sha256",
        "generation_contract_sha256",
        "review_policy_sha256",
    }:
        raise SlotBriefInventoryError("brief lineage is incomplete or unknown")
    if lineage["architecture_sha256"] != architecture_content_digest(architecture):
        raise SlotBriefInventoryError("brief architecture lineage is stale")
    if lineage["graph_sha256"] != graph_content_digest(graph):
        raise SlotBriefInventoryError("brief graph lineage is stale")
    if lineage["generation_contract_sha256"] != contract_digest(contract):
        raise SlotBriefInventoryError("brief generation contract lineage is stale")
    _require_text(lineage["graph_version"], "lineage.graph_version")
    if lineage["review_policy_sha256"] != review_policy_sha256:
        raise SlotBriefInventoryError("brief review policy lineage is stale")
    allocation = brief["allocation"]
    if not isinstance(allocation, dict) or set(allocation) != {"bucket", "matrix_cell"}:
        raise SlotBriefInventoryError("brief allocation is incomplete or unknown")
    if allocation["bucket"] not in ALLOCATION_BUCKETS:
        raise SlotBriefInventoryError("brief allocation bucket is invalid")
    _require_text(allocation["matrix_cell"], "allocation.matrix_cell")
    graph_binding = brief["graph_binding"]
    if not isinstance(graph_binding, dict) or set(graph_binding) != {
        "primary_node_id",
        "related_node_ids",
        "prerequisite_role",
    }:
        raise SlotBriefInventoryError("brief graph_binding is incomplete or unknown")
    if graph_binding["primary_node_id"] not in graph_node_ids:
        raise SlotBriefInventoryError("brief primary_node_id is not in the graph")
    if not isinstance(graph_binding["related_node_ids"], list) or any(
        node_id not in graph_node_ids for node_id in graph_binding["related_node_ids"]
    ):
        raise SlotBriefInventoryError("brief related_node_ids are not in the graph")
    _require_text(graph_binding["prerequisite_role"], "graph_binding.prerequisite_role")
    design = brief["design"]
    if not isinstance(design, dict) or set(design) != {
        "purpose",
        "family_id",
        "risk_tier",
        "response_modality",
        "production_mode",
        "review_route_class",
    }:
        raise SlotBriefInventoryError("brief design is incomplete or unknown")
    if design["family_id"] not in {
        family["family_id"] for family in architecture["question_families"]
    }:
        raise SlotBriefInventoryError("brief family_id is not in the architecture")
    family = next(
        family for family in architecture["question_families"]
        if family["family_id"] == design["family_id"]
    )
    if design["purpose"] != family["purpose"]:
        raise SlotBriefInventoryError("brief purpose does not match family purpose")
    if design["risk_tier"] != family["risk_tier"]:
        raise SlotBriefInventoryError("brief risk_tier does not match family risk_tier")
    if design["response_modality"] not in family["allowed_modalities"]:
        raise SlotBriefInventoryError("brief modality is not allowed by family")
    if design["production_mode"] != contract["production_mode"]:
        raise SlotBriefInventoryError("brief production mode is invalid")
    _require_text(design["review_route_class"], "design.review_route_class")
    intent = brief["measurement_intent"]
    if not isinstance(intent, dict) or set(intent) != {
        "intent_id",
        "target",
        "observable_evidence",
        "failure_signal",
        "non_goal",
    }:
        raise SlotBriefInventoryError("measurement_intent is incomplete or unknown")
    for field in intent:
        _require_text(intent[field], f"measurement_intent.{field}")
    variation = brief["variation_policy"]
    if not isinstance(variation, dict) or set(variation) != {
        "allowed_variations",
        "forbidden_surface_patterns",
    }:
        raise SlotBriefInventoryError("variation_policy is incomplete or unknown")
    _require_list(variation["allowed_variations"], "variation_policy.allowed_variations")
    _require_list(variation["forbidden_surface_patterns"], "variation_policy.forbidden_surface_patterns")
    collision = brief["collision"]
    if not isinstance(collision, dict) or set(collision) != {
        "collision_group_id",
        "distinctness_basis",
    }:
        raise SlotBriefInventoryError("collision is incomplete or unknown")
    _require_text(collision["collision_group_id"], "collision.collision_group_id")
    _require_text(collision["distinctness_basis"], "collision.distinctness_basis")
    answer_shape = brief["answer_contract_shape"]
    if not isinstance(answer_shape, dict) or set(answer_shape) != {
        "contract_schema_id",
        "required_evidence_fields",
    }:
        raise SlotBriefInventoryError("answer_contract_shape is incomplete or unknown")
    _require_text(answer_shape["contract_schema_id"], "answer_contract_shape.contract_schema_id")
    _require_list(answer_shape["required_evidence_fields"], "answer_contract_shape.required_evidence_fields")
    visual = brief["visual_authority"]
    if not isinstance(visual, dict) or set(visual) != {
        "status",
        "renderer_sha256",
        "resource_sha256",
        "answer_capture_sha256",
    }:
        raise SlotBriefInventoryError("visual_authority is incomplete or unknown")
    if design["response_modality"] == "visual_interactive":
        if visual["status"] != "conditional_pending_authority":
            raise SlotBriefInventoryError("visual brief requires conditional_pending_authority")
    elif visual["status"] not in {"not_applicable", "authorized"}:
        raise SlotBriefInventoryError("nonvisual brief has invalid visual authority status")
    for field in ("renderer_sha256", "resource_sha256", "answer_capture_sha256"):
        if visual[field] != "" and (not isinstance(visual[field], str) or not SHA256_PATTERN.fullmatch(visual[field])):
            raise SlotBriefInventoryError(f"visual_authority.{field} is invalid")
    if not isinstance(brief["brief_sha256"], str) or not SHA256_PATTERN.fullmatch(brief["brief_sha256"]):
        raise SlotBriefInventoryError("brief_sha256 is invalid")
    if brief["brief_sha256"] != brief_digest(brief):
        raise SlotBriefInventoryError("brief_sha256 does not match brief content")
    return deepcopy(brief)


def validate_inventory(
    inventory: Any,
    *,
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
) -> dict[str, Any]:
    if not isinstance(inventory, dict) or set(inventory) != INVENTORY_FIELDS:
        raise SlotBriefInventoryError("inventory fields are incomplete or unknown")
    if inventory["schema_version"] != INVENTORY_SCHEMA_VERSION:
        raise SlotBriefInventoryError("unsupported slot brief inventory schema")
    if inventory["status"] not in STATUSES:
        raise SlotBriefInventoryError("inventory status is invalid")
    if inventory["architecture_sha256"] != architecture_content_digest(architecture):
        raise SlotBriefInventoryError("inventory architecture binding is stale")
    if inventory["graph_sha256"] != graph_content_digest(graph):
        raise SlotBriefInventoryError("inventory graph binding is stale")
    if inventory["review_policy_sha256"] != review_policy_sha256:
        raise SlotBriefInventoryError("inventory review policy binding is stale")
    if inventory["generation_contract_sha256"] != contract_digest(contract):
        raise SlotBriefInventoryError("inventory generation contract binding is stale")
    planned = architecture["capacity"]["planned_slot_count"]
    if inventory["planned_slot_count"] != planned:
        raise SlotBriefInventoryError("inventory planned count does not match architecture")
    slots = inventory["slots"]
    if not isinstance(slots, list) or len(slots) != planned:
        raise SlotBriefInventoryError("inventory slot count does not match architecture")
    graph_node_ids = load_graph_node_ids_from_graph(graph)
    validated = [
        validate_brief(
            brief,
            graph_node_ids=graph_node_ids,
            graph=graph,
            architecture=architecture,
            contract=contract,
            review_policy_sha256=review_policy_sha256,
        )
        for brief in slots
    ]
    slot_ids = [brief["slot_id"] for brief in validated]
    operation_keys = [brief["operation_key"] for brief in validated]
    if len(set(slot_ids)) != len(slot_ids) or len(set(operation_keys)) != len(operation_keys):
        raise SlotBriefInventoryError("slot ids and operation keys must be unique")
    _validate_distribution(validated, architecture, graph_node_ids)
    claimed = inventory["inventory_sha256"]
    if not isinstance(claimed, str) or not SHA256_PATTERN.fullmatch(claimed):
        raise SlotBriefInventoryError("inventory_sha256 is invalid")
    if claimed != inventory_digest(inventory):
        raise SlotBriefInventoryError("inventory_sha256 does not match inventory content")
    return deepcopy(inventory)


def load_graph_node_ids_from_graph(graph: dict[str, Any]) -> set[str]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise SlotBriefInventoryError("graph nodes must be a list")
    node_ids = {str(node.get("id")) for node in nodes if isinstance(node, dict) and node.get("id")}
    if len(node_ids) != len(nodes):
        raise SlotBriefInventoryError("graph node ids must be unique")
    return node_ids


def _validate_distribution(
    briefs: list[dict[str, Any]],
    architecture: dict[str, Any],
    graph_node_ids: set[str],
) -> None:
    allocation = architecture["allocation_formula"]
    expected_buckets = {
        "node_local_base": allocation["node_local_base"]["subtotal"],
        "high_impact_deepening": allocation["high_impact_deepening"]["subtotal"],
        "cross_node_transfer": allocation["cross_node_transfer"],
        "application_context": allocation["application_context"],
        "visual_interactive": allocation["visual_interactive"],
    }
    actual_buckets = {
        bucket: sum(brief["allocation"]["bucket"] == bucket for brief in briefs)
        for bucket in expected_buckets
    }
    if actual_buckets != expected_buckets:
        raise SlotBriefInventoryError("inventory allocation bucket counts do not match architecture")
    purpose_mix = architecture["purpose_mix"]
    for purpose in ("diagnostic", "guided", "practice", "challenge"):
        if sum(brief["design"]["purpose"] == purpose for brief in briefs) != purpose_mix[purpose]:
            raise SlotBriefInventoryError(f"inventory purpose count does not match: {purpose}")
    local_counts = {
        node_id: sum(
            brief["allocation"]["bucket"] == "node_local_base"
            and brief["graph_binding"]["primary_node_id"] == node_id
            for brief in briefs
        )
        for node_id in graph_node_ids
    }
    if any(count != allocation["node_local_base"]["slots_per_node"] for count in local_counts.values()):
        raise SlotBriefInventoryError("node_local_base must cover every graph node equally")
    high_impact = set(architecture["high_impact_nodes"])
    high_impact_counts = {
        node_id: sum(
            brief["allocation"]["bucket"] == "high_impact_deepening"
            and brief["graph_binding"]["primary_node_id"] == node_id
            for brief in briefs
        )
        for node_id in high_impact
    }
    if any(
        count != allocation["high_impact_deepening"]["extra_slots_per_node"]
        for count in high_impact_counts.values()
    ):
        raise SlotBriefInventoryError("high-impact deepening must cover every high-impact node equally")
