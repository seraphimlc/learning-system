from __future__ import annotations

import ast
import copy
import importlib.util
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system import graph_runtime, model_router, question_bank


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_GRAPH = json.loads(
    (PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json").read_text(
        encoding="utf-8"
    )
)
CURRENT_NODE_ID = "M-G7-POS-NEG"
CURRENT_GRAPH_VERSION = graph_runtime.GraphRuntimeService(
    project_root=PROJECT_ROOT
).current_graph_version()
HISTORICAL_V3_CHECKPOINT = (
    PROJECT_ROOT
    / "data/question_banks/math/.v12_checkpoints_20260712_process_pilot_v3/M-BRIDGE-SOLUTION-HABIT.json"
)


def _load_builder():
    path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
    spec = importlib.util.spec_from_file_location("build_math_question_bank_v12_v4_contract_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _require_callable(test: unittest.TestCase, owner, name: str):
    value = getattr(owner, name, None)
    test.assertTrue(
        callable(value),
        f"missing planned v4 contract symbol: {getattr(owner, '__name__', type(owner).__name__)}.{name}",
    )
    return value


def _voice_families() -> list[str]:
    return list(question_bank.V12_INSTRUCTION_VOICE_FAMILIES)


_VOICE_ASSIGNMENTS = {
    5: (
        "classify_and_justify", "represent_and_translate", "solve_and_interpret", "solve_and_interpret",
        "compare_and_choose", "diagnose_and_repair", "classify_and_justify", "compare_and_choose",
        "represent_and_translate", "compare_and_choose", "solve_and_interpret", "classify_and_justify",
        "classify_and_justify", "compare_and_choose", "compare_and_choose", "classify_and_justify",
        "classify_and_justify", "compare_and_choose", "solve_and_interpret", "compare_and_choose",
    ),
    6: (
        "classify_and_justify", "represent_and_translate", "estimate_and_predict", "solve_and_interpret",
        "compare_and_choose", "diagnose_and_repair", "classify_and_justify", "compare_and_choose",
        "estimate_and_predict", "compare_and_choose", "estimate_and_predict", "classify_and_justify",
        "classify_and_justify", "compare_and_choose", "compare_and_choose", "classify_and_justify",
        "classify_and_justify", "compare_and_choose", "estimate_and_predict", "compare_and_choose",
    ),
    8: (
        "classify_and_justify", "construct_or_complete", "estimate_and_predict", "solve_and_interpret",
        "compare_and_choose", "diagnose_and_repair", "reverse_reasoning", "represent_and_translate",
        "estimate_and_predict", "compare_and_choose", "estimate_and_predict", "classify_and_justify",
        "classify_and_justify", "compare_and_choose", "compare_and_choose", "classify_and_justify",
        "classify_and_justify", "compare_and_choose", "estimate_and_predict", "compare_and_choose",
    ),
}


def _graph_node() -> dict:
    return copy.deepcopy(
        next(node for node in AUTHORITATIVE_GRAPH["nodes"] if node["id"] == CURRENT_NODE_ID)
    )


def _interaction_schema(kind: str = "short_text") -> dict:
    base = {
        "schema_version": question_bank.QUESTION_INTERACTION_SCHEMA_VERSION,
        "type": kind,
        "title": "",
        "allow_explanation": True,
        "explanation_label": "补充说明",
        "fields": [],
        "choices": [],
        "formula_label": "",
        "placeholder": "",
    }
    if kind == "fill_blank":
        base["title"] = "补完整关键量"
        base["fields"] = [
            {"id": "first", "label": "第一步量", "placeholder": "", "prefix": "", "suffix": ""},
            {"id": "second", "label": "第二步量", "placeholder": "", "prefix": "", "suffix": ""},
        ]
    elif kind == "single_choice":
        base["title"] = "选择更合适的关系"
        base["choices"] = [
            {"id": "a", "label": "关系 A"},
            {"id": "b", "label": "关系 B"},
        ]
    elif kind == "formula_input":
        base["formula_label"] = "关键关系"
        base["placeholder"] = "写出等量关系或算式"
    return base


def _semantic_evidence(item: dict) -> dict:
    requires_unprompted = question_bank.v12_item_requires_unprompted_process_evidence(item)
    return {
        "version": question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "ux_verdict": "approved",
        "natural_self_contained_task": {"verdict": "pass", "score": 0.95, "reason": "complete task"},
        "natural_chinese": {"verdict": "pass", "score": 0.95, "reason": "natural child-facing language"},
        "rendered_notation_readiness": {
            "verdict": "pass",
            "score": 1.0,
            "reason": "render ready",
            "child_visible_risks": [],
        },
        "age_dignity": {"verdict": "pass", "score": 0.95, "reason": "incoming Grade-7 appropriate"},
        "instruction_voice_family": item["intended_instruction_voice_family"],
        "response_moves": ["solve", "state result"],
        "unprompted_process_evidence": {
            "applicability": "required" if requires_unprompted else "not_applicable",
            "verdict": "satisfied" if requires_unprompted else "not_applicable",
            "score": 0.95 if requires_unprompted else 1.0,
            "reason": "process evidence remains spontaneous" if requires_unprompted else "not a designated process slot",
        },
        "process_target_disclosed": False,
        "process_disclosure_evidence": {
            "verdict": "not_disclosed",
            "source_field": "none",
            "quote": "",
            "reason": "No process target is disclosed in the child-visible prompt.",
        },
        "evidence": "Recorded reviewer evidence over the child-visible prompt and review-only answer packet.",
        "repair_direction": "none",
    }


def _item(
    slot: int,
    *,
    voice: str | None = None,
    prompt: str | None = None,
    family_count: int | None = None,
) -> dict:
    if voice is not None:
        family = voice
    elif family_count is not None:
        family = _VOICE_ASSIGNMENTS[family_count][slot - 1]
    else:
        family = question_bank.v12_instruction_voice_plan(_graph_node())[slot]
    elicitation_mode = (
        question_bank.V12_UNPROMPTED_PROCESS_ELICITATION_MODE
        if slot in question_bank.V12_PROCESS_UNPROMPTED_SLOTS
        else "direct_prompted_evidence"
    )
    item = {
        "id": f"QB12-{CURRENT_NODE_ID}-{slot:02d}",
        "slot": slot,
        "slot_role": question_bank.v12_slot_role_for_node(_graph_node(), slot),
        "node_id": CURRENT_NODE_ID,
        "kind": question_bank.v12_slot_role_for_node(_graph_node(), slot),
        "question_type": question_bank.v12_slot_role_for_node(_graph_node(), slot),
        "variant_level": "L2",
        "prompt": prompt or f"Child prompt {slot}: determine the signed change and state the result.",
        "interaction_schema": _interaction_schema(),
        "answer_format": "HIDDEN review instruction: show relation, steps, unit, and final check.",
        "expected_answer": f"HIDDEN expected answer {slot}",
        "accepted_alternatives": [f"HIDDEN alternative {slot}"],
        "solution_steps": [
            "HIDDEN solution relation.",
            "HIDDEN calculation and check.",
        ],
        "target_error_tags": ["process_habit"],
        "rollback_candidates": [],
        "problem_family_id": f"PF-V4-{slot:02d}",
        "core_stem_id": f"CS-V4-{slot:02d}",
        "math_core_signature": f"CORE-V4-{slot:02d}",
        "evidence_goal": f"Collect diagnostic evidence for slot {slot} without coaching the target habit.",
        "elicitation_mode": elicitation_mode,
        "child_surface_design": copy.deepcopy(question_bank.V12_CHILD_SURFACE_DESIGN),
        "intended_instruction_voice_family": family,
        "difficulty_vector": {
            "concept_demand": 2,
            "reasoning_steps": 2,
            "calculation_load": 1,
            "representation_demand": 1,
            "transfer_distance": 1,
        },
        "requires_reasoning": True,
        "node_local_mainline": True,
        "controlled_stretch": False,
        "estimated_minutes": 4,
    }
    review = {
        "verdict": "approved",
        "scores": {key: 0.95 for key in question_bank.V12_REVIEW_SCORE_KEYS},
        "semantic_evidence_version": question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "semantic_evidence": _semantic_evidence(item),
        "confidence": 0.95,
    }
    review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(item, review)
    item["review_artifact"] = review
    return item


def _node_entry(*, family_count: int | None = None) -> dict:
    return {
        "node_id": CURRENT_NODE_ID,
        "node_name": "V4 contract node",
        "items": [_item(slot, family_count=family_count) for slot in range(1, 21)],
    }


def _process_disclosure_evidence(*, disclosed: bool, quote: str = "") -> dict:
    return {
        "process_target_disclosed": disclosed,
        "process_disclosure_evidence": {
            "verdict": "disclosed" if disclosed else "not_disclosed",
            "source_field": "child_visible.prompt" if disclosed else "none",
            "quote": quote if disclosed else "",
            "reason": "Recorded semantic judgment over the exact child-visible prompt.",
        },
    }


def _scored(*, verdict: str = "pass", score: float = 0.95, reason: str = "approved") -> dict:
    return {"verdict": verdict, "score": score, "reason": reason}


def _item_by_slot(node_entry: dict, slot: int) -> dict:
    return next(item for item in node_entry["items"] if int(item["slot"]) == slot)


def _repair_directive(
    node_entry: dict,
    slot: int,
    *,
    scope: str = "focal_math_or_context",
    family: str | None = None,
    dimension: str = "context_semantics",
    from_value: str = "ambiguous_context",
    to_value: str = "unambiguous_context",
    replace_math_core: bool = False,
) -> dict:
    item = _item_by_slot(node_entry, slot)
    current_voice = item["review_artifact"]["semantic_evidence"]["instruction_voice_family"]
    required_voice = family or current_voice
    if dimension == "instruction_voice_family":
        from_value = current_voice
        to_value = required_voice
    return {
        "slot": slot,
        "repair_scope": scope,
        "preserved_role": item["slot_role"],
        "preserve_or_replace_math_core": "replace_math_core" if replace_math_core else "preserve_math_core",
        "required_voice_family": required_voice,
        "avoided_voice_families": [current_voice] if required_voice != current_voice else [],
        "exact_target_delta": {
            "dimension": dimension,
            "from_value": from_value,
            "to_value": to_value,
        },
        "evidence_refs": [f"review:slot:{slot}"],
    }


def _local_shard_output(
    node_entry: dict,
    focal_slots: list[int],
    *,
    verdict: str = "approved",
    rejected_slots: list[int] | None = None,
    repair_instructions: list[dict] | None = None,
    duplicate_suspicions: list[dict] | None = None,
) -> dict:
    rejected = set(rejected_slots or [])
    return {
        "schema_version": question_bank.V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION,
        "node_id": CURRENT_NODE_ID,
        "graph_version": CURRENT_GRAPH_VERSION,
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": question_bank.V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "verdict": verdict,
        "rejected_slots": sorted(rejected),
        "duplicate_suspicions": copy.deepcopy(duplicate_suspicions or []),
        "focal_slot_reviews": [
            {
                "slot": slot,
                "item_id": _item_by_slot(node_entry, slot)["id"],
                "candidate_sha256": question_bank.v12_external_candidate_sha256(_item_by_slot(node_entry, slot)),
                "item_review_semantic_evidence_sha256": _item_by_slot(node_entry, slot)["review_artifact"]["semantic_evidence_sha256"],
                "verdict": "needs_repair" if slot in rejected else "approved",
                "slot_fit": _scored(),
                "mathematical_correctness": _scored(),
                "context_semantics": _scored(),
                "prompt_answer_alignment": _scored(),
                "duplicate_suspicion_ids": [],
                "evidence": "Focal mathematical and semantic checks completed.",
                "repair_direction": "repair the cited defect" if slot in rejected else "none",
            }
            for slot in focal_slots
        ],
        "confidence": 0.95,
        "reasons": ["focal semantic evidence reviewed"],
        "repair_instructions": copy.deepcopy(repair_instructions or []),
    }


def _constituent_reviews(node_entry: dict, *, rejected_slots: set[int] | None = None) -> list[dict]:
    rejected_slots = set(rejected_slots or set())
    reviews = []
    for slots in question_bank.v12_expected_node_set_review_shards():
        focal_rejected = sorted(rejected_slots.intersection(slots))
        directives = [
            _repair_directive(node_entry, slot)
            for slot in focal_rejected
        ]
        output = _local_shard_output(
            node_entry,
            slots,
            verdict="needs_repair" if focal_rejected else "approved",
            rejected_slots=focal_rejected,
            repair_instructions=directives,
        )
        reviews.append({
            "shard_id": question_bank.v12_node_set_review_shard_id(slots),
            "reviewed_slots": list(slots),
            "review_output": output,
        })
    return reviews


def _global_classifications(node_entry: dict) -> list[dict]:
    evidence_moves = list(question_bank.V12_PRIMARY_EVIDENCE_MOVES)
    answer_paths = list(question_bank.V12_ANSWER_PATH_FAMILIES)
    representations = list(question_bank.V12_REPRESENTATION_FAMILIES)
    result = []
    for index, item in enumerate(sorted(node_entry["items"], key=lambda value: int(value["slot"]))):
        subject = question_bank.v12_item_review_subject_binding(item)
        result.append({
            **{key: subject[key] for key in (
                "node_id", "slot", "item_id", "candidate_sha256", "child_surface_sha256",
                "item_review_request_sha256", "item_review_semantic_evidence_sha256",
            )},
            "ownership_mode": "current_node_mainline",
            "current_node_indispensable": "yes",
            "primary_evidence_move": evidence_moves[index % len(evidence_moves)],
            "answer_path_family": answer_paths[index % len(answer_paths)],
            "representation_family": representations[index % len(representations)],
            "difficulty_verdict": "L2" if index < 14 else "L3",
            "difficulty_features": [],
            "prompt_interaction_verdict": "aligned",
            "reason": "classification follows actual prompt, controls, and answer path",
        })
    return result


def _global_output(
    node_entry: dict,
    constituent_reviews: list[dict],
    *,
    verdict: str | None = None,
    rejected_slots: list[int] | None = None,
    repair_plan: list[dict] | None = None,
    clusters: list[dict] | None = None,
    duplicate_groups: list[dict] | None = None,
    distribution_scores: dict[str, float] | None = None,
    confidence: float = 0.95,
) -> dict:
    reported_clusters = copy.deepcopy(clusters or [])
    reported_duplicates = copy.deepcopy(duplicate_groups or [])
    score_payload = distribution_scores or {
        key: 0.95 for key in question_bank.V12_NODE_SET_DISTRIBUTION_SCORE_KEYS
    }
    ux = question_bank.v12_node_set_ux_aggregate(
        node_entry,
        constituent_reviews,
        {
            "node_ux_verdict": "approved",
            "repetitive_instruction_clusters": reported_clusters,
            "overloaded_slots": [],
            "notation_failure_slots": [],
            "dignity_failure_slots": [],
            "ux_rejected_slots": [],
        },
    )
    focal_rejected = {
        int(slot)
        for review in constituent_reviews
        for slot in (review.get("review_output") or {}).get("rejected_slots", [])
    }
    has_global_failure = bool(
        focal_rejected
        or ux["gate_errors"]
        or reported_duplicates
        or any(score_payload[key] < question_bank.V12_REVIEW_MIN_SCORE for key in question_bank.V12_NODE_SET_DISTRIBUTION_SCORE_KEYS)
        or confidence < question_bank.V12_NODE_SET_REVIEW_MIN_CONFIDENCE
    )
    return {
        "schema_version": question_bank.V12_NODE_SET_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "node_id": CURRENT_NODE_ID,
        "graph_version": CURRENT_GRAPH_VERSION,
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "verdict": verdict or ("needs_repair" if has_global_failure else "approved"),
        "node_ux_verdict": "needs_repair" if ux["gate_errors"] else "approved",
        "slot_evidence_coverage": question_bank.v12_node_set_semantic_evidence_coverage(
            node_entry,
            constituent_reviews,
        ),
        "distribution_scores": score_payload,
        "item_classifications": _global_classifications(node_entry),
        "homogeneous_clusters": [],
        "instruction_voice_distribution": ux["instruction_voice_distribution"],
        "unprompted_slot_results": ux["unprompted_slot_results"],
        "repetitive_instruction_clusters": reported_clusters,
        "duplicate_groups": reported_duplicates,
        "overloaded_slots": ux["overloaded_slots"],
        "notation_failure_slots": ux["notation_failure_slots"],
        "dignity_failure_slots": ux["dignity_failure_slots"],
        "ux_rejected_slots": ux["ux_rejected_slots"],
        "rejected_slots": sorted(rejected_slots or []),
        "confidence": confidence,
        "reasons": ["global compact review completed"],
        "repair_plan": copy.deepcopy(repair_plan or []),
    }


class QuestionBankV12V4ContractTest(unittest.TestCase):
    def test_v4_contract_identities_and_agent_files_are_fresh(self):
        module = _load_builder()
        identity_names = (
            "V12_DESIGNER_CONTRACT_VERSION",
            "V12_DESIGNER_PROMPT_VERSION_ID",
            "V12_DESIGNER_RESPONSE_SCHEMA_VERSION",
            "V12_REVIEWER_CONTRACT_VERSION",
            "V12_REVIEWER_PROMPT_VERSION_ID",
            "V12_REVIEWER_RESPONSE_SCHEMA_VERSION",
            "V12_NODE_SET_REVIEWER_CONTRACT_VERSION",
            "V12_NODE_SET_REVIEWER_PROMPT_VERSION_ID",
            "V12_NODE_SET_REVIEWER_RESPONSE_SCHEMA_VERSION",
            "V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION",
            "V12_NODE_SET_REVIEW_SEMANTIC_EVIDENCE_VERSION",
            "V12_RUNNER_RECEIPT_SCHEMA_VERSION",
            "V12_COMPLETED_NODE_RECEIPT_SCHEMA_VERSION",
            "V12_ACTIVE_QUALITY_CONTRACT_VERSION",
        )
        for name in identity_names:
            with self.subTest(identity=name):
                self.assertTrue(str(getattr(question_bank, name, "")).endswith(".v4"), name)

        v6_identity_names = (
            "V12_GLOBAL_FINALIZER_CONTRACT_VERSION",
            "V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID",
            "V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION",
            "V12_NODE_SET_GLOBAL_FINALIZER_MODEL_EVIDENCE_VERSION",
        )
        for name in v6_identity_names:
            with self.subTest(identity=name):
                self.assertTrue(str(getattr(question_bank, name, "")).endswith(".v6"), name)
        self.assertTrue(question_bank.V12_SEMANTIC_EVIDENCE_COMMITMENT_VERSION.endswith(".v5"))
        self.assertTrue(
            question_bank.V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION.endswith(".v4")
        )
        self.assertTrue(
            question_bank.V12_NODE_SET_GLOBAL_FINALIZER_REQUEST_LINEAGE_VERSION.endswith(".v1")
        )

        v4_path_names = (
            "DESIGNER_CONTRACT_PATH",
            "REVIEWER_CONTRACT_PATH",
            "NODE_SET_REVIEWER_CONTRACT_PATH",
            "DESIGNER_PROMPT_PATH",
            "REVIEWER_PROMPT_PATH",
            "NODE_SET_REVIEWER_PROMPT_PATH",
        )
        for name in v4_path_names:
            with self.subTest(path=name):
                path = getattr(module, name, None)
                self.assertIsInstance(path, Path, f"missing v4 builder path {name}")
                self.assertIn(".v4.", path.name)
                self.assertTrue(path.is_file(), path)
        for name in ("GLOBAL_FINALIZER_CONTRACT_PATH", "GLOBAL_FINALIZER_PROMPT_PATH"):
            with self.subTest(path=name):
                path = getattr(module, name, None)
                self.assertIsInstance(path, Path, f"missing v5 builder path {name}")
                self.assertIn(".v6.", path.name)
                self.assertTrue(path.is_file(), path)

    def test_child_visible_prompt_and_review_only_payloads_are_strictly_partitioned(self):
        module = _load_builder()
        item = _item(14)
        packet = module._node_set_review_focal_item(item)

        self.assertEqual(
            {
                "prompt_format": question_bank.CHILD_PROMPT_FORMAT,
                "prompt": item["prompt"],
                "interaction_schema": question_bank.normalize_question_interaction_schema(
                    item["interaction_schema"]
                ),
            },
            packet.get("child_visible"),
        )
        self.assertEqual(
            {
                "answer_format": item["answer_format"],
                "expected_answer": item["expected_answer"],
                "accepted_alternatives": item["accepted_alternatives"],
                "solution_steps": item["solution_steps"],
            },
            packet.get("review_only"),
        )
        for hidden_key in ("answer_format", "expected_answer", "accepted_alternatives", "solution_steps"):
            with self.subTest(hidden_key=hidden_key):
                self.assertNotIn(hidden_key, packet)
                self.assertNotIn(hidden_key, packet["child_visible"])

    def test_interaction_schema_is_required_for_current_designer_and_answer_safe(self):
        current_item = _item(3)
        current_item["designer_artifact"] = {
            "prompt_version_id": question_bank.V12_DESIGNER_PROMPT_VERSION_ID,
        }
        missing_schema = copy.deepcopy(current_item)
        missing_schema.pop("interaction_schema")
        missing_errors = question_bank.v12_item_policy_errors(_graph_node(), missing_schema)
        self.assertIn("interaction_schema:missing_for_current_designer_contract", missing_errors)

        leaky_schema = copy.deepcopy(current_item)
        leaky_schema["interaction_schema"] = {
            **_interaction_schema("single_choice"),
            "choices": [
                {"id": "a", "label": "关系 A", "is_correct": True},
                {"id": "b", "label": "关系 B"},
            ],
            "expected_answer": "关系 A",
        }
        leaky_errors = question_bank.v12_item_policy_errors(_graph_node(), leaky_schema)
        self.assertTrue(
            any(error.startswith("interaction_schema.forbidden_key:") for error in leaky_errors),
            leaky_errors,
        )

        leaky_value_schema = copy.deepcopy(current_item)
        leaky_value_schema["interaction_schema"] = {
            **_interaction_schema("fill_blank"),
            "fields": [
                {"id": "expected_answer", "label": "第一空", "placeholder": "不要泄漏"},
            ],
        }
        leaky_value_errors = question_bank.v12_item_policy_errors(_graph_node(), leaky_value_schema)
        self.assertTrue(
            any(error.startswith("interaction_schema.forbidden_value:") for error in leaky_value_errors),
            leaky_value_errors,
        )

        safe_structured = copy.deepcopy(current_item)
        safe_structured["interaction_schema"] = _interaction_schema("formula_input")
        safe_errors = question_bank.v12_item_policy_errors(_graph_node(), safe_structured)
        self.assertNotIn("interaction_schema:missing_for_current_designer_contract", safe_errors)
        self.assertFalse(
            any(error.startswith("interaction_schema.") for error in safe_errors),
            safe_errors,
        )

    def test_process_disclosure_uses_exact_child_prompt_quotes_and_ignores_hidden_fields(self):
        gate_errors = _require_callable(
            self,
            question_bank,
            "v12_process_disclosure_gate_errors",
        )
        for slot in (14, 19, 20):
            item = _item(slot)
            with self.subTest(slot=slot, boundary="prompt-only pass"):
                self.assertEqual(
                    [],
                    gate_errors(item, _process_disclosure_evidence(disclosed=False)),
                )
            with self.subTest(slot=slot, boundary="hidden quote rejected"):
                errors = gate_errors(
                    item,
                    _process_disclosure_evidence(
                        disclosed=True,
                        quote=item["answer_format"],
                    ),
                )
                self.assertIn("process_disclosure_evidence:exact_child_prompt_quote_required", errors)

        disclosed_prompt = "Determine the result. Show the relation, every step, the unit, and a final check."
        disclosed = _item(19, prompt=disclosed_prompt)
        errors = gate_errors(
            disclosed,
            _process_disclosure_evidence(
                disclosed=True,
                quote="Show the relation, every step, the unit, and a final check.",
            ),
        )
        self.assertIn("unprompted_process_evidence:process_target_disclosed", errors)

    def test_two_slot_shard_repair_authority_is_exactly_focal(self):
        validate = _require_callable(self, question_bank, "v12_local_shard_output_errors")
        node_entry = _node_entry()
        focal = [1, 2]
        valid = _local_shard_output(
            node_entry,
            focal,
            verdict="needs_repair",
            rejected_slots=[1],
            repair_instructions=[_repair_directive(node_entry, 1)],
            duplicate_suspicions=[
                {
                    "suspicion_id": "dup-1-7",
                    "slots": [1, 7],
                    "reason": "possible duplicate touching focal slot",
                    "evidence_refs": ["slot:1", "slot:7"],
                }
            ],
        )
        self.assertEqual([], validate(node_entry, reviewed_slots=focal, output=valid))

        cases = {
            "non_focal_rejected_slot": _local_shard_output(
                node_entry,
                focal,
                verdict="needs_repair",
                rejected_slots=[3],
                repair_instructions=[_repair_directive(node_entry, 3)],
            ),
            "rejected_directive_mismatch": _local_shard_output(
                node_entry,
                focal,
                verdict="needs_repair",
                rejected_slots=[1],
                repair_instructions=[_repair_directive(node_entry, 2)],
            ),
            "approved_with_actionable_repair": _local_shard_output(
                node_entry,
                focal,
                verdict="approved",
                repair_instructions=[_repair_directive(node_entry, 1)],
            ),
            "duplicate_suspicion_without_focal_slot": _local_shard_output(
                node_entry,
                focal,
                duplicate_suspicions=[
                    {
                        "suspicion_id": "dup-3-4",
                        "slots": [3, 4],
                        "reason": "non-focal claim",
                        "evidence_refs": ["slot:3", "slot:4"],
                    }
                ],
            ),
        }
        for name, output in cases.items():
            with self.subTest(case=name):
                self.assertTrue(validate(node_entry, reviewed_slots=focal, output=output), name)

    def test_local_shard_global_variety_is_advisory_and_cannot_trigger_repair(self):
        validate = _require_callable(self, question_bank, "v12_local_shard_output_errors")
        node_entry = _node_entry()
        output = _local_shard_output(
            node_entry,
            [1, 2],
            verdict="approved",
        )
        self.assertEqual(
            [],
            validate(node_entry, reviewed_slots=[1, 2], output=output),
        )
        self.assertEqual([], output["rejected_slots"])
        self.assertEqual([], output["repair_instructions"])

    def test_designer_target_voice_and_item_review_actual_voice_are_contractual(self):
        module = _load_builder()
        designer_path = getattr(module, "DESIGNER_CONTRACT_PATH", None)
        reviewer_path = getattr(module, "REVIEWER_CONTRACT_PATH", None)
        self.assertIsInstance(designer_path, Path)
        self.assertIsInstance(reviewer_path, Path)
        designer = json.loads(designer_path.read_text(encoding="utf-8"))
        reviewer = json.loads(reviewer_path.read_text(encoding="utf-8"))
        designer_item = designer["response_schema"]["properties"]["items"]["items"]
        review_item = reviewer["response_schema"]["properties"]["item_reviews"]["items"]
        semantic = review_item["properties"]["semantic_evidence"]

        self.assertIn("intended_instruction_voice_family", designer_item["required"])
        self.assertIn("interaction_schema", designer_item["required"])
        interaction_schema = designer_item["properties"]["interaction_schema"]
        self.assertEqual(question_bank.QUESTION_INTERACTION_SCHEMA_VERSION, interaction_schema["properties"]["schema_version"]["const"])
        self.assertIn("fill_blank", interaction_schema["properties"]["type"]["enum"])
        self.assertIn("single_choice", interaction_schema["properties"]["type"]["enum"])
        self.assertIn("formula_input", interaction_schema["properties"]["type"]["enum"])
        self.assertIn("instruction_voice_family", semantic["required"])
        self.assertNotIn("actual_instruction_voice_family", semantic["required"])
        disclosure = semantic["properties"]["process_disclosure_evidence"]
        self.assertIn("verdict", disclosure["required"])
        self.assertEqual(["disclosed", "not_disclosed"], disclosure["properties"]["verdict"]["enum"])

        validate = _require_callable(self, question_bank, "v12_instruction_voice_evidence_errors")
        item = _item(3, voice="compare_and_choose")
        matching = {
            "instruction_voice_family": "compare_and_choose",
            "reason": "The child compares two methods before choosing.",
        }
        self.assertEqual([], validate(item, matching))
        mismatching = {
            **matching,
            "instruction_voice_family": "solve_and_interpret",
        }
        self.assertTrue(validate(item, mismatching))

        item_with_review = copy.deepcopy(item)
        item_with_review["review_artifact"] = {
            "semantic_evidence": {
                **matching,
                "response_moves": ["compare", "choose", "justify"],
            }
        }
        summary = module._item_summaries([item_with_review])[0]
        self.assertEqual("compare_and_choose", summary["instruction_voice_family"])
        self.assertEqual(["compare", "choose", "justify"], summary["response_moves"])

    def test_deterministic_voice_plan_has_six_family_hard_floor_and_eight_family_target(self):
        reduce_global = _require_callable(self, question_bank, "v12_global_review_reduce")

        planned = question_bank.v12_instruction_voice_plan(_graph_node())
        self.assertGreaterEqual(len(set(planned.values())), 8)

        six_node = _node_entry(family_count=6)
        six_reviews = _constituent_reviews(six_node)
        six = reduce_global(six_node, six_reviews, _global_output(six_node, six_reviews))
        self.assertNotIn("instruction_voice_family_minimum", six["gate_errors"])
        self.assertEqual("approved", six["verdict"])

        five_node = _node_entry(family_count=5)
        five_reviews = _constituent_reviews(five_node)
        five = reduce_global(five_node, five_reviews, _global_output(five_node, five_reviews))
        self.assertIn("instruction_voice_family_minimum", five["gate_errors"])
        self.assertIn("global.voice_family_minimum:missing_exact_repair_plan", five["errors"])

    def test_focal_review_runtime_binds_opaque_item_references_by_slot(self):
        module = _load_builder()
        bind_identity = _require_callable(
            self,
            module,
            "_bind_node_set_focal_review_identity",
        )
        node_entry = _node_entry()
        raw_output = _local_shard_output(node_entry, [7, 8])
        for entry in raw_output["focal_slot_reviews"]:
            entry["item_id"] = "model-copied-the-wrong-item-id"
            entry["candidate_sha256"] = "model-copied-the-wrong-candidate-digest"
            entry["item_review_semantic_evidence_sha256"] = (
                "model-copied-the-wrong-evidence-digest"
            )
        original = copy.deepcopy(raw_output)

        bound = bind_identity(
            node_entry=node_entry,
            reviewed_slots=[7, 8],
            output=raw_output,
        )

        self.assertEqual(original, raw_output, "runtime binding must preserve the raw model output")
        for entry in bound["focal_slot_reviews"]:
            item = _item_by_slot(node_entry, int(entry["slot"]))
            self.assertEqual(item["id"], entry["item_id"])
            self.assertEqual(
                question_bank.v12_external_candidate_sha256(item),
                entry["candidate_sha256"],
            )
            self.assertEqual(
                item["review_artifact"]["semantic_evidence_sha256"],
                entry["item_review_semantic_evidence_sha256"],
            )
            raw_entry = next(
                candidate
                for candidate in original["focal_slot_reviews"]
                if candidate["slot"] == entry["slot"]
            )
            for semantic_field in (
                "verdict",
                "slot_fit",
                "mathematical_correctness",
                "context_semantics",
                "prompt_answer_alignment",
                "duplicate_suspicion_ids",
                "evidence",
                "repair_direction",
            ):
                self.assertEqual(raw_entry[semantic_field], entry[semantic_field])

    def test_focal_review_runtime_binding_does_not_launder_wrong_slot_or_semantic_judgment(self):
        module = _load_builder()
        bind_identity = _require_callable(
            self,
            module,
            "_bind_node_set_focal_review_identity",
        )
        node_entry = _node_entry()

        wrong_slot = _local_shard_output(node_entry, [7, 8])
        wrong_slot["focal_slot_reviews"][0]["slot"] = 9
        bound_wrong_slot = bind_identity(
            node_entry=node_entry,
            reviewed_slots=[7, 8],
            output=wrong_slot,
        )
        wrong_slot_errors = question_bank.v12_node_set_focal_review_output_errors(
            node_entry,
            reviewed_slots=[7, 8],
            output=bound_wrong_slot,
        )
        self.assertIn("focal_slot_reviews:coverage_mismatch", wrong_slot_errors[0])
        self.assertTrue(
            any("mismatch" in detail for detail in wrong_slot_errors[9]),
            wrong_slot_errors,
        )

        wrong_semantics = _local_shard_output(node_entry, [7, 8])
        for entry in wrong_semantics["focal_slot_reviews"]:
            entry["item_id"] = "wrong-model-item-echo"
            entry["candidate_sha256"] = "wrong-model-candidate-echo"
            entry["item_review_semantic_evidence_sha256"] = "wrong-model-review-echo"
        wrong_semantics["focal_slot_reviews"][0]["context_semantics"] = _scored(
            verdict="fail",
            score=0.1,
            reason="The model judged the focal context as mathematically ambiguous.",
        )
        bound_wrong_semantics = bind_identity(
            node_entry=node_entry,
            reviewed_slots=[7, 8],
            output=wrong_semantics,
        )
        slot7 = next(
            entry
            for entry in bound_wrong_semantics["focal_slot_reviews"]
            if entry["slot"] == 7
        )
        self.assertEqual("fail", slot7["context_semantics"]["verdict"])
        self.assertEqual(0.1, slot7["context_semantics"]["score"])
        semantic_errors = question_bank.v12_node_set_focal_review_output_errors(
            node_entry,
            reviewed_slots=[7, 8],
            output=bound_wrong_semantics,
        )
        self.assertIn(
            "focal_slot_review.context_semantics:verdict_not_pass",
            semantic_errors[7],
        )
        self.assertIn(
            "focal_slot_review.context_semantics:score_below_gate",
            semantic_errors[7],
        )

    def test_focal_review_runtime_binding_rejects_trusted_item_review_digest_drift(self):
        module = _load_builder()
        bind_identity = _require_callable(
            self,
            module,
            "_bind_node_set_focal_review_identity",
        )
        node_entry = _node_entry()
        item = _item_by_slot(node_entry, 7)
        item["review_artifact"]["semantic_evidence"]["evidence"] = (
            "tampered trusted semantic evidence after its digest was committed"
        )
        raw_output = _local_shard_output(node_entry, [7, 8])
        for entry in raw_output["focal_slot_reviews"]:
            entry["item_id"] = "wrong-model-item-echo"
            entry["candidate_sha256"] = "wrong-model-candidate-echo"
            entry["item_review_semantic_evidence_sha256"] = "wrong-model-review-echo"

        with self.assertRaisesRegex(
            module.model_router.ModelCallError,
            r"trusted item review semantic evidence mismatch for slot 7",
        ):
            bind_identity(
                node_entry=node_entry,
                reviewed_slots=[7, 8],
                output=raw_output,
            )

    def test_one_global_finalizer_call_receives_twenty_prompt_only_compact_cards(self):
        module = _load_builder()
        run_review = _require_callable(self, module, "_node_set_semantic_repair_instructions")
        signature = inspect.signature(run_review)
        for parameter in (
            "global_finalizer_contract",
            "global_finalizer_prompt_template",
        ):
            self.assertIn(parameter, signature.parameters, f"missing v4 finalizer parameter {parameter}")

        global_contract_path = getattr(module, "GLOBAL_FINALIZER_CONTRACT_PATH", None)
        self.assertIsInstance(global_contract_path, Path)
        global_contract = json.loads(global_contract_path.read_text(encoding="utf-8"))
        global_schema = global_contract["response_schema"]
        self.assertFalse(global_schema["additionalProperties"])
        self.assertEqual(
            question_bank.V12_NODE_SET_GLOBAL_FINALIZER_MODEL_FIELDS,
            set(global_schema["properties"]),
        )
        for runtime_owned in (
            "verdict",
            "node_ux_verdict",
            "slot_evidence_coverage",
            "instruction_voice_distribution",
            "unprompted_slot_results",
            "rejected_slots",
            "overloaded_slots",
            "notation_failure_slots",
            "dignity_failure_slots",
            "ux_rejected_slots",
            "gate_errors",
        ):
            self.assertNotIn(runtime_owned, global_schema["properties"])
        local_contract = json.loads(module.NODE_SET_REVIEWER_CONTRACT_PATH.read_text(encoding="utf-8"))
        node_entry = _node_entry()
        calls: list[dict] = []

        def fake_call(**kwargs):
            calls.append(copy.deepcopy(kwargs))
            task = kwargs["route"].task
            if task == "node_set_review":
                focal = list(kwargs["trusted_context"]["reviewed_slots"])
                value = _local_shard_output(node_entry, focal)
                for entry in value["focal_slot_reviews"]:
                    entry["item_id"] = "wrong-runtime-model-item-echo"
                    entry["candidate_sha256"] = "wrong-runtime-model-candidate-echo"
                    entry["item_review_semantic_evidence_sha256"] = (
                        "wrong-runtime-model-review-echo"
                    )
            elif task == "node_global_finalizer":
                value = module._global_model_judgment_from_output(
                    _global_output(node_entry, _constituent_reviews(node_entry))
                )
            else:
                raise AssertionError(f"unexpected route {task}")
            rendered = (
                module._render_prompt(
                    kwargs["prompt_template"],
                    trusted_context=kwargs["trusted_context"],
                    untrusted_payload=kwargs["untrusted_payload"],
                )
                if task == "node_global_finalizer"
                else f"rendered:{task}"
            )
            return model_router.StructuredJSONResult(
                value=value,
                mode="json_schema",
                raw_response={"task": task},
            ), rendered

        local_route = model_router.ModelRoute(
            agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
            task="node_set_review",
            provider="test",
            model="test",
            model_alias="test",
            base_url="",
            api_key="",
            timeout_seconds=1.0,
            model_params={},
        )
        global_route = model_router.ModelRoute(
            agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
            task="node_global_finalizer",
            provider="test",
            model="test",
            model_alias="test",
            base_url="",
            api_key="",
            timeout_seconds=1.0,
            model_params={},
        )
        with mock.patch.object(module, "_call_v12_batch_agent", side_effect=fake_call), mock.patch.object(
            module.model_router,
            "question_node_set_review_route",
            return_value=local_route,
        ), mock.patch.object(
            module.model_router,
            "question_node_global_finalizer_route",
            return_value=global_route,
            create=True,
        ):
            review_result = run_review(
                node_entry=node_entry,
                node=_graph_node(),
                graph=AUTHORITATIVE_GRAPH,
                graph_version=CURRENT_GRAPH_VERSION,
                contract=local_contract,
                prompt_template=module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                global_finalizer_contract=global_contract,
                global_finalizer_prompt_template=module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(encoding="utf-8"),
                accepted_core_summaries=[],
                node_review_concurrency=1,
            )

        constituent_reviews = review_result["node_review_artifact"]["constituent_reviews"]
        self.assertEqual(10, len(constituent_reviews))
        for constituent in constituent_reviews:
            for entry in constituent["review_output"]["focal_slot_reviews"]:
                item = _item_by_slot(node_entry, int(entry["slot"]))
                self.assertEqual(item["id"], entry["item_id"])
                self.assertEqual(
                    question_bank.v12_external_candidate_sha256(item),
                    entry["candidate_sha256"],
                )
                self.assertEqual(
                    item["review_artifact"]["semantic_evidence_sha256"],
                    entry["item_review_semantic_evidence_sha256"],
                )

        global_calls = [call for call in calls if call["route"].task == "node_global_finalizer"]
        self.assertEqual(1, len(global_calls))
        payload = global_calls[0]["untrusted_payload"]
        cards = payload["item_cards"]
        self.assertEqual(list(range(1, 21)), [int(card["slot"]) for card in cards])
        for card, item in zip(cards, node_entry["items"]):
            with self.subTest(slot=item["slot"]):
                self.assertEqual(question_bank.CHILD_PROMPT_FORMAT, card["child_visible"]["prompt_format"])
                self.assertEqual(item["prompt"], card["child_visible"]["prompt"])
                self.assertIn("interaction_schema", card["child_visible"])
                self.assertIn("review_subject", card)
                self.assertNotIn("answer_format", card)
                self.assertNotIn("expected_answer", card)
                self.assertNotIn("solution_steps", card)
                self.assertNotIn("review_only", card)
                self.assertNotIn("question_digest_sha256", card)
                self.assertNotIn("semantic_evidence_sha256", card)
        model_fields = set(global_contract["response_schema"]["properties"])
        self.assertTrue(
            all(
                runtime_owned not in model_fields
                for runtime_owned in (
                    "slot_evidence_coverage",
                    "rejected_slots",
                    "verdict",
                    "node_ux_verdict",
                )
            )
        )
        self.assertEqual(1, global_calls[0]["trusted_context"]["policy"]["global_finalizer_concurrency"])

    def test_global_finalizer_repair_slots_and_directives_match_exactly(self):
        validate = _require_callable(self, question_bank, "v12_global_finalizer_output_errors")
        node_entry = _node_entry()
        reviews = _constituent_reviews(node_entry)
        low_scores = {
            key: 0.95 for key in question_bank.V12_NODE_SET_DISTRIBUTION_SCORE_KEYS
        }
        low_scores["instruction_voice_variety"] = 0.7
        plan = [
            _repair_directive(
                node_entry,
                3,
                scope="global_voice_distribution",
                family="represent_and_translate",
                dimension="instruction_voice_family",
            ),
            _repair_directive(
                node_entry,
                13,
                scope="global_voice_distribution",
                family="reverse_reasoning",
                dimension="instruction_voice_family",
            ),
        ]
        valid = _global_output(
            node_entry,
            reviews,
            verdict="needs_repair",
            rejected_slots=[3, 13],
            repair_plan=plan,
            distribution_scores=low_scores,
        )
        self.assertEqual([], validate(node_entry, valid, constituent_reviews=reviews))

        missing_directive = copy.deepcopy(valid)
        missing_directive["repair_plan"].pop()
        self.assertIn(
            "global.rejected_slots:must_equal_repair_plan_slots",
            validate(node_entry, missing_directive, constituent_reviews=reviews),
        )
        low_score_without_plan = _global_output(
            node_entry,
            reviews,
            verdict="needs_repair",
            distribution_scores=low_scores,
        )
        low_score_without_plan["verdict"] = "needs_repair"
        self.assertIn(
            "global.low_score_or_confidence:missing_exact_repair_plan",
            validate(node_entry, low_score_without_plan, constituent_reviews=reviews),
        )

    def test_noop_repair_is_rejected_without_consuming_repair_budget(self):
        transition = _require_callable(self, question_bank, "v12_repair_state_transition")
        old_item = _item(3, voice="solve_and_interpret")
        node_entry = {"items": [old_item]}
        state = {
            "repair_rounds_by_slot": {"3": 1},
            "pending_repair_slots": [3],
            "accepted_by_slot": {"3": copy.deepcopy(old_item)},
        }
        result = transition(
            state=copy.deepcopy(state),
            old_item=old_item,
            new_item=copy.deepcopy(old_item),
            directive=_repair_directive(
                node_entry,
                3,
                family="compare_and_choose",
                dimension="instruction_voice_family",
            ),
        )
        self.assertFalse(result["accepted"])
        self.assertEqual("no_effective_delta", result["reason"])
        self.assertEqual(state["repair_rounds_by_slot"], result["state"]["repair_rounds_by_slot"])
        self.assertEqual(state["pending_repair_slots"], result["state"]["pending_repair_slots"])

    def test_global_reducer_canonicalizes_overlapping_clusters_independent_of_order(self):
        reduce_global = _require_callable(self, question_bank, "v12_global_review_reduce")
        node_entry = _node_entry(family_count=8)
        reviews = _constituent_reviews(node_entry)
        clusters = [
            {
                "cluster_id": "judgment-cluster-7",
                "slots": [2, 3, 6, 13, 14, 16, 20],
                "cluster_summary": "seven items share one substantive instruction skeleton",
                "reason": "seven items share one substantive instruction skeleton",
                "evidence_refs": ["cluster:judgment"],
            },
            {
                "cluster_id": "diagnostic-cluster-6",
                "slots": [2, 6, 14, 17, 19, 20],
                "cluster_summary": "six items share a second repetitive shell",
                "reason": "six items share a second repetitive shell",
                "evidence_refs": ["cluster:diagnostic"],
            },
        ]
        first = reduce_global(node_entry, reviews, _global_output(node_entry, reviews, clusters=clusters))
        second = reduce_global(
            node_entry,
            list(reversed(reviews)),
            _global_output(node_entry, list(reversed(reviews)), clusters=list(reversed(clusters))),
        )

        expected = [3, 14, 16, 19, 20]
        self.assertEqual(expected, first["rejected_slots"])
        self.assertEqual(expected, second["rejected_slots"])
        self.assertEqual(first["rejected_slots"], second["rejected_slots"])
        for retained in (2, 6, 13, 17):
            self.assertNotIn(retained, first["rejected_slots"])
        for cluster in first["repetitive_instruction_clusters"]:
            remaining = set(cluster["slots"]) - set(first["rejected_slots"])
            self.assertLessEqual(len(remaining), question_bank.V12_MAX_REPETITIVE_INSTRUCTION_CLUSTER)

    def test_v3_and_v4_evidence_cannot_be_mixed_across_checkpoint_receipt_or_seed(self):
        validate = _require_callable(self, question_bank, "v12_v4_evidence_identity_errors")
        current = {
            "designer_contract_version": question_bank.V12_DESIGNER_CONTRACT_VERSION,
            "item_review_semantic_evidence_version": question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
            "local_constituent_versions": [
                question_bank.V12_NODE_SET_REVIEW_SEMANTIC_EVIDENCE_VERSION
                for _ in range(10)
            ],
            "global_finalizer_semantic_evidence_version": getattr(
                question_bank,
                "V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION",
                "missing-v4-global-evidence",
            ),
            "semantic_commitment_version": question_bank.V12_SEMANTIC_EVIDENCE_COMMITMENT_VERSION,
            "runner_receipt_schema_version": question_bank.V12_RUNNER_RECEIPT_SCHEMA_VERSION,
            "completed_node_receipt_schema_version": question_bank.V12_COMPLETED_NODE_RECEIPT_SCHEMA_VERSION,
            "active_quality_contract_version": question_bank.V12_ACTIVE_QUALITY_CONTRACT_VERSION,
        }
        self.assertEqual([], validate(current))

        v3_identity = "2026-07-12.math-qb-v12.node-set-review-semantic-evidence.v3"
        mutations = {
            "checkpoint_constituent": ("local_constituent_versions", [v3_identity] + current["local_constituent_versions"][1:]),
            "runner_receipt": ("runner_receipt_schema_version", "2026-07-12.math-qb-v12.runner-receipt.v3"),
            "completed_receipt": ("completed_node_receipt_schema_version", "2026-07-12.math-qb-v12.completed-node-receipt.v3"),
            "active_seed": ("active_quality_contract_version", "2026-07-12.math-qb-v12.active-quality.v3"),
        }
        for name, (field, value) in mutations.items():
            mixed = copy.deepcopy(current)
            mixed[field] = value
            with self.subTest(surface=name):
                self.assertTrue(validate(mixed), name)

    def test_exhaustion_persists_final_aggregate_plan_slots_and_seal_before_raise(self):
        module = _load_builder()
        exhaust = _require_callable(self, module, "_persist_v4_node_set_exhaustion_and_raise")
        node_entry = _node_entry()
        plan = [_repair_directive(node_entry, 3), _repair_directive(node_entry, 13)]
        node_review_artifact = {
            "verdict": "needs_repair",
            "node_ux_verdict": "needs_repair",
            "distribution_scores": {},
            "confidence": 0.95,
            "duplicate_groups": [],
            "repetitive_instruction_clusters": [],
            "rejected_slots": [3, 13],
            "gate_errors": ["repetitive_instruction_cluster_limit"],
            "semantic_evidence_version": question_bank.V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION,
            "semantic_evidence_sha256": "semantic-sha",
            "global_review_output_sha256": "global-sha",
            "aggregation": {"aggregate_sha256": "aggregate-sha"},
            "canonical_repair_plan": plan,
            "stage_attempt": 2,
        }

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "exhausted"):
                exhaust(
                    checkpoint_dir=Path(tmp),
                    node_id=CURRENT_NODE_ID,
                    graph_version=CURRENT_GRAPH_VERSION,
                    rounds_used=3,
                    rejected_rounds=2,
                    report={"issues": []},
                    node_entry=node_entry,
                    node_review_artifact=node_review_artifact,
                    pending_repair_by_slot={3: [plan[0]], 13: [plan[1]]},
                    slot_rounds={3: 3, 13: 3},
                    stage_counters={"node_set_repair_rounds_by_slot": {"3": 3, "13": 3}},
                    repair_chain_events=[],
                    checkpoint_migrations=[],
                    exhausted_slots=[3, 13],
                    max_semantic_rounds=3,
                )

            persisted = json.loads((Path(tmp) / f"{CURRENT_NODE_ID}.json").read_text(encoding="utf-8"))

        self.assertEqual(node_review_artifact["verdict"], persisted["final_node_review_aggregate"]["verdict"])
        self.assertEqual(plan, persisted["canonical_repair_plan"])
        self.assertEqual([3, 13], persisted["exhausted_slots"])
        self.assertEqual("incomplete", persisted["status"])
        self.assertEqual("node_set_semantic_repair_exhausted", persisted["exhaustion_diagnostic"]["failure_class"])
        self.assertEqual(
            module._checkpoint_integrity_sha256(persisted),
            persisted["checkpoint_integrity_sha256"],
        )

    def test_resume_plan_is_idempotent_for_local_shards_and_global_finalizer(self):
        resume_plan = _require_callable(self, question_bank, "v12_v4_resume_plan")
        expected_shards = question_bank.v12_expected_node_set_review_shards()
        checkpoint = {
            "local_constituent_reviewed_slots": copy.deepcopy(expected_shards[:5]),
            "global_finalizer": None,
            "execution_policy": {
                "slot_chunk_concurrency": 4,
                "node_review_concurrency": 1,
                "global_finalizer_concurrency": 1,
            },
        }
        first = resume_plan(checkpoint)
        self.assertEqual(expected_shards[5:], first["missing_local_shards"])
        self.assertTrue(first["global_finalizer_required"])
        self.assertEqual(4, first["slot_chunk_concurrency"])
        self.assertEqual(1, first["node_review_concurrency"])
        self.assertEqual(1, first["global_finalizer_concurrency"])

        completed = copy.deepcopy(checkpoint)
        completed["local_constituent_reviewed_slots"] = copy.deepcopy(expected_shards)
        completed["global_finalizer"] = {
            "verdict": "approved",
            "semantic_evidence_version": getattr(
                question_bank,
                "V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION",
                "missing-v4-global-evidence",
            ),
        }
        second = resume_plan(completed)
        self.assertEqual([], second["missing_local_shards"])
        self.assertFalse(second["global_finalizer_required"])
        self.assertEqual(second, resume_plan(copy.deepcopy(completed)))

    def test_v4_semantic_decisions_do_not_use_regex_or_keyword_oracles(self):
        semantic_functions = (
            "v12_process_disclosure_gate_errors",
            "v12_local_shard_output_errors",
            "v12_instruction_voice_evidence_errors",
            "v12_global_review_reduce",
            "v12_global_finalizer_output_errors",
            "v12_repair_state_transition",
        )
        for name in semantic_functions:
            function = _require_callable(self, question_bank, name)
            source = inspect.getsource(function)
            tree = ast.parse(source)
            forbidden_calls: list[str] = []
            forbidden_membership: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    owner = node.func.value
                    if isinstance(owner, ast.Name) and owner.id == "re":
                        forbidden_calls.append(f"re.{node.func.attr}")
                    if node.func.attr in {"find", "index", "startswith", "endswith"}:
                        forbidden_calls.append(node.func.attr)
                if isinstance(node, ast.Compare) and any(
                    isinstance(operator, (ast.In, ast.NotIn)) for operator in node.ops
                ):
                    if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                        forbidden_membership.append(node.left.value)
            with self.subTest(function=name):
                self.assertEqual([], forbidden_calls, f"regex/string classifier calls in {name}")
                self.assertEqual([], forbidden_membership, f"literal keyword membership oracle in {name}")

    def test_historical_v3_checkpoint_remains_read_only_oracle(self):
        self.assertTrue(HISTORICAL_V3_CHECKPOINT.is_file())
        before = HISTORICAL_V3_CHECKPOINT.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / HISTORICAL_V3_CHECKPOINT.name
            copied.write_bytes(before)
            self.assertEqual(before, copied.read_bytes())
        self.assertEqual(before, HISTORICAL_V3_CHECKPOINT.read_bytes())


if __name__ == "__main__":
    unittest.main()
