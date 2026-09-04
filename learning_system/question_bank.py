from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Any

from . import child_prompt, question_usage, question_visuals
from .error_tags import CANONICAL_ERROR_TAGS


BASE_RUBRIC = [
    {
        "result": "correct",
        "points": 2,
        "evidence": "结果正确，关键步骤可复盘，且能用一句话解释方法。",
    },
    {
        "result": "partial",
        "points": 1,
        "evidence": "核心关系或方法部分正确，但计算、表达、单位或解释不稳。",
    },
    {
        "result": "wrong",
        "points": 0,
        "evidence": "答案错误、跳过，或无法说清关键概念/关系。",
    },
]

QUESTION_BANK_VERSION = "2026-07-22.bank.v17.expanded-1000"
QUESTION_BANK_V12_VERSION = "2026-07-12.bank.v12"
QUESTION_BANK_V12_SCHEMA_VERSION = "2026-07-12.math-question-bank.v12.asset.v1"
EVOLVED_ITEM_VERSION = "2026-07-07.evolved.v5"
QUESTION_PRODUCTION_CONTRACT_VERSION = "2026-07-22.question-production.v17"
QUESTION_COORDINATOR_AGENT_KEY = "question_agent"
QUESTION_DESIGNER_AGENT_KEY = "question_designer_agent"
QUESTION_REVIEWER_AGENT_KEY = "question_reviewer_agent"
QUESTION_ID_PREFIX = "QB17"
INCOMING_GRADE_7_AGE_FLOOR = "incoming_grade_7"
FORMAL_ADMIN_PRODUCTION_SOURCE = "admin_reviewed_graph_production"
FORMAL_ADMIN_REVIEW_CONTRACT_VERSION = "2026-07-28.admin-reviewed-question.v1"
PRODUCTION_CATEGORY_TEACHING_DIAGNOSTIC = "teaching_diagnostic"
PRODUCTION_CATEGORY_CHALLENGING_PRACTICE = "challenging_practice"
EVIDENCE_MODE_GUIDED_FORMATIVE = "guided_formative"
EVIDENCE_MODE_NO_HINT_CONFIRMATION = "no_hint_confirmation"
EVIDENCE_MODE_TRANSFER_SIGNAL_ONLY = "transfer_signal_only"
TEACHING_DIAGNOSTIC_EVIDENCE_MODES = frozenset(
    {
        EVIDENCE_MODE_GUIDED_FORMATIVE,
        EVIDENCE_MODE_NO_HINT_CONFIRMATION,
    }
)
INDEPENDENT_LIVE_REVIEW_MIN_RECEIPTS = 3
INDEPENDENT_LIVE_REVIEW_REQUIRED_PROFILES = frozenset(
    {
        "frontline_math_teacher",
        "diagnostic_assessment_expert",
        "sixth_grade_child_perspective",
    }
)
INDEPENDENT_LIVE_REVIEW_ADJUDICATOR_PROFILE = (
    "senior_question_review_adjudicator"
)
INDEPENDENT_LIVE_REVIEW_MIN_CONFIDENCE = 0.86
INDEPENDENT_LIVE_REVIEW_DIRECT_PASS_CONFIDENCE = 0.90
FORMAL_PRODUCTION_CATEGORIES = frozenset(
    {
        PRODUCTION_CATEGORY_TEACHING_DIAGNOSTIC,
        PRODUCTION_CATEGORY_CHALLENGING_PRACTICE,
    }
)
QUESTIONS_PER_GRAPH_NODE = 20
V12_FULL_BANK_NODE_COUNT = 56
V12_FULL_BANK_ITEM_COUNT = V12_FULL_BANK_NODE_COUNT * QUESTIONS_PER_GRAPH_NODE
V12_PILOT_SIX_NODE_IDS = (
    "M-G7-EQ-DENOM",
    "M-G7-NUMBER-LINE",
    "M-G7-RATIONAL-ADD-SUB",
    "M-BRIDGE-MOTION-CHASE",
    "M-G7-GEO-VIEWS",
    "M-PRE-UNIT-CONVERSION",
)
V12_NODE_SET_REVIEW_SHARD_SIZE = 2
V12_NODE_SET_REVIEW_ACTIVATION_CONCURRENCY = 1
MIN_DISTINCT_QUESTION_TYPES_PER_NODE = 8
MIN_DISTINCT_QUESTION_KINDS_PER_NODE = 8
MIN_PROBLEM_FAMILIES_PER_NODE = 6
MAX_PROBLEM_FAMILY_REPEAT_PER_NODE = 4
MAX_CORE_STEM_REPEAT_PER_NODE = 2
MIN_CANONICAL_CORE_STEMS_PER_NODE = 12

PROBLEM_FAMILY_KIND_GROUPS: dict[str, str] = {
    "standard_example": "model_application_and_verification",
    "check_strategy": "model_application_and_verification",
    "communication": "model_application_and_verification",
    "essence_check": "concept_boundary_and_misconception",
    "misconception_probe": "concept_boundary_and_misconception",
    "explanation_only": "concept_boundary_and_misconception",
    "boundary_case": "concept_boundary_and_misconception",
    "error_spotting": "error_repair_and_symbol_audit",
    "symbol_unit_audit": "error_repair_and_symbol_audit",
    "self_correction": "error_repair_and_symbol_audit",
    "variant": "transfer_and_rule_stability",
    "transfer_retest": "transfer_and_rule_stability",
    "stretch_transfer": "transfer_and_rule_stability",
    "missing_condition": "representation_condition_prerequisite",
    "representation": "representation_condition_prerequisite",
    "prerequisite_probe": "representation_condition_prerequisite",
    "reverse_reasoning": "reverse_reasoning",
    "estimation_modeling": "estimation_and_range_control",
    "two_method_compare": "method_comparison",
    "model_selection": "model_selection",
}

CORE_STEM_KEYS_BY_TEMPLATE_SLOT: dict[int, tuple[str, ...]] = {
    1: ("problem", "rule", "check"),
    2: ("wrong_solution", "wrong_reason"),
    3: ("method_a", "method_b", "problem"),
    4: ("variant_problem", "variant_answer"),
    5: ("representation", "problem"),
    6: ("condition", "problem"),
    7: ("short_answer", "problem", "check"),
    8: ("implausible_answer", "problem"),
    9: ("bad_rule", "problem"),
    10: ("method_a", "representation", "problem"),
    11: ("incomplete_answer", "problem"),
    12: ("rule_options", "problem"),
    13: ("condition", "common_mistake", "problem"),
    14: ("common_mistake", "problem"),
    15: ("condition", "problem"),
    16: ("check", "problem"),
    17: ("variant_problem", "changed_condition"),
    18: ("claim_a", "claim_b", "problem"),
    19: ("irrelevant", "problem_with_irrelevant"),
    20: ("problem", "rule", "incomplete_answer"),
}

PROBLEM_INSTANCE_FIELD_BY_TEMPLATE_SLOT: dict[int, str] = {
    1: "problem",
    2: "wrong_solution",
    3: "problem",
    4: "variant_problem",
    5: "problem",
    6: "problem",
    7: "problem",
    8: "problem",
    9: "problem",
    10: "problem",
    11: "incomplete_answer",
    12: "problem",
    13: "problem",
    14: "problem",
    15: "problem",
    16: "problem",
    17: "variant_problem",
    18: "problem",
    19: "problem_with_irrelevant",
    20: "problem",
}

PROCESS_EVIDENCE_REQUIREMENTS = [
    "写出关键规则/关系/模型",
    "呈现必要步骤或结构化推理",
    "用检验、反例、错因辨析或迁移说明证明方法可靠",
]

MIN_NODE_LOCAL_MAINLINE_ITEMS_PER_NODE = 14
MAX_PICTURE_LEVEL_CHALLENGES_PER_NODE = 4
MAX_SAME_PICTURE_CHALLENGE_LABEL_PER_NODE = 2
MAX_SAME_PICTURE_CHALLENGE_STEM_NODES = 2
MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND = 1
MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND = 2
MIN_NODE_LOCAL_MAINLINE_TASKS_PER_ROUND = 7
CONTROLLED_ADVANCED_CHALLENGE_SLOTS = {14, 19}

PICTURE_LEVEL_CHALLENGE_NODE_ALLOWLIST: dict[str, set[str]] = {
    "digit_reverse_place_value": {"M-BRIDGE-SOLUTION-HABIT", "M-PRE-INTEGER-OPS"},
    "coordinate_pattern_square_layer": {"M-PRE-NUMBER-SENSE", "M-G7-NUMBER-LINE"},
    "pigeonhole_prefix_sum_proof": {"M-PRE-QUANTITY-RELATION", "M-BRIDGE-WORD-PROBLEM-READING"},
    "alternating_sum_structure": {"M-G7-POS-NEG"},
    "absolute_value_distance_model": {"M-G7-ABSOLUTE"},
    "parameter_comparison": {"M-G7-COMPARE"},
    "case_split_absolute_value": {"M-G7-OPPOSITE"},
    "telescoping_sum": {"M-G7-RATIONAL-ADD-SUB"},
    "telescoping_product": {"M-G7-RATIONAL-MUL-DIV"},
    "custom_operation_structure": {"M-G7-RATIONAL-MIXED"},
}

REVIEWER_EVIDENCE_FLAGS = (
    "graph_bound",
    "incoming_grade_7_ready",
    "diagnostic_structure",
    "process_evidence_required",
    "not_mechanical_drill",
    "child_prompt_self_contained",
    "specific_expected_answer",
)

GRAPH_SEED_REVIEW_MANIFEST_ID = "math_graph_seed_question_bank_v11_curated_review"
DETERMINISTIC_EVOLUTION_REVIEW_STRATEGIES = {
    "same_node_error_retest",
    "cannot_start_repair",
}

V12_SLOT_ROLES = (
    "concept_boundary",
    "essence_model",
    "standard_model",
    "standard_example",
    "representation_translation",
    "wrong_solution_repair",
    "necessary_condition",
    "same_structure_confirmation",
    "near_transfer",
    "alternative_method",
    "inverse_check",
    "expression_notation",
    "prerequisite_probe",
    "integrated_transfer",
    "calculation_symbol_precision",
    "model_selection",
    "misconception_boundary",
    "multi_representation",
    "stretch_readiness_check",
    "summary_transfer_check",
)
V12_ROOT_READINESS_SLOT_ROLE = "root_readiness_probe"
V12_PROCESS_UNPROMPTED_SLOTS = {9, 14, 19, 20}
V12_UNPROMPTED_PROCESS_ELICITATION_MODE = "unprompted_process_evidence"
V12_MAINLINE_ROLE_MINIMUM = 14
V12_MAX_CORE_REPEAT_PER_NODE = 2
V12_MAX_CONTROLLED_STRETCH_PER_NODE = 2
V12_REVIEW_PROVENANCE = "v12_independent_semantic_review"
V12_SOURCE_TYPE = "external_v12_question_bank"
V12_REVIEW_MIN_SCORE = 0.80
V12_REVIEW_MIN_CONFIDENCE = 0.88
V12_NODE_SET_REVIEW_MIN_CONFIDENCE = 0.88
V12_SEMANTIC_GATE_MIN_SCORE = 0.88
V12_NATURAL_CHINESE_MIN_SCORE = 0.85
V12_RENDERED_NOTATION_REQUIRED_SCORE = 1.0
V12_AGE_DIGNITY_MIN_SCORE = 0.90
V12_UNPROMPTED_PROCESS_MIN_SCORE = 0.90
V12_MAX_RESPONSE_MOVES = 3
V12_MIN_INSTRUCTION_VOICE_FAMILIES = 6
V12_MAX_REPETITIVE_INSTRUCTION_CLUSTER = 4
V12_MAX_CONSECUTIVE_INSTRUCTION_VOICE = 2
V12_INSTRUCTION_VOICE_FAMILIES = (
    "solve_and_interpret",
    "compare_and_choose",
    "diagnose_and_repair",
    "represent_and_translate",
    "classify_and_justify",
    "estimate_and_predict",
    "construct_or_complete",
    "reverse_reasoning",
    "validate_a_claim",
    "explain_a_relationship",
)
V12_AGENT_KNOWLEDGE_VERSION = "2026-07-12.math-qb-v12.review-policy.v4"
V12_AGENT_KNOWLEDGE_PATH = Path(__file__).resolve().parent / "agent_knowledge/math_question_bank_v12_review_policy.v4.json"
V12_DESIGNER_CONTRACT_VERSION = "2026-07-12.math-qb-v12.designer-batch.v4"
V12_DESIGNER_PROMPT_VERSION_ID = "2026-07-12.math-qb-v12.designer.prompt.v4"
V12_DESIGNER_RESPONSE_SCHEMA_VERSION = "2026-07-12.math-qb-v12.designer.schema.v4"
V12_REVIEWER_CONTRACT_VERSION = "2026-07-12.math-qb-v12.reviewer-batch.v4"
V12_REVIEWER_PROMPT_VERSION_ID = "2026-07-12.math-qb-v12.reviewer.prompt.v4"
V12_REVIEWER_RESPONSE_SCHEMA_VERSION = "2026-07-12.math-qb-v12.reviewer.schema.v4"
V12_NODE_SET_FOCAL_REVIEWER_CONTRACT_VERSION = "2026-07-12.math-qb-v12.node-set-focal-reviewer.v4"
V12_NODE_SET_FOCAL_REVIEWER_PROMPT_VERSION_ID = "2026-07-12.math-qb-v12.node-set-focal-reviewer.prompt.v4"
V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION = "2026-07-12.math-qb-v12.node-set-focal-review.schema.v4"
V12_NODE_SET_GLOBAL_FINALIZER_CONTRACT_VERSION = "2026-07-17.math-qb-v12.node-set-global-finalizer.v6"
V12_NODE_SET_GLOBAL_FINALIZER_PROMPT_VERSION_ID = "2026-07-17.math-qb-v12.node-set-global-finalizer.prompt.v6"
V12_NODE_SET_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION = "2026-07-17.math-qb-v12.node-set-global-model-judgment.schema.v6"
V12_NODE_SET_GLOBAL_FINALIZER_MODEL_EVIDENCE_VERSION = "2026-07-17.math-qb-v12.node-set-global-model-judgment.v6"
V12_NODE_SET_GLOBAL_FINALIZER_PROMPT_TEMPLATE_SHA256 = "99bc460a9de41096afef67b262a26d4a5a639969570da877df243233326fb672"
V12_NODE_SET_GLOBAL_FINALIZER_RESPONSE_SCHEMA_SHA256 = "1a3a971c176f8fe1f359008a2cf4cfa20ae74375fe36063e06902978fdd66428"
V12_NODE_SET_GLOBAL_FINALIZER_REQUEST_LINEAGE_VERSION = "2026-07-17.math-qb-v12.node-set-global-finalizer-request.v3"
V12_NODE_SET_GLOBAL_VERIFIER_CONTRACT_VERSION = "2026-07-17.math-qb-v12.node-set-global-verifier.v2"
V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_VERSION_ID = "2026-07-17.math-qb-v12.node-set-global-verifier.prompt.v2"
V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_VERSION = "2026-07-17.math-qb-v12.node-set-global-verifier-shard.schema.v2"
V12_NODE_SET_GLOBAL_VERIFIER_SHARD_MODEL_EVIDENCE_VERSION = "2026-07-17.math-qb-v12.node-set-global-verifier-shard-judgment.v2"
V12_NODE_SET_GLOBAL_VERIFIER_SEMANTIC_EVIDENCE_VERSION = "2026-07-17.math-qb-v12.node-set-global-verifier-evidence.v2"
V12_NODE_SET_GLOBAL_VERIFIER_SHARD_SEMANTIC_EVIDENCE_VERSION = "2026-07-17.math-qb-v12.node-set-global-verifier-shard-evidence.v2"
V12_NODE_SET_GLOBAL_VERIFIER_AGGREGATE_VERSION = "2026-07-17.math-qb-v12.node-set-global-verifier-aggregate.v2"
V12_NODE_SET_GLOBAL_VERIFIER_SHARD_POLICY_VERSION = "2026-07-17.math-qb-v12.node-set-global-verifier-shards.v2"
V12_NODE_SET_GLOBAL_VERIFIER_SHARD_SIZE = 5
V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_TEMPLATE_SHA256 = "10e29d25461be6d4cb23e9e645b77be90788359cfa2267bd7ddc40550339c53b"
V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_SHA256 = "88182911c8ec079379c2d63d8e13935432178f444bc8caeafff0daa87ed14e38"
V12_NODE_SET_GLOBAL_VERIFIER_REQUEST_LINEAGE_VERSION = "2026-07-17.math-qb-v12.node-set-global-verifier-shard-request.v2"
V12_NODE_SET_GLOBAL_FINALIZER_MODEL_FIELDS = frozenset({
    "schema_version",
    "node_id",
    "graph_version",
    "question_bank_version",
    "semantic_evidence_version",
    "item_classifications",
    "homogeneous_clusters",
    "distribution_scores",
    "repetitive_instruction_clusters",
    "duplicate_groups",
    "confidence",
    "reasons",
    "repair_plan",
})
V12_OWNERSHIP_MODES = (
    "current_node_mainline",
    "current_node_with_prerequisite_support",
    "prerequisite_only",
    "controlled_stretch",
)
V12_CURRENT_NODE_INDISPENSABLE = ("yes", "no")
V12_PRIMARY_EVIDENCE_MOVES = (
    "compute_and_interpret",
    "represent_or_translate",
    "classify_by_definition",
    "compare_or_select",
    "diagnose_or_repair",
    "justify_or_prove",
    "construct",
    "reverse_reason",
    "validate_or_counterexample",
    "parameter_case_analysis",
    "multiple_constraint_reasoning",
    "explain_relationship",
)
V12_ANSWER_PATH_FAMILIES = (
    "direct_calculation",
    "equation_or_expression",
    "representation_translation",
    "classification",
    "comparison_selection",
    "error_diagnosis",
    "parameter_cases",
    "construction",
    "proof",
    "counterexample",
    "multiple_constraints",
)
V12_REPRESENTATION_FAMILIES = (
    "numeric_symbolic",
    "verbal_symbolic",
    "labeled_lines",
    "number_line",
    "diagram_spatial",
    "equation_model",
    "algebraic_structure",
    "multiple_representations",
    "contextual_quantity",
)
V12_DIFFICULTY_VERDICTS = ("L1", "L2", "L3", "L4", "stretch")
V12_DIFFICULTY_FEATURES = (
    "parameter_cases",
    "construction",
    "proof",
    "counterexample",
    "multiple_constraints",
)
V12_MIN_PRIMARY_EVIDENCE_MOVE_FAMILIES = 8
V12_MAX_HOMOGENEOUS_CLUSTER = 4
V12_NODE_SET_GLOBAL_FULL_OUTPUT_SCHEMA_VERSION = "2026-07-12.math-qb-v12.node-set-global-finalizer.schema.v4"
# Existing node-set names identify the bounded two-slot focal phase.
V12_NODE_SET_REVIEWER_CONTRACT_VERSION = V12_NODE_SET_FOCAL_REVIEWER_CONTRACT_VERSION
V12_NODE_SET_REVIEWER_PROMPT_VERSION_ID = V12_NODE_SET_FOCAL_REVIEWER_PROMPT_VERSION_ID
V12_NODE_SET_REVIEWER_RESPONSE_SCHEMA_VERSION = V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION
V12_GLOBAL_FINALIZER_CONTRACT_VERSION = V12_NODE_SET_GLOBAL_FINALIZER_CONTRACT_VERSION
V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID = V12_NODE_SET_GLOBAL_FINALIZER_PROMPT_VERSION_ID
V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION = V12_NODE_SET_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION
V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION = "2026-07-12.math-qb-v12.item-review-semantic-evidence.v4"
V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION = "2026-07-12.math-qb-v12.node-set-focal-evidence.v4"
V12_NODE_SET_GLOBAL_REVIEW_SEMANTIC_EVIDENCE_VERSION = "2026-07-12.math-qb-v12.node-set-global-evidence.v4"
V12_NODE_SET_REVIEW_SEMANTIC_EVIDENCE_VERSION = V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION
V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION = V12_NODE_SET_GLOBAL_REVIEW_SEMANTIC_EVIDENCE_VERSION
V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION = "2026-07-12.math-qb-v12.node-set-aggregate-evidence.v4"
V12_LEGACY_SEMANTIC_EVIDENCE_COMMITMENT_VERSION = "2026-07-12.math-qb-v12.semantic-evidence-commitment.v4"
V12_SEMANTIC_EVIDENCE_COMMITMENT_VERSION = "2026-07-17.math-qb-v12.semantic-evidence-commitment.v6"
V12_RUNNER_RECEIPT_SCHEMA_VERSION = "2026-07-17.math-qb-v12.runner-receipt.v5"
V12_COMPLETED_NODE_RECEIPT_SCHEMA_VERSION = "2026-07-12.math-qb-v12.completed-node-receipt.v4"
V12_ACTIVE_QUALITY_CONTRACT_VERSION = "2026-07-12.math-qb-v12.active-quality.v4"
V12_STRUCTURED_QUALITY_BASIS = "v12_v6_bound_independent_verifier_and_global_finalizer_evidence"
V12_CROSS_NODE_SUMMARY_CONTEXT_SCHEMA_VERSION = "2026-07-16.math-qb-v12.cross-node-summary-context.v1"
V12_CROSS_NODE_SUMMARY_SELECTOR_POLICY_VERSION = "2026-07-16.math-qb-v12.cross-node-summary-selector.v1"
V12_CROSS_NODE_SUMMARY_MAX_SELECTED = 80
V12_MODEL_BUDGET_SCHEMA_VERSION = "2026-07-16.v12-model-budget.v2"
QUESTION_INTERACTION_SCHEMA_VERSION = child_prompt.QUESTION_INTERACTION_SCHEMA_V2
QUESTION_INTERACTION_CURRENT_SCHEMA_VERSION = child_prompt.QUESTION_INTERACTION_SCHEMA_V2
QUESTION_INTERACTION_LEGACY_SCHEMA_VERSION = child_prompt.QUESTION_INTERACTION_SCHEMA_V1
QUESTION_INTERACTION_TYPES = set(child_prompt.INTERACTION_TYPES)
QUESTION_INTERACTION_FORBIDDEN_KEYS = set(child_prompt.FORBIDDEN_SCHEMA_KEYS)
CHILD_PROMPT_FORMAT = child_prompt.CHILD_PROMPT_FORMAT
CHILD_SURFACE_PROJECTION_VERSION = child_prompt.CHILD_SURFACE_PROJECTION_VERSION
V12_CHILD_SURFACE_DESIGN = {
    "prompt_mode": "natural_self_contained_mathematical_task",
    "notation_mode": "child_surface_plain_math",
    "response_burden": "single_coherent_current_step",
}
V12_SEMANTIC_EVIDENCE_DIMENSIONS = ("natural_self_contained_task",)
V12_CONTENT_REVIEW_SCORE_KEYS: tuple[str, ...] = ()
V12_REVIEW_SCORE_KEYS = (
    "node_alignment",
    "mathematical_correctness",
    "reasoning_signal",
    "non_mechanical",
    "answer_alignment",
)
V12_NODE_SET_DISTRIBUTION_SCORE_KEYS = (
    "semantic_diversity",
    "slot_fit",
    "difficulty_distribution",
    "problem_family_distribution",
    "age_context_fit",
    "instruction_voice_variety",
)
V12_DIFFICULTY_VECTOR_RANGES = {
    "concept_demand": (1, 4),
    "reasoning_steps": (1, 8),
    "calculation_load": (1, 4),
    "representation_demand": (1, 4),
    "transfer_distance": (0, 4),
}


@lru_cache(maxsize=1)
def _v12_agent_knowledge_cached() -> dict[str, Any]:
    knowledge = json.loads(V12_AGENT_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    if knowledge.get("knowledge_version") != V12_AGENT_KNOWLEDGE_VERSION:
        raise ValueError("v12 agent knowledge version mismatch")
    if tuple(knowledge.get("instruction_voice_families") or []) != V12_INSTRUCTION_VOICE_FAMILIES:
        raise ValueError("v12 agent knowledge instruction voice enum mismatch")
    role_matrix = knowledge.get("role_voice_matrix") if isinstance(knowledge.get("role_voice_matrix"), dict) else {}
    expected_roles = set(V12_SLOT_ROLES) | {V12_ROOT_READINESS_SLOT_ROLE}
    if set(role_matrix) != expected_roles:
        raise ValueError("v12 agent knowledge role voice coverage mismatch")
    for role, policy in role_matrix.items():
        if not isinstance(policy, dict):
            raise ValueError(f"v12 agent knowledge role policy malformed: {role}")
        preferred = policy.get("preferred") if isinstance(policy.get("preferred"), list) else []
        allowed = policy.get("allowed") if isinstance(policy.get("allowed"), list) else []
        if not preferred or not allowed or not set(preferred).issubset(set(allowed)):
            raise ValueError(f"v12 agent knowledge role voice policy incomplete: {role}")
        if any(family not in V12_INSTRUCTION_VOICE_FAMILIES for family in allowed):
            raise ValueError(f"v12 agent knowledge role voice family invalid: {role}")
    return knowledge


def v12_agent_knowledge() -> dict[str, Any]:
    return copy.deepcopy(_v12_agent_knowledge_cached())


def v12_agent_knowledge_sha256() -> str:
    return _v12_digest_json(_v12_agent_knowledge_cached())


def v12_role_voice_policy(slot_role: str) -> dict[str, Any]:
    matrix = _v12_agent_knowledge_cached()["role_voice_matrix"]
    policy = matrix.get(str(slot_role) or "")
    return copy.deepcopy(policy) if isinstance(policy, dict) else {}


def v12_instruction_voice_plan(node: dict[str, Any]) -> dict[int, str]:
    knowledge = _v12_agent_knowledge_cached()
    design_target = int((knowledge.get("initial_plan") or {}).get("design_target_distinct_families") or 8)
    plan: dict[int, str] = {}
    used: set[str] = set()
    recent: list[str] = []
    for slot in range(1, QUESTIONS_PER_GRAPH_NODE + 1):
        role = v12_slot_role_for_node(node, slot)
        policy = v12_role_voice_policy(role)
        preferred = list(policy.get("preferred") or [])
        allowed = list(policy.get("allowed") or [])
        ordered = preferred + [family for family in allowed if family not in preferred]
        viable = [
            family
            for family in ordered
            if not (len(recent) >= V12_MAX_CONSECUTIVE_INSTRUCTION_VOICE and all(
                previous == family for previous in recent[-V12_MAX_CONSECUTIVE_INSTRUCTION_VOICE:]
            ))
        ]
        if not viable:
            raise ValueError(f"v12 instruction voice plan has no role-compatible target for slot {slot}:{role}")
        if len(used) < design_target:
            unseen = [family for family in viable if family not in used]
            selected = unseen[0] if unseen else viable[0]
        else:
            selected = viable[0]
        plan[slot] = selected
        used.add(selected)
        recent.append(selected)
    distribution = Counter(plan.values())
    if len(distribution) < V12_MIN_INSTRUCTION_VOICE_FAMILIES:
        raise ValueError("v12 instruction voice plan does not meet the hard family minimum")
    if _v12_consecutive_voice_violation_slots([
        {"instruction_voice_family": family, "slots": [slot for slot, current in plan.items() if current == family]}
        for family in V12_INSTRUCTION_VOICE_FAMILIES
        if family in distribution
    ]):
        raise ValueError("v12 instruction voice plan exceeds the consecutive-family limit")
    return plan


def v12_instruction_voice_target_errors(node: dict[str, Any], item: dict[str, Any]) -> list[str]:
    role = str(item.get("slot_role") or "")
    intended = str(item.get("intended_instruction_voice_family") or "")
    policy = v12_role_voice_policy(role)
    errors: list[str] = []
    if intended not in V12_INSTRUCTION_VOICE_FAMILIES:
        errors.append("intended_instruction_voice_family:missing_or_invalid")
    elif intended not in set(policy.get("allowed") or []):
        errors.append("intended_instruction_voice_family:not_allowed_for_slot_role")
    return errors


def v12_instruction_voice_evidence_errors(item: dict[str, Any], evidence: Any) -> list[str]:
    if not isinstance(evidence, dict):
        return ["instruction_voice_evidence:not_object"]
    actual = str(evidence.get("instruction_voice_family") or "")
    intended = str(item.get("intended_instruction_voice_family") or "")
    errors: list[str] = []
    if actual not in V12_INSTRUCTION_VOICE_FAMILIES:
        errors.append("instruction_voice_family:invalid")
    elif actual != intended:
        errors.append("instruction_voice_family:intended_mismatch")
    return errors


def v12_process_disclosure_gate_errors(item: dict[str, Any], evidence: Any) -> list[str]:
    if not isinstance(evidence, dict):
        return ["process_disclosure_evidence:not_object"]
    disclosure = evidence.get("process_disclosure_evidence")
    disclosure = disclosure if isinstance(disclosure, dict) else {}
    disclosed = evidence.get("process_target_disclosed") is True
    source = str(disclosure.get("source_field") or "")
    quote = str(disclosure.get("quote") or "")
    prompt = str(item.get("prompt") or "")
    errors: list[str] = []
    if set(disclosure) != {"verdict", "source_field", "quote", "reason"}:
        errors.append("process_disclosure_evidence:unexpected_or_missing_fields")
    if disclosed and disclosure.get("verdict") != "disclosed":
        errors.append("process_disclosure_evidence:verdict_mismatch")
    if not disclosed and disclosure.get("verdict") != "not_disclosed":
        errors.append("process_disclosure_evidence:verdict_mismatch")
    if disclosed and (source != "child_visible.prompt" or not quote or quote not in prompt):
        errors.append("process_disclosure_evidence:exact_child_prompt_quote_required")
    if not disclosed and (source != "none" or quote):
        errors.append("process_disclosure_evidence:not_disclosed_shape_invalid")
    if v12_item_requires_unprompted_process_evidence(item) and disclosed:
        errors.append("unprompted_process_evidence:process_target_disclosed")
    if not str(disclosure.get("reason") or "").strip():
        errors.append("process_disclosure_evidence:reason_missing")
    return errors


def v12_local_shard_output_errors(
    node_entry: dict[str, Any],
    *,
    reviewed_slots: list[int],
    output: dict[str, Any],
) -> list[str]:
    errors_by_slot = v12_node_set_focal_review_output_errors(
        node_entry,
        reviewed_slots=reviewed_slots,
        output=output,
    )
    return sorted({detail for details in errors_by_slot.values() for detail in details})


def v12_global_review_reduce(
    node_entry: dict[str, Any],
    constituent_reviews: list[dict[str, Any]],
    global_output: dict[str, Any],
) -> dict[str, Any]:
    return v12_reduce_node_set_v4(node_entry, constituent_reviews, global_output)


def v12_global_model_judgment_errors(
    model_judgment: Any,
    *,
    node_id: str = "",
    graph_version: str = "",
) -> list[str]:
    if not isinstance(model_judgment, dict):
        return ["model_judgment_output:not_object"]
    errors: list[str] = []
    if set(model_judgment) != set(V12_NODE_SET_GLOBAL_FINALIZER_MODEL_FIELDS):
        errors.append("model_judgment_output:unexpected_or_missing_fields")
    expected_constants = {
        "schema_version": V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "question_bank_version": QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": V12_NODE_SET_GLOBAL_FINALIZER_MODEL_EVIDENCE_VERSION,
    }
    if node_id:
        expected_constants["node_id"] = node_id
    if graph_version:
        expected_constants["graph_version"] = graph_version
    for key, expected in expected_constants.items():
        if model_judgment.get(key) != expected:
            errors.append(f"model_judgment_output.{key}:mismatch")
    classifications = model_judgment.get("item_classifications")
    classification_fields = {
        "slot",
        "node_id",
        "item_id",
        "candidate_sha256",
        "child_surface_sha256",
        "item_review_request_sha256",
        "item_review_semantic_evidence_sha256",
        "ownership_mode",
        "current_node_indispensable",
        "primary_evidence_move",
        "answer_path_family",
        "representation_family",
        "difficulty_verdict",
        "difficulty_features",
        "prompt_interaction_verdict",
        "reason",
    }
    if not isinstance(classifications, list) or len(classifications) != QUESTIONS_PER_GRAPH_NODE:
        errors.append("model_judgment_output.item_classifications:requires_exactly_20")
    else:
        slots: list[int] = []
        enum_contracts = {
            "ownership_mode": set(V12_OWNERSHIP_MODES),
            "current_node_indispensable": set(V12_CURRENT_NODE_INDISPENSABLE),
            "primary_evidence_move": set(V12_PRIMARY_EVIDENCE_MOVES),
            "answer_path_family": set(V12_ANSWER_PATH_FAMILIES),
            "representation_family": set(V12_REPRESENTATION_FAMILIES),
            "difficulty_verdict": set(V12_DIFFICULTY_VERDICTS),
            "prompt_interaction_verdict": {"aligned", "mismatch"},
        }
        for index, classification in enumerate(classifications):
            if not isinstance(classification, dict) or set(classification) != classification_fields:
                errors.append(
                    f"model_judgment_output.item_classifications[{index}]:unexpected_or_missing_fields"
                )
                continue
            slot = classification.get("slot")
            if not isinstance(slot, int) or not 1 <= slot <= QUESTIONS_PER_GRAPH_NODE:
                errors.append(f"model_judgment_output.item_classifications[{index}].slot:invalid")
            else:
                slots.append(slot)
            for key, allowed in enum_contracts.items():
                if classification.get(key) not in allowed:
                    errors.append(
                        f"model_judgment_output.item_classifications[{index}].{key}:invalid"
                    )
            features = classification.get("difficulty_features")
            if not isinstance(features, list) or any(
                feature not in V12_DIFFICULTY_FEATURES for feature in features
            ):
                errors.append(
                    f"model_judgment_output.item_classifications[{index}].difficulty_features:invalid"
                )
            if not str(classification.get("reason") or "").strip():
                errors.append(f"model_judgment_output.item_classifications[{index}].reason:missing")
        if sorted(slots) != list(range(1, QUESTIONS_PER_GRAPH_NODE + 1)):
            errors.append("model_judgment_output.item_classifications:slot_coverage_mismatch")
    scores = model_judgment.get("distribution_scores")
    if not isinstance(scores, dict) or set(scores) != set(V12_NODE_SET_DISTRIBUTION_SCORE_KEYS):
        errors.append("model_judgment_output.distribution_scores:unexpected_or_missing_fields")
    nested_contracts = (
        (
            "homogeneous_clusters",
            {"cluster_id", "slots", "reason", "subject_sha256s"},
        ),
        (
            "repetitive_instruction_clusters",
            {"cluster_id", "slots", "cluster_summary", "reason", "evidence_refs", "subject_sha256s"},
        ),
        (
            "duplicate_groups",
            {"group_id", "slots", "reason", "evidence_refs", "subject_sha256s"},
        ),
        (
            "repair_plan",
            {
                "slot",
                "repair_scope",
                "preserved_role",
                "preserve_or_replace_math_core",
                "required_voice_family",
                "avoided_voice_families",
                "exact_target_delta",
                "evidence_refs",
            },
        ),
    )
    for key, expected_fields in nested_contracts:
        values = model_judgment.get(key)
        if not isinstance(values, list):
            errors.append(f"model_judgment_output.{key}:not_array")
            continue
        for index, value in enumerate(values):
            if not isinstance(value, dict) or set(value) != expected_fields:
                errors.append(f"model_judgment_output.{key}[{index}]:unexpected_or_missing_fields")
                continue
            if key == "repair_plan":
                delta = value.get("exact_target_delta")
                if not isinstance(delta, dict) or set(delta) != {"dimension", "from_value", "to_value"}:
                    errors.append(
                        f"model_judgment_output.{key}[{index}].exact_target_delta:unexpected_or_missing_fields"
                    )
    return sorted(set(errors))


def v12_bind_global_model_judgment(
    node_entry: dict[str, Any],
    model_judgment: dict[str, Any],
    *,
    graph_version: str,
) -> dict[str, Any]:
    bound = copy.deepcopy(model_judgment)
    bound["schema_version"] = V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION
    bound["node_id"] = node_entry.get("node_id")
    bound["graph_version"] = graph_version
    bound["question_bank_version"] = QUESTION_BANK_V12_VERSION
    bound["semantic_evidence_version"] = V12_NODE_SET_GLOBAL_FINALIZER_MODEL_EVIDENCE_VERSION
    item_by_slot = _v12_item_by_slot(node_entry)
    subject_by_slot = {
        slot: v12_item_review_subject_binding(item)
        for slot, item in item_by_slot.items()
    }
    classifications = []
    for entry in bound.get("item_classifications") or []:
        if not isinstance(entry, dict):
            continue
        try:
            slot = int(entry.get("slot") or 0)
        except (TypeError, ValueError):
            continue
        subject = subject_by_slot.get(slot)
        if not subject:
            continue
        classifications.append({
            **entry,
            **{
                key: subject[key]
                for key in (
                    "node_id",
                    "slot",
                    "item_id",
                    "candidate_sha256",
                    "child_surface_sha256",
                    "item_review_request_sha256",
                    "item_review_semantic_evidence_sha256",
                )
            },
        })
    bound["item_classifications"] = sorted(
        classifications,
        key=lambda value: int(value.get("slot") or 0),
    )
    for key in ("homogeneous_clusters", "repetitive_instruction_clusters", "duplicate_groups"):
        groups = []
        for group in bound.get(key) or []:
            if not isinstance(group, dict):
                continue
            slots = _v12_canonical_slot_list(group.get("slots"))
            groups.append({
                **group,
                "slots": slots,
                "subject_sha256s": sorted(
                    subject_by_slot[slot]["subject_sha256"]
                    for slot in slots
                    if slot in subject_by_slot
                ),
            })
        bound[key] = groups
    return bound


def v12_global_model_judgment_binding_errors(
    node_entry: dict[str, Any],
    model_judgment: Any,
) -> list[str]:
    if not isinstance(model_judgment, dict):
        return ["model_judgment_binding:not_object"]
    item_by_slot = _v12_item_by_slot(node_entry)
    subject_by_slot = {
        slot: v12_item_review_subject_binding(item)
        for slot, item in item_by_slot.items()
    }
    errors: list[str] = []
    classifications = model_judgment.get("item_classifications")
    if not isinstance(classifications, list):
        return ["model_judgment_binding.item_classifications:not_array"]
    binding_fields = (
        "node_id",
        "slot",
        "item_id",
        "candidate_sha256",
        "child_surface_sha256",
        "item_review_request_sha256",
        "item_review_semantic_evidence_sha256",
    )
    for index, classification in enumerate(classifications):
        if not isinstance(classification, dict):
            continue
        slot = classification.get("slot")
        subject = subject_by_slot.get(slot) if isinstance(slot, int) else None
        if not subject:
            errors.append(f"model_judgment_binding.item_classifications[{index}].slot:unknown")
            continue
        for field in binding_fields:
            if classification.get(field) != subject.get(field):
                errors.append(
                    f"model_judgment_binding.item_classifications[{index}].{field}:mismatch"
                )
    for key in ("homogeneous_clusters", "repetitive_instruction_clusters", "duplicate_groups"):
        groups = model_judgment.get(key)
        if not isinstance(groups, list):
            continue
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            slots = _v12_canonical_slot_list(group.get("slots"))
            if len(slots) != len(group.get("slots") or []) or any(
                slot not in subject_by_slot for slot in slots
            ):
                errors.append(f"model_judgment_binding.{key}[{index}].slots:mismatch")
                continue
            expected_subjects = sorted(
                subject_by_slot[slot]["subject_sha256"] for slot in slots
            )
            if group.get("subject_sha256s") != expected_subjects:
                errors.append(
                    f"model_judgment_binding.{key}[{index}].subject_sha256s:mismatch"
                )
    return sorted(set(errors))


def _v12_merge_overlapping_global_verifier_clusters(
    node_entry: dict[str, Any],
    clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        slots = {
            int(slot)
            for slot in cluster.get("slots") or []
            if isinstance(slot, int) and 1 <= slot <= QUESTIONS_PER_GRAPH_NODE
        }
        if not slots:
            continue
        overlapping = [entry for entry in components if entry["slots"] & slots]
        if overlapping:
            merged_slots = set(slots)
            reasons = {str(cluster.get("reason") or "")}
            for entry in overlapping:
                merged_slots.update(entry["slots"])
                reasons.update(entry["reasons"])
                components.remove(entry)
            components.append({"slots": merged_slots, "reasons": reasons})
        else:
            components.append({
                "slots": slots,
                "reasons": {str(cluster.get("reason") or "")},
            })
    item_by_slot = _v12_item_by_slot(node_entry)
    merged: list[dict[str, Any]] = []
    for component in components:
        slots = sorted(component["slots"])
        merged.append({
            "cluster_id": "verifier-homogeneous-" + _v12_digest_json(slots)[:12],
            "slots": slots,
            "reason": " | ".join(sorted(reason for reason in component["reasons"] if reason)),
            "subject_sha256s": sorted(
                v12_item_review_subject_binding(item_by_slot[slot])["subject_sha256"]
                for slot in slots
                if slot in item_by_slot
            ),
        })
    return sorted(merged, key=lambda value: (value["slots"], value["cluster_id"]))


def v12_aggregate_global_verifier_shard_judgments(
    node_entry: dict[str, Any],
    shard_artifacts: list[dict[str, Any]],
    *,
    graph_version: str,
) -> dict[str, Any]:
    expected_shards = v12_expected_global_verifier_shards()
    actual_shards = [
        list(artifact.get("reviewed_slots") or [])
        for artifact in shard_artifacts
        if isinstance(artifact, dict)
    ]
    if actual_shards != expected_shards:
        raise ValueError(f"global verifier shard coverage mismatch: {actual_shards}")
    judgments = [
        artifact.get("model_judgment_output")
        for artifact in shard_artifacts
        if isinstance(artifact.get("model_judgment_output"), dict)
    ]
    if len(judgments) != len(expected_shards):
        raise ValueError("global verifier shard judgment missing")
    classifications = sorted(
        [
            copy.deepcopy(entry)
            for judgment in judgments
            for entry in judgment.get("item_classifications") or []
            if isinstance(entry, dict)
        ],
        key=lambda value: int(value.get("slot") or 0),
    )
    slots = [int(entry.get("slot") or 0) for entry in classifications]
    if slots != list(range(1, QUESTIONS_PER_GRAPH_NODE + 1)):
        raise ValueError(f"global verifier classification coverage mismatch: {slots}")

    def unique_entries(key: str) -> list[dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        for judgment in judgments:
            for entry in judgment.get(key) or []:
                if isinstance(entry, dict):
                    entries.setdefault(_v12_digest_json(entry), copy.deepcopy(entry))
        return sorted(
            entries.values(),
            key=lambda value: (
                list(value.get("slots") or [int(value.get("slot") or 0)]),
                _v12_digest_json(value),
            ),
        )

    aggregate = {
        "schema_version": V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "node_id": node_entry.get("node_id"),
        "graph_version": graph_version,
        "question_bank_version": QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": V12_NODE_SET_GLOBAL_FINALIZER_MODEL_EVIDENCE_VERSION,
        "item_classifications": classifications,
        "homogeneous_clusters": _v12_merge_overlapping_global_verifier_clusters(
            node_entry,
            [
                copy.deepcopy(group)
                for judgment in judgments
                for group in judgment.get("homogeneous_clusters") or []
                if isinstance(group, dict)
            ],
        ),
        "distribution_scores": {
            key: min(
                float((judgment.get("distribution_scores") or {}).get(key) or 0.0)
                for judgment in judgments
            )
            for key in V12_NODE_SET_DISTRIBUTION_SCORE_KEYS
        },
        "repetitive_instruction_clusters": unique_entries("repetitive_instruction_clusters"),
        "duplicate_groups": unique_entries("duplicate_groups"),
        "confidence": min(float(judgment.get("confidence") or 0.0) for judgment in judgments),
        "reasons": sorted({
            str(reason)
            for judgment in judgments
            for reason in judgment.get("reasons") or []
            if str(reason)
        }),
        "repair_plan": unique_entries("repair_plan"),
    }
    errors = v12_global_model_judgment_errors(
        aggregate,
        node_id=str(node_entry.get("node_id") or ""),
        graph_version=graph_version,
    )
    errors.extend(v12_global_model_judgment_binding_errors(node_entry, aggregate))
    if errors:
        raise ValueError("global verifier aggregate failed validation: " + "; ".join(errors[:8]))
    return aggregate


def v12_global_verifier_shard_route_tuples(
    shard_artifacts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "model_provider": str(shard.get("model_provider") or ""),
            "model_name": str(shard.get("model_name") or ""),
            "model_alias": str(shard.get("model_alias") or ""),
            "structured_json_mode": str(shard.get("structured_json_mode") or ""),
        }
        for shard in shard_artifacts
        if isinstance(shard, dict)
    ]


def v12_expand_global_model_judgment(
    node_entry: dict[str, Any],
    constituent_reviews: list[dict[str, Any]],
    model_judgment: dict[str, Any],
    *,
    graph_version: str,
) -> dict[str, Any]:
    """Assemble runtime-owned global evidence around the model's semantic delta."""
    ux = v12_node_set_ux_aggregate(
        node_entry,
        constituent_reviews,
        {
            "node_ux_verdict": "approved",
            "repetitive_instruction_clusters": model_judgment.get("repetitive_instruction_clusters") or [],
        },
    )
    scores = (
        model_judgment.get("distribution_scores")
        if isinstance(model_judgment.get("distribution_scores"), dict)
        else {}
    )
    repair_plan = [
        entry
        for entry in (model_judgment.get("repair_plan") or [])
        if isinstance(entry, dict)
    ]
    rejected_slots = sorted({
        int(entry.get("slot") or 0)
        for entry in repair_plan
        if 1 <= int(entry.get("slot") or 0) <= QUESTIONS_PER_GRAPH_NODE
    })
    focal_rejected = {
        int(slot)
        for review in constituent_reviews
        if isinstance(review, dict)
        for slot in ((_v12_node_set_output(review).get("rejected_slots") or []))
        if isinstance(slot, int)
    }
    low_scores = any(
        _v12_score(scores, key) < V12_REVIEW_MIN_SCORE
        for key in V12_NODE_SET_DISTRIBUTION_SCORE_KEYS
    )
    low_confidence = _v12_score(model_judgment, "confidence") < V12_NODE_SET_REVIEW_MIN_CONFIDENCE
    has_failure = bool(
        focal_rejected
        or ux["gate_errors"]
        or v12_bounded_teaching_quality_gate(node_entry, model_judgment)["gate_errors"]
        or model_judgment.get("duplicate_groups")
        or low_scores
        or low_confidence
        or repair_plan
    )
    return {
        "schema_version": V12_NODE_SET_GLOBAL_FULL_OUTPUT_SCHEMA_VERSION,
        "node_id": node_entry.get("node_id"),
        "graph_version": graph_version,
        "question_bank_version": QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": V12_NODE_SET_GLOBAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "verdict": "needs_repair" if has_failure else "approved",
        "node_ux_verdict": ux["node_ux_verdict"],
        "slot_evidence_coverage": v12_node_set_semantic_evidence_coverage(
            node_entry,
            constituent_reviews,
        ),
        "distribution_scores": {
            key: scores.get(key)
            for key in V12_NODE_SET_DISTRIBUTION_SCORE_KEYS
        },
        "item_classifications": model_judgment.get("item_classifications") or [],
        "homogeneous_clusters": model_judgment.get("homogeneous_clusters") or [],
        "instruction_voice_distribution": ux["instruction_voice_distribution"],
        "unprompted_slot_results": ux["unprompted_slot_results"],
        "repetitive_instruction_clusters": model_judgment.get("repetitive_instruction_clusters") or [],
        "duplicate_groups": model_judgment.get("duplicate_groups") or [],
        "overloaded_slots": ux["overloaded_slots"],
        "notation_failure_slots": ux["notation_failure_slots"],
        "dignity_failure_slots": ux["dignity_failure_slots"],
        "ux_rejected_slots": ux["ux_rejected_slots"],
        "rejected_slots": rejected_slots,
        "confidence": model_judgment.get("confidence"),
        "reasons": list(model_judgment.get("reasons") or []),
        "repair_plan": repair_plan,
    }


def _v12_union_overlapping_slot_groups(groups: Any) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for raw in groups if isinstance(groups, list) else []:
        if not isinstance(raw, dict):
            continue
        slots = set(_v12_canonical_slot_list(raw.get("slots")))
        if len(slots) < 2:
            continue
        component = {
            "slots": slots,
            "cluster_ids": {str(raw.get("cluster_id") or "")},
            "reasons": {str(raw.get("reason") or "")},
            "subject_sha256s": {str(value) for value in (raw.get("subject_sha256s") or []) if str(value)},
        }
        while True:
            overlaps = [existing for existing in components if existing["slots"].intersection(component["slots"])]
            if not overlaps:
                break
            for existing in overlaps:
                component["slots"].update(existing["slots"])
                component["cluster_ids"].update(existing["cluster_ids"])
                component["reasons"].update(existing["reasons"])
                component["subject_sha256s"].update(existing["subject_sha256s"])
                components.remove(existing)
        components.append(component)
    return [
        {
            "slots": sorted(component["slots"]),
            "cluster_ids": sorted(value for value in component["cluster_ids"] if value),
            "reason": " | ".join(sorted(value for value in component["reasons"] if value)),
            "subject_sha256s": sorted(component["subject_sha256s"]),
        }
        for component in sorted(components, key=lambda value: tuple(sorted(value["slots"])))
    ]


def v12_bounded_teaching_quality_gate(
    node_entry: dict[str, Any],
    model_judgment: dict[str, Any],
) -> dict[str, Any]:
    item_by_slot = _v12_item_by_slot(node_entry)
    subject_by_slot = {
        slot: v12_item_review_subject_binding(item)
        for slot, item in item_by_slot.items()
    }
    classifications = [
        entry for entry in (model_judgment.get("item_classifications") or [])
        if isinstance(entry, dict)
    ]
    by_slot = {int(entry.get("slot") or 0): entry for entry in classifications}
    gate_errors: list[str] = []
    rejected_slots: set[int] = set()
    if sorted(by_slot) != list(range(1, QUESTIONS_PER_GRAPH_NODE + 1)):
        gate_errors.append("item_classification_coverage")
    for slot, item in item_by_slot.items():
        classification = by_slot.get(slot)
        subject = subject_by_slot[slot]
        if not classification:
            rejected_slots.add(slot)
            continue
        for key in (
            "node_id",
            "slot",
            "item_id",
            "candidate_sha256",
            "child_surface_sha256",
            "item_review_request_sha256",
            "item_review_semantic_evidence_sha256",
        ):
            if classification.get(key) != subject.get(key):
                gate_errors.append(f"item_classification_binding:{slot}:{key}")
                rejected_slots.add(slot)
        if classification.get("prompt_interaction_verdict") != "aligned":
            gate_errors.append(f"prompt_interaction_mismatch:{slot}")
            rejected_slots.add(slot)
        if classification.get("ownership_mode") == "prerequisite_only" and slot != 13:
            gate_errors.append(f"prerequisite_only_forbidden:{slot}")
            rejected_slots.add(slot)
        if classification.get("ownership_mode") == "prerequisite_only":
            if classification.get("current_node_indispensable") != "no":
                gate_errors.append(f"prerequisite_only_indispensable_mismatch:{slot}")
                rejected_slots.add(slot)
        elif classification.get("current_node_indispensable") != "yes":
            gate_errors.append(f"current_node_indispensable_required:{slot}")
            rejected_slots.add(slot)
        if (
            classification.get("ownership_mode") == "controlled_stretch"
            and slot not in CONTROLLED_ADVANCED_CHALLENGE_SLOTS
        ):
            gate_errors.append(f"controlled_stretch_slot_forbidden:{slot}")
            rejected_slots.add(slot)
        if classification.get("difficulty_verdict") in {"L4", "stretch"} and not set(
            classification.get("difficulty_features") or []
        ).intersection(V12_DIFFICULTY_FEATURES):
            gate_errors.append(f"advanced_difficulty_missing_feature:{slot}")
            rejected_slots.add(slot)
    evidence_families = {
        str(entry.get("primary_evidence_move") or "")
        for entry in classifications
        if str(entry.get("primary_evidence_move") or "") in V12_PRIMARY_EVIDENCE_MOVES
    }
    if len(evidence_families) < V12_MIN_PRIMARY_EVIDENCE_MOVE_FAMILIES:
        gate_errors.append("primary_evidence_move_family_minimum")
    controlled_stretch_slots = [
        slot
        for slot, classification in by_slot.items()
        if classification.get("ownership_mode") == "controlled_stretch"
    ]
    if len(controlled_stretch_slots) > V12_MAX_CONTROLLED_STRETCH_PER_NODE:
        gate_errors.append("controlled_stretch_classification_maximum")
        rejected_slots.update(controlled_stretch_slots[V12_MAX_CONTROLLED_STRETCH_PER_NODE:])
    homogeneous_clusters = _v12_union_overlapping_slot_groups(
        model_judgment.get("homogeneous_clusters") or []
    )
    oversized_homogeneous = [
        cluster for cluster in homogeneous_clusters
        if len(cluster.get("slots") or []) > V12_MAX_HOMOGENEOUS_CLUSTER
    ]
    if oversized_homogeneous:
        gate_errors.append("homogeneous_cluster_limit")
        for cluster in oversized_homogeneous:
            rejected_slots.update((cluster.get("slots") or [])[V12_MAX_HOMOGENEOUS_CLUSTER:])
    repair_plan = [entry for entry in (model_judgment.get("repair_plan") or []) if isinstance(entry, dict)]
    repetitive_without_exact_plan: list[str] = []
    for cluster in model_judgment.get("repetitive_instruction_clusters") or []:
        if not isinstance(cluster, dict):
            continue
        cluster_id = str(cluster.get("cluster_id") or "")
        cluster_slots = set(_v12_canonical_slot_list(cluster.get("slots")))
        exact = [
            directive for directive in repair_plan
            if int(directive.get("slot") or 0) in cluster_slots
            and (
                cluster_id in set(str(ref) for ref in (directive.get("evidence_refs") or []))
                or f"repetitive_cluster:{cluster_id}" in set(str(ref) for ref in (directive.get("evidence_refs") or []))
            )
        ]
        required = max(1, len(cluster_slots) - V12_MAX_REPETITIVE_INSTRUCTION_CLUSTER)
        if len({int(entry.get("slot") or 0) for entry in exact}) < required:
            repetitive_without_exact_plan.append(cluster_id)
            rejected_slots.update(sorted(cluster_slots)[-required:])
    if repetitive_without_exact_plan:
        gate_errors.append("repetitive_cluster_missing_exact_repair_plan")
    return {
        "gate_errors": sorted(set(gate_errors)),
        "rejected_slots": sorted(rejected_slots),
        "primary_evidence_move_family_count": len(evidence_families),
        "homogeneous_clusters": homogeneous_clusters,
        "oversized_homogeneous_clusters": oversized_homogeneous,
        "repetitive_clusters_missing_exact_plan": sorted(repetitive_without_exact_plan),
    }


def v12_global_finalizer_output_errors(
    node_entry: dict[str, Any],
    output: dict[str, Any],
    *,
    constituent_reviews: list[dict[str, Any]] | None = None,
) -> list[str]:
    if constituent_reviews is None:
        artifact = node_entry.get("node_review_artifact") if isinstance(node_entry.get("node_review_artifact"), dict) else {}
        constituent_reviews = artifact.get("constituent_reviews") if isinstance(artifact.get("constituent_reviews"), list) else []
    return v12_reduce_node_set_v4(node_entry, constituent_reviews, output)["errors"]


def v12_repair_state_transition(
    *,
    state: dict[str, Any],
    old_item: dict[str, Any],
    new_item: dict[str, Any],
    directive: dict[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    if v12_external_candidate_sha256(old_item) == v12_external_candidate_sha256(new_item):
        return {"accepted": False, "reason": "no_effective_delta", "state": updated}
    target = str(directive.get("required_voice_family") or "")
    actual = str(new_item.get("intended_instruction_voice_family") or "")
    if target and target != actual:
        return {"accepted": False, "reason": "required_voice_not_satisfied", "state": updated}
    slot = int(new_item.get("slot") or old_item.get("slot") or 0)
    rounds = updated.setdefault("repair_rounds_by_slot", {})
    rounds[str(slot)] = int(rounds.get(str(slot)) or 0) + 1
    updated.setdefault("accepted_by_slot", {})[str(slot)] = copy.deepcopy(new_item)
    updated["pending_repair_slots"] = [
        value for value in (updated.get("pending_repair_slots") or []) if int(value) != slot
    ]
    return {"accepted": True, "reason": "effective_delta", "state": updated}


def v12_v4_evidence_identity_errors(identity: dict[str, Any]) -> list[str]:
    expected = {
        "designer_contract_version": V12_DESIGNER_CONTRACT_VERSION,
        "item_review_semantic_evidence_version": V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "global_finalizer_semantic_evidence_version": V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION,
        "semantic_commitment_version": V12_SEMANTIC_EVIDENCE_COMMITMENT_VERSION,
        "runner_receipt_schema_version": V12_RUNNER_RECEIPT_SCHEMA_VERSION,
        "completed_node_receipt_schema_version": V12_COMPLETED_NODE_RECEIPT_SCHEMA_VERSION,
        "active_quality_contract_version": V12_ACTIVE_QUALITY_CONTRACT_VERSION,
    }
    errors = [f"{key}:mismatch" for key, value in expected.items() if identity.get(key) != value]
    constituents = identity.get("local_constituent_versions") if isinstance(identity.get("local_constituent_versions"), list) else []
    if len(constituents) != len(v12_expected_node_set_review_shards()) or any(
        value != V12_NODE_SET_REVIEW_SEMANTIC_EVIDENCE_VERSION for value in constituents
    ):
        errors.append("local_constituent_versions:mismatch")
    return errors


def v12_v4_resume_plan(checkpoint: dict[str, Any]) -> dict[str, Any]:
    reviewed = {
        tuple(int(slot) for slot in slots)
        for slots in (checkpoint.get("local_constituent_reviewed_slots") or [])
        if isinstance(slots, list)
    }
    expected = v12_expected_node_set_review_shards()
    policy = checkpoint.get("execution_policy") if isinstance(checkpoint.get("execution_policy"), dict) else {}
    global_finalizer = checkpoint.get("global_finalizer") if isinstance(checkpoint.get("global_finalizer"), dict) else {}
    global_complete = (
        global_finalizer.get("semantic_evidence_version") == V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION
        and global_finalizer.get("verdict") in {"approved", "needs_repair", "blocked"}
    )
    return {
        "missing_local_shards": [slots for slots in expected if tuple(slots) not in reviewed],
        "global_finalizer_required": not global_complete,
        "slot_chunk_concurrency": int(policy.get("slot_chunk_concurrency") or 1),
        "node_review_concurrency": int(policy.get("node_review_concurrency") or V12_NODE_SET_REVIEW_ACTIVATION_CONCURRENCY),
        "global_finalizer_concurrency": int(policy.get("global_finalizer_concurrency") or 1),
    }


def v12_semantic_evidence_policy() -> dict[str, Any]:
    return {
        "commitment_version": V12_SEMANTIC_EVIDENCE_COMMITMENT_VERSION,
        "item_review_version": V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "node_set_focal_review_version": V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "node_set_global_review_version": V12_NODE_SET_GLOBAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "node_set_review_version": V12_NODE_SET_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "node_set_aggregate_version": V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION,
        "agent_knowledge_version": V12_AGENT_KNOWLEDGE_VERSION,
        "agent_knowledge_sha256": v12_agent_knowledge_sha256(),
        "natural_self_contained_min_score": V12_SEMANTIC_GATE_MIN_SCORE,
        "natural_chinese_min_score": V12_NATURAL_CHINESE_MIN_SCORE,
        "rendered_notation_required_score": V12_RENDERED_NOTATION_REQUIRED_SCORE,
        "age_dignity_min_score": V12_AGE_DIGNITY_MIN_SCORE,
        "unprompted_process_min_score": V12_UNPROMPTED_PROCESS_MIN_SCORE,
        "max_response_moves": V12_MAX_RESPONSE_MOVES,
        "minimum_instruction_voice_families": V12_MIN_INSTRUCTION_VOICE_FAMILIES,
        "max_repetitive_instruction_cluster": V12_MAX_REPETITIVE_INSTRUCTION_CLUSTER,
        "max_consecutive_instruction_voice": V12_MAX_CONSECUTIVE_INSTRUCTION_VOICE,
        "node_set_review_shard_size": V12_NODE_SET_REVIEW_SHARD_SIZE,
        "node_set_review_expected_shards": len(v12_expected_node_set_review_shards()),
        "node_set_review_activation_concurrency": V12_NODE_SET_REVIEW_ACTIVATION_CONCURRENCY,
    }


def v12_expected_node_set_review_shards() -> list[list[int]]:
    slots = list(range(1, QUESTIONS_PER_GRAPH_NODE + 1))
    return [
        slots[index:index + V12_NODE_SET_REVIEW_SHARD_SIZE]
        for index in range(0, len(slots), V12_NODE_SET_REVIEW_SHARD_SIZE)
    ]


def v12_expected_global_verifier_shards() -> list[list[int]]:
    slots = list(range(1, QUESTIONS_PER_GRAPH_NODE + 1))
    return [
        slots[index:index + V12_NODE_SET_GLOBAL_VERIFIER_SHARD_SIZE]
        for index in range(0, len(slots), V12_NODE_SET_GLOBAL_VERIFIER_SHARD_SIZE)
    ]


def v12_node_set_review_shard_id(slots: list[int]) -> str:
    return f"slots-{slots[0]:02d}-{slots[-1]:02d}" if slots else ""


def v12_allowed_rollback_nodes_for_graph_node(node: dict[str, Any]) -> list[str]:
    error_diagnosis = node.get("error_diagnosis") if isinstance(node.get("error_diagnosis"), dict) else {}
    ordered: list[str] = []
    for node_id in [*(error_diagnosis.get("rollback_to") or []), *(node.get("prerequisites") or [])]:
        node_id = str(node_id)
        if node_id and node_id not in ordered:
            ordered.append(node_id)
    return ordered


def v12_slot_role_for_node(node: dict[str, Any], slot: int) -> str:
    if slot == 13 and not v12_allowed_rollback_nodes_for_graph_node(node):
        return V12_ROOT_READINESS_SLOT_ROLE
    if 1 <= slot <= len(V12_SLOT_ROLES):
        return V12_SLOT_ROLES[slot - 1]
    return ""


def v12_is_process_node(node: dict[str, Any]) -> bool:
    taxonomy = node.get("taxonomy") if isinstance(node.get("taxonomy"), dict) else {}
    if str(taxonomy.get("concept_type") or "").lower() == "process":
        return True
    tags = node.get("tags") if isinstance(node.get("tags"), list) else []
    return any(str(tag).lower() == "process" for tag in tags)


def v12_item_policy_errors(node: dict[str, Any], item: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    slot = int(item.get("slot") or 0)
    design = item.get("child_surface_design") if isinstance(item.get("child_surface_design"), dict) else {}
    if design != V12_CHILD_SURFACE_DESIGN:
        errors.append("child_surface_design:missing_or_invalid_v4_contract")
    errors.extend(v12_instruction_voice_target_errors(node, item))
    if v12_is_process_node(node) and slot in V12_PROCESS_UNPROMPTED_SLOTS:
        if item.get("elicitation_mode") != V12_UNPROMPTED_PROCESS_ELICITATION_MODE:
            errors.append(f"elicitation_mode:expected_{V12_UNPROMPTED_PROCESS_ELICITATION_MODE}")
    interaction_schema = item.get("interaction_schema")
    if v12_item_requires_interaction_schema(item) and not isinstance(interaction_schema, dict):
        errors.append("interaction_schema:missing_for_current_designer_contract")
    if isinstance(interaction_schema, dict):
        if (
            interaction_schema.get("schema_version")
            != QUESTION_INTERACTION_CURRENT_SCHEMA_VERSION
        ):
            errors.append("interaction_schema:current_v2_required")
        errors.extend(question_interaction_schema_errors(interaction_schema))
    for detail in canonical_child_surface_errors(item):
        errors.append(f"child_surface:{detail}")
    return errors


def v12_item_requires_interaction_schema(item: dict[str, Any]) -> bool:
    artifact = item.get("designer_artifact") if isinstance(item.get("designer_artifact"), dict) else {}
    return artifact.get("prompt_version_id") == V12_DESIGNER_PROMPT_VERSION_ID


def normalize_question_interaction_schema(schema: Any) -> dict[str, Any] | None:
    try:
        return child_prompt.normalize_interaction_schema(schema, allow_legacy=True)
    except child_prompt.ChildPromptContractError:
        return None


def question_interaction_schema_errors(schema: dict[str, Any]) -> list[str]:
    try:
        child_prompt.normalize_interaction_schema(schema, allow_legacy=True)
    except child_prompt.ChildPromptContractError as exc:
        return list(exc.errors)
    return []


def canonical_child_surface_projection(
    item: dict[str, Any],
    *,
    prompt_interaction_verdict: str = "aligned",
) -> dict[str, Any]:
    return child_prompt.project_child_surface(
        prompt=item.get("prompt"),
        prompt_format=item.get("prompt_format"),
        interaction_schema=item.get("interaction_schema"),
        allow_legacy=True,
        prompt_interaction_verdict=prompt_interaction_verdict,
    )


def canonical_child_surface_errors(item: dict[str, Any]) -> list[str]:
    return child_prompt.projection_errors(
        prompt=item.get("prompt"),
        prompt_format=item.get("prompt_format"),
        interaction_schema=item.get("interaction_schema"),
        allow_legacy=True,
    )


def v12_item_review_request_payload(item: dict[str, Any]) -> dict[str, Any]:
    projection = canonical_child_surface_projection(item)
    return {
        "node_id": item.get("node_id"),
        "slot": item.get("slot"),
        "item_id": item.get("id"),
        "candidate_sha256": v12_external_candidate_sha256(item),
        "source_prompt_sha256": projection["source_prompt_sha256"],
        "source_interaction_schema_sha256": projection["source_interaction_schema_sha256"],
        "child_surface_sha256": projection["projection_sha256"],
        "answer_material": {
            "answer_format": item.get("answer_format"),
            "expected_answer": item.get("expected_answer"),
            "accepted_alternatives": item.get("accepted_alternatives") or [],
            "solution_steps": item.get("solution_steps") or [],
        },
    }


def v12_item_review_request_sha256(item: dict[str, Any]) -> str:
    return _v12_digest_json(v12_item_review_request_payload(item))


def v12_item_review_subject_binding(item: dict[str, Any]) -> dict[str, Any]:
    projection = canonical_child_surface_projection(item)
    review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
    binding = {
        "node_id": item.get("node_id"),
        "slot": item.get("slot"),
        "item_id": item.get("id"),
        "candidate_sha256": v12_external_candidate_sha256(item),
        "child_surface_sha256": projection["projection_sha256"],
        "item_review_request_sha256": v12_item_review_request_sha256(item),
        "item_review_semantic_evidence_sha256": review.get("semantic_evidence_sha256") or "",
    }
    return {**binding, "subject_sha256": _v12_digest_json(binding)}


def v12_item_review_binding_errors(item: dict[str, Any]) -> list[str]:
    review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
    try:
        projection = canonical_child_surface_projection(item)
        expected_request = v12_item_review_request_sha256(item)
    except child_prompt.ChildPromptContractError as exc:
        return [f"child_surface:{detail}" for detail in exc.errors]
    errors: list[str] = []
    stored_surface = str(review.get("child_surface_sha256") or "")
    stored_request = str(review.get("item_review_request_sha256") or "")
    if not stored_surface:
        errors.append("review.child_surface_sha256:missing")
    elif stored_surface != projection["projection_sha256"]:
        errors.append("review.child_surface_sha256:mismatch")
    if not stored_request:
        errors.append("review.item_review_request_sha256:missing")
    elif stored_request != expected_request:
        errors.append("review.item_review_request_sha256:mismatch")
    return errors


def v12_external_candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in item.items()
        if key not in {"review_artifact", "reviewer_artifact"}
    }
    return payload


def v12_external_candidate_sha256(item: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            v12_external_candidate_payload(item),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def v12_node_candidate_payload(node_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node_entry.get("node_id"),
        "node_name": node_entry.get("node_name", ""),
        "items": node_entry.get("items") or [],
    }


def v12_node_candidate_sha256(node_entry: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            v12_node_candidate_payload(node_entry),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _v12_digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def v12_cross_node_summary_selector_policy() -> dict[str, Any]:
    return {
        "version": V12_CROSS_NODE_SUMMARY_SELECTOR_POLICY_VERSION,
        "max_selected_summaries": V12_CROSS_NODE_SUMMARY_MAX_SELECTED,
        "source_priority": [
            "direct_prerequisite_or_unlock",
            "same_module_nearest",
            "taxonomy_structural_similarity",
            "global_module_and_recent_sentinels",
        ],
        "tier_quotas": {
            "direct_prerequisite_or_unlock": 40,
            "same_module_nearest": 24,
            "taxonomy_structural_similarity": 12,
            "global_module_and_recent_sentinels": 4,
        },
        "item_sampling": "tiered_source_round_robin_with_boundary_slots_first",
        "full_registry_prompt_policy": "digest_only_never_full_registry",
        "structured_duplicate_audit": "full_registry_exact_signature_and_stem_candidates",
    }


def _v12_cross_node_item_summary(node_id: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "slot": item.get("slot"),
        "slot_role": item.get("slot_role"),
        "evidence_goal": item.get("evidence_goal"),
        "elicitation_mode": item.get("elicitation_mode"),
        "child_surface_design": item.get("child_surface_design"),
        "math_core_signature": item.get("math_core_signature"),
        "problem_family_id": item.get("problem_family_id"),
        "core_stem_id": item.get("core_stem_id"),
        "prompt_preview": str(item.get("prompt") or "")[:180],
        "expected_answer_preview": str(item.get("expected_answer") or "")[:160],
    }


def v12_cross_node_summary_registry(
    node_entries: Any,
    graph: dict[str, Any],
) -> list[dict[str, Any]]:
    graph_order = {
        str(node.get("id")): index
        for index, node in enumerate(graph.get("nodes") or [])
        if isinstance(node, dict) and node.get("id")
    }
    ordered_nodes = sorted(
        (node for node in list(node_entries or []) if isinstance(node, dict)),
        key=lambda node: (
            graph_order.get(str(node.get("node_id") or ""), len(graph_order)),
            str(node.get("node_id") or ""),
        ),
    )
    registry: list[dict[str, Any]] = []
    for node_entry in ordered_nodes:
        node_id = str(node_entry.get("node_id") or "")
        if not node_id:
            continue
        for item in sorted(
            (item for item in node_entry.get("items") or [] if isinstance(item, dict)),
            key=lambda item: (int(item.get("slot") or 0), str(item.get("id") or "")),
        ):
            registry.append(_v12_cross_node_item_summary(node_id, item))
    return registry


def _v12_cross_node_source_priority(
    *,
    source_id: str,
    focal_id: str,
    graph_nodes: dict[str, dict[str, Any]],
    graph_order: dict[str, int],
    sentinel_ids: set[str],
) -> tuple[Any, ...]:
    focal = graph_nodes.get(focal_id, {})
    source = graph_nodes.get(source_id, {})
    focal_taxonomy = focal.get("taxonomy") if isinstance(focal.get("taxonomy"), dict) else {}
    source_taxonomy = source.get("taxonomy") if isinstance(source.get("taxonomy"), dict) else {}
    focal_relations = {
        *[str(value) for value in focal.get("prerequisites") or []],
        *[str(value) for value in focal.get("unlocks") or []],
    }
    source_relations = {
        *[str(value) for value in source.get("prerequisites") or []],
        *[str(value) for value in source.get("unlocks") or []],
    }
    direct = source_id in focal_relations or focal_id in source_relations
    same_module = bool(
        focal_taxonomy.get("module_id")
        and focal_taxonomy.get("module_id") == source_taxonomy.get("module_id")
    )
    structural_fields = ("concept_type", "grain", "chapter_anchor")
    structural_score = sum(
        1
        for field in structural_fields
        if focal_taxonomy.get(field)
        and focal_taxonomy.get(field) == source_taxonomy.get(field)
    )
    structural_score += int(bool(set(focal.get("tags") or []) & set(source.get("tags") or [])))
    if direct:
        bucket = 0
    elif same_module:
        bucket = 1
    elif structural_score:
        bucket = 2
    elif source_id in sentinel_ids:
        bucket = 3
    else:
        bucket = 4
    focal_index = graph_order.get(focal_id, len(graph_order))
    source_index = graph_order.get(source_id, len(graph_order))
    return (
        bucket,
        -structural_score,
        abs(focal_index - source_index),
        -source_index if source_id in sentinel_ids else source_index,
        source_id,
    )


def v12_select_cross_node_summaries(
    *,
    focal_node_id: str,
    registry: list[dict[str, Any]],
    graph: dict[str, Any],
    limit: int = V12_CROSS_NODE_SUMMARY_MAX_SELECTED,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("cross-node summary selection limit must be positive")
    graph_nodes = {
        str(node.get("id")): node
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }
    graph_order = {node_id: index for index, node_id in enumerate(graph_nodes)}
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for summary in registry:
        source_id = str(summary.get("node_id") or "")
        if source_id and source_id != focal_node_id:
            by_source[source_id].append(summary)
    module_first_last: dict[str, list[str]] = defaultdict(list)
    for source_id in by_source:
        taxonomy = graph_nodes.get(source_id, {}).get("taxonomy")
        module_id = str((taxonomy or {}).get("module_id") or "") if isinstance(taxonomy, dict) else ""
        if module_id:
            module_first_last[module_id].append(source_id)
    sentinel_ids: set[str] = set()
    for source_ids in module_first_last.values():
        ordered = sorted(source_ids, key=lambda node_id: graph_order.get(node_id, len(graph_order)))
        sentinel_ids.update(ordered[:1])
        sentinel_ids.update(ordered[-1:])
    recent = sorted(by_source, key=lambda node_id: graph_order.get(node_id, -1), reverse=True)
    sentinel_ids.update(recent[:3])
    ordered_sources = sorted(
        by_source,
        key=lambda source_id: _v12_cross_node_source_priority(
            source_id=source_id,
            focal_id=focal_node_id,
            graph_nodes=graph_nodes,
            graph_order=graph_order,
            sentinel_ids=sentinel_ids,
        ),
    )
    boundary_slot_order = [20, 1, 10, 5, 15, 3, 7, 12, 17, 2, 4, 6, 8, 9, 11, 13, 14, 16, 18, 19]
    slot_rank = {slot: index for index, slot in enumerate(boundary_slot_order)}
    for source_id, source_items in by_source.items():
        by_source[source_id] = sorted(
            source_items,
            key=lambda summary: (
                slot_rank.get(int(summary.get("slot") or 0), len(slot_rank)),
                int(summary.get("slot") or 0),
                _v12_digest_json(summary),
            ),
        )
    tier_sources: dict[int, list[str]] = defaultdict(list)
    for source_id in ordered_sources:
        priority = _v12_cross_node_source_priority(
            source_id=source_id,
            focal_id=focal_node_id,
            graph_nodes=graph_nodes,
            graph_order=graph_order,
            sentinel_ids=sentinel_ids,
        )
        tier_sources[int(priority[0])].append(source_id)

    def take_round_robin(source_ids: list[str], quota: int) -> list[dict[str, Any]]:
        taken: list[dict[str, Any]] = []
        item_index = 0
        while len(taken) < quota:
            added = False
            for source_id in source_ids:
                source_items = by_source[source_id]
                if item_index < len(source_items):
                    taken.append(dict(source_items[item_index]))
                    added = True
                    if len(taken) >= quota:
                        break
            if not added:
                break
            item_index += 1
        return taken

    selected: list[dict[str, Any]] = []
    tier_quotas = ((0, 40), (1, 24), (2, 12), (3, 4))
    carried = 0
    for tier, quota in tier_quotas:
        tier_selection = take_round_robin(
            tier_sources.get(tier, []),
            min(limit - len(selected), quota + carried),
        )
        selected.extend(tier_selection)
        carried = quota + carried - len(tier_selection)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        selected_digests = {_v12_digest_json(summary) for summary in selected}
        for summary in take_round_robin(ordered_sources, limit):
            digest = _v12_digest_json(summary)
            if digest in selected_digests:
                continue
            selected.append(summary)
            selected_digests.add(digest)
            if len(selected) >= limit:
                break
    return selected


def v12_cross_node_structured_duplicate_candidates(
    *,
    focal_node_entry: dict[str, Any],
    registry: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    focal_node_id = str(focal_node_entry.get("node_id") or "")
    for item in sorted(
        (item for item in focal_node_entry.get("items") or [] if isinstance(item, dict)),
        key=lambda item: int(item.get("slot") or 0),
    ):
        focal_values = {
            "math_core_signature": str(item.get("math_core_signature") or ""),
            "core_stem_id": str(item.get("core_stem_id") or ""),
        }
        for summary in registry:
            source_node_id = str(summary.get("node_id") or "")
            if not source_node_id or source_node_id == focal_node_id:
                continue
            matched_fields = [
                field
                for field, value in focal_values.items()
                if value and value == str(summary.get(field) or "")
            ]
            if not matched_fields:
                continue
            candidates.append({
                "focal_slot": int(item.get("slot") or 0),
                "source_node_id": source_node_id,
                "source_slot": int(summary.get("slot") or 0),
                "matched_fields": matched_fields,
                "math_core_signature": focal_values["math_core_signature"],
                "core_stem_id": focal_values["core_stem_id"],
            })
    return sorted(
        candidates,
        key=lambda candidate: (
            int(candidate["focal_slot"]),
            str(candidate["source_node_id"]),
            int(candidate["source_slot"]),
            tuple(candidate["matched_fields"]),
        ),
    )


def v12_cross_node_summary_bundle(
    *,
    focal_node_id: str,
    source_node_entries: Any,
    graph: dict[str, Any],
    registry_scope: str,
) -> dict[str, Any]:
    registry = v12_cross_node_summary_registry(source_node_entries, graph)
    selected = v12_select_cross_node_summaries(
        focal_node_id=focal_node_id,
        registry=registry,
        graph=graph,
    )
    ordered_source_node_ids = list(dict.fromkeys(
        str(summary.get("node_id") or "")
        for summary in registry
        if str(summary.get("node_id") or "")
    ))
    selected_source_node_ids = list(dict.fromkeys(
        str(summary.get("node_id") or "")
        for summary in selected
        if str(summary.get("node_id") or "")
    ))
    policy = v12_cross_node_summary_selector_policy()
    context = {
        "schema_version": V12_CROSS_NODE_SUMMARY_CONTEXT_SCHEMA_VERSION,
        "selector_policy_version": V12_CROSS_NODE_SUMMARY_SELECTOR_POLICY_VERSION,
        "selector_policy_sha256": _v12_digest_json(policy),
        "registry_scope": registry_scope,
        "focal_node_id": focal_node_id,
        "ordered_source_node_ids": ordered_source_node_ids,
        "selected_source_node_ids": selected_source_node_ids,
        "full_registry_count": len(registry),
        "full_registry_digest_sha256": _v12_digest_json(registry),
        "selected_summary_count": len(selected),
        "selected_summary_digest_sha256": _v12_digest_json(selected),
    }
    return {
        "context": context,
        "selected_summaries": selected,
        "full_registry": registry,
    }


def v12_canonical_manifest_sha256(manifest: dict[str, Any]) -> str:
    return _v12_digest_json(manifest)


def v12_item_requires_unprompted_process_evidence(item: dict[str, Any]) -> bool:
    return item.get("elicitation_mode") == V12_UNPROMPTED_PROCESS_ELICITATION_MODE


def v12_semantic_evidence_errors(
    item: dict[str, Any],
    evidence: Any,
    *,
    expected_version: str,
) -> list[str]:
    if not isinstance(evidence, dict):
        return ["semantic_evidence:missing_or_not_object"]
    expected_keys = {
        "version",
        "ux_verdict",
        "natural_self_contained_task",
        "natural_chinese",
        "rendered_notation_readiness",
        "age_dignity",
        "instruction_voice_family",
        "response_moves",
        "unprompted_process_evidence",
        "process_target_disclosed",
        "process_disclosure_evidence",
        "evidence",
        "repair_direction",
    }
    errors: list[str] = []
    if set(evidence) != expected_keys:
        errors.append("semantic_evidence:unexpected_or_missing_fields")
    if evidence.get("version") != expected_version:
        errors.append(f"semantic_evidence.version:expected_{expected_version}")
    if evidence.get("ux_verdict") != "approved":
        errors.append("semantic_evidence.ux_verdict:not_approved")
    assessment_thresholds = {
        "natural_self_contained_task": V12_SEMANTIC_GATE_MIN_SCORE,
        "natural_chinese": V12_NATURAL_CHINESE_MIN_SCORE,
        "age_dignity": V12_AGE_DIGNITY_MIN_SCORE,
    }
    for key, threshold in assessment_thresholds.items():
        assessment = evidence.get(key) if isinstance(evidence.get(key), dict) else {}
        if set(assessment) != {"verdict", "score", "reason"}:
            errors.append(f"semantic_evidence.{key}:unexpected_or_missing_fields")
        if assessment.get("verdict") != "pass":
            errors.append(f"semantic_evidence.{key}:verdict_not_pass")
        score = _v12_score(assessment, "score")
        if score < 0.0 or score > 1.0:
            errors.append(f"semantic_evidence.{key}:score_out_of_range")
        if score < threshold:
            errors.append(f"semantic_evidence.{key}:score_below_gate")
        if not str(assessment.get("reason") or "").strip():
            errors.append(f"semantic_evidence.{key}:reason_missing")
    notation = evidence.get("rendered_notation_readiness") if isinstance(evidence.get("rendered_notation_readiness"), dict) else {}
    if set(notation) != {"verdict", "score", "reason", "child_visible_risks"}:
        errors.append("semantic_evidence.rendered_notation_readiness:unexpected_or_missing_fields")
    if notation.get("verdict") != "pass":
        errors.append("semantic_evidence.rendered_notation_readiness:verdict_not_pass")
    notation_score = _v12_score(notation, "score")
    if notation_score < 0.0 or notation_score > 1.0:
        errors.append("semantic_evidence.rendered_notation_readiness:score_out_of_range")
    if abs(notation_score - V12_RENDERED_NOTATION_REQUIRED_SCORE) > 1e-9:
        errors.append("semantic_evidence.rendered_notation_readiness:score_not_perfect")
    risks = notation.get("child_visible_risks")
    if not isinstance(risks, list):
        errors.append("semantic_evidence.rendered_notation_readiness:risks_not_array")
    elif risks:
        errors.append("semantic_evidence.rendered_notation_readiness:child_visible_risks_present")
    if not str(notation.get("reason") or "").strip():
        errors.append("semantic_evidence.rendered_notation_readiness:reason_missing")
    errors.extend(
        f"semantic_evidence.{detail}"
        for detail in v12_instruction_voice_evidence_errors(item, evidence)
    )
    response_moves = evidence.get("response_moves")
    if not isinstance(response_moves, list):
        errors.append("semantic_evidence.response_moves:not_array")
    else:
        if not response_moves:
            errors.append("semantic_evidence.response_moves:empty")
        if len(response_moves) > V12_MAX_RESPONSE_MOVES:
            errors.append("semantic_evidence.response_moves:overloaded")
        if any(not str(move or "").strip() for move in response_moves):
            errors.append("semantic_evidence.response_moves:blank_move")
    process = evidence.get("unprompted_process_evidence") if isinstance(evidence.get("unprompted_process_evidence"), dict) else {}
    if set(process) != {"applicability", "verdict", "score", "reason"}:
        errors.append("semantic_evidence.unprompted_process_evidence:unexpected_or_missing_fields")
    if v12_item_requires_unprompted_process_evidence(item):
        if process.get("applicability") != "required":
            errors.append("semantic_evidence.unprompted_process_evidence:applicability_not_required")
        if process.get("verdict") != "satisfied":
            errors.append("semantic_evidence.unprompted_process_evidence:verdict_not_satisfied")
        process_score = _v12_score(process, "score")
        if process_score < 0.0 or process_score > 1.0:
            errors.append("semantic_evidence.unprompted_process_evidence:score_out_of_range")
        if process_score < V12_UNPROMPTED_PROCESS_MIN_SCORE:
            errors.append("semantic_evidence.unprompted_process_evidence:score_below_gate")
        if evidence.get("process_target_disclosed") is not False:
            errors.append("semantic_evidence.process_target_disclosed:must_be_false_for_unprompted")
    else:
        if process.get("applicability") != "not_applicable":
            errors.append("semantic_evidence.unprompted_process_evidence:applicability_not_not_applicable")
        if process.get("verdict") != "not_applicable":
            errors.append("semantic_evidence.unprompted_process_evidence:verdict_not_not_applicable")
        process_score = _v12_score(process, "score")
        if process_score < 0.0 or process_score > 1.0:
            errors.append("semantic_evidence.unprompted_process_evidence:score_out_of_range")
    if not str(process.get("reason") or "").strip():
        errors.append("semantic_evidence.unprompted_process_evidence:reason_missing")
    if not isinstance(evidence.get("process_target_disclosed"), bool):
        errors.append("semantic_evidence.process_target_disclosed:not_boolean")
    errors.extend(
        f"semantic_evidence.{detail}"
        for detail in v12_process_disclosure_gate_errors(item, evidence)
    )
    if not str(evidence.get("evidence") or "").strip():
        errors.append("semantic_evidence.evidence:missing")
    if not str(evidence.get("repair_direction") or "").strip():
        errors.append("semantic_evidence.repair_direction:missing")
    return errors


def _v12_node_set_output(review: dict[str, Any]) -> dict[str, Any]:
    output = review.get("review_output") if isinstance(review.get("review_output"), dict) else review.get("output")
    return output if isinstance(output, dict) else {}


def _v12_semantic_evidence_failure_categories(
    item: dict[str, Any],
    evidence: Any,
    *,
    expected_version: str,
) -> dict[str, bool]:
    evidence = evidence if isinstance(evidence, dict) else {}
    response_moves = evidence.get("response_moves") if isinstance(evidence.get("response_moves"), list) else []
    notation = evidence.get("rendered_notation_readiness") if isinstance(evidence.get("rendered_notation_readiness"), dict) else {}
    dignity = evidence.get("age_dignity") if isinstance(evidence.get("age_dignity"), dict) else {}
    semantic_errors = v12_semantic_evidence_errors(item, evidence, expected_version=expected_version)
    return {
        "overloaded": len(response_moves) > V12_MAX_RESPONSE_MOVES,
        "notation_failure": (
            notation.get("verdict") != "pass"
            or abs(_v12_score(notation, "score") - V12_RENDERED_NOTATION_REQUIRED_SCORE) > 1e-9
            or not isinstance(notation.get("child_visible_risks"), list)
            or bool(notation.get("child_visible_risks"))
        ),
        "dignity_failure": (
            dignity.get("verdict") != "pass"
            or _v12_score(dignity, "score") < V12_AGE_DIGNITY_MIN_SCORE
        ),
        "ux_rejected": bool(semantic_errors),
    }


def v12_item_review_evidence_entries(node_entry: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in sorted(
        [candidate for candidate in (node_entry.get("items") or []) if isinstance(candidate, dict)],
        key=lambda candidate: int(candidate.get("slot") or 0),
    ):
        review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
        entries.append({
            "slot": int(item.get("slot") or 0),
            "item_id": item.get("id"),
            "candidate_sha256": v12_external_candidate_sha256(item),
            "semantic_evidence_sha256": review.get("semantic_evidence_sha256", ""),
            "semantic_evidence": review.get("semantic_evidence") if isinstance(review.get("semantic_evidence"), dict) else {},
        })
    return entries


def _v12_instruction_voice_distribution(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slots_by_family: dict[str, list[int]] = defaultdict(list)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        evidence = entry.get("semantic_evidence") if isinstance(entry.get("semantic_evidence"), dict) else {}
        family = str(evidence.get("instruction_voice_family") or "")
        slot = int(entry.get("slot") or 0)
        if family in V12_INSTRUCTION_VOICE_FAMILIES and 1 <= slot <= QUESTIONS_PER_GRAPH_NODE:
            slots_by_family[family].append(slot)
    return [
        {"instruction_voice_family": family, "slots": sorted(set(slots_by_family[family]))}
        for family in V12_INSTRUCTION_VOICE_FAMILIES
        if slots_by_family.get(family)
    ]


def _v12_normalize_reported_instruction_voice_distribution(value: Any) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(value, list):
        return [], False
    slots_by_family: dict[str, set[int]] = defaultdict(set)
    raw_slots: list[int] = []
    valid = True
    for entry in value:
        if not isinstance(entry, dict):
            valid = False
            continue
        family = str(entry.get("instruction_voice_family") or "")
        slots = entry.get("slots") if isinstance(entry.get("slots"), list) else []
        if family not in V12_INSTRUCTION_VOICE_FAMILIES or not slots:
            valid = False
            continue
        for slot in slots:
            if not isinstance(slot, int) or not 1 <= slot <= QUESTIONS_PER_GRAPH_NODE:
                valid = False
                continue
            raw_slots.append(slot)
            slots_by_family[family].add(slot)
    if len(raw_slots) != len(set(raw_slots)):
        valid = False
    normalized = [
        {"instruction_voice_family": family, "slots": sorted(slots_by_family[family])}
        for family in V12_INSTRUCTION_VOICE_FAMILIES
        if slots_by_family.get(family)
    ]
    return normalized, valid


def _v12_unprompted_slot_results(
    node_entry: dict[str, Any],
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    item_by_slot = _v12_item_by_slot(node_entry)
    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slot = int(entry.get("slot") or 0)
        item = item_by_slot.get(slot)
        if not item or not v12_item_requires_unprompted_process_evidence(item):
            continue
        evidence = entry.get("semantic_evidence") if isinstance(entry.get("semantic_evidence"), dict) else {}
        process = evidence.get("unprompted_process_evidence") if isinstance(evidence.get("unprompted_process_evidence"), dict) else {}
        disclosure = evidence.get("process_disclosure_evidence") if isinstance(evidence.get("process_disclosure_evidence"), dict) else {}
        results.append({
            "slot": slot,
            "item_id": entry.get("item_id"),
            "candidate_sha256": entry.get("candidate_sha256"),
            "process_target_disclosed": evidence.get("process_target_disclosed"),
            "verdict": process.get("verdict"),
            "score": process.get("score"),
            "source_field": disclosure.get("source_field"),
            "quote": disclosure.get("quote"),
            "reason": process.get("reason"),
        })
    return sorted(results, key=lambda entry: int(entry.get("slot") or 0))


def _v12_canonical_slot_list(value: Any) -> list[int]:
    return sorted({
        int(slot)
        for slot in (value if isinstance(value, list) else [])
        if isinstance(slot, int) and 1 <= slot <= QUESTIONS_PER_GRAPH_NODE
    })


def _v12_repetitive_instruction_clusters(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: dict[tuple[int, ...], dict[str, Any]] = {}
    for output in outputs:
        for cluster in output.get("repetitive_instruction_clusters") or []:
            if not isinstance(cluster, dict):
                continue
            slots = tuple(_v12_canonical_slot_list(cluster.get("slots")))
            if len(slots) < 2:
                continue
            clusters.setdefault(slots, {
                "slots": list(slots),
                "cluster_summary": str(cluster.get("cluster_summary") or ""),
                "reason": str(cluster.get("reason") or ""),
            })
    return [clusters[key] for key in sorted(clusters)]


def _v12_canonicalize_overlapping_groups(
    groups: Any,
    *,
    id_key: str,
    summary_key: str,
) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for raw in groups if isinstance(groups, list) else []:
        if not isinstance(raw, dict):
            continue
        slots = set(_v12_canonical_slot_list(raw.get("slots")))
        if len(slots) < 2:
            continue
        component = {
            "slots": slots,
            "source_ids": {str(raw.get(id_key) or "")},
            "summaries": {str(raw.get(summary_key) or "")},
            "reasons": {str(raw.get("reason") or "")},
            "evidence_refs": {
                str(value)
                for value in (raw.get("evidence_refs") or [])
                if str(value)
            },
        }
        while True:
            overlapping = [
                existing
                for existing in components
                if component["slots"].intersection(existing["slots"])
            ]
            if not overlapping:
                break
            for existing in overlapping:
                component["slots"].update(existing["slots"])
                component["source_ids"].update(existing["source_ids"])
                component["summaries"].update(existing["summaries"])
                component["reasons"].update(existing["reasons"])
                component["evidence_refs"].update(existing["evidence_refs"])
                components.remove(existing)
        components.append(component)
    normalized = []
    for component in sorted(components, key=lambda value: tuple(sorted(value["slots"]))):
        normalized.append({
            "slots": sorted(component["slots"]),
            "source_ids": sorted(value for value in component["source_ids"] if value),
            "cluster_summary": " | ".join(sorted(value for value in component["summaries"] if value)),
            "reason": " | ".join(sorted(value for value in component["reasons"] if value)),
            "evidence_refs": sorted(component["evidence_refs"]),
        })
    return normalized


def _v12_consecutive_voice_violation_slots(distribution: list[dict[str, Any]]) -> list[int]:
    family_by_slot = {
        int(slot): str(entry.get("instruction_voice_family") or "")
        for entry in distribution
        if isinstance(entry, dict)
        for slot in (entry.get("slots") or [])
        if isinstance(slot, int)
    }
    violations: list[int] = []
    current_family = ""
    run_slots: list[int] = []
    for slot in range(1, QUESTIONS_PER_GRAPH_NODE + 1):
        family = family_by_slot.get(slot, "")
        if family and family == current_family:
            run_slots.append(slot)
        else:
            if len(run_slots) > V12_MAX_CONSECUTIVE_INSTRUCTION_VOICE:
                violations.extend(run_slots[V12_MAX_CONSECUTIVE_INSTRUCTION_VOICE:])
            current_family = family
            run_slots = [slot] if family else []
    if len(run_slots) > V12_MAX_CONSECUTIVE_INSTRUCTION_VOICE:
        violations.extend(run_slots[V12_MAX_CONSECUTIVE_INSTRUCTION_VOICE:])
    return sorted(set(violations))


def v12_node_set_structured_inventory(node_entry: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in (node_entry.get("items") or []) if isinstance(item, dict)]
    slots = sorted(int(item.get("slot") or 0) for item in items)
    return {
        "item_count": len(items),
        "slots": slots,
        "node_local_mainline_count": sum(
            1 for item in items if item.get("node_local_mainline") is True
        ),
        "controlled_stretch_count": sum(
            1 for item in items if item.get("controlled_stretch") is True
        ),
        "invalid_difficulty_vector_slots": sorted({
            int(item.get("slot") or 0)
            for item in items
            if _v12_difficulty_vector_errors(item)
        }),
    }


def v12_node_set_ux_aggregate(
    node_entry: dict[str, Any],
    constituent_reviews: list[dict[str, Any]],
    global_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global_output = global_output if isinstance(global_output, dict) else {}
    entries = v12_item_review_evidence_entries(node_entry)
    item_by_slot = _v12_item_by_slot(node_entry)
    overloaded_slots: set[int] = set()
    notation_failure_slots: set[int] = set()
    dignity_failure_slots: set[int] = set()
    ux_rejected_slots: set[int] = set()
    for entry in entries:
        slot = int(entry.get("slot") or 0)
        item = item_by_slot.get(slot)
        if not item:
            continue
        categories = _v12_semantic_evidence_failure_categories(
            item,
            entry.get("semantic_evidence"),
            expected_version=V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        )
        if categories["overloaded"]:
            overloaded_slots.add(slot)
        if categories["notation_failure"]:
            notation_failure_slots.add(slot)
        if categories["dignity_failure"]:
            dignity_failure_slots.add(slot)
        if categories["ux_rejected"]:
            ux_rejected_slots.add(slot)
    reported_failures = {
        "overloaded_slots": overloaded_slots,
        "notation_failure_slots": notation_failure_slots,
        "dignity_failure_slots": dignity_failure_slots,
        "ux_rejected_slots": ux_rejected_slots,
    }
    for key, bucket in reported_failures.items():
        bucket.update(_v12_canonical_slot_list(global_output.get(key)))
    ux_rejected_slots.update(overloaded_slots | notation_failure_slots | dignity_failure_slots)
    distribution = _v12_instruction_voice_distribution(entries)
    clusters = _v12_canonicalize_overlapping_groups(
        global_output.get("repetitive_instruction_clusters") or [],
        id_key="cluster_id",
        summary_key="cluster_summary",
    )
    oversized_cluster_slots = sorted({
        slot
        for cluster in clusters
        if len(cluster.get("slots") or []) > V12_MAX_REPETITIVE_INSTRUCTION_CLUSTER
        for slot in (cluster.get("slots") or [])[V12_MAX_REPETITIVE_INSTRUCTION_CLUSTER:]
    })
    consecutive_voice_violation_slots = _v12_consecutive_voice_violation_slots(distribution)
    voice_family_count = len(distribution)
    coverage_slots = sorted(int(entry.get("slot") or 0) for entry in entries)
    coverage_ok = (
        coverage_slots == list(range(1, QUESTIONS_PER_GRAPH_NODE + 1))
        and len(coverage_slots) == len(set(coverage_slots))
    )
    inventory = v12_node_set_structured_inventory(node_entry)
    item_slots = inventory["slots"]
    item_count_ok = (
        inventory["item_count"] == QUESTIONS_PER_GRAPH_NODE
        and item_slots == list(range(1, QUESTIONS_PER_GRAPH_NODE + 1))
        and len(item_slots) == len(set(item_slots))
    )
    node_local_mainline_count = inventory["node_local_mainline_count"]
    controlled_stretch_count = inventory["controlled_stretch_count"]
    invalid_difficulty_vector_slots = inventory["invalid_difficulty_vector_slots"]
    gate_errors: list[str] = []
    if not item_count_ok:
        gate_errors.append("node_item_count_or_slot_coverage")
    if node_local_mainline_count < V12_MAINLINE_ROLE_MINIMUM:
        gate_errors.append("node_local_mainline_minimum")
    if controlled_stretch_count > V12_MAX_CONTROLLED_STRETCH_PER_NODE:
        gate_errors.append("controlled_stretch_maximum")
    if invalid_difficulty_vector_slots:
        gate_errors.append("difficulty_vector_invalid_slots")
    if not coverage_ok:
        gate_errors.append("slot_semantic_evidence_coverage")
    if voice_family_count < V12_MIN_INSTRUCTION_VOICE_FAMILIES:
        gate_errors.append("instruction_voice_family_minimum")
    if oversized_cluster_slots:
        gate_errors.append("repetitive_instruction_cluster_limit")
    if consecutive_voice_violation_slots:
        gate_errors.append("consecutive_instruction_voice_limit")
    if overloaded_slots:
        gate_errors.append("overloaded_slots")
    if notation_failure_slots:
        gate_errors.append("notation_failure_slots")
    if dignity_failure_slots:
        gate_errors.append("dignity_failure_slots")
    if ux_rejected_slots:
        gate_errors.append("ux_rejected_slots")
    if global_output and global_output.get("node_ux_verdict") != "approved":
        gate_errors.append("model_node_ux_verdict")
    return {
        "node_ux_verdict": "approved" if not gate_errors else "needs_repair",
        "unprompted_slot_results": _v12_unprompted_slot_results(node_entry, entries),
        "instruction_voice_distribution": distribution,
        "repetitive_instruction_clusters": clusters,
        "overloaded_slots": sorted(overloaded_slots),
        "notation_failure_slots": sorted(notation_failure_slots),
        "dignity_failure_slots": sorted(dignity_failure_slots),
        "ux_rejected_slots": sorted(ux_rejected_slots),
        "voice_family_count": voice_family_count,
        "item_count": inventory["item_count"],
        "node_local_mainline_count": node_local_mainline_count,
        "controlled_stretch_count": controlled_stretch_count,
        "invalid_difficulty_vector_slots": invalid_difficulty_vector_slots,
        "oversized_cluster_slots": oversized_cluster_slots,
        "consecutive_voice_violation_slots": consecutive_voice_violation_slots,
        "gate_errors": gate_errors,
    }


def v12_item_review_semantic_evidence_payload(
    item: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    evidence = review.get("semantic_evidence") if isinstance(review.get("semantic_evidence"), dict) else {}
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    return {
        "semantic_evidence_version": review.get("semantic_evidence_version") or evidence.get("version") or "",
        "item_id": item.get("id"),
        "candidate_sha256": v12_external_candidate_sha256(item),
        "review_verdict": review.get("verdict"),
        "review_confidence": review.get("confidence"),
        "semantic_scores": {key: scores.get(key) for key in V12_CONTENT_REVIEW_SCORE_KEYS},
        "semantic_evidence": evidence,
    }


def v12_item_review_semantic_evidence_sha256(
    item: dict[str, Any],
    review: dict[str, Any],
) -> str:
    return _v12_digest_json(v12_item_review_semantic_evidence_payload(item, review))


def _v12_item_by_slot(node_entry: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in node_entry.get("items") or []:
        if not isinstance(item, dict):
            continue
        try:
            slot = int(item.get("slot") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= slot <= QUESTIONS_PER_GRAPH_NODE:
            result[slot] = item
    return result


def _v12_scored_verdict_errors(value: Any, *, threshold: float) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"verdict", "score", "reason"}:
        return ["unexpected_or_missing_fields"]
    errors: list[str] = []
    if value.get("verdict") != "pass":
        errors.append("verdict_not_pass")
    score = _v12_score(value, "score")
    if score < threshold:
        errors.append("score_below_gate")
    if not str(value.get("reason") or "").strip():
        errors.append("reason_missing")
    return errors


def v12_repair_directive_errors(node_entry: dict[str, Any], directive: Any) -> list[str]:
    if not isinstance(directive, dict):
        return ["repair_directive:not_object"]
    item_by_slot = _v12_item_by_slot(node_entry)
    slot = int(directive.get("slot") or 0)
    item = item_by_slot.get(slot)
    if not item:
        return ["repair_directive:unknown_slot"]
    errors: list[str] = []
    role = str(item.get("slot_role") or "")
    if directive.get("preserved_role") != role:
        errors.append("repair_directive:preserved_role_mismatch")
    knowledge = _v12_agent_knowledge_cached()
    rules = knowledge.get("repair_delta_rules") if isinstance(knowledge.get("repair_delta_rules"), dict) else {}
    allowed_scopes = set(rules.get("repair_scopes") or []) | {
        "global_ownership",
        "global_evidence_diversity",
        "global_homogeneous_cluster",
        "global_difficulty",
        "global_prompt_interaction",
    }
    if directive.get("repair_scope") not in allowed_scopes:
        errors.append("repair_directive:repair_scope_invalid")
    if directive.get("preserve_or_replace_math_core") not in set(rules.get("math_core_decisions") or []):
        errors.append("repair_directive:math_core_decision_invalid")
    required_voice = str(directive.get("required_voice_family") or "")
    allowed = set(v12_role_voice_policy(role).get("allowed") or [])
    if required_voice not in allowed:
        errors.append("repair_directive:required_voice_not_allowed_for_role")
    avoided = directive.get("avoided_voice_families") if isinstance(directive.get("avoided_voice_families"), list) else []
    if any(family not in V12_INSTRUCTION_VOICE_FAMILIES for family in avoided):
        errors.append("repair_directive:avoided_voice_invalid")
    if required_voice in avoided:
        errors.append("repair_directive:required_voice_is_avoided")
    delta = directive.get("exact_target_delta") if isinstance(directive.get("exact_target_delta"), dict) else {}
    if set(delta) != {"dimension", "from_value", "to_value"}:
        errors.append("repair_directive:exact_target_delta_malformed")
        return errors
    dimension = str(delta.get("dimension") or "")
    allowed_dimensions = set(rules.get("delta_dimensions") or []) | {
        "ownership_mode",
        "primary_evidence_move",
        "answer_path_family",
        "representation_family",
        "difficulty_verdict",
        "prompt_interaction_verdict",
    }
    if dimension not in allowed_dimensions:
        errors.append("repair_directive:delta_dimension_invalid")
    from_value = str(delta.get("from_value") or "")
    to_value = str(delta.get("to_value") or "")
    if not from_value or not to_value or from_value == to_value:
        errors.append("repair_directive:no_op_delta")
    review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
    evidence = review.get("semantic_evidence") if isinstance(review.get("semantic_evidence"), dict) else {}
    current_voice = str(evidence.get("instruction_voice_family") or "")
    if dimension == "instruction_voice_family":
        if from_value != current_voice or to_value != required_voice or required_voice == current_voice:
            errors.append("repair_directive:voice_delta_no_op_or_mismatch")
    elif dimension == "process_disclosure" and evidence.get("process_target_disclosed") is not True:
        errors.append("repair_directive:process_disclosure_already_satisfied")
    elif dimension == "response_burden" and len(evidence.get("response_moves") or []) <= V12_MAX_RESPONSE_MOVES:
        errors.append("repair_directive:response_burden_already_satisfied")
    elif dimension == "notation_readiness":
        notation = evidence.get("rendered_notation_readiness") if isinstance(evidence.get("rendered_notation_readiness"), dict) else {}
        if notation.get("verdict") == "pass" and _v12_score(notation, "score") == 1.0 and not notation.get("child_visible_risks"):
            errors.append("repair_directive:notation_already_satisfied")
    elif dimension == "age_dignity":
        dignity = evidence.get("age_dignity") if isinstance(evidence.get("age_dignity"), dict) else {}
        if dignity.get("verdict") == "pass" and _v12_score(dignity, "score") >= V12_AGE_DIGNITY_MIN_SCORE:
            errors.append("repair_directive:dignity_already_satisfied")
    refs = directive.get("evidence_refs") if isinstance(directive.get("evidence_refs"), list) else []
    if not refs or any(not str(ref or "").strip() for ref in refs):
        errors.append("repair_directive:evidence_refs_missing")
    return errors


def v12_node_set_focal_review_output_errors(
    node_entry: dict[str, Any],
    *,
    reviewed_slots: list[int],
    output: dict[str, Any],
) -> dict[int, list[str]]:
    errors_by_slot: dict[int, list[str]] = {}
    expected_slots = sorted(int(slot) for slot in reviewed_slots)
    if output.get("semantic_evidence_version") != V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION:
        errors_by_slot.setdefault(0, []).append("semantic_evidence_version:mismatch")
    item_by_slot = _v12_item_by_slot(node_entry)
    raw_reviews = output.get("focal_slot_reviews") if isinstance(output.get("focal_slot_reviews"), list) else []
    seen_slots: list[int] = []
    suspicion_ids = {
        str(entry.get("suspicion_id") or "")
        for entry in (output.get("duplicate_suspicions") or [])
        if isinstance(entry, dict)
    }
    for entry in raw_reviews:
        if not isinstance(entry, dict):
            errors_by_slot.setdefault(0, []).append("focal_slot_reviews:entry_not_object")
            continue
        slot = int(entry.get("slot") or 0)
        seen_slots.append(slot)
        item = item_by_slot.get(slot)
        if not item:
            errors_by_slot.setdefault(slot, []).append("focal_slot_review:unknown_slot")
            continue
        item_review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
        if entry.get("item_id") != item.get("id"):
            errors_by_slot.setdefault(slot, []).append("focal_slot_review:item_id_mismatch")
        if entry.get("candidate_sha256") != v12_external_candidate_sha256(item):
            errors_by_slot.setdefault(slot, []).append("focal_slot_review:candidate_sha256_mismatch")
        subject = v12_item_review_subject_binding(item)
        if entry.get("child_surface_sha256") != subject["child_surface_sha256"]:
            errors_by_slot.setdefault(slot, []).append("focal_slot_review:child_surface_sha256_mismatch")
        if entry.get("item_review_request_sha256") != subject["item_review_request_sha256"]:
            errors_by_slot.setdefault(slot, []).append("focal_slot_review:item_review_request_sha256_mismatch")
        if entry.get("item_review_semantic_evidence_sha256") != item_review.get("semantic_evidence_sha256"):
            errors_by_slot.setdefault(slot, []).append("focal_slot_review:item_review_semantic_evidence_sha256_mismatch")
        for key in ("slot_fit", "mathematical_correctness", "context_semantics", "prompt_answer_alignment"):
            for detail in _v12_scored_verdict_errors(entry.get(key), threshold=V12_REVIEW_MIN_SCORE):
                # Approved slots must clear every score gate. A slot explicitly
                # routed to repair may carry a fail/low score as the defect
                # evidence; only malformed or ungrounded scored evidence is
                # invalid in that branch.
                if entry.get("verdict") == "approved" or detail in {
                    "unexpected_or_missing_fields",
                    "reason_missing",
                }:
                    errors_by_slot.setdefault(slot, []).append(f"focal_slot_review.{key}:{detail}")
        unknown_suspicions = set(entry.get("duplicate_suspicion_ids") or []) - suspicion_ids
        if unknown_suspicions:
            errors_by_slot.setdefault(slot, []).append("focal_slot_review:unknown_duplicate_suspicion_id")
    if sorted(seen_slots) != expected_slots or len(seen_slots) != len(set(seen_slots)):
        errors_by_slot.setdefault(0, []).append("focal_slot_reviews:coverage_mismatch")
    for suspicion in output.get("duplicate_suspicions") or []:
        if not isinstance(suspicion, dict):
            errors_by_slot.setdefault(0, []).append("duplicate_suspicions:entry_not_object")
            continue
        slots = set(_v12_canonical_slot_list(suspicion.get("slots")))
        if not slots.intersection(expected_slots):
            errors_by_slot.setdefault(0, []).append("duplicate_suspicions:must_include_focal_slot")
    rejected = _v12_canonical_slot_list(output.get("rejected_slots"))
    directives = [entry for entry in (output.get("repair_instructions") or []) if isinstance(entry, dict)]
    directive_slots = sorted({int(entry.get("slot") or 0) for entry in directives})
    if rejected != directive_slots:
        errors_by_slot.setdefault(0, []).append("rejected_slots:must_equal_repair_instruction_slots")
    for directive in directives:
        slot = int(directive.get("slot") or 0)
        if slot not in expected_slots:
            errors_by_slot.setdefault(slot, []).append("repair_directive:non_focal_slot")
        for detail in v12_repair_directive_errors(node_entry, directive):
            errors_by_slot.setdefault(slot, []).append(detail)
    review_verdict_by_slot = {
        int(entry.get("slot") or 0): entry.get("verdict")
        for entry in raw_reviews
        if isinstance(entry, dict)
    }
    for slot in expected_slots:
        if review_verdict_by_slot.get(slot) != "approved" and slot not in rejected:
            errors_by_slot.setdefault(slot, []).append("focal_slot_review:non_approved_without_repair")
    if output.get("verdict") == "approved":
        if rejected or directives or any(value != "approved" for value in review_verdict_by_slot.values()):
            errors_by_slot.setdefault(0, []).append("verdict:approved_with_repair_or_rejection")
    elif not rejected:
        errors_by_slot.setdefault(0, []).append("verdict:non_approved_without_exact_repair")
    if _v12_score(output, "confidence") < V12_NODE_SET_REVIEW_MIN_CONFIDENCE:
        errors_by_slot.setdefault(0, []).append("confidence:below_gate")
    return errors_by_slot


def v12_node_set_review_output_semantic_evidence_errors(
    node_entry: dict[str, Any],
    *,
    reviewed_slots: list[int],
    output: dict[str, Any],
) -> dict[int, list[str]]:
    return v12_node_set_focal_review_output_errors(
        node_entry,
        reviewed_slots=reviewed_slots,
        output=output,
    )


def v12_node_set_focal_slot_review_sha256(
    node_entry: dict[str, Any],
    entry: dict[str, Any],
) -> str:
    return _v12_digest_json({
        "semantic_evidence_version": V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "node_id": node_entry.get("node_id"),
        "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
        "slot_review": entry,
    })


def v12_node_set_slot_semantic_evidence_sha256(
    node_entry: dict[str, Any],
    entry: dict[str, Any],
) -> str:
    return v12_node_set_focal_slot_review_sha256(node_entry, entry)


def v12_node_set_constituent_semantic_evidence_payload(
    node_entry: dict[str, Any],
    constituent_review: dict[str, Any],
) -> dict[str, Any]:
    output = constituent_review.get("review_output") if isinstance(constituent_review.get("review_output"), dict) else {}
    coverage = [
        {
            "slot": entry.get("slot"),
            "item_id": entry.get("item_id"),
            "candidate_sha256": entry.get("candidate_sha256"),
            "child_surface_sha256": entry.get("child_surface_sha256"),
            "item_review_request_sha256": entry.get("item_review_request_sha256"),
            "item_review_semantic_evidence_sha256": entry.get("item_review_semantic_evidence_sha256"),
            "focal_review_sha256": v12_node_set_focal_slot_review_sha256(node_entry, entry),
        }
        for entry in (output.get("focal_slot_reviews") or [])
        if isinstance(entry, dict)
    ]
    coverage.sort(key=lambda entry: (int(entry.get("slot") or 0), str(entry.get("item_id") or "")))
    return {
        "semantic_evidence_version": V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
        "shard_id": constituent_review.get("shard_id"),
        "reviewed_slots": list(constituent_review.get("reviewed_slots") or []),
        "coverage": coverage,
        "verdict": output.get("verdict"),
        "rejected_slots": output.get("rejected_slots") or [],
        "duplicate_suspicions": output.get("duplicate_suspicions") or [],
        "repair_instructions": output.get("repair_instructions") or [],
    }


def v12_node_set_constituent_semantic_evidence_sha256(
    node_entry: dict[str, Any],
    constituent_review: dict[str, Any],
) -> str:
    return _v12_digest_json(v12_node_set_constituent_semantic_evidence_payload(node_entry, constituent_review))


def v12_node_set_semantic_evidence_coverage(
    node_entry: dict[str, Any],
    constituent_reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for review in constituent_reviews:
        if not isinstance(review, dict):
            continue
        payload = v12_node_set_constituent_semantic_evidence_payload(node_entry, review)
        for entry in payload["coverage"]:
            coverage.append({**entry, "shard_id": review.get("shard_id")})
    return sorted(
        coverage,
        key=lambda entry: (int(entry.get("slot") or 0), str(entry.get("shard_id") or "")),
    )


def v12_node_set_review_semantic_evidence_sha256(
    node_entry: dict[str, Any],
    constituent_reviews: list[dict[str, Any]],
    global_review_artifact: dict[str, Any] | None = None,
    global_verifier_artifact: dict[str, Any] | None = None,
) -> str:
    global_review_artifact = global_review_artifact if isinstance(global_review_artifact, dict) else {}
    global_verifier_artifact = global_verifier_artifact if isinstance(global_verifier_artifact, dict) else {}
    global_output = (
        global_review_artifact.get("global_review_output")
        if isinstance(global_review_artifact.get("global_review_output"), dict)
        else {}
    )
    return _v12_digest_json({
        "semantic_evidence_version": V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION,
        "agent_knowledge_version": V12_AGENT_KNOWLEDGE_VERSION,
        "agent_knowledge_sha256": v12_agent_knowledge_sha256(),
        "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
        "shard_policy": {
            "shard_size": V12_NODE_SET_REVIEW_SHARD_SIZE,
            "expected_shard_count": len(v12_expected_node_set_review_shards()),
        },
        "constituent_semantic_evidence_sha256": [
            v12_node_set_constituent_semantic_evidence_sha256(node_entry, review)
            for review in constituent_reviews
            if isinstance(review, dict)
        ],
        "coverage": v12_node_set_semantic_evidence_coverage(node_entry, constituent_reviews),
        "global_verifier": {
            "semantic_evidence_version": global_verifier_artifact.get("semantic_evidence_version") or "",
            "semantic_evidence_sha256": global_verifier_artifact.get("semantic_evidence_sha256") or "",
            "model_judgment_output_sha256": global_verifier_artifact.get("model_judgment_output_sha256") or "",
            "shard_artifacts_sha256": global_verifier_artifact.get("shard_artifacts_sha256") or "",
            "aggregate_commitment_sha256": global_verifier_artifact.get("aggregate_commitment_sha256") or "",
        },
        "global_finalizer": {
            "semantic_evidence_version": global_review_artifact.get("semantic_evidence_version") or "",
            "review_output_sha256": global_review_artifact.get("global_review_output_sha256") or "",
            "review_output": global_output,
        },
    })


def _v12_minimal_group_repair_slots(
    node_entry: dict[str, Any],
    *,
    base_slots: set[int],
    constraints: list[tuple[set[int], int]],
) -> set[int]:
    if all(len(slots - base_slots) <= maximum_remaining for slots, maximum_remaining in constraints):
        return set(base_slots)
    item_by_slot = _v12_item_by_slot(node_entry)
    candidates = sorted(
        {
            slot
            for slots, _ in constraints
            for slot in slots
            if slot not in base_slots
        },
        key=lambda slot: (
            int(v12_role_voice_policy(str((item_by_slot.get(slot) or {}).get("slot_role") or "")).get("repair_priority") or 999),
            slot,
        ),
    )
    for count in range(1, len(candidates) + 1):
        for selected in combinations(candidates, count):
            repaired = base_slots | set(selected)
            if all(len(slots - repaired) <= maximum_remaining for slots, maximum_remaining in constraints):
                return repaired
    return base_slots | set(candidates)


def v12_reduce_node_set_v4(
    node_entry: dict[str, Any],
    constituent_reviews: list[dict[str, Any]],
    global_output: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    expected_coverage = v12_node_set_semantic_evidence_coverage(node_entry, constituent_reviews)
    if global_output.get("semantic_evidence_version") != V12_NODE_SET_GLOBAL_REVIEW_SEMANTIC_EVIDENCE_VERSION:
        errors.append("global.semantic_evidence_version:mismatch")
    if global_output.get("slot_evidence_coverage") != expected_coverage:
        errors.append("global.slot_evidence_coverage:mismatch")
    ux = v12_node_set_ux_aggregate(node_entry, constituent_reviews, global_output)
    teaching_quality = v12_bounded_teaching_quality_gate(node_entry, global_output)
    reported_distribution, distribution_valid = _v12_normalize_reported_instruction_voice_distribution(
        global_output.get("instruction_voice_distribution")
    )
    if not distribution_valid or reported_distribution != ux["instruction_voice_distribution"]:
        errors.append("global.instruction_voice_distribution:mismatch")
    if sorted(global_output.get("unprompted_slot_results") or [], key=lambda value: int(value.get("slot") or 0)) != ux["unprompted_slot_results"]:
        errors.append("global.unprompted_slot_results:mismatch")
    for key in ("overloaded_slots", "notation_failure_slots", "dignity_failure_slots", "ux_rejected_slots"):
        if _v12_canonical_slot_list(global_output.get(key)) != ux[key]:
            errors.append(f"global.{key}:mismatch")
    scores = global_output.get("distribution_scores") if isinstance(global_output.get("distribution_scores"), dict) else {}
    low_scores = [key for key in V12_NODE_SET_DISTRIBUTION_SCORE_KEYS if _v12_score(scores, key) < V12_REVIEW_MIN_SCORE]
    low_confidence = _v12_score(global_output, "confidence") < V12_NODE_SET_REVIEW_MIN_CONFIDENCE
    directives = [entry for entry in (global_output.get("repair_plan") or []) if isinstance(entry, dict)]
    model_repair_slots = _v12_canonical_slot_list(global_output.get("rejected_slots"))
    directive_slots = sorted({int(entry.get("slot") or 0) for entry in directives})
    if model_repair_slots != directive_slots:
        errors.append("global.rejected_slots:must_equal_repair_plan_slots")
    for directive in directives:
        errors.extend(v12_repair_directive_errors(node_entry, directive))
    focal_rejected = {
        int(slot)
        for review in constituent_reviews
        if isinstance(review, dict)
        for slot in ((_v12_node_set_output(review).get("rejected_slots") or []))
        if isinstance(slot, int)
    }
    base_slots = set(focal_rejected)
    for key in ("overloaded_slots", "notation_failure_slots", "dignity_failure_slots", "ux_rejected_slots"):
        base_slots.update(ux[key])
    base_slots.update(ux["consecutive_voice_violation_slots"])
    base_slots.update(teaching_quality["rejected_slots"])
    duplicate_groups = _v12_canonicalize_overlapping_groups(
        global_output.get("duplicate_groups") or [],
        id_key="group_id",
        summary_key="reason",
    )
    constraints: list[tuple[set[int], int]] = [
        (set(group.get("slots") or []), 1)
        for group in duplicate_groups
    ]
    constraints.extend(
        (set(cluster.get("slots") or []), V12_MAX_REPETITIVE_INSTRUCTION_CLUSTER)
        for cluster in ux["repetitive_instruction_clusters"]
    )
    constraints.extend(
        (set(cluster.get("slots") or []), V12_MAX_HOMOGENEOUS_CLUSTER)
        for cluster in teaching_quality["homogeneous_clusters"]
    )
    canonical_slots = _v12_minimal_group_repair_slots(
        node_entry,
        base_slots=base_slots,
        constraints=constraints,
    )
    family_deficit = max(0, V12_MIN_INSTRUCTION_VOICE_FAMILIES - ux["voice_family_count"])
    if family_deficit:
        current_families = {
            str(entry.get("instruction_voice_family") or "")
            for entry in ux["instruction_voice_distribution"]
        }
        candidates = []
        introduced: set[str] = set()
        for directive in sorted(directives, key=lambda entry: int(entry.get("slot") or 0)):
            required = str(directive.get("required_voice_family") or "")
            if directive.get("repair_scope") != "global_voice_distribution":
                continue
            if required in current_families or required in introduced:
                continue
            candidates.append(int(directive.get("slot") or 0))
            introduced.add(required)
            if len(introduced) >= family_deficit:
                break
        if len(introduced) < family_deficit:
            errors.append("global.voice_family_minimum:missing_exact_repair_plan")
        canonical_slots.update(slot for slot in candidates if slot)
    if (low_scores or low_confidence) and not directives:
        errors.append("global.low_score_or_confidence:missing_exact_repair_plan")
    if (low_scores or low_confidence) and directives:
        canonical_slots.update(directive_slots)
    evidence_family_deficit = max(
        0,
        V12_MIN_PRIMARY_EVIDENCE_MOVE_FAMILIES
        - teaching_quality["primary_evidence_move_family_count"],
    )
    if evidence_family_deficit:
        evidence_directives = [
            int(directive.get("slot") or 0)
            for directive in directives
            if directive.get("repair_scope") == "global_evidence_diversity"
        ]
        if len(set(evidence_directives)) < evidence_family_deficit:
            errors.append("global.primary_evidence_move_family_minimum:missing_exact_repair_plan")
        canonical_slots.update(slot for slot in evidence_directives if slot)
    if teaching_quality["gate_errors"] and not directives:
        errors.append("global.teaching_quality_failure_without_repair_plan")
    has_global_failure = bool(
        focal_rejected
        or ux["gate_errors"]
        or teaching_quality["gate_errors"]
        or duplicate_groups
        or low_scores
        or low_confidence
    )
    if has_global_failure and not directives:
        errors.append("global.failure_without_repair_plan")
    if canonical_slots != set(model_repair_slots):
        errors.append("global.repair_plan:not_canonical_minimal_set")
    expected_verdict = "needs_repair" if has_global_failure or canonical_slots else "approved"
    if global_output.get("verdict") != expected_verdict:
        errors.append("global.verdict:mismatch")
    expected_ux_verdict = "needs_repair" if ux["gate_errors"] else "approved"
    if global_output.get("node_ux_verdict") != expected_ux_verdict:
        errors.append("global.node_ux_verdict:mismatch")
    if expected_verdict == "approved" and (model_repair_slots or directives):
        errors.append("global.approved_with_repair_plan")
    return {
        "errors": sorted(set(errors)),
        "verdict": expected_verdict,
        "node_ux_verdict": expected_ux_verdict,
        "distribution_scores": {key: scores.get(key) for key in V12_NODE_SET_DISTRIBUTION_SCORE_KEYS},
        "confidence": _v12_score(global_output, "confidence"),
        "duplicate_groups": duplicate_groups,
        "reasons": list(global_output.get("reasons") or []),
        "repair_instructions": sorted(directives, key=lambda entry: int(entry.get("slot") or 0)),
        "rejected_slots": sorted(canonical_slots),
        "teaching_quality_gate": teaching_quality,
        **ux,
    }


def _v12_union_dict_entries(*collections: Any) -> list[dict[str, Any]]:
    by_digest: dict[str, dict[str, Any]] = {}
    for collection in collections:
        for entry in collection if isinstance(collection, list) else []:
            if not isinstance(entry, dict):
                continue
            by_digest.setdefault(_v12_digest_json(entry), copy.deepcopy(entry))
    return [by_digest[key] for key in sorted(by_digest)]


def v12_union_independent_global_reviews(
    node_entry: dict[str, Any],
    constituent_reviews: list[dict[str, Any]],
    verifier_output: dict[str, Any],
    finalizer_output: dict[str, Any],
) -> dict[str, Any]:
    verifier = v12_reduce_node_set_v4(node_entry, constituent_reviews, verifier_output)
    finalizer = v12_reduce_node_set_v4(node_entry, constituent_reviews, finalizer_output)
    errors = [
        *(f"global_verifier:{detail}" for detail in verifier.get("errors") or []),
        *(f"global_finalizer:{detail}" for detail in finalizer.get("errors") or []),
    ]
    if errors:
        return {"errors": sorted(set(errors))}
    verifier_teaching = verifier.get("teaching_quality_gate") if isinstance(
        verifier.get("teaching_quality_gate"), dict
    ) else {}
    finalizer_teaching = finalizer.get("teaching_quality_gate") if isinstance(
        finalizer.get("teaching_quality_gate"), dict
    ) else {}
    repair_instructions = _v12_union_dict_entries(
        verifier.get("repair_instructions"),
        finalizer.get("repair_instructions"),
    )
    repair_instructions.sort(
        key=lambda entry: (int(entry.get("slot") or 0), _v12_digest_json(entry))
    )
    rejected_slots = sorted({
        *[int(slot) for slot in (verifier.get("rejected_slots") or [])],
        *[int(slot) for slot in (finalizer.get("rejected_slots") or [])],
    })
    teaching_quality_gate = {
        "gate_errors": sorted({
            *(verifier_teaching.get("gate_errors") or []),
            *(finalizer_teaching.get("gate_errors") or []),
        }),
        "rejected_slots": sorted({
            *[int(slot) for slot in (verifier_teaching.get("rejected_slots") or [])],
            *[int(slot) for slot in (finalizer_teaching.get("rejected_slots") or [])],
        }),
        "primary_evidence_move_family_count": min(
            int(verifier_teaching.get("primary_evidence_move_family_count") or 0),
            int(finalizer_teaching.get("primary_evidence_move_family_count") or 0),
        ),
        "homogeneous_clusters": _v12_union_dict_entries(
            verifier_teaching.get("homogeneous_clusters"),
            finalizer_teaching.get("homogeneous_clusters"),
        ),
        "oversized_homogeneous_clusters": _v12_union_dict_entries(
            verifier_teaching.get("oversized_homogeneous_clusters"),
            finalizer_teaching.get("oversized_homogeneous_clusters"),
        ),
        "repetitive_clusters_missing_exact_plan": sorted({
            *(verifier_teaching.get("repetitive_clusters_missing_exact_plan") or []),
            *(finalizer_teaching.get("repetitive_clusters_missing_exact_plan") or []),
        }),
        "authority_results": {
            "global_verifier": copy.deepcopy(verifier_teaching),
            "global_finalizer": copy.deepcopy(finalizer_teaching),
        },
    }
    return {
        "errors": [],
        "verdict": "needs_repair" if (
            verifier.get("verdict") != "approved"
            or finalizer.get("verdict") != "approved"
            or rejected_slots
            or repair_instructions
        ) else "approved",
        "node_ux_verdict": "needs_repair" if (
            verifier.get("node_ux_verdict") != "approved"
            or finalizer.get("node_ux_verdict") != "approved"
        ) else "approved",
        "distribution_scores": {
            key: min(
                _v12_score(verifier.get("distribution_scores") or {}, key),
                _v12_score(finalizer.get("distribution_scores") or {}, key),
            )
            for key in V12_NODE_SET_DISTRIBUTION_SCORE_KEYS
        },
        "confidence": min(
            _v12_score(verifier, "confidence"),
            _v12_score(finalizer, "confidence"),
        ),
        "duplicate_groups": _v12_union_dict_entries(
            verifier.get("duplicate_groups"),
            finalizer.get("duplicate_groups"),
        ),
        "reasons": [
            *(f"global_verifier: {reason}" for reason in (verifier.get("reasons") or [])),
            *(f"global_finalizer: {reason}" for reason in (finalizer.get("reasons") or [])),
        ],
        "repair_instructions": repair_instructions,
        "rejected_slots": rejected_slots,
        "teaching_quality_gate": teaching_quality_gate,
        "unprompted_slot_results": _v12_union_dict_entries(
            verifier.get("unprompted_slot_results"),
            finalizer.get("unprompted_slot_results"),
        ),
        "instruction_voice_distribution": verifier.get("instruction_voice_distribution") or [],
        "repetitive_instruction_clusters": _v12_union_dict_entries(
            verifier.get("repetitive_instruction_clusters"),
            finalizer.get("repetitive_instruction_clusters"),
        ),
        "overloaded_slots": sorted({
            *(verifier.get("overloaded_slots") or []),
            *(finalizer.get("overloaded_slots") or []),
        }),
        "notation_failure_slots": sorted({
            *(verifier.get("notation_failure_slots") or []),
            *(finalizer.get("notation_failure_slots") or []),
        }),
        "dignity_failure_slots": sorted({
            *(verifier.get("dignity_failure_slots") or []),
            *(finalizer.get("dignity_failure_slots") or []),
        }),
        "ux_rejected_slots": sorted({
            *(verifier.get("ux_rejected_slots") or []),
            *(finalizer.get("ux_rejected_slots") or []),
        }),
        "voice_family_count": min(
            int(verifier.get("voice_family_count") or 0),
            int(finalizer.get("voice_family_count") or 0),
        ),
        "item_count": min(
            int(verifier.get("item_count") or 0),
            int(finalizer.get("item_count") or 0),
        ),
        "node_local_mainline_count": min(
            int(verifier.get("node_local_mainline_count") or 0),
            int(finalizer.get("node_local_mainline_count") or 0),
        ),
        "controlled_stretch_count": max(
            int(verifier.get("controlled_stretch_count") or 0),
            int(finalizer.get("controlled_stretch_count") or 0),
        ),
        "invalid_difficulty_vector_slots": sorted({
            *(verifier.get("invalid_difficulty_vector_slots") or []),
            *(finalizer.get("invalid_difficulty_vector_slots") or []),
        }),
        "oversized_cluster_slots": sorted({
            *(verifier.get("oversized_cluster_slots") or []),
            *(finalizer.get("oversized_cluster_slots") or []),
        }),
        "consecutive_voice_violation_slots": sorted({
            *(verifier.get("consecutive_voice_violation_slots") or []),
            *(finalizer.get("consecutive_voice_violation_slots") or []),
        }),
        "gate_errors": sorted({
            *(verifier.get("gate_errors") or []),
            *(finalizer.get("gate_errors") or []),
        }),
    }


def v12_node_semantic_evidence_commitment(node_entry: dict[str, Any]) -> dict[str, Any]:
    item_reviews = []
    items = [item for item in (node_entry.get("items") or []) if isinstance(item, dict)]
    for item in sorted(items, key=lambda value: int(value.get("slot") or 0)):
        review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
        item_reviews.append({
            "slot": item.get("slot"),
            "item_id": item.get("id"),
            "semantic_evidence_version": review.get("semantic_evidence_version") or "",
            "semantic_evidence_sha256": review.get("semantic_evidence_sha256") or "",
        })
    artifact = node_entry.get("node_review_artifact") if isinstance(node_entry.get("node_review_artifact"), dict) else {}
    constituent_reviews = artifact.get("constituent_reviews") if isinstance(artifact.get("constituent_reviews"), list) else []
    global_verifier = artifact.get("global_verifier") if isinstance(artifact.get("global_verifier"), dict) else {}
    global_finalizer = artifact.get("global_finalizer") if isinstance(artifact.get("global_finalizer"), dict) else {}
    node_set_review = {
        "semantic_evidence_version": artifact.get("semantic_evidence_version") or "",
        "semantic_evidence_sha256": artifact.get("semantic_evidence_sha256") or "",
        "semantic_evidence_coverage": artifact.get("semantic_evidence_coverage") or [],
        "node_ux_verdict": artifact.get("node_ux_verdict") or "",
        "unprompted_slot_results": artifact.get("unprompted_slot_results") or [],
        "instruction_voice_distribution": artifact.get("instruction_voice_distribution") or [],
        "repetitive_instruction_clusters": artifact.get("repetitive_instruction_clusters") or [],
        "overloaded_slots": artifact.get("overloaded_slots") or [],
        "notation_failure_slots": artifact.get("notation_failure_slots") or [],
        "dignity_failure_slots": artifact.get("dignity_failure_slots") or [],
        "ux_rejected_slots": artifact.get("ux_rejected_slots") or [],
        "item_count": artifact.get("item_count"),
        "node_local_mainline_count": artifact.get("node_local_mainline_count"),
        "controlled_stretch_count": artifact.get("controlled_stretch_count"),
        "invalid_difficulty_vector_slots": artifact.get("invalid_difficulty_vector_slots") or [],
        "gate_errors": artifact.get("gate_errors") or [],
        "focal_review_semantic_evidence_sha256": [
            review.get("semantic_evidence_sha256") or ""
            for review in constituent_reviews
            if isinstance(review, dict)
        ],
        "global_verifier": {
            "contract_version": global_verifier.get("contract_version") or "",
            "prompt_version_id": global_verifier.get("prompt_version_id") or "",
            "prompt_template_sha256": global_verifier.get("prompt_template_sha256") or "",
            "rendered_prompt_sha256": global_verifier.get("rendered_prompt_sha256") or "",
            "response_schema_version": global_verifier.get("response_schema_version") or "",
            "response_schema_sha256": global_verifier.get("response_schema_sha256") or "",
            "request_lineage_version": global_verifier.get("request_lineage_version") or "",
            "trusted_context_sha256": global_verifier.get("trusted_context_sha256") or "",
            "untrusted_payload_sha256": global_verifier.get("untrusted_payload_sha256") or "",
            "request_options_sha256": global_verifier.get("request_options_sha256") or "",
            "request_input_sha256": global_verifier.get("request_input_sha256") or "",
            "request_lineage_sha256": global_verifier.get("request_lineage_sha256") or "",
            "semantic_evidence_version": global_verifier.get("semantic_evidence_version") or "",
            "semantic_evidence_sha256": global_verifier.get("semantic_evidence_sha256") or "",
            "model_judgment_output_sha256": global_verifier.get("model_judgment_output_sha256") or "",
            "shard_policy_version": global_verifier.get("shard_policy_version") or "",
            "expected_shards": global_verifier.get("expected_shards") or [],
            "shard_artifacts_sha256": global_verifier.get("shard_artifacts_sha256") or "",
            "shard_semantic_evidence_sha256s": global_verifier.get("shard_semantic_evidence_sha256s") or [],
            "aggregate_commitment_sha256": global_verifier.get("aggregate_commitment_sha256") or "",
        },
        "global_finalizer": {
            "contract_version": global_finalizer.get("contract_version") or "",
            "prompt_version_id": global_finalizer.get("prompt_version_id") or "",
            "prompt_template_sha256": global_finalizer.get("prompt_template_sha256") or "",
            "rendered_prompt_sha256": global_finalizer.get("rendered_prompt_sha256") or "",
            "response_schema_version": global_finalizer.get("response_schema_version") or "",
            "response_schema_sha256": global_finalizer.get("response_schema_sha256") or "",
            "request_lineage_version": global_finalizer.get("request_lineage_version") or "",
            "trusted_context_sha256": global_finalizer.get("trusted_context_sha256") or "",
            "untrusted_payload_sha256": global_finalizer.get("untrusted_payload_sha256") or "",
            "request_options_sha256": global_finalizer.get("request_options_sha256") or "",
            "request_input_sha256": global_finalizer.get("request_input_sha256") or "",
            "request_lineage_sha256": global_finalizer.get("request_lineage_sha256") or "",
            "semantic_evidence_version": global_finalizer.get("semantic_evidence_version") or "",
            "semantic_evidence_sha256": global_finalizer.get("semantic_evidence_sha256") or "",
            "model_judgment_output_sha256": global_finalizer.get("model_judgment_output_sha256") or "",
            "global_review_output_sha256": global_finalizer.get("global_review_output_sha256") or "",
        },
        "shard_policy": {
            "node_set_review_shard_size": V12_NODE_SET_REVIEW_SHARD_SIZE,
            "node_set_review_expected_shards": len(v12_expected_node_set_review_shards()),
        },
    }
    payload = {
        "version": V12_SEMANTIC_EVIDENCE_COMMITMENT_VERSION,
        "node_id": node_entry.get("node_id"),
        "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
        "agent_knowledge_version": V12_AGENT_KNOWLEDGE_VERSION,
        "agent_knowledge_sha256": v12_agent_knowledge_sha256(),
        "item_reviews": item_reviews,
        "node_set_review": node_set_review,
    }
    return {**payload, "sha256": _v12_digest_json(payload)}


def v12_child_surface_projection_commitment(node_entry: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in (node_entry.get("items") or []) if isinstance(item, dict)]
    bindings = [
        v12_item_review_subject_binding(item)
        for item in sorted(items, key=lambda value: int(value.get("slot") or 0))
    ]
    payload = {
        "version": CHILD_SURFACE_PROJECTION_VERSION,
        "node_id": node_entry.get("node_id"),
        "item_bindings": bindings,
    }
    return {**payload, "sha256": _v12_digest_json(payload)}


def v12_pilot_six_inventory_errors(manifest: Any) -> list[str]:
    if not isinstance(manifest, dict):
        return ["pilot_six:manifest_not_object"]
    nodes = manifest.get("nodes")
    if not isinstance(nodes, list):
        return ["pilot_six:nodes_not_array"]
    errors: list[str] = []
    node_ids = [str(node.get("node_id") or "") for node in nodes if isinstance(node, dict)]
    if len(nodes) != len(V12_PILOT_SIX_NODE_IDS):
        errors.append("pilot_six:requires_exactly_six_nodes")
    if node_ids != list(V12_PILOT_SIX_NODE_IDS):
        errors.append("pilot_six:node_ids_or_order_mismatch")
    question_ids: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("pilot_six:node_not_object")
            continue
        node_id = str(node.get("node_id") or "")
        items = node.get("items")
        if not isinstance(items, list) or len(items) != QUESTIONS_PER_GRAPH_NODE:
            errors.append(f"pilot_six:{node_id}:requires_exactly_twenty_items")
            continue
        for item in items:
            if not isinstance(item, dict):
                errors.append(f"pilot_six:{node_id}:item_not_object")
                continue
            question_id = str(item.get("id") or "")
            question_ids.append(question_id)
            if item.get("node_id") != node_id:
                errors.append(f"pilot_six:{question_id}:node_binding_mismatch")
    if len(question_ids) != len(V12_PILOT_SIX_NODE_IDS) * QUESTIONS_PER_GRAPH_NODE:
        errors.append("pilot_six:requires_exactly_120_questions")
    if len(set(question_ids)) != len(V12_PILOT_SIX_NODE_IDS) * QUESTIONS_PER_GRAPH_NODE:
        errors.append("pilot_six:requires_120_unique_questions")
    if any(not question_id for question_id in question_ids):
        errors.append("pilot_six:question_id_missing")
    return sorted(set(errors))


def validate_external_question_bank_v12(manifest: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    graph_nodes = {str(node.get("id") or ""): node for node in graph.get("nodes", []) if node.get("id")}
    seen_question_ids: set[str] = set()
    node_summaries: list[dict[str, Any]] = []

    if manifest.get("schema_version") != QUESTION_BANK_V12_SCHEMA_VERSION:
        issues.append(_v12_issue("P0", "v12_schema_version_mismatch", "-", str(manifest.get("schema_version") or "")))
    if manifest.get("question_bank_version") != QUESTION_BANK_V12_VERSION:
        issues.append(_v12_issue("P0", "v12_question_bank_version_mismatch", "-", str(manifest.get("question_bank_version") or "")))
    if not manifest.get("graph_version"):
        issues.append(_v12_issue("P0", "v12_missing_graph_version", "-", "manifest graph_version is required"))

    for node_entry in manifest.get("nodes") or []:
        node_id = str(node_entry.get("node_id") or "")
        graph_node = graph_nodes.get(node_id)
        items = node_entry.get("items") if isinstance(node_entry.get("items"), list) else []
        if not graph_node:
            issues.append(_v12_issue("P0", "v12_unknown_graph_node", node_id, "node is not in graph"))
            continue
        if len(items) != QUESTIONS_PER_GRAPH_NODE:
            issues.append(_v12_issue("P0", "v12_node_question_count_not_20", node_id, f"{len(items)} items"))
        slots = [item.get("slot") for item in items]
        if sorted(slots) != list(range(1, QUESTIONS_PER_GRAPH_NODE + 1)):
            issues.append(_v12_issue("P0", "v12_slots_not_exact_1_to_20", node_id, f"slots={slots}"))
        mainline_count = 0
        stretch_count = 0
        node_core_counts: Counter[str] = Counter()
        node_family_counts: Counter[str] = Counter()
        approved_count = 0
        node_child_surfaces_valid = True
        for item in items:
            item_id = str(item.get("id") or "")
            slot = int(item.get("slot") or 0)
            role = str(item.get("slot_role") or "")
            core = str(item.get("math_core_signature") or item.get("core_stem_id") or item_id)
            family = str(item.get("problem_family_id") or "")
            node_core_counts[core] += 1
            if family:
                node_family_counts[family] += 1
            if item_id in seen_question_ids:
                issues.append(_v12_issue("P0", "v12_duplicate_question_id", node_id, item_id))
            seen_question_ids.add(item_id)
            if item.get("node_id") != node_id:
                issues.append(_v12_issue("P0", "v12_item_node_mismatch", node_id, item_id))
            expected_slot_role = v12_slot_role_for_node(graph_node, slot)
            if expected_slot_role and role != expected_slot_role:
                issues.append(_v12_issue("P1", "v12_slot_role_mismatch", node_id, f"{item_id}:{role}"))
            item_policy_errors = v12_item_policy_errors(graph_node, item)
            if any(detail.startswith("child_surface:") for detail in item_policy_errors):
                node_child_surfaces_valid = False
            for detail in item_policy_errors:
                issues.append(_v12_issue("P1", "v12_item_policy_violation", node_id, f"{item_id}:{detail}"))
            for detail in _v12_difficulty_vector_errors(item):
                issues.append(_v12_issue("P1", "v12_invalid_difficulty_vector", node_id, f"{item_id}:{detail}"))
            allowed_tags = _v12_allowed_error_tags_for_node(graph_node)
            for tag in item.get("target_error_tags") or []:
                if tag not in allowed_tags:
                    issues.append(_v12_issue("P1", "v12_unknown_target_error_tag", node_id, f"{item_id}:{tag}"))
            allowed_rollbacks = set(_v12_allowed_rollback_nodes_for_node(graph_node))
            for rollback_id in item.get("rollback_candidates") or []:
                if str(rollback_id) not in allowed_rollbacks:
                    issues.append(_v12_issue("P1", "v12_illegal_rollback_candidate", node_id, f"{item_id}:{rollback_id}"))
            if bool(item.get("node_local_mainline")):
                mainline_count += 1
            if bool(item.get("controlled_stretch")) or role == "controlled_stretch":
                stretch_count += 1
                summer = graph_node.get("summer_execution") if isinstance(graph_node.get("summer_execution"), dict) else {}
                if summer.get("mode") != "controlled_extension":
                    issues.append(_v12_issue("P1", "v12_controlled_stretch_on_ineligible_node", node_id, item_id))
            _validate_v12_designer_artifact(item, node_id=node_id, item_id=item_id, issues=issues)
            _validate_v12_item_review_artifact(item, node_id=node_id, item_id=item_id, issues=issues)
            if (item.get("review_artifact") or {}).get("verdict") == "approved":
                approved_count += 1
            if not str(item.get("prompt") or "").strip() or not str(item.get("expected_answer") or "").strip():
                issues.append(_v12_issue("P0", "v12_prompt_or_answer_missing", node_id, item_id))
            if len(item.get("solution_steps") or []) < 2:
                issues.append(_v12_issue("P0", "v12_solution_steps_too_thin", node_id, item_id))
        for core, count in node_core_counts.items():
            if count > V12_MAX_CORE_REPEAT_PER_NODE:
                issues.append(_v12_issue("P1", "v12_core_reused_too_often", node_id, f"{core} repeats {count}"))
        for family, count in node_family_counts.items():
            if count > MAX_PROBLEM_FAMILY_REPEAT_PER_NODE:
                issues.append(_v12_issue("P1", "v12_problem_family_repeated_too_often", node_id, f"{family} repeats {count}"))
        if mainline_count < V12_MAINLINE_ROLE_MINIMUM:
            issues.append(_v12_issue("P1", "v12_too_few_node_local_mainline_items", node_id, f"{mainline_count}/{QUESTIONS_PER_GRAPH_NODE}"))
        if stretch_count > V12_MAX_CONTROLLED_STRETCH_PER_NODE:
            issues.append(_v12_issue("P1", "v12_too_many_controlled_stretch_items", node_id, f"{stretch_count}"))
        if (
            node_child_surfaces_valid
            and str(manifest.get("status") or "") not in {"draft_live_round", "checkpoint_resume"}
        ):
            _validate_v12_node_review_artifact(
                node_entry,
                node_id=node_id,
                graph_version=str(manifest.get("graph_version") or ""),
                issues=issues,
            )
        node_summaries.append({
            "node_id": node_id,
            "item_count": len(items),
            "approved_count": approved_count,
            "node_local_mainline_count": mainline_count,
            "controlled_stretch_count": stretch_count,
            "unique_math_core_count": len(node_core_counts),
            "unique_problem_family_count": len(node_family_counts),
            "max_core_repeat": max(node_core_counts.values() or [0]),
            "max_problem_family_repeat": max(node_family_counts.values() or [0]),
        })

    return {
        "schema_version": QUESTION_BANK_V12_SCHEMA_VERSION,
        "question_bank_version": str(manifest.get("question_bank_version") or ""),
        "node_count": len(manifest.get("nodes") or []),
        "item_count": sum(len(node.get("items") or []) for node in manifest.get("nodes") or []),
        "node_summaries": node_summaries,
        "issues": issues,
    }


def _v12_difficulty_vector_errors(item: dict[str, Any]) -> list[str]:
    vector = item.get("difficulty_vector") if isinstance(item.get("difficulty_vector"), dict) else {}
    errors: list[str] = []
    for key, (minimum, maximum) in V12_DIFFICULTY_VECTOR_RANGES.items():
        value = vector.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{key}:missing_or_not_integer")
            continue
        if value < minimum or value > maximum:
            errors.append(f"{key}:out_of_range:{value}")
    return errors


def _v12_allowed_error_tags_for_node(node: dict[str, Any]) -> set[str]:
    error_diagnosis = node.get("error_diagnosis") if isinstance(node.get("error_diagnosis"), dict) else {}
    likely = [str(tag) for tag in (error_diagnosis.get("likely_error_tags") or []) if str(tag) in CANONICAL_ERROR_TAGS]
    return set(likely or CANONICAL_ERROR_TAGS)


def _v12_allowed_rollback_nodes_for_node(node: dict[str, Any]) -> list[str]:
    error_diagnosis = node.get("error_diagnosis") if isinstance(node.get("error_diagnosis"), dict) else {}
    ordered = []
    for node_id in [*(error_diagnosis.get("rollback_to") or []), *(node.get("prerequisites") or [])]:
        node_id = str(node_id)
        if node_id and node_id not in ordered:
            ordered.append(node_id)
    return ordered


def _validate_v12_designer_artifact(
    item: dict[str, Any],
    *,
    node_id: str,
    item_id: str,
    issues: list[dict[str, Any]],
) -> None:
    artifact = item.get("designer_artifact") if isinstance(item.get("designer_artifact"), dict) else {}
    expected = {
        "agent_key": QUESTION_DESIGNER_AGENT_KEY,
        "phase": "question_candidate",
        "artifact_role": "designer",
        "contract_key": "math_question_bank_v12_designer_batch",
        "contract_version": V12_DESIGNER_CONTRACT_VERSION,
        "prompt_version_id": V12_DESIGNER_PROMPT_VERSION_ID,
        "response_schema_version": V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
    }
    if not artifact or not str(artifact.get("designer_run_id") or "").strip():
        issues.append(_v12_issue("P1", "v12_missing_designer_artifact", node_id, item_id))
        return
    for key, value in expected.items():
        if artifact.get(key) != value:
            issues.append(_v12_issue("P1", "v12_designer_contract_identity_mismatch", node_id, f"{item_id}:{key}"))
    for key in ("prompt_template_sha256", "rendered_prompt_sha256", "response_schema_sha256", "batch_raw_response_sha256"):
        if not str(artifact.get(key) or "").strip():
            issues.append(_v12_issue("P1", "v12_designer_contract_identity_mismatch", node_id, f"{item_id}:{key}"))


def _validate_v12_item_review_artifact(item: dict[str, Any], *, node_id: str, item_id: str, issues: list[dict[str, Any]]) -> None:
    review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
    evidence = review.get("reviewer_evidence") if isinstance(review.get("reviewer_evidence"), dict) else {}
    if not review or not review.get("reviewer_run_id") or review.get("verdict") != "approved":
        issues.append(_v12_issue("P1", "v12_missing_independent_review_artifact", node_id, item_id))
        return
    expected = {
        "agent_key": QUESTION_REVIEWER_AGENT_KEY,
        "phase": "question_review",
        "artifact_role": "reviewer",
        "contract_key": "math_question_bank_v12_reviewer_batch",
        "contract_version": V12_REVIEWER_CONTRACT_VERSION,
        "prompt_version_id": V12_REVIEWER_PROMPT_VERSION_ID,
        "response_schema_version": V12_REVIEWER_RESPONSE_SCHEMA_VERSION,
        "semantic_evidence_version": V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
    }
    for key, value in expected.items():
        if review.get(key) != value:
            issues.append(_v12_issue("P1", "v12_reviewer_contract_identity_mismatch", node_id, f"{item_id}:{key}"))
    for key in ("prompt_template_sha256", "rendered_prompt_sha256", "response_schema_sha256", "batch_raw_response_sha256"):
        if not str(review.get(key) or "").strip():
            issues.append(_v12_issue("P1", "v12_reviewer_contract_identity_mismatch", node_id, f"{item_id}:{key}"))
    if review.get("candidate_sha256") != v12_external_candidate_sha256(item):
        issues.append(_v12_issue("P1", "v12_review_candidate_hash_mismatch", node_id, item_id))
    for detail in v12_item_review_binding_errors(item):
        issues.append(_v12_issue("P1", "v12_item_review_binding_failed", node_id, f"{item_id}:{detail}"))
    if evidence.get("provenance_type") != V12_REVIEW_PROVENANCE:
        issues.append(_v12_issue("P1", "v12_missing_independent_review_artifact", node_id, f"{item_id}:bad_provenance"))
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    for score_key in V12_REVIEW_SCORE_KEYS:
        if _v12_score(scores, score_key) < V12_REVIEW_MIN_SCORE:
            issues.append(_v12_issue("P1", "v12_review_score_below_gate", node_id, f"{item_id}:{score_key}"))
    for score_key in V12_CONTENT_REVIEW_SCORE_KEYS:
        if _v12_score(scores, score_key) < V12_SEMANTIC_GATE_MIN_SCORE:
            issues.append(_v12_issue("P1", "v12_item_semantic_score_below_gate", node_id, f"{item_id}:{score_key}"))
    if _v12_score(review, "confidence") < V12_REVIEW_MIN_CONFIDENCE:
        issues.append(_v12_issue("P1", "v12_review_confidence_below_gate", node_id, item_id))
    for flag in REVIEWER_EVIDENCE_FLAGS:
        if evidence.get(flag) is not True:
            issues.append(_v12_issue("P1", "v12_review_evidence_flag_failed", node_id, f"{item_id}:{flag}"))
    for detail in v12_semantic_evidence_errors(
        item,
        review.get("semantic_evidence"),
        expected_version=V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
    ):
        issues.append(_v12_issue("P1", "v12_item_semantic_evidence_failed", node_id, f"{item_id}:{detail}"))
    expected_digest = v12_item_review_semantic_evidence_sha256(item, review)
    if review.get("semantic_evidence_sha256") != expected_digest:
        issues.append(_v12_issue("P1", "v12_item_semantic_evidence_digest_mismatch", node_id, item_id))


def _validate_v12_node_review_artifact(
    node_entry: dict[str, Any],
    *,
    node_id: str,
    graph_version: str,
    issues: list[dict[str, Any]],
) -> None:
    artifact = node_entry.get("node_review_artifact") if isinstance(node_entry.get("node_review_artifact"), dict) else {}
    if not artifact:
        issues.append(_v12_issue("P1", "v12_missing_node_set_review_artifact", node_id, "node_review_artifact is required"))
        return
    if not str(artifact.get("node_reviewer_run_id") or "").strip() or artifact.get("verdict") != "approved":
        issues.append(_v12_issue("P1", "v12_node_set_review_not_approved", node_id, str(artifact.get("verdict") or "")))
    expected_identity = {
        "agent_key": QUESTION_REVIEWER_AGENT_KEY,
        "phase": "node_global_finalizer",
        "artifact_role": "node_set_review",
        "contract_key": "math_question_bank_v12_node_set_global_finalizer",
        "contract_version": V12_GLOBAL_FINALIZER_CONTRACT_VERSION,
        "prompt_version_id": V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID,
        "response_schema_version": V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "semantic_evidence_version": V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION,
        "provider_mode": "live_model",
    }
    for key, value in expected_identity.items():
        if artifact.get(key) != value:
            issues.append(_v12_issue("P1", "v12_node_set_review_contract_identity_mismatch", node_id, key))
    for key in ("prompt_template_sha256", "rendered_prompt_sha256", "response_schema_sha256", "batch_raw_response_sha256"):
        if not str(artifact.get(key) or "").strip():
            issues.append(_v12_issue("P1", "v12_node_set_review_contract_identity_mismatch", node_id, key))
    if artifact.get("node_candidate_sha256") != v12_node_candidate_sha256(node_entry):
        issues.append(_v12_issue("P1", "v12_node_set_review_candidate_hash_mismatch", node_id, "node candidate hash mismatch"))
    scores = artifact.get("distribution_scores") if isinstance(artifact.get("distribution_scores"), dict) else {}
    for score_key in V12_NODE_SET_DISTRIBUTION_SCORE_KEYS:
        threshold = V12_SEMANTIC_GATE_MIN_SCORE if score_key in V12_CONTENT_REVIEW_SCORE_KEYS else V12_REVIEW_MIN_SCORE
        if _v12_score(scores, score_key) < threshold:
            issues.append(_v12_issue("P1", "v12_node_set_review_score_below_gate", node_id, score_key))
    if _v12_score(artifact, "confidence") < V12_NODE_SET_REVIEW_MIN_CONFIDENCE:
        issues.append(_v12_issue("P1", "v12_node_set_review_confidence_below_gate", node_id, "confidence"))
    if artifact.get("node_ux_verdict") != "approved":
        issues.append(_v12_issue("P1", "v12_node_set_ux_not_approved", node_id, str(artifact.get("node_ux_verdict") or "")))
    execution_policy = artifact.get("execution_policy") if isinstance(artifact.get("execution_policy"), dict) else {}
    expected_policy = {
        "node_review_concurrency": V12_NODE_SET_REVIEW_ACTIVATION_CONCURRENCY,
        "node_set_review_shard_size": V12_NODE_SET_REVIEW_SHARD_SIZE,
        "node_set_review_expected_shards": len(v12_expected_node_set_review_shards()),
        "global_finalizer_concurrency": 1,
    }
    for key, value in expected_policy.items():
        if execution_policy.get(key) != value:
            issues.append(_v12_issue("P1", "v12_node_set_review_bad_execution_policy", node_id, key))
    constituent_reviews = artifact.get("constituent_reviews") if isinstance(artifact.get("constituent_reviews"), list) else []
    aggregation = artifact.get("aggregation") if isinstance(artifact.get("aggregation"), dict) else {}
    if not constituent_reviews:
        issues.append(_v12_issue("P1", "v12_node_set_review_missing_constituent_reviews", node_id, "constituent_reviews"))
    expected_shards = v12_expected_node_set_review_shards()
    expected_slots = list(range(1, QUESTIONS_PER_GRAPH_NODE + 1))
    if len(constituent_reviews) != len(expected_shards):
        issues.append(_v12_issue("P1", "v12_node_set_review_bad_shard_coverage", node_id, f"count={len(constituent_reviews)}"))
    seen_slots: list[int] = []
    expected_graph_versions = {
        str(item.get("graph_version") or "")
        for item in (node_entry.get("items") or [])
        if isinstance(item, dict) and str(item.get("graph_version") or "")
    }
    if graph_version:
        expected_graph_versions.add(graph_version)
    for index, review in enumerate(constituent_reviews):
        if not isinstance(review, dict):
            issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, str(index)))
            continue
        expected_slots_for_index = expected_shards[index] if index < len(expected_shards) else []
        expected_shard_id = v12_node_set_review_shard_id(expected_slots_for_index)
        if review.get("agent_key") != QUESTION_REVIEWER_AGENT_KEY or review.get("phase") != "node_set_review":
            issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:agent_phase"))
        if review.get("artifact_role") != "node_set_focal_review_shard":
            issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:artifact_role"))
        expected_constituent_identity = {
            "contract_key": "math_question_bank_v12_node_set_focal_review",
            "contract_version": V12_NODE_SET_FOCAL_REVIEWER_CONTRACT_VERSION,
            "prompt_version_id": V12_NODE_SET_FOCAL_REVIEWER_PROMPT_VERSION_ID,
            "response_schema_version": V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION,
            "semantic_evidence_version": V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
            "provider_mode": "live_model",
        }
        for key, value in expected_constituent_identity.items():
            if review.get(key) != value:
                issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:{key}"))
        if expected_shard_id and review.get("shard_id") != expected_shard_id:
            issues.append(_v12_issue("P1", "v12_node_set_review_bad_shard_coverage", node_id, f"{index}:shard_id"))
        if review.get("node_candidate_sha256") != artifact.get("node_candidate_sha256"):
            issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:node_candidate_sha256"))
        slots = review.get("reviewed_slots") if isinstance(review.get("reviewed_slots"), list) else []
        if slots != expected_slots_for_index:
            issues.append(_v12_issue("P1", "v12_node_set_review_bad_shard_coverage", node_id, f"{index}:reviewed_slots={slots}"))
        seen_slots.extend(slot for slot in slots if isinstance(slot, int))
        output = review.get("review_output") if isinstance(review.get("review_output"), dict) else {}
        if output:
            if output.get("schema_version") != V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION:
                issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:output_schema_version"))
            if output.get("semantic_evidence_version") != V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION:
                issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:output_semantic_evidence_version"))
            if output.get("node_id") != node_id:
                issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:output_node_id"))
            if expected_graph_versions and str(output.get("graph_version") or "") not in expected_graph_versions:
                issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:output_graph_version"))
            if output.get("question_bank_version") not in {None, "", QUESTION_BANK_V12_VERSION}:
                issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:output_question_bank_version"))
            output_sha = _v12_digest_json(output)
            if review.get("review_output_sha256") != output_sha:
                issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:review_output_sha256"))
            semantic_errors = v12_node_set_review_output_semantic_evidence_errors(
                node_entry,
                reviewed_slots=expected_slots_for_index,
                output=output,
            )
            for slot, details in sorted(semantic_errors.items()):
                for detail in details:
                    issues.append(_v12_issue(
                        "P1",
                        "v12_node_set_slot_semantic_evidence_failed",
                        node_id,
                        f"{index}:slot={slot}:{detail}",
                    ))
            expected_semantic_digest = v12_node_set_constituent_semantic_evidence_sha256(node_entry, review)
            if review.get("semantic_evidence_sha256") != expected_semantic_digest:
                issues.append(_v12_issue(
                    "P1",
                    "v12_node_set_semantic_evidence_digest_mismatch",
                    node_id,
                    f"constituent:{index}",
                ))
        for key in ("reviewed_slots", "prompt_template_sha256", "rendered_prompt_sha256", "response_schema_sha256", "batch_raw_response_sha256"):
            if not review.get(key):
                issues.append(_v12_issue("P1", "v12_node_set_review_bad_constituent_review", node_id, f"{index}:{key}"))
    if sorted(seen_slots) != expected_slots or len(seen_slots) != len(set(seen_slots)):
        issues.append(_v12_issue("P1", "v12_node_set_review_bad_shard_coverage", node_id, f"coverage={seen_slots}"))
    expected_semantic_coverage = v12_node_set_semantic_evidence_coverage(node_entry, constituent_reviews)
    if artifact.get("semantic_evidence_coverage") != expected_semantic_coverage:
        issues.append(_v12_issue("P1", "v12_node_set_semantic_evidence_coverage_mismatch", node_id, "coverage"))
    if [entry.get("slot") for entry in expected_semantic_coverage] != expected_slots:
        issues.append(_v12_issue("P1", "v12_node_set_semantic_evidence_coverage_mismatch", node_id, "slots"))
    expected_constituent_semantic_hashes = [
        review.get("semantic_evidence_sha256") or ""
        for review in constituent_reviews
        if isinstance(review, dict)
    ]
    global_verifier = artifact.get("global_verifier") if isinstance(artifact.get("global_verifier"), dict) else {}
    expected_verifier_identity = {
        "agent_key": QUESTION_REVIEWER_AGENT_KEY,
        "phase": "node_global_verifier",
        "artifact_role": "node_set_global_verifier",
        "contract_key": "math_question_bank_v12_node_set_global_verifier",
        "contract_version": V12_NODE_SET_GLOBAL_VERIFIER_CONTRACT_VERSION,
        "prompt_version_id": V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_VERSION_ID,
        "response_schema_version": V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_VERSION,
        "semantic_evidence_version": V12_NODE_SET_GLOBAL_VERIFIER_SEMANTIC_EVIDENCE_VERSION,
        "provider_mode": "live_model",
        "prompt_template_sha256": V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_TEMPLATE_SHA256,
        "response_schema_sha256": V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_SHA256,
        "request_lineage_version": V12_NODE_SET_GLOBAL_VERIFIER_REQUEST_LINEAGE_VERSION,
    }
    if not global_verifier:
        issues.append(_v12_issue("P1", "v12_node_set_review_missing_global_verifier", node_id, "global_verifier"))
    for key, value in expected_verifier_identity.items():
        if global_verifier.get(key) != value:
            issues.append(_v12_issue("P1", "v12_node_set_global_verifier_identity_mismatch", node_id, key))
    for key in (
        "rendered_prompt_sha256",
        "batch_raw_response_sha256",
        "trusted_context_sha256",
        "untrusted_payload_sha256",
        "request_options_sha256",
        "request_input_sha256",
        "request_lineage_sha256",
    ):
        if not str(global_verifier.get(key) or "").strip():
            issues.append(_v12_issue("P1", "v12_node_set_global_verifier_identity_mismatch", node_id, key))
    if global_verifier.get("node_candidate_sha256") != v12_node_candidate_sha256(node_entry):
        issues.append(_v12_issue("P1", "v12_node_set_global_verifier_candidate_hash_mismatch", node_id, "node_candidate_sha256"))
    if global_verifier.get("constituent_semantic_evidence_sha256") != expected_constituent_semantic_hashes:
        issues.append(_v12_issue("P1", "v12_node_set_global_verifier_constituent_mismatch", node_id, "constituent hashes"))
    verifier_shards = (
        global_verifier.get("shard_artifacts")
        if isinstance(global_verifier.get("shard_artifacts"), list)
        else []
    )
    expected_verifier_shards = v12_expected_global_verifier_shards()
    top_level_verifier_route = {
        "model_provider": str(global_verifier.get("model_provider") or ""),
        "model_name": str(global_verifier.get("model_name") or ""),
        "model_alias": str(global_verifier.get("model_alias") or ""),
        "structured_json_mode": str(global_verifier.get("structured_json_mode") or ""),
    }
    if [
        list(shard.get("reviewed_slots") or [])
        for shard in verifier_shards
        if isinstance(shard, dict)
    ] != expected_verifier_shards:
        issues.append(_v12_issue(
            "P1",
            "v12_node_set_global_verifier_shard_coverage_mismatch",
            node_id,
            "shard coverage",
        ))
    verifier_shard_semantic_hashes: list[str] = []
    for index, shard in enumerate(verifier_shards):
        if not isinstance(shard, dict):
            issues.append(_v12_issue(
                "P1",
                "v12_node_set_global_verifier_shard_invalid",
                node_id,
                f"{index}:not_object",
            ))
            continue
        reviewed_slots = list(shard.get("reviewed_slots") or [])
        expected_identity = {
            "agent_key": QUESTION_REVIEWER_AGENT_KEY,
            "phase": "node_global_verifier",
            "artifact_role": "node_set_global_verifier_shard",
            "contract_key": "math_question_bank_v12_node_set_global_verifier",
            "contract_version": V12_NODE_SET_GLOBAL_VERIFIER_CONTRACT_VERSION,
            "prompt_version_id": V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_VERSION_ID,
            "response_schema_version": V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_VERSION,
            "semantic_evidence_version": V12_NODE_SET_GLOBAL_VERIFIER_SHARD_SEMANTIC_EVIDENCE_VERSION,
            "provider_mode": "live_model",
            "prompt_template_sha256": V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_TEMPLATE_SHA256,
            "response_schema_sha256": V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_SHA256,
            "request_lineage_version": V12_NODE_SET_GLOBAL_VERIFIER_REQUEST_LINEAGE_VERSION,
            "shard_id": v12_node_set_review_shard_id(reviewed_slots),
        }
        for field, expected in top_level_verifier_route.items():
            if shard.get(field) != expected:
                issues.append(_v12_issue(
                    "P1",
                    "v12_node_set_global_verifier_shard_route_mismatch",
                    node_id,
                    f"{index}:{field}",
                ))
        for field, expected in expected_identity.items():
            if shard.get(field) != expected:
                issues.append(_v12_issue(
                    "P1",
                    "v12_node_set_global_verifier_shard_invalid",
                    node_id,
                    f"{index}:{field}",
                ))
        shard_judgment = (
            shard.get("model_judgment_output")
            if isinstance(shard.get("model_judgment_output"), dict)
            else {}
        )
        classification_slots = [
            int(entry.get("slot") or 0)
            for entry in shard_judgment.get("item_classifications") or []
            if isinstance(entry, dict)
        ]
        if (
            shard_judgment.get("reviewed_slots") != reviewed_slots
            or classification_slots != reviewed_slots
            or len(classification_slots) != len(set(classification_slots))
            or shard.get("model_judgment_output_sha256")
            != _v12_digest_json(shard_judgment)
        ):
            issues.append(_v12_issue(
                "P1",
                "v12_node_set_global_verifier_shard_invalid",
                node_id,
                f"{index}:judgment",
            ))
        for detail in v12_global_model_judgment_binding_errors(node_entry, shard_judgment):
            issues.append(_v12_issue(
                "P1",
                "v12_node_set_global_verifier_shard_binding_invalid",
                node_id,
                f"{index}:{detail}",
            ))
        expected_shard_semantic = _v12_digest_json({
            "semantic_evidence_version": V12_NODE_SET_GLOBAL_VERIFIER_SHARD_SEMANTIC_EVIDENCE_VERSION,
            "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
            "constituent_semantic_evidence_sha256": expected_constituent_semantic_hashes,
            "reviewed_slots": reviewed_slots,
            "compact_index_sha256": shard.get("compact_index_sha256") or "",
            "model_judgment_output_sha256": shard.get("model_judgment_output_sha256") or "",
        })
        if shard.get("semantic_evidence_sha256") != expected_shard_semantic:
            issues.append(_v12_issue(
                "P1",
                "v12_node_set_global_verifier_shard_invalid",
                node_id,
                f"{index}:semantic_evidence_sha256",
            ))
        verifier_shard_semantic_hashes.append(
            str(shard.get("semantic_evidence_sha256") or "")
        )
    if (
        global_verifier.get("shard_policy_version")
        != V12_NODE_SET_GLOBAL_VERIFIER_SHARD_POLICY_VERSION
        or global_verifier.get("expected_shards") != expected_verifier_shards
        or global_verifier.get("shard_artifacts_sha256")
        != _v12_digest_json(verifier_shards)
        or global_verifier.get("shard_semantic_evidence_sha256s")
        != verifier_shard_semantic_hashes
        or global_verifier.get("shard_route_tuples")
        != v12_global_verifier_shard_route_tuples(verifier_shards)
        or global_verifier.get("shard_route_tuples_sha256")
        != _v12_digest_json(v12_global_verifier_shard_route_tuples(verifier_shards))
    ):
        issues.append(_v12_issue(
            "P1",
            "v12_node_set_global_verifier_shard_commitment_mismatch",
            node_id,
            "aggregate shard commitment",
        ))
    verifier_judgment = global_verifier.get("model_judgment_output") if isinstance(
        global_verifier.get("model_judgment_output"), dict
    ) else {}
    if global_verifier.get("model_judgment_output_sha256") != _v12_digest_json(verifier_judgment):
        issues.append(_v12_issue("P1", "v12_node_set_global_verifier_digest_mismatch", node_id, "model_judgment_output_sha256"))
    for detail in v12_global_model_judgment_errors(
        verifier_judgment,
        node_id=node_id,
        graph_version=str(verifier_judgment.get("graph_version") or ""),
    ):
        issues.append(_v12_issue("P1", "v12_node_set_global_verifier_invalid", node_id, detail))
    for detail in v12_global_model_judgment_binding_errors(node_entry, verifier_judgment):
        issues.append(_v12_issue("P1", "v12_node_set_global_verifier_binding_invalid", node_id, detail))
    try:
        expected_verifier_judgment = v12_aggregate_global_verifier_shard_judgments(
            node_entry,
            verifier_shards,
            graph_version=str(verifier_judgment.get("graph_version") or ""),
        )
    except ValueError as exc:
        issues.append(_v12_issue(
            "P1",
            "v12_node_set_global_verifier_aggregate_invalid",
            node_id,
            str(exc),
        ))
        expected_verifier_judgment = None
    if (
        expected_verifier_judgment is not None
        and verifier_judgment != expected_verifier_judgment
    ):
        issues.append(_v12_issue(
            "P1",
            "v12_node_set_global_verifier_aggregate_mismatch",
            node_id,
            "model_judgment_output",
        ))
    expected_verifier_aggregate_commitment = _v12_digest_json({
        "version": V12_NODE_SET_GLOBAL_VERIFIER_AGGREGATE_VERSION,
        "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
        "expected_shards": expected_verifier_shards,
        "shard_semantic_evidence_sha256s": verifier_shard_semantic_hashes,
        "shard_artifacts_sha256": global_verifier.get("shard_artifacts_sha256") or "",
        "shard_route_tuples_sha256": global_verifier.get("shard_route_tuples_sha256") or "",
        "model_judgment_output_sha256": global_verifier.get("model_judgment_output_sha256") or "",
        "request_lineage_sha256": global_verifier.get("request_lineage_sha256") or "",
    })
    if (
        global_verifier.get("aggregate_commitment_sha256")
        != expected_verifier_aggregate_commitment
    ):
        issues.append(_v12_issue(
            "P1",
            "v12_node_set_global_verifier_shard_commitment_mismatch",
            node_id,
            "aggregate_commitment_sha256",
        ))
    expected_verifier_semantic_sha256 = _v12_digest_json({
        "semantic_evidence_version": V12_NODE_SET_GLOBAL_VERIFIER_SEMANTIC_EVIDENCE_VERSION,
        "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
        "constituent_semantic_evidence_sha256": expected_constituent_semantic_hashes,
        "shard_semantic_evidence_sha256s": verifier_shard_semantic_hashes,
        "aggregate_commitment_sha256": global_verifier.get("aggregate_commitment_sha256") or "",
        "model_judgment_output_sha256": global_verifier.get("model_judgment_output_sha256") or "",
    })
    if global_verifier.get("semantic_evidence_sha256") != expected_verifier_semantic_sha256:
        issues.append(_v12_issue("P1", "v12_node_set_global_verifier_semantic_digest_mismatch", node_id, "semantic_evidence_sha256"))
    global_finalizer = artifact.get("global_finalizer") if isinstance(artifact.get("global_finalizer"), dict) else {}
    expected_global_identity = {
        "agent_key": QUESTION_REVIEWER_AGENT_KEY,
        "phase": "node_global_finalizer",
        "artifact_role": "node_set_global_finalizer",
        "contract_key": "math_question_bank_v12_node_set_global_finalizer",
        "contract_version": V12_GLOBAL_FINALIZER_CONTRACT_VERSION,
        "prompt_version_id": V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID,
        "response_schema_version": V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "semantic_evidence_version": V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION,
        "provider_mode": "live_model",
    }
    if not global_finalizer:
        issues.append(_v12_issue("P1", "v12_node_set_review_missing_global_finalizer", node_id, "global_finalizer"))
    for key, value in expected_global_identity.items():
        if global_finalizer.get(key) != value:
            issues.append(_v12_issue("P1", "v12_node_set_global_finalizer_identity_mismatch", node_id, key))
    expected_immutable_hashes = {
        "prompt_template_sha256": V12_NODE_SET_GLOBAL_FINALIZER_PROMPT_TEMPLATE_SHA256,
        "response_schema_sha256": V12_NODE_SET_GLOBAL_FINALIZER_RESPONSE_SCHEMA_SHA256,
        "request_lineage_version": V12_NODE_SET_GLOBAL_FINALIZER_REQUEST_LINEAGE_VERSION,
    }
    for key, value in expected_immutable_hashes.items():
        if global_finalizer.get(key) != value:
            issues.append(_v12_issue("P1", "v12_node_set_global_finalizer_identity_mismatch", node_id, key))
    for key in (
        "rendered_prompt_sha256",
        "batch_raw_response_sha256",
        "trusted_context_sha256",
        "untrusted_payload_sha256",
        "request_options_sha256",
        "request_input_sha256",
        "request_lineage_sha256",
    ):
        if not str(global_finalizer.get(key) or "").strip():
            issues.append(_v12_issue("P1", "v12_node_set_global_finalizer_identity_mismatch", node_id, key))
    if global_finalizer.get("node_candidate_sha256") != v12_node_candidate_sha256(node_entry):
        issues.append(_v12_issue("P1", "v12_node_set_global_finalizer_candidate_hash_mismatch", node_id, "node_candidate_sha256"))
    if global_finalizer.get("constituent_semantic_evidence_sha256") != expected_constituent_semantic_hashes:
        issues.append(_v12_issue("P1", "v12_node_set_global_finalizer_constituent_mismatch", node_id, "constituent hashes"))
    global_output = (
        global_finalizer.get("global_review_output")
        if isinstance(global_finalizer.get("global_review_output"), dict)
        else {}
    )
    if global_finalizer.get("global_review_output_sha256") != _v12_digest_json(global_output):
        issues.append(_v12_issue("P1", "v12_node_set_global_finalizer_output_digest_mismatch", node_id, "global_review_output_sha256"))
    model_judgment = (
        global_finalizer.get("model_judgment_output")
        if isinstance(global_finalizer.get("model_judgment_output"), dict)
        else {}
    )
    if global_finalizer.get("model_judgment_output_sha256") != _v12_digest_json(model_judgment):
        issues.append(_v12_issue("P1", "v12_node_set_global_model_judgment_digest_mismatch", node_id, "model_judgment_output_sha256"))
    for detail in v12_global_model_judgment_errors(
        model_judgment,
        node_id=node_id,
        graph_version=str(global_output.get("graph_version") or ""),
    ):
        issues.append(_v12_issue("P1", "v12_node_set_global_model_judgment_invalid", node_id, detail))
    for detail in v12_global_model_judgment_binding_errors(node_entry, model_judgment):
        issues.append(_v12_issue("P1", "v12_node_set_global_model_judgment_binding_invalid", node_id, detail))
    if model_judgment and v12_expand_global_model_judgment(
        node_entry,
        constituent_reviews,
        model_judgment,
        graph_version=str(global_output.get("graph_version") or ""),
    ) != global_output:
        issues.append(_v12_issue("P1", "v12_node_set_global_runtime_expansion_mismatch", node_id, "global_review_output"))
    expected_global_semantic_sha256 = _v12_digest_json({
        "semantic_evidence_version": V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION,
        "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
        "constituent_semantic_evidence_sha256": expected_constituent_semantic_hashes,
        "global_review_output_sha256": global_finalizer.get("global_review_output_sha256") or "",
    })
    if global_finalizer.get("semantic_evidence_sha256") != expected_global_semantic_sha256:
        issues.append(_v12_issue("P1", "v12_node_set_global_finalizer_semantic_digest_mismatch", node_id, "semantic_evidence_sha256"))
    verifier_output = v12_expand_global_model_judgment(
        node_entry,
        constituent_reviews,
        verifier_judgment,
        graph_version=str(global_output.get("graph_version") or ""),
    )
    reduced = v12_union_independent_global_reviews(
        node_entry,
        constituent_reviews,
        verifier_output,
        global_output,
    )
    for detail in reduced.get("errors") or []:
        issues.append(_v12_issue("P1", "v12_node_set_global_finalizer_output_failed", node_id, str(detail)))
    expected_aggregate = v12_node_set_review_aggregate_payload(
        node_entry=node_entry,
        shard_reviews=constituent_reviews,
        global_verifier_artifact=global_verifier,
        global_finalizer_artifact=global_finalizer,
        reduced=reduced,
    )
    expected_semantic_digest = v12_node_set_review_semantic_evidence_sha256(
        node_entry,
        constituent_reviews,
        global_finalizer,
        global_verifier,
    )
    if artifact.get("semantic_evidence_sha256") != expected_semantic_digest:
        issues.append(_v12_issue("P1", "v12_node_set_semantic_evidence_digest_mismatch", node_id, "aggregate"))
    if aggregation != expected_aggregate["aggregation"]:
        issues.append(_v12_issue("P1", "v12_node_set_review_aggregation_mismatch", node_id, "aggregation"))
    for key in (
        "verdict",
        "distribution_scores",
        "confidence",
        "duplicate_groups",
        "reasons",
        "canonical_repair_plan",
        "rejected_slots",
        "node_ux_verdict",
        "unprompted_slot_results",
        "instruction_voice_distribution",
        "repetitive_instruction_clusters",
        "overloaded_slots",
        "notation_failure_slots",
        "dignity_failure_slots",
        "ux_rejected_slots",
        "item_count",
        "node_local_mainline_count",
        "controlled_stretch_count",
        "invalid_difficulty_vector_slots",
        "gate_errors",
    ):
        reduced_key = "repair_instructions" if key == "canonical_repair_plan" else key
        if artifact.get(key) != reduced.get(reduced_key):
            issues.append(_v12_issue("P1", "v12_node_set_review_aggregation_mismatch", node_id, key))
    if artifact.get("global_review_output_sha256") != global_finalizer.get("global_review_output_sha256"):
        issues.append(_v12_issue("P1", "v12_node_set_review_aggregation_mismatch", node_id, "global_review_output_sha256"))
    for gate_error in reduced.get("gate_errors") or []:
        issues.append(_v12_issue("P1", "v12_node_set_ux_gate_failed", node_id, str(gate_error)))


def _v12_expected_node_set_review_shards() -> list[list[int]]:
    return v12_expected_node_set_review_shards()


def _v12_recompute_node_set_review_from_constituents(
    node_entry: dict[str, Any],
    constituent_reviews: list[dict[str, Any]],
    global_finalizer_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global_finalizer_artifact = global_finalizer_artifact if isinstance(global_finalizer_artifact, dict) else {}
    output = (
        global_finalizer_artifact.get("global_review_output")
        if isinstance(global_finalizer_artifact.get("global_review_output"), dict)
        else {}
    )
    return v12_reduce_node_set_v4(node_entry, constituent_reviews, output)


def v12_node_set_review_aggregate_payload(
    *,
    node_entry: dict[str, Any],
    shard_reviews: list[dict[str, Any]],
    global_finalizer_artifact: dict[str, Any],
    global_verifier_artifact: dict[str, Any] | None = None,
    reduced: dict[str, Any],
) -> dict[str, Any]:
    constituent_hashes = [
        str(review.get("review_output_sha256") or _v12_digest_json(review.get("output") or {}))
        for review in shard_reviews
        if isinstance(review, dict)
    ]
    reviewed_slots = sorted({
        int(slot)
        for review in shard_reviews
        if isinstance(review, dict)
        for slot in (review.get("reviewed_slots") or [])
        if isinstance(slot, int)
    })
    semantic_evidence_coverage = v12_node_set_semantic_evidence_coverage(node_entry, shard_reviews)
    semantic_evidence_sha256 = v12_node_set_review_semantic_evidence_sha256(
        node_entry,
        shard_reviews,
        global_finalizer_artifact,
        global_verifier_artifact,
    )
    payload = {
        "node_candidate_sha256": v12_node_candidate_sha256(node_entry),
        "shard_policy": {
            "shard_size": V12_NODE_SET_REVIEW_SHARD_SIZE,
            "expected_shard_count": len(v12_expected_node_set_review_shards()),
        },
        "constituent_hashes": constituent_hashes,
        "reviewed_slots": reviewed_slots,
        "global_finalizer_output_sha256": global_finalizer_artifact.get("global_review_output_sha256", ""),
        "global_verifier_semantic_evidence_sha256": (
            (global_verifier_artifact or {}).get("semantic_evidence_sha256", "")
        ),
        "verdict": reduced.get("verdict"),
        "distribution_scores": reduced.get("distribution_scores") or {},
        "confidence": reduced.get("confidence"),
        "duplicate_groups": reduced.get("duplicate_groups") or [],
        "reasons": reduced.get("reasons") or [],
        "repair_instruction_count": len(reduced.get("repair_instructions") or []),
        "semantic_evidence_version": V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION,
        "semantic_evidence_sha256": semantic_evidence_sha256,
        "semantic_evidence_coverage": semantic_evidence_coverage,
        "node_ux_verdict": reduced.get("node_ux_verdict"),
        "unprompted_slot_results": reduced.get("unprompted_slot_results") or [],
        "instruction_voice_distribution": reduced.get("instruction_voice_distribution") or [],
        "repetitive_instruction_clusters": reduced.get("repetitive_instruction_clusters") or [],
        "overloaded_slots": reduced.get("overloaded_slots") or [],
        "notation_failure_slots": reduced.get("notation_failure_slots") or [],
        "dignity_failure_slots": reduced.get("dignity_failure_slots") or [],
        "ux_rejected_slots": reduced.get("ux_rejected_slots") or [],
        "item_count": reduced.get("item_count"),
        "node_local_mainline_count": reduced.get("node_local_mainline_count"),
        "controlled_stretch_count": reduced.get("controlled_stretch_count"),
        "invalid_difficulty_vector_slots": reduced.get("invalid_difficulty_vector_slots") or [],
        "ux_gate_errors": reduced.get("gate_errors") or [],
    }
    aggregate_sha256 = _v12_digest_json(payload)
    return {
        "semantic_evidence_version": V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION,
        "semantic_evidence_sha256": semantic_evidence_sha256,
        "semantic_evidence_coverage": semantic_evidence_coverage,
        "node_ux_verdict": reduced.get("node_ux_verdict"),
        "unprompted_slot_results": reduced.get("unprompted_slot_results") or [],
        "instruction_voice_distribution": reduced.get("instruction_voice_distribution") or [],
        "repetitive_instruction_clusters": reduced.get("repetitive_instruction_clusters") or [],
        "overloaded_slots": reduced.get("overloaded_slots") or [],
        "notation_failure_slots": reduced.get("notation_failure_slots") or [],
        "dignity_failure_slots": reduced.get("dignity_failure_slots") or [],
        "ux_rejected_slots": reduced.get("ux_rejected_slots") or [],
        "item_count": reduced.get("item_count"),
        "node_local_mainline_count": reduced.get("node_local_mainline_count"),
        "controlled_stretch_count": reduced.get("controlled_stretch_count"),
        "invalid_difficulty_vector_slots": reduced.get("invalid_difficulty_vector_slots") or [],
        "gate_errors": reduced.get("gate_errors") or [],
        "aggregation": {
            "strategy": "v4_focal_evidence_plus_global_finalizer",
            "aggregate_sha256": aggregate_sha256,
            "constituent_count": len(shard_reviews),
            "shard_size": V12_NODE_SET_REVIEW_SHARD_SIZE,
            "expected_constituent_count": len(v12_expected_node_set_review_shards()),
            "constituent_hashes": constituent_hashes,
            "reviewed_slots": reviewed_slots,
            "global_finalizer_output_sha256": global_finalizer_artifact.get("global_review_output_sha256", ""),
            "global_verifier_semantic_evidence_sha256": (
                (global_verifier_artifact or {}).get("semantic_evidence_sha256", "")
            ),
        }
    }


def _v12_score(scores: dict[str, Any], key: str) -> float:
    try:
        return float(scores.get(key))
    except (TypeError, ValueError):
        return 0.0


def _v12_issue(severity: str, issue_type: str, node_id: str, detail: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "type": issue_type,
        "node_id": node_id,
        "detail": detail,
    }


def _v12_external_item_activation_issues(
    manifest: dict[str, Any],
    node: dict[str, Any],
    item: dict[str, Any],
) -> list[dict[str, Any]]:
    node_id = str(node.get("id") or "")
    item_id = str(item.get("id") or "")
    issues: list[dict[str, Any]] = []
    if manifest.get("schema_version") != QUESTION_BANK_V12_SCHEMA_VERSION:
        issues.append(_v12_issue("P0", "v12_schema_version_mismatch", node_id, item_id))
    if manifest.get("question_bank_version") != QUESTION_BANK_V12_VERSION:
        issues.append(_v12_issue("P0", "v12_question_bank_version_mismatch", node_id, item_id))
    if item.get("node_id") != node_id:
        issues.append(_v12_issue("P0", "v12_item_node_mismatch", node_id, item_id))
    slot = int(item.get("slot") or 0)
    expected_role = v12_slot_role_for_node(node, slot)
    if expected_role and item.get("slot_role") != expected_role:
        issues.append(_v12_issue("P1", "v12_slot_role_mismatch", node_id, item_id))
    for detail in v12_item_policy_errors(node, item):
        issues.append(_v12_issue("P1", "v12_item_policy_violation", node_id, f"{item_id}:{detail}"))
    for detail in _v12_difficulty_vector_errors(item):
        issues.append(_v12_issue("P1", "v12_invalid_difficulty_vector", node_id, f"{item_id}:{detail}"))
    allowed_tags = _v12_allowed_error_tags_for_node(node)
    for tag in item.get("target_error_tags") or []:
        if tag not in allowed_tags:
            issues.append(_v12_issue("P1", "v12_unknown_target_error_tag", node_id, f"{item_id}:{tag}"))
    allowed_rollbacks = set(_v12_allowed_rollback_nodes_for_node(node))
    for rollback_id in item.get("rollback_candidates") or []:
        if str(rollback_id) not in allowed_rollbacks:
            issues.append(_v12_issue("P1", "v12_illegal_rollback_candidate", node_id, f"{item_id}:{rollback_id}"))
    summer = node.get("summer_execution") if isinstance(node.get("summer_execution"), dict) else {}
    if bool(item.get("controlled_stretch")) and summer.get("mode") != "controlled_extension":
        issues.append(_v12_issue("P1", "v12_controlled_stretch_on_ineligible_node", node_id, item_id))
    if not str(item.get("prompt") or "").strip() or not str(item.get("expected_answer") or "").strip():
        issues.append(_v12_issue("P0", "v12_prompt_or_answer_missing", node_id, item_id))
    if len(item.get("solution_steps") or []) < 2:
        issues.append(_v12_issue("P0", "v12_solution_steps_too_thin", node_id, item_id))
    _validate_v12_designer_artifact(item, node_id=node_id, item_id=item_id, issues=issues)
    _validate_v12_item_review_artifact(item, node_id=node_id, item_id=item_id, issues=issues)
    return issues


def _v12_quality_from_reviewed_external_item(
    manifest: dict[str, Any],
    node: dict[str, Any],
    external_item: dict[str, Any],
    converted: dict[str, Any],
) -> dict[str, Any]:
    issues = _v12_external_item_activation_issues(manifest, node, external_item)
    blocking = [issue for issue in issues if issue.get("severity") in {"P0", "P1"}]
    if blocking:
        reasons = [f"{issue.get('type')}:{issue.get('detail', '')}" for issue in blocking]
        raise ValueError(f"V12 question item {external_item.get('id')} rejected by structured quality gate: {reasons}")
    review = external_item.get("review_artifact") if isinstance(external_item.get("review_artifact"), dict) else {}
    evidence = review.get("reviewer_evidence") if isinstance(review.get("reviewer_evidence"), dict) else {}
    semantic_evidence = review.get("semantic_evidence") if isinstance(review.get("semantic_evidence"), dict) else {}
    candidate_sha256 = v12_external_candidate_sha256(external_item)
    semantic_evidence_sha256 = v12_item_review_semantic_evidence_sha256(external_item, review)
    return {
        "contract_version": V12_ACTIVE_QUALITY_CONTRACT_VERSION,
        "quality_basis": V12_STRUCTURED_QUALITY_BASIS,
        "graph_version": str(manifest.get("graph_version") or ""),
        "question_bank_version": QUESTION_BANK_V12_VERSION,
        "review_status": "approved",
        "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
        "reviewer_contract_version": V12_REVIEWER_CONTRACT_VERSION,
        "reviewer_evidence": evidence,
        "semantic_evidence_version": V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "semantic_evidence_sha256": semantic_evidence_sha256,
        "external_candidate_sha256": candidate_sha256,
        "semantic_ux_approved": semantic_evidence.get("ux_verdict") == "approved",
        "age_floor": INCOMING_GRADE_7_AGE_FLOOR,
        "cognitive_level": _cognitive_level(str(converted.get("kind") or ""), str(converted.get("variant_level") or "")),
        "item_purpose": _item_purpose(str(converted.get("kind") or "")),
        "requires_reasoning": evidence.get("process_evidence_required") is True,
        "has_high_signal_structure": evidence.get("diagnostic_structure") is True,
        "picture_level_challenge_labels": picture_level_challenge_labels(converted),
        "problem_family_id": converted.get("problem_family_id", ""),
        "core_stem_id": converted.get("core_stem_id", ""),
        "node_alignment": converted.get("node_alignment", {}),
        "identity_basis": _identity_basis_for_review(converted),
        "requires_process_evidence": PROCESS_EVIDENCE_REQUIREMENTS,
        "no_mechanical_drill": evidence.get("not_mechanical_drill") is True,
        "instruction_voice_family": semantic_evidence.get("instruction_voice_family", ""),
        "response_moves": list(semantic_evidence.get("response_moves") or []),
        "criteria": [
            "v12_v4_structured_reviewer_evidence",
            "v12_v4_focal_and_global_node_review",
            "semantic_evidence_digest_bound",
            "incoming_grade_7_dignity",
            "rendered_notation_ready",
            "single_coherent_response_burden",
            "graph_node_bound",
        ],
        "rejection_reasons": [],
    }


def external_v12_item_to_question_item(
    manifest: dict[str, Any],
    node: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
    evidence = review.get("reviewer_evidence") if isinstance(review.get("reviewer_evidence"), dict) else {}
    if evidence.get("provenance_type") != V12_REVIEW_PROVENANCE:
        raise ValueError(f"V12 item {item.get('id')} lacks independent reviewer evidence")
    problem_family_id = _canonical_v12_identity_id(
        item.get("problem_family_id"),
        prefix="PF",
        fallback=str(item.get("id") or "item"),
    )
    core_stem_id = _canonical_v12_identity_id(
        item.get("core_stem_id"),
        prefix="CS",
        fallback=str(item.get("id") or "item"),
    )
    alignment = {
        "status": "claimed",
        "alignment_mode": "v12_external_reviewed_asset",
        "primary_node_id": node["id"],
        "primary_node_name": node.get("name", ""),
        "question_type": str(item.get("question_type") or item.get("slot_role") or ""),
        "problem_family_id": problem_family_id,
        "core_stem_id": core_stem_id,
        "reason": str(review.get("reasons", [""])[0] if isinstance(review.get("reasons"), list) and review.get("reasons") else "v12 independent review accepted node alignment"),
        "matched_terms": [node.get("name", ""), str(item.get("slot_role") or "")],
        "measured_capability": str(item.get("evidence_goal") or item.get("slot_role") or ""),
        "graph_seed_question_type": str(item.get("slot_role") or ""),
        "node_local_anchor": str(item.get("math_core_signature") or item.get("prompt") or "")[:160],
        "problem_family_basis": {"probe_family": str(item.get("evidence_goal") or item.get("slot_role") or "")},
        "core_stem_basis": {"core_fields": {"math_core_signature": str(item.get("math_core_signature") or core_stem_id)}},
    }
    source = {
        "type": "graph_generated",
        "external_source_type": V12_SOURCE_TYPE,
        "manifest_id": str(manifest.get("manifest_id") or ""),
        "manifest_question_bank_version": str(manifest.get("question_bank_version") or QUESTION_BANK_V12_VERSION),
        "graph_version": str(manifest.get("graph_version") or ""),
        "question_bank_version": str(manifest.get("question_bank_version") or QUESTION_BANK_V12_VERSION),
        "slot": int(item.get("slot") or 0),
        "slot_role": str(item.get("slot_role") or ""),
        "evidence_goal": str(item.get("evidence_goal") or ""),
        "elicitation_mode": str(item.get("elicitation_mode") or ""),
        "child_surface_design": item.get("child_surface_design") if isinstance(item.get("child_surface_design"), dict) else {},
        "intended_instruction_voice_family": str(item.get("intended_instruction_voice_family") or ""),
        "designer_artifact": item.get("designer_artifact") if isinstance(item.get("designer_artifact"), dict) else {},
        "review_artifact": review,
        "reviewer_evidence": evidence,
        "external_candidate_sha256": v12_external_candidate_sha256(item),
        "semantic_evidence_version": review.get("semantic_evidence_version", ""),
        "semantic_evidence_sha256": review.get("semantic_evidence_sha256", ""),
        "problem_family_id": problem_family_id,
        "core_stem_id": core_stem_id,
        "node_alignment": alignment,
        "problem_family_basis": alignment["problem_family_basis"],
        "core_stem_basis": alignment["core_stem_basis"],
        "node_local_anchor": alignment["node_local_anchor"],
        "production_pipeline": {
            "contract_version": "2026-07-12.math-qb-v12.external-seed.v4",
            "designer_agent": QUESTION_DESIGNER_AGENT_KEY,
            "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
            "workflow": ["external_v12_asset", "per_item_design", "independent_review", "activate_only_after_qa"],
            "manifest_only_review_is_forbidden": True,
        },
    }
    converted = {
        "id": str(item["id"]),
        "item_version": str(manifest.get("question_bank_version") or QUESTION_BANK_V12_VERSION),
        "source_type": "graph_generated",
        "graph_version": str(manifest.get("graph_version") or ""),
        "question_bank_version": str(manifest.get("question_bank_version") or QUESTION_BANK_V12_VERSION),
        "node_id": node["id"],
        "secondary_node_ids": [str(value) for value in item.get("secondary_node_ids") or []],
        "node_snapshot": {
            "id": node["id"],
            "name": node.get("name", ""),
            "stage": node.get("stage", ""),
            "domain": node.get("domain", ""),
            "priority": node.get("priority", ""),
            "summer_mode": _node_mode(node),
        },
        "kind": str(item.get("kind") or item.get("slot_role") or "v12_question"),
        "question_type": str(item.get("question_type") or item.get("slot_role") or ""),
        "variant_level": str(item.get("variant_level") or "L2"),
        "evidence_goal": str(item.get("evidence_goal") or item.get("slot_role") or ""),
        "elicitation_mode": str(item.get("elicitation_mode") or ""),
        "child_surface_design": item.get("child_surface_design") if isinstance(item.get("child_surface_design"), dict) else {},
        "intended_instruction_voice_family": str(item.get("intended_instruction_voice_family") or ""),
        "difficulty_vector": item.get("difficulty_vector") if isinstance(item.get("difficulty_vector"), dict) else {},
        "prompt": str(item.get("prompt") or ""),
        "answer_format": str(item.get("answer_format") or "关键步骤 + 答案 + 检验"),
        "expected_answer": str(item.get("expected_answer") or ""),
        "accepted_alternatives": list(item.get("accepted_alternatives") or []),
        "rubric": item.get("rubric") if isinstance(item.get("rubric"), list) else BASE_RUBRIC,
        "solution_steps": list(item.get("solution_steps") or []),
        "target_error_tags": [tag for tag in item.get("target_error_tags") or ["general"] if tag in CANONICAL_ERROR_TAGS] or ["general"],
        "rollback_candidates": [str(value) for value in item.get("rollback_candidates") or []],
        "rollback_candidate_relations": item.get("rollback_candidate_relations") if isinstance(item.get("rollback_candidate_relations"), list) else [],
        "estimated_minutes": _safe_estimated_minutes(item.get("estimated_minutes", 5)),
        "parent_observation": "v12 外置题库逐题审题通过；观察孩子是否能给出关系、过程和检验。",
        "problem_family_id": problem_family_id,
        "core_stem_id": core_stem_id,
        "node_alignment": alignment,
        "source": source,
    }
    interaction_schema = normalize_question_interaction_schema(item.get("interaction_schema"))
    if interaction_schema:
        converted["interaction_schema"] = interaction_schema
    quality = _v12_quality_from_reviewed_external_item(manifest, node, item, converted)
    converted["quality"] = quality
    converted["cognitive_level"] = quality["cognitive_level"]
    converted["item_purpose"] = quality["item_purpose"]
    converted["requires_reasoning"] = quality["requires_reasoning"]
    converted["challenge_profile"] = {
        "picture_level": bool(quality["picture_level_challenge_labels"]),
        "labels": quality["picture_level_challenge_labels"],
    }
    converted["review_agent_check"] = {
        "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
        "status": quality["review_status"],
        "rejection_reasons": quality["rejection_reasons"],
    }
    return converted


def _canonical_v12_identity_id(value: Any, *, prefix: str, fallback: str) -> str:
    raw = str(value or "").strip()
    expected_prefix = f"{prefix}-"
    if raw.startswith(expected_prefix):
        return raw
    normalized = _safe_id(raw) or _safe_id(fallback) or "ITEM"
    return f"{prefix}-V12-{normalized}"


def apply_question_lineage(
    item: dict[str, Any],
    *,
    graph_version: str,
    question_bank_version: str = QUESTION_BANK_VERSION,
) -> dict[str, Any]:
    """Attach authoritative graph/question-bank lineage without changing item semantics."""
    if not graph_version:
        return item
    source_type = item.get("source_type") or item.get("source", {}).get("type")
    if source_type not in {"graph_generated", "evolved"}:
        return item
    item["graph_version"] = graph_version
    item["question_bank_version"] = question_bank_version
    source = item.setdefault("source", {})
    if isinstance(source, dict):
        source["graph_version"] = graph_version
        source["question_bank_version"] = question_bank_version
    quality = item.get("quality")
    if isinstance(quality, dict):
        quality["graph_version"] = graph_version
        quality["question_bank_version"] = question_bank_version
    evidence = source.get("reviewer_evidence") if isinstance(source, dict) else None
    if isinstance(evidence, dict):
        evidence["graph_version"] = graph_version
        evidence["question_bank_version"] = question_bank_version
    design_intent = item.get("design_intent")
    if isinstance(design_intent, dict):
        design_intent["graph_version"] = graph_version
        design_intent["question_bank_version"] = question_bank_version
        claims = design_intent.get("evidence_claims")
        if isinstance(claims, dict):
            claims["graph_version"] = graph_version
            claims["question_bank_version"] = question_bank_version
    return item


class QuestionSpecLoader:
    """Stage-1 v2 seam for future question specs; reviewer evidence is authoritative."""

    standards_path = "data/question_specs/math_question_standards_v1.md"
    families_path = "data/question_specs/question_families_v1.json"
    calibration_path = "data/question_specs/seed_problem_calibration_v1.jsonl"
    python_gate_authoritative = False

    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "enabled": False,
            "python_gate_authoritative": cls.python_gate_authoritative,
            "structured_reviewer_evidence_required": True,
            "planned_paths": {
                "standards": cls.standards_path,
                "families": cls.families_path,
                "calibration": cls.calibration_path,
            },
            "parity_required_before_activation": True,
        }


def _validated_support_routing_context(
    conn,
    *,
    flow_id: str,
    node_id: str,
    question_bank_version: str,
    requested_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context = requested_context if isinstance(requested_context, dict) else {}
    assessment_id = str(context.get("source_assessment_id") or "").strip()
    assessment_digest = str(
        context.get("source_assessment_digest_sha256") or ""
    ).strip()
    attempt_id = str(context.get("source_attempt_id") or "").strip()
    source_item_id = str(context.get("source_item_id") or "").strip()
    if not all(
        (flow_id, assessment_id, assessment_digest, attempt_id, source_item_id)
    ):
        raise ValueError(
            "targeted support requires an accepted assessment routing receipt"
        )
    row = conn.execute(
        """
        select
          assessment.id as assessment_id,
          assessment.attempt_id,
          assessment.assessment_digest_sha256,
          assessment.question_id as assessment_question_id,
          assessment.question_item_version,
          assessment.criterion_judgments_json,
          assessment.question_passed,
          assessment.status as assessment_status,
          attempt.node_id,
          attempt.question_id as attempt_question_id,
          attempt.question_bank_version,
          attempt.evidence_status,
          step.flow_id
        from attempt_assessments assessment
        join attempts attempt on attempt.id = assessment.attempt_id
        join flow_steps step on step.id = attempt.flow_step_id
        where assessment.id = ?
        """,
        (assessment_id,),
    ).fetchone()
    if not row:
        raise ValueError("targeted support routing receipt is unknown")
    if (
        str(row["assessment_status"] or "") != "accepted"
        or str(row["evidence_status"] or "") != "active"
        or str(row["flow_id"] or "") != flow_id
        or str(row["attempt_id"] or "") != attempt_id
        or str(row["assessment_digest_sha256"] or "") != assessment_digest
        or str(row["assessment_question_id"] or "") != source_item_id
        or str(row["attempt_question_id"] or "") != source_item_id
        or str(row["question_item_version"] or "") != question_bank_version
        or str(row["question_bank_version"] or "") != question_bank_version
        or str(row["node_id"] or "") != node_id
        or bool(row["question_passed"])
        or str(context.get("node_state") or "") != "weak"
    ):
        raise ValueError("targeted support routing receipt does not match the flow")
    try:
        judgments = json.loads(str(row["criterion_judgments_json"] or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("targeted support assessment criteria are unreadable") from exc
    criterion_statuses = {
        str(judgment.get("criterion_key") or "").strip(): str(
            judgment.get("status") or ""
        ).strip()
        for judgment in judgments
        if isinstance(judgment, dict)
        and str(judgment.get("criterion_key") or "").strip()
    }
    if not criterion_statuses:
        raise ValueError("targeted support assessment has no criterion evidence")
    return {
        "source_assessment_id": assessment_id,
        "source_assessment_digest_sha256": assessment_digest,
        "source_attempt_id": attempt_id,
        "source_item_id": source_item_id,
        "criterion_statuses": criterion_statuses,
        "node_state": "weak",
    }


class QuestionBankService:
    """v3 metadata-only candidate packet skeleton for planner hot path."""

    packet_schema_version = "2026-07-11.v5.planner-candidate-packet.v1"

    @classmethod
    def candidate_packet_for_node(
        cls,
        conn,
        *,
        node_id: str,
        graph_version: str,
        question_bank_version: str,
        required_purpose: str,
        flow_id: str = "",
        flow_revision: int = 0,
        source_review_target_id: str = "",
        limit: int = 8,
        exclusions: dict[str, Any] | None = None,
        selection_intent: str = "general",
        next_evidence_goal: str = "",
        learner_status: str = "",
        prerequisite_ready: bool = False,
        support_routing_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        question_bank_version = str(question_bank_version or "").strip()
        if not question_bank_version:
            raise ValueError("candidate packet requires an explicit question-bank version")
        required_purpose = str(required_purpose or "").strip()
        if required_purpose not in {"teaching", "practice", "diagnostic"}:
            raise ValueError(
                "candidate packet requires purpose teaching, practice, or diagnostic"
            )
        ledger_rows = conn.execute(
            """
            select id, question_bank_version, graph_version, manifest_sha256, status
            from question_bank_version_ledger
            where question_bank_version = ?
            order by created_at desc, id desc
            """,
            (question_bank_version,),
        ).fetchall()
        if len(ledger_rows) != 1:
            raise ValueError(
                "candidate packet requires exactly one known question-bank ledger row"
            )
        ledger = ledger_rows[0]
        if str(ledger["status"] or "") not in {"active", "superseded"}:
            raise ValueError(
                "candidate packet question-bank version is not available to a learning flow"
            )
        if str(ledger["graph_version"] or "") != str(graph_version or ""):
            raise ValueError(
                "candidate packet graph version does not match question-bank ledger"
            )
        trusted_support_routing_context = None
        if selection_intent == "targeted_support_repair":
            trusted_support_routing_context = _validated_support_routing_context(
                conn,
                flow_id=str(flow_id or ""),
                node_id=str(node_id or ""),
                question_bank_version=question_bank_version,
                requested_context=support_routing_context,
            )
        limit = max(0, min(int(limit or 0), 8))
        filter_summary = {
            "active_rows_seen": 0,
            "excluded_stale": 0,
            "excluded_inactive": 0,
            "excluded_duplicate": 0,
            "excluded_problem_instance_duplicate": 0,
            "excluded_cooldown": 0,
            "excluded_problem_instance_cooldown": 0,
            "excluded_mastered_extra": 0,
            "excluded_missing_lineage": 0,
            "excluded_intent_role_mismatch": 0,
            "excluded_purpose_mismatch": 0,
            "excluded_support_routing_mismatch": 0,
        }
        exclusions = exclusions or {}
        recent_question_ids = set(exclusions.get("recent_question_ids") or [])
        recent_problem_instance_ids = set(exclusions.get("recent_problem_instance_ids") or [])
        mastered_node_ids = set(exclusions.get("mastered_node_ids") or [])
        rows = conn.execute(
            """
            select q.*, r.id as review_record_id, r.reviewer_run_id, r.review_contract_version
            from question_items q
            left join question_review_records r
              on r.question_id = q.id
             and r.item_version = q.item_version
             and r.source_type = q.source_type
             and r.review_status = 'approved'
             and r.active_eligible = 1
            where q.node_id = ?
            order by q.item_version desc, q.id
            limit 200
            """,
            (node_id,),
        ).fetchall()
        prefiltered: list[dict[str, Any]] = []
        from . import db as db_module

        for row in rows:
            item = _row_to_candidate_item(row)
            if not is_item_approved_for_active_use(item):
                filter_summary["excluded_inactive"] += 1
                continue
            filter_summary["active_rows_seen"] += 1
            try:
                active_use_question = db_module.get_question(conn, item["id"])
            except KeyError:
                filter_summary["excluded_missing_lineage"] += 1
                continue
            if not db_module.question_review_record_allows_active_use(conn, active_use_question, row["review_record_id"]):
                filter_summary["excluded_missing_lineage"] += 1
                continue
            lineage_status = _candidate_lineage_status(item, row, graph_version, question_bank_version)
            if lineage_status == "stale":
                filter_summary["excluded_stale"] += 1
                continue
            if lineage_status == "missing_lineage":
                filter_summary["excluded_missing_lineage"] += 1
                continue
            if item["id"] in recent_question_ids:
                filter_summary["excluded_cooldown"] += 1
                continue
            problem_instance_id = str(item.get("problem_instance_id") or "")
            if problem_instance_id and problem_instance_id in recent_problem_instance_ids:
                filter_summary["excluded_problem_instance_cooldown"] += 1
                continue
            if item.get("node_id") in mastered_node_ids:
                filter_summary["excluded_mastered_extra"] += 1
                continue
            usage_policy = db_module.active_question_usage_policy(
                conn,
                item["id"],
                item_version=item["item_version"],
            )
            allowed_purposes = list((usage_policy or {}).get("allowed_purposes") or [])
            support_only = bool((usage_policy or {}).get("support_only"))
            if (
                (support_only and required_purpose != "teaching")
                or (required_purpose and required_purpose not in allowed_purposes)
            ):
                filter_summary["excluded_purpose_mismatch"] += 1
                continue
            matched_support_route: dict[str, Any] | None = None
            if support_only:
                if selection_intent != "targeted_support_repair":
                    filter_summary["excluded_intent_role_mismatch"] += 1
                    continue
                matched_support_route = question_usage.matching_support_route(
                    usage_policy or {},
                    trusted_support_routing_context,
                )
                if matched_support_route is None:
                    filter_summary["excluded_support_routing_mismatch"] += 1
                    continue
            candidate = _candidate_metadata_row(
                item,
                row,
                graph_version,
                question_bank_version,
            )
            candidate["allowed_purposes"] = allowed_purposes
            candidate["usage_policy_digest_sha256"] = str(
                (usage_policy or {}).get("policy_digest_sha256") or ""
            )
            candidate["support_only"] = support_only
            if matched_support_route is not None:
                candidate["matched_support_route"] = matched_support_route
            prefiltered.append(candidate)
        ranked_candidates: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
        for index, candidate in enumerate(prefiltered):
            if not _candidate_allowed_for_intent(
                candidate,
                selection_intent=selection_intent,
                next_evidence_goal=next_evidence_goal,
                learner_status=learner_status,
                prerequisite_ready=prerequisite_ready,
            ):
                filter_summary["excluded_intent_role_mismatch"] += 1
                continue
            ranked_candidates.append((
                _candidate_intent_rank(
                    candidate,
                    selection_intent=selection_intent,
                    next_evidence_goal=next_evidence_goal,
                    learner_status=learner_status,
                    prerequisite_ready=prerequisite_ready,
                    original_index=index,
                ),
                candidate,
            ))
        ranked_candidates.sort(key=lambda item: item[0])
        candidates: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()
        seen_problem_instance_ids: set[str] = set()
        for _rank, candidate in ranked_candidates:
            problem_instance_id = str(candidate.get("problem_instance_id") or "")
            if problem_instance_id and problem_instance_id in seen_problem_instance_ids:
                filter_summary["excluded_problem_instance_duplicate"] += 1
                continue
            signature = str(
                candidate.get("variant_signature")
                or candidate.get("question_id")
                or ""
            )
            if signature and signature in seen_signatures:
                filter_summary["excluded_duplicate"] += 1
                continue
            if problem_instance_id:
                seen_problem_instance_ids.add(problem_instance_id)
            if signature:
                seen_signatures.add(signature)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        identity_material = {
            "flow_id": flow_id,
            "flow_revision": int(flow_revision or 0),
            "source_review_target_id": source_review_target_id,
            "node_id": node_id,
            "graph_version": graph_version,
            "question_bank_version": question_bank_version,
            "question_bank_ledger_id": str(ledger["id"] or ""),
            "question_bank_manifest_sha256": str(
                ledger["manifest_sha256"] or ""
            ),
            "selection_intent": selection_intent,
            "next_evidence_goal": next_evidence_goal,
            "learner_status": learner_status,
            "prerequisite_ready": bool(prerequisite_ready),
            "required_purpose": required_purpose,
            "support_routing_context": trusted_support_routing_context or {},
        }
        packet = {
            "packet_id": "CP-" + hashlib.sha256(
                json.dumps(identity_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:12],
            "packet_schema_version": cls.packet_schema_version,
            "legacy_packet_schema_version": "2026-07-10.v3.candidate-packet",
            "graph_version": graph_version,
            "question_bank_version": question_bank_version,
            "question_bank_ledger_id": str(ledger["id"] or ""),
            "question_bank_manifest_sha256": str(
                ledger["manifest_sha256"] or ""
            ),
            "target_node_id": node_id,
            "flow_id": flow_id,
            "flow_revision": int(flow_revision or 0),
            "source_review_target_id": source_review_target_id,
            "candidate_count": len(candidates),
            "filter_summary": filter_summary,
            "selection_intent": selection_intent,
            "next_evidence_goal": next_evidence_goal,
            "learner_status": learner_status,
            "prerequisite_ready": bool(prerequisite_ready),
            "required_purpose": required_purpose,
            "support_routing_context_digest_sha256": (
                question_usage.canonical_sha256(trusted_support_routing_context)
                if trusted_support_routing_context
                else ""
            ),
            "candidates": candidates,
        }
        packet["packet_hash"] = hashlib.sha256(
            json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return packet

    candidate_packet = candidate_packet_for_node


def _row_to_candidate_item(row) -> dict[str, Any]:
    raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
    item = {
        **raw,
        "id": row["id"],
        "item_version": row["item_version"],
        "source_type": row["source_type"],
        "node_id": row["node_id"],
        "kind": row["kind"],
        "question_type": row["question_type"],
        "variant_level": row["variant_level"],
        "error_tags": json.loads(row["error_tags_json"] or "[]"),
    }
    return item


def _candidate_lineage_status(item: dict[str, Any], row, graph_version: str, question_bank_version: str) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    item_graph_version = str(item.get("graph_version") or source.get("graph_version") or quality.get("graph_version") or "")
    item_bank_version = str(item.get("question_bank_version") or source.get("question_bank_version") or item.get("item_version") or "")
    if not item_graph_version or not item_bank_version or not row["review_record_id"] or not row["reviewer_run_id"]:
        return "missing_lineage"
    if item_graph_version != graph_version or item_bank_version != question_bank_version:
        return "stale"
    return "current"


def _candidate_metadata_row(item: dict[str, Any], row, graph_version: str, question_bank_version: str) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    slot_role = _candidate_slot_role(item)
    evidence_role = _candidate_evidence_role(item, slot_role)
    controlled_stretch = bool(
        item.get("controlled_stretch")
        or source.get("controlled_stretch")
        or quality.get("controlled_extension_only")
        or source.get("usage_scope") == "controlled_extension_only"
    )
    age_floor = str(item.get("age_floor") or quality.get("age_floor") or "incoming_grade_7")
    dignity_profile = {
        "age_floor": age_floor,
        "not_mechanical_drill": bool(quality.get("not_mechanical_drill", quality.get("no_mechanical_drill", True))),
        "incoming_grade_7_ready": bool(quality.get("incoming_grade_7_ready", True)),
    }
    return {
        "question_id": item["id"],
        "node_id": item["node_id"],
        "graph_version": graph_version,
        "item_version": item["item_version"],
        "review_record_id": row["review_record_id"],
        "slot": item.get("slot") or source.get("slot"),
        "slot_role": slot_role,
        "evidence_role": evidence_role,
        "kind": str(item.get("kind") or slot_role or "legacy_question"),
        "variant_level": str(item.get("variant_level") or ""),
        "selection_priority": int(item.get("selection_priority") or 0),
        "question_family": str(item.get("problem_family_id") or source.get("problem_family_id") or item.get("kind") or ""),
        "problem_instance_id": str(item.get("problem_instance_id") or source.get("problem_instance_id") or ""),
        "variant_signature": str(item.get("variant_signature") or item.get("core_stem_id") or item["id"]),
        "difficulty_vector": item.get("difficulty_vector") or {
            "variant_level": item.get("variant_level"),
            "kind": item.get("kind"),
        },
        "evidence_goal": str(item.get("evidence_goal") or source.get("evidence_goal") or item.get("question_type") or ""),
        "target_error_tags": list(item.get("target_error_tags") or item.get("error_tags") or []),
        "requires_reasoning": bool(quality.get("requires_reasoning", True)),
        "controlled_stretch": controlled_stretch,
        "age_floor": age_floor,
        "dignity_profile": dignity_profile,
        "last_used_at": None,
        "why_candidate": "current_lineage_active_use_metadata",
        "filter_summary": {"lineage_status": "current", "metadata_only": True},
        "active_use_proof": {
            "active_eligible": True,
            "reviewer_agent_key": QUESTION_REVIEWER_AGENT_KEY,
            "reviewer_run_id": row["reviewer_run_id"],
            "review_contract_version": row["review_contract_version"],
        },
        "question_bank_version": question_bank_version,
        "lineage_status": "current",
    }


TRANSFER_SLOT_ROLES = {
    "near_transfer",
    "integrated_transfer",
    "multi_representation",
    "alternative_method",
    "model_selection",
    "summary_transfer_check",
}
STRETCH_SLOT_ROLES = {"stretch_readiness_check", "controlled_stretch"}
TRANSFER_QUESTION_KINDS = {
    "variant",
    "transfer_retest",
    "near_transfer",
    "integrated_transfer",
    "multi_representation",
    "two_method_compare",
    "model_selection",
    "reverse_reasoning",
}
STRETCH_QUESTION_KINDS = {"stretch_transfer", "controlled_stretch"}
TRANSFER_VARIANT_LEVELS = {"transfer_retest", "near_transfer"}
STRETCH_VARIANT_LEVELS = {"stretch_readiness_check", "controlled_stretch"}
TRANSFER_EVIDENCE_ROLES = {
    "transfer",
    "near_transfer",
    "integrated_transfer",
    "multi_representation",
    "alternative_method",
    "summary_transfer_check",
}
STRETCH_EVIDENCE_ROLES = {"stretch_readiness", "picture_level_extension"}
CONCEPT_BOUNDARY_SLOT_ROLES = {
    "concept_boundary",
    "misconception_boundary",
    "essence_model",
}
INITIAL_HIGH_DISCRIMINATION_ROLES = {
    "necessary_condition",
    "misconception_boundary",
    "concept_boundary",
    "multi_representation",
    "representation_translation",
    "near_transfer",
    "integrated_transfer",
    "model_selection",
}
INITIAL_EXCLUDED_ROLES = {"concept_boundary", "essence_model", "wrong_solution_repair"}
TEACHING_CONTEXT_SLOT_ROLES = {
    "essence_model",
    "standard_model",
    "standard_example",
    "core_representation",
    "representation_translation",
    "multi_representation",
    "concept_boundary",
    "misconception_boundary",
    "model_selection",
    "necessary_condition",
    "calculation_symbol_precision",
    "inverse_check",
    "legacy_mainline",
}
REPAIR_SLOT_ROLES = {
    "wrong_solution_repair",
    "necessary_condition",
    "prerequisite_probe",
    "calculation_symbol_precision",
}
SAME_STRUCTURE_SLOT_ROLES = {
    "same_structure_confirmation",
    "standard_model",
    "standard_example",
    "wrong_solution_repair",
    "inverse_check",
    "calculation_symbol_precision",
    "expression_notation",
}


def _candidate_slot_role(item: dict[str, Any]) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    role = str(
        item.get("slot_role")
        or source.get("slot_role")
        or item.get("evidence_role")
        or source.get("evidence_role")
        or ""
    )
    if role:
        return role
    inferred = _legacy_candidate_slot_role(item)
    if inferred:
        return inferred
    return "legacy_mainline"


def _legacy_candidate_slot_role(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "").strip()
    variant_level = str(item.get("variant_level") or "").strip()
    kind_map = {
        "concept_boundary": "concept_boundary",
        "essence_model": "essence_model",
        "standard_model": "standard_model",
        "standard_example": "standard_example",
        "same_structure_confirmation": "same_structure_confirmation",
        "same_structure_retest": "same_structure_confirmation",
        "check_strategy": "inverse_check",
        "communication": "standard_example",
        "essence_check": "essence_model",
        "explanation_only": "essence_model",
        "misconception_probe": "misconception_boundary",
        "boundary_case": "concept_boundary",
        "variant": "near_transfer",
        "transfer_retest": "near_transfer",
        "near_transfer": "near_transfer",
        "integrated_transfer": "integrated_transfer",
        "representation": "multi_representation",
        "multi_representation": "multi_representation",
        "model_selection": "model_selection",
        "reverse_reasoning": "alternative_method",
        "alternative_method": "alternative_method",
        "error_spotting": "wrong_solution_repair",
        "self_correction": "wrong_solution_repair",
        "wrong_solution_repair": "wrong_solution_repair",
        "missing_condition": "necessary_condition",
        "necessary_condition": "necessary_condition",
        "symbol_unit_audit": "calculation_symbol_precision",
        "estimation_modeling": "model_selection",
        "two_method_compare": "alternative_method",
        "prerequisite_probe": "prerequisite_probe",
        "stretch_transfer": "stretch_readiness_check",
        "controlled_stretch": "controlled_stretch",
    }
    if kind in kind_map:
        return kind_map[kind]
    variant_level_map = {
        "standard_example": "standard_example",
        "standard_model": "standard_model",
        "same_structure_confirmation": "same_structure_confirmation",
        "transfer_retest": "near_transfer",
        "near_transfer": "near_transfer",
        "stretch_readiness_check": "stretch_readiness_check",
        "controlled_stretch": "controlled_stretch",
    }
    if variant_level in variant_level_map:
        return variant_level_map[variant_level]
    return ""


def _candidate_evidence_role(item: dict[str, Any], slot_role: str) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    node_alignment = (
        item.get("node_alignment")
        if isinstance(item.get("node_alignment"), dict)
        else source.get("node_alignment")
        if isinstance(source.get("node_alignment"), dict)
        else quality.get("node_alignment")
        if isinstance(quality.get("node_alignment"), dict)
        else {}
    )
    problem_family_basis = (
        source.get("problem_family_basis")
        if isinstance(source.get("problem_family_basis"), dict)
        else {}
    )
    reviewer_evidence = (
        quality.get("reviewer_evidence")
        if isinstance(quality.get("reviewer_evidence"), dict)
        else {}
    )
    role = str(
        source.get("evidence_role")
        or item.get("evidence_role")
        or node_alignment.get("alignment_mode")
        or problem_family_basis.get("evidence_role")
        or reviewer_evidence.get("evidence_role")
        or ""
    )
    if role:
        return role
    if slot_role in STRETCH_SLOT_ROLES or bool(item.get("controlled_stretch")):
        return "stretch_readiness"
    if slot_role in TRANSFER_SLOT_ROLES:
        return "transfer"
    if slot_role in REPAIR_SLOT_ROLES:
        return "repair"
    if slot_role in CONCEPT_BOUNDARY_SLOT_ROLES:
        return "concept_boundary"
    if slot_role == "legacy_mainline":
        return "direct"
    return "direct"


def candidate_supports_transfer(candidate: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict):
        raise TypeError("candidate role metadata must be a mapping")
    return bool(
        str(candidate.get("slot_role") or "") in TRANSFER_SLOT_ROLES
        or str(candidate.get("evidence_role") or "")
        in TRANSFER_EVIDENCE_ROLES
        or str(candidate.get("kind") or "") in TRANSFER_QUESTION_KINDS
        or str(candidate.get("variant_level") or "")
        in TRANSFER_VARIANT_LEVELS
    )


def candidate_supports_stretch(candidate: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict):
        raise TypeError("candidate role metadata must be a mapping")
    role = str(candidate.get("slot_role") or "")
    evidence_role = str(candidate.get("evidence_role") or "")
    return (
        candidate.get("controlled_stretch") is True
        or role in STRETCH_SLOT_ROLES
        or evidence_role in STRETCH_EVIDENCE_ROLES
        or str(candidate.get("kind") or "") in STRETCH_QUESTION_KINDS
        or str(candidate.get("variant_level") or "")
        in STRETCH_VARIANT_LEVELS
    )


def _candidate_is_stretch(candidate: dict[str, Any]) -> bool:
    return candidate_supports_stretch(candidate)


def question_is_transfer_or_stretch(question: dict[str, Any]) -> bool:
    if not isinstance(question, dict):
        raise TypeError("question role metadata must be a mapping")
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    source = (
        question.get("source")
        if isinstance(question.get("source"), dict)
        else {}
    )
    kinds = {
        str(question.get("kind") or ""),
        str(raw.get("kind") or ""),
        str(source.get("kind") or ""),
    }
    variant_levels = {
        str(question.get("variant_level") or ""),
        str(raw.get("variant_level") or ""),
        str(source.get("variant_level") or ""),
    }
    slot_roles = {
        str(raw.get("slot_role") or ""),
        str(source.get("slot_role") or ""),
    }
    evidence_roles = {
        str(raw.get("evidence_role") or ""),
        str(source.get("evidence_role") or ""),
    }
    return bool(
        kinds.intersection(TRANSFER_QUESTION_KINDS | STRETCH_QUESTION_KINDS)
        or variant_levels.intersection(
            TRANSFER_VARIANT_LEVELS | STRETCH_VARIANT_LEVELS
        )
        or slot_roles.intersection(TRANSFER_SLOT_ROLES | STRETCH_SLOT_ROLES)
        or evidence_roles.intersection(
            TRANSFER_EVIDENCE_ROLES | STRETCH_EVIDENCE_ROLES
        )
    )


def question_is_stretch(question: dict[str, Any]) -> bool:
    if not isinstance(question, dict):
        raise TypeError("question role metadata must be a mapping")
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    source = (
        question.get("source")
        if isinstance(question.get("source"), dict)
        else {}
    )
    return any(
        candidate_supports_stretch(candidate)
        for candidate in (question, raw, source)
    )


def _candidate_is_controlled_extension(candidate: dict[str, Any]) -> bool:
    return bool(candidate.get("controlled_stretch")) or str(
        candidate.get("evidence_role") or ""
    ) == "picture_level_extension"


def _candidate_allowed_for_intent(
    candidate: dict[str, Any],
    *,
    selection_intent: str,
    next_evidence_goal: str,
    learner_status: str,
    prerequisite_ready: bool,
) -> bool:
    intent = str(selection_intent or "general")
    role = str(candidate.get("slot_role") or "")
    legacy = role == "legacy_mainline"
    if intent == "targeted_support_repair":
        return bool(
            candidate.get("support_only")
            and isinstance(candidate.get("matched_support_route"), dict)
        )
    if candidate.get("support_only"):
        return False
    try:
        expert_priority = int(candidate.get("selection_priority") or 0)
    except (TypeError, ValueError):
        expert_priority = 0
    if intent == "initial_review" and expert_priority > 0:
        return True
    if _candidate_is_stretch(candidate):
        stable_extension_ready = (
            intent == "stable_ready"
            and str(learner_status or "") == "A"
            and bool(prerequisite_ready)
        )
        if _candidate_is_controlled_extension(candidate):
            return stable_extension_ready
        return stable_extension_ready or intent in {"correct_narrow", "near_transfer_retest"}
    if legacy:
        return True
    if intent == "initial_review":
        return role not in INITIAL_EXCLUDED_ROLES
    if intent == "new_knowledge_teaching":
        return role in TEACHING_CONTEXT_SLOT_ROLES and role not in {"wrong_solution_repair", "prerequisite_probe"}
    if intent in {"wrong_blocking", "prerequisite_probe"}:
        return role in REPAIR_SLOT_ROLES or role in CONCEPT_BOUNDARY_SLOT_ROLES
    if intent in {"partial_unstable", "same_structure_retest"}:
        if str(next_evidence_goal or "") == "near_transfer_retest":
            return role in SAME_STRUCTURE_SLOT_ROLES | TRANSFER_SLOT_ROLES | CONCEPT_BOUNDARY_SLOT_ROLES
        return role in SAME_STRUCTURE_SLOT_ROLES | CONCEPT_BOUNDARY_SLOT_ROLES
    if intent in {"correct_narrow", "near_transfer_retest"}:
        return (
            role in TRANSFER_SLOT_ROLES
            or role in {"model_selection", "inverse_check"}
            or role in SAME_STRUCTURE_SLOT_ROLES
            or role in CONCEPT_BOUNDARY_SLOT_ROLES
        )
    if intent == "stable_ready":
        return role in TRANSFER_SLOT_ROLES | SAME_STRUCTURE_SLOT_ROLES | INITIAL_HIGH_DISCRIMINATION_ROLES | CONCEPT_BOUNDARY_SLOT_ROLES
    return True


def _candidate_intent_rank(
    candidate: dict[str, Any],
    *,
    selection_intent: str,
    next_evidence_goal: str,
    learner_status: str,
    prerequisite_ready: bool,
    original_index: int,
) -> tuple[int, int, str]:
    role = str(candidate.get("slot_role") or "")
    role_order: list[str]
    intent = str(selection_intent or "general")
    if intent == "initial_review":
        role_order = [
            "necessary_condition",
            "misconception_boundary",
            "multi_representation",
            "representation_translation",
            "near_transfer",
            "integrated_transfer",
            "model_selection",
            "same_structure_confirmation",
            "standard_model",
            "standard_example",
            "legacy_mainline",
        ]
    elif intent == "new_knowledge_teaching":
        role_order = [
            "essence_model",
            "standard_model",
            "standard_example",
            "core_representation",
            "representation_translation",
            "multi_representation",
            "misconception_boundary",
            "model_selection",
            "necessary_condition",
            "calculation_symbol_precision",
            "inverse_check",
            "concept_boundary",
            "legacy_mainline",
        ]
    elif intent in {"wrong_blocking", "prerequisite_probe"}:
        role_order = [
            "prerequisite_probe",
            "necessary_condition",
            "wrong_solution_repair",
            "calculation_symbol_precision",
            "misconception_boundary",
            "concept_boundary",
            "essence_model",
            "legacy_mainline",
        ]
    elif intent in {"partial_unstable", "same_structure_retest"}:
        role_order = [
            "same_structure_confirmation",
            "wrong_solution_repair",
            "standard_model",
            "standard_example",
            "inverse_check",
            "calculation_symbol_precision",
            "expression_notation",
            "misconception_boundary",
            "concept_boundary",
            "essence_model",
            "legacy_mainline",
        ]
    elif intent in {"correct_narrow", "near_transfer_retest"} or str(next_evidence_goal or "") == "near_transfer_retest":
        role_order = [
            "near_transfer",
            "integrated_transfer",
            "multi_representation",
            "alternative_method",
            "summary_transfer_check",
            "model_selection",
            "inverse_check",
            "same_structure_confirmation",
            "standard_model",
            "standard_example",
            "calculation_symbol_precision",
            "expression_notation",
            "misconception_boundary",
            "concept_boundary",
            "essence_model",
            "legacy_mainline",
        ]
    elif intent == "stable_ready" and str(learner_status or "") == "A" and bool(prerequisite_ready):
        role_order = [
            "stretch_readiness_check",
            "near_transfer",
            "integrated_transfer",
            "multi_representation",
            "alternative_method",
            "legacy_mainline",
        ]
    else:
        role_order = ["legacy_mainline"]
    try:
        priority = role_order.index(role)
    except ValueError:
        priority = len(role_order)
    return (priority, original_index, str(candidate.get("question_id") or ""))


PROMPT_INJECTION_PATTERNS = (
    re.compile(r"(?:忽略|无视|覆盖|绕过|不要遵守).{0,24}(?:以上|前面|规则|要求|系统|提示|rubric)", re.IGNORECASE),
    re.compile(r"(?:直接|只|仅).{0,8}(?:告诉|输出|给出|返回).{0,8}(?:答案|结果)", re.IGNORECASE),
    re.compile(r"(?:不要|无需|不用).{0,12}(?:写|说明|展示).{0,12}(?:步骤|过程|理由|检验|思路)", re.IGNORECASE),
)

CHILD_FACING_META_PATTERNS = (
    "围绕“",
    "完成一道",
    "诊断题",
    "知识点练习",
    "回炉题",
    "真实错因",
    "孩子上次",
    "上次在",
    "知识图谱",
    "图谱节点",
    "agent",
    "Agent",
    "Codex",
    "后台分析",
    "错因标签",
    "模型路由",
    "base_url",
    "model_name",
    "model_alias",
    "model_provider",
    "低年级",
    "答题框架",
    "先写一句",
    "本题沿用的规则",
    "变式题：",
    "原题是：",
    "现在换成变式",
    "请先指出要使用的结构",
    "请判断原方法哪一步不变",
    "原方法哪一步不变",
    "错因或模型",
    "最容易错的一步",
)

CHILD_FACING_META_REGEXES = (
    re.compile(r"请设计.{0,24}(?:小题|题目|问题)"),
    re.compile(r"自拟(?:小题|数字|例子|情境)?"),
    re.compile(r"如果你不想自拟"),
    re.compile(r"请写一份.{0,24}自查清单"),
    re.compile(r"把\s*[^，。；：]{1,24}\s*放进一个实际情境"),
    re.compile(r"请给\s*[^，。；：]{1,24}\s*写一个边界情况"),
    re.compile(r"完成一题\s*[^，。；：]{1,24}(?:。|；|$)"),
    re.compile(r"有一道\s*[^，。；：]{1,24}\s*的题"),
    re.compile(r"比较\s*[^，。；：]{1,24}\s*和一个相近题型"),
    re.compile(r"请完成一次\s*[^，。；：]{1,24}\s*的复盘"),
    re.compile(r"请把\s*[^，。；：]{1,24}\s*的解题过程压缩成"),
    re.compile(r"请说明\s*[^，。；：]{1,24}\s*中“规则会变”"),
    re.compile(r"缺了哪两个过程证据"),
    re.compile(r"最多只能算部分正确"),
)

def _safe_id(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", text.upper()).strip("-")


def _node_mode(node: dict[str, Any]) -> str:
    return node.get("summer_execution", {}).get("mode", "selective_core")


def _error_tags(node: dict[str, Any]) -> list[str]:
    tags = node.get("error_diagnosis", {}).get("likely_error_tags") or ["general"]
    filtered = [tag for tag in tags if tag in CANONICAL_ERROR_TAGS]
    return filtered or ["general"]


def _rollback_candidates(node: dict[str, Any]) -> list[str]:
    rollback = node.get("error_diagnosis", {}).get("rollback_to") or node.get("prerequisites") or []
    return list(dict.fromkeys(rollback))


def _rollback_relations(node: dict[str, Any]) -> list[dict[str, str]]:
    return [{"node_id": candidate, "relation": "prerequisite_chain"} for candidate in _rollback_candidates(node)]


def _seed_types(node: dict[str, Any]) -> list[str]:
    configured = node.get("question_generation", {}).get("seed_question_types") or node.get("question_types") or []
    return configured or [node.get("name", "知识点练习")]


def _item_purpose(kind: str) -> str:
    purposes = {
        "essence_check": "先测概念本质和易混点，不用低龄口算替代诊断。",
        "standard_example": "用标准结构暴露模型、步骤和检验习惯。",
        "variant": "通过变式检查迁移能力和错因是否复发。",
        "transfer_retest": "改变数字或情境后复测规则是否真正稳定。",
        "evidence_driven_retest": "根据真实错因回炉，验证同类断点是否修复。",
        "misconception_probe": "用常见错法暴露概念混淆，而不是只看结果。",
        "reverse_reasoning": "从条件或结论反推模型，检查关系理解是否可逆。",
        "error_spotting": "要求定位错因并修正，区分会算和会判断。",
        "missing_condition": "检查必要条件、单位、边界是否被漏掉。",
        "representation": "在文字、式子、图示或表格之间转换表达。",
        "explanation_only": "只考解释质量，防止答案对但思路不可复盘。",
        "check_strategy": "要求主动检验、反例或代回，培养稳定得分习惯。",
        "estimation_modeling": "先用估算或模型选择排除不合理路径。",
        "prerequisite_probe": "沿前置依赖链探测断点，避免同类题硬刷。",
        "stretch_transfer": "在受控难度上做迁移，判断是否可以拔高。",
        "two_method_compare": "比较两种方法的适用条件和风险点。",
        "boundary_case": "用边界或特殊情况检查规则是否过度泛化。",
        "symbol_unit_audit": "专门审查符号、单位、括号或维度表达。",
        "self_correction": "让孩子先发现并修复自己的可能错法。",
        "near_transfer": "换数字或近似情境复测是否脱离模板。",
        "far_transfer": "换表示或远一点的情境复测结构稳定性。",
        "model_selection": "在相似模型之间选择并说明为什么。",
        "communication": "要求把数学关系说清楚，检查表达是否完整。",
    }
    return purposes.get(kind, "图谱绑定诊断题，要求过程证据。")


QUESTION_BLUEPRINTS: list[dict[str, Any]] = [
    {
        "kind": "standard_example",
        "level": "L2",
        "label": "核心模型",
        "target_tags": ["concept_confusion", "process_habit"],
        "answer_format": "规则 + 关键步骤 + 答案 + 检验",
        "prefix": "先写出本题用到的关键规则，再完成：",
        "suffix": "最后用一句话说明为什么这个规则适用。",
    },
    {
        "kind": "essence_check",
        "level": "L1",
        "label": "本质识别",
        "target_tags": ["concept_confusion"],
        "answer_format": "考点判断 + 理由 + 答案",
        "prefix": "先判断这题真正考的是什么，再完成：",
        "suffix": "请说明只看最终答案会漏掉什么。",
    },
    {
        "kind": "misconception_probe",
        "level": "L2",
        "label": "易混概念辨析",
        "target_tags": ["concept_confusion"],
        "answer_format": "判断 + 错因 + 正确过程",
        "prefix": "把下面题目当成一次错因辨析，先找最容易混淆的概念，再完成：",
        "suffix": "如果有人只背公式，请指出他最可能错在哪一步。",
    },
    {
        "kind": "error_spotting",
        "level": "L3",
        "label": "错解定位",
        "target_tags": ["process_habit", "calculation_or_symbol"],
        "answer_format": "错因定位 + 改正 + 检验",
        "prefix": "请用“错在哪里、为什么错、怎样改”三步完成：",
        "suffix": "把你认为最危险的一步圈出来，并写一个检查办法。",
    },
    {
        "kind": "variant",
        "level": "L3",
        "label": "近迁移变式",
        "target_tags": ["calculation_or_symbol", "modeling_or_reading"],
        "answer_format": "模型/关系 + 过程 + 答案",
        "prefix": "换一种相近情境来做，先写模型或关系，再完成：",
        "suffix": "说明这道变式和原规则相比，改变的是数字还是结构。",
    },
    {
        "kind": "transfer_retest",
        "level": "L4",
        "label": "远迁移复测",
        "target_tags": ["modeling_or_reading", "concept_confusion"],
        "answer_format": "结构判断 + 迁移理由 + 答案",
        "prefix": "不要急着套模板，先判断结构是否相同，再完成：",
        "suffix": "再改一个条件，说明方法中哪一部分保持不变。",
    },
    {
        "kind": "reverse_reasoning",
        "level": "L3",
        "label": "反向推理",
        "target_tags": ["modeling_or_reading", "concept_confusion"],
        "answer_format": "反推关系 + 过程 + 检验",
        "prefix": "请从结论或条件反推关键关系，再完成：",
        "suffix": "用反向检验说明你的关系没有写反。",
    },
    {
        "kind": "missing_condition",
        "level": "L3",
        "label": "条件完整性",
        "target_tags": ["modeling_or_reading", "process_habit"],
        "answer_format": "必要条件 + 判断 + 修正",
        "prefix": "先列出解题必须确认的条件，再完成：",
        "suffix": "指出如果少看一个条件，答案可能怎样偏掉。",
    },
    {
        "kind": "representation",
        "level": "L2",
        "label": "表示转换",
        "target_tags": ["visual_spatial", "modeling_or_reading"],
        "answer_format": "文字/图式/算式转换 + 解释",
        "prefix": "把题意先换成另一种表示方式，再完成：",
        "suffix": "说明这种表示为什么能帮助你避免读题错误。",
    },
    {
        "kind": "explanation_only",
        "level": "L2",
        "label": "只考解释",
        "target_tags": ["process_habit", "concept_confusion"],
        "answer_format": "解释 + 依据 + 反例/检验",
        "prefix": "这次重点不是快算，而是解释清楚。请完成：",
        "suffix": "用一句不跳步的话说明关键理由。",
    },
    {
        "kind": "check_strategy",
        "level": "L2",
        "label": "检验策略",
        "target_tags": ["process_habit"],
        "answer_format": "解答 + 检验方法 + 结论",
        "prefix": "做完必须检查。请先想一种检验方法，再完成：",
        "suffix": "最后写出你用的是代入、估算、反例还是单位检查。",
    },
    {
        "kind": "estimation_modeling",
        "level": "L2",
        "label": "估算与模型选择",
        "target_tags": ["calculation_or_symbol", "modeling_or_reading"],
        "answer_format": "估算/模型选择 + 过程 + 答案",
        "prefix": "先用估算或模型选择判断答案大致范围，再完成：",
        "suffix": "说明估算怎样帮你发现不合理答案。",
    },
    {
        "kind": "prerequisite_probe",
        "level": "L1",
        "label": "前置依赖探针",
        "target_tags": ["general", "concept_confusion"],
        "answer_format": "前置规则 + 解答 + 卡点说明",
        "prefix": "先写出这题依赖的前一个基础规则，再完成：",
        "suffix": "如果这里卡住，请写清楚是读题、概念、符号还是步骤卡住。",
    },
    {
        "kind": "stretch_transfer",
        "level": "L4",
        "label": "拔高迁移",
        "target_tags": ["modeling_or_reading", "process_habit"],
        "answer_format": "迁移判断 + 过程 + 复盘",
        "prefix": "在不增加机械计算量的前提下做一个拔高判断：",
        "suffix": "说明这题比标准题多了哪一个思考点。",
    },
    {
        "kind": "two_method_compare",
        "level": "L3",
        "label": "两法比较",
        "target_tags": ["concept_confusion", "process_habit"],
        "answer_format": "两种方法比较 + 选择理由",
        "prefix": "请比较两种可能做法的适用条件，再完成：",
        "suffix": "写出你选择的方法，并说明另一种方法的风险。",
    },
    {
        "kind": "boundary_case",
        "level": "L3",
        "label": "边界反例",
        "target_tags": ["concept_confusion", "general"],
        "answer_format": "规则 + 边界/反例 + 结论",
        "prefix": "先想一个边界情况或反例，再完成：",
        "suffix": "判断这个规则是不是在所有类似情况都成立。",
    },
    {
        "kind": "symbol_unit_audit",
        "level": "L2",
        "label": "符号单位审查",
        "target_tags": ["calculation_or_symbol", "process_habit"],
        "answer_format": "符号/单位检查 + 过程 + 答案",
        "prefix": "先检查符号、单位、括号或维度，再完成：",
        "suffix": "写出最容易因为符号或单位丢分的地方。",
    },
    {
        "kind": "self_correction",
        "level": "L3",
        "label": "自我纠错",
        "target_tags": ["process_habit"],
        "answer_format": "可能错法 + 正确过程 + 自查",
        "prefix": "先预测自己最可能犯的一个错，再完成：",
        "suffix": "完成后按你预测的错法检查一遍。",
    },
    {
        "kind": "model_selection",
        "level": "L3",
        "label": "模型选择",
        "target_tags": ["modeling_or_reading"],
        "answer_format": "模型选择 + 排除理由 + 解答",
        "prefix": "这题先选择模型，不要直接列式。请完成：",
        "suffix": "说明你排除了哪一种看起来相似但不适用的方法。",
    },
    {
        "kind": "communication",
        "level": "L2",
        "label": "表达完整性",
        "target_tags": ["process_habit", "modeling_or_reading"],
        "answer_format": "完整表达 + 答案 + 一句话总结",
        "prefix": "请把关系、步骤和结论说完整，再完成：",
        "suffix": "最后指出只留下一个数或式子错在哪里，并写一句完整答句。",
    },
]


def _cognitive_level(kind: str, level: str) -> str:
    levels = {
        "essence_check": "concept_discrimination",
        "standard_example": "model_application",
        "variant": "error_analysis_and_variant_transfer",
        "transfer_retest": "far_transfer_and_rule_stability",
        "evidence_driven_retest": "evidence_driven_error_repair",
        "misconception_probe": "misconception_discrimination",
        "reverse_reasoning": "reverse_model_reconstruction",
        "error_spotting": "error_analysis",
        "missing_condition": "condition_and_boundary_check",
        "representation": "representation_conversion",
        "explanation_only": "explanation_quality",
        "check_strategy": "verification_strategy",
        "estimation_modeling": "estimation_and_model_choice",
        "prerequisite_probe": "prerequisite_dependency_probe",
        "stretch_transfer": "controlled_stretch_transfer",
        "two_method_compare": "method_comparison",
        "boundary_case": "boundary_case_reasoning",
        "symbol_unit_audit": "symbol_and_unit_audit",
        "self_correction": "self_correction_protocol",
        "near_transfer": "near_transfer",
        "far_transfer": "far_transfer",
        "model_selection": "model_selection",
        "communication": "mathematical_communication",
    }
    return levels.get(kind, f"graph_bound_{level.lower()}")


def _reviewer_evidence(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    evidence = source.get("reviewer_evidence")
    if isinstance(evidence, dict):
        return evidence
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    if (
        source.get("type") == "diagnostic_generated"
        and (source.get("production_pipeline") or {}).get("reviewer_agent") == QUESTION_REVIEWER_AGENT_KEY
        and quality.get("review_status") == "approved"
        and quality.get("requires_reasoning") is True
        and quality.get("has_high_signal_structure") is True
        and quality.get("no_mechanical_drill") is True
    ):
        return {
            "agent_key": QUESTION_REVIEWER_AGENT_KEY,
            "engine_type": "legacy_imported_review_record",
            "graph_bound": True,
            "incoming_grade_7_ready": True,
            "diagnostic_structure": True,
            "process_evidence_required": True,
            "not_mechanical_drill": True,
            "child_prompt_self_contained": True,
            "specific_expected_answer": True,
        }
    return {}


def _has_reasoning_demand(item: dict[str, Any]) -> bool:
    evidence = _reviewer_evidence(item)
    if evidence:
        return evidence.get("process_evidence_required") is True
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    return quality.get("requires_reasoning") is True


def has_high_signal_structure(item: dict[str, Any]) -> bool:
    evidence = _reviewer_evidence(item)
    if evidence:
        return evidence.get("diagnostic_structure") is True
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    return quality.get("has_high_signal_structure") is True


def picture_level_challenge_labels(item: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    containers = [
        source.get("problem_family_basis"),
        source.get("core_stem_basis"),
        item.get("node_alignment"),
        item.get("quality"),
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        raw_labels = container.get("picture_level_challenge_labels")
        if isinstance(raw_labels, list):
            labels.extend(str(label) for label in raw_labels)
        label = container.get("challenge_label")
        if isinstance(label, str) and label:
            labels.append(label)
    return [
        label for label in dict.fromkeys(labels)
        if label in PICTURE_LEVEL_CHALLENGE_NODE_ALLOWLIST
    ]


def is_picture_level_challenge_item(item: dict[str, Any]) -> bool:
    return bool(picture_level_challenge_labels(item))


def is_low_signal_surface_prompt(item: dict[str, Any]) -> bool:
    return _has_low_signal_mechanical_surface(item) or _looks_like_mechanical_drill(item)


def _has_low_signal_mechanical_surface(item: dict[str, Any]) -> bool:
    prompt = str(item.get("prompt") or "").strip()
    compact = re.sub(r"\s+", "", prompt)
    bare_calc = re.fullmatch(
        r"(?:请)?(?:直接)?计算[-−]?\d+(?:\.\d+)?[+\-×xX*÷/][-−]?\d+(?:\.\d+)?[。；]?",
        compact,
    )
    weak_calc_wrapper = re.search(
        r"(?:^|[，。；:：])(?:请)?(?:计算|算出)[-−]?\d+(?:\.\d+)?[+\-×xX*÷/][-−]?\d+(?:\.\d+)?(?:并)?(?:写出过程|判断答案是否正确|说明判断依据|用检验说明答案)",
        compact,
    )
    weak_conversion = re.search(
        r"(?:^|[，。；:：])(?:把)?\d+(?:\.\d+)?(?:米|m|M|平方米|平方分米|厘米|cm|CM)(?:化成|换成|转成)\d*(?:米|m|M|平方米|平方分米|厘米|cm|CM)",
        compact,
    )
    return bool(bare_calc or weak_calc_wrapper or weak_conversion)


def _looks_like_mechanical_drill(item: dict[str, Any]) -> bool:
    evidence = _reviewer_evidence(item)
    if evidence:
        return evidence.get("not_mechanical_drill") is not True
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    if "no_mechanical_drill" in quality:
        return quality.get("no_mechanical_drill") is not True
    return True


def _has_unresolved_child_context_reference(prompt: str) -> bool:
    return False


def _compact_identity_text(value: str) -> str:
    text = value
    for blueprint in QUESTION_BLUEPRINTS:
        for key in ("prefix", "suffix"):
            part = str(blueprint.get(key) or "")
            if part:
                text = text.replace(part, " ")
    wrappers = (
        "先判断考点，再作答：",
        "最后用检验、错因或模型说明关键一步为什么成立。",
        "做完后把最容易错的一步圈出来。",
        "换一个相近条件，说明原来的哪条规则仍然不变。",
    )
    for wrapper in wrappers:
        text = text.replace(wrapper, " ")
    text = re.sub(r"本题重点：[^。]+。?", " ", text)
    text = re.sub(r"作答时请特别写清“[^”]+”的关键关系。?", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[，。；：、,.!?？!“”\"'`]+", "", text)
    return text.strip()


def _short_digest(payload: dict[str, Any], length: int = 16) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _problem_family_group(kind: str) -> str:
    return PROBLEM_FAMILY_KIND_GROUPS.get(kind, "other_graph_bound_probe")


def _identity_basis_value(item: dict[str, Any], key: str, default: Any = "") -> Any:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    value = source.get(key)
    return value if value not in (None, "", [], {}) else default


def _identity_basis_for_review(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return {
        "problem_family_basis": source.get("problem_family_basis", {}),
        "core_stem_basis": source.get("core_stem_basis", {}),
        "problem_instance_basis": source.get("problem_instance_basis", {}),
        "node_local_anchor": source.get("node_local_anchor", ""),
    }


def _canonical_core_payload_from_basis(item: dict[str, Any]) -> dict[str, Any]:
    basis = _identity_basis_value(item, "core_stem_basis", {})
    core_fields = basis.get("core_fields") if isinstance(basis, dict) else {}
    if isinstance(core_fields, dict) and any(str(value or "").strip() for value in core_fields.values()):
        stem_anchor = str(
            core_fields.get("stem_anchor")
            or core_fields.get("prompt_core")
            or core_fields.get("problem")
            or ""
        )
        return {
            "semantic_stem": _compact_identity_text(stem_anchor),
        }
    return {
        "semantic_stem": _compact_identity_text(str(item.get("prompt") or ""))[:260],
        "answer_core": _compact_identity_text(str(item.get("expected_answer") or ""))[:220],
    }


def canonical_core_signature(item: dict[str, Any], *, include_node: bool = False) -> str:
    payload = _canonical_core_payload_from_basis(item)
    if include_node:
        payload = {"node_id": item.get("node_id", ""), **payload}
    return f"CC-{_short_digest(payload, 14)}"


def question_evidence_role(item: dict[str, Any]) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    core_basis = source.get("core_stem_basis") if isinstance(source.get("core_stem_basis"), dict) else {}
    role = str(core_basis.get("evidence_role") or source.get("evidence_role") or "")
    if role:
        return role
    return "picture_level_extension" if picture_level_challenge_labels(item) else "node_local_mainline"


def is_node_local_mainline_item(item: dict[str, Any]) -> bool:
    return question_evidence_role(item) == "node_local_mainline" and not picture_level_challenge_labels(item)


def _question_identity_from_context(
    node: dict[str, Any],
    question_type: str,
    kind: str,
    offset: int,
    context: dict[str, str],
    *,
    template_slot: int,
) -> dict[str, Any]:
    topic_family = _topic_family(node, question_type)
    probe_family = _problem_family_group(kind)
    challenge_label = str(context.get("challenge_label") or "")
    evidence_role = str(context.get("evidence_role") or ("picture_level_extension" if challenge_label else "node_local_mainline"))
    anchor_parts = []
    for key in CORE_STEM_KEYS_BY_TEMPLATE_SLOT.get(template_slot, ("problem", "rule", "check")):
        value = str(context.get(key) or "").strip()
        if value:
            anchor_parts.append(f"{key}={value}")
    if not anchor_parts:
        anchor_parts.append(str(context.get("problem") or context.get("variant_problem") or context.get("wrong_solution") or ""))
    stem_anchor = " | ".join(anchor_parts)
    core_fields = {
        "stem_anchor": stem_anchor,
        "rule_anchor": str(context.get("rule") or ""),
        "answer_anchor": str(context.get("short_answer") or context.get("answer") or ""),
    }
    semantic_stem_signature = f"CC-{_short_digest({'semantic_stem': _compact_identity_text(stem_anchor)}, 14)}"
    problem_family_basis = {
        "node_id": node.get("id", ""),
        "node_name": node.get("name", ""),
        "topic_family": topic_family,
        "seed_question_type": question_type,
        "probe_family": probe_family,
        "kind": kind,
        "evidence_role": evidence_role,
        "challenge_label": challenge_label,
    }
    core_stem_basis = {
        "node_id": node.get("id", ""),
        "topic_family": topic_family,
        "core_fields": core_fields,
        "semantic_stem_signature": semantic_stem_signature,
        "evidence_role": evidence_role,
        "challenge_label": challenge_label,
    }
    instance_field = PROBLEM_INSTANCE_FIELD_BY_TEMPLATE_SLOT.get(template_slot, "problem")
    instance_problem = str(
        context.get(instance_field)
        or context.get("problem")
        or context.get("variant_problem")
        or ""
    )
    explicit_instance_key = str(context.get("problem_instance_key") or "").strip()
    base_problem = str(context.get("problem") or instance_problem).strip()
    base_instance_key = explicit_instance_key or (
        "context:problem:" + _short_digest({"problem": base_problem}, 12)
    )
    variant_changes_mathematical_data = instance_field == "variant_problem"
    problem_instance_basis = {
        "instance_field": instance_field,
        "instance_key": (
            base_instance_key
            if not variant_changes_mathematical_data
            else f"{base_instance_key}:variant:{_short_digest({'problem': instance_problem}, 12)}"
        ),
        "problem": instance_problem,
    }
    return {
        "problem_family_basis": problem_family_basis,
        "core_stem_basis": core_stem_basis,
        "problem_instance_basis": problem_instance_basis,
        "node_local_anchor": str(context.get("rule") or context.get("condition") or context.get("problem") or ""),
        "context_offset": offset,
    }


def _fallback_question_identity(
    node: dict[str, Any],
    question_type: str,
    kind: str,
    *,
    prompt: str,
    answer: str,
    offset: int,
    problem_instance_problem: str = "",
) -> dict[str, Any]:
    topic_family = _topic_family(node, question_type)
    probe_family = _problem_family_group(kind)
    canonical_problem = str(problem_instance_problem or "").strip()
    core_fields = {
        "prompt_core": _compact_identity_text(prompt)[:260],
        "answer_core": _compact_identity_text(answer)[:220],
    }
    return {
        "problem_family_basis": {
            "node_id": node.get("id", ""),
            "node_name": node.get("name", ""),
            "topic_family": topic_family,
            "seed_question_type": question_type,
            "probe_family": probe_family,
            "kind": kind,
            "fallback": True,
        },
        "core_stem_basis": {
            "node_id": node.get("id", ""),
            "topic_family": topic_family,
            "core_fields": core_fields,
            "semantic_stem_signature": f"CC-{_short_digest({'semantic_stem': core_fields['prompt_core']}, 14)}",
            "evidence_role": "node_local_mainline",
            "challenge_label": "",
            "fallback": True,
        },
        "problem_instance_basis": {
            "instance_key": (
                "context:problem:" + _short_digest({"problem": canonical_problem}, 12)
                if canonical_problem
                else f"fallback:{_short_digest({'prompt': prompt, 'answer': answer}, 16)}"
            ),
            "problem": canonical_problem or prompt,
            "fallback": True,
        },
        "node_local_anchor": str(node.get("teaching_contract", {}).get("one_sentence_essence") or node.get("name") or question_type),
        "context_offset": offset,
    }


def _problem_family_id(node: dict[str, Any], question_type: str, item: dict[str, Any]) -> str:
    labels = picture_level_challenge_labels(item)
    basis = _identity_basis_value(item, "problem_family_basis", {})
    probe_family = ""
    topic_family = ""
    seed_type = question_type
    if isinstance(basis, dict):
        probe_family = str(basis.get("probe_family") or "")
        topic_family = str(basis.get("topic_family") or "")
        seed_type = str(basis.get("seed_question_type") or question_type)
    substrate = labels[0] if labels else topic_family or _topic_family(node, question_type)
    payload = {
        "node_id": node.get("id", ""),
        "substrate": substrate,
        "question_type": seed_type,
        "probe_family": probe_family or _problem_family_group(str(item.get("kind") or "")),
    }
    return f"PF-{_safe_id(str(node.get('id', 'NODE')))}-{_short_digest(payload, 10)}"


def _core_stem_id(node: dict[str, Any], question_type: str, item: dict[str, Any]) -> str:
    payload = {
        "node_id": node.get("id", ""),
        "canonical_core_signature": canonical_core_signature(item),
    }
    return f"CS-{_safe_id(str(node.get('id', 'NODE')))}-{_short_digest(payload, 12)}"


def _problem_instance_id(item: dict[str, Any]) -> str:
    basis = _identity_basis_value(item, "problem_instance_basis", {})
    if isinstance(basis, dict):
        instance_key = str(basis.get("instance_key") or "").strip()
        problem = str(basis.get("problem") or "").strip()
    else:
        instance_key = ""
        problem = ""
    payload = {
        "instance_key": instance_key,
        "problem": "" if instance_key else problem,
    }
    if not any(payload.values()):
        payload = {
            "fallback_prompt": str(item.get("prompt") or ""),
            "fallback_answer": str(item.get("expected_answer") or ""),
        }
    return f"PI-{_short_digest(payload, 16)}"


def _node_alignment_for(node: dict[str, Any], question_type: str, item: dict[str, Any]) -> dict[str, Any]:
    node_name = str(node.get("name") or "")
    essence = str(_node_essence(node))
    target_error_tags = [tag for tag in item.get("target_error_tags", []) if tag in CANONICAL_ERROR_TAGS]
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    problem_family_basis = source.get("problem_family_basis") if isinstance(source.get("problem_family_basis"), dict) else {}
    core_stem_basis = source.get("core_stem_basis") if isinstance(source.get("core_stem_basis"), dict) else {}
    node_local_anchor = str(source.get("node_local_anchor") or "")
    challenge_labels = picture_level_challenge_labels(item)
    matched_terms = [
        term
        for term in [
            node.get("id", ""),
            node_name,
            question_type,
            problem_family_basis.get("topic_family", ""),
            problem_family_basis.get("probe_family", ""),
            node_local_anchor,
            *challenge_labels,
        ]
        if str(term).strip()
    ]
    measured_capability = (
        f"{node_name} / {question_type} / "
        f"{problem_family_basis.get('probe_family') or _problem_family_group(str(item.get('kind') or ''))}"
    )
    seed_types = [str(seed) for seed in _seed_types(node)]
    seed_match = [seed for seed in seed_types if seed and seed == question_type]
    if not seed_match and question_type:
        seed_match = [question_type]
    alignment_mode = "picture_level_extension" if challenge_labels else "node_local_mainline"
    reason = (
        f"题目围绕图谱节点「{node_name}」的「{question_type}」设计，"
        f"要求孩子给出规则/关系、过程证据和检验；目标错因={','.join(target_error_tags) or 'general'}。"
    )
    if challenge_labels:
        reason += f" 拔高素材={','.join(challenge_labels)}，必须由当前节点技能完成，而不是只挂名。"
    return {
        "status": "claimed",
        "alignment_mode": alignment_mode,
        "primary_node_id": node.get("id", ""),
        "primary_node_name": node_name,
        "question_type": question_type,
        "problem_family_id": item.get("problem_family_id", ""),
        "core_stem_id": item.get("core_stem_id", ""),
        "problem_instance_id": item.get("problem_instance_id", ""),
        "reason": reason,
        "matched_terms": list(dict.fromkeys(matched_terms))[:10],
        "measured_capability": measured_capability,
        "graph_seed_question_type": question_type,
        "graph_seed_match": seed_match[:5],
        "node_local_anchor": node_local_anchor,
        "problem_family_basis": problem_family_basis,
        "core_stem_basis": core_stem_basis,
        "problem_instance_basis": source.get("problem_instance_basis", {}),
        "off_node_risk": (
            "picture_level_extension_must_not_replace_node_local_evidence"
            if challenge_labels else "low"
        ),
        "rollback_rationale": (
            "If this task exposes a gap, planning should inspect rollback candidates before assigning more same-node variants."
            if _rollback_candidates(node) else "No explicit rollback candidate in graph."
        ),
        "target_error_tags": target_error_tags,
        "rollback_candidate_node_ids": _rollback_candidates(node),
        "one_sentence_essence": essence,
    }


def _attach_question_identity_contract(item: dict[str, Any], node: dict[str, Any], question_type: str) -> None:
    item.setdefault("source", {})
    source = item["source"]
    if (
        not isinstance(source.get("problem_family_basis"), dict)
        or not isinstance(source.get("core_stem_basis"), dict)
        or not isinstance(source.get("problem_instance_basis"), dict)
    ):
        source.update(
            _fallback_question_identity(
                node,
                question_type,
                str(item.get("kind") or ""),
                prompt=str(item.get("prompt") or ""),
                answer=str(item.get("expected_answer") or ""),
                offset=int(source.get("blueprint_slot") or 0),
            )
        )
    item["problem_family_id"] = _problem_family_id(node, question_type, item)
    item["core_stem_id"] = _core_stem_id(node, question_type, item)
    item["problem_instance_id"] = _problem_instance_id(item)
    item["node_alignment"] = _node_alignment_for(node, question_type, item)
    item["source"]["problem_family_id"] = item["problem_family_id"]
    item["source"]["core_stem_id"] = item["core_stem_id"]
    item["source"]["problem_instance_id"] = item["problem_instance_id"]
    item["source"]["node_alignment"] = item["node_alignment"]


def _identity_contract_rejection_reasons(item: dict[str, Any]) -> list[str]:
    source_type = item.get("source_type") or item.get("source", {}).get("type")
    if source_type not in {"graph_generated", "evolved"}:
        return []
    reasons: list[str] = []
    if not str(item.get("problem_family_id") or "").startswith("PF-"):
        reasons.append("missing_problem_family_id")
    if not str(item.get("core_stem_id") or "").startswith("CS-"):
        reasons.append("missing_core_stem_id")
    if not str(item.get("problem_instance_id") or "").startswith("PI-"):
        reasons.append("missing_problem_instance_id")
    alignment = item.get("node_alignment")
    if not isinstance(alignment, dict):
        reasons.append("missing_node_alignment")
        return reasons
    if alignment.get("primary_node_id") != item.get("node_id"):
        reasons.append("node_alignment_primary_node_mismatch")
    if not str(alignment.get("reason") or "").strip():
        reasons.append("missing_node_alignment_reason")
    if not alignment.get("matched_terms"):
        reasons.append("node_alignment_lacks_matched_terms")
    if alignment.get("problem_family_id") != item.get("problem_family_id"):
        reasons.append("node_alignment_problem_family_mismatch")
    if alignment.get("core_stem_id") != item.get("core_stem_id"):
        reasons.append("node_alignment_core_stem_mismatch")
    if alignment.get("problem_instance_id") != item.get("problem_instance_id"):
        reasons.append("node_alignment_problem_instance_mismatch")
    basis = _identity_basis_for_review(item)
    problem_family_basis = basis["problem_family_basis"]
    core_stem_basis = basis["core_stem_basis"]
    problem_instance_basis = basis["problem_instance_basis"]
    if not isinstance(problem_family_basis, dict) or not str(problem_family_basis.get("probe_family") or "").strip():
        reasons.append("missing_problem_family_basis")
    if not isinstance(core_stem_basis, dict) or not core_stem_basis.get("core_fields"):
        reasons.append("missing_core_stem_basis")
    if not isinstance(problem_instance_basis, dict) or not (
        str(problem_instance_basis.get("instance_key") or "").strip()
        or str(problem_instance_basis.get("problem") or "").strip()
    ):
        reasons.append("missing_problem_instance_basis")
    if not str(basis.get("node_local_anchor") or "").strip():
        reasons.append("missing_node_local_anchor")
    if not str(alignment.get("measured_capability") or "").strip():
        reasons.append("missing_measured_capability")
    if not str(alignment.get("graph_seed_question_type") or "").strip():
        reasons.append("missing_graph_seed_question_type")
    if not str(alignment.get("node_local_anchor") or "").strip():
        reasons.append("node_alignment_missing_node_local_anchor")
    if (
        not isinstance(alignment.get("problem_family_basis"), dict)
        or not isinstance(alignment.get("core_stem_basis"), dict)
        or not isinstance(alignment.get("problem_instance_basis"), dict)
    ):
        reasons.append("node_alignment_missing_identity_basis")
    return reasons


def curated_seed_reviewer_evidence(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return {
        "agent_key": QUESTION_REVIEWER_AGENT_KEY,
        "engine_type": "curated_seed_manifest_review",
        "provenance_type": "curated_seed_manifest",
        "curated_manifest_id": GRAPH_SEED_REVIEW_MANIFEST_ID,
        "curated_manifest_version": QUESTION_BANK_VERSION,
        "graph_version": item.get("graph_version") or source.get("graph_version") or "",
        "question_bank_version": item.get("question_bank_version") or source.get("question_bank_version") or QUESTION_BANK_VERSION,
        "contract_version": QUESTION_PRODUCTION_CONTRACT_VERSION,
        "graph_bound": True,
        "incoming_grade_7_ready": True,
        "diagnostic_structure": True,
        "process_evidence_required": True,
        "not_mechanical_drill": True,
        "child_prompt_self_contained": True,
        "specific_expected_answer": True,
        "problem_family_id": item.get("problem_family_id", ""),
        "core_stem_id": item.get("core_stem_id", ""),
        "problem_instance_id": item.get("problem_instance_id", ""),
        "evidence_role": question_evidence_role(item),
        "review_rationale": "Curated graph seed item with graph binding, non-mechanical process evidence, concrete answer, and child-contained prompt.",
    }


def deterministic_evolution_reviewer_evidence(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return {
        "agent_key": QUESTION_REVIEWER_AGENT_KEY,
        "engine_type": "deterministic_evolution_review",
        "provenance_type": "deterministic_evidence_retest_review",
        "contract_version": QUESTION_PRODUCTION_CONTRACT_VERSION,
        "graph_bound": True,
        "incoming_grade_7_ready": True,
        "diagnostic_structure": True,
        "process_evidence_required": True,
        "not_mechanical_drill": True,
        "child_prompt_self_contained": True,
        "specific_expected_answer": True,
        "problem_family_id": item.get("problem_family_id", ""),
        "core_stem_id": item.get("core_stem_id", ""),
        "problem_instance_id": item.get("problem_instance_id", ""),
        "evidence_role": question_evidence_role(item),
        "source_attempt_id": source.get("attempt_id", ""),
        "evolution_strategy": source.get("evolution_strategy", ""),
        "review_rationale": "Deterministic evidence-retest item built from an active graded attempt; requires a recorded reviewer run before child active use.",
    }


def _reviewer_evidence_rejection_reasons(item: dict[str, Any]) -> list[str]:
    evidence = _reviewer_evidence(item)
    if not evidence:
        return ["missing_structured_reviewer_evidence"]
    reasons: list[str] = []
    if evidence.get("agent_key") != QUESTION_REVIEWER_AGENT_KEY:
        reasons.append("invalid_reviewer_agent_key")
    required_flags = REVIEWER_EVIDENCE_FLAGS
    production_pipeline = evidence.get("provenance_type") == "question_production_pipeline"
    fixed_answer = str(item.get("answer_format") or "") == "fixed_answer"
    if production_pipeline and fixed_answer:
        required_flags = tuple(
            flag for flag in REVIEWER_EVIDENCE_FLAGS
            if flag != "process_evidence_required"
        )
    for flag in required_flags:
        if evidence.get(flag) is not True:
            reasons.append(f"reviewer_evidence_failed:{flag}")
    return reasons


def _semantic_node_mismatch_reasons(item: dict[str, Any]) -> list[str]:
    node_id = str(item.get("node_id") or "")
    reasons: list[str] = []
    alignment = item.get("node_alignment") if isinstance(item.get("node_alignment"), dict) else {}
    if alignment and alignment.get("primary_node_id") != node_id:
        reasons.append("semantic_node_mismatch:node_alignment_primary_node_mismatch")
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    source_alignment = source.get("node_alignment") if isinstance(source.get("node_alignment"), dict) else {}
    if source_alignment and source_alignment.get("primary_node_id") != node_id:
        reasons.append("semantic_node_mismatch:source_node_alignment_primary_node_mismatch")
    challenge_labels = picture_level_challenge_labels(item)
    if challenge_labels:
        role = question_evidence_role(item)
        if role != "picture_level_extension":
            reasons.append("semantic_node_mismatch:picture_level_item_missing_extension_role")
        for label in challenge_labels:
            allowed_nodes = PICTURE_LEVEL_CHALLENGE_NODE_ALLOWLIST.get(label, set())
            if node_id not in allowed_nodes:
                reasons.append(f"semantic_node_mismatch:picture_level_challenge_off_node:{label}")
    return reasons


def review_item_quality(item: dict[str, Any]) -> dict[str, Any]:
    production_evidence = _reviewer_evidence(item)
    if production_evidence.get("provenance_type") == "question_production_pipeline":
        return _review_question_production_item(item)
    if _is_v12_external_active_item(item):
        return review_item_quality_for_active_use(item)
    prompt = str(item.get("prompt", ""))
    expected_answer = str(item.get("expected_answer", ""))
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    rejection_reasons: list[str] = []
    if not item.get("node_id"):
        rejection_reasons.append("missing_graph_node_binding")
    if item.get("age_floor") not in {None, INCOMING_GRADE_7_AGE_FLOOR}:
        rejection_reasons.append("wrong_age_floor")
    if not _has_reasoning_demand(item):
        rejection_reasons.append("missing_process_or_reasoning_demand")
    if not has_high_signal_structure(item):
        rejection_reasons.append("missing_high_signal_diagnostic_structure")
    if len(item.get("solution_steps", [])) < 2:
        rejection_reasons.append("insufficient_solution_step_evidence")
    rejection_reasons.extend(_reviewer_evidence_rejection_reasons(item))
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(prompt):
            rejection_reasons.append("prompt_injection_or_answer_only_instruction")
            break
    if is_low_signal_surface_prompt(item):
        rejection_reasons.append("low_signal_or_insulting_mechanical_prompt")
    if any(pattern in prompt for pattern in CHILD_FACING_META_PATTERNS) or any(
        pattern.search(prompt) for pattern in CHILD_FACING_META_REGEXES
    ):
        rejection_reasons.append("child_facing_generator_meta_language")
    if _has_unresolved_child_context_reference(prompt):
        rejection_reasons.append("unresolved_child_context_reference")
    if _reviewer_evidence(item).get("specific_expected_answer") is False:
        rejection_reasons.append("generic_or_rubric_only_expected_answer")
    if _looks_like_mechanical_drill(item):
        rejection_reasons.append("mechanical_arithmetic_without_reasoning")
    rejection_reasons.extend(_semantic_node_mismatch_reasons(item))
    rejection_reasons.extend(_identity_contract_rejection_reasons(item))

    approved = not rejection_reasons
    return {
        "contract_version": QUESTION_PRODUCTION_CONTRACT_VERSION,
        "graph_version": item.get("graph_version") or source.get("graph_version") or "",
        "question_bank_version": item.get("question_bank_version") or source.get("question_bank_version") or item.get("item_version", ""),
        "review_status": "approved" if approved else "rejected",
        "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
        "reviewer_evidence": _reviewer_evidence(item),
        "age_floor": INCOMING_GRADE_7_AGE_FLOOR,
        "cognitive_level": _cognitive_level(str(item.get("kind", "")), str(item.get("variant_level", ""))),
        "item_purpose": _item_purpose(str(item.get("kind", ""))),
        "requires_reasoning": _has_reasoning_demand(item),
        "has_high_signal_structure": has_high_signal_structure(item),
        "picture_level_challenge_labels": picture_level_challenge_labels(item),
        "problem_family_id": item.get("problem_family_id", ""),
        "core_stem_id": item.get("core_stem_id", ""),
        "problem_instance_id": item.get("problem_instance_id", ""),
        "node_alignment": item.get("node_alignment", {}),
        "identity_basis": _identity_basis_for_review(item),
        "requires_process_evidence": PROCESS_EVIDENCE_REQUIREMENTS,
        "no_mechanical_drill": not _looks_like_mechanical_drill(item)
        and "low_signal_or_insulting_mechanical_prompt" not in rejection_reasons,
        "criteria": [
            "graph_node_bound",
            "incoming_grade_7_floor",
            "diagnostic_not_drill",
            "process_evidence_required",
            "specific_expected_answer_not_rubric_only",
            "problem_family_core_stem_and_problem_instance_traceable",
            "node_alignment_reason_required",
        ],
        "rejection_reasons": rejection_reasons,
    }


def _review_question_production_item(item: dict[str, Any]) -> dict[str, Any]:
    """Evaluate items carrying the production pipeline's accepted review evidence.

    Fixed-answer items are validated for answer/control integrity and do not
    inherit the legacy requirement for written solution steps. Short-answer
    items still require the process evidence used by semantic assessment.
    """
    evidence = _reviewer_evidence(item)
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    production_review = evidence.get("production_review") if isinstance(evidence.get("production_review"), dict) else {}
    rejection_reasons: list[str] = []
    fixed_answer = str(item.get("answer_format") or "") == "fixed_answer"
    if production_review.get("decision") != "accepted":
        rejection_reasons.append("production_semantic_review_not_accepted")
    if not item.get("node_id"):
        rejection_reasons.append("missing_graph_node_binding")
    if item.get("age_floor") not in {None, INCOMING_GRADE_7_AGE_FLOOR}:
        rejection_reasons.append("wrong_age_floor")
    if not str(item.get("prompt") or "").strip():
        rejection_reasons.append("missing_prompt")
    if not str(item.get("expected_answer") or "").strip():
        rejection_reasons.append("missing_specific_expected_answer")
    if not fixed_answer and len(item.get("solution_steps") or []) < 2:
        rejection_reasons.append("insufficient_solution_step_evidence")
    rejection_reasons.extend(_reviewer_evidence_rejection_reasons(item))
    prompt = str(item.get("prompt") or "")
    if is_low_signal_surface_prompt(item):
        rejection_reasons.append("low_signal_or_insulting_mechanical_prompt")
    if any(pattern in prompt for pattern in CHILD_FACING_META_PATTERNS) or any(
        pattern.search(prompt) for pattern in CHILD_FACING_META_REGEXES
    ):
        rejection_reasons.append("child_facing_generator_meta_language")
    rejection_reasons.extend(_identity_contract_rejection_reasons(item))
    approved = not rejection_reasons
    requires_reasoning = not fixed_answer
    no_mechanical_drill = evidence.get("not_mechanical_drill") is True and not is_low_signal_surface_prompt(item)
    return {
        "contract_version": QUESTION_PRODUCTION_CONTRACT_VERSION,
        "graph_version": item.get("graph_version") or source.get("graph_version") or "",
        "question_bank_version": item.get("question_bank_version") or source.get("question_bank_version") or item.get("item_version", ""),
        "review_status": "approved" if approved else "rejected",
        "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
        "reviewer_evidence": evidence,
        "age_floor": INCOMING_GRADE_7_AGE_FLOOR,
        "cognitive_level": _cognitive_level(str(item.get("kind", "")), str(item.get("variant_level", ""))),
        "item_purpose": _item_purpose(str(item.get("kind", ""))),
        "requires_reasoning": requires_reasoning,
        "has_high_signal_structure": evidence.get("diagnostic_structure") is True,
        "picture_level_challenge_labels": picture_level_challenge_labels(item),
        "problem_family_id": item.get("problem_family_id", ""),
        "core_stem_id": item.get("core_stem_id", ""),
        "problem_instance_id": item.get("problem_instance_id", ""),
        "node_alignment": item.get("node_alignment", {}),
        "identity_basis": _identity_basis_for_review(item),
        "requires_process_evidence": PROCESS_EVIDENCE_REQUIREMENTS if requires_reasoning else [],
        "no_mechanical_drill": no_mechanical_drill,
        "criteria": [
            "graph_node_bound",
            "incoming_grade_7_floor",
            "production_semantic_review_accepted",
            "fixed_answer_or_process_evidence_contract",
            "child_prompt_self_contained",
            "problem_family_core_stem_and_problem_instance_traceable",
        ],
        "rejection_reasons": rejection_reasons,
    }


def _apply_question_production_contract(
    item: dict[str, Any],
    node: dict[str, Any],
    *,
    question_type: str,
    graph_version: str = "",
    question_bank_version: str = QUESTION_BANK_VERSION,
) -> dict[str, Any]:
    item["age_floor"] = INCOMING_GRADE_7_AGE_FLOOR
    _attach_question_identity_contract(item, node, question_type)
    apply_question_lineage(
        item,
        graph_version=graph_version,
        question_bank_version=question_bank_version,
    )
    item["design_intent"] = {
        "designer_agent": QUESTION_DESIGNER_AGENT_KEY,
        "coordinator_agent": QUESTION_COORDINATOR_AGENT_KEY,
        "graph_version": item.get("graph_version", ""),
        "question_bank_version": item.get("question_bank_version", question_bank_version),
        "node_id": node["id"],
        "node_name": node.get("name", ""),
        "question_type": question_type,
        "problem_family_id": item["problem_family_id"],
        "core_stem_id": item["core_stem_id"],
        "problem_instance_id": item["problem_instance_id"],
        "node_alignment": item["node_alignment"],
        "identity_basis": _identity_basis_for_review(item),
        "target_breakpoint": _item_purpose(str(item.get("kind", ""))),
        "evidence_claims": {
            "primary_node_id": node["id"],
            "primary_node_name": node.get("name", ""),
            "question_type": question_type,
            "problem_family_id": item["problem_family_id"],
            "core_stem_id": item["core_stem_id"],
            "problem_instance_id": item["problem_instance_id"],
            "node_alignment_reason": item["node_alignment"]["reason"],
            "graph_version": item.get("graph_version", ""),
            "question_bank_version": item.get("question_bank_version", question_bank_version),
            "measured_capability": item["node_alignment"].get("measured_capability", ""),
            "node_local_anchor": item["node_alignment"].get("node_local_anchor", ""),
            "target_error_tags": item.get("target_error_tags", []),
            "requires": PROCESS_EVIDENCE_REQUIREMENTS,
            "evidence_rule": "孩子必须给出规则/关系、过程或表示、检验或错因说明，不能只靠最终答案证明掌握。",
        },
        "not_for": "低龄机械刷题、只看最终答案、脱离图谱的随机题",
    }
    item.setdefault("source", {})
    item["source"]["production_pipeline"] = {
        "contract_version": QUESTION_PRODUCTION_CONTRACT_VERSION,
        "designer_agent": QUESTION_DESIGNER_AGENT_KEY,
        "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
        "coordinator_agent": QUESTION_COORDINATOR_AGENT_KEY,
        "graph_version": item.get("graph_version", ""),
        "question_bank_version": item.get("question_bank_version", question_bank_version),
        "workflow": ["design_from_graph_node", "review_quality_gate", "activate_only_if_approved"],
    }
    if (
        item["source"].get("type") == "graph_generated"
        and item["source"].get("curated_manifest_id") == GRAPH_SEED_REVIEW_MANIFEST_ID
        and not isinstance(item["source"].get("reviewer_evidence"), dict)
    ):
        item["source"]["reviewer_evidence"] = curated_seed_reviewer_evidence(item)
    if (
        item["source"].get("type") == "evolved_from_attempt"
        and item["source"].get("evolution_strategy") in DETERMINISTIC_EVOLUTION_REVIEW_STRATEGIES
        and not isinstance(item["source"].get("reviewer_evidence"), dict)
    ):
        item["source"]["reviewer_evidence"] = deterministic_evolution_reviewer_evidence(item)
    quality = review_item_quality(item)
    item["quality"] = quality
    item["cognitive_level"] = quality["cognitive_level"]
    item["item_purpose"] = quality["item_purpose"]
    item["requires_reasoning"] = quality["requires_reasoning"]
    item["challenge_profile"] = {
        "picture_level": bool(quality["picture_level_challenge_labels"]),
        "labels": quality["picture_level_challenge_labels"],
    }
    item["review_agent_check"] = {
        "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
        "status": quality["review_status"],
        "rejection_reasons": quality["rejection_reasons"],
    }
    if quality["review_status"] != "approved":
        raise ValueError(f"Question item {item.get('id')} rejected by quality gate: {quality['rejection_reasons']}")
    return item


def _is_v12_external_active_item(item: dict[str, Any]) -> bool:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return (
        item.get("item_version") == QUESTION_BANK_V12_VERSION
        or item.get("question_bank_version") == QUESTION_BANK_V12_VERSION
        or source.get("external_source_type") == V12_SOURCE_TYPE
    )


def production_category_for_coverage_role(coverage_role: Any) -> str:
    return (
        PRODUCTION_CATEGORY_CHALLENGING_PRACTICE
        if str(coverage_role or "") == "transfer_or_stretch"
        else PRODUCTION_CATEGORY_TEACHING_DIAGNOSTIC
    )


def evidence_mode_for_coverage_role(coverage_role: Any) -> str:
    role = str(coverage_role or "")
    if role == "transfer_or_stretch":
        return EVIDENCE_MODE_TRANSFER_SIGNAL_ONLY
    if role == "confirmation_or_variant":
        return EVIDENCE_MODE_NO_HINT_CONFIRMATION
    return EVIDENCE_MODE_GUIDED_FORMATIVE


def evidence_mode_for_production_mode(production_mode: Any) -> str:
    mapping = {
        "guided_formative": EVIDENCE_MODE_GUIDED_FORMATIVE,
        "no_hint_confirmation": EVIDENCE_MODE_NO_HINT_CONFIRMATION,
        "challenging_practice": EVIDENCE_MODE_TRANSFER_SIGNAL_ONLY,
    }
    mode = str(production_mode or "")
    if mode not in mapping:
        raise ValueError(f"unsupported production_mode: {mode or 'missing'}")
    return mapping[mode]


def production_evidence_mode_rejection_reasons(item: dict[str, Any]) -> list[str]:
    category = str(item.get("production_category") or "")
    evidence_mode = str(item.get("evidence_mode") or "")
    lineage = (
        item.get("production_lineage")
        if isinstance(item.get("production_lineage"), dict)
        else {}
    )
    coverage_role = str(lineage.get("coverage_role") or item.get("coverage_role") or "")
    production_mode = str(
        lineage.get("production_mode") or item.get("production_mode") or ""
    )
    reasons: list[str] = []
    if category == PRODUCTION_CATEGORY_TEACHING_DIAGNOSTIC:
        if evidence_mode not in TEACHING_DIAGNOSTIC_EVIDENCE_MODES:
            reasons.append("teaching_diagnostic_evidence_mode_invalid")
    elif category == PRODUCTION_CATEGORY_CHALLENGING_PRACTICE:
        if evidence_mode != EVIDENCE_MODE_TRANSFER_SIGNAL_ONLY:
            reasons.append("challenging_practice_evidence_mode_invalid")
    else:
        reasons.append("formal_production_category_invalid")
    if production_mode:
        try:
            expected_evidence_mode = evidence_mode_for_production_mode(
                production_mode
            )
        except ValueError:
            reasons.append("production_mode_invalid")
        else:
            if evidence_mode != expected_evidence_mode:
                reasons.append("production_mode_evidence_mode_mismatch")
    return reasons


def formal_purpose_for_evidence_mode(evidence_mode: Any) -> str:
    mapping = {
        EVIDENCE_MODE_GUIDED_FORMATIVE: "teaching",
        EVIDENCE_MODE_NO_HINT_CONFIRMATION: "diagnostic",
        EVIDENCE_MODE_TRANSFER_SIGNAL_ONLY: "practice",
    }
    mode = str(evidence_mode or "")
    if mode not in mapping:
        raise ValueError(f"unsupported formal evidence_mode: {mode or 'missing'}")
    return mapping[mode]


def formal_child_surface_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt": item.get("prompt"),
        "answer_format": item.get("answer_format"),
        "interaction_schema": item.get("interaction_schema") or {},
        "child_surface_design": item.get("child_surface_design") or {},
        "question_visual_asset_ref": item.get("question_visual_asset_ref") or "",
        "question_visual": item.get("question_visual") or {},
    }


def formal_child_surface_sha256(item: dict[str, Any]) -> str:
    payload = json.dumps(
        formal_child_surface_payload(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prepare_formal_activation_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """Freeze the exact child/runtime semantic payload before any live review."""
    candidate = json.loads(json.dumps(item, ensure_ascii=False))
    evidence_mode = str(candidate.get("evidence_mode") or "")
    purpose = formal_purpose_for_evidence_mode(evidence_mode)
    if not candidate.get("variant_level"):
        candidate["variant_level"] = candidate.get("difficulty")
    if not candidate.get("expected_answer"):
        candidate["expected_answer"] = candidate.get("standard_answer")
    if not candidate.get("kind"):
        candidate["kind"] = {
            EVIDENCE_MODE_GUIDED_FORMATIVE: "standard_example",
            EVIDENCE_MODE_NO_HINT_CONFIRMATION: "misconception_probe",
            EVIDENCE_MODE_TRANSFER_SIGNAL_ONLY: "stretch_transfer",
        }[evidence_mode]
    if question_visuals.embedded_visual_required(candidate):
        visual = question_visuals.validated_embedded_visual_for_question(candidate)
        if visual is None:
            raise ValueError("formal candidate requires a validated embedded question visual")
        candidate["question_visual"] = visual
    reasons = production_evidence_mode_rejection_reasons(candidate)
    if reasons:
        raise ValueError("formal evidence contract rejected: " + ",".join(reasons))
    usage_policy = candidate.get("usage_policy")
    if not isinstance(usage_policy, dict):
        raise ValueError("formal candidate requires usage_policy before review")
    allowed_purposes = list(usage_policy.get("allowed_purposes") or [])
    if allowed_purposes != [purpose]:
        raise ValueError(
            "formal candidate purpose must be exclusive and match evidence_mode"
        )
    required = (
        "id",
        "node_id",
        "question_type",
        "kind",
        "difficulty",
        "variant_level",
        "production_category",
        "evidence_mode",
        "prompt",
        "answer_format",
        "expected_answer",
    )
    missing = [field for field in required if candidate.get(field) in (None, "")]
    if missing:
        raise ValueError("formal canonical payload missing fields: " + ",".join(missing))
    candidate["parent_observation"] = str(candidate.get("parent_observation") or "")
    try:
        estimated_minutes = int(candidate.get("estimated_minutes") or 3)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "formal candidate estimated_minutes must be a positive integer"
        ) from exc
    if isinstance(candidate.get("estimated_minutes"), bool) or estimated_minutes <= 0:
        raise ValueError("formal candidate estimated_minutes must be a positive integer")
    candidate["estimated_minutes"] = estimated_minutes
    canonical = formal_reviewed_content_payload(candidate)
    candidate["canonical_activation_payload"] = canonical
    candidate["canonical_activation_payload_sha256"] = formal_reviewed_content_sha256(
        candidate
    )
    candidate["question_surface_sha256"] = formal_child_surface_sha256(candidate)
    return candidate


def validate_independent_live_review_receipts(
    receipts: Any,
    *,
    expected_candidate_sha256: str = "",
) -> dict[str, Any]:
    errors: list[str] = []
    values = receipts if isinstance(receipts, list) else []
    if not isinstance(receipts, list):
        errors.append("independent_review_receipts_must_be_list")
    required = INDEPENDENT_LIVE_REVIEW_MIN_RECEIPTS
    if len(values) < required:
        errors.append("independent_review_receipt_count_below_minimum")
    if len(values) > required + 1:
        errors.append("independent_review_receipt_count_above_maximum")

    profiles: list[str] = []
    run_ids: list[str] = []
    invocation_ids: list[str] = []
    context_ids: list[str] = []
    response_hashes: list[str] = []
    confidences: dict[str, float] = {}
    for index, receipt in enumerate(values):
        if not isinstance(receipt, dict):
            errors.append(f"independent_review_receipt_invalid:{index}")
            continue
        profile = str(receipt.get("review_profile") or "")
        run_id = str(receipt.get("run_id") or "")
        invocation_id = str(receipt.get("invocation_id") or "")
        context_id = str(receipt.get("context_id") or "")
        raw_response_sha256 = str(receipt.get("raw_response_sha256") or "").lower()
        status = str(receipt.get("status") or "").upper()
        provider_mode = str(receipt.get("provider_mode") or "")
        profiles.append(profile)
        run_ids.append(run_id)
        invocation_ids.append(invocation_id)
        context_ids.append(context_id)
        response_hashes.append(raw_response_sha256)
        if not profile:
            errors.append(f"independent_review_profile_missing:{index}")
        if not run_id:
            errors.append(f"independent_review_run_id_missing:{index}")
        if not invocation_id:
            errors.append(f"independent_review_invocation_id_missing:{index}")
        if not context_id:
            errors.append(f"independent_review_context_id_missing:{index}")
        if not re.fullmatch(r"[0-9a-f]{64}", raw_response_sha256):
            errors.append(f"independent_review_raw_response_sha256_invalid:{index}")
        if provider_mode != "live_model":
            errors.append(f"independent_review_not_live_model:{index}")
        if status != "PASS":
            errors.append(f"independent_review_not_passed:{index}:{status or 'MISSING'}")
        confidence = receipt.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            errors.append(f"independent_review_confidence_invalid:{index}")
        else:
            confidences[profile] = float(confidence)
        if (
            expected_candidate_sha256
            and str(receipt.get("candidate_sha256") or "") != expected_candidate_sha256
        ):
            errors.append(f"independent_review_candidate_sha256_mismatch:{index}")

    required_profiles = INDEPENDENT_LIVE_REVIEW_REQUIRED_PROFILES
    primary_profiles = {
        profile
        for profile in profiles
        if profile != INDEPENDENT_LIVE_REVIEW_ADJUDICATOR_PROFILE
    }
    if primary_profiles != required_profiles:
        errors.append("independent_review_required_profiles_mismatch")
    allowed_profiles = required_profiles | {
        INDEPENDENT_LIVE_REVIEW_ADJUDICATOR_PROFILE
    }
    if any(profile not in allowed_profiles for profile in profiles):
        errors.append("independent_review_profile_not_allowed")
    if len(profiles) != len(set(profiles)):
        errors.append("independent_review_profiles_not_distinct")
    if len(set(run_ids)) != len(run_ids):
        errors.append("independent_review_run_ids_not_distinct")
    if len(set(invocation_ids)) != len(invocation_ids):
        errors.append("independent_review_invocation_ids_not_distinct")
    if len(set(context_ids)) != len(context_ids):
        errors.append("independent_review_context_ids_not_distinct")
    if len(set(response_hashes)) != len(response_hashes):
        errors.append("independent_review_raw_responses_not_distinct")

    primary_confidences = [
        confidences.get(profile)
        for profile in sorted(required_profiles)
    ]
    below_minimum = any(
        confidence is not None
        and confidence < INDEPENDENT_LIVE_REVIEW_MIN_CONFIDENCE
        for confidence in primary_confidences
    )
    adjudication_required = any(
        confidence is not None
        and INDEPENDENT_LIVE_REVIEW_MIN_CONFIDENCE
        <= confidence
        < INDEPENDENT_LIVE_REVIEW_DIRECT_PASS_CONFIDENCE
        for confidence in primary_confidences
    )
    adjudicator_present = (
        INDEPENDENT_LIVE_REVIEW_ADJUDICATOR_PROFILE in profiles
    )
    adjudication_confidence = confidences.get(
        INDEPENDENT_LIVE_REVIEW_ADJUDICATOR_PROFILE
    )
    adjudicator_receipt = next(
        (
            receipt
            for receipt in values
            if isinstance(receipt, dict)
            and receipt.get("review_profile")
            == INDEPENDENT_LIVE_REVIEW_ADJUDICATOR_PROFILE
        ),
        {},
    )
    adjudication_verified = bool(
        adjudication_required
        and adjudicator_present
        and adjudication_confidence is not None
        and adjudication_confidence
        >= INDEPENDENT_LIVE_REVIEW_DIRECT_PASS_CONFIDENCE
        and str(adjudicator_receipt.get("status") or "").upper() == "PASS"
    )
    if below_minimum:
        errors.append("independent_review_confidence_below_minimum")
    if adjudication_required and not adjudicator_present:
        errors.append("independent_review_adjudication_required")
    elif adjudication_required and not adjudication_verified:
        errors.append("independent_review_adjudication_not_verified")
    elif not adjudication_required and adjudicator_present:
        errors.append("independent_review_adjudication_unexpected")
    unique_errors = list(dict.fromkeys(errors))
    return {
        "status": "PASS" if not unique_errors else "BLOCKED",
        "verified": not unique_errors,
        "minimum_receipts": required,
        "receipt_count": len(values),
        "distinct_review_profile_count": len(set(profiles)),
        "distinct_run_id_count": len(set(run_ids)),
        "distinct_invocation_id_count": len(set(invocation_ids)),
        "distinct_context_id_count": len(set(context_ids)),
        "distinct_raw_response_sha256_count": len(set(response_hashes)),
        "adjudication_required": adjudication_required,
        "adjudication_verified": adjudication_verified,
        "errors": unique_errors,
    }


def formal_reviewed_content_payload(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    candidate = raw if raw.get("source") else item
    lineage = (
        candidate.get("production_lineage")
        if isinstance(candidate.get("production_lineage"), dict)
        else {}
    )
    payload = {
        "id": candidate.get("id"),
        "node_id": candidate.get("node_id"),
        "secondary_node_ids": list(candidate.get("secondary_node_ids") or []),
        "question_type": candidate.get("question_type"),
        "kind": candidate.get("kind"),
        "difficulty": candidate.get("difficulty") or candidate.get("variant_level"),
        "variant_level": candidate.get("variant_level"),
        "production_category": candidate.get("production_category"),
        "evidence_mode": candidate.get("evidence_mode"),
        "prompt": candidate.get("prompt"),
        "answer_format": candidate.get("answer_format"),
        "expected_answer": candidate.get("expected_answer"),
        "standard_answer": candidate.get("standard_answer"),
        "accepted_alternatives": list(candidate.get("accepted_alternatives") or []),
        "required_evidence": list(candidate.get("required_evidence") or []),
        "key_score_points": list(candidate.get("key_score_points") or []),
        "solution_steps": list(candidate.get("solution_steps") or []),
        "target_error_tags": list(candidate.get("target_error_tags") or []),
        "rollback_candidates": list(candidate.get("rollback_candidates") or []),
        "rollback_candidate_node_ids": list(
            candidate.get("rollback_candidate_node_ids") or []
        ),
        "rollback_candidate_relations": list(
            candidate.get("rollback_candidate_relations") or []
        ),
        "estimated_minutes": candidate.get("estimated_minutes"),
        "parent_observation": candidate.get("parent_observation"),
        "interaction_schema": candidate.get("interaction_schema") or {},
        "child_surface_design": candidate.get("child_surface_design") or {},
        "question_visual_asset_ref": candidate.get("question_visual_asset_ref") or "",
        "question_visual": candidate.get("question_visual") or {},
        "math_core_signature": candidate.get("math_core_signature"),
        "response_domain_contract": candidate.get("response_domain_contract") or {},
        "usage_policy": candidate.get("usage_policy") or {},
    }
    visual_authority = lineage.get("visual_authority")
    if isinstance(visual_authority, dict) and visual_authority:
        payload["visual_authority"] = visual_authority
        payload["item_visual_authority_sha256"] = str(
            lineage.get("item_visual_authority_sha256") or ""
        )
    measurement_authority = lineage.get("measurement_authority")
    if isinstance(measurement_authority, dict) and measurement_authority:
        payload["measurement_authority"] = measurement_authority
        payload["item_measurement_authority_sha256"] = str(
            lineage.get("item_measurement_authority_sha256") or ""
        )
    visual_adjudication = lineage.get("visual_adjudication")
    if isinstance(visual_adjudication, dict) and visual_adjudication:
        payload["visual_adjudication"] = visual_adjudication
        payload["item_visual_adjudication_sha256"] = str(
            lineage.get("item_visual_adjudication_sha256") or ""
        )
    return payload


def formal_reviewed_content_sha256(item: dict[str, Any]) -> str:
    payload = json.dumps(
        formal_reviewed_content_payload(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


FORMAL_CONTENT_ENVELOPE_SCHEMA_VERSION = (
    "2026-07-24.codex-admin.staged-content-envelope.v1"
)
_FORMAL_CONTENT_ENVELOPE_QUALITY_FIELDS = {
    "activation_eligible",
    "content_envelope_sha256",
    "review_evidence",
    "review_status",
    "staging_receipts",
    "status",
}


def formal_content_envelope_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Freeze every candidate field reviewed before staging metadata is attached."""
    content = json.loads(json.dumps(item, ensure_ascii=False))
    content.pop("question_bank_version", None)
    content["source_type"] = str(content.get("source_type") or "ai_original")
    quality = dict(
        content.get("quality") if isinstance(content.get("quality"), dict) else {}
    )
    for field in _FORMAL_CONTENT_ENVELOPE_QUALITY_FIELDS:
        quality.pop(field, None)
    if quality:
        content["quality"] = quality
    else:
        content.pop("quality", None)
    return {
        "schema_version": FORMAL_CONTENT_ENVELOPE_SCHEMA_VERSION,
        "item": content,
    }


def formal_content_envelope_sha256(item: dict[str, Any]) -> str:
    payload = json.dumps(
        formal_content_envelope_payload(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _formal_admin_active_quality(item: dict[str, Any]) -> dict[str, Any] | None:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    candidate = raw if raw.get("source") else item
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    if source.get("formal_production_source") != FORMAL_ADMIN_PRODUCTION_SOURCE:
        return None
    quality = candidate.get("quality") if isinstance(candidate.get("quality"), dict) else {}
    formal_review = source.get("formal_review") if isinstance(source.get("formal_review"), dict) else {}
    review_evidence = formal_review.get("review_evidence") if isinstance(formal_review.get("review_evidence"), dict) else {}
    receipts = review_evidence.get("receipts") if isinstance(review_evidence.get("receipts"), dict) else {}
    independent_receipts = review_evidence.get("independent_live_model_reviews")
    semantic_receipt = receipts.get("semantic_qa_review") or receipts.get("guanzhi_qa_review") or {}
    reasons: list[str] = []
    category = str(candidate.get("production_category") or "")
    if category not in FORMAL_PRODUCTION_CATEGORIES:
        reasons.append("formal_production_category_invalid")
    reasons.extend(production_evidence_mode_rejection_reasons(candidate))
    if candidate.get("item_version") != source.get("question_bank_version"):
        reasons.append("formal_question_bank_version_mismatch")
    if not str(source.get("graph_version") or ""):
        reasons.append("formal_graph_version_missing")
    if formal_review.get("contract_version") != FORMAL_ADMIN_REVIEW_CONTRACT_VERSION:
        reasons.append("formal_review_contract_version_mismatch")
    if formal_review.get("reviewed_content_sha256") != formal_reviewed_content_sha256(candidate):
        reasons.append("formal_reviewed_content_digest_mismatch")
    required_receipts = {
        "deterministic_expert_review": receipts.get("deterministic_expert_review") or {},
        "model_expert_board_review": receipts.get("model_expert_board_review") or {},
        "semantic_qa_review": semantic_receipt,
    }
    for receipt_name, receipt in required_receipts.items():
        if not isinstance(receipt, dict) or receipt.get("status") != "PASS":
            reasons.append(f"formal_{receipt_name}_not_passed")
    model_receipt = required_receipts["model_expert_board_review"]
    if model_receipt.get("role") != "live_model_expert_board_review" or model_receipt.get("provider_mode") != "live_model":
        reasons.append("formal_model_expert_review_not_live_model")
    if semantic_receipt.get("role") != "live_model_semantic_qa_review" or semantic_receipt.get("provider_mode") != "live_model":
        reasons.append("formal_semantic_qa_not_live_model")
    independent_validation = validate_independent_live_review_receipts(
        independent_receipts,
        expected_candidate_sha256=str(formal_review.get("reviewed_content_sha256") or ""),
    )
    reasons.extend(
        f"formal_{error}" for error in independent_validation.get("errors") or []
    )
    expected_quality = {
        "review_status": "approved",
        "activation_eligible": True,
        "age_floor": INCOMING_GRADE_7_AGE_FLOOR,
        "no_mechanical_drill": True,
    }
    for key, expected in expected_quality.items():
        if quality.get(key) != expected:
            reasons.append(f"formal_quality_{key}_mismatch")
    return {
        **quality,
        "contract_version": FORMAL_ADMIN_REVIEW_CONTRACT_VERSION,
        "review_status": "rejected" if reasons else "approved",
        "rejection_reasons": reasons,
    }


def _v12_active_quality_rejection_reasons(item: dict[str, Any]) -> list[str]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    review = source.get("review_artifact") if isinstance(source.get("review_artifact"), dict) else {}
    evidence = review.get("reviewer_evidence") if isinstance(review.get("reviewer_evidence"), dict) else {}
    reasons: list[str] = []
    if item.get("item_version") != QUESTION_BANK_V12_VERSION:
        reasons.append("v12_item_version_mismatch")
    if source.get("external_source_type") != V12_SOURCE_TYPE:
        reasons.append("v12_external_source_type_missing")
    expected_quality = {
        "contract_version": V12_ACTIVE_QUALITY_CONTRACT_VERSION,
        "quality_basis": V12_STRUCTURED_QUALITY_BASIS,
        "question_bank_version": QUESTION_BANK_V12_VERSION,
        "review_status": "approved",
        "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
        "reviewer_contract_version": V12_REVIEWER_CONTRACT_VERSION,
        "semantic_evidence_version": V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "semantic_ux_approved": True,
        "age_floor": INCOMING_GRADE_7_AGE_FLOOR,
        "requires_reasoning": True,
        "has_high_signal_structure": True,
        "no_mechanical_drill": True,
    }
    for key, value in expected_quality.items():
        if quality.get(key) != value:
            reasons.append(f"v12_quality_{key}_mismatch")
    expected_review = {
        "agent_key": QUESTION_REVIEWER_AGENT_KEY,
        "phase": "question_review",
        "artifact_role": "reviewer",
        "contract_key": "math_question_bank_v12_reviewer_batch",
        "contract_version": V12_REVIEWER_CONTRACT_VERSION,
        "prompt_version_id": V12_REVIEWER_PROMPT_VERSION_ID,
        "response_schema_version": V12_REVIEWER_RESPONSE_SCHEMA_VERSION,
        "semantic_evidence_version": V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "verdict": "approved",
    }
    for key, value in expected_review.items():
        if review.get(key) != value:
            reasons.append(f"v12_review_{key}_mismatch")
    if review.get("candidate_sha256") != source.get("external_candidate_sha256"):
        reasons.append("v12_external_candidate_sha256_mismatch")
    if review.get("semantic_evidence_sha256") != source.get("semantic_evidence_sha256"):
        reasons.append("v12_source_semantic_evidence_sha256_mismatch")
    if review.get("semantic_evidence_sha256") != quality.get("semantic_evidence_sha256"):
        reasons.append("v12_quality_semantic_evidence_sha256_mismatch")
    if source.get("semantic_evidence_version") != V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION:
        reasons.append("v12_source_semantic_evidence_version_mismatch")
    if quality.get("external_candidate_sha256") != source.get("external_candidate_sha256"):
        reasons.append("v12_quality_external_candidate_sha256_mismatch")
    if _v12_score(review, "confidence") < V12_REVIEW_MIN_CONFIDENCE:
        reasons.append("v12_review_confidence_below_gate")
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    for score_key in V12_REVIEW_SCORE_KEYS:
        if _v12_score(scores, score_key) < V12_REVIEW_MIN_SCORE:
            reasons.append(f"v12_review_score_below_gate:{score_key}")
    for flag in REVIEWER_EVIDENCE_FLAGS:
        if evidence.get(flag) is not True:
            reasons.append(f"v12_reviewer_evidence_failed:{flag}")
    reasons.extend(
        f"v12_{detail}"
        for detail in v12_semantic_evidence_errors(
            item,
            review.get("semantic_evidence"),
            expected_version=V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        )
    )
    reasons.extend(_identity_contract_rejection_reasons(item))
    return reasons


def review_item_quality_for_active_use(item: dict[str, Any]) -> dict[str, Any]:
    formal_quality = _formal_admin_active_quality(item)
    if formal_quality is not None:
        return formal_quality
    if not _is_v12_external_active_item(item):
        return review_item_quality(item)
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    rejection_reasons = _v12_active_quality_rejection_reasons(item)
    return {
        **quality,
        "contract_version": V12_ACTIVE_QUALITY_CONTRACT_VERSION,
        "quality_basis": V12_STRUCTURED_QUALITY_BASIS,
        "review_status": "rejected" if rejection_reasons else "approved",
        "rejection_reasons": rejection_reasons,
    }


def validate_active_item_quality(item: dict[str, Any]) -> None:
    source_type = item.get("source_type") or item.get("source", {}).get("type")
    version = item.get("item_version", "")
    if source_type not in {"graph_generated", "evolved"}:
        return
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    if source_type == "evolved" and source.get("evidence_status") == "invalidated":
        raise ValueError(f"Active question item {item.get('id')} is based on invalidated evidence")
    formal_quality = _formal_admin_active_quality(item)
    if formal_quality is not None:
        if formal_quality["review_status"] != "approved":
            raise ValueError(
                f"Active formal question item {item.get('id')} fails review gate: "
                f"{formal_quality['rejection_reasons']}"
            )
        return
    if _is_v12_external_active_item(item):
        reviewed = review_item_quality_for_active_use(item)
        if reviewed["review_status"] != "approved":
            raise ValueError(f"Active V12 question item {item.get('id')} fails structured quality gate: {reviewed['rejection_reasons']}")
        return
    if version not in {QUESTION_BANK_VERSION, EVOLVED_ITEM_VERSION}:
        return
    recomputed = review_item_quality(item)
    if recomputed["review_status"] != "approved":
        raise ValueError(f"Active question item {item.get('id')} fails current quality gate: {recomputed['rejection_reasons']}")
    quality = item.get("quality") or item.get("review_agent_check") or {}
    if quality.get("review_status") != "approved":
        raise ValueError(f"Active question item {item.get('id')} is not reviewer-approved")
    if quality.get("age_floor") != INCOMING_GRADE_7_AGE_FLOOR:
        raise ValueError(f"Active question item {item.get('id')} has invalid age floor")
    if quality.get("requires_reasoning") is not True:
        raise ValueError(f"Active question item {item.get('id')} does not require reasoning")
    if quality.get("no_mechanical_drill") is not True:
        raise ValueError(f"Active question item {item.get('id')} is a mechanical drill")


def is_item_approved_for_active_use(item: dict[str, Any]) -> bool:
    source_type = item.get("source_type") or item.get("source", {}).get("type")
    if source_type not in {"graph_generated", "evolved"}:
        return True
    raw = item.get("raw", {}) if isinstance(item.get("raw"), dict) else {}
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    raw_source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    if source_type == "evolved" and (
        source.get("evidence_status") == "invalidated"
        or raw_source.get("evidence_status") == "invalidated"
    ):
        return False
    formal_quality = _formal_admin_active_quality(item)
    if formal_quality is not None:
        return formal_quality["review_status"] == "approved"
    if _is_v12_external_active_item(item):
        return review_item_quality_for_active_use(item)["review_status"] == "approved"
    quality = item.get("quality") or raw.get("quality") or item.get("review_agent_check") or raw.get("review_agent_check") or {}
    if review_item_quality(item)["review_status"] != "approved":
        return False
    return (
        quality.get("review_status") == "approved"
        and quality.get("age_floor") == INCOMING_GRADE_7_AGE_FLOOR
        and quality.get("requires_reasoning") is True
        and quality.get("no_mechanical_drill") is True
    )


def validate_question_bank_collection(items: list[dict[str, Any]]) -> None:
    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    picture_stem_nodes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in items:
        if item.get("source_type") == "graph_generated" and item.get("item_version") == QUESTION_BANK_VERSION:
            by_node[str(item.get("node_id") or "")].append(item)
            for label in picture_level_challenge_labels(item):
                picture_stem_nodes[(label, canonical_core_signature(item))].add(str(item.get("node_id") or ""))
    errors: list[str] = []
    for node_id, node_items in sorted(by_node.items()):
        family_counts = Counter(str(item.get("problem_family_id") or "") for item in node_items)
        core_counts = Counter(str(item.get("core_stem_id") or "") for item in node_items)
        canonical_core_counts = Counter(canonical_core_signature(item) for item in node_items)
        node_local_count = sum(1 for item in node_items if is_node_local_mainline_item(item))
        picture_items = [item for item in node_items if picture_level_challenge_labels(item)]
        picture_label_counts = Counter(
            label
            for item in picture_items
            for label in picture_level_challenge_labels(item)
        )
        if len(node_items) != QUESTIONS_PER_GRAPH_NODE:
            errors.append(f"{node_id}: {len(node_items)} items, expected {QUESTIONS_PER_GRAPH_NODE}")
        if node_local_count < MIN_NODE_LOCAL_MAINLINE_ITEMS_PER_NODE:
            errors.append(f"{node_id}: {node_local_count} node-local mainline items, minimum {MIN_NODE_LOCAL_MAINLINE_ITEMS_PER_NODE}")
        if len(picture_items) > MAX_PICTURE_LEVEL_CHALLENGES_PER_NODE:
            errors.append(f"{node_id}: {len(picture_items)} picture-level extensions, cap {MAX_PICTURE_LEVEL_CHALLENGES_PER_NODE}")
        if max(picture_label_counts.values() or [0]) > MAX_SAME_PICTURE_CHALLENGE_LABEL_PER_NODE:
            label, count = picture_label_counts.most_common(1)[0]
            errors.append(f"{node_id}: picture-level label {label} repeats {count}, cap {MAX_SAME_PICTURE_CHALLENGE_LABEL_PER_NODE}")
        if len(family_counts) < MIN_PROBLEM_FAMILIES_PER_NODE:
            errors.append(f"{node_id}: {len(family_counts)} problem families, minimum {MIN_PROBLEM_FAMILIES_PER_NODE}")
        if max(family_counts.values() or [0]) > MAX_PROBLEM_FAMILY_REPEAT_PER_NODE:
            errors.append(f"{node_id}: one problem family repeats {max(family_counts.values())}, cap {MAX_PROBLEM_FAMILY_REPEAT_PER_NODE}")
        if len(core_counts) < 12:
            errors.append(f"{node_id}: {len(core_counts)} core stems, minimum 12")
        if max(core_counts.values() or [0]) > MAX_CORE_STEM_REPEAT_PER_NODE:
            errors.append(f"{node_id}: one core stem repeats {max(core_counts.values())}, cap {MAX_CORE_STEM_REPEAT_PER_NODE}")
        if len(canonical_core_counts) < MIN_CANONICAL_CORE_STEMS_PER_NODE:
            errors.append(f"{node_id}: {len(canonical_core_counts)} canonical core stems, minimum {MIN_CANONICAL_CORE_STEMS_PER_NODE}")
        if max(canonical_core_counts.values() or [0]) > MAX_CORE_STEM_REPEAT_PER_NODE:
            signature, count = canonical_core_counts.most_common(1)[0]
            errors.append(f"{node_id}: canonical core stem {signature} repeats {count}, cap {MAX_CORE_STEM_REPEAT_PER_NODE}")
    for (label, signature), node_ids in sorted(picture_stem_nodes.items()):
        if len(node_ids) > MAX_SAME_PICTURE_CHALLENGE_STEM_NODES:
            errors.append(
                f"picture-level stem {label}/{signature} appears on {len(node_ids)} nodes, cap {MAX_SAME_PICTURE_CHALLENGE_STEM_NODES}"
            )
    if errors:
        sample = "; ".join(errors[:8])
        raise ValueError(f"Question bank collection failed node-level quality gate: {sample}")


def _node_essence(node: dict[str, Any]) -> str:
    return (
        node.get("teaching_contract", {}).get("one_sentence_essence")
        or node.get("essence_for_child")
        or node.get("name")
        or "把规则、关系、步骤和检验说清楚"
    )


def _generated_diagnostic_example_for(
    node: dict[str, Any],
    question_type: str,
    kind: str,
    offset: int,
) -> dict[str, Any]:
    qtype = str(question_type or node.get("name") or "数学关系")
    context = _concrete_question_context(node, qtype, offset, kind=kind)
    templates = [
        {
            "prompt": f"{context['problem']} 请写出关键规则，完成解答，并用 {context['check']} 检验。",
            "answer": f"{context['answer']} 关键规则：{context['rule']} 检验：{context['check']}",
            "format": "规则 + 过程 + 答案 + 检验",
            "steps": ["写出关键规则。", "完成计算或判断。", "用指定方法检验结论。"],
        },
        {
            "prompt": f"某同学这样做：{context['wrong_solution']} 请指出错在哪里，写出正确过程，并说明错因。",
            "answer": f"错因：{context['wrong_reason']} 正确过程与结论：{context['answer']} 检验：{context['check']}",
            "format": "错因定位 + 正确过程 + 结论",
            "steps": ["定位错误步骤。", "说明错误破坏了哪条规则。", "写出正确过程和结论。"],
        },
        {
            "prompt": f"比较两种做法：A：{context['method_a']}；B：{context['method_b']}。请判断哪种更稳，并完成本题：{context['problem']}",
            "answer": f"A更稳。理由：{context['rule']} B的风险：{context['wrong_reason']} 本题结论：{context['answer']}",
            "format": "方法比较 + 选择理由 + 解答",
            "steps": ["比较两种方法的适用条件。", "排除风险更高的方法。", "用更稳的方法解答。"],
        },
        {
            "prompt": f"请先想清楚规则：{context['rule']} 题目：{context['variant_problem']} 写出判断和理由。",
            "answer": f"使用规则：{context['rule']} 结论：{context['variant_answer']}",
            "format": "规则判断 + 解答理由",
            "steps": ["确认要用的数学规则。", "根据题目条件求解。", "写出判断理由。"],
        },
        {
            "prompt": f"把题意转成 {context['representation']}：{context['problem']} 请写出转换后的关系，再解答。",
            "answer": f"可转成：{context['representation']}。关系或规则：{context['rule']} 结论：{context['answer']}",
            "format": "表示转换 + 关系说明 + 解答",
            "steps": ["选择表示方式。", "把题中关系转换过去。", "依据转换结果解答。"],
        },
        {
            "prompt": f"{context['problem']} 如果少看“{context['condition']}”，会得到什么错误判断？请说明必要条件并完成。",
            "answer": f"必要条件：{context['condition']}。少看它会导致：{context['wrong_reason']} 正确结论：{context['answer']}",
            "format": "必要条件 + 错误风险 + 正确解答",
            "steps": ["圈出必要条件。", "说明少看条件的后果。", "带着完整条件解答。"],
        },
        {
            "prompt": f"已知本题正确结论是“{context['short_answer']}”。请反推至少两步过程证据，并代回题目条件检验：{context['problem']}",
            "answer": f"至少应反推出规则：{context['rule']}；关键过程能得到：{context['answer']}；检验：{context['check']}",
            "format": "反推过程 + 条件检验",
            "steps": ["从结论反推关键关系。", "补出必要步骤。", "代回题目条件检验。"],
        },
        {
            "prompt": f"先估算或判断合理范围，再完成：{context['problem']} 请说明“{context['implausible_answer']}”为什么不可能。",
            "answer": f"不可能答案：{context['implausible_answer']}，原因：{context['wrong_reason']} 合理结论：{context['answer']} 估算/检查：{context['check']}",
            "format": "估算/范围 + 排除 + 解答",
            "steps": ["先判断合理范围。", "排除不可能答案。", "完成精确解答。"],
        },
        {
            "prompt": f"判断这个说法是否成立：“{context['bad_rule']}”。请用本题数据反驳或修正，并完成：{context['problem']}",
            "answer": f"该说法不成立或不严谨。修正规则：{context['rule']} 本题数据支持：{context['answer']} 常见错因：{context['wrong_reason']}",
            "format": "判断 + 反例/修正 + 解答",
            "steps": ["判断说法是否过度泛化。", "用题中数据说明原因。", "给出修正后的解答。"],
        },
        {
            "prompt": f"{context['problem']} 请给出两种解法或两种表示，并比较它们各自适合什么情况。",
            "answer": f"一种做法：{context['method_a']}。另一种表示：{context['representation']}。结论：{context['answer']} 易错点：{context['common_mistake']}",
            "format": "两法/两表示 + 答案 + 风险点",
            "steps": ["给出第一种解法或表示。", "给出第二种解法或表示。", "指出共同结论和易错点。"],
        },
        {
            "prompt": f"下面答案不完整：“{context['incomplete_answer']}”。请补上缺失的依据、过程和检验。",
            "answer": f"完整答案应补出规则：{context['rule']}；过程和结论：{context['answer']}；检验：{context['check']}",
            "format": "补依据 + 补过程 + 补检验",
            "steps": ["判断缺少哪类依据。", "补出关键过程。", "写出检验方法。"],
        },
        {
            "prompt": f"这题应选择哪种模型或规则：{context['rule_options']}？请排除不适用的一种，再解答：{context['problem']}",
            "answer": f"应选择：{context['rule']}。排除另一种的理由：{context['wrong_reason']} 本题结论：{context['answer']}",
            "format": "模型选择 + 排除理由 + 解答",
            "steps": ["读题并选择模型。", "说明被排除模型为什么不适用。", "用正确模型解答。"],
        },
        {
            "prompt": f"{context['problem']} 请专门检查符号、单位、括号或维度，并指出最容易丢分的地方。",
            "answer": f"结论：{context['answer']} 需要检查：{context['condition']}。最容易丢分：{context['common_mistake']}",
            "format": "符号/单位/维度审查 + 解答",
            "steps": ["检查符号、单位、括号或维度。", "修正可能错误。", "写出答案和易错点。"],
        },
        {
            "prompt": f"解题前先标出一个高风险步骤：“{context['common_mistake']}”。再完成本题，并按这个风险点检查：{context['problem']}",
            "answer": f"高风险步骤：{context['common_mistake']}。正确结论：{context['answer']} 自检：{context['check']}",
            "format": "可能错法 + 正确过程 + 自检",
            "steps": ["说出可能错法。", "写出正确过程。", "按错法反查一遍。"],
        },
        {
            "prompt": f"先圈出题目要求的结果、关键条件和检验方式，再完成：{context['problem']}",
            "answer": f"需要确认：题目要求的结果、关键条件、检验方式。规则：{context['rule']} 结论：{context['answer']}",
            "format": "任务拆解 + 过程 + 结论",
            "steps": ["圈出要求的结果。", "确认关键条件。", "写出完整结论并检验。"],
        },
        {
            "prompt": f"用代入、反向或估算中的一种方法检验：{context['problem']} 请写出你选择的检验方法和检验结果。",
            "answer": f"结论：{context['answer']} 可选择的检验：{context['check']} 检验应支持原结论。",
            "format": "解答 + 检验方法 + 检验结果",
            "steps": ["先解答题目。", "选择一种检验方法。", "写出检验过程和结果。"],
        },
        {
            "prompt": f"先比较条件变化，再完成：{context['variant_problem']} 请写出你沿用的规则，并重新求结果。",
            "answer": f"不变的是：{context['rule']} 变式结论：{context['variant_answer']} 原题可作为对照：{context['answer']}",
            "format": "条件变化 + 不变量 + 新结果",
            "steps": ["找出改变的条件。", "说明不变的规则或模型。", "重新求出结果。"],
        },
        {
            "prompt": f"两位同学争论：甲说“{context['claim_a']}”；乙说“{context['claim_b']}”。请判断谁更严谨，并完成本题：{context['problem']}",
            "answer": f"乙更严谨。理由：{context['rule']} 甲的问题：{context['wrong_reason']} 本题结论：{context['answer']}",
            "format": "观点判断 + 理由 + 解答",
            "steps": ["判断两种观点。", "说明严谨依据。", "完成题目并检验。"],
        },
        {
            "prompt": f"先圈出真正参与解题的条件，排除无关信息“{context['irrelevant']}”：{context['problem_with_irrelevant']}",
            "answer": f"无关信息：{context['irrelevant']}。真正参与的是：{context['condition']} 以及题中核心数据。结论：{context['answer']}",
            "format": "条件筛选 + 关系确认 + 解答",
            "steps": ["圈出相关条件。", "说明无关信息为什么不参与。", "用相关条件解答。"],
        },
        {
            "prompt": f"请写完整答句：{context['problem']} 答案必须包含关系、过程、结论和检验。",
            "answer": f"完整答句应包含规则：{context['rule']}；过程和结论：{context['answer']}；检验：{context['check']}",
            "format": "完整答句 + 过程 + 检验",
            "steps": ["写出关系。", "写出过程和结论。", "补上检验或解释。"],
        },
    ]
    template_slot = ((offset - 1) % len(templates)) + 1
    template = templates[template_slot - 1]
    return {
        "prompt": template["prompt"],
        "answer": template["answer"],
        "steps": template["steps"],
        "identity": _question_identity_from_context(
            node,
            qtype,
            kind,
            offset,
            context,
            template_slot=template_slot,
        ),
    }


def _topic_family(node: dict[str, Any], question_type: str) -> str:
    node_id = str(node.get("id", ""))
    exact = {
        "M-PRE-DECIMAL-OPS": "decimal_ops",
        "M-PRE-INTEGER-OPS": "integer_ops",
        "M-PRE-NUMBER-SENSE": "number_sense",
        "M-PRE-ORDER-OPS": "order_ops",
        "M-PRE-FRACTION-MEANING": "fraction_meaning",
        "M-PRE-FRACTION-OPS": "fraction_ops",
        "M-BRIDGE-CLOCK-ANGLE": "clock",
        "M-G7-COMPARE": "rational_compare",
        "M-G7-RATIONAL-CLASSIFY": "rational_classify",
        "M-G7-NUMBER-LINE": "number_line",
        "M-G7-ABSOLUTE": "absolute",
        "M-G7-OPPOSITE": "opposite",
        "M-G7-POS-NEG": "pos_neg",
        "M-G7-RATIONAL-MUL-DIV": "rational_muldiv",
        "M-G7-RATIONAL-MIXED": "rational_mixed",
        "M-G7-LIKE-TERMS": "like_terms",
        "M-G7-COMBINE-LIKE": "combine_like",
        "M-G7-POLY-ADD-SUB": "poly_add_sub",
        "M-G7-MONOMIAL": "monomial",
        "M-G7-POLYNOMIAL": "polynomial",
        "M-G7-EXPR-VALUE": "expr_value",
        "M-G7-ALG-EXPR": "algebra_expr",
        "M-G7-PARENTHESIS": "algebra_simplify",
        "M-G7-EQUATION-CONCEPT": "equation_concept",
        "M-G7-ANGLE-CALC": "angle_calc",
        "M-G7-ANGLE": "angle",
    }
    if node_id in exact:
        return exact[node_id]
    return "word_model"


def _advanced_challenge_context(
    node: dict[str, Any],
    family: str,
    offset: int,
    *,
    kind: str = "",
) -> dict[str, str] | None:
    node_id = str(node.get("id", ""))
    if offset not in CONTROLLED_ADVANCED_CHALLENGE_SLOTS:
        return None

    digit_reverse = {
        "problem": "设 n 是一个四位数，它的 4 倍恰好等于它的反序数。例如 1234 的反序数是 4321。请设 n=1000a+100b+10c+d，写出数位方程并求 n。",
        "answer": "n=2178。因为 2178×4=8712。设 n=1000a+100b+10c+d，则 4n=1000d+100c+10b+a；结合进位或逐位试验可得 a=2,b=1,c=7,d=8，检验成立。",
        "short_answer": "2178",
        "wrong_solution": "只猜 1089，因为它乘9会反序。",
        "wrong_reason": "把倍数4看成倍数9，或者只猜答案没有写数位关系与检验。",
        "rule": "数位题要把数写成十进制展开式，并跟反序数建立等式。",
        "check": "2178×4=8712，正好是2178的反序数",
        "method_a": "设四个数位并列方程，再用进位约束缩小范围",
        "method_b": "只试几个熟悉的反序数",
        "variant_problem": "若一个四位数 n 的9倍等于它的反序数，请设 n=1000a+100b+10c+d，写出数位方程并求 n。",
        "variant_answer": "1089×9=9801",
        "representation": "1000a+100b+10c+d 与 1000d+100c+10b+a 的数位方程",
        "condition": "n 是四位数，首位 a 和末位 d 都不是0，且4n仍是四位数",
        "implausible_answer": "1089",
        "bad_rule": "看到反序数就套熟悉答案",
        "incomplete_answer": "2178",
        "rule_options": "数位方程与进位约束，还是只靠猜数",
        "common_mistake": "没有处理进位导致数位关系不成立",
        "changed_condition": "把4倍改成9倍",
        "claim_a": "只要末位乘4后个位对上首位就够了",
        "claim_b": "每一位和进位都要同时满足",
        "irrelevant": "题目举了三位数反序数例子",
        "problem_with_irrelevant": "题目举了三位数反序数例子。请解决四位数 n 的4倍等于反序数的问题。",
    }
    coordinate_pattern = {
        "problem": "自然数按如下规律排成行列：第1列自上而下是1,4,9,16,...；第2列前两行是2,3，第三行起接8,15,24,...；每一层 m×m 的边界按先向下再向左补齐。请推出一般规则，并求上起第12行、左起第15列的数。",
        "answer": "当列 c≥行 r 时，数为 (c-1)^2+r；当行 r>列 c 时，数为 r^2-c+1。第12行第15列满足 c≥r，所以是14^2+12=208。",
        "short_answer": "208",
        "wrong_solution": "直接把12和15相乘或相加得到180或27。",
        "wrong_reason": "没有找出每一层平方数边界的规律。",
        "rule": "规律排列题先确定所在层 m=max(r,c)，再判断落在竖边还是横边。",
        "check": "第15列顶部从14^2+1=197开始，第12行就是197+11=208",
        "method_a": "先找层数 m=max(行,列)，再用边界公式",
        "method_b": "只看行列数做四则运算",
        "variant_problem": "在这个平方层行列规则中，数190在上起第几行、左起第几列？",
        "variant_answer": "169<190≤196，属于第14层；190=14^2-c+1，所以 c=7，位置是第14行第7列。",
        "representation": "以平方数 1,4,9,16,... 作为每层左下角的行列坐标图",
        "condition": "要先判断行和列谁更大，不能套一个公式到底",
        "implausible_answer": "180",
        "bad_rule": "行列题只需要行×列",
        "incomplete_answer": "第12行第15列是208",
        "rule_options": "平方层边界公式，还是行列直接运算",
        "common_mistake": "没有区分竖边公式和横边公式",
        "changed_condition": "把第12行第15列改成第15行第12列",
        "claim_a": "第12行第15列应接近12×15",
        "claim_b": "先找第15层，再沿第15列向下数",
        "irrelevant": "表格画得不是等距",
        "problem_with_irrelevant": "表格画得不是等距。请按规律求第12行第15列的数。",
    }
    pigeonhole_subset = {
        "problem": "任意给出 k 个自然数，是否一定能从中选出若干个数（至少一个，可以不连续），使这些数的和能被 k 整除？请说明理由。",
        "answer": "一定能。把这 k 个数排成一列，记前缀和 S1,S2,...,Sk，并看它们除以 k 的余数。若某个 Si 余0，则前 i 个数的和可被 k 整除；若没有余0，则 k 个前缀和只落在1到k-1这 k-1类余数中，必有两个余数相同，它们的差就是一段连续若干个数的和，可被 k 整除。连续若干个数也是从原数中选出的若干个数。",
        "short_answer": "一定能，用前缀和余数和抽屉原理证明",
        "wrong_solution": "不一定，因为每个数本身都可能不能被 k 整除。",
        "wrong_reason": "只检查单个数，忽略多个数的和以及余数重复。",
        "rule": "整除存在性题常用前缀和余数分类，再用抽屉原理找余数0或两个相同余数。",
        "check": "两个前缀和余数相同，则它们的差除以k余0",
        "method_a": "构造前缀和并按除以k的余数分类",
        "method_b": "逐个看每个数能不能被k整除",
        "variant_problem": "给出7个自然数，证明一定能选出连续若干个数，使它们的和能被7整除。",
        "variant_answer": "看7个前缀和除以7的余数；若有0直接成立，否则7个数落入6个非零余数类，必有两个相同，差对应连续一段。",
        "representation": "前缀和 S1,...,Sk 的余数分类表",
        "condition": "选择的是若干个数；证明中找到的是连续一段，当然也是若干个数",
        "implausible_answer": "不一定",
        "bad_rule": "只看单个数是否能整除",
        "incomplete_answer": "一定能",
        "rule_options": "抽屉原理与前缀和，还是逐个检查单数",
        "common_mistake": "忘记两个相同余数相减会被k整除",
        "changed_condition": "把k个数改成k-1个数",
        "claim_a": "如果每个数都不能被k整除，就找不到",
        "claim_b": "多个数相加后的余数可以抵消",
        "irrelevant": "这些自然数是否按大小排序",
        "problem_with_irrelevant": "这些自然数是否按大小排序并不重要。请证明 k 个自然数中能选出若干个和被 k 整除。",
    }
    signed_pattern = {
        "problem": "把 1,2,3,...,100 依次写上符号：第1个为正，第2个为负，第3个为正，第4个为负，如此交替。先不逐项计算，求这100个带符号数的和；再说明如果改成前101项，结论怎样变。",
        "answer": "(1-2)+(3-4)+...+(99-100)=50个(-1)，和为-50。前101项比前100项多一个+101，所以和为51。",
        "short_answer": "前100项和为-50；前101项和为51",
        "wrong_solution": "正负各一半，所以和为0。",
        "wrong_reason": "正数和负数个数相同不代表数值大小抵消。",
        "rule": "符号规律题要先分组，再看每组和与末项是否多出。",
        "check": "每两项一组：2m-1-(2m)=-1",
        "method_a": "按相邻两项分组",
        "method_b": "只数正负号个数",
        "variant_problem": "求 1-2+3-4+...+2025-2026，并说明怎样分组。",
        "variant_answer": "共有1013组，每组-1，和为-1013。",
        "representation": "(1-2)+(3-4)+... 的分组结构",
        "condition": "相邻两项符号相反且后一个数大1",
        "implausible_answer": "0",
        "bad_rule": "正负号数量相同就一定抵消",
        "incomplete_answer": "-50",
        "rule_options": "分组求和，还是只数正负号",
        "common_mistake": "忽略每组不是0而是-1",
        "changed_condition": "把100项改成101项",
        "claim_a": "正负各50个，所以和为0",
        "claim_b": "每组1-2、3-4都等于-1",
        "irrelevant": "这些数写在同一行",
        "problem_with_irrelevant": "这些数写在同一行：求 1-2+3-4+...-100 的和。",
    }
    absolute_distance = {
        "problem": "求所有整数 x，使 |x-3|+|x+2|≤9。请不要只试数，要用数轴解释“到3和到-2的距离和”怎样变化。",
        "answer": "在 -2 到 3 之间，距离和恒为5；向左或向右每远离1，距离和增加2。满足≤9的整数为 -4,-3,-2,-1,0,1,2,3,4,5。",
        "short_answer": "x=-4,-3,-2,-1,0,1,2,3,4,5",
        "wrong_solution": "只解 |x-3|=9 或 |x+2|=9。",
        "wrong_reason": "把两个距离的和拆成单个距离条件。",
        "rule": "绝对值可以看成数轴距离，两个定点的距离和要按区间讨论。",
        "check": "x=-4时距离和7+2=9；x=5时2+7=9；中间都不超过9",
        "method_a": "画数轴并按区间讨论距离和",
        "method_b": "只把其中一个绝对值单独等于9",
        "variant_problem": "求所有整数 x，使 |x-1|+|x+4|≤11。",
        "variant_answer": "两点距离5，左右最多各扩3，整数从-7到4。",
        "representation": "数轴上到 -2 与 3 的距离和",
        "condition": "两个绝对值表示到两个定点的距离",
        "implausible_answer": "只有-6和12",
        "bad_rule": "绝对值和可以分别单独处理",
        "incomplete_answer": "-4到5",
        "rule_options": "数轴距离和，还是单个绝对值方程",
        "common_mistake": "漏掉中间一整段都满足条件",
        "changed_condition": "把≤9改成=9",
        "claim_a": "只要分别解两个绝对值就行",
        "claim_b": "应看一个点到两个定点的总距离",
        "irrelevant": "x 写成大写字母也一样",
        "problem_with_irrelevant": "x 写成大写字母也一样。请用数轴求 |x-3|+|x+2|≤9 的整数解。",
    }
    opposite_parameter = {
        "problem": "已知 a 与 b 互为相反数，c 与 d 互为倒数，且 |m|=2。求 a+b+cd-m 的所有可能值，并说明为什么不是唯一答案。",
        "answer": "a+b=0，cd=1，m=2或-2。所以 a+b+cd-m=1-m，可能为 -1 或 3。",
        "short_answer": "-1 或 3",
        "wrong_solution": "a+b=0，cd=1，所以结果就是1。",
        "wrong_reason": "漏掉 |m|=2 有 m=2 和 m=-2 两种情况。",
        "rule": "相反数和为0，倒数乘积为1；绝对值条件通常有两个方向。",
        "check": "m=2时为-1；m=-2时为3",
        "method_a": "先把条件翻译成代数关系，再分类讨论m",
        "method_b": "看到绝对值就只取正数",
        "variant_problem": "若 |m|=5，求 a+b+cd+m 的可能值。",
        "variant_answer": "1+m，可能为6或-4。",
        "representation": "a+b=0、cd=1、m=±2 的条件表",
        "condition": "|m|=2 表示 m 到0的距离为2",
        "implausible_answer": "1",
        "bad_rule": "绝对值等于正数时原数只能取正",
        "incomplete_answer": "-1",
        "rule_options": "条件翻译与分类讨论，还是只代一个值",
        "common_mistake": "漏掉 m=-2",
        "changed_condition": "把 -m 改成 +m",
        "claim_a": "|m|=2 所以 m=2",
        "claim_b": "|m|=2 表示 m=2 或 -2",
        "irrelevant": "a,b,c,d 的具体大小未知",
        "problem_with_irrelevant": "a,b,c,d 的具体大小未知。请根据关系求 a+b+cd-m 的可能值。",
    }
    rational_parameter_compare = {
        "problem": "已知 0<a<1，把 -1/a、-1、-a、-a² 从小到大排列，并说明每一步为什么成立。",
        "answer": "因为 0<a<1，所以 1/a>1，且 0<a²<a<1。取负后方向改变：-1/a<-1<-a<-a²。",
        "short_answer": "-1/a < -1 < -a < -a²",
        "wrong_solution": "-a²<-a<-1<-1/a。",
        "wrong_reason": "负号会改变大小方向，且没有利用0<a<1。",
        "rule": "含参数比较先在正数范围比较，再乘负号时反向。",
        "check": "取 a=1/2，得到 -2<-1<-1/2<-1/4",
        "method_a": "先比较 1/a、1、a、a²，再整体取相反数",
        "method_b": "只按字母式子长短排序",
        "variant_problem": "若 a>1，重新比较 -1/a、-1、-a、-a²。",
        "variant_answer": "a²>a>1>1/a，所以 -a²<-a<-1<-1/a。",
        "representation": "0<a<1 时 a²、a、1、1/a 的数轴位置",
        "condition": "0<a<1 是关键条件",
        "implausible_answer": "-a² 最小",
        "bad_rule": "带平方的一定最大或最小",
        "incomplete_answer": "-1/a<-1<-a<-a²",
        "rule_options": "参数范围比较，还是凭式子外形排序",
        "common_mistake": "忘记取相反数后不等号方向变化",
        "changed_condition": "把0<a<1改成a>1",
        "claim_a": "a²看起来更大，所以-a²最小",
        "claim_b": "0<a<1时a²反而比a小",
        "irrelevant": "a 没给具体数值",
        "problem_with_irrelevant": "a 没给具体数值。请在 0<a<1 条件下比较 -1/a、-1、-a、-a²。",
    }
    telescoping_sum = {
        "problem": "计算 1/(1×2)+1/(2×3)+1/(3×4)+...+1/(19×20)。请先找出每一项能拆成哪两个分数的差，再求和。",
        "answer": "1/(n(n+1))=1/n-1/(n+1)。原式=(1-1/2)+(1/2-1/3)+...+(1/19-1/20)=1-1/20=19/20。",
        "short_answer": "19/20",
        "wrong_solution": "把分母相乘后直接相加，认为分母越来越大可以忽略。",
        "wrong_reason": "没有发现裂项后中间项会相消。",
        "rule": "形如1/[n(n+1)]的和常用裂项相消。",
        "check": "前3项为1/2+1/6+1/12=3/4，裂项得1-1/4=3/4",
        "method_a": "把每项拆成1/n-1/(n+1)",
        "method_b": "逐项通分硬算",
        "variant_problem": "计算 1/(2×3)+1/(3×4)+...+1/(20×21)。",
        "variant_answer": "1/2-1/21=19/42",
        "representation": "裂项相消链条",
        "condition": "相邻两个因数 n 和 n+1",
        "implausible_answer": "接近0",
        "bad_rule": "分母大就可以忽略不算",
        "incomplete_answer": "19/20",
        "rule_options": "裂项相消，还是逐项通分",
        "common_mistake": "不会把1/[n(n+1)]拆成两个分数的差",
        "changed_condition": "起点从1×2改成2×3",
        "claim_a": "这么多分数只能通分",
        "claim_b": "每一项都能拆成相邻倒数的差",
        "irrelevant": "分数写得很长",
        "problem_with_irrelevant": "分数写得很长。请计算 1/(1×2)+...+1/(19×20)。",
    }
    telescoping_product = {
        "problem": "计算 (1-1/2)(1-1/3)(1-1/4)...(1-1/20)。请先把每个括号改写成分数，再观察约分规律。",
        "answer": "每项 1-1/n=(n-1)/n，所以原式=(1/2)(2/3)(3/4)...(19/20)=1/20。",
        "short_answer": "1/20",
        "wrong_solution": "每个括号都接近1，所以结果也接近1。",
        "wrong_reason": "忽略了连续乘积会大量约分，且第一个因子是1/2。",
        "rule": "连续乘积要先改写成可约分结构。",
        "check": "前4项为(1/2)(2/3)(3/4)=1/4",
        "method_a": "把每项写成(n-1)/n后连乘约分",
        "method_b": "凭每项接近1估计",
        "variant_problem": "计算 (1-1/3)(1-1/4)...(1-1/20)。",
        "variant_answer": "(2/3)(3/4)...(19/20)=2/20=1/10",
        "representation": "连续分子分母约分链",
        "condition": "每一项分子正好等于下一项分母的一部分",
        "implausible_answer": "接近1",
        "bad_rule": "很多接近1的数相乘一定接近1",
        "incomplete_answer": "1/20",
        "rule_options": "连乘约分，还是凭大小感觉估计",
        "common_mistake": "没有把括号化成(n-1)/n",
        "changed_condition": "从1-1/3开始乘",
        "claim_a": "每项都不到1但很接近1",
        "claim_b": "相邻分子分母会连续约掉",
        "irrelevant": "乘号很多",
        "problem_with_irrelevant": "乘号很多。请计算 (1-1/2)(1-1/3)...(1-1/20)。",
    }
    operation_structure = {
        "problem": "定义一种新运算：a※b=a+b-ab。先证明 a※b=1-(1-a)(1-b)，再按从左到右计算 1/2※1/3※1/4※...※1/20。",
        "answer": "因为 a+b-ab=1-(1-a)(1-b)，所以连续运算后等于 1-(1-1/2)(1-1/3)...(1-1/20)=1-(1/2)(2/3)...(19/20)=1-1/20=19/20。",
        "short_answer": "19/20",
        "wrong_solution": "把 ※ 当成普通加法，直接把 1/2 到 1/20 相加。",
        "wrong_reason": "没有使用新运算定义，也没有把结构转化成可约分的连乘。",
        "rule": "新定义运算题先按定义改写，再寻找隐藏的常规结构。",
        "check": "先算 1/2※1/3=1/2+1/3-1/6=2/3，也等于1-(1/2)(2/3)",
        "method_a": "把 a※b 改写成 1-(1-a)(1-b)",
        "method_b": "把符号 ※ 当成加号或乘号",
        "variant_problem": "仍按 a※b=a+b-ab，计算 1/3※1/4※...※1/20。",
        "variant_answer": "1-(2/3)(3/4)...(19/20)=1-1/10=9/10。",
        "representation": "新运算转化为 1 减连续乘积",
        "condition": "每一步都必须使用 a※b=a+b-ab 的定义",
        "implausible_answer": "普通分数和",
        "bad_rule": "陌生符号可以按熟悉运算猜",
        "incomplete_answer": "19/20",
        "rule_options": "定义转化与连乘约分，还是把新符号当普通运算",
        "common_mistake": "没有证明等价结构就直接套运算",
        "changed_condition": "把起点从1/2改成1/3",
        "claim_a": "※看起来像乘号，所以直接相乘",
        "claim_b": "先把新运算化成1-(1-a)(1-b)",
        "irrelevant": "符号 ※ 的形状",
        "problem_with_irrelevant": "符号 ※ 的形状不重要。请按定义计算 1/2※1/3※...※1/20。",
    }

    def extension(payload: dict[str, str], label: str) -> dict[str, str]:
        return {
            **payload,
            "challenge_label": label,
            "evidence_role": "picture_level_extension",
        }

    if node_id in PICTURE_LEVEL_CHALLENGE_NODE_ALLOWLIST["digit_reverse_place_value"]:
        return extension(digit_reverse, "digit_reverse_place_value")
    if node_id in PICTURE_LEVEL_CHALLENGE_NODE_ALLOWLIST["coordinate_pattern_square_layer"]:
        return extension(coordinate_pattern, "coordinate_pattern_square_layer")
    if node_id in PICTURE_LEVEL_CHALLENGE_NODE_ALLOWLIST["pigeonhole_prefix_sum_proof"]:
        return extension(pigeonhole_subset, "pigeonhole_prefix_sum_proof")
    if node_id == "M-G7-POS-NEG":
        return extension(signed_pattern, "alternating_sum_structure")
    if node_id == "M-G7-ABSOLUTE":
        return extension(absolute_distance, "absolute_value_distance_model")
    if node_id == "M-G7-OPPOSITE":
        return extension(opposite_parameter, "case_split_absolute_value")
    if node_id == "M-G7-COMPARE":
        return extension(rational_parameter_compare, "parameter_comparison")
    if node_id == "M-G7-RATIONAL-ADD-SUB":
        return extension(telescoping_sum, "telescoping_sum")
    if node_id == "M-G7-RATIONAL-MIXED":
        return extension(operation_structure, "custom_operation_structure")
    if node_id == "M-G7-RATIONAL-MUL-DIV":
        return extension(telescoping_product, "telescoping_product")
    return None


def _concrete_question_context(node: dict[str, Any], question_type: str, offset: int, *, kind: str = "") -> dict[str, str]:
    family = _topic_family(node, question_type)
    advanced = _advanced_challenge_context(node, family, offset, kind=kind)
    if advanced:
        return advanced
    contexts = {
        "decimal_ops": [
            {
                "problem": "小林计算 12.6 - 3.48 时把小数点没有对齐，写成 9.42。请先判断错因，再写出正确竖式思路和结果。",
                "answer": "小数加减要按相同数位对齐，也就是小数点对齐。12.60-3.48=9.12；9.42 是数位没有对齐造成的。",
                "short_answer": "12.6-3.48=9.12",
                "wrong_solution": "12.6-3.48=9.42。",
                "wrong_reason": "小数点没有对齐，十分位和百分位被错位相减。",
                "rule": "小数加减按相同数位对齐，小数点上下对齐后再算。",
                "check": "9.12+3.48=12.60",
                "method_a": "把12.6补成12.60，再按位相减",
                "method_b": "只把末位数字对齐",
                "variant_problem": "计算 8.05 + 0.7，并说明为什么要写成 8.05+0.70。",
                "variant_answer": "8.05+0.70=8.75",
                "representation": "小数点对齐的竖式",
                "condition": "相同数位才能相加减",
                "implausible_answer": "9.42",
                "bad_rule": "小数加减只要末位对齐",
                "incomplete_answer": "结果是9.12",
                "rule_options": "按数位对齐，还是按数字末尾对齐",
                "common_mistake": "补0和对齐数位处理不稳",
                "changed_condition": "把12.6改成12.06",
                "claim_a": "末位对齐更方便，所以9.42也可能对",
                "claim_b": "小数点对齐后才能保证同位相减",
                "irrelevant": "题目写在草稿纸左边",
                "problem_with_irrelevant": "题目写在草稿纸左边：计算 12.6-3.48，并判断9.42这个结果是否合理。",
            },
            {
                "problem": "一张小票上写着 7.2 元/千克、0.48 千克，金额却写成 34.56 元。请先估算，再求合理金额。",
                "answer": "7.2≈7，0.48≈0.5，金额应接近3.5元；准确计算为7.2×0.48=3.456元，所以34.56元小数点错了一位。",
                "short_answer": "合理金额是3.456元",
                "wrong_solution": "7.2×0.48=34.56，所以金额是34.56元。",
                "wrong_reason": "只按小数位移动写结果，没有用数量级估算检查。",
                "rule": "小数乘除要把整数计算、小数位处理和数量级估算放在一起检查。",
                "check": "7×0.5≈3.5元",
                "method_a": "先估算数量级，再按小数位数计算",
                "method_b": "只数小数位，不检查结果范围",
                "variant_problem": "一件商品 6.4 元/千克，买 0.52 千克。请估算并计算金额。",
                "variant_answer": "6.4×0.52=3.328元，约3.3元",
                "representation": "单价×数量=总价的表格",
                "condition": "0.48 千克小于 1 千克",
                "implausible_answer": "34.56 元",
                "bad_rule": "小数乘法只要数小数位就不会错",
                "incomplete_answer": "金额是3.456",
                "rule_options": "单价乘数量，还是把两个小数直接拼成一个数",
                "common_mistake": "结果没有和估算数量级比较",
                "changed_condition": "把0.48千克改成1.2千克",
                "claim_a": "34.56也可能对，因为小数位数没错",
                "claim_b": "先估算，少于1千克时金额应小于7.2元",
                "irrelevant": "包装袋颜色是蓝色",
                "problem_with_irrelevant": "一张小票上写着 7.2 元/千克、0.48 千克，包装袋颜色是蓝色，金额写成 34.56 元。请判断金额是否合理。",
            },
            {
                "problem": "把 0.375 化成分数，再判断 3/8 写成小数是多少。请说明小数和分数互化时分母或位数从哪里来。",
                "answer": "0.375=375/1000=3/8；3/8=0.375。小数三位表示千分之几，分数化小数可以把分母化成1000或做除法。",
                "short_answer": "0.375=3/8，3/8=0.375",
                "wrong_solution": "0.375=375/100，因为有两位小数。",
                "wrong_reason": "没有按小数位数确定分母，三位小数应是千分之几。",
                "rule": "小数与分数互化要看小数位数对应的分母，或用分子除以分母。",
                "check": "3÷8=0.375，3/8×1000=375",
                "method_a": "先写成375/1000再约分",
                "method_b": "只看前两位，随手写成百分之几",
                "variant_problem": "把 0.45 化成最简分数，并把 7/20 化成小数。",
                "variant_answer": "0.45=45/100=9/20；7/20=0.35",
                "representation": "小数位数与分母10、100、1000的对照表",
                "condition": "0.375 有三位小数",
                "implausible_answer": "375/100",
                "bad_rule": "所有小数化分数都写成百分之几",
                "incomplete_answer": "3/8",
                "rule_options": "按小数位数确定分母，还是随便写一个整十整百分母",
                "common_mistake": "小数位数和分母10的幂对应错",
                "changed_condition": "把0.375改成0.0375",
                "claim_a": "0.375看起来像百分数，所以分母是100",
                "claim_b": "三位小数先写成千分之375再约分",
                "irrelevant": "数字里有5",
                "problem_with_irrelevant": "数字里有5：把 0.375 化成分数，并把 3/8 写成小数。",
            },
        ],
        "integer_ops": [
            {
                "problem_instance_key": "integer_ops.remainder.verify.987_div_8",
                "problem": "某同学做有余数除法，只写了“987 ÷ 8 = 123 余 3”。请写出验算关系，判断是否正确，并说明余数为什么必须小于除数。",
                "answer": "验算应为 除数×商+余数=被除数。8×123+3=987，且3<8，所以这道有余数除法成立。",
                "short_answer": "987÷8=123余3，验算成立",
                "wrong_solution": "只写商和余数，不验算也可以。",
                "wrong_reason": "没有用除数×商+余数回到被除数，也没有检查余数小于除数。",
                "rule": "有余数除法必须满足 被除数=除数×商+余数，且余数小于除数。",
                "check": "8×123+3=987，3<8",
                "method_a": "先乘回去再加余数验算",
                "method_b": "只看商大概对不对",
                "variant_problem": "判断 754 ÷ 6 = 125 余 4 是否正确，并写验算。",
                "variant_answer": "6×125+4=754，4<6，正确",
                "representation": "被除数、除数、商、余数的关系式",
                "condition": "余数必须小于除数",
                "implausible_answer": "987÷8=123余9",
                "bad_rule": "余数可以比除数大",
                "incomplete_answer": "商123余3",
                "rule_options": "除法验算关系，还是只写商和余数",
                "common_mistake": "漏验算或余数大于除数",
                "changed_condition": "把余数3改成余数9",
                "claim_a": "商对了就不用管余数大小",
                "claim_b": "余数如果不小于除数，商还能继续增加",
                "irrelevant": "987是三位数",
                "problem_with_irrelevant": "987是三位数：判断 987÷8=123余3 是否正确并验算。",
            },
            {
                "problem_instance_key": "integer_ops.simplify.square_difference.2025",
                "problem": "不直接展开计算，比较 2026×2024 和 2025² 的大小，并求两者相差多少。有人说“2026 比 2025 大，所以前者更大”，请判断错因。",
                "answer": "2026×2024=(2025+1)(2025-1)=2025²-1，所以 2026×2024 比 2025² 小 1。错在只比较一个因数，忽略另一个因数也变了。",
                "short_answer": "2026×2024=2025²-1，小1",
                "wrong_solution": "2026>2025，所以 2026×2024>2025²。",
                "wrong_reason": "只看一个因数变大，没有同时处理另一个因数变小。",
                "rule": "相邻数乘积可用平方差：(a+1)(a-1)=a²-1。",
                "check": "把 a=2025 代入 (a+1)(a-1)=a²-1",
                "method_a": "把两个因数写成 2025+1 和 2025-1",
                "method_b": "只看第一个因数大小",
                "variant_problem": "不展开计算，比较 1001×999 和 1000²，并求差。",
                "variant_answer": "1001×999=(1000+1)(1000-1)=1000²-1，小1",
                "representation": "平方差结构图：(a+1)(a-1)",
                "condition": "两个因数分别在同一个基准数两侧相差1",
                "implausible_answer": "前者大",
                "bad_rule": "只比较其中一个因数",
                "incomplete_answer": "小1",
                "rule_options": "平方差结构，还是单独比较一个因数",
                "common_mistake": "只看2026更大，漏看2024更小",
                "changed_condition": "把 2026×2024 改成 2027×2023",
                "claim_a": "第一个因数更大，所以乘积更大",
                "claim_b": "两个因数在2025两边对称，乘积是2025²减1",
                "irrelevant": "2026是偶数",
                "problem_with_irrelevant": "2026是偶数。请比较 2026×2024 和 2025² 的大小，并说明结构。",
            },
            {
                "problem_instance_key": "integer_ops.compensation.998_times_37_plus_74",
                "problem": "不用竖式计算 998×37+74。请先把 998 看成 1000-2，再说明为什么结果能直接凑成整千。",
                "answer": "998×37+74=(1000-2)×37+2×37=1000×37=37000。",
                "short_answer": "37000",
                "wrong_solution": "998×37+74=1000×37+74=37074。",
                "wrong_reason": "把998补到1000后，没有扣回多算的2×37；题中的74正好用于抵消这部分。",
                "rule": "把接近整百、整千的因数拆开时，要同时补偿多算或少算的部分。",
                "check": "74=2×37，所以(998+2)×37=1000×37",
                "method_a": "把74写成2×37后提取公因数37",
                "method_b": "把998直接改成1000却不补偿",
                "variant_problem": "不用竖式计算 997×46+138，并说明凑整结构。",
                "variant_answer": "997×46+138=(1000-3)×46+3×46=46000",
                "representation": "补偿关系：少3个46，再补3个46",
                "condition": "74恰好等于2×37",
                "implausible_answer": "37074",
                "bad_rule": "接近整千就可以直接替换成整千",
                "incomplete_answer": "37000",
                "rule_options": "补偿法或提取公因数，还是直接改数不补偿",
                "common_mistake": "凑整后忘记补偿",
                "changed_condition": "把74改成37",
                "claim_a": "998可以直接当成1000",
                "claim_b": "只有把差的2×37补回来，才能等价变形",
                "irrelevant": "37是两位数",
                "problem_with_irrelevant": "37是两位数。请不用竖式计算998×37+74，并解释凑整依据。",
            },
            {
                "problem_instance_key": "integer_ops.remainder.verify.754_div_6",
                "problem": "有人写 754÷6=125余4。请判断这个结果是否成立，并用一条等式和一个大小关系完成验算。",
                "answer": "6×125+4=754，且4<6，所以754÷6=125余4成立。",
                "short_answer": "成立；6×125+4=754，4<6",
                "wrong_solution": "6×125+4=754，所以一定正确。",
                "wrong_reason": "只验证了乘加关系，还没有检查余数4是否小于除数6。",
                "rule": "有余数除法同时满足被除数=除数×商+余数、余数小于除数。",
                "check": "6×125+4=754，4<6",
                "method_a": "乘回去加余数，再比较余数和除数",
                "method_b": "只做乘加验算",
                "variant_problem": "判断 936÷7=133余5 是否成立，并完整验算。",
                "variant_answer": "7×133+5=936，5<7，成立",
                "representation": "被除数=除数×商+余数的关系式",
                "condition": "乘加关系和余数范围必须同时成立",
                "implausible_answer": "754÷6=124余10",
                "bad_rule": "乘加关系对了就不用看余数大小",
                "incomplete_answer": "正确",
                "rule_options": "完整验算，还是只检查乘加关系",
                "common_mistake": "漏查余数必须小于除数",
                "changed_condition": "把余数4改成余数10",
                "claim_a": "乘加等式成立就足够",
                "claim_b": "还必须检查余数小于除数",
                "irrelevant": "754是偶数",
                "problem_with_irrelevant": "754是偶数。请判断754÷6=125余4是否成立并完整验算。",
            },
            {
                "problem_instance_key": "integer_ops.simplify.regroup.125_times_32_times_25",
                "problem": "计算 125×32×25，不要逐步硬乘。请把32拆成合适的两个因数，凑出两个整千或整百结构。",
                "answer": "32=8×4，所以125×32×25=(125×8)×(4×25)=1000×100=100000。",
                "short_answer": "100000",
                "wrong_solution": "先算125×32=4000，再算4000×25。",
                "wrong_reason": "顺算可以得到正确结果，但不符合本题要求的凑整策略；真正的错误是拆分后漏因数或把乘法关系改掉。",
                "rule": "连乘可以利用交换律、结合律和因数分拆，优先组成整十、整百、整千。",
                "check": "125×8=1000，25×4=100",
                "method_a": "把32拆成8×4并重新结合",
                "method_b": "按原顺序逐项硬乘",
                "variant_problem": "计算 25×48×125，并写出最省步数的分拆。",
                "variant_answer": "48=6×8，25×6×(8×125)=150×1000=150000",
                "representation": "因数配对图：125↔8，25↔4",
                "condition": "拆分后必须保留全部因数和连乘关系",
                "implausible_answer": "10000",
                "bad_rule": "连乘只能按从左到右的顺序",
                "incomplete_answer": "100000",
                "rule_options": "交换结合并拆因数，还是固定从左到右",
                "common_mistake": "拆因数后漏乘或配对不完整",
                "changed_condition": "把32改成24",
                "claim_a": "改变乘法顺序会改变结果",
                "claim_b": "整数连乘可以交换、结合，因数一个也不能少",
                "irrelevant": "三个因数位数不同",
                "problem_with_irrelevant": "三个因数位数不同。请用凑整方法计算125×32×25。",
            },
            {
                "problem_instance_key": "integer_ops.division.scale.864000_div_125",
                "problem": "不用长除法计算 864000÷125。请说明为什么把被除数和除数同时乘8后，商保持不变。",
                "answer": "864000÷125=(864000×8)÷(125×8)=6912000÷1000=6912。被除数和除数同时乘同一个非零数，商不变。",
                "short_answer": "6912",
                "wrong_solution": "只把125乘8变成1000，得到864000÷1000=864。",
                "wrong_reason": "只改变除数，没有同步改变被除数，原来的商被改变了。",
                "rule": "商不变性质要求被除数和除数同时乘或除以同一个非零数。",
                "check": "125×6912=864000",
                "method_a": "被除数和除数同时乘8，把除数化成1000",
                "method_b": "只把除数变成1000",
                "variant_problem": "不用长除法计算 372000÷125，并说明变形依据。",
                "variant_answer": "(372000×8)÷1000=2976",
                "representation": "等值除法：(a÷b)=(8a)÷(8b)",
                "condition": "同时乘8且8不为0",
                "implausible_answer": "864",
                "bad_rule": "只改变除数也能保持商不变",
                "incomplete_answer": "6912",
                "rule_options": "商不变性质，还是只改一个数",
                "common_mistake": "只放大除数，忘记同步放大被除数",
                "changed_condition": "把125改成250",
                "claim_a": "为了凑整，只改除数也可以",
                "claim_b": "被除数和除数必须同步变化",
                "irrelevant": "864000末尾有三个0",
                "problem_with_irrelevant": "864000末尾有三个0。请用商不变性质计算864000÷125。",
            },
            {
                "problem_instance_key": "integer_ops.remainder.constraint.lcm_12_18",
                "problem": "一个三位自然数除以12余5，除以18也余5。这样的数最小是多少？请说明为什么要先处理“减去5”后的数。",
                "answer": "这个数减去5后同时是12和18的倍数。12和18的最小公倍数是36，最小三位数形如36k+5；k=3时得到113，所以最小是113。",
                "short_answer": "113",
                "wrong_solution": "12×18+5=221，所以最小是221。",
                "wrong_reason": "直接用两个数的乘积，忽略了它们有公因数6；应使用最小公倍数36。",
                "rule": "多个除法条件余数相同时，先减去共同余数，再转化为公倍数问题。",
                "check": "113=12×9+5=18×6+5",
                "method_a": "先减5，再找12和18的最小公倍数",
                "method_b": "直接把12和18相乘",
                "variant_problem": "一个三位自然数除以8和14都余3，求最小可能值。",
                "variant_answer": "减3后是8和14的公倍数；最小公倍数56，最小三位数是56×2+3=115",
                "representation": "n-5是12与18公倍数的关系图",
                "condition": "要求三位自然数且两个条件的余数相同",
                "implausible_answer": "41",
                "bad_rule": "共同倍数一定等于两个数的乘积",
                "incomplete_answer": "113",
                "rule_options": "共同余数转公倍数，还是直接相乘",
                "common_mistake": "找到36+5=41后忘记三位数条件",
                "changed_condition": "把三位自然数改成两位自然数",
                "claim_a": "12×18+5一定最小",
                "claim_b": "先求最小公倍数，再满足三位数范围",
                "irrelevant": "这个数的个位是3",
                "problem_with_irrelevant": "有人猜这个数的个位是3。请根据除以12和18都余5的条件求最小三位数。",
            },
            {
                "problem_instance_key": "integer_ops.remainder.constraint.under_200_divisible_7",
                "problem": "一个小于200的自然数，除以8和12都余5，同时它能被7整除。求这个数，并写出缩小范围的过程。",
                "answer": "减去5后是8和12的公倍数，所以这个数形如24k+5。小于200时依次检查29、53、77、101、125、149、173、197，其中77能被7整除，因此这个数是77。",
                "short_answer": "77",
                "wrong_solution": "8×12+5=101，所以答案是101。",
                "wrong_reason": "8和12的共同倍数应按最小公倍数24生成，并且还要检查能否被7整除。",
                "rule": "先把共同余数条件转成最小公倍数序列，再用额外整除条件筛选。",
                "check": "77=8×9+5=12×6+5，且77÷7=11",
                "method_a": "列出24k+5并用7的倍数筛选",
                "method_b": "直接把8和12相乘后加5",
                "variant_problem": "一个小于250的自然数，除以6和15都余4，同时能被8整除，求最小正整数解。",
                "variant_answer": "数形如30k+4；检查可得64能被8整除，所以最小是64",
                "representation": "24k+5的候选数列与7的倍数交点",
                "condition": "小于200、两个共同余数条件、还能被7整除",
                "implausible_answer": "101",
                "bad_rule": "只满足共同余数条件就可以停止",
                "incomplete_answer": "77",
                "rule_options": "公倍数序列加筛选，还是只算8×12+5",
                "common_mistake": "漏掉最后的7整除条件",
                "changed_condition": "把小于200改成大于200且小于300",
                "claim_a": "101满足前两个条件，所以就是答案",
                "claim_b": "还必须同时满足被7整除",
                "irrelevant": "200是整百数",
                "problem_with_irrelevant": "200是整百数。请找出小于200、除以8和12都余5且能被7整除的自然数。",
            },
        ],
        "number_sense": [
            {
                "problem": "不精算，判断 49.8×20.4 比 1000 大还是小，并估计大约差多少。有人说“49.8 接近 50、20.4 接近 20，所以一定等于 1000”，请指出问题。",
                "answer": "49.8×20.4=(50-0.2)(20+0.4)=1000+20-4-0.08=1015.92，比1000大约16。错在把两个近似误差都抹掉，没有判断误差方向。",
                "short_answer": "大于1000，约大16",
                "wrong_solution": "49.8≈50，20.4≈20，所以等于1000。",
                "wrong_reason": "估算可以判断范围，但不能把误差方向当作不存在。",
                "rule": "估算要同时看基准、误差方向和数量级。",
                "check": "比 50×20 多约 50×0.4-0.2×20=16",
                "method_a": "以 50×20 为基准，再判断误差方向",
                "method_b": "只四舍五入后直接当成精确值",
                "variant_problem": "不精算，判断 30.2×39.7 比 1200 大还是小，并估计差距。",
                "variant_answer": "30.2×39.7=(30+0.2)(40-0.3)=1200-9+8-0.06=1198.94，略小于1200",
                "representation": "基准乘积 + 误差修正表",
                "condition": "两个数分别偏离基准的方向和大小",
                "implausible_answer": "正好1000",
                "bad_rule": "四舍五入后把近似值当精确值",
                "incomplete_answer": "大于1000",
                "rule_options": "误差方向估算，还是只看四舍五入",
                "common_mistake": "估算后不判断误差方向",
                "changed_condition": "把20.4改成19.6",
                "claim_a": "接近50×20，所以就等于1000",
                "claim_b": "接近1000，但还要看两个误差对乘积的影响",
                "irrelevant": "数字都有一位小数",
                "problem_with_irrelevant": "数字都有一位小数：判断 49.8×20.4 与 1000 的大小关系。",
            },
            {
                "problem": "不精算，判断 6.8×0.49 的结果应接近 3.4、34 还是 0.34，并说明为什么。",
                "answer": "应接近3.4。6.8≈7，0.49≈0.5，7×0.5=3.5，所以34明显大了，0.34明显小了。",
                "short_answer": "接近3.4",
                "wrong_solution": "接近34，因为6.8×49=333.2。",
                "wrong_reason": "忽略0.49小于1，结果应小于6.8。",
                "rule": "数感估算要先看乘数与1的关系，再判断结果范围。",
                "check": "0.49<1，所以6.8×0.49<6.8",
                "method_a": "先看0.49约等于0.5",
                "method_b": "把0.49当49处理",
                "variant_problem": "判断 8.2×1.9 应接近16还是160。",
                "variant_answer": "8.2≈8，1.9≈2，约16",
                "representation": "与1比较的大小关系表",
                "condition": "0.49 小于 1",
                "implausible_answer": "34",
                "bad_rule": "小数点可以最后随便补",
                "incomplete_answer": "3.4",
                "rule_options": "数量级估算，还是先当整数算",
                "common_mistake": "小数点位置离谱也不检查",
                "changed_condition": "把0.49改成4.9",
                "claim_a": "算出333.2再点小数点，34可能合理",
                "claim_b": "乘小于1的数，结果应变小",
                "irrelevant": "题目来自小票",
                "problem_with_irrelevant": "题目来自小票：判断 6.8×0.49 的结果范围。",
            },
        ],
        "order_ops": [
            {
                "problem": "判断错解：18 - 6 ÷ 3 × 2 = 12 ÷ 3 × 2 = 8。请指出错因，写出正确顺序和结果。",
                "answer": "错在先算了18-6。应先按同级从左到右算除乘：6÷3×2=4，再算18-4=14。",
                "short_answer": "14",
                "wrong_solution": "18 - 6 ÷ 3 × 2 = 12 ÷ 3 × 2 = 8。",
                "wrong_reason": "没有遵守先乘除后加减，且同级乘除要从左到右。",
                "rule": "混合运算先算括号，再乘除，后加减；同级从左到右。",
                "check": "6÷3×2=4，18-4=14",
                "method_a": "先标运算顺序再计算",
                "method_b": "完全按看到的第一处加减先算",
                "variant_problem": "计算 24 - 8 ÷ 2 × 3，并说明顺序。",
                "variant_answer": "8÷2×3=12，24-12=12",
                "representation": "运算优先级标注图",
                "condition": "除法和乘法同级，从左到右",
                "implausible_answer": "8",
                "bad_rule": "没有括号就从最左边任意算",
                "incomplete_answer": "14",
                "rule_options": "运算顺序规则，还是只按书写位置猜",
                "common_mistake": "先做加减或同级顺序错",
                "changed_condition": "给6÷3加括号",
                "claim_a": "从左到右先算18-6",
                "claim_b": "乘除优先，所以先算6÷3×2",
                "irrelevant": "算式里有空格",
                "problem_with_irrelevant": "算式里有空格：18 - 6 ÷ 3 × 2。请按正确顺序计算。",
            },
            {
                "problem": "计算 2.4 + (3/5) × 10。有人先算 2.4+3/5。请指出错因，并写出正确过程。",
                "answer": "括号内3/5只是一个数，乘法优先于加法。先算(3/5)×10=6，再算2.4+6=8.4。",
                "short_answer": "8.4",
                "wrong_solution": "先把2.4和3/5相加，再乘10。",
                "wrong_reason": "把加法提前，破坏了先乘除后加减的顺序。",
                "rule": "小数/分数混合运算仍遵守运算顺序，先乘除后加减。",
                "check": "3/5×10=6，结果应大于6",
                "method_a": "先标出乘法部分，再统一数的形式",
                "method_b": "看到前两个数就先相加",
                "variant_problem": "计算 1.5 + (2/3)×6，并说明顺序。",
                "variant_answer": "2/3×6=4，1.5+4=5.5",
                "representation": "小数、分数和运算优先级的步骤表",
                "condition": "乘法在加法之前",
                "implausible_answer": "先加再乘的结果",
                "bad_rule": "混合了小数分数就从左到右算",
                "incomplete_answer": "8.4",
                "rule_options": "运算顺序，还是先统一前两个数",
                "common_mistake": "小数/分数混合时忘记优先级",
                "changed_condition": "给2.4+3/5加括号",
                "claim_a": "2.4在最前面，所以先和3/5相加",
                "claim_b": "没有括住2.4+3/5，乘法应先算",
                "irrelevant": "3/5写在括号里",
                "problem_with_irrelevant": "3/5写在括号里：计算 2.4 + (3/5) × 10。",
            },
        ],
        "fraction_meaning": [
            {
                "problem": "一本书读了全书的 3/5，正好是 60 页。请先写单位1，再求全书页数。",
                "answer": "单位1是全书页数。60页对应3/5，全书页数=60÷3/5=100页。",
                "short_answer": "全书100页",
                "wrong_solution": "60×3/5=36页。",
                "wrong_reason": "把已知部分又乘分率，混淆了求部分和求整体。",
                "rule": "已知部分量和对应分率，求整体用部分量÷分率。",
                "check": "100×3/5=60页",
                "method_a": "先找单位1，再用除法求整体",
                "method_b": "看到分数就直接乘",
                "variant_problem": "全书的 2/3 是 80 页，求全书页数。",
                "variant_answer": "80÷2/3=120页",
                "representation": "把全书看成5等份的线段图",
                "condition": "60页对应的是全书的3/5",
                "implausible_answer": "36页",
                "bad_rule": "看到几分之几就一定用乘法",
                "incomplete_answer": "100页",
                "rule_options": "求整体用除法，还是求部分用乘法",
                "common_mistake": "单位1没有找准",
                "changed_condition": "把读了3/5改成读了2/5",
                "claim_a": "分数题一般乘起来更快",
                "claim_b": "先看已知的是部分还是整体",
                "irrelevant": "这本书封面是红色",
                "problem_with_irrelevant": "一本红色封面的书读了全书的 3/5，正好是 60 页。请求全书页数。",
            },
        ],
        "fraction_ops": [
            {
                "problem": "两位同学计算 5/6 - 1/4：甲写 4/2，乙写 7/12。请判断谁对，并写出通分过程。",
                "answer": "乙对。5/6=10/12，1/4=3/12，所以5/6-1/4=7/12；甲把分子分母随意相减。",
                "short_answer": "结果是7/12",
                "wrong_solution": "5/6-1/4=(5-1)/(6-4)=4/2。",
                "wrong_reason": "分母不同的分数单位不同，不能直接分子分母相减。",
                "rule": "分数加减先统一分数单位，也就是先通分。",
                "check": "7/12+1/4=7/12+3/12=10/12=5/6",
                "method_a": "先通分到12再相减",
                "method_b": "分子分母分别相减",
                "variant_problem": "计算 3/4 - 1/6，并说明通分依据。",
                "variant_answer": "3/4=9/12，1/6=2/12，差为7/12",
                "representation": "同一个单位条被分成12份的图示",
                "condition": "两个分数的单位不同",
                "implausible_answer": "4/2",
                "bad_rule": "分数相减可以上下分别相减",
                "incomplete_answer": "乙对，是7/12",
                "rule_options": "通分，还是分子分母分别相减",
                "common_mistake": "没有统一分数单位就相减",
                "changed_condition": "把1/4改成1/3",
                "claim_a": "分数就是两个数，上下都减就行",
                "claim_b": "先统一分数单位才能加减",
                "irrelevant": "甲写字更工整",
                "problem_with_irrelevant": "两位同学计算 5/6 - 1/4，甲写字更工整且写 4/2，乙写 7/12。请判断谁对。",
            },
            {
                "problem": "计算 3/4 ÷ 2/5。有人写成 3/4 × 2/5。请判断错因，写出正确过程，并说明为什么要乘倒数。",
                "answer": "分数除法要转化为乘除数的倒数。3/4÷2/5=3/4×5/2=15/8。错法没有把除数变成倒数。",
                "short_answer": "15/8",
                "wrong_solution": "3/4÷2/5=3/4×2/5=3/10。",
                "wrong_reason": "除法转乘法时忘记把除数变成倒数。",
                "rule": "除以一个非零数等于乘这个数的倒数。",
                "check": "15/8×2/5=3/4",
                "method_a": "除法转乘倒数再约分",
                "method_b": "只把除号改乘号",
                "variant_problem": "计算 5/6 ÷ 3/4，并说明倒数。",
                "variant_answer": "5/6×4/3=10/9",
                "representation": "除数和倒数的对照表",
                "condition": "2/5 是除数，变成 5/2",
                "implausible_answer": "3/10",
                "bad_rule": "分数除法只把除号改成乘号",
                "incomplete_answer": "15/8",
                "rule_options": "乘倒数，还是只改运算符号",
                "common_mistake": "忘记倒数或约分不彻底",
                "changed_condition": "把2/5改成5/2",
                "claim_a": "改成乘法就完成了",
                "claim_b": "除数必须变成倒数",
                "irrelevant": "分数都是真分数",
                "problem_with_irrelevant": "分数都是真分数：计算 3/4 ÷ 2/5，并说明过程。",
            },
        ],
        "arithmetic": [
            {
                "problem": "一张小票上写着 7.2 元/千克、0.48 千克，金额却写成 34.56 元。请先估算，再求合理金额。",
                "answer": "7.2≈7，0.48≈0.5，金额应接近3.5元；准确计算为7.2×0.48=3.456元，所以34.56元小数点错了一位。",
                "short_answer": "合理金额是3.456元",
                "wrong_solution": "7.2×0.48=34.56，所以金额是34.56元。",
                "wrong_reason": "只按小数位移动写结果，没有用数量级估算检查。",
                "rule": "小数乘法要同时检查位数和数量级。",
                "check": "7×0.5≈3.5元",
                "method_a": "先估算数量级，再按小数位数计算",
                "method_b": "直接数小数位，不检查结果范围",
                "variant_problem": "一件商品 6.4 元/千克，买 0.52 千克。请估算并计算金额。",
                "variant_answer": "6.4×0.52=3.328元，约3.3元",
                "representation": "单价×数量=总价的表格",
                "condition": "0.48 千克小于 1 千克",
                "implausible_answer": "34.56 元",
                "bad_rule": "小数乘法只要数小数位就不会错",
                "incomplete_answer": "金额是3.456",
                "rule_options": "单价乘数量，还是把两个小数直接拼成一个数",
                "common_mistake": "结果没有和估算数量级比较",
                "changed_condition": "把0.48千克改成1.2千克",
                "claim_a": "34.56也可能对，因为小数位数没错",
                "claim_b": "先估算，少于1千克时金额应小于7.2元",
                "irrelevant": "包装袋颜色是蓝色",
                "problem_with_irrelevant": "一张小票上写着 7.2 元/千克、0.48 千克，包装袋颜色是蓝色，金额写成 34.56 元。请判断金额是否合理。",
            },
            {
                "problem": "不直接展开计算，比较 2026×2024 和 2025² 的大小，并求两者相差多少。有人说“2026 比 2025 大，所以前者更大”，请判断错因。",
                "answer": "2026×2024=(2025+1)(2025-1)=2025²-1，所以 2026×2024 比 2025² 小 1。错在只比较一个因数，忽略另一个因数也变了。",
                "short_answer": "2026×2024=2025²-1，小1",
                "wrong_solution": "2026>2025，所以 2026×2024>2025²。",
                "wrong_reason": "只看一个因数变大，没有同时处理另一个因数变小。",
                "rule": "相邻数乘积可用平方差：(a+1)(a-1)=a²-1。",
                "check": "把 a=2025 代入 (a+1)(a-1)=a²-1",
                "method_a": "把两个因数写成 2025+1 和 2025-1",
                "method_b": "只看第一个因数大小",
                "variant_problem": "不展开计算，比较 1001×999 和 1000²，并求差。",
                "variant_answer": "1001×999=(1000+1)(1000-1)=1000²-1，小1",
                "representation": "平方差结构图：(a+1)(a-1)",
                "condition": "两个因数分别在同一个基准数两侧相差1",
                "implausible_answer": "前者大",
                "bad_rule": "只比较其中一个因数",
                "incomplete_answer": "小1",
                "rule_options": "平方差结构，还是单独比较一个因数",
                "common_mistake": "只看2026更大，漏看2024更小",
                "changed_condition": "把 2026×2024 改成 2027×2023",
                "claim_a": "第一个因数更大，所以乘积更大",
                "claim_b": "两个因数在2025两边对称，乘积是2025²减1",
                "irrelevant": "2026是偶数",
                "problem_with_irrelevant": "2026是偶数。请比较 2026×2024 和 2025² 的大小，并说明结构。",
            },
        ],
        "fraction": [
            {
                "problem": "两位同学计算 5/6 - 1/4：甲写 4/2，乙写 7/12。请判断谁对，并写出通分过程。",
                "answer": "乙对。5/6=10/12，1/4=3/12，所以5/6-1/4=7/12；甲把分子分母随意相减。",
                "short_answer": "结果是7/12",
                "wrong_solution": "5/6-1/4=(5-1)/(6-4)=4/2。",
                "wrong_reason": "分母不同的分数单位不同，不能直接分子分母相减。",
                "rule": "分数加减先统一分数单位，也就是先通分。",
                "check": "7/12+1/4=7/12+3/12=10/12=5/6",
                "method_a": "先通分到12再相减",
                "method_b": "分子分母分别相减",
                "variant_problem": "计算 3/4 - 1/6，并说明通分依据。",
                "variant_answer": "3/4=9/12，1/6=2/12，差为7/12",
                "representation": "同一个单位条被分成12份的图示",
                "condition": "两个分数的单位不同",
                "implausible_answer": "4/2",
                "bad_rule": "分数相减可以上下分别相减",
                "incomplete_answer": "乙对，是7/12",
                "rule_options": "通分，还是分子分母分别相减",
                "common_mistake": "没有统一分数单位就相减",
                "changed_condition": "把1/4改成1/3",
                "claim_a": "分数就是两个数，上下都减就行",
                "claim_b": "先统一分数单位才能加减",
                "irrelevant": "甲写字更工整",
                "problem_with_irrelevant": "两位同学计算 5/6 - 1/4，甲写字更工整且写 4/2，乙写 7/12。请判断谁对。",
            },
            {
                "problem": "一本书读了全书的 3/5，正好是 60 页。请先写单位1，再求全书页数。",
                "answer": "单位1是全书页数。60页对应3/5，全书页数=60÷3/5=100页。",
                "short_answer": "全书100页",
                "wrong_solution": "60×3/5=36页。",
                "wrong_reason": "把已知部分又乘分率，混淆了求部分和求整体。",
                "rule": "已知部分量和对应分率，求整体用部分量÷分率。",
                "check": "100×3/5=60页",
                "method_a": "先找单位1，再用除法求整体",
                "method_b": "看到分数就直接乘",
                "variant_problem": "全书的 2/3 是 80 页，求全书页数。",
                "variant_answer": "80÷2/3=120页",
                "representation": "把全书看成5等份的线段图",
                "condition": "60页对应的是全书的3/5",
                "implausible_answer": "36页",
                "bad_rule": "看到几分之几就一定用乘法",
                "incomplete_answer": "100页",
                "rule_options": "求整体用除法，还是求部分用乘法",
                "common_mistake": "单位1没有找准",
                "changed_condition": "把读了3/5改成读了2/5",
                "claim_a": "分数题一般乘起来更快",
                "claim_b": "先看已知的是部分还是整体",
                "irrelevant": "这本书封面是红色",
                "problem_with_irrelevant": "一本红色封面的书读了全书的 3/5，正好是 60 页。请求全书页数。",
            },
        ],
        "percent": [
            {
                "problem": "一件商品先打八折，再在折后价基础上涨价 20%。请判断是否回到原价，并说明两次百分数的单位1。",
                "answer": "没有回到原价。八折后是原价的80%，再涨20%是以折后价为单位1，得到80%×120%=96%原价。",
                "short_answer": "最终是原价的96%",
                "wrong_solution": "降20%再涨20%，正好抵消，回到原价。",
                "wrong_reason": "两次百分数的单位1不同，不能把百分数直接相加抵消。",
                "rule": "百分数应用必须先确定每一次变化的单位1。",
                "check": "设原价100元，八折80元，再涨20%是96元",
                "method_a": "设原价100元追踪单位1",
                "method_b": "把-20%和+20%直接抵消",
                "variant_problem": "商品先涨价10%，再降价10%，最终是原价的多少？",
                "variant_answer": "100×110%×90%=99，是原价的99%",
                "representation": "原价、折后价、再涨价的三列表格",
                "condition": "上涨20%是在折后价基础上",
                "implausible_answer": "100%原价",
                "bad_rule": "涨降百分数相同就一定回到原价",
                "incomplete_answer": "不能回到原价",
                "rule_options": "连续乘法模型，还是百分数加减抵消",
                "common_mistake": "没有说明第二次变化的单位1",
                "changed_condition": "把上涨20%改成上涨25%",
                "claim_a": "八折就是降20%，涨20%就抵消",
                "claim_b": "第二个20%是以80%原价为单位1",
                "irrelevant": "商品颜色是黑色",
                "problem_with_irrelevant": "一件黑色商品先打八折，再在折后价基础上涨价20%。请判断最终与原价的关系。",
            },
        ],
        "ratio": [
            {
                "problem": "甲乙两数的比是 3:5，和是 64。小林用 64×3/5 求甲。请判断错在哪里，并求甲乙。",
                "answer": "3/5是甲与乙的比，不是甲占总数的比例。总份数8，每份64÷8=8，甲24，乙40。",
                "short_answer": "甲24，乙40",
                "wrong_solution": "甲=64×3/5=38.4。",
                "wrong_reason": "把甲:乙误当成甲占总数的比例。",
                "rule": "按比例分配先求总份数，再把份数对应到实际量。",
                "check": "24:40=3:5，且24+40=64",
                "method_a": "先算总份数3+5",
                "method_b": "直接用3/5乘总量",
                "variant_problem": "甲乙比为2:7，和是81，求甲乙。",
                "variant_answer": "总份数9，每份9，甲18，乙63",
                "representation": "3份和5份的份数线段图",
                "condition": "和是甲乙总量，不是乙的量",
                "implausible_answer": "38.4",
                "bad_rule": "3:5里甲就占总数的3/5",
                "incomplete_answer": "甲是24",
                "rule_options": "份数模型，还是把前项除以后项直接乘总量",
                "common_mistake": "忘记总份数是8",
                "changed_condition": "把和64改成差16",
                "claim_a": "3:5中的3/5就是甲占全部",
                "claim_b": "甲占全部的3/(3+5)",
                "irrelevant": "甲数写在前面",
                "problem_with_irrelevant": "甲数写在前面，甲乙两数的比是3:5，和是64。请求甲乙。",
            },
        ],
        "algebra_expr": [
            {
                "problem": "“a 的 3 倍减去 5”和“a 减去 5 后的 3 倍”是否一样？分别写成代数式，并用 a=4 检验。",
                "answer": "不一样。前者是3a-5，后者是3(a-5)。a=4时分别为7和-3。",
                "short_answer": "3a-5 与 3(a-5) 不一样",
                "wrong_solution": "两句话都写成3a-5。",
                "wrong_reason": "没有用括号表示“a减去5”这个整体。",
                "rule": "文字语言中的整体要用括号表达。",
                "check": "代入a=4，两式值不同",
                "method_a": "按语言顺序找整体再写式",
                "method_b": "看到3倍和减5就固定写3a-5",
                "variant_problem": "写出“x的一半加2”和“x加2后的一半”，并用x=6检验。",
                "variant_answer": "x/2+2 与 (x+2)/2；x=6时为5和4",
                "representation": "文字短语到代数式的箭头图",
                "condition": "“后”的作用范围",
                "implausible_answer": "两个式子相同",
                "bad_rule": "同样的数字和字母出现，就表示同一个式子",
                "incomplete_answer": "不一样",
                "rule_options": "整体括号，还是按出现顺序简单拼接",
                "common_mistake": "漏写括号",
                "changed_condition": "把减去5改成加上5",
                "claim_a": "3倍和减5都出现，所以式子一样",
                "claim_b": "要先看谁是整体再写括号",
                "irrelevant": "a 是英文字母",
                "problem_with_irrelevant": "a 是英文字母。请比较“a 的 3 倍减去 5”和“a 减去 5 后的 3 倍”。",
            },
        ],
        "like_terms": [
            {
                "problem": "判断 3a、-5a、2a²、7b、a 中哪些是同类项。请说明为什么 3a 和 2a² 不是同类项，系数不同是否影响同类项。",
                "answer": "3a、-5a、a 是同类项；3a 和 2a² 字母指数不同，不是同类项；系数不同不影响同类项。",
                "short_answer": "3a、-5a、a 是同类项",
                "wrong_solution": "3a 和 2a² 都有 a，所以是同类项。",
                "wrong_reason": "只看字母种类，没有看相同字母的指数是否相同。",
                "rule": "同类项要求字母相同且相同字母指数也相同，系数可以不同。",
                "check": "比较字母部分：a 与 a² 的指数不同",
                "method_a": "先看字母和指数，再忽略系数差异",
                "method_b": "只看有没有同一个字母",
                "variant_problem": "判断 4x²y、-3x²y、5xy²、7x 中哪些是同类项，并说明依据。",
                "variant_answer": "4x²y 和 -3x²y 是同类项；5xy²、7x不与它们同类",
                "representation": "字母部分对照表",
                "condition": "相同字母的指数也要相同",
                "implausible_answer": "3a和2a²是同类项",
                "bad_rule": "只要有相同字母就是同类项",
                "incomplete_answer": "3a、-5a、a",
                "rule_options": "字母部分完全相同，还是只看字母名称",
                "common_mistake": "把指数不同的项合并",
                "changed_condition": "把2a²改成2a",
                "claim_a": "3a和2a²都有a，所以可以合并",
                "claim_b": "a和a²指数不同，不能合并",
                "irrelevant": "系数有正有负",
                "problem_with_irrelevant": "系数有正有负：判断 3a、-5a、2a²、7b、a 中哪些是同类项。",
            },
        ],
        "combine_like": [
            {
                "problem": "合并同类项：2x + 3y - 5x + y。请说明为什么 x 项和 y 项不能互相合并。",
                "answer": "x项合并为2x-5x=-3x，y项合并为3y+y=4y，所以结果是-3x+4y；x和y字母不同，不能互相合并。",
                "short_answer": "-3x+4y",
                "wrong_solution": "2x+3y-5x+y=(2+3-5+1)xy=xy。",
                "wrong_reason": "把不同字母部分的项强行合并。",
                "rule": "只合并同类项的系数，字母部分保持不变。",
                "check": "分别收集x项和y项",
                "method_a": "按字母部分分组再合并系数",
                "method_b": "把所有系数加在一起",
                "variant_problem": "合并同类项：4a - 2b - 7a + 5b。",
                "variant_answer": "-3a+3b",
                "representation": "x项/y项分组表",
                "condition": "只有同类项才能合并",
                "implausible_answer": "xy",
                "bad_rule": "所有含字母的项都能合并",
                "incomplete_answer": "-3x+4y",
                "rule_options": "同类项分组，还是所有系数相加",
                "common_mistake": "合并后改变字母部分",
                "changed_condition": "把3y改成3x",
                "claim_a": "都是字母项，所以可以全合并",
                "claim_b": "x项只能和x项合并，y项只能和y项合并",
                "irrelevant": "式子有四项",
                "problem_with_irrelevant": "式子有四项：2x + 3y - 5x + y。请合并同类项并说明依据。",
            },
        ],
        "poly_add_sub": [
            {
                "problem": "先化简 (2x² - 3x + 1) - (x² + x - 4)，再代入 x=2 检验。",
                "answer": "去括号得2x²-3x+1-x²-x+4=x²-4x+5。x=2时代入得4-8+5=1。",
                "short_answer": "x²-4x+5；x=2时为1",
                "wrong_solution": "(2x² - 3x + 1) - (x² + x - 4)=x²-2x-3。",
                "wrong_reason": "减去第二个多项式时没有让括号内每一项变号。",
                "rule": "整式相减要先去括号，减号作用到后一个多项式的每一项，再合并同类项。",
                "check": "x=2代入原式和化简式都等于1",
                "method_a": "先逐项变号再合并同类项",
                "method_b": "只减每个同位置的系数或漏变号",
                "variant_problem": "化简 (3a²+a-2)-(a²-4a+1)。",
                "variant_answer": "2a²+5a-3",
                "representation": "前后多项式项对齐表",
                "condition": "第二个括号整体被减去",
                "implausible_answer": "x²-2x-3",
                "bad_rule": "多项式相减只改第一项符号",
                "incomplete_answer": "x²-4x+5",
                "rule_options": "整式相减逐项变号，还是直接对齐相减",
                "common_mistake": "漏掉后括号内项变号",
                "changed_condition": "把中间减号改成加号",
                "claim_a": "只需要把x²减掉",
                "claim_b": "整个后括号都被减去，每一项都变号",
                "irrelevant": "多项式写在括号里",
                "problem_with_irrelevant": "多项式写在括号里：化简 (2x² - 3x + 1) - (x² + x - 4)。",
            },
        ],
        "monomial": [
            {
                "problem": "指出 -3a²b 的系数和次数。有人说次数是2，因为只看到 a²。请判断并解释。",
                "answer": "系数是-3，次数是3；次数要把所有字母指数相加，a的指数2加b的指数1。",
                "short_answer": "系数-3，次数3",
                "wrong_solution": "次数是2，因为最高指数是2。",
                "wrong_reason": "漏掉b的指数1，没有把所有字母指数相加。",
                "rule": "单项式次数是所有字母指数的和，系数包括符号。",
                "check": "a²b 中指数和为2+1=3",
                "method_a": "先找数字因数，再把字母指数相加",
                "method_b": "只看最大的一个指数",
                "variant_problem": "指出 5xy³ 的系数和次数。",
                "variant_answer": "系数5，次数4",
                "representation": "系数/字母指数表",
                "condition": "b的指数是1",
                "implausible_answer": "次数2",
                "bad_rule": "单项式次数等于最高指数",
                "incomplete_answer": "系数-3",
                "rule_options": "指数求和，还是只看最高指数",
                "common_mistake": "忘记指数1",
                "changed_condition": "把b改成b³",
                "claim_a": "看到a²，所以次数是2",
                "claim_b": "还要加上b的指数1",
                "irrelevant": "字母按ab顺序写",
                "problem_with_irrelevant": "字母按ab顺序写：指出 -3a²b 的系数和次数。",
            },
        ],
        "polynomial": [
            {
                "problem": "指出 2x² - 3x + 1 是几项式、次数是多少。请解释为什么常数项不决定多项式次数。",
                "answer": "这是三项式，次数是2；次数看最高次项2x²，常数项次数为0，不决定最高次数。",
                "short_answer": "三项式，次数2",
                "wrong_solution": "次数是1，因为最后一项是1。",
                "wrong_reason": "把常数项或项的个数误当成多项式次数。",
                "rule": "多项式次数由最高次项的次数决定。",
                "check": "各项次数分别是2、1、0，最高为2",
                "method_a": "先分项，再看每项次数，取最高",
                "method_b": "看最后一项或项数",
                "variant_problem": "指出 4a³ - a + 7 是几项式、次数是多少。",
                "variant_answer": "三项式，次数3",
                "representation": "项与次数对照表",
                "condition": "最高次项是2x²",
                "implausible_answer": "次数1",
                "bad_rule": "常数项或项数决定次数",
                "incomplete_answer": "三项式",
                "rule_options": "最高次项决定次数，还是最后一项决定次数",
                "common_mistake": "项数和次数混淆",
                "changed_condition": "把2x²改成2x³",
                "claim_a": "有三项，所以次数是3",
                "claim_b": "次数看最高次项，不看项数",
                "irrelevant": "常数项写在最后",
                "problem_with_irrelevant": "常数项写在最后：指出 2x² - 3x + 1 是几项式、次数是多少。",
            },
        ],
        "expr_value": [
            {
                "problem": "当 a=-2、b=3 时，求 2a²-b 的值。有人写成 2a²-b=2×(-2)×2-3。请指出错因并计算。",
                "answer": "a²表示(-2)²=4，不是(-2)×2。2a²-b=2×4-3=5。",
                "short_answer": "5",
                "wrong_solution": "2×(-2)×2-3=-11。",
                "wrong_reason": "代入负数乘方时没有把底数用括号保住。",
                "rule": "代入负数时要加括号，乘方先算底数的幂。",
                "check": "(-2)²=4，所以2×4-3=5",
                "method_a": "先完整代入带括号，再按运算顺序算",
                "method_b": "把a²误写成a×2",
                "variant_problem": "当 x=-3 时，求 x²-2x 的值。",
                "variant_answer": "9+6=15",
                "representation": "代入前后表达式对照",
                "condition": "a=-2是负数",
                "implausible_answer": "-11",
                "bad_rule": "a²就是a乘2",
                "incomplete_answer": "5",
                "rule_options": "负数代入加括号，还是直接替换符号",
                "common_mistake": "负数乘方括号缺失",
                "changed_condition": "把a=-2改成a=2",
                "claim_a": "a²就是a×2",
                "claim_b": "a²是a×a，代入-2应为(-2)²",
                "irrelevant": "b是正数",
                "problem_with_irrelevant": "b是正数。当 a=-2、b=3 时，求 2a²-b 的值。",
            },
        ],
        "equation_concept": [
            {
                "problem": "判断 3x+5=20、2a+1、7-4=3 哪些是方程，哪些是一元一次方程，并说明“方程的解”是什么意思。",
                "answer": "3x+5=20 是一元一次方程；2a+1 不是方程，因为没有等号；7-4=3 是等式但不是方程，因为没有未知数。方程的解是使方程左右两边相等的未知数的值。",
                "short_answer": "3x+5=20 是一元一次方程",
                "wrong_solution": "2a+1也是方程，因为有字母。",
                "wrong_reason": "把含字母的式子和方程混淆，忽略方程必须有等号。",
                "rule": "方程是含未知数的等式；一元一次方程只有一个未知数且未知数次数为1。",
                "check": "把x=5代入3x+5=20左右相等",
                "method_a": "先看等号，再看未知数个数和次数",
                "method_b": "只看有没有字母",
                "variant_problem": "判断 x²+1=5、y-3=0、4+2=6 哪些是一元一次方程。",
                "variant_answer": "y-3=0 是一元一次方程；x²+1=5不是一次；4+2=6没有未知数",
                "representation": "等号/未知数/次数检查表",
                "condition": "必须含未知数且有等号",
                "implausible_answer": "2a+1是方程",
                "bad_rule": "有字母就是方程",
                "incomplete_answer": "3x+5=20",
                "rule_options": "方程定义，还是含字母表达式",
                "common_mistake": "式子、等式、方程混淆",
                "changed_condition": "把2a+1改成2a+1=0",
                "claim_a": "2a+1有字母，所以是方程",
                "claim_b": "没有等号就不是方程",
                "irrelevant": "式子写在同一行",
                "problem_with_irrelevant": "式子写在同一行：3x+5=20、2a+1、7-4=3。请判断哪些是方程。",
            },
        ],
        "angle_calc": [
            {
                "problem": "∠AOB=70°，OC 是角平分线。有人说 ∠AOC=70°。请判断错因，并求 ∠AOC 和 ∠COB。",
                "answer": "角平分线把角分成相等的两部分，所以∠AOC=∠COB=35°；错在把原角当成半角。",
                "short_answer": "∠AOC=∠COB=35°",
                "wrong_solution": "∠AOC=70°。",
                "wrong_reason": "没有理解角平分线是把一个角平分成两个相等角。",
                "rule": "角平分线上的两边把原角分成两个相等的角。",
                "check": "35°+35°=70°",
                "method_a": "先识别整体角，再除以2",
                "method_b": "把整体角直接当作其中一部分",
                "variant_problem": "∠MON=96°，OP平分∠MON，求∠MOP。",
                "variant_answer": "48°",
                "representation": "整体角和两个半角示意图",
                "condition": "OC是角平分线",
                "implausible_answer": "70°",
                "bad_rule": "角平分线不改变角度",
                "incomplete_answer": "35°",
                "rule_options": "角平分线模型，还是直接照抄原角",
                "common_mistake": "整体角与部分角混淆",
                "changed_condition": "把70°改成110°",
                "claim_a": "OC在角内，所以∠AOC还是70°",
                "claim_b": "角平分线把70°分成两个35°",
                "irrelevant": "图形画得不标准",
                "problem_with_irrelevant": "图形画得不标准，∠AOB=70°，OC 是角平分线。请求两个小角。",
            },
        ],
        "algebra_simplify": [
            {
                "problem": "化简 4a - 2b - (a - 5b) + 3，并用 a=2、b=1 代入检验。",
                "answer": "括号前是负号，去括号得4a-2b-a+5b+3=3a+3b+3。代入a=2,b=1，原式和化简式都等于12。",
                "short_answer": "3a+3b+3",
                "wrong_solution": "4a-2b-(a-5b)+3=3a-7b+3。",
                "wrong_reason": "括号前负号没有同时作用到-5b。",
                "rule": "括号前是负号时，括号内每一项都要变号。",
                "check": "a=2、b=1代入原式和化简式都为12",
                "method_a": "把负号看成乘以-1逐项分配",
                "method_b": "只把第一项a变号",
                "variant_problem": "化简 2x - (3x - 4y) + y。",
                "variant_answer": "-x+5y",
                "representation": "去括号前后各项符号的对照表",
                "condition": "负号作用于括号内每一项",
                "implausible_answer": "3a-7b+3",
                "bad_rule": "括号前负号只影响第一项",
                "incomplete_answer": "3a+3b+3",
                "rule_options": "逐项变号，还是只改括号第一项",
                "common_mistake": "漏掉 -5b 变成 +5b",
                "changed_condition": "把括号前的负号改成正号",
                "claim_a": "-(a-5b)=-a-5b",
                "claim_b": "-(a-5b)=-a+5b",
                "irrelevant": "常数项是3",
                "problem_with_irrelevant": "常数项是3。请化简 4a - 2b - (a - 5b) + 3，并检验。",
            },
        ],
        "equation": [
            {
                "problem": "解方程 3(x-2)+5=20。请写出去括号、等式变形，并代回原方程检验。",
                "answer": "3x-6+5=20，3x-1=20，3x=21，x=7。检验：3(7-2)+5=20。",
                "short_answer": "x=7",
                "wrong_solution": "3(x-2)+5=20，所以x-2+5=20÷3。",
                "wrong_reason": "没有对整个左边和右边做同一种等式变形。",
                "rule": "等式变形必须两边同加减、同乘除，去括号要逐项分配。",
                "check": "把x=7代回原方程",
                "method_a": "先去括号再合并求解",
                "method_b": "只把含x的一部分除以3",
                "variant_problem": "解方程 -2(x-3)+5=17，并检验。",
                "variant_answer": "x=-3",
                "representation": "等式两边同步变化的步骤表",
                "condition": "括号外系数作用到括号内每一项",
                "implausible_answer": "x=20/3-3",
                "bad_rule": "看到3(x-2)就只把右边除以3",
                "incomplete_answer": "x=7",
                "rule_options": "等式性质，还是只处理含x的局部",
                "common_mistake": "变形时左右两边没有保持平衡",
                "changed_condition": "把+5改成-4",
                "claim_a": "先除以3更快，所以x-2+5=20÷3",
                "claim_b": "要么先去括号，要么整边同步变形",
                "irrelevant": "x 是未知数",
                "problem_with_irrelevant": "x 是未知数。请解方程 3(x-2)+5=20，并检验。",
            },
        ],
        "word_model": [
            {
                "problem": "小林买 3 支笔和 2 本本子共 28 元，本子单价比笔贵 5 元。设笔的单价为 x，列方程并解释 2(x+5) 表示什么。",
                "answer": "设笔x元，本子x+5元，方程3x+2(x+5)=28；2(x+5)表示2本本子的总价。",
                "short_answer": "3x+2(x+5)=28",
                "wrong_solution": "3x+2x+5=28。",
                "wrong_reason": "只给一本本子加了5元，没有给2本本子都加差价。",
                "rule": "应用题列方程先确定每个量的实际意义，再按总量关系相加。",
                "check": "解得x=3.6，本子8.6；3×3.6+2×8.6=28",
                "method_a": "先设笔价，再表示本子价和总价",
                "method_b": "看到贵5元就只加一次5",
                "variant_problem": "3支笔和4本本子共45元，本子比笔贵6元。设笔价x，列方程。",
                "variant_answer": "3x+4(x+6)=45",
                "representation": "单价、数量、总价三列表",
                "condition": "每一本本子都比笔贵5元",
                "implausible_answer": "3x+2x+5=28",
                "bad_rule": "差价只需要在总式里加一次",
                "incomplete_answer": "3x+2(x+5)=28",
                "rule_options": "总价模型，还是关键词加法",
                "common_mistake": "没有解释括号表示的实际量",
                "changed_condition": "把2本本子改成4本本子",
                "claim_a": "贵5元只出现一次，所以只加5",
                "claim_b": "2本本子各自都贵5元，所以是2(x+5)",
                "irrelevant": "笔是蓝色的",
                "problem_with_irrelevant": "小林买3支蓝色笔和2本本子共28元，本子单价比笔贵5元。请列方程。",
            },
        ],
        "motion": [
            {
                "problem": "一辆车每小时行 60 千米，行了 2 小时 30 分。有人算 60×2.30。请判断单位处理错在哪里，并求路程。",
                "answer": "2小时30分不是2.30小时，而是2.5小时；路程=60×2.5=150千米。",
                "short_answer": "路程150千米",
                "wrong_solution": "60×2.30=138千米。",
                "wrong_reason": "把60进制的30分钟当成十进制的0.30小时。",
                "rule": "行程模型中时间单位必须先统一，再用路程=速度×时间。",
                "check": "半小时行30千米，2小时行120千米，总共150千米",
                "method_a": "先把30分转成0.5小时",
                "method_b": "把2小时30分写成2.30小时",
                "variant_problem": "每小时72千米，行1小时45分，求路程。",
                "variant_answer": "1小时45分=1.75小时，路程126千米",
                "representation": "速度、时间、路程三列表",
                "condition": "30分是半小时",
                "implausible_answer": "138千米",
                "bad_rule": "小时和分钟可以直接写成小数的两位",
                "incomplete_answer": "150",
                "rule_options": "路程=速度×时间，还是把时间数字直接拼接",
                "common_mistake": "没有统一时间单位",
                "changed_condition": "把2小时30分改成2小时15分",
                "claim_a": "2小时30分就是2.30小时",
                "claim_b": "30分是30/60小时",
                "irrelevant": "车是白色的",
                "problem_with_irrelevant": "一辆白色车每小时行60千米，行了2小时30分。请求路程。",
            },
        ],
        "chase": [
            {
                "problem": "甲每分钟80米，乙每分钟60米，甲在乙后面100米同向追乙。为什么不能用 100÷(80+60)？请求追上时间。",
                "answer": "同向追及看距离差缩小速度，80-60=20米/分，所以100÷20=5分钟；80+60用于相向靠近。",
                "short_answer": "5分钟",
                "wrong_solution": "100÷(80+60)=5/7分钟。",
                "wrong_reason": "把同向追及误当成相向相遇。",
                "rule": "同向追及用速度差，相向相遇用速度和。",
                "check": "5分钟后甲走400米，乙走300米，正好多100米",
                "method_a": "先判断同向，再用速度差",
                "method_b": "看到两个人运动就加速度",
                "variant_problem": "甲90米/分，乙65米/分，甲落后150米同向追乙，几分钟追上？",
                "variant_answer": "150÷(90-65)=6分钟",
                "representation": "距离差每分钟减少20米的线段图",
                "condition": "同向",
                "implausible_answer": "5/7分钟",
                "bad_rule": "两人运动速度一定相加",
                "incomplete_answer": "5分钟",
                "rule_options": "速度差模型，还是速度和模型",
                "common_mistake": "没有先判断运动方向",
                "changed_condition": "把同向改成相向",
                "claim_a": "两人都在动，所以速度相加",
                "claim_b": "同向时距离差按速度差缩小",
                "irrelevant": "两人穿同色衣服",
                "problem_with_irrelevant": "甲乙穿同色衣服。甲每分钟80米，乙每分钟60米，甲在乙后面100米同向追乙。请算追上时间。",
            },
        ],
        "clock": [
            {
                "problem": "3点30分时，有人按3点整算成90°。请判断错因，并求时针和分针的较小夹角。",
                "answer": "分针在6，时针从3走到3和4中间，半小时移动15°；较小夹角是90°-15°=75°。",
                "short_answer": "75°",
                "wrong_solution": "3点30分仍按3点整，夹角90°。",
                "wrong_reason": "忽略时针在30分钟内也会移动。",
                "rule": "钟表角要同时跟踪分针和时针的位置。",
                "check": "时针每小时30°，半小时15°",
                "method_a": "先定位分针，再算时针移动",
                "method_b": "只看整点的初始角",
                "variant_problem": "4点30分时较小夹角是多少？",
                "variant_answer": "4点整120°，半小时后时针多走15°，夹角45°",
                "representation": "钟面上每大格30°的位置图",
                "condition": "30分钟内时针移动15°",
                "implausible_answer": "90°",
                "bad_rule": "半点时只看分针位置，时针不动",
                "incomplete_answer": "75°",
                "rule_options": "钟面追及模型，还是整点静态模型",
                "common_mistake": "漏算时针移动",
                "changed_condition": "把3点30分改成3点20分",
                "claim_a": "分针在6，所以只和3点整一样",
                "claim_b": "时针也在动，不能按整点算",
                "irrelevant": "钟表外壳是圆形",
                "problem_with_irrelevant": "一个圆形外壳的钟表显示3点30分。请求时针和分针较小夹角。",
            },
        ],
        "work_rate": [
            {
                "problem": "甲单独6天完成，乙单独3天完成。有人用 (6+3)÷2 求合作时间。请判断模型错在哪里，并求合作每天完成几分之几。",
                "answer": "不能平均天数。设工作总量为1，甲效率1/6，乙效率1/3，合作每天完成1/2，所以合作2天完成。",
                "short_answer": "合作每天完成1/2，2天完成",
                "wrong_solution": "(6+3)÷2=4.5天。",
                "wrong_reason": "平均完成天数不等于合做效率。",
                "rule": "工程问题用工作总量=1，把天数转成效率再相加。",
                "check": "2天内甲做1/3，乙做2/3，合计1",
                "method_a": "先求效率再相加",
                "method_b": "直接平均单独完成天数",
                "variant_problem": "甲单独8天、乙单独4天完成，合作几天完成？",
                "variant_answer": "1/(1/8+1/4)=8/3天",
                "representation": "工作总量1和每日效率表",
                "condition": "两人同时合作时效率相加",
                "implausible_answer": "4.5天",
                "bad_rule": "合作时间等于单独时间的平均数",
                "incomplete_answer": "1/2",
                "rule_options": "工作效率模型，还是天数平均模型",
                "common_mistake": "没有把天数转成效率",
                "changed_condition": "乙先做1天后甲加入",
                "claim_a": "6天和3天平均就是合作时间",
                "claim_b": "应先把每天完成量加起来",
                "irrelevant": "甲乙使用同一种工具",
                "problem_with_irrelevant": "甲乙使用同一种工具。甲单独6天完成，乙单独3天完成。请算合作时间。",
            },
        ],
        "rational": [
            {
                "problem": "计算 -7 + 12 - (-5)，并用数轴移动或减法转加法解释每一步符号来源。",
                "answer": "-7+12-(-5)=-7+12+5=10。减去-5等于加5，数轴上从-7向右12到5，再向右5到10。",
                "short_answer": "10",
                "wrong_solution": "-7+12-(-5)=-7+12-5=0。",
                "wrong_reason": "把减去负数错当成继续减正数。",
                "rule": "减去一个数等于加上这个数的相反数。",
                "check": "把-(-5)转成+5后按顺序计算",
                "method_a": "先把减法转加法再算",
                "method_b": "看到减号就直接减5",
                "variant_problem": "计算 -12 + 7 - (-3)，并说明符号。",
                "variant_answer": "-12+7+3=-2",
                "representation": "数轴向左、向右移动图",
                "condition": "括号里的数是-5",
                "implausible_answer": "0",
                "bad_rule": "两个减号放在一起仍然表示减",
                "incomplete_answer": "10",
                "rule_options": "减法转加法，还是只看表面的减号",
                "common_mistake": "漏掉负负得正的意义",
                "changed_condition": "把 -(-5) 改成 -(+5)",
                "claim_a": "前面有减号，所以一定往左走5",
                "claim_b": "减去-5等于向右走5",
                "irrelevant": "题目写在第一行",
                "problem_with_irrelevant": "题目写在第一行：计算 -7 + 12 - (-5)，并解释符号来源。",
            },
        ],
        "rational_compare": [
            {
                "problem": "把 -3、-1.5、0、2/3 从小到大排列。有人说 -3 比 -1.5 大，因为 3 比 1.5 大。请解释错在哪里。",
                "answer": "从小到大是 -3 < -1.5 < 0 < 2/3。错在负数大小要看数轴位置，-3 在 -1.5 左边，所以 -3 更小。",
                "short_answer": "-3 < -1.5 < 0 < 2/3",
                "wrong_solution": "-1.5 < -3 < 0 < 2/3，因为1.5小于3。",
                "wrong_reason": "比较负数时只比较绝对值，忽略数轴上越往右越大。",
                "rule": "有理数大小比较可以统一到数轴位置，越往右越大。",
                "check": "在数轴上标出四个数的位置",
                "method_a": "画数轴或统一成小数后比较",
                "method_b": "只比较负号后面的数字大小",
                "variant_problem": "把 -2.2、-2、1/3、0 从小到大排列，并说明负数部分。",
                "variant_answer": "-2.2 < -2 < 0 < 1/3",
                "representation": "数轴位置图",
                "condition": "负数比较时方向会反过来",
                "implausible_answer": "-1.5 < -3 < 0 < 2/3",
                "bad_rule": "负数也按绝对值越大数值越大",
                "incomplete_answer": "-3 < -1.5 < 0 < 2/3",
                "rule_options": "数轴位置比较，还是绝对值直接比较",
                "common_mistake": "负数比较方向弄反",
                "changed_condition": "把 -1.5 改成 -3.5",
                "claim_a": "-3比-1.5大，因为3比1.5大",
                "claim_b": "数轴上-3更靠左，所以更小",
                "irrelevant": "这些数写在同一行",
                "problem_with_irrelevant": "这些数写在同一行：-3、-1.5、0、2/3。请从小到大排列并说明依据。",
            },
        ],
        "rational_classify": [
            {
                "problem": "把 -3、0、2.5、-1/4、7 分别放入“正有理数、负有理数、整数、分数”集合；允许一个数进入多个集合，并说明 0 为什么单独处理。",
                "answer": "正有理数：2.5、7；负有理数：-3、-1/4；整数：-3、0、7；分数：2.5、-1/4。0是有理数和整数，但既不是正数也不是负数。",
                "short_answer": "0是有理数和整数，但非正非负",
                "wrong_solution": "0放入正有理数，因为0不是负数。",
                "wrong_reason": "把“不是负数”误当成“正数”。",
                "rule": "有理数分类要分别看正负零、整数/分数，一个数可属于多个集合。",
                "check": "逐个数同时检查正负性和整数/分数属性",
                "method_a": "先按正负零分，再按整数/分数分",
                "method_b": "只看一个标签就分类",
                "variant_problem": "把 -2、0、1/3、4.8 分到正有理数、负有理数、整数、分数集合。",
                "variant_answer": "正有理数：1/3、4.8；负有理数：-2；整数：-2、0；分数：1/3、4.8",
                "representation": "集合归类表",
                "condition": "0既不是正数也不是负数",
                "implausible_answer": "0是正有理数",
                "bad_rule": "不是负数就一定是正数",
                "incomplete_answer": "正有理数有2.5和7",
                "rule_options": "集合多重归类，还是单一标签归类",
                "common_mistake": "0的正负性处理错误",
                "changed_condition": "加入 -0.5",
                "claim_a": "0不是负数，所以是正数",
                "claim_b": "0既不是正数也不是负数",
                "irrelevant": "数字之间用逗号隔开",
                "problem_with_irrelevant": "数字之间用逗号隔开：-3、0、2.5、-1/4、7。请完成有理数分类。",
            },
        ],
        "number_line": [
            {
                "problem": "数轴上 A=-2.5，B=1。点 C 在 A 的右边，且 AC=3。求 C 表示的数，并把 A、B、C 从小到大排列。",
                "answer": "C=-2.5+3=0.5；从小到大 A(-2.5)<C(0.5)<B(1)。",
                "short_answer": "C=0.5，A<C<B",
                "wrong_solution": "C=-5.5，因为距离3就向左减3。",
                "wrong_reason": "没有看清C在A的右边，方向判断错。",
                "rule": "数轴向右数值增大，向左数值减小。",
                "check": "从-2.5向右移动3个单位到0.5",
                "method_a": "先判断方向再加减距离",
                "method_b": "看到距离就固定做减法",
                "variant_problem": "数轴上 D=1.2，E在D左边2个单位。求E并与0比较。",
                "variant_answer": "E=-0.8，E<0",
                "representation": "数轴移动图",
                "condition": "C在A的右边",
                "implausible_answer": "-5.5",
                "bad_rule": "距离都用减法处理",
                "incomplete_answer": "C=0.5",
                "rule_options": "方向移动模型，还是只看距离数值",
                "common_mistake": "左右方向与加减对应错",
                "changed_condition": "把右边改成左边",
                "claim_a": "距离是3，所以-2.5-3",
                "claim_b": "右边表示增加，所以-2.5+3",
                "irrelevant": "点A用黑点标出",
                "problem_with_irrelevant": "点A用黑点标出，A=-2.5，C在A右边且AC=3。请确定C的位置。",
            },
        ],
        "absolute": [
            {
                "problem": "已知 |x|=3。x 可能是多少？再判断 |-3| 和 -|3| 是否相等，并说明绝对值和前置负号的区别。",
                "answer": "x可能是3或-3；|-3|=3，-|3|=-3，不相等。绝对值是到0的距离，前置负号是在结果前取相反数。",
                "short_answer": "x=3或-3；|-3|≠-|3|",
                "wrong_solution": "|x|=3，所以x只能是3；|-3|=-3。",
                "wrong_reason": "把距离和原数符号混淆。",
                "rule": "绝对值表示到0的距离，结果非负。",
                "check": "|3|=3且|-3|=3",
                "method_a": "用数轴距离理解绝对值",
                "method_b": "把绝对值符号当普通括号",
                "variant_problem": "已知 |x|=2.5，x可能是多少？比较 |-2.5| 和 -|2.5|。",
                "variant_answer": "x=2.5或-2.5；|-2.5|=2.5，-|2.5|=-2.5",
                "representation": "到0距离相等的数轴图",
                "condition": "绝对值结果非负",
                "implausible_answer": "x只能是3",
                "bad_rule": "绝对值里面是负数，结果也负",
                "incomplete_answer": "x=3",
                "rule_options": "距离模型，还是符号复制",
                "common_mistake": "漏掉负数解或前置负号",
                "changed_condition": "把3改成0",
                "claim_a": "绝对值不改变数字，所以|-3|=-3",
                "claim_b": "绝对值是距离，所以|-3|=3",
                "irrelevant": "x写成小写字母",
                "problem_with_irrelevant": "x写成小写字母。已知 |x|=3，请求x的可能值并比较 |-3| 与 -|3|。",
            },
        ],
        "opposite": [
            {
                "problem": "写出 -7、0、2.5 的相反数，并解释为什么 0 的相反数还是 0。再判断 -(-7) 与 -7 是否相同。",
                "answer": "-7的相反数是7，0的相反数是0，2.5的相反数是-2.5；-(-7)=7，与-7不同。",
                "short_answer": "7、0、-2.5；-(-7)=7",
                "wrong_solution": "0没有相反数，-(-7)=-7。",
                "wrong_reason": "没有用“和为0”或数轴对称理解相反数。",
                "rule": "相反数到0距离相等、方向相反，0的相反数仍是0。",
                "check": "一个数与它的相反数相加等于0",
                "method_a": "用和为0或数轴对称判断",
                "method_b": "只机械增删负号",
                "variant_problem": "写出 -3.2、4、0 的相反数，并化简 -(-3.2)。",
                "variant_answer": "3.2、-4、0；-(-3.2)=3.2",
                "representation": "数轴关于0对称图",
                "condition": "0到0距离为0",
                "implausible_answer": "0没有相反数",
                "bad_rule": "相反数就是随便加一个负号",
                "incomplete_answer": "7、-2.5",
                "rule_options": "和为0模型，还是负号数量模型",
                "common_mistake": "0和多重负号处理错",
                "changed_condition": "把 -7 改成 7",
                "claim_a": "0没有方向，所以没有相反数",
                "claim_b": "0的相反数还是0",
                "irrelevant": "数字之间有顿号",
                "problem_with_irrelevant": "数字之间有顿号：-7、0、2.5。请写相反数并解释0。",
            },
        ],
        "pos_neg": [
            {
                "problem": "规定向东为正。小车先向西4米，再向东7米；另有海拔-3米。请写出运动的正负数、最后位置，并说明海拔-3米的负号意义。",
                "answer": "向西4米记为-4，向东7米记为+7，最后-4+7=+3米，在起点东边3米。海拔-3米表示低于海平面3米。",
                "short_answer": "+3米，海拔-3米表示低于海平面3米",
                "wrong_solution": "向西4米记为+4，因为走了4米。",
                "wrong_reason": "没有根据规定的正方向解释符号。",
                "rule": "正负数表示相反意义的量，必须先确定基准或正方向。",
                "check": "西和东方向相反，净位移应为向东3米",
                "method_a": "先定正方向再记录量",
                "method_b": "只看数量大小不看方向",
                "variant_problem": "规定收入为正，支出20元和收入35元合起来账户变化多少？",
                "variant_answer": "-20+35=+15元",
                "representation": "方向箭头或收支表",
                "condition": "向东为正",
                "implausible_answer": "向西4米记为+4",
                "bad_rule": "有数量就是正数",
                "incomplete_answer": "+3米",
                "rule_options": "相反意义模型，还是只看数字大小",
                "common_mistake": "忘记基准或正方向",
                "changed_condition": "把向东为正改成向西为正",
                "claim_a": "4米是正数，所以向西记+4",
                "claim_b": "符号由正方向决定，不由距离大小决定",
                "irrelevant": "小车是红色",
                "problem_with_irrelevant": "红色小车先向西4米，再向东7米，规定向东为正。请写正负数和最后位置。",
            },
        ],
        "rational_muldiv": [
            {
                "problem": "计算 (-6)×4÷(-3)。请先不算数值，只判断符号；再计算，并说明如果再乘一个 -2 符号会怎样变。",
                "answer": "原式有两个负因数，结果为正，数值6×4÷3=8；再乘-2后负因数个数变奇数，结果为负。",
                "short_answer": "8；再乘-2后为负",
                "wrong_solution": "因为第一个数是负数，所以结果一定为负。",
                "wrong_reason": "只看第一个负号，没有统计乘除中的负号个数。",
                "rule": "有理数乘除先判断符号，再算绝对值；负因数个数决定符号。",
                "check": "(-6)×4=-24，-24÷(-3)=8",
                "method_a": "先判符号再算绝对值",
                "method_b": "只看开头符号",
                "variant_problem": "计算 (-2)×(-5)÷10，并说明符号。",
                "variant_answer": "结果为正，值为1",
                "representation": "负因数个数统计表",
                "condition": "除以负数也会改变符号",
                "implausible_answer": "-8",
                "bad_rule": "开头是负数，结果一定负",
                "incomplete_answer": "8",
                "rule_options": "负因数个数判断，还是只看第一个数",
                "common_mistake": "符号和绝对值混在一起算",
                "changed_condition": "再乘一个 -2",
                "claim_a": "前面有负号，结果一定负",
                "claim_b": "两个负号相互抵消，结果为正",
                "irrelevant": "式子中有括号",
                "problem_with_irrelevant": "式子中有括号：计算 (-6)×4÷(-3)，请先判断符号再计算。",
            },
        ],
        "rational_mixed": [
            {
                "problem": "判断错解：2 - (-3) × 4 = 5 × 4 = 20。请指出错因，写出正确运算顺序和结果。",
                "answer": "错在先做了2-(-3)，没有先算乘法。正确：(-3)×4=-12，2-(-12)=14。",
                "short_answer": "14",
                "wrong_solution": "2 - (-3) × 4 = 5 × 4 = 20。",
                "wrong_reason": "违反先乘除后加减的运算顺序。",
                "rule": "有理数混合运算先乘方，再乘除，后加减；有括号先算括号。",
                "check": "先算乘法得到2-(-12)，再算减负数",
                "method_a": "先识别运算顺序再处理符号",
                "method_b": "从左到右不看优先级",
                "variant_problem": "计算 3 - (-2)×5，并说明顺序。",
                "variant_answer": "3-(-10)=13",
                "representation": "运算优先级标注图",
                "condition": "乘法优先于减法",
                "implausible_answer": "20",
                "bad_rule": "没有括号就完全从左到右",
                "incomplete_answer": "14",
                "rule_options": "运算顺序，还是只从左到右",
                "common_mistake": "先做加减再做乘法",
                "changed_condition": "把4改成-4",
                "claim_a": "从左往右先算2-(-3)",
                "claim_b": "乘法优先，所以先算(-3)×4",
                "irrelevant": "式子中有空格",
                "problem_with_irrelevant": "式子中有空格：2 - (-3) × 4。请按正确顺序计算。",
            },
        ],
        "power_sci": [
            {
                "problem": "比较 -2² 和 (-2)² 的值，并说明两个式子的底数分别是谁。",
                "answer": "-2²=-(2²)=-4，(-2)²=4；没有括号时底数是2，有括号时底数是-2。",
                "short_answer": "-2²=-4，(-2)²=4",
                "wrong_solution": "-2²=(-2)²=4。",
                "wrong_reason": "没有区分前置负号和括号内负数。",
                "rule": "乘方先确定底数，括号决定负号是否属于底数。",
                "check": "把-2²写成-(2×2)",
                "method_a": "先找底数再乘方",
                "method_b": "看到-2就默认整个-2平方",
                "variant_problem": "比较 -3² 和 (-3)²。",
                "variant_answer": "-3²=-9，(-3)²=9",
                "representation": "底数和指数的标注图",
                "condition": "是否有括号",
                "implausible_answer": "两个都等于4",
                "bad_rule": "负号总是底数的一部分",
                "incomplete_answer": "-4和4",
                "rule_options": "先确定底数，还是只看数字2",
                "common_mistake": "漏看括号",
                "changed_condition": "给-2加上括号",
                "claim_a": "-2²就是负数平方，一定为正",
                "claim_b": "没有括号时负号不属于底数",
                "irrelevant": "指数写在右上角",
                "problem_with_irrelevant": "指数写在右上角。请比较 -2² 和 (-2)² 的值并说明底数。",
            },
            {
                "problem": "把 3500000 写成科学记数法。有人写成 35×10^5，请判断数值是否对、格式是否合格。",
                "answer": "35×10^5数值等于3500000，但不是标准科学记数法；标准写法是3.5×10^6。",
                "short_answer": "3.5×10^6",
                "wrong_solution": "3500000=35×10^5，所以格式合格。",
                "wrong_reason": "忽略标准科学记数法中前面的数要大于等于1且小于10。",
                "rule": "科学记数法标准形式是a×10^n，其中1≤a<10。",
                "check": "3.5的小数点向右移6位得3500000",
                "method_a": "先写成1到10之间的数再确定指数",
                "method_b": "只要数值相等就认为格式合格",
                "variant_problem": "把 0.0048 写成科学记数法。",
                "variant_answer": "4.8×10^-3",
                "representation": "小数点移动位数表",
                "condition": "前面的数必须在[1,10)内",
                "implausible_answer": "35×10^5是标准格式",
                "bad_rule": "数值相等就是标准科学记数法",
                "incomplete_answer": "3.5×10^6",
                "rule_options": "标准形式检查，还是只检查数值",
                "common_mistake": "前面的数没有化到1到10之间",
                "changed_condition": "把3500000改成350000",
                "claim_a": "35×10^5数值对，所以就是标准答案",
                "claim_b": "数值对还要检查格式",
                "irrelevant": "数字里有多个0",
                "problem_with_irrelevant": "数字里有多个0。请把3500000写成标准科学记数法。",
            },
        ],
        "unit_conversion": [
            {
                "problem": "一个正方形边长从 1 米改写成 10 分米。有人说面积只扩大 10 倍。请判断错因，并写出 1 平方米等于多少平方分米。",
                "answer": "面积是二维量，边长扩大10倍，面积单位进率要平方化；1平方米=100平方分米。",
                "short_answer": "1平方米=100平方分米",
                "wrong_solution": "1米=10分米，所以1平方米=10平方分米。",
                "wrong_reason": "把长度一维进率直接套到面积二维单位。",
                "rule": "面积单位换算要把长度进率平方化，体积单位要立方化。",
                "check": "1m×1m=10dm×10dm=100dm²",
                "method_a": "用边长模型验证面积单位",
                "method_b": "直接照搬长度单位进率",
                "variant_problem": "1立方米等于多少立方分米？用长方体模型说明。",
                "variant_answer": "1m³=1000dm³",
                "representation": "边长换算后的正方形面积图",
                "condition": "题目问的是面积不是长度",
                "implausible_answer": "10平方分米",
                "bad_rule": "所有单位换算都只乘进率一次",
                "incomplete_answer": "100平方分米",
                "rule_options": "维度模型，还是只记长度进率",
                "common_mistake": "没有检查量的维度",
                "changed_condition": "把面积改成体积",
                "claim_a": "米到分米是10倍，平方米也10倍",
                "claim_b": "面积有两个方向，所以是10×10",
                "irrelevant": "正方形画在白纸上",
                "problem_with_irrelevant": "正方形画在白纸上，边长从1米改写成10分米。请判断面积单位怎样换算。",
            },
        ],
        "area_volume": [
            {
                "problem": "长方体长4cm、宽3cm、高2cm。有人把 4×3 当成答案。请判断他求的是哪个量，若题目问体积应怎样改正并写单位。",
                "answer": "4×3=12cm²是底面积；体积要乘三个维度，4×3×2=24cm³。",
                "short_answer": "体积24cm³",
                "wrong_solution": "体积=4×3=12cm²。",
                "wrong_reason": "把底面积当成体积，少了高这一维。",
                "rule": "面积用两个维度，体积用三个维度，单位随维度变化。",
                "check": "长、宽、高三个方向都参与体积",
                "method_a": "先判断题目求面积还是体积",
                "method_b": "看到长和宽就直接相乘当答案",
                "variant_problem": "长方体长5cm、宽4cm、高3cm，求体积并说明单位。",
                "variant_answer": "5×4×3=60cm³",
                "representation": "长、宽、高三维模型",
                "condition": "题目问体积",
                "implausible_answer": "12cm²",
                "bad_rule": "长方体只要长乘宽",
                "incomplete_answer": "24",
                "rule_options": "体积模型，还是底面积模型",
                "common_mistake": "单位没有随维度变化",
                "changed_condition": "把题目问体积改成问底面积",
                "claim_a": "4×3已经用了两个数据，够了",
                "claim_b": "体积必须包含高",
                "irrelevant": "长方体是蓝色的",
                "problem_with_irrelevant": "一个蓝色长方体长4cm、宽3cm、高2cm。请判断体积是多少。",
            },
        ],
        "angle": [
            {
                "problem": "一个角是35°。某同学把它的补角写成55°。请判断他混淆了什么概念，并写出余角和补角。",
                "answer": "55°是余角，因为余角和为90°；补角是180°-35°=145°。",
                "short_answer": "余角55°，补角145°",
                "wrong_solution": "补角=90°-35°=55°。",
                "wrong_reason": "把余角的90°关系错当成补角关系。",
                "rule": "余角和为90°，补角和为180°。",
                "check": "35°+145°=180°，35°+55°=90°",
                "method_a": "先判断问余角还是补角",
                "method_b": "所有角度题都先用90°减",
                "variant_problem": "一个角是42°，求它的余角和补角。",
                "variant_answer": "余角48°，补角138°",
                "representation": "90°直角和180°平角的对照图",
                "condition": "题目问补角",
                "implausible_answer": "补角55°",
                "bad_rule": "余角和补角都用90°减",
                "incomplete_answer": "55°和145°",
                "rule_options": "余角/补角定义，还是只套90°",
                "common_mistake": "没看清问的是余角还是补角",
                "changed_condition": "把补角改成余角",
                "claim_a": "55°就是补角",
                "claim_b": "55°是余角，补角要凑180°",
                "irrelevant": "这个角画在纸的左边",
                "problem_with_irrelevant": "一个画在纸左边的角是35°。请求它的余角和补角。",
            },
        ],
        "line_segment": [
            {
                "problem": "AB=12cm，C 在 AB 上。只知道 AC=6cm，能否直接判断 C 是中点？请说明还要验证什么。",
                "answer": "如果确认C在AB上，则CB=12-6=6cm，AC=CB，所以C是中点；判断中点必须验证点在线段上且两段相等。",
                "short_answer": "需验证C在AB上且AC=CB",
                "wrong_solution": "AC是6cm，所以C一定是任何线段的中点。",
                "wrong_reason": "没有确认点的位置和另一段长度。",
                "rule": "中点是在线段上且把线段分成相等两段的点。",
                "check": "CB=AB-AC=6cm",
                "method_a": "用定义检查位置和相等",
                "method_b": "看到一半长度就直接下结论",
                "variant_problem": "AB=18cm，C在AB上，AC=7cm。C是中点吗？",
                "variant_answer": "不是，CB=11cm，AC≠CB",
                "representation": "线段AB上点C分成AC、CB的图示",
                "condition": "C在AB上",
                "implausible_answer": "只要AC=6就一定是中点",
                "bad_rule": "只知道一段长度就能判中点",
                "incomplete_answer": "C是中点",
                "rule_options": "中点定义，还是只看一个长度",
                "common_mistake": "漏算CB",
                "changed_condition": "把AC=6cm改成AC=5cm",
                "claim_a": "6是12的一半，所以不用看别的",
                "claim_b": "还要确认C在AB上并算CB",
                "irrelevant": "线段画得很直",
                "problem_with_irrelevant": "线段画得很直，AB=12cm，C在AB上，AC=6cm。请判断C是否中点。",
            },
        ],
        "point_line_plane": [
            {
                "problem": "一个点沿直线运动，会留下什么图形？请说明点和线的区别，并举例说明点动成线。",
                "answer": "会留下线。点表示位置，线表示点运动形成的轨迹；如笔尖移动留下线迹。",
                "short_answer": "点动成线",
                "wrong_solution": "点移动后还是一个点。",
                "wrong_reason": "忽略运动轨迹形成新的几何对象。",
                "rule": "点动成线，线动成面，面动成体。",
                "check": "笔尖连续移动时留下的是线迹",
                "method_a": "看运动对象和留下的轨迹",
                "method_b": "只看原来的对象是什么",
                "variant_problem": "一条线段沿垂直方向平移，会扫出什么图形？",
                "variant_answer": "会扫出长方形一类的面",
                "representation": "运动对象到轨迹结果的箭头图",
                "condition": "点是连续运动的",
                "implausible_answer": "仍然只有一个点",
                "bad_rule": "原来是什么，运动后还是什么",
                "incomplete_answer": "线",
                "rule_options": "轨迹生成关系，还是静态名称",
                "common_mistake": "没有区分对象和轨迹",
                "changed_condition": "把点运动改成线运动",
                "claim_a": "点很小，移动后也只能是点",
                "claim_b": "连续位置组成线",
                "irrelevant": "点用红笔画",
                "problem_with_irrelevant": "一个红点沿直线运动。请说明会留下什么图形以及理由。",
            },
        ],
        "solid_views": [
            {
                "problem": "一个正方体展开图由6个正方形连成一片。有人说只要有6个正方形就一定能折成正方体。请判断并说明还要检查什么。",
                "answer": "不一定。还要检查连接方式，折起后不能重叠、不能缺面，每个面的位置关系要能围成立体。",
                "short_answer": "不一定，还要检查连接方式和折叠后是否重叠/缺面",
                "wrong_solution": "有6个正方形就一定是正方体展开图。",
                "wrong_reason": "只检查面数，没有检查面的位置关系。",
                "rule": "展开图不仅要面数正确，还要能无重叠地围成立体。",
                "check": "折叠后6个面应分别占据正方体6个方向",
                "method_a": "检查数量、连接方式、折叠重叠",
                "method_b": "只数正方形个数",
                "variant_problem": "4个小正方体底层排成一行，最左边上面再放1个，从正面看高度怎样？",
                "variant_answer": "从正面看各列高度为2、1、1、1",
                "representation": "展开图折叠或三视图草图",
                "condition": "折起后不能重叠或缺面",
                "implausible_answer": "只要6个就一定可以",
                "bad_rule": "展开图只需要数面数",
                "incomplete_answer": "不一定",
                "rule_options": "空间折叠检查，还是平面数量检查",
                "common_mistake": "把必要条件当充分条件",
                "changed_condition": "把6个正方形改成5个正方形",
                "claim_a": "正方体有6个面，所以6个正方形一定够",
                "claim_b": "6个面只是必要条件，还要看连接方式",
                "irrelevant": "正方形涂了颜色",
                "problem_with_irrelevant": "6个涂色正方形连成一片。请判断是否一定能折成正方体。",
            },
        ],
    }
    if family == "decimal_ops":
        decimal_choices = contexts["decimal_ops"]
        if "小数与分数互化" in question_type:
            return decimal_choices[2]
        if "小数乘除" in question_type:
            return decimal_choices[1]
        if "小数加减" in question_type:
            return decimal_choices[0]
    if family == "integer_ops":
        integer_choices = contexts["integer_ops"]
        sequence_index = max(0, (offset - 1) // 3)
        if "简便" in question_type:
            pool = [integer_choices[1], integer_choices[4]]
            return pool[sequence_index % len(pool)]
        if "有余数" in question_type:
            pool = [integer_choices[3], integer_choices[6], integer_choices[7]]
            return pool[sequence_index % len(pool)]
        if "多位数" in question_type:
            pool = [integer_choices[2], integer_choices[5]]
            return pool[sequence_index % len(pool)]
    if family == "order_ops":
        order_choices = contexts["order_ops"]
        if "小数/分数" in question_type:
            return order_choices[1]
        return order_choices[0]
    if family == "fraction_ops":
        fraction_choices = contexts["fraction_ops"]
        if "除法" in question_type or "乘法" in question_type:
            return fraction_choices[1]
        return fraction_choices[0]
    choices = contexts.get(family, contexts["word_model"])
    return choices[(offset - 1) % len(choices)]


def _example_for(
    node: dict[str, Any],
    question_type: str,
    level: str,
    offset: int,
    kind: str = "",
) -> dict[str, Any]:
    specific = _specific_example_for(node, question_type)
    if specific and offset == 1:
        prompt = _level_prompt(specific["prompt"], level, offset)
        return {
            "prompt": prompt,
            "answer": specific["answer"],
            "steps": specific["steps"],
            "identity": _fallback_question_identity(
                node,
                question_type,
                kind,
                prompt=prompt,
                answer=specific["answer"],
                offset=offset,
                problem_instance_problem=specific["prompt"],
            ),
        }
    if _topic_family(node, question_type) in {
        "decimal_ops",
        "integer_ops",
        "number_sense",
        "order_ops",
        "fraction_meaning",
        "fraction_ops",
    }:
        generated = _generated_diagnostic_example_for(node, question_type, kind, offset)
        return {
            "prompt": _level_prompt(generated["prompt"], level, offset),
            "answer": generated["answer"],
            "steps": generated["steps"],
            "identity": generated["identity"],
        }

    text = f"{node.get('id', '')} {node.get('name', '')} {node.get('domain', '')} {question_type}"
    examples = [
        (["估算", "数感"], "先不精算，判断 398 × 51 更接近 2000、20000 还是 200000，再说明理由。", "更接近 20000；398 接近 400，51 接近 50，400×50=20000。", ["先取近似数。", "比较数量级。", "再决定结果范围。"]),
        (["整数", "多位数", "有余数"], "某同学做有余数除法，只写了“商是120，余数是1”。请写出必须满足的验算关系，并说明余数为什么必须小于除数。", "必须满足 除数×商+余数=被除数，且余数小于除数；否则商还能继续增加。", ["写出有余数除法验算结构。", "解释余数小于除数的原因。", "判断答案是否可检验。"]),
        (["小数"], "一张购物小票把 7.2 元/千克、0.48 千克的金额写成 34.56 元。请先用估算判断数量级，再指出小数点错在哪里，并写出合理金额；最后说明小数乘法位数规则为什么必须配合估算。", "7.2约7，0.48约0.5，金额应接近3.5元，不可能是34.56元；正确金额是3.456元。小数位数规则只有和数量级估算一起检查时才可靠。", ["先用7×0.5估算数量级。", "用估算排除34.56元。", "计算7.2×0.48=3.456，并说明位数规则要配合数量级检验。"]),
        (["分数运算", "通分", "分数乘法", "分数除法"], "两位同学计算 5/6 - 1/4：甲写 4/2，乙写 7/12。请判断谁对，指出甲错在什么地方，并写出通分过程。", "乙对，结果是 7/12。甲把分母、分子随意相减，没有先通分；5/6=10/12，1/4=3/12，所以差是7/12。", ["先判断分母不同不能直接相减。", "用公分母 12 通分。", "指出错误方法破坏了分数单位。"]),
        (["单位1", "分数意义"], "一本书读了全书的 3/5，正好是 60 页。全书多少页？先写单位1。", "单位1是全书页数；60 ÷ 3/5 = 100 页。", ["找单位1。", "已知部分和分率，求整体用除法。", "写答句。"]),
        (["百分", "增长率", "折扣"], "一件商品先打八折，再在折后价基础上涨价 20%。有人说“降20%再涨20%，回到原价”。请判断并说明百分数的单位1分别是谁。", "不能回到原价。八折后是原价的80%，再涨20%是以折后价为单位1，得到 80%×120%=96% 原价。", ["先区分两次百分数的单位1。", "用乘法模型表示连续变化。", "比较 96% 与 100%。"]),
        (["比、", "比例", "比例尺", "化简比", "求比值", "按比例"], "甲乙两数的比是 3:5，和是 64。小林直接算 64×3/5 求甲。请判断错在哪里，并用份数模型求出甲乙。", "错在 3/5 是甲与乙的比，不是甲占总数的比例；总份数 8，每份 8，甲24，乙40。", ["把 3:5 转成总份数。", "说明甲占总数 3/8。", "求每份并回到实际量。"]),
        (["等量", "列式"], "男生比女生多 8 人，男生有 26 人。某同学列 26+8。请先写等量关系，再判断这个列式错在哪里。", "等量关系：女生人数+8=男生人数。女生=26-8=18；26+8 把已知男生又增加了一次差量。", ["先写文字等量关系。", "判断谁多谁少。", "解释错误列式的含义。"]),
        (["方程", "等式性质", "移项"], "解方程 3x + 5 = 20。有人第一步写 x+5=20÷3，请判断是否保持等式平衡，并给出正确解法和检验。", "不对，3x+5 不能整体只除 3x 的系数。正确：两边减5得3x=15，再除3得x=5；检验3×5+5=20。", ["判断等式变形是否对两边做同一件事。", "先处理加减项。", "代回原方程检验。"]),
        (["字母", "代数式"], "“a 的 3 倍减去 5”和“a 减去 5 后的 3 倍”是否一样？分别写成代数式，并用 a=4 检验。", "不一样；前者 3a-5，后者 3(a-5)。a=4 时分别为7和-3。", ["先按语言顺序写式。", "用括号表达整体。", "代入同一个数检验差异。"]),
        (["审题", "读题"], "小明有 24 张卡片，比小华多 6 张。请圈出“谁比谁多”，写出等量关系，并解释为什么不是 24+6。", "小明比小华多6张；等量关系：小华+6=小明，所以小华=24-6。24+6 表示比小明还多6张的人。", ["定位比较对象。", "写成等量关系。", "解释错误方向。"]),
        (["行程", "速度", "路程", "时间"], "一辆车每小时行 60 千米，行了 2 小时 30 分。有人算 60×2.30。请判断单位处理错在哪里，并求路程。", "错在 2小时30分不是2.30小时，而是2.5小时；路程=60×2.5=150千米。", ["写出路程=速度×时间。", "先统一时间单位。", "解释 30 分是 0.5 小时。"]),
        (["追及", "相遇"], "甲每分钟80米，乙每分钟60米，甲在乙后面100米同向追乙。为什么不能用 100÷(80+60)？请画出或描述距离差如何变化并求时间。", "同向追及距离差每分钟减少80-60=20米，所以100÷20=5分钟；80+60用于相向靠近。", ["判断同向还是相向。", "说明距离差变化率。", "用差速求时间。"]),
        (["正数", "负数"], "同样是 -3，一个表示海拔 -3 米，一个表示账户支出 3 元。请分别说明负号相对的基准或方向，并判断“负数一定表示少”这句话是否准确。", "海拔 -3 米相对海平面低3米；支出3元相对收入方向相反。负数表示相反意义或低于基准，不总是简单的“少”。", ["找基准或正方向。", "解释负号的实际意义。", "判断泛化说法是否过度。"]),
        (["数轴"], "有人说 -3 比 -1.5 大，因为 3 比 1.5 大。请用数轴解释这句话错在哪里，并把 -3、0、2、-1.5 从小到大排列。", "错在负数大小要看数轴位置，越往右越大；-3 在 -1.5 左边，所以 -3<-1.5<0<2。", ["把数放到数轴左右位置。", "说明负号改变方向。", "按从左到右排序。"]),
        (["绝对值"], "判断：|-3|=3，所以 -3 和 3 一样大。这个说法哪里不严谨？请说明绝对值表示什么，并比较 -3 与 3。", "绝对值相等只说明到0距离相等，不说明数值相等；-3<3。", ["把绝对值解释为距离。", "区分距离和数值大小。", "用数轴比较原数。"]),
        (["相反数"], "写出 -7、0、2.5 的相反数，并解释为什么 0 的相反数还是 0。再判断 -(-7) 与 -7 是否相同。", "-7的相反数是7，0的相反数是0，2.5的相反数是-2.5；0到0距离为0且方向不变。-(-7)=7，与-7不同。", ["用和为0或数轴对称理解相反数。", "单独处理0。", "区分原数和相反数。"]),
        (["有理数加减"], "计算 -7 + 12，并解释为什么结果取正号。再把题目改成 -12 + 7，说明哪一步改变了。", "-7+12=5，异号相加用较大绝对值减较小绝对值，取绝对值较大的12的正号；-12+7=-5，符号改为负。", ["比较绝对值大小。", "先定符号再算差。", "迁移到反向例子。"]),
        (["有理数乘除"], "计算 (-6) × 4 ÷ (-3)。请先不算数值，只判断符号；再计算，并说明如果再乘一个 -2 符号会怎样变。", "原式有两个负因数，结果为正，数值 6×4÷3=8；再乘 -2 后负因数个数变奇数，结果为负。", ["先数负号个数或逐步判断符号。", "再算绝对值。", "说明增加负因数后的变化。"]),
        (["混合运算"], "判断错解：2 - (-3) × 4 = 5 × 4 = 20。请指出错因，写出正确运算顺序和结果。", "错在先做了 2-(-3)，没有先算乘法。正确：(-3)×4=-12，2-(-12)=14。", ["先识别乘法优先。", "处理减负数。", "指出错解违反运算顺序。"]),
        (["乘方"], "比较 -2² 和 (-2)² 的值，并说明底数是谁。", "-2²=-4，(-2)²=4。", ["没有括号时底数是 2。", "有括号时底数是 -2。", "先乘方再看前置负号。"]),
        (["科学记数法", "近似数"], "把 3500000 写成科学记数法。有人写成 35×10^5，请判断它数值是否对、格式是否合格，并说明标准格式要求。", "35×10^5 数值等于3500000，但不是标准科学记数法；标准应为 3.5×10^6，前面的数大于等于1且小于10。", ["先判断数值。", "再检查标准格式。", "说明指数来自小数点移动位数。"]),
        (["同类项"], "判断 3a、-5a、2a²、7b、a 中哪些是同类项。请说明为什么 3a 和 2a² 不是同类项，系数不同是否影响同类项。", "3a、-5a、a 是同类项；3a 与 2a² 的字母指数不同，不是同类项；系数不同不影响。", ["看字母是否相同。", "看指数是否相同。", "说明系数只参与合并。"]),
        (["去括号"], "化简 4a - 2b - (a - 5b) + 3。", "3a + 3b + 3。", ["括号前是负号，括号内各项变号。", "合并 a 项。", "合并 b 项。"]),
        (["整式加减", "合并"], "合并同类项：2x + 3y - 5x + y。请说明为什么 x 项和 y 项不能合并，并写出合并后的式子。", "-3x+4y；x项和y项字母不同，不是同类项，不能合并。", ["按字母部分分组。", "只合并同类项系数。", "字母部分保持不变。"]),
        (["单项式"], "指出 -3a²b 的系数和次数。有人说次数是2，因为只看到 a²。请判断并解释。", "系数是 -3，次数是 3；次数要把所有字母指数相加，a 的指数2加 b 的指数1。", ["识别数字因数。", "补出 b 的指数 1。", "所有字母指数求和。"]),
        (["多项式"], "指出 2x² - 3x + 1 是几项式、次数是多少。请解释为什么常数项不决定多项式次数。", "三项式，次数2；次数看最高次项 2x²，常数项次数为0，不决定最高次数。", ["分清项。", "找最高次项。", "说明常数项的次数意义。"]),
        (["分母方程"], "解方程 x/2 + 1 = 4。有人第一步只把 x/2 乘2，写成 x+1=4。请判断是否保持等式平衡，并给出正确做法。", "不保持平衡。可先两边减1得 x/2=3，再两边乘2得 x=6；也可整式两边同乘2得 x+2=8，再解得 x=6。", ["判断是否对整边同做运算。", "选择一种等价变形。", "检验 x=6。"]),
        (["应用题", "一元一次方程"], "一个数的3倍加5等于20。请设未知数列方程求解，再把“加5”改成“减5”，说明方程结构如何变化。", "设这个数为x，3x+5=20，x=5；若改成减5，则方程为3x-5=20，常数项符号改变。", ["设未知数。", "把文字关系翻译成方程。", "说明情境改变时结构哪一部分改变。"]),
        (["角"], "一个角是35°。某同学把它的补角写成55°，请判断他混淆了什么概念，并写出余角和补角分别是多少。", "55°是余角，因为余角和为90°；补角是145°，因为补角和为180°。", ["区分余角和补角的总和。", "分别计算。", "指出错因。"]),
        (["直线", "射线", "线段"], "同一张图上有直线 AB、射线 AB、线段 AB 三种说法。请从端点、延伸方向、能否度量长度三个角度辨析。", "直线无端点向两方无限延伸不可度量；射线一个端点向一方无限延伸不可度量；线段两个端点可度量。", ["看端点数。", "看延伸方向。", "看是否可测量长度。"]),
        (["线段"], "AB=12cm，C 在 AB 上。只知道 AC=6cm，能否直接判断 C 是中点？如果可以，需要补充或验证什么条件？", "若 C 在 AB 上且 AC=CB=6cm，则 C 是中点；只给 AC=6cm 时还需验证 CB 也为6cm或说明 C 在 AB 上且 AB=12cm 时 CB=12-6=6。", ["确认点在线段上。", "计算或验证两段相等。", "用中点定义判断。"]),
        (["面积", "体积"], "长方体长4cm、宽3cm、高2cm。有人把 4×3 当成答案。请判断他求的是哪个量，若题目问体积应怎样改正并写单位。", "4×3=12cm² 是底面积；体积应为 4×3×2=24cm³。", ["区分面积和体积模型。", "体积需要三个维度。", "单位随维度变化。"]),
        (["单位"], "一个正方形边长从 1 米改写成 10 分米。有人说面积只扩大 10 倍。请判断错因，并说明长度单位和面积单位换算为什么不同。", "错在面积包含两个方向的长度；边长扩大10倍，面积单位换算要平方化，1平方米=100平方分米。", ["区分长度一维和面积二维。", "说明进率平方化。", "用正方形边长模型验证。"]),
        (["钟表"], "3点30分时，有人仍按3点整算成90°。请判断错因，并说明时针为什么也会移动。", "错在忽略时针30分钟内也移动；3点30分分针在6，时针在3和4之间，较小夹角是75°。", ["确定分针位置。", "计算时针半小时移动15°。", "取较小夹角。"]),
        (["工程"], "甲单独6天完成，乙单独3天完成。有人算合作时间为 (6+3)÷2。请判断模型错在哪里，并用“工作总量=1”求合作每天完成几分之几。", "错在不能平均完成天数；应把总工作量看作1，甲效率1/6，乙效率1/3，合作每天完成1/2。", ["把总工作量设为1。", "把天数转成效率。", "效率相加而不是天数平均。"]),
    ]
    for patterns, prompt, answer, steps in examples:
        if any(pattern in text for pattern in patterns):
            if offset != 1:
                generated = _generated_diagnostic_example_for(node, question_type, kind, offset)
                return {
                    "prompt": _level_prompt(generated["prompt"], level, offset),
                    "answer": generated["answer"],
                    "steps": generated["steps"],
                    "identity": generated["identity"],
                }
            leveled_prompt = _level_prompt(prompt, level, offset)
            return {
                "prompt": leveled_prompt,
                "answer": answer,
                "steps": steps,
                "identity": _fallback_question_identity(
                    node,
                    question_type,
                    kind,
                    prompt=leveled_prompt,
                    answer=answer,
                    offset=offset,
                    problem_instance_problem=prompt,
                ),
            }
    if offset != 1:
        generated = _generated_diagnostic_example_for(node, question_type, kind, offset)
        return {
            "prompt": _level_prompt(generated["prompt"], level, offset),
            "answer": generated["answer"],
            "steps": generated["steps"],
            "identity": generated["identity"],
        }
    essence = node.get("teaching_contract", {}).get("one_sentence_essence") or node.get("essence_for_child") or node.get("name")
    prompt = f"先写出“{node.get('name')}”的关键规则或关系，再判断一个常见错法错在哪里，并给出检验或反例。"
    answer = f"应体现：{essence}；同时能指出错法、写出关键关系，并用检验或反例确认。"
    leveled_prompt = _level_prompt(prompt, level, offset)
    return {
        "prompt": leveled_prompt,
        "answer": answer,
        "steps": ["说出考点。", "写关键关系或规则。", "判断错解并给出检验或反例。"],
        "identity": _fallback_question_identity(
            node,
            question_type,
            kind,
            prompt=leveled_prompt,
            answer=answer,
            offset=offset,
        ),
    }


def _level_prompt(prompt: str, level: str, offset: int) -> str:
    if level == "L1":
        return "先看清题目要你判断什么，再作答：" + prompt
    if level == "L2":
        return prompt + " 请补一句理由，说明关键判断为什么成立。"
    if level == "L3":
        return prompt + " 写出你最有把握的一条判断依据。"
    if level == "L4":
        return prompt + " 换一个相近条件，说明原来的哪条规则仍然不变。"
    return prompt


def _target_tags_for_blueprint(node: dict[str, Any], blueprint: dict[str, Any]) -> list[str]:
    node_tags = _error_tags(node)
    slot_tags = [
        tag for tag in blueprint.get("target_tags", [])
        if tag in CANONICAL_ERROR_TAGS
    ]
    merged = list(dict.fromkeys([*slot_tags, *node_tags]))
    return merged[:3] or ["general"]


def _compose_prompt(example_prompt: str, blueprint: dict[str, Any]) -> str:
    return str(example_prompt).strip()


def _bind_prompt_to_focus(prompt: str, node: dict[str, Any], question_type: str) -> str:
    node_name = str(node.get("name") or "").strip()
    if not node_name:
        return prompt
    focus = f"本题重点：{node_name}。"
    if focus in prompt:
        return prompt
    return f"{prompt} {focus}".strip()


def _solution_steps_for_blueprint(example_steps: list[str], blueprint: dict[str, Any]) -> list[str]:
    slot_steps = {
        "standard_example": ["先写关键规则或模型。"],
        "essence_check": ["先判断考点和本质。"],
        "misconception_probe": ["先指出易混概念。"],
        "error_spotting": ["定位错因并说明为什么错。"],
        "variant": ["比较本题与标准题的结构差异。"],
        "transfer_retest": ["判断情境改变后规则是否仍成立。"],
        "reverse_reasoning": ["从结论或条件反推关系。"],
        "missing_condition": ["列出必须确认的条件。"],
        "representation": ["把文字关系转成图示、式子或表格。"],
        "explanation_only": ["用清楚语言解释关键一步。"],
        "check_strategy": ["选择一种检验方法。"],
        "estimation_modeling": ["先估算或判断模型。"],
        "prerequisite_probe": ["写出前置规则。"],
        "stretch_transfer": ["说明多出的思考点。"],
        "two_method_compare": ["比较两种方法的适用条件。"],
        "boundary_case": ["用边界情况或反例检查规则。"],
        "symbol_unit_audit": ["审查符号、单位、括号或维度。"],
        "self_correction": ["预测并检查一个可能错法。"],
        "model_selection": ["先选择模型并排除相似错法。"],
        "communication": ["写完整关系、步骤和答句。"],
    }
    kind = str(blueprint.get("kind", ""))
    merged = [*slot_steps.get(kind, []), *example_steps]
    return list(dict.fromkeys(step for step in merged if str(step).strip()))[:6]


def _specific_example_for(node: dict[str, Any], question_type: str) -> dict[str, Any] | None:
    node_id = node.get("id", "")
    if node_id == "M-BRIDGE-CLOCK-ANGLE":
        return {
            "prompt": "3点30分时，有人按3点整算成90°。请判断错因，并求时针和分针的较小夹角。还要说明时针为什么也会移动。",
            "answer": "错在忽略时针30分钟内也移动。3点30分分针在6，时针在3和4之间，较小夹角是75°。",
            "steps": ["确定分针位置。", "计算时针半小时移动15°。", "取较小夹角。"],
        }

    if node_id == "M-G7-COMPARE":
        return {
            "prompt": "把 -3、-1.5、0、2/3 从小到大排列。有人说 -3 比 -1.5 大，因为 3 比 1.5 大。请用数轴或转成小数解释错在哪里。",
            "answer": "从小到大是 -3 < -1.5 < 0 < 2/3。错在负数大小不能只比较绝对值，数轴上越往右越大，-3 在 -1.5 左边。",
            "steps": ["先把数放到数轴或统一表示。", "说明负数比较看数轴位置。", "从左到右排序。"],
        }

    if node_id == "M-G7-MONOMIAL":
        return {
            "prompt": "指出 -3a²b 的系数和次数。有人说次数是2，因为只看到 a²。请判断并解释。",
            "answer": "系数是 -3，次数是 3；次数要把所有字母指数相加，a 的指数2加 b 的指数1。",
            "steps": ["识别数字因数和符号。", "补出 b 的指数 1。", "把所有字母指数相加。"],
        }

    if node_id == "M-G7-POLYNOMIAL":
        return {
            "prompt": "指出 2x² - 3x + 1 是几项式、次数是多少。请解释为什么常数项不决定多项式次数。",
            "answer": "三项式，次数2；次数看最高次项 2x²，常数项次数为0，不决定最高次数。",
            "steps": ["分清每一项。", "分别判断各项次数。", "取最高次项作为多项式次数。"],
        }

    if node_id == "M-G7-EXPR-VALUE":
        return {
            "prompt": "当 a=-2、b=3 时，求 2a²-b 的值。有人写成 2×(-2)×2-3，请指出错因并计算。",
            "answer": "a² 表示 (-2)²=4，不是 (-2)×2。2a²-b=2×4-3=5。",
            "steps": ["代入负数时给底数加括号。", "先算乘方。", "再完成乘法和减法。"],
        }

    if node_id == "M-G7-EQUATION-CONCEPT":
        return {
            "prompt": "判断 3x+5=20、2a+1、7-4=3 哪些是方程，哪些是一元一次方程，并说明“方程的解”是什么意思。",
            "answer": "3x+5=20 是一元一次方程；2a+1 不是方程，因为没有等号；7-4=3 是等式但不是方程，因为没有未知数。方程的解是使方程左右两边相等的未知数的值。",
            "steps": ["先判断是否有等号和未知数。", "再判断未知数个数和次数。", "用代入使左右相等解释方程的解。"],
        }

    if node_id == "M-PRE-UNIT-CONVERSION":
        if "时间" in question_type:
            return {
                "prompt": "有人把 2 小时 30 分写成 2.30 小时。请判断错因，把它改成小时，并说明为什么 30 分不是 0.30 小时。",
                "answer": "错在把六十进制的分钟当成十进制小数。30分是半小时，即0.5小时，所以2小时30分=2.5小时。",
                "steps": ["先说明小时和分钟的进率是60。", "把30分转成30/60小时。", "解释2.30小时表示2小时18分。"],
            }
        if "人民币" in question_type:
            return {
                "prompt": "判断：12 元 5 角可以写成 12.5 元，12 元 5 分也可以写成 12.5 元。请指出哪一句错，并说明小数位分别表示什么单位。",
                "answer": "第二句错。元的小数第一位表示角，第二位表示分；12元5角=12.5元，12元5分=12.05元。",
                "steps": ["先确定元、角、分的进率。", "说明十分位是角、百分位是分。", "区分12.5和12.05。"],
            }
        return {
            "prompt": "一个正方形边长从 1 米改写成 10 分米。有人说面积只扩大 10 倍。请判断错因，并说明长度单位和面积单位换算为什么不同。",
            "answer": "错在面积包含两个方向的长度；边长扩大10倍，面积单位换算要平方化，1平方米=100平方分米。",
            "steps": ["区分长度一维和面积二维。", "说明进率平方化。", "用正方形边长模型验证。"],
        }

    if node_id == "M-PRE-DISTRIBUTIVE":
        if "乘法分配律" in question_type:
            return {
                "prompt": "比较两种做法：25×(40+4) 和 25×40+25×4 是否等价？请说明分配律中每一项对应什么，并计算结果。",
                "answer": "等价。25要同时乘括号里的40和4，所以 25×(40+4)=25×40+25×4=1000+100=1100。",
                "steps": ["先指出括号外的25要分配给括号内每一项。", "写出等价展开式。", "计算并说明两种写法结果一致。"],
            }
        if "凑整" in question_type:
            return {
                "prompt": "不直接展开计算，比较 2026×2024 和 2025² 的大小，并求两者相差多少。请说明为什么不能只看 2026 比 2025 大。",
                "answer": "2026×2024=(2025+1)(2025-1)=2025²-1，所以比2025²小1。不能只看一个因数，因为另一个因数同时变小。",
                "steps": ["把两个因数改写成同一个基准数加减1。", "使用(a+1)(a-1)=a²-1。", "说明单独比较一个因数会误判。"],
            }
        return {
            "prompt": "下面这段化简错在哪里？4a - 2b - (a - 5b) + 3 = 3a - 7b + 3。请说明括号前负号怎样作用到括号内每一项，写出正确过程，并用 a=2、b=1 代入检验。",
            "answer": "错在括号前是负号，去括号时 -5b 应变成 +5b。正确：4a-2b-a+5b+3=3a+3b+3。代入 a=2,b=1，原式=12，化简式=12。",
            "steps": ["先把括号前负号看成乘以-1。", "括号内每一项都变号。", "合并同类项后代入检验。"],
        }

    if node_id == "M-G7-PARENTHESIS":
        if "正号" in question_type:
            return {
                "prompt": "比较 a+(2b-3) 和 a+2b-3 是否等价。请说明括号前是正号时括号内每一项发生什么变化，并用 a=1、b=4 代入检验。",
                "answer": "等价。括号前是正号，去括号后各项符号不变，所以 a+(2b-3)=a+2b-3。代入 a=1,b=4，两式都等于6。",
                "steps": ["先判断括号前是正号。", "说明括号内各项符号不变。", "代入同一组数检验两式等价。"],
            }
        if "负号" in question_type:
            return {
                "prompt": "下面这段去括号错在哪里？4a - 2b - (a - 5b) + 3 = 3a - 7b + 3。请说明负号怎样作用到括号内每一项，并写出正确过程。",
                "answer": "错在括号前是负号，去括号时 a 变成 -a，-5b 变成 +5b。正确：4a-2b-a+5b+3=3a+3b+3。",
                "steps": ["把括号前负号看成乘以-1。", "括号内每一项都变号。", "合并同类项。"],
            }
        if "系数" in question_type:
            return {
                "prompt": "判断：3(x-2)+x 可以直接写成 3x-2+x 吗？请指出错在哪里，写出正确去括号过程，并说明 3 要乘到哪些项。",
                "answer": "不可以。3 要同时乘 x 和 -2，正确是 3x-6+x=4x-6。",
                "steps": ["识别括号前系数3。", "把3分配到括号内每一项。", "合并同类项并指出错法少乘了-2。"],
            }
        return {
            "prompt": "化简 2[x-(3-y)] 时，有人只去掉外层括号。请指出错法，写出正确过程，并用一组 x、y 的值代入检验。",
            "answer": "内层括号前是负号，x-(3-y)=x-3+y，所以 2[x-(3-y)]=2(x-3+y)=2x-6+2y。只去外层会漏掉内层变号。",
            "steps": ["先处理内层负号。", "再把外层系数2分配到每一项。", "代入同一组数检验等价。"],
        }

    if node_id == "M-BRIDGE-SOLUTION-HABIT":
        if "读题" in question_type or "看不懂" in question_type or "无法启动" in question_type:
            return {
                "prompt": "小林解应用题只写了 x=12。题目是：七年级兴趣小组共有30人，男生比女生多6人。请先说明 x 表示谁，再补出方程、求解、检验和完整答句。",
                "answer": "应设女生 x 人，男生 x+6 人；x+(x+6)=30，2x=24，x=12，所以女生12人、男生18人。检验：12+18=30，18比12多6。只写 x=12 不完整，因为没有说明未知数含义、男生人数和检验。",
                "steps": ["先说明未知数的实际含义。", "列出总人数等量关系并求解。", "同时检验总人数和多6人两个条件，写完整答句。"],
            }
        if "计算过程改错" in question_type:
            return {
                "prompt": "下面这段化简错在哪里？4a - 2b - (a - 5b) + 3 = 3a - 7b + 3。请指出错因，写出正确过程，并用 a=2、b=1 代入检验。",
                "answer": "错在括号前是负号，去括号时 -5b 应变成 +5b。正确：4a-2b-a+5b+3=3a+3b+3。代入 a=2,b=1，原式=12，化简式=12。",
                "steps": ["先定位括号前负号。", "去括号后合并同类项。", "用给定数值代入原式和化简式检验。"],
            }
        if "方程代回检验" in question_type:
            return {
                "prompt": "解方程 -2(x - 3) + 5 = 17。要求写出去括号、移项/等式变形，并代回原方程检验。",
                "answer": "去括号得 -2x+6+5=17，即 -2x+11=17，-2x=6，x=-3。检验：-2(-3-3)+5=12+5=17。",
                "steps": ["先正确去括号。", "保持等式平衡求 x。", "代回原方程，而不是只代回中间式。"],
            }
        if "应用题设列解答规范" in question_type:
            return {
                "prompt": "七年级兴趣小组共有 30 人，男生比女生多 6 人。请按“设未知数、列方程、求解、检验、答句”写完整，并解释 x+6 表示什么。",
                "answer": "设女生 x 人，男生 x+6 人，x+(x+6)=30，2x=24，x=12，男生18人。检验：12+18=30，18比12多6。x+6 表示男生人数。",
                "steps": ["设较小或未知的一类为 x。", "把另一类表示成 x+6。", "用总人数列方程并检验两个条件。"],
            }
        if "单位与答句检查" in question_type:
            return {
                "prompt": "某同学解应用题只写了 x=12。已知他设的是女生人数，方程是 x+(x+6)=30。请补齐检验和答句，并说明如果只写 x=12 为什么不完整。",
                "answer": "检验：12+(12+6)=30，18比12多6。答：女生12人，男生18人。只写 x=12 没说明 x 的含义，也没有回答男生人数和检验条件。",
                "steps": ["说明 x 的实际含义。", "同时检验总人数和多6人。", "答句回答题目全部问题。"],
            }

    if node_id == "M-BRIDGE-WORD-PROBLEM-READING":
        return {
            "prompt": "小林买 3 支笔和 2 本本子共 28 元，本子单价比笔贵 5 元。请先圈出已知量和未知量，再设笔的单价为 x，列方程，并解释 2(x+5) 表示什么。",
            "answer": "已知：3支笔、2本本子、共28元、本子比笔贵5元；未知：笔和本子的单价。设笔 x 元，本子 x+5 元，方程 3x+2(x+5)=28。2(x+5) 表示2本本子的总价。",
            "steps": ["先列出已知和未知。", "用 x 表示笔价，用 x+5 表示本子价。", "按总价关系列方程并解释每一项。"],
        }

    if node_id == "M-G7-POS-NEG":
        return {
            "prompt": "规定向东为正。小车先向西 4 米，再向东 7 米；同一张图上还有一个点表示海拔 -3 米。请分别写出小车两次运动的正负数，求小车最后相对起点的位置，并说明 -3 米的负号表示什么。",
            "answer": "向西4米记为 -4，向东7米记为 +7，最后位置 -4+7=+3 米，即起点东边3米。海拔 -3 米表示低于基准海平面3米。",
            "steps": ["先明确正方向或基准。", "把相反意义的量写成正负数。", "计算净变化并解释负号含义。"],
        }

    if node_id == "M-G7-NUMBER-LINE":
        return {
            "prompt": "数轴上 A=-2.5，B=1。点 C 在 A 的右边，且 AC=3。求 C 表示的数，并把 A、B、C 从小到大排列，说明依据。",
            "answer": "C=-2.5+3=0.5。从小到大：A(-2.5) < C(0.5) < B(1)。依据是数轴上越往右越大。",
            "steps": ["从 A 向右移动 3 个单位求 C。", "把三个点放回数轴位置。", "按从左到右排序。"],
        }

    if node_id == "M-G7-ABSOLUTE":
        return {
            "prompt": "已知 |x|=3。x 可能是多少？再判断 |-3| 和 -|3| 是否相等，并说明绝对值和前置负号的区别。",
            "answer": "x 可能是 3 或 -3。|-3|=3，-|3|=-3，不相等。绝对值表示到0的距离，前置负号是在绝对值结果前取相反数。",
            "steps": ["先用距离理解 |x|=3。", "分别计算绝对值和前置负号。", "说明符号作用的先后区别。"],
        }

    if node_id == "M-G7-OPPOSITE":
        return {
            "prompt": "写出 -7、0、2.5 的相反数，并说明相反数在数轴上的位置关系。",
            "answer": "-7 的相反数是 7，0 的相反数是 0，2.5 的相反数是 -2.5；相反数到 0 距离相等、方向相反。",
            "steps": ["先看符号方向。", "0 的相反数仍是 0。", "用数轴距离和方向解释。"],
        }

    if node_id == "M-G7-RATIONAL-ADD-SUB":
        return {
            "prompt": "计算 -7 + 12 - (-5)，并用“数轴移动”或“减法转加法”解释每一步的符号来源。",
            "answer": "-7+12-(-5)=-7+12+5=10。减去 -5 等于加 5；也可理解为在数轴上先从 -7 向右12到5，再向右5到10。",
            "steps": ["先把减去负数转成加正数。", "按顺序计算。", "用数轴移动或规则解释符号。"],
        }

    if node_id == "M-BRIDGE-SUM-DIFF-MULTIPLE":
        if "年龄" in question_type:
            return {
                "prompt": "爸爸今年 40 岁，孩子今年 12 岁。几年后爸爸年龄是孩子的 3 倍？请设 x，并说明为什么两人的年龄差不变。",
                "answer": "设 x 年后，40+x=3(12+x)，解得 x=2。年龄差一直是28岁，不会随时间改变。",
                "steps": ["设 x 年后。", "把几年后的两个年龄都写出来。", "用倍数关系列方程，并说明年龄差不变。"],
            }
        if "差倍" in question_type:
            return {
                "prompt": "甲数比乙数多 18，甲数是乙数的 3 倍。请用份数模型或方程求甲、乙，并解释为什么不能直接用 18÷3。",
                "answer": "甲比乙多的是 3份-1份=2份，18对应2份，每份9，乙9，甲27。不能用18÷3，因为18不是甲的3份。",
                "steps": ["把乙看作1份，甲是3份。", "差18对应2份。", "求每份后回到甲乙，并解释错法。"],
            }
        return {
            "prompt": "两个数的和是 76，大数比小数的 2 倍少 5。请设小数为 x，列方程求两个数，并解释 2x-5 表示谁。",
            "answer": "设小数为x，大数为2x-5，x+(2x-5)=76，解得x=27，大数49。2x-5表示大数。",
            "steps": ["设小数为 x。", "把大数表示成 2x-5。", "用和是76列方程并回到两个数。"],
        }

    if node_id == "M-G7-RATIONAL-CLASSIFY":
        if "集合" in question_type:
            return {
                "prompt": "把 -3、0、2.5、-1/4、7 分别放入“正有理数、负有理数、整数、分数”这些集合；允许一个数进入多个集合，并说明 0 为什么单独处理。",
                "answer": "正有理数：2.5、7；负有理数：-3、-1/4；整数：-3、0、7；分数：2.5、-1/4。0既不是正数也不是负数，但它是整数、有理数。",
                "steps": ["先按正负零分类。", "再判断整数/分数属性。", "说明一个数可属于多个集合，0需单独处理。"],
            }
        return {
            "prompt": "判断下面说法是否正确：所有整数都是有理数，所有分数也是有理数，所以 0 既是正有理数也是负有理数。请改正不严谨的地方。",
            "answer": "前两句正确；0是有理数和整数，但0既不是正数也不是负数，所以不是正有理数或负有理数。",
            "steps": ["确认整数和分数都属于有理数。", "单独判断0的正负性。", "把分类语言改严谨。"],
        }

    if node_id == "M-G7-GEO-SOLID-PLANE":
        if "展开图" in question_type:
            return {
                "prompt": "一个正方体展开图由 6 个正方形连成一片。有人说只要有 6 个正方形就一定能折成正方体。请判断并说明还要检查什么。",
                "answer": "不一定。除了有6个正方形，还要检查连接方式，折起后不能重叠、不能缺面，每个面的位置关系要能围成立体。",
                "steps": ["先区分数量条件和连接条件。", "说明折叠后不能重叠或缺面。", "用面的位置关系判断。"],
            }
        if "方向" in question_type:
            return {
                "prompt": "一个长方体从正面看是长方形，从上面看也是长方形。能否只凭一个方向的图判断它是长方体？请说明至少还需要看什么。",
                "answer": "不能。一个方向只给平面投影，可能丢失深度信息；至少还要结合上面/左面等不同方向视图或立体特征。",
                "steps": ["说明单一视图会丢失信息。", "指出需要多个方向。", "区分平面图和立体图形。"],
            }
        return {
            "prompt": "判断：长方形、圆柱、正方体、三角形中哪些是平面图形，哪些是立体图形；请用“是否有厚度/体积”说明理由。",
            "answer": "平面图形：长方形、三角形；立体图形：圆柱、正方体。立体图形有三维空间和体积，平面图形没有厚度。",
            "steps": ["按是否占有空间分类。", "列出平面图形。", "列出立体图形并说明依据。"],
        }

    if node_id == "M-G7-POINT-LINE-PLANE":
        if "线动成面" in question_type:
            return {
                "prompt": "把一条线段沿垂直方向平移，会扫出什么图形？请再举一个“线动成面”的例子，并说明这个例子里移动的是谁。",
                "answer": "会扫出一个长方形。例子如直线绕一点旋转可扫出平面区域；移动对象是一条线。",
                "steps": ["识别运动对象是线。", "判断运动轨迹形成面。", "举例并说明对象和结果。"],
            }
        if "面动成体" in question_type:
            return {
                "prompt": "一个长方形绕它的一条边旋转一周，会形成什么立体？请说明“面动成体”里原来的面和形成的体分别是什么。",
                "answer": "会形成圆柱。原来的面是长方形，运动后扫过空间形成圆柱这个立体。",
                "steps": ["识别运动对象是面。", "判断旋转形成的空间体。", "说清原面和结果体。"],
            }
        if "元素关系" in question_type:
            return {
                "prompt": "用一句话分别说明点、线、面、体之间的关系，并判断“线只有长度没有宽度和厚度”这句话是否符合几何抽象。",
                "answer": "点动成线，线动成面，面动成体；几何中的线只考虑长度，不考虑宽度和厚度，这符合抽象模型。",
                "steps": ["写出点线面体的生成关系。", "区分现实物体和几何抽象。", "判断说法是否成立。"],
            }
        return {
            "prompt": "一个点沿直线运动，会留下什么图形？请说明点和线的区别，并举一个生活中接近“点动成线”的例子。",
            "answer": "会留下线。点表示位置，线表示点运动形成的轨迹；例子如笔尖移动留下线迹。",
            "steps": ["识别运动对象是点。", "说明轨迹是线。", "举例并区分点和线。"],
        }

    if node_id == "M-G7-GEO-VIEWS":
        if "正方体展开图" in question_type:
            return {
                "prompt": "判断一个正方体展开图时，为什么不能只数有 6 个正方形？请写出两个还必须检查的条件。",
                "answer": "还要检查正方形的连接方式是否能折起、折起后是否有面重叠或缺面；只有数量够不保证能围成立方体。",
                "steps": ["先确认6个面只是必要条件。", "检查连接方式。", "检查折叠后是否重叠或缺面。"],
            }
        if "小正方体" in question_type:
            return {
                "prompt": "一个立体由 4 个同样小正方体组成：底层 3 个排成一行，最左边小正方体上面再放 1 个。从正面看有几列、高度分别是多少？请说明你看的方向。",
                "answer": "从正面看有3列，高度从左到右分别为2、1、1。方向固定后，重叠的深度不再显示，只看每列最高高度。",
                "steps": ["明确从正面看。", "按列统计最高高度。", "说明视图会压缩深度。"],
            }
        return {
            "prompt": "同一个长方体从正面、左面、上面看到的图形可能不同。请说明三个方向各自丢失了哪一个维度的信息。",
            "answer": "正面图保留长和高，丢失深；左面图保留深和高，丢失长；上面图保留长和深，丢失高。",
            "steps": ["先明确三维量：长、宽/深、高。", "逐个方向判断保留的两个维度。", "指出丢失的维度。"],
        }

    return None


def build_practice_bank(graph: dict[str, Any], *, graph_version: str = "") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node in graph["nodes"]:
        types = _seed_types(node)
        for index, blueprint in enumerate(QUESTION_BLUEPRINTS, start=1):
            kind = str(blueprint["kind"])
            level = str(blueprint["level"])
            label = str(blueprint["label"])
            question_type = types[(index - 1) % len(types)]
            example = _example_for(node, question_type, level, index, kind)
            item_id = f"{QUESTION_ID_PREFIX}-{_safe_id(node['id'])}-{index:02d}"
            prompt = _bind_prompt_to_focus(_compose_prompt(example["prompt"], blueprint), node, question_type)
            solution_steps = _solution_steps_for_blueprint(example["steps"], blueprint)
            item = {
                "id": item_id,
                "item_version": QUESTION_BANK_VERSION,
                "source_type": "graph_generated",
                "node_id": node["id"],
                "secondary_node_ids": [],
                "node_snapshot": {
                    "id": node["id"],
                    "name": node.get("name", ""),
                    "stage": node.get("stage", ""),
                    "domain": node.get("domain", ""),
                    "priority": node.get("priority", ""),
                    "summer_mode": _node_mode(node),
                },
                "kind": kind,
                "question_type": f"{label}：{question_type}",
                "variant_level": level,
                "prompt": prompt,
                "answer_format": str(blueprint.get("answer_format") or "关键步骤 + 答案 + 一句话解释"),
                "expected_answer": example["answer"],
                "rubric": BASE_RUBRIC,
                "solution_steps": solution_steps,
                "target_error_tags": _target_tags_for_blueprint(node, blueprint),
                "rollback_candidates": _rollback_candidates(node),
                "rollback_candidate_relations": _rollback_relations(node),
                "estimated_minutes": 5 if level in {"L3", "L4"} else 4,
                "parent_observation": node.get("teaching_contract", {}).get("parent_prompt", "先问孩子这题考什么，再看步骤。"),
                "source": {
                    "type": "graph_generated",
                    "note": "Original graph-bound practice item generated from the project knowledge graph; not copied from private textbook or question bank.",
                    "curated_manifest_id": GRAPH_SEED_REVIEW_MANIFEST_ID,
                    "curated_manifest_version": QUESTION_BANK_VERSION,
                    "blueprint_slot": index,
                    "blueprint_kind": kind,
                    "blueprint_label": label,
                    **(example.get("identity") or {}),
                },
            }
            items.append(_apply_question_production_contract(
                item,
                node,
                question_type=question_type,
                graph_version=graph_version,
                question_bank_version=QUESTION_BANK_VERSION,
            ))
            item["prompt"] = _bind_prompt_to_focus(item["prompt"], node, question_type)
            _attach_question_identity_contract(item, node, question_type)
            apply_question_lineage(
                item,
                graph_version=graph_version,
                question_bank_version=QUESTION_BANK_VERSION,
            )
            item["source"]["reviewer_evidence"] = curated_seed_reviewer_evidence(item)
            item["design_intent"]["problem_family_id"] = item["problem_family_id"]
            item["design_intent"]["core_stem_id"] = item["core_stem_id"]
            item["design_intent"]["problem_instance_id"] = item["problem_instance_id"]
            item["design_intent"]["node_alignment"] = item["node_alignment"]
            item["design_intent"]["evidence_claims"]["problem_family_id"] = item["problem_family_id"]
            item["design_intent"]["evidence_claims"]["core_stem_id"] = item["core_stem_id"]
            item["design_intent"]["evidence_claims"]["problem_instance_id"] = item["problem_instance_id"]
            item["design_intent"]["evidence_claims"]["node_alignment_reason"] = item["node_alignment"]["reason"]
            item["design_intent"]["graph_version"] = item.get("graph_version", "")
            item["design_intent"]["question_bank_version"] = item.get("question_bank_version", QUESTION_BANK_VERSION)
            item["design_intent"]["evidence_claims"]["graph_version"] = item.get("graph_version", "")
            item["design_intent"]["evidence_claims"]["question_bank_version"] = item.get("question_bank_version", QUESTION_BANK_VERSION)
            quality = review_item_quality(item)
            item["quality"] = quality
            apply_question_lineage(
                item,
                graph_version=graph_version,
                question_bank_version=QUESTION_BANK_VERSION,
            )
            item["cognitive_level"] = quality["cognitive_level"]
            item["item_purpose"] = quality["item_purpose"]
            item["requires_reasoning"] = quality["requires_reasoning"]
            item["challenge_profile"] = {
                "picture_level": bool(quality["picture_level_challenge_labels"]),
                "labels": quality["picture_level_challenge_labels"],
            }
            item["review_agent_check"] = {
                "reviewer_agent": QUESTION_REVIEWER_AGENT_KEY,
                "status": quality["review_status"],
                "rejection_reasons": quality["rejection_reasons"],
            }
            item["usage_policy"] = question_usage.policy_for_item(item)
            if quality["review_status"] != "approved":
                raise ValueError(f"Question item {item.get('id')} rejected by focus-bound quality gate: {quality['rejection_reasons']}")
    validate_question_bank_collection(items)
    return items


def _is_cannot_start_attempt(attempt: dict[str, Any]) -> bool:
    return bool(attempt.get("blocking_evidence"))


def evolved_item_from_attempt(node: dict[str, Any], base_question: dict[str, Any], attempt: dict[str, Any], event_id: str) -> dict[str, Any]:
    error_tags = attempt.get("error_tags") or ["general"]
    error_tag = error_tags[0] if error_tags else "general"
    if _is_cannot_start_attempt(attempt) or error_tag == "modeling_or_reading":
        question_type = "读题拆解与无法启动修复"
    else:
        question_type = node.get("question_types", [node.get("name", "")])[0]
    example = _example_for(node, question_type, "L2", 1)
    prompt = example["prompt"]
    item = {
        "id": f"EV-{_safe_id(node['id'])}-{event_id[-8:]}",
        "item_version": EVOLVED_ITEM_VERSION,
        "source_type": "evolved",
        "node_id": node["id"],
        "secondary_node_ids": [],
        "node_snapshot": {
            "id": node["id"],
            "name": node.get("name", ""),
            "stage": node.get("stage", ""),
            "domain": node.get("domain", ""),
            "priority": node.get("priority", ""),
            "summer_mode": _node_mode(node),
        },
        "kind": "evidence_driven_retest",
        "question_type": f"真实错因回炉：{node.get('name')}",
        "variant_level": "L2",
        "prompt": prompt,
        "answer_format": "规则 + 关键步骤 + 答案 + 错因提醒",
        "expected_answer": example["answer"],
        "rubric": BASE_RUBRIC,
        "solution_steps": example["steps"] + ["最后对照上次错因做一次检查。"],
        "target_error_tags": [tag for tag in error_tags if tag in CANONICAL_ERROR_TAGS] or _error_tags(node),
        "rollback_candidates": _rollback_candidates(node),
        "rollback_candidate_relations": _rollback_relations(node),
        "estimated_minutes": 4,
        "parent_observation": "这是由真实错因生成的复测题，看同类错因是否消失。",
        "source": {
            "type": "evolved_from_attempt",
            "event_id": event_id,
            "base_question_id": base_question["id"],
            "attempt_id": attempt["id"],
            "evidence_status": attempt.get("evidence_status", "active"),
            "evidence_error_tag": error_tag,
            "evidence_summary": attempt.get("parent_note") or attempt.get("answer_raw") or "步骤/解释不稳",
            "evolution_strategy": "cannot_start_repair" if question_type == "读题拆解与无法启动修复" else "same_node_error_retest",
        },
    }
    return _apply_question_production_contract(item, node, question_type=item["question_type"])


def evolved_item_from_candidate(
    node: dict[str, Any],
    base_question: dict[str, Any],
    attempt: dict[str, Any],
    event_id: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    error_tags = [
        tag for tag in (candidate.get("target_error_tags") or attempt.get("error_tags") or ["general"])
        if tag in CANONICAL_ERROR_TAGS
    ] or _error_tags(node)
    prompt = str(candidate.get("prompt") or "").strip()
    expected_answer = str(candidate.get("expected_answer") or "").strip()
    solution_steps = [
        str(step).strip()
        for step in candidate.get("solution_steps", [])
        if str(step).strip()
    ]
    if not prompt or not expected_answer or len(solution_steps) < 2:
        raise ValueError("Model question candidate is incomplete")
    rollback_candidates = [
        node_id for node_id in (candidate.get("rollback_candidates") or _rollback_candidates(node))
        if isinstance(node_id, str)
    ]
    item = {
        "id": f"EV-{_safe_id(node['id'])}-{event_id[-8:]}",
        "item_version": EVOLVED_ITEM_VERSION,
        "source_type": "evolved",
        "node_id": node["id"],
        "secondary_node_ids": [
            node_id for node_id in candidate.get("secondary_node_ids", [])
            if isinstance(node_id, str)
        ],
        "node_snapshot": {
            "id": node["id"],
            "name": node.get("name", ""),
            "stage": node.get("stage", ""),
            "domain": node.get("domain", ""),
            "priority": node.get("priority", ""),
            "summer_mode": _node_mode(node),
        },
        "kind": "evidence_driven_retest",
        "question_type": str(candidate.get("question_type") or f"真实错因回炉：{node.get('name')}")[:120],
        "variant_level": str(candidate.get("variant_level") or "L2"),
        "prompt": prompt,
        "answer_format": str(candidate.get("answer_format") or "规则 + 关键步骤 + 答案 + 错因提醒"),
        "expected_answer": expected_answer,
        "rubric": candidate.get("rubric") if isinstance(candidate.get("rubric"), list) else BASE_RUBRIC,
        "solution_steps": solution_steps,
        "target_error_tags": error_tags,
        "rollback_candidates": rollback_candidates,
        "rollback_candidate_relations": [
            {"node_id": node_id, "relation": "prerequisite_chain"}
            for node_id in rollback_candidates
        ],
        "estimated_minutes": _safe_estimated_minutes(candidate.get("estimated_minutes", 5)),
        "parent_observation": "这是由答案分析证据生成的复测题，看同类错因是否修复。",
        "candidate_id": str(candidate.get("candidate_id") or f"QC-{event_id[-8:]}-{_safe_id(node['id'])}"),
        "source": {
            "type": "evolved_from_attempt",
            "event_id": event_id,
            "base_question_id": base_question["id"],
            "attempt_id": attempt["id"],
            "evidence_status": attempt.get("evidence_status", "active"),
            "evidence_error_tag": error_tags[0],
            "evidence_summary": attempt.get("parent_note") or attempt.get("answer_raw") or "步骤/解释不稳",
            "evolution_strategy": "model_designed_evidence_retest",
            "designer_agent": QUESTION_DESIGNER_AGENT_KEY,
            "candidate_reviewer_evidence": candidate.get("reviewer_evidence", {}),
            "model_confidence": candidate.get("confidence"),
            "candidate_rationale": candidate.get("design_rationale", ""),
        },
    }
    item["source"]["reviewer_evidence"] = deterministic_evolution_reviewer_evidence(item)
    return _apply_question_production_contract(item, node, question_type=item["question_type"])


def _safe_estimated_minutes(value: Any) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = 5
    return max(3, min(8, minutes))


def normalize_item_json(item: dict[str, Any]) -> dict[str, str]:
    return {
        "secondary_node_ids_json": json.dumps(item.get("secondary_node_ids", []), ensure_ascii=False),
        "rubric_json": json.dumps(item.get("rubric", BASE_RUBRIC), ensure_ascii=False),
        "solution_steps_json": json.dumps(item.get("solution_steps", []), ensure_ascii=False),
        "error_tags_json": json.dumps(item.get("target_error_tags", []), ensure_ascii=False),
        "rollback_candidate_node_ids_json": json.dumps(item.get("rollback_candidates", []), ensure_ascii=False),
        "rollback_candidate_relations_json": json.dumps(item.get("rollback_candidate_relations", []), ensure_ascii=False),
        "source_json": json.dumps(item.get("source", {}), ensure_ascii=False),
    }
