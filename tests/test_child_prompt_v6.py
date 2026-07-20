from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from learning_system import child_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _schema(
    interaction_type: str = "short_text",
    *,
    title: str = "我的答案",
    requires_explanation: bool = False,
    explanation_label: str = "说明理由",
    fields: list[dict] | None = None,
    choices: list[dict] | None = None,
    formula_label: str = "",
) -> dict:
    return {
        "schema_version": child_prompt.QUESTION_INTERACTION_SCHEMA_V2,
        "type": interaction_type,
        "title": title,
        "allow_explanation": True,
        "requires_explanation": requires_explanation,
        "explanation_label": explanation_label,
        "fields": fields or [],
        "choices": choices or [],
        "formula_label": formula_label,
        "placeholder": "",
    }


def _bootstrap(name: str, prompt: str, schema: dict, *, required_lines: list[str], absent_text: list[str] | None = None) -> dict:
    surface = child_prompt.project_child_surface(
        prompt=prompt,
        prompt_format=child_prompt.CHILD_PROMPT_FORMAT,
        interaction_schema=schema,
        allow_legacy=False,
    )
    step = {
        "step_handle": f"fixture-{name}",
        "position": 1,
        "kind_label": "小检测",
        "topic_label": name,
        "answer_input_mode": "interaction" if schema["type"] != "short_text" else "text",
        "allowed_response_modes": ["text", "stuck"],
        "upload_enabled": False,
        "stuck_enabled": True,
        "state": "selected",
        "support": {"hint": "", "continue_label": "", "stuck_label": "卡住了"},
        **surface,
        "child_surface_projection_sha256": surface["projection_sha256"],
    }
    return {
        "name": name,
        "bootstrap": {
            "schema_version": "3.test.child-surface.v6",
            "child_state": "current_step",
            "current_step": step,
            "message": {},
        },
        "expect": {
            "required_lines": required_lines,
            "absent_text": absent_text or [],
            "control_kind": schema["type"],
            "required_message": (
                f"请先{schema['explanation_label']}"
                if schema.get("requires_explanation")
                else ""
            ),
        },
    }


def _browser_fixture() -> dict:
    cases = [
        _bootstrap(
            "parenthesis-slot-5",
            "把下面的去括号变化记录翻译成一个完整的化简过程，并写出最后结果。\n\n原式：2m−3(m+4)\n变化记录：\nm → −3m\n+4 → −12",
            _schema(),
            required_lines=["原式：2m−3(m+4)", "变化记录：", "m → −3m", "+4 → −12"],
            absent_text=["|", "---"],
        ),
        _bootstrap(
            "poly-add-sub-slot-5",
            "小航把整式 (4p−q+3)−(p+2q−5) 的去括号结果整理成了分项记录：\n\np 项：4p，−p\nq 项：−q，−2q\n常数项：3，+5\n\n请把这份记录翻译成不含括号的式子，并写出合并同类项后的结果。",
            _schema(),
            required_lines=["p 项：4p，−p", "q 项：−q，−2q", "常数项：3，+5"],
        ),
        _bootstrap(
            "monomial-slot-18",
            "同一个单项式有两种表示：\n\n表示一：(−2)×π×u×u×v^3\n表示二：\n数字因数：−2 和 π\n字母指数：u 的指数是 2，v 的指数是 3\n\n请把两种表示都翻译成规范单项式，并判断它们得到的系数和次数是否一致。",
            _schema(),
            required_lines=["表示一：(−2)×π×u×u×v^3", "表示二：", "数字因数：−2 和 π", "字母指数：u 的指数是 2，v 的指数是 3"],
        ),
        _bootstrap(
            "polynomial-slot-9",
            "航模社记录了两种高度调整方案，变量 h 表示同一个调节量。\n\n方案甲：先上升 4h^2 米，再下降 h 米，最后下降 3 米。\n方案乙：先上升 2h^3 米，再下降 5 米，最后上升 h 米。\n\n先预测哪一个方案对应的多项式次数更高；再把这个方案对应的多项式写出来，并写出它的各项、常数项和次数。",
            _schema(),
            required_lines=["方案甲：先上升 4h^2 米，再下降 h 米，最后下降 3 米。", "方案乙：先上升 2h^3 米，再下降 5 米，最后上升 h 米。"],
        ),
        _bootstrap(
            "polynomial-slot-17",
            "有同学说：“判断一个多项式的次数，只要看写在第一项的那一项次数就行。”\n请选择所有能直接反驳这句话的式子，并说明其余式子为什么不能直接反驳。",
            _schema(
                "multi_choice",
                title="选择所有能直接反驳说法的式子",
                requires_explanation=True,
                explanation_label="说明你的分类依据",
                choices=[
                    {"id": "A", "label": "x+4x^3−2"},
                    {"id": "B", "label": "5y^2−3y+1"},
                    {"id": "C", "label": "7m−4"},
                    {"id": "D", "label": "−2a^4+3a^2−6"},
                ],
            ),
            required_lines=["请选择所有能直接反驳这句话的式子，并说明其余式子为什么不能直接反驳。"],
            absent_text=["x+4x^3−2", "5y^2−3y+1", "7m−4", "−2a^4+3a^2−6"],
        ),
        _bootstrap(
            "parenthesis-slot-13",
            "计算 18−(+6)+(−4) 时，下面哪一种改写最准确地保持了原式的意义？请选择，并说明为什么这个改写保持了原式的意义。",
            _schema(
                "single_choice",
                title="选择最准确的改写",
                requires_explanation=True,
                explanation_label="说明改写理由",
                choices=[
                    {"id": "A", "label": "18−6−4"},
                    {"id": "B", "label": "18−6+4"},
                ],
            ),
            required_lines=["计算 18−(+6)+(−4) 时，下面哪一种改写最准确地保持了原式的意义？请选择，并说明为什么这个改写保持了原式的意义。"],
            absent_text=["分类"],
        ),
        _bootstrap(
            "monomial-slot-11",
            "有人记录一个单项式为 −2πx^2y^k，并把它的系数写成 −2π、次数写成 3。根据这个记录，k 可能是多少？请用你找到的 k 反过来检查“系数 −2π、次数 3”这两个判断是否站得住。",
            _schema(),
            required_lines=["有人记录一个单项式为 −2πx^2y^k，并把它的系数写成 −2π、次数写成 3。根据这个记录，k 可能是多少？请用你找到的 k 反过来检查“系数 −2π、次数 3”这两个判断是否站得住。"],
            absent_text=["ᵏ", "²"],
        ),
        _bootstrap(
            "monomial-slot-19",
            "已知 5πx^ay^2 是一个次数为 7 的单项式。a 应是多少？请说明你的判断。",
            _schema(),
            required_lines=["已知 5πx^ay^2 是一个次数为 7 的单项式。a 应是多少？请说明你的判断。"],
            absent_text=["ᵃ", "²"],
        ),
        _bootstrap(
            "fill-alignment",
            "分别填写 x^2 的系数和次数。",
            _schema(
                "fill_blank",
                title="填写两个量",
                fields=[
                    {"id": "coefficient", "label": "系数"},
                    {"id": "degree", "label": "次数"},
                ],
            ),
            required_lines=["分别填写 x^2 的系数和次数。"],
        ),
        _bootstrap(
            "formula-alignment",
            "写出表示这个关系的一个算式。",
            _schema(
                "formula_input",
                title="写出算式",
                formula_label="含 x^2 的算式",
            ),
            required_lines=["写出表示这个关系的一个算式。"],
        ),
    ]
    return {
        "valid_cases": cases,
        "required_explanation_case": "polynomial-slot-17",
        "invalid_runtime_response": {
            "message": "当前步骤还没有准备好，请稍后再试。",
        },
    }


class ChildPromptV6Tests(unittest.TestCase):
    def test_projection_preserves_multiline_exponents_and_schema_labels(self):
        surface = child_prompt.project_child_surface(
            prompt="第一组：x^2\r\n第二组：(−3xy)^2\r\n\r\n请说明你的判断。",
            prompt_format=child_prompt.CHILD_PROMPT_FORMAT,
            interaction_schema=_schema(
                "formula_input",
                title="填写 x^2",
                formula_label="算式 y^k",
            ),
            allow_legacy=False,
        )
        self.assertEqual(
            "第一组：x^2\n第二组：(−3xy)^2\n\n请说明你的判断。",
            surface["prompt"],
        )
        exponent_segments = [
            segment for segment in surface["prompt_segments"] if segment["type"] == "exponent"
        ]
        self.assertEqual(["x^2", "(−3xy)^2"], [segment["source"] for segment in exponent_segments])
        self.assertEqual("(−3xy) 的 2 次方", exponent_segments[1]["accessible_label"])
        self.assertEqual("填写 x^2", surface["interaction_rendering"]["title"]["text"])
        self.assertEqual("算式 y^k", surface["interaction_rendering"]["formula_label"]["text"])

    def test_forbidden_sources_fail_closed(self):
        cases = {
            "markdown": "| 项 | 值 |\n|---|---|",
            "unicode_letter": "yᵏ",
            "unicode_digit": "x²",
            "latex": "$x^2$",
            "html": "x<sup>2</sup>",
        }
        for name, prompt in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(child_prompt.ChildPromptContractError):
                    child_prompt.project_child_surface(
                        prompt=prompt,
                        prompt_format=child_prompt.CHILD_PROMPT_FORMAT,
                        interaction_schema=_schema(),
                        allow_legacy=False,
                    )

    def test_schema_alignment_and_exact_required_explanation_are_enforced(self):
        with self.assertRaisesRegex(
            child_prompt.ChildPromptContractError,
            "select_all_requires_multi_choice",
        ):
            child_prompt.project_child_surface(
                prompt="请选择所有正确答案。",
                prompt_format=child_prompt.CHILD_PROMPT_FORMAT,
                interaction_schema=_schema("single_choice", choices=[
                    {"id": "A", "label": "甲"},
                    {"id": "B", "label": "乙"},
                ]),
                allow_legacy=False,
            )
        projected = child_prompt.project_child_surface(
            prompt="请选择所有正确答案。",
            prompt_format=child_prompt.CHILD_PROMPT_FORMAT,
            interaction_schema=_schema(
                "multi_choice",
                requires_explanation=True,
                choices=[
                    {"id": "A", "label": "甲"},
                    {"id": "B", "label": "乙"},
                ],
            ),
            allow_legacy=False,
        )
        self.assertTrue(projected["interaction_schema"]["requires_explanation"])

    def test_legacy_superscript_is_normalized_but_v2_source_is_rejected(self):
        legacy = child_prompt.project_child_surface(
            prompt="yᵏ 与 x²",
            interaction_schema=_schema(),
            allow_legacy=True,
        )
        self.assertEqual("y^k 与 x^2", legacy["prompt"])
        self.assertTrue(legacy["legacy_compatibility_applied"])

    def test_legacy_v1_explanation_requirement_is_derived_into_v2(self):
        legacy_schema = _schema(
            "single_choice",
            choices=[
                {"id": "A", "label": "第一种关系"},
                {"id": "B", "label": "第二种关系"},
            ],
        )
        legacy_schema["schema_version"] = child_prompt.QUESTION_INTERACTION_SCHEMA_V1
        legacy_schema.pop("requires_explanation")

        projected = child_prompt.project_child_surface(
            prompt="请选择更合适的关系，并说明理由。",
            interaction_schema=legacy_schema,
            allow_legacy=True,
        )

        self.assertEqual(
            child_prompt.QUESTION_INTERACTION_SCHEMA_V2,
            projected["interaction_schema"]["schema_version"],
        )
        self.assertTrue(projected["interaction_schema"]["requires_explanation"])

        answer_only = child_prompt.project_child_surface(
            prompt="请选择更合适的关系。",
            interaction_schema=legacy_schema,
            allow_legacy=True,
        )
        self.assertFalse(answer_only["interaction_schema"]["requires_explanation"])

    def test_real_browser_app_gate(self):
        fixture = _browser_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "child-prompt-v6.json"
            fixture_path.write_text(
                json.dumps(fixture, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "node",
                    str(PROJECT_ROOT / "tests/fixtures/browser_child_prompt_renderer_v51.mjs"),
                    "--index",
                    str(PROJECT_ROOT / "app/local_learning_system/index.html"),
                    "--app",
                    str(PROJECT_ROOT / "app/local_learning_system/app.js"),
                    "--renderer",
                    str(PROJECT_ROOT / "app/local_learning_system/child_prompt_renderer.js"),
                    "--style",
                    str(PROJECT_ROOT / "app/local_learning_system/styles.css"),
                    "--fixture",
                    str(fixture_path),
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(0, report["required_recovery"]["submit_posts"])
        self.assertTrue(report["unavailable"]["form_hidden"])
        self.assertTrue(report["no_network"])


if __name__ == "__main__":
    unittest.main()
