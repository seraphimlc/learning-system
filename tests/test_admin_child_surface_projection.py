from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from learning_system import child_prompt, question_bank
from learning_system.admin.question_generation import (
    _child_surface_findings,
    _normalize_model_item,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _interaction_schema(
    *,
    interaction_type: str = "formula_input",
    allow_explanation: bool = False,
) -> dict:
    return {
        "schema_version": "2026-07-17.question-interaction.v2",
        "type": interaction_type,
        "title": "写下答案",
        "allow_explanation": allow_explanation,
        "requires_explanation": False,
        "explanation_label": "补充说明" if allow_explanation else "",
        "fields": [],
        "choices": [],
        "formula_label": "算式或答案" if interaction_type == "formula_input" else "",
        "placeholder": "写下结果" if interaction_type in {"short_text", "formula_input"} else "",
    }


def _item(prompt: str = "计算 3+4，写出结果。") -> dict:
    return {
        "id": "CAND-child-projection",
        "node_id": "M-G7-NUMBER-LINE",
        "prompt": prompt,
        "prompt_format": child_prompt.CHILD_PROMPT_FORMAT,
        "answer_format": "填写一个结果",
        "interaction_schema": _interaction_schema(),
        "standard_answer": "7",
        "expected_answer": "7",
        "accepted_alternatives": [],
        "rubric": ["结果正确。"],
        "solution_steps": ["3+4=7。"],
        "required_evidence": ["完成核心计算"],
        "key_score_points": [
            {
                "key": "final_conclusion",
                "points": 10,
                "evidence": "结果为 7。",
                "mastery_dimension": "final_conclusion",
            }
        ],
        "target_error_tags": ["calculation"],
        "rollback_candidates": [],
        "estimated_minutes": 2,
        "evidence_goal": "完成核心计算",
        "math_core_signature": "child-projection-test",
        "design_rationale": "用一个短任务验证孩子端投影合同。",
    }


def _design() -> dict:
    return {
        "task_focus_count": 1,
        "primary_task": "完成一个核心数学任务",
        "child_deliverables": ["一个结果"],
        "backend_evidence_targets": ["完成核心计算"],
        "student_actions": {
            "primary": "compute_or_solve",
            "supporting": [],
        },
        "interaction_requirements": {
            "response_kind": "formula_input",
            "actions": [],
        },
        "writing_burden": {
            "burden_level": "light",
            "estimated_response_lines": 1,
            "why_necessary": "一行结果足以判断。",
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
            "short_explanation_requests": 0,
        },
        "distractor_design": {"distractors": []},
        "difficulty_alignment": {
            "target_difficulty": "L2",
            "diagnostic_breakpoint": "能否完成一个核心数学动作",
            "difficulty_source": "mathematical_structure",
        },
    }


def _requirement() -> dict:
    return {
        "question_requirement_id": "REQ-child-projection",
        "slot_id": "M-G7-NUMBER-LINE:number_line_reference_frame:01",
        "node_id": "M-G7-NUMBER-LINE",
        "family_id": "number_line_reference_frame",
        "difficulty": "L2",
        "evidence_goal": "完成核心计算",
        "must_include": ["核心计算"],
        "support_only": False,
        "not_for_activation": False,
        "exclude_from_coverage": False,
        "secondary_nodes": [],
    }


def _plan(*, visual_resources: list[object] | None = None) -> dict:
    return {
        "design_brief_id": "BRIEF-child-projection",
        "node_id": "M-G7-NUMBER-LINE",
        "family_id": "number_line_reference_frame",
        "bounded_candidate_packet": {
            "visual_resources": visual_resources or [],
            "family_plan_entry": {"required_evidence": ["完成核心计算"]},
        },
    }


def _finding_codes(
    item: dict,
    design: dict,
    *,
    plan: dict | None = None,
) -> set[str]:
    return {
        finding["code"]
        for finding in _child_surface_findings(
            item,
            model_output={"item": item, "child_surface_design": design},
            plan=plan or _plan(),
            requirement=_requirement(),
        )
    }


class AdminChildSurfaceProjectionTests(unittest.TestCase):
    def test_generation_contract_requires_structured_interaction_requirements(self) -> None:
        single = json.loads(
            (PROJECT_ROOT / "learning_system/agent_contracts/question_candidate.v1.json").read_text(encoding="utf-8")
        )
        batch = json.loads(
            (PROJECT_ROOT / "learning_system/agent_contracts/question_candidate_batch.v1.json").read_text(encoding="utf-8")
        )
        single_design = single["response_schema"]["properties"]["child_surface_design"]
        batch_design = batch["child_surface_design_schema"]

        for design_schema in (single_design, batch_design):
            self.assertIn("interaction_requirements", design_schema["required"])
            self.assertIn("interaction_requirements", design_schema["properties"])

    def test_missing_structured_interaction_requirements_fails_closed(self) -> None:
        design = _design()
        design.pop("interaction_requirements")

        self.assertIn(
            "child_surface_missing_interaction_requirements",
            _finding_codes(_item(), design),
        )

    def test_generation_gate_calls_canonical_child_surface_projection(self) -> None:
        item = _item()
        design = _design()
        projection_error = child_prompt.ChildPromptContractError(
            ["prompt_interaction:mismatch"]
        )

        with mock.patch.object(
            question_bank,
            "canonical_child_surface_projection",
            side_effect=projection_error,
        ) as project:
            codes = _finding_codes(item, design)

        project.assert_called_once()
        self.assertIn("child_surface_projection_failed", codes)

    def test_structured_control_and_task_contract_mismatch_is_blocked(self) -> None:
        item = _item("完成下面的任务，并提交你的选择。")
        item["interaction_schema"] = _interaction_schema(
            interaction_type="formula_input"
        )
        design = _design()
        design["student_actions"] = {
            "primary": "compare_or_classify",
            "supporting": [],
        }
        design["interaction_requirements"] = {
            "response_kind": "select_one",
            "minimum_selections": 1,
            "maximum_selections": 1,
        }

        codes = _finding_codes(item, design)

        self.assertIn("child_surface_interaction_action_mismatch", codes)

    def test_markdown_table_requires_supported_projection_or_blocks(self) -> None:
        item = _item(
            "| 数 | 对应位置 |\n"
            "| --- | --- |\n"
            "| -2 | 原点左侧 |\n"
            "请填写表中这个数到原点的距离。"
        )
        design = _design()
        with self.assertRaises(child_prompt.ChildPromptContractError) as caught:
            question_bank.canonical_child_surface_projection(item)

        self.assertIn("prompt:markdown_table_forbidden", caught.exception.errors)
        self.assertIn(
            "child_surface_projection_failed",
            _finding_codes(item, design),
        )

    def test_structured_direct_manipulation_task_requires_executable_control(self) -> None:
        item = _item("完成题面指定操作后，填写你得到的结果。")
        design = _design()
        design["interaction_requirements"] = {
            "response_kind": "direct_manipulation",
            "actions": [
                {"action": "move", "target": "number_line_point"},
                {"action": "draw", "target": "question_visual"},
            ],
        }

        codes = _finding_codes(item, design)

        self.assertIn("child_surface_unrenderable_interaction_requirement", codes)

    def test_direct_actions_cannot_hide_behind_a_plain_input_control(self) -> None:
        design = _design()
        design["interaction_requirements"] = {
            "response_kind": "formula_input",
            "actions": [{"action": "draw", "target": "number_line"}],
        }

        self.assertIn(
            "child_surface_unrenderable_interaction_requirement",
            _finding_codes(_item(), design),
        )

    def test_selection_bounds_must_match_control_and_choice_count(self) -> None:
        item = _item("选择正确答案。")
        item["interaction_schema"] = _interaction_schema(interaction_type="single_choice")
        item["interaction_schema"]["choices"] = [
            {"id": "A", "label": "甲"},
            {"id": "B", "label": "乙"},
        ]
        design = _design()
        design["interaction_requirements"] = {
            "response_kind": "select_one",
            "actions": [],
            "minimum_selections": 0,
            "maximum_selections": 8,
        }

        self.assertIn(
            "child_surface_selection_contract_invalid",
            _finding_codes(item, design),
        )

    def test_external_asset_is_bound_to_question_visual_or_fails_closed(self) -> None:
        asset_ref = "trusted-visual:number-line:001"
        visual_resource = {
            "asset_ref": asset_ref,
            "question_visual": {
                "scene_type": "number_line",
                "alt_text": "一条标有原点和两个点的数轴",
                "long_description": "数轴从负三到正三，点 A 位于负二。",
                "scene": {
                    "min": -3,
                    "max": 3,
                    "step": 1,
                    "points": [{"id": "A", "value": -2}],
                },
            },
        }
        plan = _plan(visual_resources=[visual_resource])
        design = _design()
        design["visual_support"] = {
            "mode": "external_asset",
            "prompt_depends_on_visual": True,
            "asset_ref": asset_ref,
            "inline_visual": "",
        }
        output = {"item": _item(), "child_surface_design": design}

        normalized = _normalize_model_item(
            output,
            plan=plan,
            requirement=_requirement(),
            generation_attempt=1,
            previous_rejection_codes=[],
        )
        codes = _finding_codes(normalized, design, plan=plan)
        bound_visual = normalized.get("question_visual")

        bound = (
            isinstance(bound_visual, dict)
            and bound_visual == visual_resource["question_visual"]
        )
        failed_closed = "child_surface_external_visual_pipeline_not_ready" in codes
        self.assertTrue(bound or failed_closed)


if __name__ == "__main__":
    unittest.main()
