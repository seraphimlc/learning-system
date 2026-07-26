from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system import model_router
from learning_system.admin.model_semantic_regression import (
    DEFAULT_ANSWER_CASES_PATH,
    _load_cases,
    _model_api_key_env,
    AdminProductionError,
    run_answer_semantic_regression,
    write_answer_semantic_regression_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _answer_review_output(case: dict, *, wrong: bool = False) -> dict:
    criteria = []
    for criterion in case["criteria"]:
        key = criterion["criterion_key"]
        status = case["expected_statuses"][key]
        if wrong and key == case["criteria"][0]["criterion_key"]:
            status = "not_met" if status != "not_met" else "met"
        criteria.append({
            "criterion_key": key,
            "status": status,
            "child_evidence": "模拟证据",
            "reason": "根据孩子作答可判断。",
        })
    return {
        "schema_version": "2026-07-14.answer-review.v5.schema.v3",
        "criteria": criteria,
        "answer_gap": "核心判断已按证据完成。",
        "improvement_direction": ["保持把关键关系写出来。"],
        "expression_judgment": "表达可以判断数学意图。",
        "teaching_explanation": "这一步主要看关系和结论是否一致。",
        "confidence": 0.91,
    }


class AdminConsoleModelSemanticRegressionTests(unittest.TestCase):
    def test_default_answer_semantic_cases_cover_required_scenario_classes(self) -> None:
        payload = _load_cases(PROJECT_ROOT, DEFAULT_ANSWER_CASES_PATH)
        categories = {case["category"] for case in payload["cases"]}

        self.assertEqual(20, payload["case_count"])
        self.assertEqual(20, len(payload["cases"]))
        for category in {
            "correct_with_reasoning",
            "answer_only",
            "right_answer_wrong_reason",
            "alternative_valid_method",
            "stuck",
            "blank",
            "photo_text_conflict",
            "unclear_photo",
            "correct_result_missing_nonessential_rule",
        }:
            self.assertIn(category, categories)

    def test_semantic_regression_fails_closed_without_api_key(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            report = run_answer_semantic_regression(
                root=PROJECT_ROOT,
                models=["gpt-5.6-luna"],
                limit=2,
                api_key_env="MISSING_TEST_API_KEY",
            )

        self.assertEqual("BLOCKED_MODEL_NOT_CONFIGURED", report["status"])
        self.assertEqual("BLOCKED_MODEL_NOT_CONFIGURED", report["models"][0]["status"])
        self.assertEqual(2, report["models"][0]["blocked_count"])
        self.assertEqual("api keys are read from environment and never written to reports", report["secret_policy"])

    def test_semantic_regression_scores_mocked_model_against_case_oracle(self) -> None:
        payload = _load_cases(PROJECT_ROOT, DEFAULT_ANSWER_CASES_PATH)
        calls = {"value": 0}

        def fake_call(route, request_payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            case = payload["cases"][calls["value"]]
            calls["value"] += 1
            return model_router.StructuredJSONResult(
                value=_answer_review_output(case),
                mode="json_schema",
                raw_response={"output_text": json.dumps(_answer_review_output(case), ensure_ascii=False)},
                endpoint="responses",
            )

        with mock.patch.dict(os.environ, {"TEST_MODEL_KEY": "secret-value"}, clear=True), mock.patch.object(
            model_router,
            "call_structured_json",
            side_effect=fake_call,
        ):
            report = run_answer_semantic_regression(
                root=PROJECT_ROOT,
                models=["gpt-5.6-luna"],
                limit=3,
                api_key_env="TEST_MODEL_KEY",
            )

        self.assertEqual("PASS", report["status"])
        self.assertEqual(3, report["models"][0]["passed_count"])
        self.assertNotIn("secret-value", json.dumps(report, ensure_ascii=False))

    def test_semantic_regression_reports_mismatched_criterion_status(self) -> None:
        payload = _load_cases(PROJECT_ROOT, DEFAULT_ANSWER_CASES_PATH)

        def fake_call(route, request_payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            case = payload["cases"][0]
            return model_router.StructuredJSONResult(
                value=_answer_review_output(case, wrong=True),
                mode="json_schema",
                raw_response={"output_text": json.dumps(_answer_review_output(case, wrong=True), ensure_ascii=False)},
                endpoint="responses",
            )

        with mock.patch.dict(os.environ, {"TEST_MODEL_KEY": "secret-value"}, clear=True), mock.patch.object(
            model_router,
            "call_structured_json",
            side_effect=fake_call,
        ):
            report = run_answer_semantic_regression(
                root=PROJECT_ROOT,
                models=["gpt-5.6-luna"],
                limit=1,
                api_key_env="TEST_MODEL_KEY",
            )

        self.assertEqual("FAIL", report["status"])
        case_report = report["models"][0]["cases"][0]
        self.assertEqual("FAIL", case_report["status"])
        self.assertIn("status_mismatch", {issue["code"] for issue in case_report["issues"]})

    def test_semantic_regression_accepts_declared_status_equivalence(self) -> None:
        payload = _load_cases(PROJECT_ROOT, DEFAULT_ANSWER_CASES_PATH)
        case = next(item for item in payload["cases"] if item["case_id"] == "ASR-009-correct-result-missing-nonessential-rule")

        def fake_call(route, request_payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            output = _answer_review_output(case)
            for criterion in output["criteria"]:
                if criterion["criterion_key"] == "remainder_bound":
                    criterion["status"] = "not_met"
            return model_router.StructuredJSONResult(
                value=output,
                mode="json_schema",
                raw_response={"output_text": json.dumps(output, ensure_ascii=False)},
                endpoint="responses",
            )

        with mock.patch.dict(os.environ, {"TEST_MODEL_KEY": "secret-value"}, clear=True), mock.patch.object(
            model_router,
            "call_structured_json",
            side_effect=fake_call,
        ):
            report = run_answer_semantic_regression(
                root=PROJECT_ROOT,
                models=["gpt-5.6-luna"],
                cases_path=DEFAULT_ANSWER_CASES_PATH,
                limit=9,
                api_key_env="TEST_MODEL_KEY",
            )

        case_report = report["models"][0]["cases"][-1]
        self.assertEqual("ASR-009-correct-result-missing-nonessential-rule", case_report["case_id"])
        self.assertEqual("PASS", case_report["status"])
        self.assertEqual(["not_met", "unclear"], case_report["accepted_statuses"]["remainder_bound"])

    def test_semantic_regression_uses_model_specific_api_key_env_when_present(self) -> None:
        captured = {}

        def fake_call(route, request_payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            captured["api_key"] = route.api_key
            payload = _load_cases(PROJECT_ROOT, DEFAULT_ANSWER_CASES_PATH)
            return model_router.StructuredJSONResult(
                value=_answer_review_output(payload["cases"][0]),
                mode="json_object",
                raw_response={"output_text": json.dumps(_answer_review_output(payload["cases"][0]), ensure_ascii=False)},
                endpoint="responses",
            )

        model = "deepseek-v4-pro-260425"
        with mock.patch.dict(
            os.environ,
            {
                "TEST_MODEL_KEY": "default-secret",
                _model_api_key_env(model): "model-specific-secret",
            },
            clear=True,
        ), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            report = run_answer_semantic_regression(
                root=PROJECT_ROOT,
                models=[model],
                limit=1,
                api_key_env="TEST_MODEL_KEY",
            )

        self.assertEqual("PASS", report["status"])
        self.assertEqual("model-specific-secret", captured["api_key"])
        self.assertNotIn("model-specific-secret", json.dumps(report, ensure_ascii=False))

    def test_semantic_regression_flags_forbidden_child_feedback_phrase(self) -> None:
        payload = _load_cases(PROJECT_ROOT, DEFAULT_ANSWER_CASES_PATH)
        case = next(item for item in payload["cases"] if item["case_id"] == "ASR-005-symbol-error")
        one_case_payload = {**payload, "case_count": 1, "cases": [case]}

        def fake_call(route, request_payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            output = _answer_review_output(case)
            output["teaching_explanation"] = "减法要加上被减数的相反数。"
            return model_router.StructuredJSONResult(
                value=output,
                mode="json_schema",
                raw_response={"output_text": json.dumps(output, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp:
            cases_path = Path(tmp) / "cases.json"
            cases_path.write_text(json.dumps(one_case_payload, ensure_ascii=False), encoding="utf-8")
            with mock.patch.dict(os.environ, {"TEST_MODEL_KEY": "secret-value"}, clear=True), mock.patch.object(
                model_router,
                "call_structured_json",
                side_effect=fake_call,
            ):
                report = run_answer_semantic_regression(
                    root=PROJECT_ROOT,
                    models=["gpt-5.6-luna"],
                    cases_path=cases_path,
                    api_key_env="TEST_MODEL_KEY",
                )

        self.assertEqual("FAIL", report["status"])
        issues = report["models"][0]["cases"][0]["issues"]
        self.assertIn("child_facing_feedback_forbidden_substring", {issue["code"] for issue in issues})

    def test_semantic_regression_can_run_selected_case_ids_only(self) -> None:
        payload = _load_cases(PROJECT_ROOT, DEFAULT_ANSWER_CASES_PATH)
        selected_case = next(item for item in payload["cases"] if item["case_id"] == "ASR-007-stuck")
        captured_case_prompts = []

        def fake_call(route, request_payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            captured_case_prompts.append(json.dumps(request_payload, ensure_ascii=False))
            return model_router.StructuredJSONResult(
                value=_answer_review_output(selected_case),
                mode="json_schema",
                raw_response={"output_text": json.dumps(_answer_review_output(selected_case), ensure_ascii=False)},
                endpoint="responses",
            )

        with mock.patch.dict(os.environ, {"TEST_MODEL_KEY": "secret-value"}, clear=True), mock.patch.object(
            model_router,
            "call_structured_json",
            side_effect=fake_call,
        ):
            report = run_answer_semantic_regression(
                root=PROJECT_ROOT,
                models=["gpt-5.6-luna"],
                case_ids=["ASR-007-stuck"],
                api_key_env="TEST_MODEL_KEY",
            )

        self.assertEqual(1, report["case_count"])
        self.assertEqual("ASR-007-stuck", report["models"][0]["cases"][0]["case_id"])
        self.assertEqual(1, len(captured_case_prompts))
        self.assertIn("ASR-007-stuck", captured_case_prompts[0])

    def test_semantic_regression_rejects_unknown_case_id(self) -> None:
        with self.assertRaises(AdminProductionError):
            run_answer_semantic_regression(
                root=PROJECT_ROOT,
                models=["gpt-5.6-luna"],
                case_ids=["ASR-does-not-exist"],
                api_key_env="TEST_MODEL_KEY",
            )

    def test_semantic_regression_report_writer_is_apply_guarded(self) -> None:
        report = {
            "schema_version": "2026-07-23.codex-admin.model-semantic-regression.answer.v1",
            "run_id": "MSR-test",
            "status": "PASS",
            "case_count": 1,
            "models": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dry = write_answer_semantic_regression_report(report, root=tmp_path, apply=False)
            self.assertFalse(dry["write_applied"])
            self.assertFalse((tmp_path / dry["regression_json_path"]).exists())
            written = write_answer_semantic_regression_report(report, root=tmp_path, apply=True)
            self.assertTrue((tmp_path / written["regression_json_path"]).exists())
            self.assertTrue((tmp_path / written["regression_markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
