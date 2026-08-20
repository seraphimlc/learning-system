import unittest

from learning_system.answer_verification import is_math_equivalent


class TestMathEquivalent(unittest.TestCase):
    def test_equivalent_fraction_and_decimal(self):
        self.assertTrue(is_math_equivalent("3/4 + 5/6", "19/12"))  # 3/4+5/6 = 19/12
        self.assertTrue(is_math_equivalent("1.5", "3/2"))
        self.assertTrue(is_math_equivalent("6/4", "1.5"))

    def test_mismatch_returns_false(self):
        self.assertFalse(is_math_equivalent("1/2", "2/3"))
        self.assertFalse(is_math_equivalent("3", "4"))

    def test_invalid_input_returns_false(self):
        self.assertFalse(is_math_equivalent("abc", "1"))
        self.assertFalse(is_math_equivalent("", "1"))

    def test_unicode_multiply_normalized_in_equivalence(self):
        # 答案卡排版常用 ×/÷/−：sympify 前需归一化，否则误报 mismatch
        self.assertTrue(is_math_equivalent("3 × 2", "6"))


from learning_system.answer_verification import extract_calculation


class TestExtractCalculation(unittest.TestCase):
    def test_extracts_plain_expression(self):
        self.assertEqual(extract_calculation("计算：3/4 + 5/6 的结果"), "3/4 + 5/6")

    def test_handles_unicode_operators(self):
        self.assertEqual(extract_calculation("计算：2 × 3 ÷ 4"), "2 * 3 / 4")

    def test_no_calculation_returns_none(self):
        self.assertIsNone(extract_calculation("下列说法正确的是（ ）"))

    def test_invalid_expression_returns_none(self):
        self.assertIsNone(extract_calculation("计算：abracadabra"))

    def test_unicode_minus_u2212_maps_to_ascii_minus(self):
        # 无空格输入按字符替换（与 ×/÷ 处理一致，保留输入间距）
        self.assertEqual(extract_calculation("计算：3−1"), "3-1")
        # 带空格输入原样保留空格
        self.assertEqual(extract_calculation("计算：3 − 1"), "3 - 1")

    def test_unicode_minus_uff0d_maps_to_ascii_minus(self):
        self.assertEqual(extract_calculation("计算：2－3"), "2-3")
        self.assertEqual(extract_calculation("计算：2 － 3"), "2 - 3")

    def test_sympify_gate_rejects_trailing_plus(self):
        self.assertIsNone(extract_calculation("计算：3 + +"))

    def test_sympify_gate_rejects_unbalanced_paren(self):
        self.assertIsNone(extract_calculation("计算：(1/2"))

    def test_non_colon_prefix_returns_none(self):
        self.assertIsNone(extract_calculation("计算下列各题：1/2+1/3"))

    def test_truncated_half_expression_boundary(self):
        self.assertEqual(extract_calculation("计算：1/2 与 1/3 的大小"), "1/2")


from learning_system.answer_verification import verify_expected_answer


class TestVerifyExpectedAnswer(unittest.TestCase):
    def test_verified_when_expression_matches(self):
        result = verify_expected_answer("计算：1/2 + 1/3", "5/6")
        self.assertEqual(result["verdict"], "verified")

    def test_mismatch_detected(self):
        result = verify_expected_answer("计算：1/2 + 1/3", "1")
        self.assertEqual(result["verdict"], "mismatch")
        self.assertEqual(result["expected"], "1")

    def test_unverifiable_when_no_expression(self):
        result = verify_expected_answer("判断题：3 是质数", "对")
        self.assertEqual(result["verdict"], "unverifiable")
        self.assertIn("reason", result)

    def test_empty_expected_answer_is_unverifiable(self):
        # 空 expected 属"无法校验"而非 mismatch（与批量审计脚本语义一致）
        result = verify_expected_answer("计算：1/2 + 1/3", "")
        self.assertEqual(result, {"verdict": "unverifiable", "reason": "empty expected answer"})
        self.assertEqual(verify_expected_answer("计算：1/2 + 1/3", "   ")["verdict"], "unverifiable")

    def test_division_operator_in_expected_answer_verified(self):
        # 含 ÷ 的答案卡排版也能验证（sympify 前归一化）
        result = verify_expected_answer("计算：1/2 + 1/3", "5 ÷ 6")
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(result["expression"], "1/2 + 1/3")


import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = PROJECT_ROOT / "scripts/audit_question_bank_answers.py"


class TestAuditScriptContract(unittest.TestCase):
    """锁定审计脚本的退出码与输出契约（subprocess 冒烟级，防回归）。"""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(AUDIT_SCRIPT), *args],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
        )

    def test_two_item_fixture_with_mismatch_exits_1_and_reports_counts(self):
        with tempfile.TemporaryDirectory(prefix="audit_script_contract_") as tmp:
            fixture = Path(tmp) / "items.json"
            fixture.write_text(json.dumps([
                {"prompt": "计算：1/2 + 1/3", "expected_answer": "5/6"},  # verified
                {"prompt": "计算：1/2 + 1/3", "expected_answer": "1"},     # mismatch
            ], ensure_ascii=False), encoding="utf-8")
            proc = self._run("--json", str(fixture))
        self.assertEqual(proc.returncode, 1)
        report = json.loads(proc.stdout)
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["verified"], 1)
        self.assertEqual(report["mismatch"], 1)
        self.assertEqual(report["unverifiable"], 0)

    def test_no_mismatch_exits_0(self):
        with tempfile.TemporaryDirectory(prefix="audit_script_contract_") as tmp:
            fixture = Path(tmp) / "items.json"
            fixture.write_text(json.dumps([
                {"prompt": "计算：1/2 + 1/3", "expected_answer": "5/6"},
                {"prompt": "计算：2 × 3", "expected_answer": "6"},
            ], ensure_ascii=False), encoding="utf-8")
            proc = self._run("--json", str(fixture))
        self.assertEqual(proc.returncode, 0)
        report = json.loads(proc.stdout)
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["verified"], 2)
        self.assertEqual(report["mismatch"], 0)

    def test_missing_json_file_exits_2_with_friendly_message(self):
        missing = Path(tempfile.gettempdir()) / "audit_script_missing_fixture.json"
        missing.unlink(missing_ok=True)  # 确保不存在
        proc = self._run("--json", str(missing))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("JSON 文件不存在", proc.stderr)

    def test_top_level_non_list_exits_2_with_friendly_message(self):
        with tempfile.TemporaryDirectory(prefix="audit_script_contract_") as tmp:
            fixture = Path(tmp) / "items.json"
            fixture.write_text(json.dumps({"prompt": "不是 list"}, ensure_ascii=False), encoding="utf-8")
            proc = self._run("--json", str(fixture))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("顶层必须是 list", proc.stderr)


if __name__ == "__main__":
    unittest.main()
