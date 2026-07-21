from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import knowledge_cards


GENERATION_RULES_SCHEMA_VERSION = "knowledge-card-generation-rules.v1"
GENERATION_RULES_PATH = Path("data/knowledge_cards/generation_rules.v1.json")
GENERATION_PACKET_SCHEMA_VERSION = "knowledge-card-generation-packet.v1"
GENERATION_BATCH_PLAN_SCHEMA_VERSION = "knowledge-card-generation-batch-plan.v1"
REVIEW_REPORT_SCHEMA_VERSION = "knowledge-card-draft-review.v1"


class KnowledgeCardGenerationError(ValueError):
    pass


def _canonical_digest(value: Any) -> str:
    return knowledge_cards._canonical_sha256(value)


def _project_root(project_root: Path | str | None = None) -> Path:
    return Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]


def _graph_payload(project_root: Path | str | None = None) -> dict[str, Any]:
    root = _project_root(project_root)
    payload = json.loads((root / knowledge_cards.MATH_GRAPH_PATH).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise KnowledgeCardGenerationError("math graph must be an object")
    return payload


def _graph_node_index(project_root: Path | str | None = None) -> dict[str, dict[str, Any]]:
    payload = _graph_payload(project_root)
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise KnowledgeCardGenerationError("math graph has no nodes")
    index: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"].strip():
            index[node["id"]] = node
    return index


def draft_card_inventory(project_root: Path | str | None = None) -> dict[str, Any]:
    root = _project_root(project_root)
    registry = knowledge_cards.load_component_registry(root)
    cards_root = root / knowledge_cards.CARD_ROOT
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for path in sorted(cards_root.glob("*.v2.draft.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            card = knowledge_cards.validate_knowledge_card_v2(payload, registry=registry)
            valid.append({
                "node_id": str(card["node_id"]),
                "card_version": str(card["card_version"]),
                "source": str(path.relative_to(root)),
            })
        except (OSError, json.JSONDecodeError, knowledge_cards.KnowledgeCardError) as exc:
            invalid.append({
                "source": str(path.relative_to(root)),
                "reason": str(exc),
            })
    return {
        "schema_version": "knowledge-card-draft-inventory.v1",
        "valid_draft_count": len(valid),
        "invalid_draft_count": len(invalid),
        "valid_drafts": valid,
        "invalid_drafts": invalid,
    }


def validate_generation_rules(rules: Any, *, registry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(rules, dict):
        raise KnowledgeCardGenerationError("generation rules must be an object")
    if rules.get("schema_version") != GENERATION_RULES_SCHEMA_VERSION:
        raise KnowledgeCardGenerationError("generation rules schema_version mismatch")
    if not isinstance(rules.get("rules_version"), str) or not rules["rules_version"].strip():
        raise KnowledgeCardGenerationError("generation rules rules_version is missing")
    cognitive_objects = set(registry.get("cognitive_objects", {}))
    defaults = rules.get("taxonomy_defaults")
    if not isinstance(defaults, dict) or not defaults:
        raise KnowledgeCardGenerationError("generation rules taxonomy_defaults missing")
    unknown_defaults = sorted(set(defaults.values()) - cognitive_objects)
    if unknown_defaults:
        raise KnowledgeCardGenerationError(f"unknown taxonomy default cognitive objects: {unknown_defaults}")
    overrides = rules.get("node_overrides")
    if not isinstance(overrides, dict):
        raise KnowledgeCardGenerationError("generation rules node_overrides must be an object")
    unknown_overrides = sorted(set(overrides.values()) - cognitive_objects)
    if unknown_overrides:
        raise KnowledgeCardGenerationError(f"unknown node override cognitive objects: {unknown_overrides}")
    gates = rules.get("review_gates")
    if not isinstance(gates, dict):
        raise KnowledgeCardGenerationError("generation rules review_gates missing")
    for key in (
        "requires_design_brief_before_child_card",
        "requires_child_action_evidence",
        "reject_text_only_template",
        "reject_decorative_interaction",
        "requires_direct_prerequisite_coverage",
    ):
        if not isinstance(gates.get(key), bool):
            raise KnowledgeCardGenerationError(f"review_gates.{key} must be boolean")
    if not isinstance(gates.get("min_storyboard_components"), int) or gates["min_storyboard_components"] < 1:
        raise KnowledgeCardGenerationError("review_gates.min_storyboard_components is invalid")
    if not isinstance(gates.get("max_default_sequence_components"), int) or gates["max_default_sequence_components"] < 1:
        raise KnowledgeCardGenerationError("review_gates.max_default_sequence_components is invalid")
    return rules


def load_generation_rules(project_root: Path | str | None = None) -> dict[str, Any]:
    root = _project_root(project_root)
    registry = knowledge_cards.load_component_registry(root)
    payload = json.loads((root / GENERATION_RULES_PATH).read_text(encoding="utf-8"))
    return validate_generation_rules(payload, registry=registry)


def _compact_node(node: dict[str, Any]) -> dict[str, Any]:
    taxonomy = node.get("taxonomy") if isinstance(node.get("taxonomy"), dict) else {}
    return {
        "node_id": str(node.get("id") or ""),
        "name": str(node.get("name") or ""),
        "stage": str(node.get("stage") or ""),
        "domain": str(node.get("domain") or ""),
        "priority": str(node.get("priority") or ""),
        "module_id": str(taxonomy.get("module_id") or "UNKNOWN"),
        "module_name": str(taxonomy.get("module_name") or node.get("domain") or "未归类"),
        "concept_type": str(taxonomy.get("concept_type") or ""),
        "chapter_anchor": str(taxonomy.get("chapter_anchor") or ""),
        "essence_for_child": str(node.get("essence_for_child") or ""),
    }


def _linked_nodes(node_ids: list[Any], index: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    linked: list[dict[str, str]] = []
    for node_id in node_ids:
        node = index.get(str(node_id or ""))
        if node:
            linked.append({
                "node_id": str(node["id"]),
                "name": str(node.get("name") or ""),
            })
    return linked


def _candidate_cognitive_object(
    node: dict[str, Any],
    *,
    rules: dict[str, Any],
) -> dict[str, str]:
    node_id = str(node.get("id") or "")
    overrides = rules.get("node_overrides") if isinstance(rules.get("node_overrides"), dict) else {}
    if node_id in overrides:
        return {
            "cognitive_object": str(overrides[node_id]),
            "source": "node_override",
            "confidence": "high",
        }
    taxonomy = node.get("taxonomy") if isinstance(node.get("taxonomy"), dict) else {}
    concept_type = str(taxonomy.get("concept_type") or "")
    defaults = rules.get("taxonomy_defaults") if isinstance(rules.get("taxonomy_defaults"), dict) else {}
    if concept_type in defaults:
        return {
            "cognitive_object": str(defaults[concept_type]),
            "source": f"taxonomy_default:{concept_type}",
            "confidence": "medium",
        }
    return {
        "cognitive_object": "quantity_relation_modeling",
        "source": "fallback_requires_review",
        "confidence": "low",
    }


def build_generation_packet_for_node(
    node_id: str,
    *,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    registry = knowledge_cards.load_component_registry(root)
    rules = load_generation_rules(root)
    index = _graph_node_index(root)
    node = index.get(str(node_id or ""))
    if not node:
        raise KnowledgeCardGenerationError(f"unknown graph node: {node_id}")
    candidate = _candidate_cognitive_object(node, rules=rules)
    cognitive_object = candidate["cognitive_object"]
    default_components = registry["cognitive_objects"][cognitive_object]["default_components"]
    prerequisites = _linked_nodes(node.get("prerequisites") if isinstance(node.get("prerequisites"), list) else [], index)
    unlocks = _linked_nodes(node.get("unlocks") if isinstance(node.get("unlocks"), list) else [], index)
    packet: dict[str, Any] = {
        "schema_version": GENERATION_PACKET_SCHEMA_VERSION,
        "rules_version": rules["rules_version"],
        "graph_node": _compact_node(node),
        "graph_context": {
            "prerequisites": prerequisites,
            "unlocks": unlocks,
        },
        "teaching_inputs": {
            "teaching_contract": node.get("teaching_contract") if isinstance(node.get("teaching_contract"), dict) else {},
            "question_generation": node.get("question_generation") if isinstance(node.get("question_generation"), dict) else {},
            "mastery_criteria": node.get("mastery_criteria") if isinstance(node.get("mastery_criteria"), list) else [],
            "common_mistakes": node.get("common_mistakes") if isinstance(node.get("common_mistakes"), list) else [],
            "question_types": node.get("question_types") if isinstance(node.get("question_types"), list) else [],
        },
        "diagnosis_inputs": {
            "diagnosis_contract": node.get("diagnosis_contract") if isinstance(node.get("diagnosis_contract"), dict) else {},
            "error_diagnosis": node.get("error_diagnosis") if isinstance(node.get("error_diagnosis"), dict) else {},
        },
        "generation_guidance": {
            **candidate,
            "default_components": default_components,
            "component_contracts": {
                component_type: registry["component_types"][component_type]
                for component_type in default_components
                if component_type in registry["component_types"]
            },
            "required_output_schema": knowledge_cards.V2_CARD_SCHEMA_VERSION,
        },
        "review_gates": rules["review_gates"],
    }
    packet["generation_input_digest_sha256"] = _canonical_digest(packet)
    return packet


def plan_generation_batch(
    *,
    project_root: Path | str | None = None,
    limit: int = 5,
    module_id: str | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    coverage = knowledge_cards.knowledge_card_coverage_report(root)
    draft_inventory = draft_card_inventory(root)
    drafted_node_ids = {item["node_id"] for item in draft_inventory["valid_drafts"]}
    graph_nodes = knowledge_cards.load_math_graph_nodes(root)
    missing_ids = {item["node_id"] for item in coverage["missing_cards"]}
    selected: list[dict[str, Any]] = []
    for graph_node in graph_nodes:
        if graph_node["id"] not in missing_ids:
            continue
        if graph_node["id"] in drafted_node_ids:
            continue
        if module_id and graph_node["module_id"] != module_id:
            continue
        packet = build_generation_packet_for_node(graph_node["id"], project_root=root)
        guidance = packet["generation_guidance"]
        selected.append({
            "node_id": graph_node["id"],
            "name": graph_node["name"],
            "module_id": graph_node["module_id"],
            "module_name": graph_node["module_name"],
            "cognitive_object": guidance["cognitive_object"],
            "cognitive_object_source": guidance["source"],
            "confidence": guidance["confidence"],
            "default_components": guidance["default_components"][:5],
            "generation_input_digest_sha256": packet["generation_input_digest_sha256"],
        })
        if len(selected) >= max(1, limit):
            break
    return {
        "schema_version": GENERATION_BATCH_PLAN_SCHEMA_VERSION,
        "coverage": {
            "total_graph_nodes": coverage["total_graph_nodes"],
            "active_card_count": coverage["active_card_count"],
            "missing_card_count": coverage["missing_card_count"],
            "invalid_card_count": coverage["invalid_card_count"],
            "valid_draft_count": draft_inventory["valid_draft_count"],
            "invalid_draft_count": draft_inventory["invalid_draft_count"],
        },
        "limit": max(1, limit),
        "module_id": module_id or "",
        "items": selected,
    }


def _issue(code: str, message: str, *, severity: str = "blocking") -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
    }


def review_draft_v2(
    card: Any,
    *,
    project_root: Path | str | None = None,
    expected_node_id: str | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    registry = knowledge_cards.load_component_registry(root)
    rules = load_generation_rules(root)
    issues: list[dict[str, str]] = []
    try:
        validated = knowledge_cards.validate_knowledge_card_v2(
            card,
            registry=registry,
            expected_node_id=expected_node_id,
        )
    except (knowledge_cards.KnowledgeCardError, ValueError, TypeError) as exc:
        return {
            "schema_version": REVIEW_REPORT_SCHEMA_VERSION,
            "node_id": str(expected_node_id or (card.get("node_id") if isinstance(card, dict) else "") or ""),
            "verdict": "rejected",
            "issues": [_issue("schema_invalid", str(exc))],
        }
    node_id = str(validated["node_id"])
    index = _graph_node_index(root)
    node = index.get(node_id)
    if not node:
        issues.append(_issue("unknown_graph_node", "Draft node_id is not present in the active graph."))
    else:
        direct_prerequisites = set(str(item) for item in node.get("prerequisites", []) if str(item).strip())
        draft_prerequisites = set(str(item) for item in validated["graph_binding"].get("prerequisite_node_ids", []))
        missing_prerequisites = sorted(direct_prerequisites - draft_prerequisites)
        if rules["review_gates"]["requires_direct_prerequisite_coverage"] and missing_prerequisites:
            issues.append(_issue(
                "missing_direct_prerequisites",
                f"Draft graph_binding omitted direct prerequisites: {', '.join(missing_prerequisites)}.",
            ))
        graph_unlocks = set(str(item) for item in node.get("unlocks", []) if str(item).strip())
        draft_unlocks = set(str(item) for item in validated["graph_binding"].get("unlocks_node_ids", []))
        extra_unlocks = sorted(draft_unlocks - graph_unlocks)
        if extra_unlocks:
            issues.append(_issue(
                "extra_unlocks_need_review",
                f"Draft unlocks are not direct graph unlocks and need explicit review: {', '.join(extra_unlocks)}.",
                severity="warning",
            ))
        expected_object = _candidate_cognitive_object(node, rules=rules)
        actual_object = str(validated["design_brief"]["cognitive_object"])
        if (
            expected_object["confidence"] == "high"
            and actual_object != expected_object["cognitive_object"]
        ):
            issues.append(_issue(
                "cognitive_object_override_mismatch",
                f"Expected {expected_object['cognitive_object']} from generation rules, got {actual_object}.",
            ))
    storyboard = validated["component_storyboard"]
    gates = rules["review_gates"]
    if len(storyboard) < gates["min_storyboard_components"]:
        issues.append(_issue(
            "too_few_storyboard_components",
            "Draft is too short to establish model, action evidence, and repair path.",
        ))
    component_types = [str(component.get("type") or "") for component in storyboard]
    evidence_actions = [
        component for component in storyboard
        if component.get("target_evidence")
        and registry["component_types"][str(component.get("type"))]["child_action_required"]
    ]
    if gates["requires_child_action_evidence"] and not evidence_actions:
        issues.append(_issue(
            "no_child_action_evidence",
            "Draft has no evidence-producing child action.",
        ))
    text_only_types = {"text_explanation", "worked_example"}
    if gates["reject_text_only_template"] and set(component_types) <= text_only_types:
        issues.append(_issue(
            "text_only_template",
            "Draft is only explanation/example text; it cannot confirm understanding.",
        ))
    default_sequence = validated["child_card"]["default_sequence"]
    if len(default_sequence) > gates["max_default_sequence_components"]:
        issues.append(_issue(
            "default_sequence_too_long",
            "Child-facing sequence is too long for one knowledge card.",
        ))
    blocking = [issue for issue in issues if issue["severity"] == "blocking"]
    return {
        "schema_version": REVIEW_REPORT_SCHEMA_VERSION,
        "node_id": node_id,
        "card_version": validated["card_version"],
        "verdict": "accepted" if not blocking else "needs_fix",
        "issues": issues,
        "blocking_issue_count": len(blocking),
        "warning_count": len(issues) - len(blocking),
    }
