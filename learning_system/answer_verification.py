# learning_system/answer_verification.py
"""Math answer verification via sympy (calculation-answer底线校验)."""
from __future__ import annotations

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
