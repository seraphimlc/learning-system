from __future__ import annotations

import unittest

from learning_system.question_production_skills import (
    CandidateGenerationSkill,
    BriefGenerationSkill,
    QFDesignSkill,
    RESPONSE_MODES,
    SlotDesignSkill,
    ValidationResult,
    build_question_production_skills,
    validate_candidate,
    validate_qf,
    build_model_question_production_skills,
)


class QuestionProductionSkillsTests(unittest.TestCase):
    @staticmethod
    def _valid_brief_v2(response_mode="short_answer"):
        encoding = {
            "single_choice": "choice_text",
            "multi_choice": "choice_text",
            "fill_blank": "field_text",
            "short_answer": "response_text",
        }[response_mode]
        return {
            "schema_version": "brief-design.v2",
            "brief_id": "brief-1",
            "node_id": "N-1",
            "qf_id": "qf-1",
            "slot_id": "slot-1",
            "task": {"task_type": "reasoning", "response_mode": response_mode},
            "mechanism": {
                "type": "comparison",
                "purpose": "比较两个对象的关系",
                "steps": [{
                    "id": "step-1",
                    "purpose": "确定比较对象",
                    "input": "题面给出的两个对象",
                    "student_action": "比较对象关系",
                    "output": "比较结论",
                    "success_condition": "结论与定义一致",
                }],
                "completion_condition": "完成比较并给出唯一结论",
            },
            "parameter_model": {
                "variables": [
                    {"name": "task_variant", "role": "固定题面变体", "type": "categorical", "domain": "唯一变体"},
                    {"name": "a", "role": "第一个对象", "type": "integer", "domain": "1至9的整数"},
                ],
                "constraints": ["两个对象必须可比较"],
                "construction_steps": ["先选对象", "再确定关系", "最后检查唯一性"],
            },
            "evidence_plan": {"items": [{
                "evidence_id": "e1",
                "student_action": "比较",
                "observable_evidence": "写出比较结论",
                "capture_mode": response_mode,
                "required": True,
            }]},
            "answer_plan": {
                "encoding": encoding,
                "response_field_count": 1,
                "reference_answer_count": 1,
                "field_mapping": {
                    "prompt": "完整题干",
                    "choices": "选择题选项，否则固定为空数组",
                    "answer": "参考答案数组",
                    "rubric": "评分证据",
                    "solution_steps": "参考步骤",
                },
                "answer_evidence": ["比较结论"],
                "solution_structure": ["识别对象", "完成比较", "给出结论"],
            },
            "instance_acceptance": {
                "must_hold": ["信息充分", "答案唯一"],
                "uniqueness_check": ["重新推导答案"],
                "reject_if": ["答案可直接看出", "信息不足"],
            },
        }

    def test_brief_schema_requires_a_substantive_content_blueprint(self):
        from learning_system.question_production_skills import LIVE_SCHEMAS

        schema = LIVE_SCHEMAS["brief-design.v1"]
        self.assertIn("content_blueprint", schema["required"])
        blueprint = schema["properties"]["content_blueprint"]
        self.assertEqual(
            {
                "target_concept",
                "mechanism_type",
                "problem_mechanism",
                "student_actions",
                "misconception_mechanism",
                "parameter_pattern",
                "answer_derivation",
                "good_instance_pattern",
                "bad_instance_pattern",
            },
            set(blueprint["properties"]),
        )
        self.assertEqual(
            {"vary", "must_hold", "avoid", "generation_steps"},
            set(blueprint["properties"]["parameter_pattern"]["properties"]),
        )
        self.assertIn("candidate_contract", schema["required"])
        self.assertEqual(
            {
                "response_mode",
                "field_mapping",
                "answer_encoding",
                "response_field_count",
                "reference_answer_count",
                "answer_requirements",
                "choice_requirements",
                "prompt_requirements",
            },
            set(schema["properties"]["candidate_contract"]["properties"]),
        )
        self.assertIn("mechanism_type", blueprint["properties"])

    def test_brief_v2_schema_is_an_executable_plan_not_a_text_checklist(self):
        from learning_system.question_production_skills import LIVE_SCHEMAS

        schema = LIVE_SCHEMAS["brief-design.v2"]
        self.assertEqual(
            {"schema_version", "brief_id", "node_id", "qf_id", "slot_id", "task", "mechanism", "parameter_model", "evidence_plan", "answer_plan", "instance_acceptance"},
            set(schema["required"]),
        )
        self.assertEqual(
            {"type", "purpose", "steps", "completion_condition"},
            set(schema["properties"]["mechanism"]["properties"]),
        )
        self.assertEqual(
            {"variables", "constraints", "construction_steps"},
            set(schema["properties"]["parameter_model"]["properties"]),
        )
        self.assertEqual(
            {"items"},
            set(schema["properties"]["evidence_plan"]["properties"]),
        )
        self.assertEqual(
            {"encoding", "response_field_count", "reference_answer_count", "field_mapping", "answer_evidence", "solution_structure"},
            set(schema["properties"]["answer_plan"]["properties"]),
        )

    def test_brief_v2_validator_rejects_multiple_mechanisms_and_missing_field_mapping(self):
        from learning_system.question_production_skills import validate_brief

        result = validate_brief(
            {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"},
            {
                "schema_version": "brief-design.v2",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "qf_id": "qf-1",
                "slot_id": "slot-1",
                "task": {"task_type": "reasoning", "response_mode": "short_answer"},
                "mechanism": {"type": "综合：方程或估算", "purpose": "完成任务", "steps": [{"id": "s1", "purpose": "检查", "input": "输入", "student_action": "判断", "output": "结果", "success_condition": "成立"}], "completion_condition": "完成"},
                "parameter_model": {"variables": [{"name": "x", "role": "候选值", "type": "integer", "domain": "范围"}], "constraints": ["唯一"], "construction_steps": ["生成"]},
                "evidence_plan": {"items": [{"evidence_id": "e1", "student_action": "解释", "observable_evidence": "说明关系", "capture_mode": "short_answer", "required": True}]},
                "answer_plan": {"encoding": "response_text", "response_field_count": 1, "reference_answer_count": 1, "field_mapping": {}, "answer_evidence": ["解释"], "solution_structure": ["先判断"]},
                "instance_acceptance": {"must_hold": ["唯一"], "uniqueness_check": ["检查"], "reject_if": ["多解"]},
            },
        )

        self.assertEqual("rejected", result.status)
        self.assertIn("brief_v2_mechanism_type_invalid", result.error_codes())
        self.assertIn("brief_v2_field_mapping_prompt_invalid", result.error_codes())

    def test_brief_v2_validator_accepts_a_complete_execution_plan(self):
        from learning_system.question_production_skills import validate_brief

        brief = self._valid_brief_v2()
        result = validate_brief(
            {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"},
            brief,
        )

        self.assertEqual("passed", result.status)
        self.assertEqual([], result.errors)

    def test_brief_v2_validator_requires_task_variant(self):
        from learning_system.question_production_skills import validate_brief

        brief = self._valid_brief_v2()
        brief["parameter_model"]["variables"] = [
            variable for variable in brief["parameter_model"]["variables"]
            if variable["name"] != "task_variant"
        ]

        result = validate_brief(
            {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"},
            brief,
        )

        self.assertEqual("rejected", result.status)
        self.assertIn("brief_v2_task_variant_missing", result.error_codes())

    def test_brief_v2_validator_requires_required_evidence_to_match_response_mode(self):
        from learning_system.question_production_skills import validate_brief

        brief = self._valid_brief_v2()
        brief["evidence_plan"]["items"][0]["capture_mode"] = "fill_blank"

        result = validate_brief(
            {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"},
            brief,
        )

        self.assertEqual("rejected", result.status)
        self.assertIn("brief_v2_evidence_capture_mode_mismatch", result.error_codes())

    def test_live_brief_generator_requests_v2_and_its_output_passes_the_real_validator(self):
        from learning_system.question_production_skills import build_model_question_production_skills

        class FakeModel:
            def __init__(self):
                self.schemas = []

            def generate_json(self, prompt, schema):
                self.schemas.append(schema)
                return QuestionProductionSkillsTests._valid_brief_v2()

        model = FakeModel()
        skills = build_model_question_production_skills(model)
        payload = {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"}
        output = skills["brief_generation"].run(payload)[0]
        result = skills["brief_generation"].validate(payload, output)

        self.assertEqual(["brief-design.v2"], model.schemas)
        self.assertEqual("passed", result.status)

    def test_v2_brief_contract_can_drive_candidate_contract_validation(self):
        from learning_system.question_production_skills import validate_candidate

        brief = self._valid_brief_v2("multi_choice")
        result = validate_candidate(
            {
                "candidate_id": "brief-1:candidate",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "brief": brief,
            },
            {
                "candidate_id": "brief-1:candidate",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "content": {
                    "schema_version": "question-content.v1",
                    "task_type": "reasoning",
                    "response_mode": "multi_choice",
                    "prompt": "选择所有符合条件的选项。",
                    "choices": ["甲", "乙", "丙"],
                    "answer": ["甲"],
                    "rubric": [],
                    "solution_steps": [],
                },
            },
        )

        self.assertEqual("passed", result.status)

    def test_brief_validator_rejects_answer_contract_incompatible_with_response_mode(self):
        from learning_system.question_production_skills import validate_brief

        result = validate_brief(
            {"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"},
            {
                "brief_id": "brief-1",
                "node_id": "N-1",
                "qf_id": "qf-1",
                "slot_id": "slot-1",
                "task": {"task_type": "reasoning", "response_mode": "fill_blank"},
                "content_blueprint": {
                    "target_concept": "概念",
                    "mechanism_type": "comparison",
                    "problem_mechanism": "机制",
                    "student_actions": ["动作"],
                    "misconception_mechanism": "误解",
                    "parameter_pattern": {"vary": ["变化"], "must_hold": ["关系"], "avoid": ["排除"], "generation_steps": ["先选参数"]},
                    "answer_derivation": "推导",
                    "good_instance_pattern": "有效",
                    "bad_instance_pattern": "无效",
                },
                    "candidate_contract": {
                    "response_mode": "fill_blank",
                    "answer_encoding": "choice_text",
                    "field_mapping": {"prompt": "题干", "choices": "选项", "answer": "答案", "rubric": "评分", "solution_steps": "过程"},
                    "response_field_count": 1,
                    "reference_answer_count": 1,
                    "answer_requirements": ["答案必须是选项文本集合"],
                    "choice_requirements": ["正确集合唯一"],
                    "prompt_requirements": ["题干完整"],
                },
                "construction": {},
                    "answer_contract": {"grading_mode": "fixed_answer", "answer_shape": "选项编号", "field_count": 1},
                "difficulty_contract": {},
                "self_check": ["ok"],
            },
        )

        self.assertEqual("rejected", result.status)
        self.assertIn("brief_candidate_contract_answer_encoding_invalid", result.error_codes())

    def test_semantic_review_contract_declares_root_cause_and_recovery(self):
        from learning_system.question_production_skills import LIVE_SCHEMAS, validate_semantic_review

        schema = LIVE_SCHEMAS["semantic-review.v1"]
        self.assertEqual(
            {
                "decision",
                "score",
                "issues",
                "repair_instructions",
                "root_cause_stage",
                "recovery_action",
                "recovery_stage",
                "confidence",
            },
            set(schema["properties"]),
        )
        review = {
            "decision": "rejected",
            "score": 4,
            "issues": ["Brief 与 Candidate 合同冲突"],
            "repair_instructions": ["回退重生成 Brief"],
            "root_cause_stage": "brief_generation",
            "recovery_action": "regenerate_from_stage",
            "recovery_stage": "brief_generation",
            "confidence": 0.95,
        }
        result = validate_semantic_review(
            {"stage": "candidate_generation"},
            [{"candidate_id": "candidate-1"}],
            review,
        )
        self.assertEqual("rejected", result.status)
        self.assertEqual("brief_generation", result.target_stage)

    def test_semantic_review_rejects_upstream_recovery_point_after_current_stage(self):
        from learning_system.question_production_skills import validate_semantic_review

        review = {
            "decision": "rejected",
            "score": 4,
            "issues": ["invalid recovery"],
            "repair_instructions": ["do not move downstream"],
            "root_cause_stage": "brief_generation",
            "recovery_action": "regenerate_from_stage",
            "recovery_stage": "candidate_generation",
            "confidence": 0.9,
        }
        result = validate_semantic_review(
            {"stage": "brief_generation"},
            [{"brief_id": "brief-1"}],
            review,
        )
        self.assertEqual("rejected", result.status)
        self.assertIn("semantic_review_recovery_stage_invalid", result.error_codes())

    def test_candidate_validator_enforces_the_parent_candidate_contract(self):
        from learning_system.question_production_skills import validate_candidate

        result = validate_candidate(
            {
                "candidate_id": "brief-1:candidate",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "brief": {
                    "task": {"response_mode": "multi_choice"},
                    "candidate_contract": {
                        "response_mode": "multi_choice",
                        "answer_encoding": "choice_text",
                        "response_field_count": 1,
                        "reference_answer_count": 2,
                    },
                },
            },
            {
                "candidate_id": "brief-1:candidate",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "content": {
                    "schema_version": "question-content.v1",
                    "task_type": "reasoning",
                    "response_mode": "multi_choice",
                    "prompt": "选择所有正确选项。",
                    "choices": ["A", "B", "C"],
                    "answer": ["A"],
                    "rubric": [],
                    "solution_steps": [],
                },
            },
        )

        self.assertEqual("rejected", result.status)
        self.assertIn("candidate_contract_reference_answer_count_mismatch", result.error_codes())

    def test_live_model_has_one_reviewer_route_per_production_layer(self):
        from unittest.mock import patch
        from learning_system.question_production_skills import ModelRouterQuestionProductionModel

        class FakeRoute:
            enabled = True
            def __init__(self, agent_key):
                self.agent_key = agent_key

        with patch("learning_system.question_production_skills.model_router.question_designer_route", return_value=FakeRoute("question_designer_agent")), \
             patch("learning_system.question_production_skills.model_router.slot_brief_designer_route", return_value=FakeRoute("slot_brief_designer_agent")), \
             patch("learning_system.question_production_skills.model_router.qf_reviewer_route", return_value=FakeRoute("qf_reviewer_agent")), \
             patch("learning_system.question_production_skills.model_router.slot_reviewer_route", return_value=FakeRoute("slot_reviewer_agent")), \
             patch("learning_system.question_production_skills.model_router.brief_reviewer_route", return_value=FakeRoute("brief_reviewer_agent")), \
             patch("learning_system.question_production_skills.model_router.candidate_reviewer_route", return_value=FakeRoute("candidate_reviewer_agent")):
            model = ModelRouterQuestionProductionModel()

        self.assertEqual(
            {
                "qf_design": "qf_reviewer_agent",
                "slot_design": "slot_reviewer_agent",
                "brief_generation": "brief_reviewer_agent",
                "candidate_generation": "candidate_reviewer_agent",
            },
            {stage: route.agent_key for stage, route in model.reviewer_routes.items()},
        )

    def test_route_statuses_expose_each_production_reviewer(self):
        from learning_system import model_router

        routes = model_router.configured_route_statuses()

        self.assertEqual("qf_reviewer_agent", routes["qf_review"]["agent_key"])
        self.assertEqual("slot_reviewer_agent", routes["slot_review"]["agent_key"])
        self.assertEqual("brief_reviewer_agent", routes["brief_review"]["agent_key"])
        self.assertEqual("candidate_reviewer_agent", routes["candidate_review"]["agent_key"])

    def test_live_design_schema_constrains_response_mode_to_machine_values(self):
        from learning_system.question_production_skills import LIVE_SCHEMAS

        slot_mode = LIVE_SCHEMAS["slot-design.v1"]["properties"]["slots"]["items"]["properties"]["response_mode"]
        qf_modes = LIVE_SCHEMAS["qf-design.v1"]["properties"]["qfs"]["items"]["properties"]["allowed_response_modes"]["items"]

        self.assertEqual(sorted(RESPONSE_MODES), sorted(slot_mode["enum"]))
        self.assertEqual(sorted(RESPONSE_MODES), sorted(qf_modes["enum"]))

    def test_candidate_schema_requires_explicit_short_answer_contract_fields(self):
        from learning_system.question_production_skills import LIVE_SCHEMAS

        schema = LIVE_SCHEMAS["question-content.v1"]
        self.assertIn("rubric", schema["required"])
        self.assertIn("solution_steps", schema["required"])

    def test_model_skill_factory_uses_prompted_skills_without_calling_a_provider_here(self):
        class FakeModel:
            def generate_json(self, prompt, schema):
                if schema == "qf-design.v1":
                    return {"qf_id": "qf-1", "node_id": "N-1", "name": "测试 QF", "task_type": "reasoning", "measurement_intent": "测量", "independent_reason": "独立", "allowed_response_modes": ["single_choice"], "scope": {}, "required_evidence": ["answer"], "reject_if": ["机械"]}
                if schema == "slot-design.v1":
                    return {"slot_id": "slot-1", "node_id": "N-1", "qf_id": "qf-1", "task_type": "reasoning", "response_mode": "single_choice", "structure": "test", "measurement_target": "测量", "conditions": ["条件"], "error_targets": ["错因"], "minimum_quality": ["非机械"], "reject_if": ["简单"]}
                if schema == "brief-design.v2":
                    return QuestionProductionSkillsTests._valid_brief_v2()
                return {"schema_version": "question-content.v1", "task_type": "reasoning", "response_mode": "single_choice", "prompt": "选择正确答案。", "choices": ["A", "B"], "answer": ["A"]}

        skills = build_model_question_production_skills(FakeModel())
        node = {"node_id": "N-1", "name": "测试节点"}
        qf = skills["qf_design"].run(node)[0]
        slot = skills["slot_design"].run({"node_id": "N-1", "qf_id": qf["qf_id"], **qf})[0]
        brief = skills["brief_generation"].run({"node_id": "N-1", "qf_id": qf["qf_id"], "slot_id": slot["slot_id"], **slot})[0]
        candidate = skills["candidate_generation"].run({"node_id": "N-1", "qf_id": qf["qf_id"], "slot_id": slot["slot_id"], "brief_id": brief["brief_id"], **brief})[0]

        self.assertEqual("qf-1", qf["qf_id"])
        self.assertEqual("slot-1", slot["slot_id"])
        self.assertEqual("brief-1", brief["brief_id"])
        self.assertEqual("passed", skills["brief_generation"].validate({"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"}, brief).status)
        self.assertEqual("question-content.v1", candidate["content"]["schema_version"])
    def test_qf_validator_returns_structured_rejection(self):
        result = validate_qf({"node_id": "N-1"}, {"node_id": "N-1"})

        self.assertIsInstance(result, ValidationResult)
        self.assertEqual("rejected", result.status)
        self.assertTrue(result.retry_allowed)
        self.assertEqual("qf_design", result.target_stage)
        self.assertIn("qf_id_missing", result.error_codes())

    def test_candidate_validator_accepts_complete_fixed_answer_content(self):
        result = validate_candidate(
            {"candidate_id": "brief-1:candidate", "brief_id": "brief-1", "node_id": "N-1"},
            {
                "candidate_id": "brief-1:candidate",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "content": {
                    "schema_version": "question-content.v1",
                    "task_type": "calculation",
                    "response_mode": "fill_blank",
                    "prompt": "计算：1 + 1 = ____。",
                    "choices": [],
                    "answer": ["2"],
                },
            },
        )

        self.assertEqual("passed", result.status)
        self.assertEqual([], result.errors)

    def test_candidate_validator_rejects_internal_display_fields_and_bad_fixed_answer(self):
        result = validate_candidate(
            {"candidate_id": "brief-1:candidate", "brief_id": "brief-1", "node_id": "N-1"},
            {
                "candidate_id": "brief-1:candidate",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "content": {
                    "schema_version": "question-content.v1",
                    "task_type": "calculation",
                    "response_mode": "single_choice",
                    "prompt": "选择正确答案。",
                    "choices": ["A", "B"],
                    "answer": ["C"],
                    "interaction_schema": {},
                },
            },
        )

        self.assertEqual("rejected", result.status)
        self.assertIn("candidate_internal_field_forbidden", result.error_codes())
        self.assertIn("candidate_answer_not_in_choices", result.error_codes())

    def test_candidate_validator_rejects_duplicate_multi_choice_answers(self):
        result = validate_candidate(
            {"candidate_id": "candidate-1", "brief_id": "brief-1", "node_id": "N-1"},
            {
                "candidate_id": "candidate-1",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "content": {
                    "schema_version": "question-content.v1",
                    "task_type": "reasoning",
                    "response_mode": "multi_choice",
                    "prompt": "选择所有正确说法。",
                    "choices": ["A", "B", "C"],
                    "answer": ["A", "A"],
                    "rubric": [],
                    "solution_steps": [],
                },
            },
        )

        self.assertEqual("rejected", result.status)
        self.assertIn("candidate_multi_choice_answers_duplicate", result.error_codes())

    def test_candidate_validator_rejects_prompt_that_child_renderer_cannot_display(self):
        result = validate_candidate(
            {"candidate_id": "candidate-1", "brief_id": "brief-1", "node_id": "N-1"},
            {
                "candidate_id": "candidate-1",
                "brief_id": "brief-1",
                "node_id": "N-1",
                "content": {
                    "schema_version": "question-content.v1",
                    "task_type": "calculation",
                    "response_mode": "fill_blank",
                    "prompt": "计算：\\frac{1}{2} = ____。",
                    "choices": [],
                    "answer": ["0.5"],
                    "rubric": [],
                    "solution_steps": [],
                },
            },
        )

        self.assertEqual("rejected", result.status)
        self.assertIn("candidate_prompt_not_renderable", result.error_codes())

    def test_candidate_generator_is_single_item_only(self):
        skills = build_question_production_skills({
            "qf_design": lambda payload: {},
            "slot_design": lambda payload: {},
            "brief_generation": lambda payload: {},
            "candidate_generation": lambda payload: [{}, {}],
        })

        output = skills["candidate_generation"].run({"brief_id": "brief-1", "node_id": "N-1"})
        result = skills["candidate_generation"].validate({"brief_id": "brief-1", "node_id": "N-1"}, output[0])

        self.assertEqual("rejected", result.status)
        self.assertIn("candidate_must_be_single", result.error_codes())

    def test_concrete_skills_use_their_fixed_stage_validators(self):
        qf_skill = QFDesignSkill(lambda payload: {
            "qf_id": "qf-1", "node_id": payload["node_id"], "name": "测试 QF",
            "task_type": "reasoning", "measurement_intent": "测试", "independent_reason": "独立",
            "allowed_response_modes": ["single_choice"], "scope": {},
            "required_evidence": ["answer"], "reject_if": ["机械题"],
        })
        slot_skill = SlotDesignSkill(lambda payload: {
            "slot_id": "slot-1", "node_id": payload["node_id"], "qf_id": payload["qf_id"],
            "task_type": "reasoning", "response_mode": "single_choice", "structure": "test",
            "measurement_target": "测试", "conditions": ["条件"], "error_targets": ["错因"],
            "minimum_quality": ["非机械"], "reject_if": ["简单"],
        })
        brief_skill = BriefGenerationSkill(lambda payload: {
            "brief_id": "brief-1", "node_id": payload["node_id"], "qf_id": payload["qf_id"],
            "slot_id": payload["slot_id"], "task": {"task_type": "reasoning", "response_mode": "single_choice"},
            "content_blueprint": {"target_concept": "测量能力", "mechanism_type": "comparison", "problem_mechanism": "通过比较完成测量", "student_actions": ["比较"], "misconception_mechanism": "混淆比较对象", "parameter_pattern": {"vary": ["数值"], "must_hold": ["答案唯一"], "avoid": ["一眼可见"], "generation_steps": ["先选参数"]}, "answer_derivation": "按定义推导", "good_instance_pattern": "需要比较后作答", "bad_instance_pattern": "直接可见答案"},
            "candidate_contract": {"response_mode": "single_choice", "answer_encoding": "choice_text", "field_mapping": {"prompt": "题干", "choices": "选项", "answer": "答案", "rubric": "评分", "solution_steps": "过程"}, "response_field_count": 1, "reference_answer_count": 1, "answer_requirements": ["引用正确选项文本"], "choice_requirements": ["选项互斥"], "prompt_requirements": ["题干完整"]},
            "construction": {}, "answer_contract": {}, "difficulty_contract": {}, "self_check": ["ok"],
        })

        self.assertEqual("passed", qf_skill.validate({"node_id": "N-1"}, qf_skill.run({"node_id": "N-1"})[0]).status)
        self.assertEqual("passed", slot_skill.validate({"node_id": "N-1", "qf_id": "qf-1"}, slot_skill.run({"node_id": "N-1", "qf_id": "qf-1"})[0]).status)
        self.assertEqual("passed", brief_skill.validate({"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"}, brief_skill.run({"node_id": "N-1", "qf_id": "qf-1", "slot_id": "slot-1"})[0]).status)

    def test_skill_factory_registers_exactly_four_stages(self):
        generators = {stage: lambda payload: {} for stage in ("qf_design", "slot_design", "brief_generation", "candidate_generation")}

        skills = build_question_production_skills(generators)

        self.assertEqual({"qf_design", "slot_design", "brief_generation", "candidate_generation"}, set(skills))
        self.assertIsInstance(skills["qf_design"], QFDesignSkill)
        self.assertIsInstance(skills["slot_design"], SlotDesignSkill)
        self.assertIsInstance(skills["brief_generation"], BriefGenerationSkill)
        self.assertIsInstance(skills["candidate_generation"], CandidateGenerationSkill)


if __name__ == "__main__":
    unittest.main()
