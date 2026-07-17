from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


ALLOWED_MASTERY_DIMENSIONS = frozenset(
    {
        "concept",
        "model_relation",
        "procedure",
        "calculation",
        "representation",
        "expression_notation",
        "final_answer",
        "check",
        "transfer",
    }
)

ALLOWED_CRITERION_STATUSES = frozenset(
    {"met", "not_met", "contradicted", "unclear"}
)

ACTIVE_QUESTION_KINDS = (
    "boundary_case",
    "check_strategy",
    "communication",
    "error_spotting",
    "essence_check",
    "estimation_modeling",
    "explanation_only",
    "misconception_probe",
    "missing_condition",
    "model_selection",
    "prerequisite_probe",
    "representation",
    "reverse_reasoning",
    "self_correction",
    "standard_example",
    "stretch_transfer",
    "symbol_unit_audit",
    "transfer_retest",
    "two_method_compare",
    "variant",
)

# Profiles select the scoring-target authority path. They never invent criteria.
PROFILE_BY_KIND = {kind: "scoring_targets" for kind in ACTIVE_QUESTION_KINDS}

_PROFILE_SLOT_LAYOUTS = {
    "boundary_case": (
        ("boundary_condition", 4, "concept", True),
        ("boundary_application", 3, "procedure", True),
        ("boundary_conclusion", 3, "check", False),
    ),
    "check_strategy": (
        ("check_target", 3, "concept", True),
        ("check_execution", 4, "check", True),
        ("check_conclusion", 3, "expression_notation", False),
    ),
    "communication": (
        ("mathematical_claim", 4, "concept", True),
        ("supporting_relation", 3, "model_relation", True),
        ("clear_conclusion", 3, "expression_notation", False),
    ),
    "error_spotting": (
        ("error_location", 3, "concept", True),
        ("error_reason", 4, "model_relation", True),
        ("corrected_result", 3, "procedure", True),
    ),
    "essence_check": (
        ("essential_relation", 4, "concept", True),
        ("relation_application", 3, "model_relation", True),
        ("result_justification", 3, "check", False),
    ),
    "estimation_modeling": (
        ("quantity_model", 4, "model_relation", True),
        ("estimation_process", 3, "calculation", True),
        ("reasonableness_check", 3, "check", False),
    ),
    "explanation_only": (
        ("core_explanation", 4, "concept", True),
        ("mathematical_support", 3, "model_relation", True),
        ("conclusion_link", 3, "expression_notation", False),
    ),
    "misconception_probe": (
        ("misconception_identification", 3, "concept", True),
        ("correct_relation", 4, "model_relation", True),
        ("corrected_conclusion", 3, "procedure", True),
    ),
    "missing_condition": (
        ("missing_condition", 4, "concept", True),
        ("condition_effect", 3, "model_relation", True),
        ("revised_conclusion", 3, "procedure", False),
    ),
    "model_selection": (
        ("selected_model", 4, "model_relation", True),
        ("model_application", 3, "procedure", True),
        ("model_check", 3, "check", False),
    ),
    "prerequisite_probe": (
        ("prerequisite_relation", 4, "concept", True),
        ("prerequisite_procedure", 3, "procedure", True),
        ("prerequisite_result", 3, "final_answer", False),
    ),
    "representation": (
        ("representation_choice", 3, "representation", True),
        ("representation_accuracy", 4, "model_relation", True),
        ("represented_conclusion", 3, "final_answer", False),
    ),
    "reverse_reasoning": (
        ("reverse_relation", 4, "model_relation", True),
        ("reverse_derivation", 3, "procedure", True),
        ("forward_check", 3, "check", False),
    ),
    "self_correction": (
        ("original_error", 3, "concept", True),
        ("corrected_process", 4, "procedure", True),
        ("correction_check", 3, "check", False),
    ),
    "standard_example": (
        ("core_relation", 4, "model_relation", True),
        ("mathematical_execution", 3, "procedure", True),
        ("verified_conclusion", 3, "check", False),
    ),
    "stretch_transfer": (
        ("transferred_relation", 4, "transfer", True),
        ("transfer_execution", 3, "procedure", True),
        ("transfer_check", 3, "check", False),
    ),
    "symbol_unit_audit": (
        ("symbol_or_unit_rule", 3, "expression_notation", True),
        ("symbol_or_unit_application", 4, "representation", True),
        ("audited_conclusion", 3, "check", False),
    ),
    "transfer_retest": (
        ("retained_relation", 4, "transfer", True),
        ("retest_execution", 3, "procedure", True),
        ("retest_conclusion", 3, "final_answer", False),
    ),
    "two_method_compare": (
        ("first_method", 3, "procedure", True),
        ("second_method", 3, "procedure", True),
        ("method_comparison", 2, "concept", True),
        ("shared_conclusion", 2, "check", False),
    ),
    "variant": (
        ("variant_relation", 4, "transfer", True),
        ("variant_execution", 3, "procedure", True),
        ("variant_conclusion", 3, "final_answer", False),
    ),
}

_POINTS_BY_TARGET_COUNT = {
    2: (6, 4),
    3: (4, 3, 3),
    4: (3, 3, 2, 2),
}

_FORBIDDEN_REPAIR_KEYS = frozenset(
    {
        "corrected_node_id",
        "rebound_node_id",
        "suggested_node_id",
        "question_node_alignment",
    }
)

V2_SLOT_CATALOGS = {
    kind: tuple(
        {
            "slot_key": slot_key,
            "description": slot_key.replace("_", " "),
            "dimension": dimension,
            "catalog_order": index,
            "required_for_pass": bool(required),
        }
        for index, (slot_key, _points, dimension, required) in enumerate(layout)
    )
    for kind, layout in _PROFILE_SLOT_LAYOUTS.items()
}
V2_SLOT_CATALOGS["standard_example"] = (
    {
        "slot_key": "core_relation",
        "description": "core mathematical relation or identified error",
        "dimension": "model_relation",
        "catalog_order": 0,
        "required_for_pass": True,
    },
    {
        "slot_key": "intermediate_result",
        "description": "observable intermediate mathematical result",
        "dimension": "calculation",
        "catalog_order": 1,
        "required_for_pass": True,
    },
    {
        "slot_key": "final_result",
        "description": "observable final mathematical conclusion",
        "dimension": "final_answer",
        "catalog_order": 2,
        "required_for_pass": True,
    },
    {
        "slot_key": "verification",
        "description": "independent mathematical verification",
        "dimension": "check",
        "catalog_order": 3,
        "required_for_pass": False,
    },
)

_V2_PRESENTATION_PATTERNS = (
    r"\bneat(?:ness)?\b",
    r"\bhandwriting\b",
    r"\bformat(?:ting)?\b",
    r"\bfull sentence\b",
    r"\bcomplete sentence\b",
    r"书写(?:整齐|美观)",
    r"格式(?:规范|美观)",
)


class ContractCompileError(ValueError):
    def __init__(self, issue_code: str, message: str) -> None:
        super().__init__(message)
        self.issue_code = issue_code


def _nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _has_reference_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return value is not None


def _validate_scoring_targets(targets: Any) -> list[dict[str, Any]]:
    if not isinstance(targets, list):
        raise TypeError("scoring_targets must be a list")
    if len(targets) < 2:
        raise ValueError("scoring_targets must contain at least two targets")

    validated: list[dict[str, Any]] = []
    keys: list[str] = []
    for target in targets:
        if not isinstance(target, dict):
            raise TypeError("each scoring target must be a mapping")
        key = _nonempty_text(target.get("key"), "scoring target key")
        if key == "prompt_required_expression":
            raise ValueError("prompt-derived presentation targets cannot be scored")
        _nonempty_text(target.get("criterion"), f"criterion for target {key}")
        if target.get("dimension") not in ALLOWED_MASTERY_DIMENSIONS:
            raise ValueError(f"invalid mastery dimension for target {key}")
        if not isinstance(target.get("required_for_pass"), bool):
            raise TypeError(f"required_for_pass for target {key} must be boolean")
        keys.append(key)
        validated.append(deepcopy(target))

    if len(keys) != len(set(keys)):
        raise ValueError("scoring target keys must be unique")
    return validated


def _fallback_scoring_targets(question: dict[str, Any]) -> list[dict[str, Any]]:
    steps = question.get("solution_steps")
    if not isinstance(steps, (list, tuple)):
        steps = []
    usable_steps = [step for step in steps if _has_reference_value(step)][:4]

    targets = [
        {
            "key": f"solution_step_{index}",
            "criterion": f"Demonstrates reference solution step {index}",
            "dimension": "procedure",
            "required_for_pass": True,
            "reference_component": f"solution_steps[{index - 1}]",
        }
        for index, _step in enumerate(usable_steps, start=1)
    ]
    if len(targets) < 2 and _has_reference_value(question.get("expected_answer")):
        targets.append(
            {
                "key": "reference_answer",
                "criterion": "Provides the reference answer conclusion",
                "dimension": "final_answer",
                "required_for_pass": True,
                "reference_component": "expected_answer",
            }
        )
    if len(targets) < 2:
        raise ValueError(
            "a question without scoring_targets needs at least two independent "
            "solution reference components"
        )
    return targets[:4]


def _reference_components(question: dict[str, Any]) -> dict[str, Any]:
    components: dict[str, Any] = {}
    if _has_reference_value(question.get("expected_answer")):
        components["expected_answer"] = deepcopy(question["expected_answer"])
    steps = question.get("solution_steps")
    if isinstance(steps, (list, tuple)):
        for index, step in enumerate(steps[:4]):
            if _has_reference_value(step):
                components[f"solution_steps[{index}]"] = deepcopy(step)
    if len(components) < 2:
        raise ValueError("contract design requires at least two reference components")
    return components


def build_contract_skeleton(question: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(question, dict):
        raise TypeError("question must be a mapping")
    kind = _nonempty_text(question.get("kind"), "question.kind")
    try:
        layout = _PROFILE_SLOT_LAYOUTS[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported question kind: {kind}") from exc
    components = _reference_components(question)
    component_keys = list(components)
    slots = []
    for index, (slot_key, points, dimension, required) in enumerate(layout):
        preferred = []
        if index < len(component_keys):
            preferred.append(component_keys[index])
        if "expected_answer" in components and "expected_answer" not in preferred:
            preferred.append("expected_answer")
        if not preferred:
            preferred = component_keys[:1]
        slots.append(
            {
                "slot_key": slot_key,
                "points": points,
                "dimension": dimension,
                "required_for_pass": required,
                "allowed_reference_component_keys": preferred,
            }
        )
    skeleton = {
        "profile_version": "answer-contract-profile.v1",
        "profile_key": kind,
        "question_kind": kind,
        "slots": slots,
        "reference_component_keys": component_keys,
    }
    if not 2 <= len(slots) <= 4 or sum(slot["points"] for slot in slots) != 10:
        raise ValueError("contract skeleton profile is invalid")
    return skeleton


def compile_answer_contract(
    question: dict[str, Any],
    skeleton: dict[str, Any],
    designer_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(question, dict) or not isinstance(skeleton, dict):
        raise TypeError("question and skeleton must be mappings")
    expected_handle = skeleton.get("item_handle")
    authoritative_skeleton = {
        key: deepcopy(value)
        for key, value in skeleton.items()
        if key != "item_handle"
    }
    expected_skeleton = build_contract_skeleton(question)
    if authoritative_skeleton != expected_skeleton:
        raise ValueError("contract skeleton does not match the question profile")
    if not isinstance(designer_items, list) or not 2 <= len(designer_items) <= 4:
        raise ValueError("designer output must contain two to four criteria")
    allowed_fields = {
        "item_handle",
        "slot_key",
        "criterion",
        "reference_component_keys",
        "confidence",
    }
    slots_by_key = {slot["slot_key"]: slot for slot in skeleton["slots"]}
    items_by_slot: dict[str, dict[str, Any]] = {}
    handles = set()
    for item in designer_items:
        if not isinstance(item, dict) or set(item) != allowed_fields:
            raise ValueError("designer criterion fields must match the exact schema")
        handle = _nonempty_text(item.get("item_handle"), "item_handle")
        slot_key = _nonempty_text(item.get("slot_key"), "slot_key")
        criterion = _nonempty_text(item.get("criterion"), "criterion")
        references = item.get("reference_component_keys")
        confidence = item.get("confidence")
        if expected_handle is not None and handle != expected_handle:
            raise ValueError("designer item_handle does not match sealed input")
        if slot_key not in slots_by_key or slot_key in items_by_slot:
            raise ValueError("designer slots must be known and unique")
        if (
            not isinstance(references, list)
            or not references
            or len(references) != len(set(references))
            or not all(isinstance(key, str) and key for key in references)
        ):
            raise ValueError("reference component keys must be a unique string list")
        if not set(references).issubset(
            set(slots_by_key[slot_key]["allowed_reference_component_keys"])
        ):
            raise ValueError("designer referenced a component outside the slot authority")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.8 <= confidence <= 1
        ):
            raise ValueError("designer confidence must be at least 0.8")
        _validate_designed_criterion(criterion)
        handles.add(handle)
        items_by_slot[slot_key] = {
            **deepcopy(item),
            "criterion": criterion,
        }
    if len(handles) != 1 or set(items_by_slot) != set(slots_by_key):
        raise ValueError("designer output must cover every skeleton slot exactly once")

    scoring_targets = []
    score_points = []
    for slot in skeleton["slots"]:
        semantic = items_by_slot[slot["slot_key"]]
        target = {
            "key": slot["slot_key"],
            "criterion": semantic["criterion"],
            "dimension": slot["dimension"],
            "required_for_pass": slot["required_for_pass"],
            "reference_component": list(semantic["reference_component_keys"]),
        }
        scoring_targets.append(target)
        score_points.append(
            {
                **deepcopy(target),
                "points": slot["points"],
                "source_target_key": slot["slot_key"],
            }
        )
    contract = {
        "question_id": _nonempty_text(question.get("id"), "question.id"),
        "item_version": _nonempty_text(
            question.get("item_version"), "question.item_version"
        ),
        "node_id": _nonempty_text(question.get("node_id"), "question.node_id"),
        "question_kind": skeleton["question_kind"],
        "reference_solution": {
            "answer": deepcopy(question.get("expected_answer")),
            "solution_steps": deepcopy(question.get("solution_steps")),
        },
        "scoring_targets": scoring_targets,
        "score_points": score_points,
        "design_profile_version": skeleton["profile_version"],
        "status": "draft_designed",
    }
    validate_contract(contract)
    return contract


def _validate_designed_criterion(criterion: str) -> None:
    normalized = " ".join(criterion.lower().split())
    generic_patterns = (
        r"\bobservable mathematical evidence\b",
        r"\breference solution\b",
        r"\bsolution[_ ]?step\b",
        r"\bdemonstrates? step\b",
        r"\bshows? (?:good )?understanding\b",
        r"\buses? (?:an )?appropriate method\b",
        r"\bgives? the correct answer\b",
        r"\bcorrect process\b",
    )
    unobservable_patterns = (
        r"\bunderstands?\b",
        r"\bknows?\b",
        r"\bhas mastery\b",
        r"\bseems? to\b",
    )
    if any(re.search(pattern, normalized) for pattern in generic_patterns):
        raise ValueError("designer criterion is generic rather than question-specific")
    if any(re.search(pattern, normalized) for pattern in unobservable_patterns):
        raise ValueError("designer criterion is not observable in the child answer")
    if (
        "\n" in criterion
        or criterion.count(";") + criterion.count("；") > 0
        or " and also " in normalized
        or " as well as " in normalized
        or "并且" in criterion
    ):
        raise ValueError("designer criterion must be atomic")


def _v2_reference_anchors(question: dict[str, Any]) -> dict[str, dict[str, Any]]:
    supplied = question.get("reference_anchors")
    anchors: dict[str, dict[str, Any]] = {}
    if supplied is not None:
        if not isinstance(supplied, dict) or not supplied:
            raise ValueError("reference_anchors must be a nonempty mapping")
        for key, value in supplied.items():
            anchor_key = _nonempty_text(key, "reference anchor key")
            if not re.fullmatch(r"[a-z0-9_]+", anchor_key):
                raise ValueError("reference anchor keys must be local identifiers")
            if not isinstance(value, dict):
                raise TypeError("reference anchors must be mappings")
            anchors[anchor_key] = {
                "claim": _nonempty_text(value.get("claim"), "reference anchor claim"),
                "source": _nonempty_text(
                    value.get("source") or "explicit", "reference anchor source"
                ),
            }
    else:
        steps = question.get("solution_steps")
        if isinstance(steps, (list, tuple)):
            for index, step in enumerate(steps[:6], start=1):
                if _has_reference_value(step):
                    anchors[f"solution_step_{index}"] = {
                        "claim": str(step).strip(),
                        "source": f"solution_step_{index}",
                    }
        if _has_reference_value(question.get("expected_answer")):
            anchors["expected_answer"] = {
                "claim": str(question["expected_answer"]).strip(),
                "source": "expected_answer",
            }
    if len(anchors) < 2:
        raise ValueError("v2 contract design requires two reference anchors")
    return anchors


def build_contract_skeleton_v2(question: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(question, dict):
        raise TypeError("question must be a mapping")
    kind = _nonempty_text(question.get("kind"), "question.kind")
    try:
        catalog = V2_SLOT_CATALOGS[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported question kind: {kind}") from exc
    reference_anchors = _v2_reference_anchors(question)
    def anchor_order(key: str) -> tuple[int, int, str]:
        source = str(reference_anchors[key].get("source") or "")
        match = re.search(r"(?:solution[_ ]?step|step)[_ ]?(\d+)$", source)
        if match:
            return (0, int(match.group(1)), key)
        if source == "expected_answer":
            return (2, 0, key)
        return (1, 0, key)

    reference_keys = sorted(reference_anchors, key=anchor_order)
    slots = [
        {
            **deepcopy(slot),
            "allowed_source_anchor_keys": (
                [slot["slot_key"]]
                if slot["slot_key"] in reference_anchors
                else [
                    reference_keys[
                        slot["catalog_order"] % len(reference_keys)
                    ],
                    *[
                        key
                        for key in reference_keys
                        if key
                        != reference_keys[
                            slot["catalog_order"] % len(reference_keys)
                        ]
                    ],
                ]
            ),
        }
        for slot in catalog
    ]
    return {
        "profile_version": "answer-contract-profile.v2",
        "profile_key": kind,
        "question_kind": kind,
        "allowed_slot_catalog": slots,
        "reference_anchors": reference_anchors,
    }


def _validate_designed_criterion_v2(criterion: str) -> None:
    try:
        _validate_designed_criterion(criterion)
    except ValueError as exc:
        raise ContractCompileError("criterion_unobservable", str(exc)) from exc
    normalized = " ".join(criterion.lower().split())
    if any(
        marker in normalized
        for marker in (" and also ", " as well as ", "并且", "同时", "以及")
    ):
        raise ContractCompileError(
            "criterion_bundled",
            "v2 designer criterion bundles independent targets",
        )
    if any(re.search(pattern, normalized) for pattern in _V2_PRESENTATION_PATTERNS):
        raise ContractCompileError(
            "presentation_only_scored",
            "presentation-only preferences cannot be scored",
        )


def _derived_claims_duplicate(first: str, second: str) -> bool:
    return " ".join(first.casefold().split()) == " ".join(
        second.casefold().split()
    )


def compile_answer_contract_v2(
    question: dict[str, Any],
    skeleton: dict[str, Any],
    designer_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(question, dict) or not isinstance(skeleton, dict):
        raise TypeError("question and skeleton must be mappings")
    expected_handle = skeleton.get("item_handle")
    authoritative_skeleton = {
        key: deepcopy(value) for key, value in skeleton.items() if key != "item_handle"
    }
    expected_skeleton = build_contract_skeleton_v2(question)
    if authoritative_skeleton != expected_skeleton:
        raise ValueError("v2 contract skeleton does not match the question profile")
    if not isinstance(designer_items, list) or not 2 <= len(designer_items) <= 4:
        raise ValueError("v2 designer must select two to four atomic components")
    allowed_fields = {
        "item_handle",
        "slot_key",
        "criterion",
        "reference_evidence",
        "confidence",
    }
    catalog = {
        slot["slot_key"]: slot for slot in skeleton["allowed_slot_catalog"]
    }
    anchors = skeleton["reference_anchors"]
    selected: dict[str, dict[str, Any]] = {}
    claims_by_anchor: dict[str, list[tuple[str, str]]] = {}
    criteria = set()
    handles = set()
    for item in designer_items:
        if not isinstance(item, dict) or set(item) != allowed_fields:
            raise ValueError("v2 designer fields must match the exact schema")
        handle = _nonempty_text(item["item_handle"], "item_handle")
        slot_key = _nonempty_text(item["slot_key"], "slot_key")
        criterion = _nonempty_text(item["criterion"], "criterion")
        evidence = item["reference_evidence"]
        confidence = item["confidence"]
        if expected_handle is not None and handle != expected_handle:
            raise ContractCompileError(
                "other_contract_issue",
                "v2 designer item_handle does not match sealed input",
            )
        if slot_key not in catalog or slot_key in selected:
            raise ContractCompileError(
                "slot_not_allowed",
                "v2 designer slots must be allowed and unique",
            )
        if not isinstance(evidence, dict) or set(evidence) != {
            "claim",
            "source_anchor_keys",
            "derivation_scope",
        }:
            raise ContractCompileError(
                "reference_evidence_missing",
                "v2 reference evidence fields must match the exact schema",
            )
        claim = _nonempty_text(evidence["claim"], "reference evidence claim")
        source_keys = evidence["source_anchor_keys"]
        if (
            not isinstance(source_keys, list)
            or len(source_keys) != 1
            or not isinstance(source_keys[0], str)
            or not source_keys[0]
        ):
            raise ContractCompileError(
                "reference_evidence_broad",
                "v2 reference evidence must use one precise source anchor",
            )
        anchor_key = source_keys[0]
        if anchor_key not in anchors:
            raise ContractCompileError(
                "reference_evidence_missing",
                "v2 designer referenced an unknown source anchor",
            )
        if anchor_key not in catalog[slot_key]["allowed_source_anchor_keys"]:
            raise ContractCompileError(
                "reference_evidence_missing",
                "v2 source anchor is outside slot authority",
            )
        derivation_scope = evidence["derivation_scope"]
        if derivation_scope not in {"direct", "derived"}:
            raise ContractCompileError(
                "derived_grounding_invalid",
                "unsupported v2 reference derivation scope",
            )
        anchor_claim = anchors[anchor_key]["claim"].strip()
        if derivation_scope == "direct" and claim.strip() != anchor_claim:
            raise ContractCompileError(
                "derived_grounding_invalid",
                "direct v2 evidence must equal its sealed source anchor",
            )
        effective_scope = (
            "direct"
            if derivation_scope == "derived" and claim.strip() == anchor_claim
            else derivation_scope
        )
        prior_claims = claims_by_anchor.setdefault(anchor_key, [])
        if any(
            effective_scope == "direct"
            or prior_scope == "direct"
            or _derived_claims_duplicate(claim, prior_claim)
            for prior_scope, prior_claim in prior_claims
        ):
            raise ContractCompileError(
                "criterion_overlap",
                "v2 score points overlap the same reference evidence",
            )
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.8 <= confidence <= 1
        ):
            raise ContractCompileError(
                "low_confidence",
                "v2 designer confidence must be at least 0.8",
            )
        _validate_designed_criterion_v2(criterion)
        normalized_criterion = " ".join(criterion.lower().split())
        if normalized_criterion in criteria:
            raise ContractCompileError(
                "criterion_overlap",
                "v2 score point criteria cannot overlap",
            )
        criteria.add(normalized_criterion)
        prior_claims.append((effective_scope, claim))
        handles.add(handle)
        selected_item = deepcopy(item)
        selected_item["reference_evidence"][
            "derivation_scope"
        ] = effective_scope
        selected[slot_key] = selected_item
    if len(handles) != 1:
        raise ValueError("v2 designer items must share one sealed handle")

    ordered_slots = sorted(
        (catalog[key] for key in selected), key=lambda slot: slot["catalog_order"]
    )
    points_by_order = _POINTS_BY_TARGET_COUNT[len(ordered_slots)]
    selected_has_required = any(slot["required_for_pass"] for slot in ordered_slots)
    components = []
    scoring_targets = []
    score_points = []
    for index, (slot, points) in enumerate(zip(ordered_slots, points_by_order)):
        semantic = selected[slot["slot_key"]]
        evidence = semantic["reference_evidence"]
        component_key = f"component_{slot['slot_key']}"
        components.append(
            {
                "key": component_key,
                "claim": evidence["claim"],
                "source_anchor_keys": deepcopy(evidence["source_anchor_keys"]),
                "derivation_scope": evidence["derivation_scope"],
            }
        )
        required = slot["required_for_pass"] or (
            index == 0 and not selected_has_required
        )
        target = {
            "key": slot["slot_key"],
            "criterion": semantic["criterion"],
            "dimension": slot["dimension"],
            "required_for_pass": required,
            "reference_component": component_key,
        }
        scoring_targets.append(target)
        score_points.append(
            {
                **deepcopy(target),
                "points": points,
                "source_target_key": slot["slot_key"],
                "reference_component_key": component_key,
            }
        )
    contract = {
        "question_id": _nonempty_text(question.get("id"), "question.id"),
        "item_version": _nonempty_text(
            question.get("item_version"), "question.item_version"
        ),
        "node_id": _nonempty_text(question.get("node_id"), "question.node_id"),
        "question_kind": skeleton["question_kind"],
        "reference_solution": {
            "components": components,
        },
        "scoring_targets": scoring_targets,
        "score_points": score_points,
        "design_profile_version": skeleton["profile_version"],
        "status": "draft_designed_v2",
    }
    validate_contract(contract)
    return contract


def build_answer_contract(question: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(question, dict):
        raise TypeError("question must be a mapping")

    kind = _nonempty_text(question.get("kind"), "question.kind")
    if kind not in PROFILE_BY_KIND:
        raise ValueError(f"unsupported question kind: {kind}")

    expected_answer = deepcopy(question.get("expected_answer"))
    solution_steps = deepcopy(question.get("solution_steps"))
    if not _has_reference_value(expected_answer) and not _has_reference_value(
        solution_steps
    ):
        raise ValueError("question must provide expected_answer or solution_steps")

    supplied_targets = question.get("scoring_targets")
    if not supplied_targets and question.get("_answer_contract_generation_required"):
        raise ValueError(
            "authoritative inventory requires semantic answer-contract design"
        )
    fallback = not supplied_targets
    scoring_targets = _validate_scoring_targets(
        _fallback_scoring_targets(question) if fallback else supplied_targets
    )

    ordered_targets = [
        *[target for target in scoring_targets if target["required_for_pass"]],
        *[target for target in scoring_targets if not target["required_for_pass"]],
    ]
    selected_targets = ordered_targets[:4]
    if len(selected_targets) < 2:
        raise ValueError("a contract needs two to four independent scoring targets")
    weights = _POINTS_BY_TARGET_COUNT[len(selected_targets)]

    selected_keys = [target["key"] for target in selected_targets]
    omitted_keys = [
        target["key"]
        for target in scoring_targets
        if target["key"] not in selected_keys
    ]
    score_points = []
    for target, points in zip(selected_targets, weights):
        score_point = {
            "key": target["key"],
            "criterion": target["criterion"],
            "points": points,
            "dimension": target["dimension"],
            "required_for_pass": target["required_for_pass"],
            "source_target_key": target["key"],
        }
        if "reference_component" in target:
            score_point["reference_component"] = deepcopy(
                target["reference_component"]
            )
        score_points.append(score_point)

    contract = {
        "question_id": _nonempty_text(question.get("id"), "question.id"),
        "item_version": _nonempty_text(
            question.get("item_version"), "question.item_version"
        ),
        "node_id": _nonempty_text(question.get("node_id"), "question.node_id"),
        "question_kind": kind,
        "reference_solution": {
            "answer": expected_answer,
            "solution_steps": solution_steps,
        },
        "scoring_targets": scoring_targets,
        "score_points": score_points,
        "status": "draft_unreviewed" if fallback else "draft",
    }
    if omitted_keys:
        contract["selected_scoring_target_keys"] = selected_keys
        contract["omitted_scoring_target_reasons"] = {
            key: "draft contracts support at most four atomic score points"
            for key in omitted_keys
        }
    validate_contract(contract)
    return contract


def validate_contract(contract: dict[str, Any]) -> None:
    if not isinstance(contract, dict):
        raise TypeError("contract must be a mapping")
    if _FORBIDDEN_REPAIR_KEYS.intersection(contract):
        raise ValueError("draft contracts cannot repair or judge node binding")
    if contract.get("status") == "active":
        raise ValueError("draft contract profiles cannot be active")

    for field in ("question_id", "item_version", "node_id"):
        _nonempty_text(contract.get(field), field)

    reference = contract.get("reference_solution")
    if not isinstance(reference, dict) or not reference:
        raise ValueError("reference_solution must be a nonempty mapping")
    if not any(_has_reference_value(value) for value in reference.values()):
        raise ValueError("reference_solution must contain usable reference content")

    scoring_targets = _validate_scoring_targets(contract.get("scoring_targets"))
    targets_by_key = {target["key"]: target for target in scoring_targets}

    score_points = contract.get("score_points")
    if not isinstance(score_points, list):
        raise TypeError("score_points must be a list")
    if not 2 <= len(score_points) <= 4:
        raise ValueError("score_points must contain two to four criteria")

    keys: list[str] = []
    source_keys: list[str] = []
    total = 0
    has_required = False
    for point in score_points:
        if not isinstance(point, dict):
            raise TypeError("each score point must be a mapping")
        if "source_target_keys" in point:
            raise ValueError("a score point may reference only one scoring target")
        key = _nonempty_text(point.get("key"), "score point key")
        source_key = _nonempty_text(
            point.get("source_target_key"), f"source_target_key for {key}"
        )
        if source_key not in targets_by_key:
            raise ValueError(f"unknown source_target_key for {key}")
        _nonempty_text(point.get("criterion"), f"criterion {key}")
        points = point.get("points")
        if isinstance(points, bool) or not isinstance(points, int) or points <= 0:
            raise ValueError(f"points for {key} must be a positive integer")
        if point.get("dimension") not in ALLOWED_MASTERY_DIMENSIONS:
            raise ValueError(f"invalid mastery dimension for {key}")
        if not isinstance(point.get("required_for_pass"), bool):
            raise TypeError(f"required_for_pass for {key} must be boolean")
        keys.append(key)
        source_keys.append(source_key)
        total += points
        has_required = has_required or point["required_for_pass"]

    if len(keys) != len(set(keys)):
        raise ValueError("score point keys must be unique")
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("each score point must map to a unique scoring target")
    if total != 10:
        raise ValueError("score points must total 10")
    if not has_required:
        raise ValueError("at least one score point must be required for pass")

    if set(source_keys) != set(targets_by_key):
        selected = contract.get("selected_scoring_target_keys")
        reasons = contract.get("omitted_scoring_target_reasons")
        if (
            not isinstance(selected, list)
            or selected != source_keys
            or not isinstance(reasons, dict)
            or set(reasons) != set(targets_by_key).difference(source_keys)
            or not all(
                isinstance(reason, str) and reason.strip()
                for reason in reasons.values()
            )
        ):
            raise ValueError("omitted scoring targets require explicit selection lineage")


def validate_criterion_judgments(
    contract: dict[str, Any], judgments: list[dict[str, Any]]
) -> None:
    validate_contract(contract)
    if not isinstance(judgments, list):
        raise TypeError("judgments must be a list")

    expected_keys = [point["key"] for point in contract["score_points"]]
    actual_keys: list[str] = []
    for judgment in judgments:
        if not isinstance(judgment, dict):
            raise TypeError("each criterion judgment must be a mapping")
        key = _nonempty_text(judgment.get("criterion_key"), "criterion_key")
        status = judgment.get("status")
        if status not in ALLOWED_CRITERION_STATUSES:
            raise ValueError(f"invalid criterion status for {key}")
        evidence = judgment.get("child_evidence")
        if not isinstance(evidence, str):
            raise TypeError(f"child_evidence for {key} must be a string")
        if status == "met" and not evidence.strip():
            raise ValueError(f"met judgment for {key} requires grounded evidence")
        _nonempty_text(judgment.get("reason"), f"reason for {key}")
        actual_keys.append(key)

    if len(actual_keys) != len(set(actual_keys)):
        raise ValueError("criterion judgments cannot contain duplicate keys")
    if set(actual_keys) != set(expected_keys) or len(actual_keys) != len(expected_keys):
        raise ValueError("criterion judgments must cover the exact contract keys")


def calculate_assessment(
    contract: dict[str, Any], judgments: list[dict[str, Any]]
) -> dict[str, Any]:
    validate_criterion_judgments(contract, judgments)
    by_key = {judgment["criterion_key"]: judgment for judgment in judgments}

    if any(judgment["status"] == "unclear" for judgment in judgments):
        return {
            "finalized": False,
            "score_out_of_10": None,
            "compatibility_score_points": None,
            "question_passed": False,
        }

    score = sum(
        point["points"]
        for point in contract["score_points"]
        if by_key[point["key"]]["status"] == "met"
    )
    passed = all(
        by_key[point["key"]]["status"] == "met"
        for point in contract["score_points"]
        if point["required_for_pass"]
    )
    return {
        "finalized": True,
        "score_out_of_10": score,
        "compatibility_score_points": score / 5,
        "question_passed": passed,
    }
