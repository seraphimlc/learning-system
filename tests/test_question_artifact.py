import unittest

from learning_system import child_prompt, question_artifact


class QuestionArtifactContractTests(unittest.TestCase):
    def _fill_candidate(self):
        return {
            "schema_version": question_artifact.CANDIDATE_SCHEMA_VERSION,
            "content": {
                "blocks": [
                    {"type": "text", "text": "计算：4.8 + 2.35 × 0.6 = "},
                    {"type": "blank", "field_id": "result"},
                ]
            },
            "task": {"task_type": "calculation", "response_mode": "fill_blank"},
            "interaction_proposal": {
                "controls": [
                    {
                        "id": "result",
                        "control_type": "text_input",
                        "value_type": "decimal",
                        "label": "计算结果",
                        "order": 1,
                        "required": True,
                    }
                ],
                "choices": [],
            },
            "answer_proposal": {
                "grading_mode": "local_fixed_answer",
                "targets": [
                    {
                        "control_id": "result",
                        "answer_type": "decimal",
                        "accepted_values": ["6.21"],
                        "normalization": "decimal",
                    }
                ],
            },
            "authoring_evidence": {"operation_order": "先乘后加"},
            "self_check": ["字段绑定正确"],
        }

    def _choice_candidate(self):
        return {
            "schema_version": question_artifact.CANDIDATE_SCHEMA_VERSION,
            "content": {"blocks": [{"type": "text", "text": "选择正确的改写。"}]},
            "task": {"task_type": "reasoning", "response_mode": "single_choice"},
            "interaction_proposal": {
                "controls": [],
                "choices": [
                    {"id": "A", "label": "3.470", "order": 1},
                    {"id": "B", "label": "3.047", "order": 2},
                ],
            },
            "answer_proposal": {
                "grading_mode": "local_fixed_answer",
                "targets": [{"choice_id": "A"}],
            },
            "authoring_evidence": {},
            "self_check": [],
        }

    def test_fill_candidate_compiles_to_child_surface_and_local_grading(self):
        artifact = question_artifact.compile_question_artifact(
            self._fill_candidate(),
            identity={
                "question_id": "Q-123",
                "node_id": "M-PRE-DECIMAL-OPS",
                "qf_id": "decimal_mixed_calculation",
                "slot_id": "decimal-add-multiply-001",
                "artifact_version": 1,
            },
        )

        self.assertEqual("计算：4.8 + 2.35 × 0.6 =（ ）", artifact["child_surface"]["prompt"])
        self.assertEqual("计算结果", artifact["child_surface"]["interaction_schema"]["fields"][0]["label"])
        self.assertEqual("local_fixed_answer", artifact["grading"]["mode"])
        self.assertEqual("result", artifact["grading"]["targets"][0]["control_id"])
        self.assertNotIn("authoring_evidence", artifact["child_surface"])

        surface = child_prompt.project_child_surface(
            prompt=artifact["child_surface"]["prompt"],
            prompt_format=artifact["child_surface"]["prompt_format"],
            interaction_schema=artifact["child_surface"]["interaction_schema"],
            allow_legacy=False,
        )
        self.assertEqual("计算结果", surface["interaction_schema"]["fields"][0]["label"])

        correct = question_artifact.grade_response(
            artifact,
            {
                "schema_version": question_artifact.RESPONSE_SCHEMA_VERSION,
                "question_id": "Q-123",
                "artifact_version": 1,
                "response": {
                    "schema_version": question_artifact.FIXED_RESPONSE_SCHEMA_VERSION,
                    "type": "fill_blank",
                    "fields": [{"id": "result", "value": "6.210"}],
                },
            },
        )
        self.assertEqual("correct", correct["grading"]["status"])
        self.assertEqual("6.21", correct["grading"]["field_results"][0]["normalized_value"])

        wrong = question_artifact.grade_response(
            artifact,
            {
                "schema_version": question_artifact.RESPONSE_SCHEMA_VERSION,
                "question_id": "Q-123",
                "artifact_version": 1,
                "response": {
                    "schema_version": question_artifact.FIXED_RESPONSE_SCHEMA_VERSION,
                    "type": "fill_blank",
                    "fields": [{"id": "result", "value": "6.12"}],
                },
            },
        )
        self.assertEqual("wrong", wrong["grading"]["status"])

    def test_decimal_normalization_alias_accepts_equivalent_trailing_zeros(self):
        candidate = self._fill_candidate()
        candidate["answer_proposal"]["targets"][0]["normalization"] = "trim_whitespace_and_leading_zeros"
        artifact = question_artifact.compile_question_artifact(
            candidate,
            identity={
                "question_id": "Q-128",
                "node_id": "M-PRE-DECIMAL-OPS",
                "qf_id": "decimal_mixed_calculation",
                "slot_id": "decimal-add-multiply-003",
            },
        )
        result = question_artifact.grade_response(
            artifact,
            {
                "schema_version": question_artifact.RESPONSE_SCHEMA_VERSION,
                "question_id": "Q-128",
                "artifact_version": 1,
                "response": {
                    "schema_version": question_artifact.FIXED_RESPONSE_SCHEMA_VERSION,
                    "type": "fill_blank",
                    "fields": [{"id": "result", "value": "6.210"}],
                },
            },
        )
        self.assertEqual("correct", result["grading"]["status"])

    def test_fill_blank_allows_repeated_correct_values_for_different_blanks(self):
        artifact = question_artifact.compile_question_content(
            {
                "schema_version": "question-content.v1",
                "task_type": "calculation",
                "response_mode": "fill_blank",
                "prompt": "填写：____ + ____ = 4。",
                "choices": [],
                "answer": ["2", "2"],
            },
            identity={
                "question_id": "Q-REPEATED-FILL",
                "node_id": "M-PRE-FRACTION-OPS",
                "qf_id": "qf-1",
                "slot_id": "slot-1",
            },
        )

        self.assertEqual(["2", "2"], [target["accepted_values"][0] for target in artifact["grading"]["targets"]])

    def test_decimal_input_control_alias_and_trim_whitespace_are_supported(self):
        candidate = self._fill_candidate()
        candidate["interaction_proposal"]["controls"][0]["control_type"] = "number_input"
        candidate["answer_proposal"]["targets"][0]["normalization"] = "trim_whitespace"
        artifact = question_artifact.compile_question_artifact(
            candidate,
            identity={
                "question_id": "Q-130",
                "node_id": "M-PRE-DECIMAL-OPS",
                "qf_id": "decimal_mixed_calculation",
                "slot_id": "decimal-add-multiply-004",
            },
        )
        result = question_artifact.grade_response(
            artifact,
            {
                "schema_version": question_artifact.RESPONSE_SCHEMA_VERSION,
                "question_id": "Q-130",
                "artifact_version": 1,
                "response": {
                    "schema_version": question_artifact.FIXED_RESPONSE_SCHEMA_VERSION,
                    "type": "fill_blank",
                    "fields": [{"id": "result", "value": " 6.21 "}],
                },
            },
        )
        self.assertEqual("correct", result["grading"]["status"])

    def test_decimal_normalization_aliases_are_compiled_to_decimal(self):
        for policy in ("normalize_decimal", "trim_whitespace;trim_trailing_zeros", "trim_spaces_and_trailing_zeros"):
            with self.subTest(policy=policy):
                candidate = self._fill_candidate()
                candidate["answer_proposal"]["targets"][0]["normalization"] = policy
                artifact = question_artifact.compile_question_artifact(
                    candidate,
                    identity={
                        "question_id": "Q-131",
                        "node_id": "M-PRE-DECIMAL-OPS",
                        "qf_id": "decimal_mixed_calculation",
                        "slot_id": "decimal-add-multiply-005",
                    },
                )
                self.assertEqual("decimal", artifact["grading"]["targets"][0]["normalization"])

    def test_choice_candidate_compiles_and_uses_choice_ids(self):
        artifact = question_artifact.compile_question_artifact(
            self._choice_candidate(),
            identity={
                "question_id": "Q-124",
                "node_id": "M-PRE-DECIMAL-OPS",
                "qf_id": "decimal_operation_reasoning_check",
                "slot_id": "decimal-equivalent-representation-001",
                "artifact_version": 1,
            },
        )
        self.assertEqual("single_choice", artifact["child_surface"]["interaction_schema"]["type"])
        self.assertEqual(["A", "B"], [item["id"] for item in artifact["child_surface"]["interaction_schema"]["choices"]])
        result = question_artifact.grade_response(
            artifact,
            {
                "schema_version": question_artifact.RESPONSE_SCHEMA_VERSION,
                "question_id": "Q-124",
                "artifact_version": 1,
                "response": {
                    "schema_version": question_artifact.FIXED_RESPONSE_SCHEMA_VERSION,
                    "type": "single_choice",
                    "choice_id": "A",
                },
            },
        )
        self.assertEqual("correct", result["grading"]["status"])

    def test_choice_control_proposal_is_normalized_to_choice_list(self):
        candidate = self._choice_candidate()
        candidate["interaction_proposal"]["controls"] = [{
            "id": "q1",
            "control_type": "single_choice",
            "value_type": "choice_single",
            "label": "请选择正确选项",
            "order": 1,
            "required": True,
            "placeholder": "",
        }]
        candidate["answer_proposal"]["targets"] = [{
            "control_id": "q1",
            "choice_id": "A",
            "answer_type": "choice_single",
            "accepted_values": ["A"],
            "normalization": "exact",
        }]
        artifact = question_artifact.compile_question_artifact(
            candidate,
            identity={
                "question_id": "Q-129",
                "node_id": "M-PRE-DECIMAL-OPS",
                "qf_id": "decimal_operation_reasoning_check",
                "slot_id": "decimal-representation-003",
            },
        )
        self.assertEqual([], artifact["child_surface"]["interaction_schema"]["fields"])
        self.assertEqual(["A", "B"], [item["id"] for item in artifact["child_surface"]["interaction_schema"]["choices"]])

    def test_multi_choice_candidate_requires_the_exact_choice_set(self):
        candidate = self._choice_candidate()
        candidate["task"] = {"task_type": "reasoning", "response_mode": "multi_choice"}
        candidate["answer_proposal"] = {
            "grading_mode": "local_fixed_answer",
            "targets": [{"choice_id": "A"}, {"choice_id": "B"}],
        }
        artifact = question_artifact.compile_question_artifact(
            candidate,
            identity={
                "question_id": "Q-126",
                "node_id": "M-PRE-DECIMAL-OPS",
                "qf_id": "decimal_operation_reasoning_check",
                "slot_id": "decimal-representation-002",
            },
        )
        result = question_artifact.grade_response(
            artifact,
            {
                "schema_version": question_artifact.RESPONSE_SCHEMA_VERSION,
                "question_id": "Q-126",
                "artifact_version": 1,
                "response": {
                    "schema_version": question_artifact.FIXED_RESPONSE_SCHEMA_VERSION,
                    "type": "multi_choice",
                    "choice_ids": ["B", "A"],
                },
            },
        )
        self.assertEqual("correct", result["grading"]["status"])

    def test_response_version_and_field_binding_are_checked_before_grading(self):
        artifact = question_artifact.compile_question_artifact(
            self._fill_candidate(),
            identity={
                "question_id": "Q-127",
                "node_id": "M-PRE-DECIMAL-OPS",
                "qf_id": "decimal_mixed_calculation",
                "slot_id": "decimal-add-multiply-002",
            },
        )
        with self.assertRaisesRegex(question_artifact.ContractError, "version"):
            question_artifact.grade_response(
                artifact,
                {
                    "schema_version": question_artifact.RESPONSE_SCHEMA_VERSION,
                    "question_id": "Q-127",
                    "artifact_version": 2,
                    "response": {},
                },
            )
        with self.assertRaisesRegex(question_artifact.ContractError, "fields"):
            question_artifact.grade_response(
                artifact,
                {
                    "schema_version": question_artifact.RESPONSE_SCHEMA_VERSION,
                    "question_id": "Q-127",
                    "artifact_version": 1,
                    "response": {
                        "schema_version": question_artifact.FIXED_RESPONSE_SCHEMA_VERSION,
                        "type": "fill_blank",
                        "fields": [{"id": "other", "value": "6.21"}],
                    },
                },
            )

    def test_compiler_rejects_unbound_blank_and_answer_target(self):
        candidate = self._fill_candidate()
        candidate["content"]["blocks"][1]["field_id"] = "missing"
        with self.assertRaisesRegex(question_artifact.ContractError, "blank field"):
            question_artifact.compile_question_artifact(candidate, identity={"question_id": "Q"})

        candidate = self._fill_candidate()
        candidate["answer_proposal"]["targets"][0]["control_id"] = "missing"
        with self.assertRaisesRegex(question_artifact.ContractError, "answer target"):
            question_artifact.compile_question_artifact(candidate, identity={"question_id": "Q"})

    def test_application_is_task_type_but_short_answer_uses_model_route(self):
        candidate = self._fill_candidate()
        candidate["task"] = {"task_type": "application", "response_mode": "short_answer"}
        candidate["content"] = {"blocks": [{"type": "text", "text": "请说明总价如何计算。"}]}
        candidate["interaction_proposal"] = {"controls": [], "choices": []}
        candidate["answer_proposal"] = {
            "grading_mode": "model_semantic_assessment",
            "rubric": ["正确建立小数数量关系"],
        }
        artifact = question_artifact.compile_question_artifact(
            candidate,
            identity={"question_id": "Q-125", "node_id": "M-PRE-DECIMAL-OPS", "qf_id": "decimal_operation_reasoning_check", "slot_id": "decimal-application-001"},
        )
        self.assertEqual("application", artifact["task"]["task_type"])
        self.assertEqual("model_semantic_assessment", artifact["grading"]["mode"])
        with self.assertRaisesRegex(question_artifact.ContractError, "semantic"):
            question_artifact.grade_response(artifact, {})


if __name__ == "__main__":
    unittest.main()
