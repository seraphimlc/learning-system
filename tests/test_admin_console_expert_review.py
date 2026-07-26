from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system import model_router
from learning_system.admin.expert_review import (
    build_candidate_expert_review,
    build_candidate_model_expert_board_review,
    build_expert_quality_review,
    write_model_expert_board_review,
    write_expert_quality_review,
)
from tests.test_admin_console_production_loop import _good_candidate, _model_expert_pass_output, _number_line_brief


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AdminConsoleExpertReviewTests(unittest.TestCase):
    def test_model_expert_status_cannot_pass_when_a_profile_needs_revision(self) -> None:
        from learning_system.admin.expert_review import EXPERT_PROFILES, _model_expert_status

        profiles = [
            {
                "profile": profile,
                "status": "needs_revision" if profile == "assessment_expert" else "pass",
            }
            for profile in EXPERT_PROFILES
        ]
        self.assertEqual(
            "NEEDS_FIX",
            _model_expert_status("pass", profiles, [], 0.99, 0.86),
        )

    def test_expert_prompt_has_batch_quality_floor(self) -> None:
        prompt = (PROJECT_ROOT / "learning_system/prompts/admin_question_expert_review.v1.md").read_text(encoding="utf-8")

        self.assertIn("Batch production is only an efficiency mechanism", prompt)
        self.assertIn("It never lowers the quality bar", prompt)
        self.assertIn("do not average quality across the batch", prompt)
        self.assertIn("question_requirement", prompt)
        self.assertIn("do not require every single question to cover every family-level evidence target", prompt)

    def test_v18_sample_expert_gate_passes_with_scope_and_does_not_activate(self) -> None:
        report = build_expert_quality_review(root=PROJECT_ROOT, version="v18-sample")

        self.assertEqual("PASS_WITH_SCOPE", report["status"])
        self.assertTrue(report["sample_only"])
        self.assertEqual("does_not_authorize_activation", report["activation_implication"])
        self.assertNotIn("P0", report["finding_counts"])
        self.assertNotIn("P1", report["finding_counts"])

    def test_bad_question_bank_gets_needs_fix(self) -> None:
        source = json.loads((PROJECT_ROOT / "data/question_banks/v18/math_v18_sample_60.json").read_text(encoding="utf-8"))
        bad = copy.deepcopy(source)
        bad["items"] = [copy.deepcopy(source["items"][0])]
        bad["item_count"] = 1
        bad["items"][0]["id"] = "BAD-001"
        bad["items"][0]["prompt"] = "直接计算 1+1。只写答案。"
        bad["items"][0]["required_evidence"] = []
        bad["items"][0]["key_score_points"] = [{"key": "answer", "points": 10, "evidence": "2"}]
        bad["items"][0]["source_type"] = "commercial_reference"
        with tempfile.TemporaryDirectory() as tmp:
            bank_path = Path(tmp) / "bad_bank.json"
            bank_path.write_text(json.dumps(bad, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_expert_quality_review(root=PROJECT_ROOT, version=str(bank_path))

        self.assertEqual("NEEDS_FIX", report["status"])
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("low_value_mechanical_prompt", codes)
        self.assertIn("weak_required_evidence", codes)
        self.assertIn("commercial_source_item", codes)

    def test_candidate_expert_review_blocks_opposite_probe_that_mixes_absolute_without_secondary(self) -> None:
        candidate = _good_candidate(_number_line_brief())
        candidate.update(
            {
                "id": "BAD-OPPOSITE-ABS",
                "node_id": "M-G7-OPPOSITE",
                "question_type": "opposite_absolute_value_model",
                "prompt": "A 在 0 左边距离 3，B 是 A 的相反数。写出 A、B，并判断 |A| 是否一定比 A 大。",
                "standard_answer": "A=-3，B=3，|A|=3，比 A 大。",
                "required_evidence": ["能说明相反数是关于0对称", "能处理0的特殊性", "能说明绝对值是距离"],
            }
        )
        candidate["production_lineage"]["family_id"] = "opposite_absolute_value_model"
        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = Path(tmp) / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            report = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)

        self.assertEqual("NEEDS_FIX", report["status"])
        self.assertIn("opposite_probe_mixes_absolute_without_secondary_node", {finding["code"] for finding in report["findings"]})

    def test_candidate_expert_review_allows_opposite_absolute_mix_when_secondary_node_is_marked(self) -> None:
        candidate = _good_candidate(_number_line_brief())
        candidate.update(
            {
                "id": "OK-OPPOSITE-ABS-SECONDARY",
                "node_id": "M-G7-OPPOSITE",
                "secondary_node_ids": ["M-G7-ABSOLUTE"],
                "question_type": "opposite_absolute_value_model",
                "prompt": "A 在 0 左边距离 3，B 是 A 的相反数。写出 A、B，并判断 |A| 是否一定比 A 大。",
                "standard_answer": "A=-3，B=3，|A|=3，比 A 大。",
                "required_evidence": ["能说明相反数是关于0对称", "能处理0的特殊性", "能说明绝对值是距离"],
            }
        )
        candidate["production_lineage"]["family_id"] = "opposite_absolute_value_model"
        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = Path(tmp) / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            report = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)

        self.assertNotIn("opposite_probe_mixes_absolute_without_secondary_node", {finding["code"] for finding in report["findings"]})

    def test_candidate_expert_review_blocks_equation_flow_that_only_explains_one_step(self) -> None:
        candidate = _good_candidate(_number_line_brief())
        candidate.update(
            {
                "id": "BAD-EQUATION-LEGALITY",
                "node_id": "M-PRE-EQUATION-BASIC",
                "question_type": "linear_equation_solving_flow",
                "difficulty": "L3",
                "prompt": "4x - 6 = 18，补全①和②：① 4x=24，② x=6。用一句话说明从原方程到第二行为什么合法，并代回检验。",
                "standard_answer": "①4x=24，②x=6；两边同时加6合法；代回正确。",
                "required_evidence": ["能保持等式合法", "结果正确且能代回检查", "关键步骤可复盘"],
            }
        )
        candidate["production_lineage"]["family_id"] = "linear_equation_solving_flow"
        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = Path(tmp) / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            report = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)

        self.assertEqual("NEEDS_FIX", report["status"])
        self.assertIn("equation_flow_legality_prompt_not_complete", {finding["code"] for finding in report["findings"]})

    def test_expert_review_receipt_can_be_written_to_temp_root(self) -> None:
        report = build_expert_quality_review(root=PROJECT_ROOT, version="v18-sample")
        with tempfile.TemporaryDirectory() as tmp:
            result = write_expert_quality_review(report, root=Path(tmp), apply=True)
            self.assertTrue((Path(tmp) / result["review_markdown_path"]).exists())
            self.assertTrue((Path(tmp) / result["review_json_path"]).exists())

    def test_v18_expert_gate_reviews_staged_bank(self) -> None:
        staged_path = PROJECT_ROOT / "data/question_banks/v18/staged_candidates_v18.json"
        staged = json.loads(staged_path.read_text(encoding="utf-8"))

        report = build_expert_quality_review(root=PROJECT_ROOT, version="v18")

        self.assertEqual("data/question_banks/v18/staged_candidates_v18.json", report["source_path"])
        self.assertEqual(staged["question_bank_version"], report["question_bank_version"])
        self.assertEqual(staged["status"], report["question_bank_status"])
        self.assertEqual(len(staged["items"]), report["reviewed_item_count"])
        self.assertFalse(report["sample_only"])
        self.assertEqual("does_not_authorize_activation", report["activation_implication"])

    def test_model_expert_board_blocks_when_model_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            candidate_path = Path(tmp) / "candidate.json"
            candidate_path.write_text(json.dumps({"item": _good_candidate(_number_line_brief())}, ensure_ascii=False), encoding="utf-8")

            report = build_candidate_model_expert_board_review(root=PROJECT_ROOT, candidate_path=candidate_path)

        self.assertEqual("BLOCKED_MODEL_NOT_CONFIGURED", report["status"])
        self.assertEqual(["configure_admin_question_expert_review_model"], report["next_actions"])

    def test_model_expert_board_live_receipt_can_be_written_with_fake_model(self) -> None:
        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            self.assertEqual("admin_question_expert_review_agent", route.agent_key)
            self.assertEqual("2026-07-23.admin-question-expert-review.schema.v1", schema["properties"]["schema_version"]["const"])
            value = _model_expert_pass_output()
            return model_router.StructuredJSONResult(
                value=value,
                mode="json_schema",
                raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_ADMIN_QUESTION_EXPERT_REVIEW_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": _good_candidate(_number_line_brief())}, ensure_ascii=False), encoding="utf-8")

            report = build_candidate_model_expert_board_review(root=PROJECT_ROOT, candidate_path=candidate_path)
            written = write_model_expert_board_review(report, root=tmp_path, apply=True)
            receipt_exists = (tmp_path / written["model_expert_review_json_path"]).exists()

        self.assertEqual("PASS", report["status"])
        self.assertEqual("live_model", report["provider_mode"])
        self.assertTrue(receipt_exists)

    def test_model_expert_board_receives_authoritative_slot_requirement(self) -> None:
        requirement = {
            "question_requirement_id": "REQ-unit-length-only",
            "slot_id": "M-G7-NUMBER-LINE:number_line_unit_length:01",
            "question_direction": "只判断相邻刻度表示的单位长度",
            "evidence_goal": "能从两个已知刻度确定单位长度",
            "must_include": ["两个已知刻度", "单位长度"],
            "must_not_include": ["同时考查原点定位", "同时考查正方向"],
            "difficulty": "L2",
        }

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            prompt = payload["input"][0]["content"][0]["text"]
            self.assertIn("REQ-unit-length-only", prompt)
            self.assertIn("只判断相邻刻度表示的单位长度", prompt)
            value = _model_expert_pass_output()
            return model_router.StructuredJSONResult(
                value=value,
                mode="json_schema",
                raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_ADMIN_QUESTION_EXPERT_REVIEW_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            candidate_path = Path(tmp) / "candidate.json"
            candidate = _good_candidate(_number_line_brief())
            candidate["production_lineage"]["question_requirement_id"] = requirement["question_requirement_id"]
            candidate["production_lineage"]["slot_id"] = requirement["slot_id"]
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            report = build_candidate_model_expert_board_review(
                root=PROJECT_ROOT,
                candidate_path=candidate_path,
                question_requirement=requirement,
            )

        self.assertEqual("PASS", report["status"])
        self.assertEqual("REQ-unit-length-only", report["question_requirement_id"])
        self.assertEqual(requirement, report["question_requirement"])


if __name__ == "__main__":
    unittest.main()
