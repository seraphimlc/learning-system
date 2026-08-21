"""Program-owned slot planning and checkpoint contracts for v20 briefs.

This module creates only work plans. It never invents measurement intent,
question text, answers, or educational decisions; those fields must come from
the model and are validated separately by ``slot_brief_inventory``.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .slot_architecture import architecture_content_digest, graph_content_digest
from .slot_brief_inventory import (
    SlotBriefInventoryError,
    brief_digest,
    contract_digest,
    validate_brief,
    validate_contract,
)
from .v20_receipts import SHA256_PATTERN, canonical_json, sha256_json


QUEUE_SCHEMA_VERSION = "question-slot-brief-generation-queue.v20"
CHECKPOINT_SCHEMA_VERSION = "question-slot-brief-generation-checkpoint.v20.1"
QUEUE_STATUSES = frozenset({"PLANNED", "IN_PROGRESS", "COMPLETE", "BLOCKED"})
CHECKPOINT_STATUSES = frozenset({"PENDING", "GENERATED", "REJECTED", "BLOCKED", "REVIEWED"})
PLAN_FIELDS = frozenset(
    {
        "ordinal",
        "slot_id",
        "operation_key",
        "allocation",
        "graph_binding",
        "lineage",
        "status",
    }
)
QUEUE_FIELDS = frozenset(
    {
        "schema_version",
        "queue_version",
        "status",
        "planned_slot_count",
        "architecture_sha256",
        "graph_sha256",
        "generation_contract_sha256",
        "review_policy_sha256",
        "plans",
        "queue_sha256",
    }
)
CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "queue_sha256",
        "slot_id",
        "operation_key",
        "plan_sha256",
        "status",
        "attempt",
        "event_seq",
        "brief_sha256",
        "updated_at",
        "checkpoint_sha256",
    }
)
MAX_GENERATION_PACKET_BYTES = 40 * 1024
MAX_PRIOR_CONTEXT_ITEMS = 24
PRIOR_CONTEXT_TEXT_CHARS = 180


class SlotBriefGenerationError(ValueError):
    pass


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SlotBriefGenerationError(f"{field} must be nonempty")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise SlotBriefGenerationError(f"{field} must be a SHA-256 digest")
    return value


def _node_ids(graph: dict[str, Any]) -> list[str]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise SlotBriefGenerationError("graph nodes must be a list")
    ids = sorted(str(node["id"]) for node in nodes if isinstance(node, dict) and node.get("id"))
    if len(ids) != len(set(ids)):
        raise SlotBriefGenerationError("graph node ids must be unique")
    return ids


def _edges(graph: dict[str, Any]) -> list[tuple[str, str]]:
    edges = graph.get("prerequisite_edges")
    if not isinstance(edges, list):
        raise SlotBriefGenerationError("graph prerequisite_edges must be a list")
    result = []
    for edge in edges:
        if not isinstance(edge, dict):
            raise SlotBriefGenerationError("graph prerequisite edge must be an object")
        result.append((_text(edge.get("from"), "edge.from"), _text(edge.get("to"), "edge.to")))
    return sorted(set(result))


def _plan(
    *,
    ordinal: int,
    bucket: str,
    primary_node_id: str,
    related_node_ids: Iterable[str],
    prerequisite_role: str,
    architecture_sha256: str,
    graph_sha256: str,
    contract_sha256: str,
    review_policy_sha256: str,
) -> dict[str, Any]:
    slot_id = f"V20-SLOT-{ordinal:04d}"
    return {
        "ordinal": ordinal,
        "slot_id": slot_id,
        "operation_key": f"v20:{slot_id}",
        "allocation": {"bucket": bucket},
        "graph_binding": {
            "primary_node_id": primary_node_id,
            "related_node_ids": sorted(set(related_node_ids)),
            "prerequisite_role": prerequisite_role,
        },
        "lineage": {
            "architecture_sha256": architecture_sha256,
            "graph_sha256": graph_sha256,
            "generation_contract_sha256": contract_sha256,
            "review_policy_sha256": review_policy_sha256,
        },
        "status": "PLANNED",
    }


def enumerate_plans(
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
) -> list[dict[str, Any]]:
    """Build a stable shell plan from frozen numeric allocation only."""
    validate_contract(contract)
    _sha(review_policy_sha256, "review_policy_sha256")
    nodes = _node_ids(graph)
    high_impact_nodes = [node_id for node_id in architecture["high_impact_nodes"] if node_id in nodes]
    nodes = high_impact_nodes + [node_id for node_id in nodes if node_id not in set(high_impact_nodes)]
    edges = _edges(graph)
    arch_sha = architecture_content_digest(architecture)
    graph_sha = graph_content_digest(graph)
    contract_sha = contract_digest(contract)
    plans: list[dict[str, Any]] = []
    ordinal = 1

    def add_many(bucket: str, node_ids: Iterable[str], count: int, role: str) -> None:
        nonlocal ordinal
        for node_id in node_ids:
            for _ in range(count):
                plans.append(
                    _plan(
                        ordinal=ordinal,
                        bucket=bucket,
                        primary_node_id=node_id,
                        related_node_ids=[],
                        prerequisite_role=role,
                        architecture_sha256=arch_sha,
                        graph_sha256=graph_sha,
                        contract_sha256=contract_sha,
                        review_policy_sha256=review_policy_sha256,
                    )
                )
                ordinal += 1

    allocation = architecture["allocation_formula"]
    add_many(
        "node_local_base",
        nodes,
        allocation["node_local_base"]["slots_per_node"],
        "local",
    )
    add_many(
        "high_impact_deepening",
        sorted(architecture["high_impact_nodes"]),
        allocation["high_impact_deepening"]["extra_slots_per_node"],
        "high_impact",
    )

    for source, target in edges[: allocation["cross_node_transfer"]]:
        plans.append(
            _plan(
                ordinal=ordinal,
                bucket="cross_node_transfer",
                primary_node_id=target,
                related_node_ids=[source],
                prerequisite_role="cross_node",
                architecture_sha256=arch_sha,
                graph_sha256=graph_sha,
                contract_sha256=contract_sha,
                review_policy_sha256=review_policy_sha256,
            )
        )
        ordinal += 1

    for index in range(allocation["application_context"]):
        node_id = nodes[index % len(nodes)]
        plans.append(
            _plan(
                ordinal=ordinal,
                bucket="application_context",
                primary_node_id=node_id,
                related_node_ids=[],
                prerequisite_role="application",
                architecture_sha256=arch_sha,
                graph_sha256=graph_sha,
                contract_sha256=contract_sha,
                review_policy_sha256=review_policy_sha256,
            )
        )
        ordinal += 1

    for index in range(allocation["visual_interactive"]):
        node_id = nodes[index % len(nodes)]
        plans.append(
            _plan(
                ordinal=ordinal,
                bucket="visual_interactive",
                primary_node_id=node_id,
                related_node_ids=[],
                prerequisite_role="visual",
                architecture_sha256=arch_sha,
                graph_sha256=graph_sha,
                contract_sha256=contract_sha,
                review_policy_sha256=review_policy_sha256,
            )
        )
        ordinal += 1

    expected = architecture["capacity"]["planned_slot_count"]
    if len(plans) != expected:
        raise SlotBriefGenerationError(
            f"plan count {len(plans)} does not match architecture count {expected}"
        )
    return plans


def plan_digest(plan: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in plan.items() if key != "status"})


def validate_plan(plan: Any, *, graph_node_ids: set[str]) -> dict[str, Any]:
    if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS:
        raise SlotBriefGenerationError("slot plan fields are incomplete or unknown")
    ordinal = plan["ordinal"]
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise SlotBriefGenerationError("slot plan ordinal is invalid")
    slot_id = _text(plan["slot_id"], "slot_id")
    if slot_id != f"V20-SLOT-{ordinal:04d}":
        raise SlotBriefGenerationError("slot plan slot_id is not derived from ordinal")
    if plan["operation_key"] != f"v20:{slot_id}":
        raise SlotBriefGenerationError("slot plan operation_key is invalid")
    allocation = plan["allocation"]
    if not isinstance(allocation, dict) or set(allocation) != {"bucket"}:
        raise SlotBriefGenerationError("slot plan allocation is incomplete")
    if allocation["bucket"] not in {
        "node_local_base",
        "high_impact_deepening",
        "cross_node_transfer",
        "application_context",
        "visual_interactive",
    }:
        raise SlotBriefGenerationError("slot plan allocation bucket is invalid")
    binding = plan["graph_binding"]
    if not isinstance(binding, dict) or set(binding) != {
        "primary_node_id",
        "related_node_ids",
        "prerequisite_role",
    }:
        raise SlotBriefGenerationError("slot plan graph binding is incomplete")
    if binding["primary_node_id"] not in graph_node_ids:
        raise SlotBriefGenerationError("slot plan primary node is unknown")
    if not isinstance(binding["related_node_ids"], list) or any(
        node not in graph_node_ids for node in binding["related_node_ids"]
    ):
        raise SlotBriefGenerationError("slot plan related node is unknown")
    _text(binding["prerequisite_role"], "prerequisite_role")
    lineage = plan["lineage"]
    if not isinstance(lineage, dict) or set(lineage) != {
        "architecture_sha256",
        "graph_sha256",
        "generation_contract_sha256",
        "review_policy_sha256",
    }:
        raise SlotBriefGenerationError("slot plan lineage is incomplete")
    for field in lineage:
        _sha(lineage[field], f"lineage.{field}")
    if plan["status"] not in {"PLANNED", "GENERATED", "REJECTED", "BLOCKED"}:
        raise SlotBriefGenerationError("slot plan status is invalid")
    return deepcopy(plan)


def build_queue(
    *,
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
) -> dict[str, Any]:
    plans = enumerate_plans(architecture, graph, contract, review_policy_sha256)
    node_ids = set(_node_ids(graph))
    for plan in plans:
        validate_plan(plan, graph_node_ids=node_ids)
    queue = {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "queue_version": "v20-brief-queue-1",
        "status": "PLANNED",
        "planned_slot_count": len(plans),
        "architecture_sha256": architecture_content_digest(architecture),
        "graph_sha256": graph_content_digest(graph),
        "generation_contract_sha256": contract_digest(contract),
        "review_policy_sha256": review_policy_sha256,
        "plans": plans,
        "queue_sha256": "",
    }
    queue["queue_sha256"] = queue_digest(queue)
    return queue


def queue_digest(queue: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in queue.items() if key != "queue_sha256"})


def validate_queue(queue: Any, *, graph_node_ids: set[str]) -> dict[str, Any]:
    if not isinstance(queue, dict) or set(queue) != QUEUE_FIELDS:
        raise SlotBriefGenerationError("generation queue fields are incomplete or unknown")
    if queue["schema_version"] != QUEUE_SCHEMA_VERSION:
        raise SlotBriefGenerationError("unsupported brief generation queue")
    if queue["status"] not in QUEUE_STATUSES:
        raise SlotBriefGenerationError("generation queue status is invalid")
    _text(queue["queue_version"], "queue_version")
    count = queue["planned_slot_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise SlotBriefGenerationError("generation queue planned count is invalid")
    for field in (
        "architecture_sha256",
        "graph_sha256",
        "generation_contract_sha256",
        "review_policy_sha256",
        "queue_sha256",
    ):
        _sha(queue[field], field)
    plans = queue["plans"]
    if not isinstance(plans, list) or len(plans) != count:
        raise SlotBriefGenerationError("generation queue plan count is invalid")
    validated = [validate_plan(plan, graph_node_ids=graph_node_ids) for plan in plans]
    if len({plan["slot_id"] for plan in validated}) != count:
        raise SlotBriefGenerationError("generation queue slot ids must be unique")
    if queue["queue_sha256"] != queue_digest(queue):
        raise SlotBriefGenerationError("generation queue digest does not match content")
    return deepcopy(queue)


def validate_generated_brief(
    *,
    plan: dict[str, Any],
    brief: dict[str, Any],
    graph_node_ids: set[str],
    graph: dict[str, Any],
    architecture: dict[str, Any],
    contract: dict[str, Any],
    review_policy_sha256: str,
) -> dict[str, Any]:
    """Validate model output against the program-owned shell plan."""
    validate_plan(plan, graph_node_ids=graph_node_ids)
    if plan["status"] != "PLANNED":
        raise SlotBriefGenerationError("only PLANNED slot plans can accept a generated brief")
    try:
        validated = validate_brief(
            brief,
            graph_node_ids=graph_node_ids,
            graph=graph,
            architecture=architecture,
            contract=contract,
            review_policy_sha256=review_policy_sha256,
        )
    except SlotBriefInventoryError as exc:
        raise SlotBriefGenerationError(
            f"model brief failed inventory contract: {exc}"
        ) from exc
    if validated["status"] != "DRAFT":
        raise SlotBriefGenerationError("generated brief must start as DRAFT")
    if validated["slot_id"] != plan["slot_id"] or validated["operation_key"] != plan["operation_key"]:
        raise SlotBriefGenerationError("generated brief identity does not match plan")
    if validated["allocation"]["bucket"] != plan["allocation"]["bucket"]:
        raise SlotBriefGenerationError("generated brief allocation does not match plan")
    if validated["graph_binding"] != plan["graph_binding"]:
        raise SlotBriefGenerationError("generated brief graph binding does not match plan")
    lineage = validated["lineage"]
    if lineage["architecture_sha256"] != plan["lineage"]["architecture_sha256"]:
        raise SlotBriefGenerationError("generated brief architecture lineage does not match plan")
    if lineage["graph_sha256"] != plan["lineage"]["graph_sha256"]:
        raise SlotBriefGenerationError("generated brief graph lineage does not match plan")
    if lineage["generation_contract_sha256"] != plan["lineage"]["generation_contract_sha256"]:
        raise SlotBriefGenerationError("generated brief contract lineage does not match plan")
    if lineage["review_policy_sha256"] != plan["lineage"]["review_policy_sha256"]:
        raise SlotBriefGenerationError("generated brief policy lineage does not match plan")
    return validated


def _compact_context_text(value: Any) -> str:
    text = value if isinstance(value, str) else str(value or "")
    return text[:PRIOR_CONTEXT_TEXT_CHARS]


def _prior_brief_context(
    prior_briefs: Iterable[dict[str, Any]] | None,
    *,
    focus_node_id: str = "",
) -> list[dict[str, Any]]:
    """Expose only semantic collision boundaries from already reviewed briefs."""
    if prior_briefs is None:
        return []
    context: list[dict[str, Any]] = []
    for brief in prior_briefs:
        if not isinstance(brief, dict) or brief.get("status") != "REVIEWED":
            raise SlotBriefGenerationError("prior brief context must contain REVIEWED briefs")
        intent = brief.get("measurement_intent")
        design = brief.get("design")
        variation = brief.get("variation_policy")
        collision = brief.get("collision")
        contract_shape = brief.get("answer_contract_shape")
        binding = brief.get("graph_binding")
        if not all(isinstance(value, dict) for value in (intent, design, variation, collision, contract_shape, binding)):
            raise SlotBriefGenerationError("prior brief context is incomplete")
        context.append(
            {
                "slot_id": brief.get("slot_id", ""),
                "primary_node_id": binding.get("primary_node_id", ""),
                "purpose": design.get("purpose", ""),
                "family_id": design.get("family_id", ""),
                "measurement_intent_id": intent.get("intent_id", ""),
                "measurement_target": _compact_context_text(intent.get("target", "")),
                "required_evidence_fields": contract_shape.get("required_evidence_fields", []),
                "collision_group_id": collision.get("collision_group_id", ""),
                "distinctness_basis": _compact_context_text(collision.get("distinctness_basis", "")),
            }
        )
    ordered = sorted(context, key=lambda item: item["slot_id"])
    if focus_node_id:
        focused = [item for item in ordered if item["primary_node_id"] == focus_node_id]
        other = [item for item in ordered if item["primary_node_id"] != focus_node_id]
        ordered = focused + other
    return ordered[:MAX_PRIOR_CONTEXT_ITEMS]


def build_generation_packet(
    *,
    plan: dict[str, Any],
    architecture: dict[str, Any],
    graph: dict[str, Any],
    contract: dict[str, Any],
    prior_briefs: Iterable[dict[str, Any]] | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Return a compact model packet with no concrete question fields."""
    validate_plan(plan, graph_node_ids=set(_node_ids(graph)))
    node = next(node for node in graph["nodes"] if node["id"] == plan["graph_binding"]["primary_node_id"])
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise SlotBriefGenerationError("generation attempt must be positive")
    packet = {
        "packet_schema": "question-slot-brief-generation-input.v20",
        "slot_plan": deepcopy(plan),
        "node_context": {
            "node_id": node["id"],
            "name": node.get("name", ""),
            "essence_for_child": node.get("essence_for_child", ""),
            "stage": node.get("stage", ""),
            "priority": node.get("priority", ""),
            "prerequisites": sorted(node.get("prerequisites", [])),
            "question_types": sorted(node.get("question_types", [])),
            "common_mistakes": sorted(node.get("common_mistakes", [])),
            "mastery_criteria": node.get("mastery_criteria", []),
            "diagnostic_probes": node.get("diagnostic_probes", []),
        },
        "question_families": [
            {
                "family_id": family["family_id"],
                "purpose": family["purpose"],
                "risk_tier": family["risk_tier"],
                "allowed_modalities": family["allowed_modalities"],
                "evidence_target": family["evidence_target"],
            }
            for family in architecture["question_families"]
        ],
        "brief_contract_schema": contract["brief_schema_version"],
        "brief_is_not_a_question": True,
        "generation_attempt": attempt,
        "prior_reviewed_briefs": _prior_brief_context(
            prior_briefs,
            focus_node_id=plan["graph_binding"]["primary_node_id"],
        ),
    }
    packet_size = len(canonical_json(packet).encode("utf-8"))
    if packet_size >= MAX_GENERATION_PACKET_BYTES:
        raise SlotBriefGenerationError(
            f"generation packet exceeds bounded context budget: {packet_size} bytes"
        )
    return packet


def build_checkpoint(
    *, queue_sha256: str, plan: dict[str, Any], status: str, attempt: int = 0,
    brief_sha256: str = "", updated_at: str, event_seq: int = 1,
) -> dict[str, Any]:
    _sha(queue_sha256, "queue_sha256")
    validate_plan(plan, graph_node_ids={plan["graph_binding"]["primary_node_id"], *plan["graph_binding"]["related_node_ids"]})
    if status not in CHECKPOINT_STATUSES:
        raise SlotBriefGenerationError("checkpoint status is invalid")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        raise SlotBriefGenerationError("checkpoint attempt is invalid")
    if isinstance(event_seq, bool) or not isinstance(event_seq, int) or event_seq < 1:
        raise SlotBriefGenerationError("checkpoint event_seq is invalid")
    if brief_sha256:
        _sha(brief_sha256, "brief_sha256")
    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "queue_sha256": queue_sha256,
        "slot_id": plan["slot_id"],
        "operation_key": plan["operation_key"],
        "plan_sha256": plan_digest(plan),
        "status": status,
        "attempt": attempt,
        "event_seq": event_seq,
        "brief_sha256": brief_sha256,
        "updated_at": _text(updated_at, "updated_at"),
        "checkpoint_sha256": "",
    }
    checkpoint["checkpoint_sha256"] = sha256_json(
        {key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"}
    )
    return checkpoint


def validate_checkpoint(checkpoint: Any) -> dict[str, Any]:
    if not isinstance(checkpoint, dict) or set(checkpoint) != CHECKPOINT_FIELDS:
        raise SlotBriefGenerationError("checkpoint fields are incomplete or unknown")
    if checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
        raise SlotBriefGenerationError("unsupported slot brief checkpoint")
    for field in ("queue_sha256", "plan_sha256", "checkpoint_sha256"):
        _sha(checkpoint[field], field)
    _text(checkpoint["slot_id"], "slot_id")
    if checkpoint["operation_key"] != f"v20:{checkpoint['slot_id']}":
        raise SlotBriefGenerationError("checkpoint operation key is invalid")
    if checkpoint["status"] not in CHECKPOINT_STATUSES:
        raise SlotBriefGenerationError("checkpoint status is invalid")
    if isinstance(checkpoint["attempt"], bool) or not isinstance(checkpoint["attempt"], int) or checkpoint["attempt"] < 0:
        raise SlotBriefGenerationError("checkpoint attempt is invalid")
    if isinstance(checkpoint["event_seq"], bool) or not isinstance(checkpoint["event_seq"], int) or checkpoint["event_seq"] < 1:
        raise SlotBriefGenerationError("checkpoint event_seq is invalid")
    if checkpoint["brief_sha256"]:
        _sha(checkpoint["brief_sha256"], "brief_sha256")
    _text(checkpoint["updated_at"], "updated_at")
    expected = sha256_json({key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"})
    if checkpoint["checkpoint_sha256"] != expected:
        raise SlotBriefGenerationError("checkpoint digest does not match content")
    return deepcopy(checkpoint)


class AppendOnlyCheckpointStore:
    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def append(self, checkpoint: dict[str, Any]) -> Path:
        checkpoint = validate_checkpoint(checkpoint)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{checkpoint['slot_id']}-{checkpoint['checkpoint_sha256'][:16]}.json"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(canonical_json(checkpoint))
            handle.write("\n")
        return path
