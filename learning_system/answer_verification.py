# learning_system/answer_verification.py
"""Math answer verification via sympy (calculation-answer底线校验)."""
from __future__ import annotations

import re

import sympy as sp


def is_math_equivalent(a: str, b: str, *, tolerance: float = 1e-9) -> bool:
    """True if two math answer strings are equivalent (3/2 == 1.5 == 6/4).

    注：符号等价（如 is_math_equivalent("x", "x")）也返回 True——超出
    "算术题底线校验"语义但无害；如需收紧，后续计划在调用侧限定数值域。
    """
    try:
        diff = sp.simplify(sp.sympify(a) - sp.sympify(b))
    except (sp.SympifyError, TypeError, ValueError):
        return False
    if diff == 0:
        return True
    try:
        return abs(float(diff)) <= tolerance
    except (TypeError, ValueError):
        return False


_CALC_PATTERN = re.compile(r"计算[:：]?\s*([0-9+\-*/×÷^().\s]+)")
_UNICODE_MAP = {"×": "*", "÷": "/", "−": "-", "－": "-"}


def extract_calculation(prompt: str) -> str | None:
    """Extract a machine-checkable arithmetic expression from a prompt, or None.

    边界（底线校验可接受）："计算下列各题：…"（非冒号）返回 None；
    "计算：1/2 与 1/3 的大小"会误截半表达式——审计报告需据此解读计数。
    """
    match = _CALC_PATTERN.search(prompt)
    if not match:
        return None
    candidate = match.group(1).strip()
    for src, dst in _UNICODE_MAP.items():
        candidate = candidate.replace(src, dst)
    try:
        sp.sympify(candidate)
    except (sp.SympifyError, TypeError, ValueError):
        return None
    return candidate
