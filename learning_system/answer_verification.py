# learning_system/answer_verification.py
"""Math answer verification via sympy (calculation-answer底线校验)."""
from __future__ import annotations

import re

import sympy as sp


def is_math_equivalent(a: str, b: str, *, tolerance: float = 1e-9) -> bool:
    """True if two math answer strings are equivalent (3/2 == 1.5 == 6/4).

    注：符号等价（如 is_math_equivalent("x", "x")）也返回 True——超出
    "算术题底线校验"语义但无害；如需收紧，后续计划在调用侧限定数值域。
    ×/÷/−/－ 等 Unicode 运算符会在 sympify 前归一化为 ASCII（答案卡排版兼容）。
    """
    try:
        diff = sp.simplify(
            sp.sympify(_normalize_operators(a)) - sp.sympify(_normalize_operators(b))
        )
    except (sp.SympifyError, TypeError, ValueError):
        return False
    if diff == 0:
        return True
    try:
        return abs(float(diff)) <= tolerance
    except (TypeError, ValueError):
        return False


# 字符类中 `^` 居中才是字面量（挪到开头会变成取反）；成员须与 _UNICODE_MAP 键同步（−/－ 在此，映射才可达）
_CALC_PATTERN = re.compile(r"计算[:：]?\s*([0-9+\-*/×÷−－^().\s]+)")
_UNICODE_MAP = {"×": "*", "÷": "/", "−": "-", "－": "-"}


def _normalize_operators(text: str) -> str:
    """Replace Unicode math operator glyphs (× ÷ − －) with ASCII (* / -).

    答案卡排版常用数学区/全角操作符，sympify 不认识它们；统一归一化后
    再解析。extract_calculation 与 is_math_equivalent 共用。
    """
    for src, dst in _UNICODE_MAP.items():
        text = text.replace(src, dst)
    return text


def extract_calculation(prompt: str) -> str | None:
    """Extract a machine-checkable arithmetic expression from a prompt, or None.

    边界（底线校验可接受）："计算下列各题：…"（非冒号）返回 None；
    "计算：1/2 与 1/3 的大小"会误截半表达式——审计报告需据此解读计数。
    """
    match = _CALC_PATTERN.search(prompt)
    if not match:
        return None
    candidate = _normalize_operators(match.group(1).strip())
    try:
        sp.sympify(candidate)
    except (sp.SympifyError, TypeError, ValueError):
        return None
    return candidate


def verify_expected_answer(prompt: str, expected_answer: str) -> dict:
    """Verify a calculation item's expected answer. Never raises for str inputs.

    verdict: verified | mismatch | unverifiable
    """
    if not expected_answer or not str(expected_answer).strip():
        return {"verdict": "unverifiable", "reason": "empty expected answer"}
    expression = extract_calculation(prompt)
    if expression is None:
        return {"verdict": "unverifiable", "reason": "no machine-checkable expression in prompt"}
    if not is_math_equivalent(expression, expected_answer):
        return {"verdict": "mismatch", "expression": expression, "expected": expected_answer}
    return {"verdict": "verified", "expression": expression}
