from __future__ import annotations

import unittest

from learning_system.question_production_skills import (
    BRIEF_V2_AUTHORING_CONTRACT,
    build_brief_v2_prompt,
    build_candidate_prompt,
    build_qf_prompt,
    build_semantic_review_prompt,
    build_slot_prompt,
)


class QuestionProductionPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.node = {
            "id": "N-1",
            "name": "测试节点",
            "production_contract": {"scope": {"boundary_rule": "只测当前节点"}},
        }
        self.qf = {
            "qf_id": "qf-1",
            "node_id": "N-1",
            "name": "测试能力家族",
            "measurement_intent": "测量一个独立能力",
        }
        self.slot = {
            "slot_id": "slot-1",
            "node_id": "N-1",
            "qf_id": "qf-1",
            "task_type": "reasoning",
            "response_mode": "short_answer",
            "structure": "呈现一个需要判断的结构",
            "measurement_target": "观察学生的关键动作",
            "conditions": ["信息充分"],
            "error_targets": ["混淆关系"],
            "minimum_quality": ["需要真实决策"],
            "reject_if": ["一眼可见"],
        }
        self.brief = {
            "schema_version": "brief-design.v2",
            "brief_id": "brief-1",
            "node_id": "N-1",
            "qf_id": "qf-1",
            "slot_id": "slot-1",
            "task": {"task_type": "reasoning", "response_mode": "short_answer"},
        }

    def test_generator_prompts_have_business_work_for_each_layer(self):
        prompts = {
            "qf": build_qf_prompt(self.node, previous_qfs=[]),
            "slot": build_slot_prompt(self.node, self.qf, previous_slots=[]),
            "brief": build_brief_v2_prompt(self.node, self.qf, self.slot),
            "candidate": build_candidate_prompt(self.brief, previous_validation_errors=[]),
        }

        self.assertIn("Node 中的能力", prompts["qf"])
        self.assertIn("独立能力盘点", prompts["qf"])
        self.assertIn("可观察的学生动作", prompts["slot"])
        self.assertIn("能承载这些证据的答题形式", prompts["slot"])
        self.assertIn("mechanism", prompts["brief"])
        self.assertIn("parameter_model", prompts["brief"])
        self.assertIn("evidence_plan", prompts["brief"])
        self.assertIn("answer_plan", prompts["brief"])
        self.assertIn("先读取 Brief v2", prompts["candidate"])
        self.assertIn("按 parameter_model.construction_steps", prompts["candidate"])

    def test_brief_v2_prompt_defines_an_executable_plan_not_a_checklist(self):
        prompt = build_brief_v2_prompt(self.node, self.qf, self.slot)

        for marker in (
            "每个 step 必须写清 input、student_action、output、success_condition",
            "每个变量的 name、role、type、domain",
            "学生动作、可观察证据、承载它的 response_mode",
            "answer、rubric、solution_steps",
            "must_hold、uniqueness_check、reject_if",
            "不能写本次 Candidate 的具体数值、具体答案或完整题干",
            "不得自行增加 Slot 未要求的数量、字段或固定实例",
            "逐项标明它对应的 Slot measurement_target 和 error_targets",
            "task_variant",
            "evidence_plan 中每项 required 证据都必须由当前 response_mode 直接采集",
            "must_hold 必须包含 Slot 的最低难度",
        ):
            self.assertIn(marker, prompt)

    def test_candidate_prompt_consumes_v2_sections_and_maps_answer_fields(self):
        prompt = build_candidate_prompt(self.brief, previous_validation_errors=[])

        self.assertIn("mechanism、parameter_model、evidence_plan、answer_plan 和 instance_acceptance", prompt)
        self.assertNotIn("content_blueprint", prompt)
        self.assertIn("choice_text", prompt)
        self.assertIn("field_text", prompt)
        self.assertIn("response_text", prompt)
        self.assertIn("answer 数量必须等于 reference_answer_count", prompt)
        self.assertIn("response_field_count 只描述孩子端实际作答字段", prompt)

    def test_revision_feedback_is_only_injected_when_requested(self):
        revision = {"source_run_id": "PR-SOURCE", "feedback": [{"message": "答案形式冲突"}]}

        normal = build_qf_prompt(self.node, previous_qfs=[])
        revised = build_qf_prompt(self.node, previous_qfs=[], revision_context=revision)
        normal_slot = build_slot_prompt(self.node, self.qf, previous_slots=[])
        revised_slot = build_slot_prompt(self.node, self.qf, previous_slots=[], revision_context=revision)

        self.assertNotIn("本次是结构修订", normal)
        self.assertIn("本次是结构修订", revised)
        self.assertIn("逐条落实每一条反馈", revised)
        self.assertNotIn("本次是结构修订", normal_slot)
        self.assertIn("只使用修订后的上游 QF", revised_slot)

    def test_reviewer_prompts_are_stage_specific_and_not_generator_prompts(self):
        payload = {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1", "brief_id": "brief-1"}
        output = [{"id": "artifact-1"}]
        prompts = {
            stage: build_semantic_review_prompt(stage, payload, output)
            for stage in ("qf_design", "slot_design", "brief_generation", "candidate_generation")
        }

        self.assertIn("QF 专属审查", prompts["qf_design"])
        self.assertIn("Slot 专属审查", prompts["slot_design"])
        self.assertIn("Brief 专属审查", prompts["brief_generation"])
        self.assertIn("Candidate 专属审查", prompts["candidate_generation"])
        self.assertIn("独立复核答案", prompts["candidate_generation"])
        for prompt in prompts.values():
            self.assertIn("只返回 semantic-review.v1", prompt)
            self.assertNotIn("你是本学习系统的数学题目生产模型", prompt)

    def test_v2_brief_reviewer_checks_v2_sections_without_legacy_requirements(self):
        payload = {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"}
        output = [{"schema_version": "brief-design.v2", "brief_id": "brief-1"}]

        prompt = build_semantic_review_prompt("brief_generation", payload, output)

        for marker in (
            "Brief v2",
            "mechanism",
            "parameter_model",
            "evidence_plan",
            "answer_plan",
            "instance_acceptance",
            "围绕该 Slot",
        ):
            self.assertIn(marker, prompt)
        for legacy_marker in (
            "content_blueprint.parameter_pattern",
            "question_shape",
            "required_decisions",
            "candidate_contract",
            "difficulty_contract",
        ):
            self.assertNotIn(legacy_marker, prompt)

    def test_brief_v2_generator_and_reviewer_share_the_same_audit_contract(self):
        generator_prompt = build_brief_v2_prompt(self.node, self.qf, self.slot)
        reviewer_prompt = build_semantic_review_prompt(
            "brief_generation",
            {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"},
            [{"schema_version": "brief-design.v2"}],
        )

        for marker in (
            "task_variant",
            "required 证据都必须由当前 response_mode 直接采集",
            "Brief 只能描述可变参数、关系和推导规则",
            "不得自行增加 Slot 未要求的数量、字段或固定实例",
        ):
            self.assertIn(marker, BRIEF_V2_AUTHORING_CONTRACT)
            self.assertIn(marker, generator_prompt)
            self.assertIn(marker, reviewer_prompt)


if __name__ == "__main__":
    unittest.main()
