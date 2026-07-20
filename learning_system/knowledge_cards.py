from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CARD_SCHEMA_VERSION = "knowledge-card.v1"
V2_CARD_SCHEMA_VERSION = "knowledge-card.v2"
COMPONENT_REGISTRY_SCHEMA_VERSION = "knowledge-card-component-registry.v1"
CARD_ROOT = Path("data/knowledge_cards/math")
COMPONENT_REGISTRY_PATH = Path("data/knowledge_cards/component_registry.v1.json")
ACTIVE_CARD_FILENAMES = {
    "M-G7-NUMBER-LINE": "M-G7-NUMBER-LINE.v1.json",
}
CHILD_CARD_ALLOWED_COMPONENT_TYPES = {
    "text_explanation",
    "number_line_visual",
    "drag_point_interaction",
    "worked_example",
    "compare_choice",
    "fill_blank",
    "micro_check",
    "voice_read_aloud",
    "mini_animation",
    "photo_answer_prompt",
    "common_mistake",
}
CHILD_FORBIDDEN_KEYS = {
    "node_id",
    "graph_lineage",
    "prerequisite_node_ids",
    "unlocks_node_ids",
    "internal_card",
    "teaching_goal",
    "core_evidence",
    "misconceptions",
    "runtime_rules",
    "question_selection_hints",
    "dimension",
    "tag",
    "signal",
    "repair",
}


class KnowledgeCardError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeCardError(f"{path} must be a non-empty string")
    return value.strip()


def _require_string_list(value: Any, path: str, *, min_items: int = 1) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) < min_items
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise KnowledgeCardError(f"{path} must be a non-empty string list")
    return [str(item).strip() for item in value]


def _assert_no_child_forbidden_keys(value: Any, *, path: str = "child_card") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in CHILD_FORBIDDEN_KEYS:
                raise KnowledgeCardError(f"{path}.{key} leaks internal knowledge-card data")
            _assert_no_child_forbidden_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_child_forbidden_keys(item, path=f"{path}[{index}]")


def _validate_teaching_sections(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise KnowledgeCardError(f"{path} must be a non-empty object")
    required = {"essence", "core_model", "worked_example", "next_micro_check"}
    if not required <= set(value):
        raise KnowledgeCardError(f"{path} missing required sections")
    for key in required:
        section = value.get(key)
        if not isinstance(section, dict):
            raise KnowledgeCardError(f"{path}.{key} must be an object")
        _require_non_empty_string(section.get("title"), f"{path}.{key}.title")
    worked = value["worked_example"]
    _require_non_empty_string(worked.get("problem"), f"{path}.worked_example.problem")
    _require_string_list(worked.get("steps"), f"{path}.worked_example.steps")
    _require_non_empty_string(value["next_micro_check"].get("prompt"), f"{path}.next_micro_check.prompt")
    return value


def validate_component_registry(registry: Any) -> dict[str, Any]:
    if not isinstance(registry, dict):
        raise KnowledgeCardError("component registry must be an object")
    if registry.get("schema_version") != COMPONENT_REGISTRY_SCHEMA_VERSION:
        raise KnowledgeCardError("component registry schema_version mismatch")
    _require_non_empty_string(registry.get("registry_version"), "registry_version")
    cognitive_objects = registry.get("cognitive_objects")
    if not isinstance(cognitive_objects, dict) or not cognitive_objects:
        raise KnowledgeCardError("cognitive_objects must be a non-empty object")
    component_types = registry.get("component_types")
    if not isinstance(component_types, dict) or not component_types:
        raise KnowledgeCardError("component_types must be a non-empty object")
    required_storyboard_fields = _require_string_list(
        registry.get("required_storyboard_fields"),
        "required_storyboard_fields",
    )
    for key, value in cognitive_objects.items():
        if not isinstance(value, dict):
            raise KnowledgeCardError(f"cognitive_objects.{key} must be an object")
        _require_non_empty_string(value.get("label"), f"cognitive_objects.{key}.label")
        _require_string_list(value.get("default_components"), f"cognitive_objects.{key}.default_components")
    for component_type, value in component_types.items():
        if not isinstance(value, dict):
            raise KnowledgeCardError(f"component_types.{component_type} must be an object")
        family = _require_non_empty_string(value.get("family"), f"component_types.{component_type}.family")
        if family != "general" and family not in cognitive_objects:
            raise KnowledgeCardError(f"component_types.{component_type}.family is unknown")
        if not isinstance(value.get("child_action_required"), bool):
            raise KnowledgeCardError(f"component_types.{component_type}.child_action_required must be boolean")
        _require_string_list(value.get("allowed_tasks"), f"component_types.{component_type}.allowed_tasks")
        examples = value.get("evidence_examples")
        if not isinstance(examples, list) or not all(isinstance(item, str) for item in examples):
            raise KnowledgeCardError(f"component_types.{component_type}.evidence_examples must be a string list")
    for object_id, value in cognitive_objects.items():
        for component_type in value["default_components"]:
            if component_type not in component_types:
                raise KnowledgeCardError(f"cognitive_objects.{object_id} references unknown component {component_type}")
    if not {"component_id", "type", "purpose", "child_action", "target_evidence"} <= set(required_storyboard_fields):
        raise KnowledgeCardError("required_storyboard_fields is missing core fields")
    return registry


def load_component_registry(project_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    payload = json.loads((root / COMPONENT_REGISTRY_PATH).read_text(encoding="utf-8"))
    return validate_component_registry(payload)


def validate_knowledge_card_v2(
    card: Any,
    *,
    registry: dict[str, Any],
    expected_node_id: str | None = None,
) -> dict[str, Any]:
    registry = validate_component_registry(registry)
    if not isinstance(card, dict):
        raise KnowledgeCardError("knowledge card v2 must be an object")
    if card.get("schema_version") != V2_CARD_SCHEMA_VERSION:
        raise KnowledgeCardError("knowledge card v2 schema_version mismatch")
    node_id = _require_non_empty_string(card.get("node_id"), "node_id")
    if expected_node_id and node_id != expected_node_id:
        raise KnowledgeCardError("knowledge card v2 node_id mismatch")
    _require_non_empty_string(card.get("card_version"), "card_version")
    if card.get("status") not in {"draft", "active", "archived"}:
        raise KnowledgeCardError("knowledge card v2 status is invalid")

    graph_binding = card.get("graph_binding")
    if not isinstance(graph_binding, dict):
        raise KnowledgeCardError("graph_binding must be an object")
    _require_string_list(graph_binding.get("prerequisite_node_ids"), "graph_binding.prerequisite_node_ids", min_items=0)
    _require_string_list(graph_binding.get("unlocks_node_ids"), "graph_binding.unlocks_node_ids", min_items=0)

    brief = card.get("design_brief")
    if not isinstance(brief, dict):
        raise KnowledgeCardError("design_brief must be an object")
    cognitive_object = _require_non_empty_string(brief.get("cognitive_object"), "design_brief.cognitive_object")
    if cognitive_object not in registry["cognitive_objects"]:
        raise KnowledgeCardError("design_brief.cognitive_object is not in registry")
    for key in ("core_mental_model", "why_this_expression", "exit_rule"):
        _require_non_empty_string(brief.get(key), f"design_brief.{key}")
    for key in (
        "primary_misconceptions",
        "best_expression_family",
        "child_actions_for_evidence",
        "repair_expression_switches",
        "near_transfer_direction",
    ):
        _require_string_list(brief.get(key), f"design_brief.{key}")

    teaching_contract = card.get("teaching_contract")
    if not isinstance(teaching_contract, dict):
        raise KnowledgeCardError("teaching_contract must be an object")
    for key in ("essence", "core_model", "minimum_child_takeaway"):
        _require_non_empty_string(teaching_contract.get(key), f"teaching_contract.{key}")
    _require_string_list(teaching_contract.get("must_not_teach_as"), "teaching_contract.must_not_teach_as", min_items=0)

    storyboard = card.get("component_storyboard")
    if not isinstance(storyboard, list) or not storyboard:
        raise KnowledgeCardError("component_storyboard must be a non-empty list")
    required_fields = set(registry["required_storyboard_fields"])
    component_ids: set[str] = set()
    evidence_generating_components = 0
    for index, component in enumerate(storyboard):
        if not isinstance(component, dict):
            raise KnowledgeCardError(f"component_storyboard[{index}] must be an object")
        missing = sorted(required_fields - set(component))
        if missing:
            raise KnowledgeCardError(f"component_storyboard[{index}] missing fields: {','.join(missing)}")
        component_id = _require_non_empty_string(component.get("component_id"), f"component_storyboard[{index}].component_id")
        if component_id in component_ids:
            raise KnowledgeCardError(f"component_storyboard[{index}].component_id is duplicated")
        component_ids.add(component_id)
        component_type = _require_non_empty_string(component.get("type"), f"component_storyboard[{index}].type")
        if component_type not in registry["component_types"]:
            raise KnowledgeCardError(f"component_storyboard[{index}].type is not in registry")
        _require_non_empty_string(component.get("purpose"), f"component_storyboard[{index}].purpose")
        child_action = _require_non_empty_string(component.get("child_action"), f"component_storyboard[{index}].child_action")
        target_evidence = _require_string_list(component.get("target_evidence"), f"component_storyboard[{index}].target_evidence", min_items=0)
        misconception_target = component.get("misconception_target")
        if not isinstance(misconception_target, list) or not all(isinstance(item, str) for item in misconception_target):
            raise KnowledgeCardError(f"component_storyboard[{index}].misconception_target must be a string list")
        _require_non_empty_string(component.get("success_signal"), f"component_storyboard[{index}].success_signal")
        _require_non_empty_string(component.get("fallback_if_failed"), f"component_storyboard[{index}].fallback_if_failed")
        if registry["component_types"][component_type]["child_action_required"] and child_action in {"read", "continue"}:
            raise KnowledgeCardError(f"component_storyboard[{index}] has non-evidence child_action")
        if target_evidence:
            evidence_generating_components += 1
    if evidence_generating_components == 0:
        raise KnowledgeCardError("component_storyboard must contain evidence-generating components")

    evidence_plan = card.get("evidence_plan")
    if not isinstance(evidence_plan, dict):
        raise KnowledgeCardError("evidence_plan must be an object")
    for key in ("core_evidence", "near_transfer_evidence", "insufficient_evidence_cases"):
        _require_string_list(evidence_plan.get(key), f"evidence_plan.{key}")

    repair_paths = card.get("repair_paths")
    if not isinstance(repair_paths, list):
        raise KnowledgeCardError("repair_paths must be a list")
    for index, repair in enumerate(repair_paths):
        if not isinstance(repair, dict):
            raise KnowledgeCardError(f"repair_paths[{index}] must be an object")
        _require_non_empty_string(repair.get("trigger"), f"repair_paths[{index}].trigger")
        switch_to = _require_string_list(repair.get("switch_to"), f"repair_paths[{index}].switch_to")
        unknown = [component_id for component_id in switch_to if component_id not in component_ids]
        if unknown:
            raise KnowledgeCardError(f"repair_paths[{index}] references unknown component")
        _require_non_empty_string(repair.get("rule"), f"repair_paths[{index}].rule")

    exit_rules = card.get("exit_rules")
    if not isinstance(exit_rules, dict) or not exit_rules:
        raise KnowledgeCardError("exit_rules must be a non-empty object")
    if not isinstance(exit_rules.get("max_same_structure_checks"), int) or exit_rules["max_same_structure_checks"] < 0:
        raise KnowledgeCardError("exit_rules.max_same_structure_checks must be a non-negative integer")
    _require_string_list(exit_rules.get("mastery_candidate_after"), "exit_rules.mastery_candidate_after")
    _require_string_list(exit_rules.get("after_mastery"), "exit_rules.after_mastery")
    _require_non_empty_string(exit_rules.get("do_not_repeat_if"), "exit_rules.do_not_repeat_if")

    child_card = card.get("child_card")
    if not isinstance(child_card, dict):
        raise KnowledgeCardError("child_card must be an object")
    _assert_no_child_forbidden_keys(child_card)
    _require_non_empty_string(child_card.get("title"), "child_card.title")
    _require_non_empty_string(child_card.get("one_sentence"), "child_card.one_sentence")
    sequence = _require_string_list(child_card.get("default_sequence"), "child_card.default_sequence")
    if any(component_id not in component_ids for component_id in sequence):
        raise KnowledgeCardError("child_card.default_sequence references unknown component")

    internal_card = card.get("internal_card")
    if not isinstance(internal_card, dict):
        raise KnowledgeCardError("internal_card must be an object")
    _require_non_empty_string(internal_card.get("teaching_goal"), "internal_card.teaching_goal")
    return card


def validate_knowledge_card(card: Any, *, expected_node_id: str | None = None) -> dict[str, Any]:
    if not isinstance(card, dict):
        raise KnowledgeCardError("knowledge card must be an object")
    if card.get("schema_version") != CARD_SCHEMA_VERSION:
        raise KnowledgeCardError("knowledge card schema_version mismatch")
    node_id = _require_non_empty_string(card.get("node_id"), "node_id")
    if expected_node_id and node_id != expected_node_id:
        raise KnowledgeCardError("knowledge card node_id mismatch")
    _require_non_empty_string(card.get("card_version"), "card_version")
    if card.get("status") != "active":
        raise KnowledgeCardError("knowledge card must be active")

    graph_binding = card.get("graph_binding")
    if not isinstance(graph_binding, dict):
        raise KnowledgeCardError("graph_binding must be an object")
    _require_string_list(graph_binding.get("prerequisite_node_ids"), "graph_binding.prerequisite_node_ids", min_items=0)
    _require_string_list(graph_binding.get("unlocks_node_ids"), "graph_binding.unlocks_node_ids", min_items=0)

    child_card = card.get("child_card")
    if not isinstance(child_card, dict):
        raise KnowledgeCardError("child_card must be an object")
    _require_non_empty_string(child_card.get("title"), "child_card.title")
    _require_non_empty_string(child_card.get("one_sentence"), "child_card.one_sentence")
    core_model = child_card.get("core_model")
    if not isinstance(core_model, dict):
        raise KnowledgeCardError("child_card.core_model must be an object")
    _require_non_empty_string(core_model.get("title"), "child_card.core_model.title")
    _require_non_empty_string(core_model.get("body"), "child_card.core_model.body")
    components = child_card.get("components")
    if not isinstance(components, list) or not components:
        raise KnowledgeCardError("child_card.components must be a non-empty list")
    seen_purposes: set[str] = set()
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise KnowledgeCardError(f"child_card.components[{index}] must be an object")
        component_type = _require_non_empty_string(
            component.get("type"),
            f"child_card.components[{index}].type",
        )
        if component_type not in CHILD_CARD_ALLOWED_COMPONENT_TYPES:
            raise KnowledgeCardError(f"child_card.components[{index}].type is unsupported")
        purpose = _require_non_empty_string(
            component.get("purpose"),
            f"child_card.components[{index}].purpose",
        )
        seen_purposes.add(purpose)
    if not {"essence", "standard_example", "evidence", "misconception"} <= seen_purposes:
        raise KnowledgeCardError("child_card.components missing core teaching purposes")
    _validate_teaching_sections(child_card.get("default_teaching_sections"), "child_card.default_teaching_sections")
    _assert_no_child_forbidden_keys(child_card)

    internal_card = card.get("internal_card")
    if not isinstance(internal_card, dict):
        raise KnowledgeCardError("internal_card must be an object")
    _require_non_empty_string(internal_card.get("teaching_goal"), "internal_card.teaching_goal")
    evidence = internal_card.get("core_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise KnowledgeCardError("internal_card.core_evidence must be a non-empty list")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise KnowledgeCardError(f"internal_card.core_evidence[{index}] must be an object")
        _require_non_empty_string(item.get("key"), f"internal_card.core_evidence[{index}].key")
        _require_non_empty_string(item.get("dimension"), f"internal_card.core_evidence[{index}].dimension")
        _require_non_empty_string(item.get("description"), f"internal_card.core_evidence[{index}].description")
    misconceptions = internal_card.get("misconceptions")
    if not isinstance(misconceptions, list) or not misconceptions:
        raise KnowledgeCardError("internal_card.misconceptions must be a non-empty list")
    runtime_rules = internal_card.get("runtime_rules")
    if not isinstance(runtime_rules, dict) or not runtime_rules:
        raise KnowledgeCardError("internal_card.runtime_rules must be a non-empty object")
    return card


@dataclass(frozen=True)
class KnowledgeCard:
    payload: dict[str, Any]
    source_path: Path

    @property
    def node_id(self) -> str:
        return str(self.payload["node_id"])

    @property
    def card_version(self) -> str:
        return str(self.payload["card_version"])

    def digest(self) -> str:
        return _canonical_sha256(self.payload)

    def child_projection(self) -> dict[str, Any]:
        child_card = json.loads(json.dumps(self.payload["child_card"], ensure_ascii=False))
        _assert_no_child_forbidden_keys(child_card)
        return {
            "schema_version": "knowledge-card-child.v1",
            "card_version": self.card_version,
            "title": child_card["title"],
            "one_sentence": child_card["one_sentence"],
            "core_model": child_card["core_model"],
            "components": child_card["components"],
        }

    def child_directory_summary(self) -> dict[str, Any]:
        child_card = json.loads(json.dumps(self.payload["child_card"], ensure_ascii=False))
        _assert_no_child_forbidden_keys(child_card)
        component_types = [
            str(component.get("type") or "")
            for component in child_card.get("components", [])
            if isinstance(component, dict)
        ]
        forms = []
        if "number_line_visual" in component_types:
            forms.append("数轴演示")
        if "worked_example" in component_types:
            forms.append("例题讲解")
        if "micro_check" in component_types:
            forms.append("小检查")
        if "common_mistake" in component_types:
            forms.append("易错提醒")
        if not forms:
            forms.append("学习卡")
        return {
            "available": True,
            "title": child_card["title"],
            "one_sentence": child_card["one_sentence"],
            "core_model_title": child_card["core_model"]["title"],
            "core_model_body": child_card["core_model"]["body"],
            "forms": forms[:4],
            "has_interaction": any(
                item in component_types
                for item in (
                    "drag_point_interaction",
                    "compare_choice",
                    "fill_blank",
                    "micro_check",
                    "photo_answer_prompt",
                )
            ),
        }

    def teaching_sections(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.payload["child_card"]["default_teaching_sections"], ensure_ascii=False))

    def runtime_packet(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-card-runtime.v1",
            "node_id": self.node_id,
            "card_version": self.card_version,
            "card_digest_sha256": self.digest(),
            "child_card_summary": {
                "one_sentence": self.payload["child_card"]["one_sentence"],
                "core_model": self.payload["child_card"]["core_model"],
                "default_teaching_sections": self.teaching_sections(),
            },
            "internal_card": json.loads(json.dumps(self.payload["internal_card"], ensure_ascii=False)),
            "graph_binding": json.loads(json.dumps(self.payload["graph_binding"], ensure_ascii=False)),
        }


class KnowledgeCardService:
    def __init__(self, *, project_root: Path | str | None = None) -> None:
        self.project_root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]

    def active_card_path(self, node_id: str) -> Path:
        filename = ACTIVE_CARD_FILENAMES.get(str(node_id or ""))
        if not filename:
            raise KnowledgeCardError(f"no active knowledge card for node: {node_id}")
        return self.project_root / CARD_ROOT / filename

    def load_active_card(self, node_id: str) -> KnowledgeCard:
        path = self.active_card_path(node_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return KnowledgeCard(
            payload=validate_knowledge_card(payload, expected_node_id=node_id),
            source_path=path,
        )

    def load_v2_draft_card(self, node_id: str) -> dict[str, Any]:
        path = self.project_root / CARD_ROOT / f"{node_id}.v2.draft.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return validate_knowledge_card_v2(
            payload,
            registry=load_component_registry(self.project_root),
            expected_node_id=node_id,
        )

    def maybe_load_active_card(self, node_id: str) -> KnowledgeCard | None:
        try:
            return self.load_active_card(node_id)
        except (FileNotFoundError, json.JSONDecodeError, KnowledgeCardError):
            return None

    def child_projection_for_node(self, node_id: str) -> dict[str, Any]:
        return self.load_active_card(node_id).child_projection()

    def child_directory_summary_for_node(self, node_id: str) -> dict[str, Any] | None:
        card = self.maybe_load_active_card(node_id)
        return card.child_directory_summary() if card else None

    def runtime_packet_for_node(self, node_id: str) -> dict[str, Any] | None:
        card = self.maybe_load_active_card(node_id)
        return card.runtime_packet() if card else None

    def teaching_sections_for_node(self, node_id: str) -> dict[str, Any] | None:
        card = self.maybe_load_active_card(node_id)
        return card.teaching_sections() if card else None
