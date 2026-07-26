from __future__ import annotations

import json
import unittest
from pathlib import Path

from learning_system.admin.question_generation import (
    _batch_response_schema,
    _child_surface_findings,
    _minimum_written_response_lines,
    _normalize_model_item,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _requirement() -> dict:
    return {
        "question_requirement_id": "REQ-child-surface-test",
        "slot_id": "M-TEST:family:01",
        "family_id": "test_family",
        "difficulty": "L3",
        "evidence_goal": "能识别核心数量关系",
        "must_include": ["核心数量关系"],
    }


def _plan(*, visual_resources: list[object] | None = None) -> dict:
    return {
        "design_brief_id": "BRIEF-child-surface-test",
        "node_id": "M-TEST",
        "family_id": "test_family",
        "bounded_candidate_packet": {
            "visual_resources": visual_resources or [],
            "family_plan_entry": {
                "required_evidence": ["核心数量关系"],
            },
        },
    }


def _interaction_schema(
    *,
    interaction_type: str = "formula_input",
    allow_explanation: bool = True,
    requires_explanation: bool = True,
) -> dict:
    return {
        "schema_version": "2026-07-17.question-interaction.v2",
        "type": interaction_type,
        "title": "写下答案",
        "allow_explanation": allow_explanation,
        "requires_explanation": requires_explanation,
        "explanation_label": "一句依据" if allow_explanation else "",
        "fields": [],
        "choices": [],
        "formula_label": "算式或答案" if interaction_type == "formula_input" else "",
        "placeholder": "写下算式或答案" if interaction_type in {"short_text", "formula_input"} else "",
    }


def _item(prompt: str = "根据数量关系求出未知数，并写一句依据。") -> dict:
    return {
        "prompt": prompt,
        "answer_format": "算式或答案 + 一句依据",
        "interaction_schema": _interaction_schema(),
        "standard_answer": "x=4。因为题中的等量关系成立。",
        "expected_answer": "x=4，并写出对应的等量关系。",
        "accepted_alternatives": [],
        "rubric": ["关系正确。"],
        "solution_steps": ["列出关系并求解。"],
        "required_evidence": ["核心数量关系"],
        "key_score_points": [
            {
                "key": "core_relation",
                "points": 10,
                "evidence": "关系与结果正确。",
                "mastery_dimension": "model_relation",
            }
        ],
        "target_error_tags": ["modeling_or_reading"],
        "rollback_candidates": [],
        "estimated_minutes": 3,
        "evidence_goal": "能识别核心数量关系",
        "math_core_signature": "child-surface-test-signature",
        "design_rationale": "用单一数量关系暴露建模断点。",
    }


def _design() -> dict:
    return {
        "task_focus_count": 1,
        "primary_task": "根据一个核心数量关系求出未知数",
        "child_deliverables": ["算式或答案", "一句依据"],
        "backend_evidence_targets": ["核心数量关系"],
        "student_actions": {
            "primary": "compute_or_solve",
            "supporting": ["explain_core_relation"],
        },
        "interaction_requirements": {
            "response_kind": "formula_input",
            "actions": [],
        },
        "writing_burden": {
            "burden_level": "light",
            "estimated_response_lines": 2,
            "why_necessary": "一行答案和一行依据足以判断是否理解数量关系。",
        },
        "visual_support": {
            "mode": "not_needed",
            "prompt_depends_on_visual": False,
            "asset_ref": "",
            "inline_visual": "",
        },
        "language_surface": {
            "natural_child_facing_chinese": True,
            "respectful_age_appropriate": True,
            "semantic_review_boundary": "requires_independent_semantic_qa",
            "named_characters": [],
            "short_explanation_requests": 1,
        },
        "distractor_design": {
            "distractors": [],
        },
        "difficulty_alignment": {
            "target_difficulty": "L3",
            "diagnostic_breakpoint": "能否把文字条件转成一个等量关系",
            "difficulty_source": "mathematical_structure",
        },
    }


def _finding_codes(item: dict, design: dict | None = None, *, plan: dict | None = None) -> set[str]:
    output = {"item": item}
    if design is not None:
        output["child_surface_design"] = design
    return {
        finding["code"]
        for finding in _child_surface_findings(
            item,
            model_output=output,
            plan=plan or _plan(),
            requirement=_requirement(),
        )
    }


class AdminQuestionChildSurfaceTests(unittest.TestCase):
    def test_clean_fixture_has_zero_findings(self) -> None:
        self.assertEqual(set(), _finding_codes(_item(), _design()))

    def test_batch_contract_requires_structured_child_surface_design(self) -> None:
        schema = _batch_response_schema()
        candidate_schema = schema["properties"]["candidates"]["items"]
        design_schema = candidate_schema["properties"]["child_surface_design"]
        item_schema = candidate_schema["properties"]["item"]

        self.assertIn("child_surface_design", candidate_schema["required"])
        self.assertIn("interaction_schema", item_schema["required"])
        self.assertEqual(
            {
                "short_text",
                "fill_blank",
                "single_choice",
                "multi_choice",
                "formula_input",
            },
            set(item_schema["properties"]["interaction_schema"]["properties"]["type"]["enum"]),
        )
        self.assertEqual(1, design_schema["properties"]["task_focus_count"]["const"])
        self.assertIn("interaction_requirements", design_schema["required"])
        self.assertEqual(
            "formula_input",
            _design()["interaction_requirements"]["response_kind"],
        )
        self.assertEqual(2, design_schema["properties"]["student_actions"]["properties"]["supporting"]["maxItems"])
        self.assertEqual(1, design_schema["properties"]["language_surface"]["properties"]["named_characters"]["maxItems"])
        self.assertNotIn(
            "formal_writing",
            design_schema["properties"]["difficulty_alignment"]["properties"]["difficulty_source"]["enum"],
        )

    def test_prompt_explains_child_surface_rules_and_semantic_review_boundary(self) -> None:
        prompt = (PROJECT_ROOT / "learning_system/prompts/question_candidate_batch.v1.md").read_text(encoding="utf-8")
        contract = json.loads(
            (PROJECT_ROOT / "learning_system/agent_contracts/question_candidate_batch.v1.json").read_text(encoding="utf-8")
        )

        self.assertIn("不得输出字面量 `\\n`", prompt)
        self.assertIn("每题只设一个清晰的主要任务", prompt)
        self.assertIn("不得把“说明理由 + 检验答案 + 分析错因”固定套在每道题上", prompt)
        self.assertIn("interaction_schema", prompt)
        self.assertIn("interaction_requirements", prompt)
        self.assertIn("当前孩子端不支持拖拽、自由画图或连线作答", prompt)
        self.assertIn("禁止 Markdown 表格、代码围栏、反引号", prompt)
        self.assertIn("不得把“理由、说明、依据、过程、错因、检验”做成填空字段", prompt)
        self.assertIn("一行简洁的 Unicode 纯文本数轴", prompt)
        self.assertIn("独立 semantic QA", prompt)
        self.assertIn("结构字段是供后续语义审查的证据，不是自我勾选通过", prompt)
        self.assertIn("child_surface_design_schema", contract)

    def test_literal_newline_escape_is_blocked_but_real_newline_is_allowed(self) -> None:
        self.assertIn(
            "child_prompt_contains_literal_newline_escape",
            _finding_codes(_item("第一行\\n第二行")),
        )
        self.assertNotIn(
            "child_prompt_contains_literal_newline_escape",
            _finding_codes(_item("第一行\n第二行")),
        )

    def test_visual_gate_uses_declared_delivery_not_prompt_keyword_matching(self) -> None:
        missing_visual = _design()
        missing_visual["visual_support"] = {
            "mode": "not_needed",
            "prompt_depends_on_visual": True,
            "asset_ref": "",
            "inline_visual": "",
        }
        self.assertIn(
            "child_surface_visual_dependency_without_delivery",
            _finding_codes(_item("判断两条线的位置关系。"), missing_visual),
        )

        inline_visual = _design()
        inline_visual["visual_support"] = {
            "mode": "inline_in_prompt",
            "prompt_depends_on_visual": True,
            "asset_ref": "",
            "inline_visual": "A---O---B",
        }
        self.assertNotIn(
            "child_surface_visual_dependency_without_delivery",
            _finding_codes(_item("如图：A---O---B。判断 O 的位置。"), inline_visual),
        )

    def test_external_visual_must_come_from_trusted_plan_resources(self) -> None:
        design = _design()
        design["visual_support"] = {
            "mode": "external_asset",
            "prompt_depends_on_visual": True,
            "asset_ref": "VIS-number-line-01",
            "inline_visual": "",
        }

        self.assertIn(
            "child_surface_external_visual_pipeline_not_ready",
            _finding_codes(_item(), design),
        )
        self.assertIn(
            "child_surface_external_visual_pipeline_not_ready",
            _finding_codes(
                _item(),
                design,
                plan=_plan(visual_resources=[{"asset_ref": "VIS-number-line-01"}]),
            ),
        )

    def test_fixed_explain_verify_error_bundle_is_blocked_by_action_structure(self) -> None:
        design = _design()
        design["student_actions"] = {
            "primary": "diagnose_error",
            "supporting": ["explain_core_relation", "verify"],
        }

        self.assertIn(
            "child_surface_fixed_explain_verify_error_bundle",
            _finding_codes(_item("完成任务。"), design),
        )

    def test_distractors_and_difficulty_require_structural_evidence(self) -> None:
        design = _design()
        design["distractor_design"] = {
            "distractors": [
                {
                    "information": "商店离学校 800 米",
                    "relevance": "obviously_unrelated",
                    "why_plausible": "",
                }
            ]
        }
        design["difficulty_alignment"]["difficulty_source"] = "formal_writing"

        codes = _finding_codes(_item(), design)
        self.assertIn("child_surface_distractor_without_plausible_relevance", codes)
        self.assertIn("child_surface_pseudo_difficulty_source", codes)

    def test_action_control_feasibility_is_not_decided_by_prompt_phrase_matching(self) -> None:
        for prompt in (
            "请把点 A 拖到数轴上的 -3。",
            "请在下面的数轴上画出移动过程。",
            "请把每个式子与对应结果连线。",
        ):
            with self.subTest(prompt=prompt):
                self.assertNotIn(
                    "child_surface_unsupported_interaction",
                    _finding_codes(_item(prompt), _design()),
                )

    def test_interaction_schema_must_use_current_child_prompt_contract(self) -> None:
        item = _item()
        item["interaction_schema"]["type"] = "drag_drop"
        self.assertIn(
            "child_surface_invalid_interaction_schema",
            _finding_codes(item, _design()),
        )

    def test_prompt_task_count_is_not_inferred_by_regex(self) -> None:
        item = _item("请完成三项：\n1. 列式。\n2. 计算。\n3. 检验。")
        codes = _finding_codes(item, _design())
        self.assertNotIn("child_surface_prompt_has_too_many_explicit_tasks", codes)
        self.assertNotIn("child_surface_prompt_deliverable_count_mismatch", codes)

    def test_answer_format_must_match_interaction_explanation_control(self) -> None:
        item = _item()
        item["interaction_schema"] = _interaction_schema(
            allow_explanation=False,
            requires_explanation=False,
        )
        self.assertIn(
            "child_surface_answer_format_requires_missing_explanation_control",
            _finding_codes(item, _design()),
        )

    def test_inline_visual_must_be_present_in_prompt(self) -> None:
        design = _design()
        design["visual_support"] = {
            "mode": "inline_in_prompt",
            "prompt_depends_on_visual": True,
            "asset_ref": "",
            "inline_visual": "0---1---2",
        }
        self.assertIn(
            "child_surface_inline_visual_missing_from_prompt",
            _finding_codes(_item("根据数轴判断位置。"), design),
        )

    def test_writing_burden_cannot_understate_actual_control_inputs(self) -> None:
        design = _design()
        design["writing_burden"]["estimated_response_lines"] = 1
        self.assertIn(
            "child_surface_writing_burden_understates_control",
            _finding_codes(_item(), design),
        )

    def test_single_choice_plus_short_explanation_can_use_one_written_line(self) -> None:
        item = _item("选择正确结论，并用一句话说明理由。")
        item["interaction_schema"] = _interaction_schema(
            interaction_type="single_choice",
            allow_explanation=True,
            requires_explanation=True,
        )
        item["interaction_schema"]["choices"] = [
            {"id": "A", "label": "结论 A"},
            {"id": "B", "label": "结论 B"},
        ]
        design = _design()
        design["interaction_requirements"] = {
            "response_kind": "select_one",
            "actions": [],
            "minimum_selections": 1,
            "maximum_selections": 1,
        }
        design["writing_burden"]["estimated_response_lines"] = 1

        self.assertNotIn(
            "child_surface_writing_burden_understates_control",
            _finding_codes(item, design),
        )

    def test_inline_fill_blanks_share_one_written_line(self) -> None:
        interaction = _interaction_schema(
            interaction_type="fill_blank",
            allow_explanation=True,
            requires_explanation=True,
        )
        interaction["placeholder"] = ""
        interaction["fields"] = [
            {"id": "left", "label": "左端", "placeholder": "", "prefix": "", "suffix": ""},
            {"id": "middle", "label": "中间", "placeholder": "", "prefix": "", "suffix": ""},
            {"id": "right", "label": "右端", "placeholder": "", "prefix": "", "suffix": ""},
        ]

        self.assertEqual(2, _minimum_written_response_lines(interaction))

    def test_optional_explanation_does_not_increase_minimum_written_lines(self) -> None:
        interaction = _interaction_schema(
            interaction_type="formula_input",
            allow_explanation=True,
            requires_explanation=False,
        )

        self.assertEqual(1, _minimum_written_response_lines(interaction))

    def test_solution_steps_and_simple_answer_have_bounded_length(self) -> None:
        item = _item()
        item["solution_steps"] = [f"第 {index} 步。" for index in range(1, 7)]
        self.assertIn(
            "child_surface_solution_steps_too_many",
            _finding_codes(item, _design()),
        )

        item = _item()
        item["standard_answer"] = "说明。" * 250
        self.assertIn(
            "child_surface_standard_answer_too_long",
            _finding_codes(item, _design()),
        )

    def test_semantic_language_attestation_requires_independent_review_boundary(self) -> None:
        design = _design()
        design["language_surface"].pop("semantic_review_boundary")
        self.assertIn(
            "child_surface_missing_independent_semantic_review_boundary",
            _finding_codes(_item(), design),
        )

    def test_normalization_preserves_child_surface_design_for_later_review(self) -> None:
        design = _design()
        normalized = _normalize_model_item(
            {"item": _item(), "child_surface_design": design},
            plan=_plan(),
            requirement=_requirement(),
            generation_attempt=1,
            previous_rejection_codes=[],
        )

        self.assertEqual(design, normalized["child_surface_design"])
        self.assertEqual(_item()["interaction_schema"], normalized["interaction_schema"])
        self.assertEqual("M-TEST", normalized["node_id"])
        self.assertEqual("L3", normalized["difficulty"])


if __name__ == "__main__":
    unittest.main()
