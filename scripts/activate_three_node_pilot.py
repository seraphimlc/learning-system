#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import (  # noqa: E402
    assessment_policy,
    child_prompt,
    db,
    knowledge_map,
    question_bank,
    question_usage,
)
from scripts.activate_lightweight_answer_contracts import (  # noqa: E402
    GENERATOR_VERSION,
    build_contract,
    receipt_for,
)


PILOT_VERSION = "2026-07-28.math-three-node-pilot.v3"
PILOT_PREVIOUS_VERSION = "2026-07-28.math-three-node-pilot.v2"
PILOT_PREVIOUS_MANIFEST_ID = "math_three_node_pilot_2026_07_28_v2"
PILOT_PREVIOUS_MANIFEST_SHA256 = (
    "ad43eb66628b5e03df49f13d5e00211ad73029cabe9059e03c030e3468e56540"
)
PILOT_MANIFEST_ID = "math_three_node_pilot_2026_07_28_v3"
PILOT_PREDECESSOR_MANIFEST_IDS = {
    "MATH-PILOT-V1": "math_three_node_pilot_2026_07_26_v1",
    "MATH-PILOT-V2": "math_three_node_pilot_2026_07_28_v2",
}
PILOT_NODE_IDS = (
    "M-PRE-INTEGER-OPS",
    "M-G7-NUMBER-LINE",
    "M-G7-EQ-SOLVE",
)
PILOT_ITEM_COUNT = 24
PILOT_ACTIVE_ITEM_COUNT = 23
PILOT_NODE_ITEM_COUNTS = Counter({
    "M-PRE-INTEGER-OPS": 6,
    "M-G7-NUMBER-LINE": 12,
    "M-G7-EQ-SOLVE": 6,
})
NUMBER_LINE_FAMILY_COUNTS = Counter({
    "number_line_reference_frame": 3,
    "number_line_coordinate_location": 3,
    "number_line_distance_relation": 3,
    "number_line_local_scale_construction": 3,
})
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "data/question_banks/math/math_three_node_pilot_2026-07-28.v3.json"
)
PREDECESSOR_MANIFEST = (
    PROJECT_ROOT
    / "data/question_banks/math/math_three_node_pilot_2026-07-28.v2.json"
)
PRODUCTION_DB = (PROJECT_ROOT / "data/local_learning_system.sqlite").resolve()

ROLE_TO_KIND = {
    "basic_confirmation": "standard_example",
    "core_understanding": "essence_check",
    "near_transfer": "transfer_retest",
    "error_diagnosis": "error_spotting",
    "fluency_practice": "check_strategy",
    "controlled_extension": "stretch_transfer",
}
ROLE_TO_USAGE = {
    "basic_confirmation": ("structural_calculation", ["stabilize_fluency"]),
    "core_understanding": ("concept_model", ["consolidate_core"]),
    "near_transfer": ("variation_reverse_reasoning", ["near_transfer", "far_transfer"]),
    "error_diagnosis": ("error_repair", ["repair_specific_gap"]),
    "fluency_practice": ("structural_calculation", ["stabilize_fluency"]),
    "controlled_extension": ("controlled_stretch", ["controlled_challenge"]),
}
PILOT_SUPPORT_ROUTING = {
    "MATH-PILOT-V3-NL-06": {
        "schema_version": question_usage.SUPPORT_ROUTING_VERSION,
        "routes": [
            {
                "evidence_key": "midpoint_reverse_location_gap",
                "source_item_id": "MATH-PILOT-V3-NL-10",
                "criterion_key": "unique_endpoints_with_midpoint",
                "trigger_statuses": ["not_met", "contradicted"],
            }
        ],
    }
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_nonempty_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"pilot manifest requires {field}")
    return text


def predecessor_manifest_id(question_id: str) -> str:
    for prefix, manifest_id in PILOT_PREDECESSOR_MANIFEST_IDS.items():
        if str(question_id or "").startswith(prefix + "-"):
            return manifest_id
    raise ValueError(f"unsupported pilot predecessor question ID: {question_id}")


def _load_graph(project_root: Path) -> tuple[dict[str, dict[str, Any]], str]:
    graph_path = project_root / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
    raw = graph_path.read_bytes()
    graph = json.loads(raw.decode("utf-8"))
    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    missing = sorted(set(PILOT_NODE_IDS) - set(nodes))
    if missing:
        raise ValueError(f"pilot graph nodes are missing: {','.join(missing)}")
    return nodes, hashlib.sha256(raw).hexdigest()


def _validate_scoring_targets(raw_targets: Any, item_id: str) -> list[dict[str, Any]]:
    if not isinstance(raw_targets, list) or not 2 <= len(raw_targets) <= 4:
        raise ValueError(f"{item_id}: scoring_targets must contain two to four targets")
    targets: list[dict[str, Any]] = []
    keys: set[str] = set()
    for raw in raw_targets:
        if not isinstance(raw, dict):
            raise ValueError(f"{item_id}: scoring target must be an object")
        key = _require_nonempty_text(raw.get("key"), f"{item_id}.scoring_targets.key")
        if key in keys:
            raise ValueError(f"{item_id}: duplicate scoring target key: {key}")
        keys.add(key)
        criterion = _require_nonempty_text(
            raw.get("criterion"), f"{item_id}.scoring_targets.{key}.criterion"
        )
        points = raw.get("points")
        if isinstance(points, bool) or not isinstance(points, int) or points <= 0:
            raise ValueError(f"{item_id}: scoring target points must be positive integers")
        required = raw.get("required_for_pass")
        if not isinstance(required, bool):
            raise ValueError(f"{item_id}: required_for_pass must be boolean")
        dimension = _require_nonempty_text(
            raw.get("dimension"),
            f"{item_id}.scoring_targets.{key}.dimension",
        )
        if dimension not in assessment_policy.ALLOWED_MASTERY_DIMENSIONS:
            raise ValueError(
                f"{item_id}: invalid scoring target dimension: {dimension}"
            )
        reference_component = _require_nonempty_text(
            raw.get("reference_component"),
            f"{item_id}.scoring_targets.{key}.reference_component",
        )
        targets.append(
            {
                "key": key,
                "criterion": criterion,
                "points": points,
                "dimension": dimension,
                "required_for_pass": required,
                "reference_component": reference_component,
            }
        )
    if sum(target["points"] for target in targets) != 10:
        raise ValueError(f"{item_id}: scoring target points must total 10")
    return targets


def _validate_rollbacks(
    *, item_id: str, node_id: str, rollback_ids: list[str], graph_nodes: dict[str, dict[str, Any]]
) -> None:
    unknown = sorted(set(rollback_ids) - set(graph_nodes))
    if unknown:
        raise ValueError(f"{item_id}: unknown rollback nodes: {','.join(unknown)}")
    node = graph_nodes[node_id]
    allowed = set(node.get("prerequisites") or [])
    allowed.update((node.get("error_diagnosis") or {}).get("rollback_to") or [])
    allowed.add(node_id)
    illegal = [rollback_id for rollback_id in rollback_ids if rollback_id not in allowed]
    if illegal:
        raise ValueError(
            f"{item_id}: rollback nodes are not on the prerequisite chain: {','.join(illegal)}"
        )


def _interaction_schema() -> dict[str, Any]:
    return child_prompt.normalize_interaction_schema(
        {
            "schema_version": child_prompt.QUESTION_INTERACTION_SCHEMA_V2,
            "type": "short_text",
            "title": "",
            "allow_explanation": True,
            "requires_explanation": False,
            "explanation_label": "补充说明（可选）",
            "placeholder": "写下答案和必要步骤",
        },
        allow_legacy=False,
    )


def _usage_policy(item: dict[str, Any], role: str, usage: str) -> dict[str, Any]:
    family, practice_roles = ROLE_TO_USAGE[role]
    diagnostic_roles = [
        "entry_probe",
        "confirmation_core",
        "confirmation_transfer",
        "prerequisite_probe",
    ]
    if usage == "support":
        allowed_purposes = ["teaching"]
        allowed_practice_roles = practice_roles
        allowed_diagnostic_roles = diagnostic_roles
    else:
        allowed_purposes = (
            ["teaching", "diagnostic", "practice"]
            if usage == "diagnostic"
            else ["teaching", "practice"]
        )
        allowed_practice_roles = practice_roles
        allowed_diagnostic_roles = diagnostic_roles
    selection_preconditions = question_usage.normalize_selection_preconditions(
        item.get("selection_preconditions")
    )
    support_routing: dict[str, Any] = {}
    if usage == "support":
        support_routing = question_usage.normalize_support_routing(
            PILOT_SUPPORT_ROUTING.get(str(item.get("id") or ""))
        )
        if not support_routing:
            raise ValueError(
                f"{item.get('id')}: support item is missing an explicit routing contract"
            )
    policy = {
        "schema_version": question_usage.USAGE_POLICY_VERSION,
        "allowed_purposes": allowed_purposes,
        "default_practice_family": family,
        "allowed_practice_roles": allowed_practice_roles,
        "diagnostic_roles": allowed_diagnostic_roles,
        "teaching_roles": ["concept_build", "worked_example", "targeted_repair"],
        "primary_node_id": item["node_id"],
        "secondary_node_ids": [],
        "structure_fingerprint": (
            "USAGE-"
            + canonical_sha256(
                {
                    "question_id": item["id"],
                    "item_version": item["item_version"],
                    "problem_instance_id": item["problem_instance_id"],
                }
            )[:20]
        ),
        "support_only": usage == "support",
        "not_for_activation": item.get("activation_status") != "active",
        "selection_preconditions": selection_preconditions,
        "support_routing": support_routing,
        "source": "explicit",
    }
    question_usage.validate_policy(policy)
    return policy


def _build_item(
    raw: dict[str, Any],
    *,
    manifest: dict[str, Any],
    manifest_sha256: str,
    graph_nodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    item_id = _require_nonempty_text(raw.get("id"), "items[].id")
    node_id = _require_nonempty_text(raw.get("node_id"), f"{item_id}.node_id")
    if node_id not in PILOT_NODE_IDS:
        raise ValueError(f"{item_id}: node_id is outside the pilot")
    role = _require_nonempty_text(raw.get("pedagogical_role"), f"{item_id}.pedagogical_role")
    if role not in ROLE_TO_KIND:
        raise ValueError(f"{item_id}: unsupported pedagogical_role: {role}")
    usage = _require_nonempty_text(raw.get("usage"), f"{item_id}.usage")
    if usage not in {"diagnostic", "practice", "support"}:
        raise ValueError(f"{item_id}: unsupported usage: {usage}")
    prompt = _require_nonempty_text(raw.get("prompt"), f"{item_id}.prompt")
    expected_answer = _require_nonempty_text(raw.get("expected_answer"), f"{item_id}.expected_answer")
    solution_steps = raw.get("solution_steps")
    if not isinstance(solution_steps, list) or len(solution_steps) < 2 or any(
        not str(step or "").strip() for step in solution_steps
    ):
        raise ValueError(f"{item_id}: at least two nonempty solution steps are required")
    original_interaction = raw.get("interaction_schema")
    if not isinstance(original_interaction, dict) or not str(original_interaction.get("type") or ""):
        raise ValueError(f"{item_id}: original interaction_schema is malformed")
    scoring_targets = _validate_scoring_targets(raw.get("scoring_targets"), item_id)
    selection_preconditions = question_usage.normalize_selection_preconditions(
        raw.get("selection_preconditions")
    )
    instance_key = _require_nonempty_text(
        raw.get("problem_instance_key"), f"{item_id}.problem_instance_key"
    )
    failure_route = raw.get("failure_route")
    if not isinstance(failure_route, dict):
        raise ValueError(f"{item_id}: failure_route must be an object")
    raw_rollbacks = failure_route.get("rollback_node_ids") or []
    if not isinstance(raw_rollbacks, list) or any(not str(value or "").strip() for value in raw_rollbacks):
        raise ValueError(f"{item_id}: rollback_node_ids must be an array of node IDs")
    rollback_ids = [str(value).strip() for value in raw_rollbacks]
    _validate_rollbacks(
        item_id=item_id,
        node_id=node_id,
        rollback_ids=rollback_ids,
        graph_nodes=graph_nodes,
    )
    rationale = raw.get("expert_review_rationale")
    if not isinstance(rationale, dict) or not all(
        str(rationale.get(key) or "").strip()
        for key in ("node_binding", "structural_role", "difference_from_siblings", "age_fit")
    ):
        raise ValueError(f"{item_id}: expert_review_rationale is incomplete")
    held_item_ids = set(manifest.get("held_item_ids") or [])
    family_assignments = manifest.get("question_family_assignments") or {}
    question_family_id = str(
        family_assignments.get(item_id) or f"{node_id}:{role}"
    ).strip()
    if not question_family_id:
        raise ValueError(f"{item_id}: question family assignment is empty")
    predecessor_question_id = str(
        (manifest.get("predecessor_question_ids") or {}).get(item_id) or ""
    ).strip()
    activation_plan = manifest.get("activation_plan") or {}
    node_activation_order = list(activation_plan.get(node_id) or [])
    activation_status = "hold" if item_id in held_item_ids else "active"
    selection_priority = (
        None
        if activation_status == "hold"
        else node_activation_order.index(item_id) + 1
    )

    family_id = "PF-PILOT-" + canonical_sha256(
        {
            "manifest_id": manifest["manifest_id"],
            "node_id": node_id,
            "question_family_id": question_family_id,
        }
    )[:16]
    core_id = "CS-PILOT-" + canonical_sha256(
        {"node_id": node_id, "prompt": prompt, "expected_answer": expected_answer}
    )[:16]
    instance_id = "PI-" + canonical_sha256(
        {
            "manifest_id": (
                predecessor_manifest_id(predecessor_question_id)
                if predecessor_question_id
                else manifest["manifest_id"]
            ),
            "question_id": predecessor_question_id or item_id,
            "problem_instance_key": instance_key,
        }
    )[:20]
    family_basis = {
        "node_id": node_id,
        "activation_status": activation_status,
        "selection_priority": selection_priority,
        "topic_family": graph_nodes[node_id].get("name", node_id),
        "probe_family": role,
        "question_family_id": question_family_id,
        "kind": ROLE_TO_KIND[role],
    }
    core_basis = {
        "node_id": node_id,
        "core_fields": {"stem_anchor": prompt, "answer_anchor": expected_answer},
        "evidence_role": "node_local_mainline",
    }
    instance_basis = {
        "instance_key": instance_key,
        "problem": prompt,
        "predecessor_question_id": predecessor_question_id,
    }
    node_local_anchor = str(rationale["node_binding"]).strip()
    alignment = {
        "status": "expert_reviewed",
        "alignment_mode": "node_local_mainline",
        "primary_node_id": node_id,
        "primary_node_name": graph_nodes[node_id].get("name", node_id),
        "question_type": role,
        "predecessor_question_id": predecessor_question_id,
        "question_family_id": question_family_id,
        "problem_family_id": family_id,
        "core_stem_id": core_id,
        "problem_instance_id": instance_id,
        "reason": node_local_anchor,
        "matched_terms": [node_id, graph_nodes[node_id].get("name", node_id), role],
        "measured_capability": str(rationale["structural_role"]).strip(),
        "graph_seed_question_type": role,
        "node_local_anchor": node_local_anchor,
        "problem_family_basis": family_basis,
        "core_stem_basis": core_basis,
        "problem_instance_basis": instance_basis,
        "target_error_tags": ["general"],
        "rollback_candidate_node_ids": rollback_ids,
    }
    reviewer_evidence = {
        "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
        "engine_type": "expert_reviewed_pilot_import",
        "provenance_type": "expert_reviewed_pilot_manifest",
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest_sha256,
        "contract_version": question_bank.QUESTION_PRODUCTION_CONTRACT_VERSION,
        "graph_bound": True,
        "incoming_grade_7_ready": True,
        "diagnostic_structure": True,
        "process_evidence_required": True,
        "not_mechanical_drill": True,
        "child_prompt_self_contained": True,
        "specific_expected_answer": True,
        "problem_family_id": family_id,
        "core_stem_id": core_id,
        "problem_instance_id": instance_id,
        "evidence_role": "node_local_mainline",
        "review_rationale": " | ".join(str(rationale[key]).strip() for key in rationale),
    }
    item: dict[str, Any] = {
        "id": item_id,
        "candidate_id": item_id,
        "item_version": PILOT_VERSION,
        "question_bank_version": PILOT_VERSION,
        "source_type": "graph_generated",
        "node_id": node_id,
        "activation_status": activation_status,
        "selection_priority": selection_priority,
        "secondary_node_ids": [],
        "kind": ROLE_TO_KIND[role],
        "question_type": role,
        "variant_level": _require_nonempty_text(raw.get("difficulty"), f"{item_id}.difficulty"),
        "prompt": prompt,
        "answer_format": "写下答案和必要步骤",
        "expected_answer": expected_answer,
        "rubric": question_bank.BASE_RUBRIC,
        "solution_steps": [str(step).strip() for step in solution_steps],
        "scoring_targets": scoring_targets,
        "target_error_tags": ["general"],
        "rollback_candidates": rollback_ids,
        "rollback_candidate_relations": [
            {"node_id": rollback_id, "relation": "prerequisite_chain"}
            for rollback_id in rollback_ids
        ],
        "estimated_minutes": 4,
        "parent_observation": "",
        "age_floor": question_bank.INCOMING_GRADE_7_AGE_FLOOR,
        "problem_family_id": family_id,
        "core_stem_id": core_id,
        "problem_instance_id": instance_id,
        "node_alignment": alignment,
        "interaction_schema": _interaction_schema(),
        "selection_preconditions": selection_preconditions,
        "child_surface_design": {
            "schema_version": "2026-07-26.three-node-pilot-child-surface.v1",
            "child_deliverables": ["答案", "必要步骤或理由"],
            "writing_burden": "two_or_fewer_short_deliverables",
            "original_interaction_type": str(original_interaction["type"]),
        },
        "source": {
            "type": "graph_generated",
            "manifest_id": manifest["manifest_id"],
            "manifest_sha256": manifest_sha256,
            "question_bank_version": PILOT_VERSION,
            "problem_family_id": family_id,
            "core_stem_id": core_id,
            "problem_instance_id": instance_id,
            "problem_family_basis": family_basis,
            "core_stem_basis": core_basis,
            "problem_instance_basis": instance_basis,
            "node_local_anchor": node_local_anchor,
            "node_alignment": alignment,
            "reviewer_evidence": reviewer_evidence,
            "expert_review_rationale": rationale,
            "activation_status": activation_status,
            "selection_priority": selection_priority,
            "original_interaction_schema": original_interaction,
            "production_pipeline": {
                "contract_version": question_bank.QUESTION_PRODUCTION_CONTRACT_VERSION,
                "designer_agent": question_bank.QUESTION_DESIGNER_AGENT_KEY,
                "reviewer_agent": question_bank.QUESTION_REVIEWER_AGENT_KEY,
                "question_bank_version": PILOT_VERSION,
                "workflow": ["expert_manifest_import", "quality_review", "isolated_activation"],
            },
        },
    }
    item["usage_policy"] = _usage_policy(item, role, usage)
    quality = question_bank.review_item_quality(item)
    item["quality"] = quality
    item["cognitive_level"] = quality["cognitive_level"]
    item["item_purpose"] = quality["item_purpose"]
    item["requires_reasoning"] = quality["requires_reasoning"]
    item["review_agent_check"] = {
        "reviewer_agent": question_bank.QUESTION_REVIEWER_AGENT_KEY,
        "status": quality["review_status"],
        "rejection_reasons": quality["rejection_reasons"],
    }
    if quality["review_status"] != "approved":
        raise ValueError(f"{item_id}: current quality gate rejected item: {quality['rejection_reasons']}")
    assessment_policy.validate_authoritative_scoring_targets(item)
    assessment_policy.build_answer_contract(item)
    return item


def _validate_support_route_cross_references(items: list[dict[str, Any]]) -> None:
    items_by_id = {str(item.get("id") or ""): item for item in items}
    for support_item in items:
        policy = support_item.get("usage_policy")
        if not isinstance(policy, dict) or not bool(policy.get("support_only")):
            continue
        support_routing = question_usage.normalize_support_routing(
            policy.get("support_routing")
        )
        for route in support_routing.get("routes") or []:
            source_item_id = route["source_item_id"]
            source_item = items_by_id.get(source_item_id)
            if source_item is None:
                raise ValueError(
                    f"{support_item['id']}: support route source item does not exist: "
                    f"{source_item_id}"
                )
            if (
                str(source_item.get("item_version") or "")
                != str(support_item.get("item_version") or "")
                or str(source_item.get("question_bank_version") or "")
                != str(support_item.get("question_bank_version") or "")
            ):
                raise ValueError(
                    f"{support_item['id']}: support route source item is outside the active bank version"
                )
            if str(source_item.get("node_id") or "") != str(
                support_item.get("node_id") or ""
            ):
                raise ValueError(
                    f"{support_item['id']}: support route source node is not legal: "
                    f"{source_item_id}"
                )
            source_criterion_keys = {
                str(target.get("key") or "")
                for target in (source_item.get("scoring_targets") or [])
                if isinstance(target, dict)
            }
            if route["criterion_key"] not in source_criterion_keys:
                raise ValueError(
                    f"{support_item['id']}: support route criterion does not exist on "
                    f"{source_item_id}: {route['criterion_key']}"
                )


def load_pilot(
    manifest_path: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    raw_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("pilot manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("pilot manifest root must be an object")
    if manifest.get("schema_version") != PILOT_VERSION:
        raise ValueError("pilot manifest schema_version mismatch")
    if manifest.get("question_bank_version") != PILOT_VERSION:
        raise ValueError("pilot question_bank_version mismatch")
    if manifest.get("manifest_id") != PILOT_MANIFEST_ID:
        raise ValueError("pilot manifest_id mismatch")
    if manifest.get("status") != "expert_reviewed_pilot_not_active":
        raise ValueError("pilot manifest must be expert reviewed and not already active")
    if manifest.get("node_ids") != list(PILOT_NODE_IDS):
        raise ValueError("pilot manifest node_ids mismatch")
    if manifest.get("item_count") != PILOT_ITEM_COUNT:
        raise ValueError("pilot manifest item_count mismatch")
    scoring_policy = manifest.get("scoring_policy")
    if not isinstance(scoring_policy, dict) or scoring_policy.get("score_scale") != 10:
        raise ValueError("pilot scoring_policy must use a 10-point scale")
    if scoring_policy.get("pass_score") != 8:
        raise ValueError("pilot scoring_policy pass_score must be 8")
    raw_items = manifest.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != PILOT_ITEM_COUNT:
        raise ValueError(f"pilot manifest must contain exactly {PILOT_ITEM_COUNT} items")
    held_item_ids = manifest.get("held_item_ids")
    if not isinstance(held_item_ids, list) or len(set(held_item_ids)) != len(held_item_ids):
        raise ValueError("pilot held_item_ids must be a unique array")
    activation_plan = manifest.get("activation_plan")
    if not isinstance(activation_plan, dict) or set(activation_plan) != set(PILOT_NODE_IDS):
        raise ValueError("pilot activation_plan must cover exactly the pilot nodes")
    manifest_item_ids = {
        str(raw.get("id") or "")
        for raw in raw_items
        if isinstance(raw, dict)
    }
    if not set(held_item_ids).issubset(manifest_item_ids):
        raise ValueError("pilot held_item_ids contains an unknown item")
    family_assignments = manifest.get("question_family_assignments")
    if not isinstance(family_assignments, dict):
        raise ValueError("pilot question_family_assignments must be an object")
    number_line_item_ids = {
        str(raw.get("id") or "")
        for raw in raw_items
        if isinstance(raw, dict) and raw.get("node_id") == "M-G7-NUMBER-LINE"
    }
    if set(family_assignments) != number_line_item_ids:
        raise ValueError(
            "pilot number-line family assignments must cover every number-line item exactly"
        )
    family_counts = Counter(str(value or "") for value in family_assignments.values())
    if family_counts != NUMBER_LINE_FAMILY_COUNTS:
        raise ValueError(
            "pilot number-line family coverage mismatch: "
            + json.dumps(dict(family_counts), ensure_ascii=False, sort_keys=True)
        )
    predecessor_question_ids = manifest.get("predecessor_question_ids")
    if not isinstance(predecessor_question_ids, dict):
        raise ValueError("pilot predecessor_question_ids must be an object")
    if set(predecessor_question_ids) != manifest_item_ids:
        raise ValueError(
            "pilot predecessor lineage must cover every v3 item exactly"
        )
    if len(set(str(value or "") for value in predecessor_question_ids.values())) != len(
        predecessor_question_ids
    ):
        raise ValueError("pilot predecessor question IDs must be unique")
    for item_id, predecessor_id in predecessor_question_ids.items():
        predecessor_id = str(predecessor_id or "")
        predecessor_manifest_id(predecessor_id)
        current_suffix = str(item_id).removeprefix("MATH-PILOT-V3")
        predecessor_suffix = predecessor_id.removeprefix("MATH-PILOT-V1").removeprefix(
            "MATH-PILOT-V2"
        )
        if not current_suffix or predecessor_suffix != current_suffix:
            raise ValueError(f"pilot predecessor lineage mismatch: {item_id}")
    ordered_active_ids: list[str] = []
    for node_id in PILOT_NODE_IDS:
        order = activation_plan.get(node_id)
        if not isinstance(order, list) or any(not str(item_id or "").strip() for item_id in order):
            raise ValueError(f"pilot activation order is malformed for {node_id}")
        ordered_active_ids.extend(str(item_id).strip() for item_id in order)
    if len(ordered_active_ids) != len(set(ordered_active_ids)):
        raise ValueError("pilot activation_plan contains duplicate items")
    if set(ordered_active_ids) != manifest_item_ids - set(held_item_ids):
        raise ValueError("pilot activation_plan must contain every non-held item exactly once")

    graph_nodes, _ = _load_graph(project_root)
    manifest_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    seen_ids: set[str] = set()
    seen_instance_keys: set[str] = set()
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("pilot items must be objects")
        item_id = str(raw.get("id") or "")
        instance_key = str(raw.get("problem_instance_key") or "")
        if item_id in seen_ids:
            raise ValueError(f"duplicate pilot item id: {item_id}")
        if instance_key in seen_instance_keys:
            raise ValueError(f"duplicate pilot problem_instance_key: {instance_key}")
        seen_ids.add(item_id)
        seen_instance_keys.add(instance_key)
        items.append(
            _build_item(
                raw,
                manifest=manifest,
                manifest_sha256=manifest_sha256,
                graph_nodes=graph_nodes,
            )
        )

    _validate_support_route_cross_references(items)

    node_counts = Counter(item["node_id"] for item in items)
    if node_counts != PILOT_NODE_ITEM_COUNTS:
        raise ValueError(
            "pilot manifest node item counts mismatch: "
            + json.dumps(dict(node_counts), ensure_ascii=False, sort_keys=True)
        )
    role_counts = Counter((item["node_id"], item["question_type"]) for item in items)
    if any(role_counts[(node_id, role)] < 1 for node_id in PILOT_NODE_IDS for role in ROLE_TO_KIND):
        raise ValueError("pilot manifest must contain every pedagogical role for each node")
    if len({item["problem_instance_id"] for item in items}) != PILOT_ITEM_COUNT:
        raise ValueError("pilot problem-instance identities are not unique")
    return manifest, items, manifest_sha256


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = ?", (table,)
        ).fetchone()
    )


def _reject_nonisolated_database(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "question_bank_version_ledger"):
        versions = {
            str(row["question_bank_version"])
            for row in conn.execute("select question_bank_version from question_bank_version_ledger")
        }
        foreign = sorted(version for version in versions if version != PILOT_VERSION)
        if foreign:
            raise ValueError(
                "isolated pilot database contains another question bank: " + ",".join(foreign)
            )
    if _table_exists(conn, "question_items"):
        rows = conn.execute("select id, item_version from question_items").fetchall()
        foreign = [
            str(row["id"])
            for row in rows
            if str(row["item_version"] or "") != PILOT_VERSION
        ]
        if foreign:
            raise ValueError("isolated pilot database contains non-pilot questions")


def _active_ledger_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "select * from question_bank_version_ledger where status = 'active' order by id"
    ).fetchall()


def _runtime_cutover_blockers(conn: sqlite3.Connection) -> dict[str, list[str]]:
    flows = [
        str(row["id"])
        for row in conn.execute(
            """
            select id from daily_flows
            where status not in ('completed','superseded')
            order by created_at, id
            """
        )
    ]
    active_job_statuses = sorted(db.V3_ACTIVE_BACKGROUND_JOB_STATUSES)
    job_placeholders = ",".join("?" for _ in active_job_statuses)
    jobs = [
        str(row["id"])
        for row in conn.execute(
            f"""
            select id from background_jobs
            where status in ({job_placeholders})
            order by created_at, id
            """,
            active_job_statuses,
        )
    ]
    intents = [
        str(row["id"])
        for row in conn.execute(
            """
            select id from learning_target_intents
            where status in ('pending','waiting_for_safe_boundary')
            order by created_at, id
            """
        )
    ]
    return {
        "daily_flows": flows,
        "background_jobs": jobs,
        "learning_target_intents": intents,
    }


def _stage_items(
    conn: sqlite3.Connection,
    *,
    manifest: dict[str, Any],
    items: list[dict[str, Any]],
    manifest_sha256: str,
    graph_version: str,
) -> dict[str, Any]:
    item_ids = [item["id"] for item in items if item.get("activation_status") == "active"]
    placeholders = ",".join("?" for _ in item_ids)
    collisions = conn.execute(
        f"select id from question_items where id in ({placeholders}) order by id",
        item_ids,
    ).fetchall()
    if collisions:
        raise ValueError(
            "pilot v3 question-id collision: "
            + ",".join(str(row["id"]) for row in collisions)
        )
    designer_run = db.record_agent_run(
        conn,
        agent_key=question_bank.QUESTION_DESIGNER_AGENT_KEY,
        engine_type="manual_maintenance",
        session_id=None,
        phase="question_design_import",
        trigger=f"three_node_pilot_import:{manifest_sha256}",
        input_refs={
            "manifest_id": manifest["manifest_id"],
            "manifest_sha256": manifest_sha256,
            "question_bank_version": PILOT_VERSION,
            "item_count": PILOT_ITEM_COUNT,
        },
        prompt_version_id=PILOT_VERSION,
        status="accepted",
        confidence=1.0,
        output={"status": "imported", "item_count": PILOT_ITEM_COUNT},
        commit=False,
    )
    for item in items:
        if item.get("activation_status") != "active":
            continue
        candidate_sha256 = canonical_sha256(item)
        reviewer_run = db.record_agent_run(
            conn,
            agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
            engine_type="manual_maintenance",
            session_id=None,
            phase="question_quality_review",
            trigger=f"three_node_pilot_review:{manifest_sha256}:{item['id']}",
            input_refs={
                "manifest_id": manifest["manifest_id"],
                "manifest_sha256": manifest_sha256,
                "question_bank_version": PILOT_VERSION,
                "question_id": item["id"],
                "candidate_sha256": candidate_sha256,
            },
            prompt_version_id=PILOT_VERSION,
            status="accepted",
            confidence=1.0,
            output={
                "review_status": "approved",
                "active_eligible": True,
                "expert_review_rationale": item["source"]["expert_review_rationale"],
            },
            commit=False,
        )
        db.upsert_question(
            conn,
            item,
            designer_run_id=designer_run["id"],
            reviewer_run_id=reviewer_run["id"],
        )
    return db.stage_question_bank_version(
        conn,
        question_bank_version=PILOT_VERSION,
        graph_version=graph_version,
        manifest_id=manifest["manifest_id"],
        manifest_sha256=manifest_sha256,
        node_count=len(PILOT_NODE_IDS),
        item_count=PILOT_ACTIVE_ITEM_COUNT,
        commit=False,
    )


def _verify_staged_installation(
    conn: sqlite3.Connection,
    *,
    items: list[dict[str, Any]],
    manifest_sha256: str,
    graph_version: str,
) -> dict[str, Any]:
    ledger = conn.execute(
        """
        select * from question_bank_version_ledger
        where question_bank_version = ? and status in ('staged','active')
        order by created_at desc, id desc limit 1
        """,
        (PILOT_VERSION,),
    ).fetchone()
    if not ledger:
        raise ValueError("pilot v3 staged ledger is missing")
    expected_ledger = {
        "manifest_id": PILOT_MANIFEST_ID,
        "manifest_sha256": manifest_sha256,
        "graph_version": graph_version,
        "node_count": len(PILOT_NODE_IDS),
        "item_count": PILOT_ACTIVE_ITEM_COUNT,
    }
    mismatches = [
        key for key, expected in expected_ledger.items() if ledger[key] != expected
    ]
    if mismatches:
        raise ValueError("pilot v3 staged ledger mismatch: " + ",".join(mismatches))
    expected_by_id = {
        item["id"]: item
        for item in items
        if item.get("activation_status") == "active"
    }
    rows = conn.execute(
        "select * from question_items where item_version = ? order by id",
        (PILOT_VERSION,),
    ).fetchall()
    if len(rows) != PILOT_ACTIVE_ITEM_COUNT:
        raise ValueError("pilot v3 staged question count mismatch")
    for row in rows:
        expected = expected_by_id.get(str(row["id"]))
        stored = db.json_load(row["raw_json"], {})
        if expected is None or canonical_sha256(stored) != canonical_sha256(expected):
            raise ValueError(f"pilot v3 staged question mismatch: {row['id']}")
    return dict(ledger)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quick_check(conn: sqlite3.Connection, *, label: str) -> None:
    rows = [str(row[0]) for row in conn.execute("pragma quick_check").fetchall()]
    if rows != ["ok"]:
        raise ValueError(f"{label} database quick_check failed: {'; '.join(rows)}")


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / (
        f"{db_path.stem}.pre-three-node-pilot-v3.{stamp}.{uuid.uuid4().hex[:8]}.sqlite"
    )
    if backup_path.exists():
        raise ValueError("pilot backup path collision")
    source = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(str(backup_path))
    try:
        _quick_check(source, label="source")
        source.backup(target)
        target.commit()
        _quick_check(target, label="backup")
    finally:
        target.close()
        source.close()
    backup_sha256 = _file_sha256(backup_path)
    if len(backup_sha256) != 64 or not backup_path.stat().st_size:
        raise ValueError("pilot backup SHA-256 verification failed")
    return backup_path


def _require_current_production_schema(conn: sqlite3.Connection) -> None:
    required_columns = {
        "system_meta": {"key", "value"},
        "question_bank_version_ledger": {
            "id",
            "question_bank_version",
            "graph_version",
            "manifest_id",
            "manifest_sha256",
            "node_count",
            "item_count",
            "status",
        },
        "question_items": {"id", "item_version", "raw_json", "source_json"},
        "question_review_records": {
            "id",
            "question_id",
            "item_version",
            "candidate_sha256",
            "review_status",
            "active_eligible",
        },
        "question_usage_policies": {"question_id", "item_version", "status"},
        "answer_contracts": {
            "id",
            "question_id",
            "item_version",
            "graph_version",
            "question_bank_version",
            "contract_digest_sha256",
            "question_digest_sha256",
            "review_record_id",
            "status",
        },
        "agent_runs": {"id", "agent_key", "status"},
        "daily_flows": {"id", "status"},
        "background_jobs": {"id", "status"},
        "learning_target_intents": {"id", "status"},
    }
    missing: list[str] = []
    for table, expected_columns in required_columns.items():
        columns = {
            str(row[1])
            for row in conn.execute(f"pragma table_info({table})").fetchall()
        }
        if not columns:
            missing.append(table)
            continue
        absent = sorted(expected_columns - columns)
        if absent:
            missing.append(f"{table}({','.join(absent)})")
    if missing:
        raise ValueError(
            "production database schema is not current; migrate separately before cutover: "
            + ",".join(missing)
        )


def _predecessor_problem_instance_ids() -> tuple[dict[str, str], set[str]]:
    raw_bytes = PREDECESSOR_MANIFEST.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != PILOT_PREVIOUS_MANIFEST_SHA256:
        raise ValueError("predecessor authority manifest SHA-256 mismatch")
    manifest = json.loads(raw_bytes.decode("utf-8"))
    if (
        manifest.get("schema_version") != PILOT_PREVIOUS_VERSION
        or manifest.get("question_bank_version") != PILOT_PREVIOUS_VERSION
        or manifest.get("manifest_id") != PILOT_PREVIOUS_MANIFEST_ID
        or manifest.get("item_count") != PILOT_ITEM_COUNT
    ):
        raise ValueError("predecessor authority manifest identity mismatch")
    raw_items = manifest.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != PILOT_ITEM_COUNT:
        raise ValueError("predecessor authority manifest item count mismatch")
    held_ids = {str(value) for value in manifest.get("held_item_ids") or []}
    predecessor_ids = manifest.get("predecessor_question_ids") or {}
    if not isinstance(predecessor_ids, dict):
        raise ValueError("predecessor authority lineage is malformed")
    item_ids = {str(item.get("id") or "") for item in raw_items if isinstance(item, dict)}
    if not set(predecessor_ids).issubset(item_ids):
        raise ValueError("predecessor authority lineage references an unknown item")
    expected: dict[str, str] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("predecessor authority item is malformed")
        question_id = _require_nonempty_text(raw.get("id"), "predecessor.items[].id")
        instance_key = _require_nonempty_text(
            raw.get("problem_instance_key"),
            f"{question_id}.problem_instance_key",
        )
        predecessor_id = str(predecessor_ids.get(question_id) or "").strip()
        expected[question_id] = "PI-" + canonical_sha256(
            {
                "manifest_id": (
                    predecessor_manifest_id(predecessor_id)
                    if predecessor_id
                    else PILOT_PREVIOUS_MANIFEST_ID
                ),
                "question_id": predecessor_id or question_id,
                "problem_instance_key": instance_key,
            }
        )[:20]
    return expected, item_ids - held_ids


def _verify_predecessor_authority(
    conn: sqlite3.Connection,
    *,
    graph_version: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    active = _active_ledger_rows(conn)
    if len(active) != 1:
        raise ValueError("predecessor authority requires exactly one active ledger")
    ledger = dict(active[0])
    expected_ledger = {
        "question_bank_version": PILOT_PREVIOUS_VERSION,
        "graph_version": graph_version,
        "manifest_id": PILOT_PREVIOUS_MANIFEST_ID,
        "manifest_sha256": PILOT_PREVIOUS_MANIFEST_SHA256,
        "node_count": len(PILOT_NODE_IDS),
        "item_count": PILOT_ACTIVE_ITEM_COUNT,
    }
    mismatches = [
        key for key, expected in expected_ledger.items() if ledger[key] != expected
    ]
    if mismatches:
        raise ValueError(
            "predecessor authority ledger mismatch: " + ",".join(mismatches)
        )

    expected_instances, active_question_ids = _predecessor_problem_instance_ids()
    rows = conn.execute(
        "select * from question_items where item_version = ? order by id",
        (PILOT_PREVIOUS_VERSION,),
    ).fetchall()
    if {str(row["id"]) for row in rows} != active_question_ids:
        raise ValueError("predecessor authority question set mismatch")
    stored_instances: dict[str, str] = {}
    for row in rows:
        question = db.row_to_question(row)
        question_id = str(row["id"])
        source = question.get("source") if isinstance(question.get("source"), dict) else {}
        stored_instance = str(question.get("problem_instance_id") or "")
        if (
            stored_instance != expected_instances[question_id]
            or source.get("manifest_id") != PILOT_PREVIOUS_MANIFEST_ID
            or source.get("manifest_sha256") != PILOT_PREVIOUS_MANIFEST_SHA256
        ):
            raise ValueError(
                f"predecessor authority problem-instance mismatch: {question_id}"
            )
        stored_instances[question_id] = stored_instance
    for item in items:
        suffix = str(item["id"]).removeprefix("MATH-PILOT-V3")
        predecessor_question_id = "MATH-PILOT-V2" + suffix
        if expected_instances.get(predecessor_question_id) != item["problem_instance_id"]:
            raise ValueError(
                f"predecessor authority v3 identity mismatch: {item['id']}"
            )

    contract_rows = conn.execute(
        """
        select ac.*, q.node_id, r.candidate_sha256
        from answer_contracts ac
        join question_items q on q.id = ac.question_id
        join question_review_records r on r.id = ac.review_record_id
        where ac.question_bank_version = ? and ac.status = 'active'
        order by ac.question_id, ac.id
        """,
        (PILOT_PREVIOUS_VERSION,),
    ).fetchall()
    if (
        len(contract_rows) != PILOT_ACTIVE_ITEM_COUNT
        or {str(row["question_id"]) for row in contract_rows} != active_question_ids
        or any(str(row["graph_version"] or "") != graph_version for row in contract_rows)
    ):
        raise ValueError("predecessor authority active contract set mismatch")
    commitments = [
        {
            "question_id": row["question_id"],
            "item_version": row["item_version"],
            "node_id": row["node_id"],
            "question_digest_sha256": row["question_digest_sha256"],
            "review_record_id": row["review_record_id"],
            "candidate_sha256": row["candidate_sha256"],
            "contract_id": row["id"],
            "contract_version": row["contract_version"],
            "contract_digest_sha256": row["contract_digest_sha256"],
        }
        for row in contract_rows
    ]
    receipt_row = conn.execute(
        "select value from system_meta where key = ?",
        (knowledge_map.ASSESSMENT_RECEIPT_KEY,),
    ).fetchone()
    receipt = db.json_load(receipt_row["value"], {}) if receipt_row else {}
    claimed_digest = str(receipt.get("receipt_digest_sha256") or "")
    receipt_body = {
        key: value for key, value in receipt.items() if key != "receipt_digest_sha256"
    }
    if (
        claimed_digest != canonical_sha256(receipt_body)
        or receipt.get("status") != "active"
        or receipt.get("question_bank_ledger_id") != ledger["id"]
        or receipt.get("question_bank_version") != PILOT_PREVIOUS_VERSION
        or receipt.get("graph_lineage") != graph_version
        or int(receipt.get("active_contract_count") or 0) != PILOT_ACTIVE_ITEM_COUNT
        or receipt.get("contract_set_digest_sha256")
        != canonical_sha256(commitments)
    ):
        raise ValueError("predecessor authority assessment receipt mismatch")
    return ledger


def _contract_question(conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        "select * from question_items where id = ? and item_version = ?",
        (item["id"], item["item_version"]),
    ).fetchone()
    if not row:
        raise ValueError(f"pilot question was not persisted: {item['id']}")
    question = db.row_to_question(row)
    review = conn.execute(
        """
        select id, candidate_sha256
        from question_review_records
        where question_id = ? and item_version = ?
          and review_status = 'approved' and active_eligible = 1
        """,
        (item["id"], item["item_version"]),
    ).fetchall()
    if len(review) != 1:
        raise ValueError(f"pilot question does not have exactly one approved review: {item['id']}")
    question["_active_review_record_id"] = review[0]["id"]
    question["_active_candidate_sha256"] = review[0]["candidate_sha256"]
    return question


def _write_contracts_and_receipt(
    conn: sqlite3.Connection,
    *,
    items: list[dict[str, Any]],
    ledger: dict[str, Any],
    graph_version: str,
) -> dict[str, Any]:
    active_items = [item for item in items if item.get("activation_status") == "active"]
    contracts = [
        build_contract(_contract_question(conn, item), graph_version, PILOT_VERSION)
        for item in active_items
    ]
    now = db.now_iso()
    for contract in contracts:
        review_receipt = {
            "activation_mode": "lightweight_local_contracts_v1",
            "provider_mode": "deterministic_runtime",
            "review_scope": "expert_reviewed_pilot_manifest_and_current_question_review",
            "manifest_id": PILOT_MANIFEST_ID,
        }
        conn.execute(
            """
            insert into answer_contracts(
              id, stable_contract_id, question_id, item_version,
              contract_version, contract_digest_sha256,
              question_digest_sha256, graph_version, question_bank_version,
              reference_solution_json, score_points_json,
              generator_version, review_record_id, review_receipt_json,
              review_receipt_sha256, fingerprint_policy_version,
              prompt_instance_fingerprint, core_structure_fingerprint,
              status, approved_at, activated_at, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      'active', ?, ?, ?, ?)
            """,
            (
                contract["id"],
                contract["stable_contract_id"],
                contract["question_id"],
                contract["item_version"],
                contract["contract_version"],
                contract["contract_digest_sha256"],
                contract["question_digest_sha256"],
                contract["graph_version"],
                contract["question_bank_version"],
                db.json_dump(contract["reference_solution"]),
                db.json_dump(contract["score_points"]),
                GENERATOR_VERSION,
                contract["review_record_id"],
                db.json_dump(review_receipt),
                canonical_sha256(review_receipt),
                contract["fingerprint_policy_version"],
                contract["prompt_instance_fingerprint"],
                contract["core_structure_fingerprint"],
                now,
                now,
                now,
                now,
            ),
        )
    receipt = receipt_for(graph_version=graph_version, ledger=ledger, contracts=contracts)
    sealed = {**receipt, "receipt_digest_sha256": canonical_sha256(receipt)}
    conn.execute(
        "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
        (knowledge_map.ASSESSMENT_RECEIPT_KEY, db.json_dump(sealed), now),
    )
    return sealed


def _verify_installation(
    conn: sqlite3.Connection,
    *,
    items: list[dict[str, Any]],
    manifest_sha256: str,
    graph_version: str,
) -> dict[str, Any]:
    active = _active_ledger_rows(conn)
    if len(active) != 1 or active[0]["question_bank_version"] != PILOT_VERSION:
        raise ValueError("pilot activation requires exactly one active pilot ledger")
    ledger = dict(active[0])
    expected_ledger = {
        "manifest_id": PILOT_MANIFEST_ID,
        "manifest_sha256": manifest_sha256,
        "graph_version": graph_version,
        "node_count": len(PILOT_NODE_IDS),
        "item_count": PILOT_ACTIVE_ITEM_COUNT,
    }
    mismatches = [key for key, value in expected_ledger.items() if ledger[key] != value]
    if mismatches:
        raise ValueError("pilot ledger identity mismatch: " + ",".join(mismatches))
    rows = conn.execute(
        "select * from question_items where item_version = ? order by id", (PILOT_VERSION,)
    ).fetchall()
    if len(rows) != PILOT_ACTIVE_ITEM_COUNT:
        raise ValueError(
            f"pilot database does not contain exactly {PILOT_ACTIVE_ITEM_COUNT} active questions"
        )
    expected_by_id = {
        item["id"]: item
        for item in items
        if item.get("activation_status") == "active"
    }
    for row in rows:
        expected = expected_by_id.get(str(row["id"]))
        stored = db.json_load(row["raw_json"], {})
        if expected is None or canonical_sha256(stored) != canonical_sha256(expected):
            raise ValueError(f"pilot question identity/content mismatch: {row['id']}")
        question = db.row_to_question(row)
        if question.get("problem_instance_id") != expected["problem_instance_id"]:
            raise ValueError(f"pilot problem-instance identity mismatch: {row['id']}")
        is_schedulable = db.is_child_schedulable_question(
            conn, question, question_bank_version=PILOT_VERSION
        )
        if not is_schedulable:
            raise ValueError(f"pilot question activation mismatch: {row['id']}")
        policy = db.active_question_usage_policy(
            conn, str(row["id"]), item_version=PILOT_VERSION
        )
        if not policy or policy["policy_digest_sha256"] != question_usage.policy_digest(
            expected["usage_policy"]
        ):
            raise ValueError(f"pilot usage policy mismatch: {row['id']}")
        contracts = conn.execute(
            """
            select score_points_json from answer_contracts
            where question_id = ? and item_version = ? and status = 'active'
            """,
            (row["id"], PILOT_VERSION),
        ).fetchall()
        if len(contracts) != 1:
            raise ValueError(f"pilot answer contract count mismatch: {row['id']}")
        if contracts:
            points = db.json_load(contracts[0]["score_points_json"], [])
            if sum(int(point.get("points") or 0) for point in points) != 10:
                raise ValueError(f"pilot answer contract is not 10 points: {row['id']}")
    receipt_row = conn.execute(
        "select value from system_meta where key = ?",
        (knowledge_map.ASSESSMENT_RECEIPT_KEY,),
    ).fetchone()
    receipt = db.json_load(receipt_row["value"], {}) if receipt_row else {}
    claimed = str(receipt.get("receipt_digest_sha256") or "")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest_sha256"}
    if (
        claimed != canonical_sha256(body)
        or receipt.get("question_bank_ledger_id") != ledger["id"]
        or receipt.get("question_bank_version") != PILOT_VERSION
        or int(receipt.get("active_contract_count") or 0) != PILOT_ACTIVE_ITEM_COUNT
    ):
        raise ValueError("pilot assessment activation receipt mismatch")
    return ledger


def activate(
    db_path: Path,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    project_root: Path = PROJECT_ROOT,
    allow_production_cutover: bool = False,
    expected_current_version: str | None = None,
    backup_dir: Path | None = None,
    stage_only: bool = False,
) -> dict[str, Any]:
    manifest, items, manifest_sha256 = load_pilot(
        manifest_path, project_root=project_root
    )
    resolved_db_path = db_path.expanduser().resolve()
    production_cutover = resolved_db_path == PRODUCTION_DB
    if production_cutover and not allow_production_cutover:
        raise ValueError("three-node pilot activation refuses the canonical production database")
    expected_current_version = (
        expected_current_version
        if expected_current_version is not None
        else (PILOT_PREVIOUS_VERSION if production_cutover else None)
    )
    backup_path: Path | None = None
    backup_sha256 = ""
    if production_cutover and not resolved_db_path.exists():
        raise ValueError("production cutover requires an existing database")
    if production_cutover and expected_current_version != PILOT_PREVIOUS_VERSION:
        raise ValueError(
            "production cutover requires the immutable v2 predecessor authority"
        )
    if production_cutover:
        backup_path = _backup_database(
            resolved_db_path,
            backup_dir or project_root / "data/backups",
        )
        backup_sha256 = _file_sha256(backup_path)
    else:
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(resolved_db_path)
    try:
        if production_cutover:
            _require_current_production_schema(conn)
        else:
            _reject_nonisolated_database(conn)
            db.init_schema(conn)
            db.seed_from_assets(conn, project_root)
        graph_ref_row = conn.execute(
            "select value from system_meta where key = 'graph_ref'"
        ).fetchone()
        graph_ref = db.json_load(graph_ref_row["value"], {}) if graph_ref_row else {}
        graph_version = str(graph_ref.get("lineage") or "")
        if not graph_version:
            raise ValueError("pilot activation requires seeded graph lineage")
        for item in items:
            question_bank.apply_question_lineage(
                item,
                graph_version=graph_version,
                question_bank_version=PILOT_VERSION,
            )

        active = _active_ledger_rows(conn)
        current_version = str(active[0]["question_bank_version"]) if len(active) == 1 else None
        if len(active) > 1:
            raise ValueError("pilot activation found multiple active question-bank ledgers")
        if current_version == PILOT_VERSION:
            ledger = _verify_installation(
                conn,
                items=items,
                manifest_sha256=manifest_sha256,
                graph_version=graph_version,
            )
            return {
                "status": "already_active",
                "question_bank_version": PILOT_VERSION,
                "ledger_id": ledger["id"],
                "item_count": PILOT_ACTIVE_ITEM_COUNT,
                "manifest_item_count": PILOT_ITEM_COUNT,
                "node_count": len(PILOT_NODE_IDS),
                "backup": str(backup_path) if backup_path else "",
                "backup_sha256": backup_sha256,
            }
        if production_cutover:
            _verify_predecessor_authority(
                conn,
                graph_version=graph_version,
                items=items,
            )
        elif active:
            raise ValueError(
                "pilot cutover active version mismatch: "
                f"expected {expected_current_version}, got {current_version}"
            )

        existing_rows = conn.execute("select id from question_items").fetchall()
        existing_ledgers = conn.execute("select id from question_bank_version_ledger").fetchall()
        candidate_row_count = conn.execute(
            "select count(*) from question_items where item_version = ?",
            (PILOT_VERSION,),
        ).fetchone()[0]
        candidate_ledger_count = conn.execute(
            "select count(*) from question_bank_version_ledger where question_bank_version = ?",
            (PILOT_VERSION,),
        ).fetchone()[0]
        if (candidate_row_count == 0) != (candidate_ledger_count == 0):
            raise ValueError("incomplete v3 staged state requires manual recovery")
        if (
            not production_cutover
            and (existing_rows or existing_ledgers)
            and candidate_row_count == 0
        ):
            raise ValueError("incomplete pilot state is not eligible for automatic activation")
        if candidate_row_count == 0:
            with conn:
                staged = _stage_items(
                    conn,
                    manifest=manifest,
                    items=items,
                    manifest_sha256=manifest_sha256,
                    graph_version=graph_version,
                )
        else:
            staged = _verify_staged_installation(
                conn,
                items=items,
                manifest_sha256=manifest_sha256,
                graph_version=graph_version,
            )

        blockers = _runtime_cutover_blockers(conn) if production_cutover else {
            "daily_flows": [],
            "background_jobs": [],
            "learning_target_intents": [],
        }
        has_blockers = any(blockers.values())
        if stage_only or (production_cutover and has_blockers):
            return {
                "status": (
                    "staged_waiting_for_safe_boundary" if has_blockers else "staged"
                ),
                "question_bank_version": PILOT_VERSION,
                "ledger_id": staged["id"],
                "item_count": PILOT_ACTIVE_ITEM_COUNT,
                "manifest_item_count": PILOT_ITEM_COUNT,
                "node_count": len(PILOT_NODE_IDS),
                "previous_question_bank_version": current_version or "",
                "blockers": blockers,
                "backup": str(backup_path) if backup_path else "",
                "backup_sha256": backup_sha256,
            }

        conn.execute("begin immediate")
        try:
            if production_cutover:
                _verify_predecessor_authority(
                    conn,
                    graph_version=graph_version,
                    items=items,
                )
                blockers = _runtime_cutover_blockers(conn)
                if any(blockers.values()):
                    conn.rollback()
                    return {
                        "status": "staged_waiting_for_safe_boundary",
                        "question_bank_version": PILOT_VERSION,
                        "ledger_id": staged["id"],
                        "item_count": PILOT_ACTIVE_ITEM_COUNT,
                        "manifest_item_count": PILOT_ITEM_COUNT,
                        "node_count": len(PILOT_NODE_IDS),
                        "previous_question_bank_version": current_version or "",
                        "blockers": blockers,
                        "backup": str(backup_path) if backup_path else "",
                        "backup_sha256": backup_sha256,
                    }
            ledger = db.activate_question_bank_version(
                conn,
                question_bank_version=PILOT_VERSION,
                expected_current_version=current_version,
                reason=(
                    "production cutover to expert-reviewed three-node pilot v3"
                    if production_cutover
                    else "isolated activation of expert-reviewed three-node pilot"
                ),
                commit=False,
            )
            _write_contracts_and_receipt(
                conn,
                items=items,
                ledger=ledger,
                graph_version=graph_version,
            )
            _verify_installation(
                conn,
                items=items,
                manifest_sha256=manifest_sha256,
                graph_version=graph_version,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return {
            "status": "activated",
            "question_bank_version": PILOT_VERSION,
            "ledger_id": staged["id"],
            "item_count": PILOT_ACTIVE_ITEM_COUNT,
            "manifest_item_count": PILOT_ITEM_COUNT,
            "active_item_count": PILOT_ACTIVE_ITEM_COUNT,
            "node_count": len(PILOT_NODE_IDS),
            "previous_question_bank_version": current_version or "",
            "backup": str(backup_path) if backup_path else "",
            "backup_sha256": backup_sha256,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Activate the expert-reviewed three-node math pilot in an isolated DB."
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-production-cutover", action="store_true")
    parser.add_argument("--stage-only", action="store_true")
    parser.add_argument("--expected-current-version", default=None)
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=PROJECT_ROOT / "data/backups",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = activate(
            args.db,
            manifest_path=args.manifest,
            allow_production_cutover=args.allow_production_cutover,
            expected_current_version=args.expected_current_version,
            backup_dir=args.backup_dir,
            stage_only=args.stage_only,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        error = {"status": "error", "error": str(exc)}
        print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
