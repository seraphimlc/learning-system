"""Unified mastery verdict core (M2.5 part 1).

Contract: docs/design/specs/2026-08-20-mastery-criteria-proposal.md
- §2.1 storage states are exactly A/B/C/D; the judgment intermediate is a
  5-value verdict {D, C, B, A, NO_CHANGE}, and NO_CHANGE is never persisted
  ("没测过 ≠ 薄弱" — no row / keep-as-is, never written as C).
- §2.2 rules R1-R6 (thresholds 0.85 / 0.60, reasoning-gap interception,
  strong-evidence predicate) and window AGG conditions C1-C6.

Pure module: no I/O, no sqlite. It decides the verdict for one eligible
judgment event (one diagnostic, no-hint, gate-passed, voice-verifiable,
non-manual attempt) plus the node's rolling 90-day window of eligible
attempts (which must include the current one). Eligibility filtering,
evidence-gate evaluation and persistence belong to the wiring layer
(M2.5 integration into daily_runtime / flow_nodes orchestrator).

Per-judgment-event semantics (§2.2): one eligible attempt = one judgment
event. The verdict is decided in rule order:

    R1 blocking_evidence -> D
    R2 wrong | ratio < 0.60 -> C
    R3 partial | explanation_score < 2 | reasoning gap -> C
    R4 correct & ratio >= 0.85 & exp >= 2 & sound & no gap  (strong)
         -> A if window AGG (C1-C6) satisfied, else B
    R5 correct & 0.60 <= ratio < 0.85 & exp >= 2 & sound -> B
    R6 everything else (ineligible / no valid evidence) -> NO_CHANGE

Strong evidence (§2.2 AGG): correct + ratio >= 0.85 + explanation_score >= 2
+ reasoning_soundness == "sound" + no reasoning gap.

Reasoning-gap predicate (evolution._has_high_score_reasoning_gap semantics,
proposal §2.2 R3 / §1 fact 3): reasoning_soundness in {incomplete, unsound,
unclear} OR evidence_strength in {weak, insufficient} OR next_evidence_need
non-empty. This is the "A 档补上 v51 缺失的推理缺口检查" (C4 + R3).

Not implemented here (later M2.5 tasks): §2.3 consecutive C/D counter and
state transitions (incl. T8 "保持 A"), §2.4 retest intervals
(RETEST_INTERVALS_DAYS), §3 manual-evidence M0/M1 flows, §4 over-diagnosis
linkage, §5 LLM tightening.

Run: python3 -m unittest tests.test_mastery_rules
"""

from __future__ import annotations

from datetime import date, datetime

# ---------------------------------------------------------------------------
# Enumerations (proposal §2.1)
# ---------------------------------------------------------------------------

VERDICT_D = "D"
VERDICT_C = "C"
VERDICT_B = "B"
VERDICT_A = "A"
VERDICT_NO_CHANGE = "NO_CHANGE"

VERDICTS = frozenset({VERDICT_D, VERDICT_C, VERDICT_B, VERDICT_A, VERDICT_NO_CHANGE})
STORAGE_STATES = frozenset({VERDICT_A, VERDICT_B, VERDICT_C, VERDICT_D})

# ---------------------------------------------------------------------------
# Thresholds & rule constants (proposal §2.2, inherited from blueprint §12 /
# evolution.py:677-682; exact copies of the proposal numbers)
# ---------------------------------------------------------------------------

RATIO_STRONG = 0.85          # correct band floor for strong evidence (R4)
RATIO_WEAK = 0.60            # below this a correct answer is still weak (R2)
EXPLANATION_SCORE_MIN = 2    # explanation_score < 2 -> C (R3)
STRONG_SOUNDNESS = "sound"   # reasoning_soundness required by R4/R5

REASONING_GAP_SOUNDNESS = frozenset({"incomplete", "unsound", "unclear"})
WEAK_EVIDENCE_STRENGTH = frozenset({"weak", "insufficient"})
NO_NEXT_EVIDENCE_NEED = frozenset({None, "", "none"})

DUAL_ROLES = frozenset({"confirmation_core", "confirmation_transfer"})  # C3

AGG_CONDITIONS = ("C1", "C2", "C3", "C4", "C5", "C6")

# ---------------------------------------------------------------------------
# Evidence shape
# ---------------------------------------------------------------------------
#
# AttemptEvidence (one eligible judgment event / one window entry), dict:
#   result:            "correct" | "wrong" | "partial"
#   score_points:      float (score)
#   max_points:        float (denominator; ratio = score / max)
#   explanation_score: int | None        (>= 2 required for B/A bands)
#   reasoning_soundness: str | None      ("sound" | "incomplete" | "unsound" | "unclear")
#   evidence_strength: str | None        ("strong" | "weak" | "insufficient" | ...)
#   next_evidence_need: str | None       (non-empty => reasoning gap)
#   blocking_evidence: bool              (explicit cannot-start / prereq break)
#   structure_fingerprint: str           (question type/structure id, C2)
#   purpose_role:        str             ("confirmation_core" | "confirmation_transfer" | ...)
#   created_at:          date | datetime | "YYYY-MM-DD[ T...]" string (C5 / C4 ordering)
#   gate_passed:         bool = True     (v51 full-chain evidence gate)
#   purpose:             str = "diagnostic"
#   hint_policy:         str = "no_hint"
#   mastery_update_eligible: bool = True
#   voice_verifiable:    bool = True     (_attempt_recognition_allows_mastery)
#   is_manual:           bool = False    (M0/M1 never produce judgment events)
#   analysis_valid:      bool = True     (answer_analysis valid)
#
# Verdict output:
#   {"code": 'D'|'C'|'B'|'A'|'NO_CHANGE',
#    "decision": str, "reason": str,
#    "is_strong": bool,
#    "attrs": {"reason_code": str, "ratio": float, "window_ratio": float,
#              "strong_count": int, "fingerprint_count": int,
#              "roles": list, "natural_days": int,
#              "satisfied": list, "failed": list, ...}}


def _ratio(evidence: dict) -> float:
    try:
        max_points = float(evidence.get("max_points") or 0)
        score = float(evidence.get("score_points") or 0)
    except (TypeError, ValueError):
        return 0.0
    return score / max_points if max_points else 0.0


def _as_date(value):
    """Normalize created_at to a date; raises ValueError on unparseable input."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        head = value.strip()[:10]
        try:
            return datetime.strptime(head, "%Y-%m-%d").date()
        except ValueError:
            pass
    raise ValueError(
        f"created_at must be a date, datetime or 'YYYY-MM-DD' string, got {value!r}"
    )


def _explanation_score(evidence: dict) -> int:
    try:
        return int(evidence.get("explanation_score") or 0)
    except (TypeError, ValueError):
        return 0


def has_reasoning_gap(evidence: dict) -> bool:
    """Reasoning-gap predicate (proposal §2.2 R3 / evolution._has_high_score_reasoning_gap)."""
    return (
        evidence.get("reasoning_soundness") in REASONING_GAP_SOUNDNESS
        or evidence.get("evidence_strength") in WEAK_EVIDENCE_STRENGTH
        or evidence.get("next_evidence_need") not in NO_NEXT_EVIDENCE_NEED
    )


def is_strong_evidence(evidence: dict) -> bool:
    """Strong evidence = R4 front half: correct + ratio>=0.85 + exp>=2 + sound + no gap."""
    return (
        evidence.get("result") == "correct"
        and _ratio(evidence) >= RATIO_STRONG
        and _explanation_score(evidence) >= EXPLANATION_SCORE_MIN
        and evidence.get("reasoning_soundness") == STRONG_SOUNDNESS
        and not has_reasoning_gap(evidence)
    )


def is_eligible(evidence: dict) -> bool:
    """Judgment-event eligibility (§2.2 eligibility; defaults are eligible)."""
    return (
        evidence.get("gate_passed", True) is True
        and evidence.get("mastery_update_eligible", True) is True
        and evidence.get("purpose", "diagnostic") == "diagnostic"
        and evidence.get("hint_policy", "no_hint") == "no_hint"
        and evidence.get("voice_verifiable", True) is True
        and evidence.get("is_manual", False) is not True
        and evidence.get("analysis_valid", True) is True
    )


def window_ratio(window: list[dict]) -> float:
    """Window ratio = sum(score) / sum(max) over all window attempts (C6)."""
    max_points = sum(float(item.get("max_points") or 0) for item in window)
    score = sum(float(item.get("score_points") or 0) for item in window)
    return score / max_points if max_points else 0.0


def _classify(evidence: dict) -> str:
    """Non-AGG attempt classification for the C4 scan (C/D / strong / other)."""
    if not is_eligible(evidence):
        return "NO_CHANGE"
    ratio = _ratio(evidence)
    if evidence.get("blocking_evidence"):
        return "D"
    if evidence.get("result") == "wrong" or ratio < RATIO_WEAK:
        return "C"
    if (
        evidence.get("result") == "partial"
        or _explanation_score(evidence) < EXPLANATION_SCORE_MIN
        or has_reasoning_gap(evidence)
    ):
        return "C"
    if is_strong_evidence(evidence):
        return "strong"
    if (
        evidence.get("result") == "correct"
        and RATIO_WEAK <= ratio < RATIO_STRONG
        and _explanation_score(evidence) >= EXPLANATION_SCORE_MIN
        and evidence.get("reasoning_soundness") == STRONG_SOUNDNESS
    ):
        return "B"
    return "NO_CHANGE"


def _c4_unrepaired_weakness(evidence: dict, window: list[dict]) -> bool:
    """C4: no unrepaired C/D newer than every strong verdict.

    Literal reading of proposal C4: if the window contains any C/D verdict,
    the most recent one must be followed by at least one strong verdict
    (repair / retest confirmation), and that strong verdict must not be
    followed by a new C/D — which is implied by "most recent C/D" once a
    strong strictly after it exists.
    """
    ordered = sorted(
        ((_as_date(item.get("created_at")), index, item) for index, item in enumerate(window)),
        key=lambda entry: (entry[0], entry[1]),
    )
    classes = [_classify(entry[2]) for entry in ordered]
    cd_positions = [i for i, cls in enumerate(classes) if cls in ("C", "D")]
    if not cd_positions:
        return True
    last_cd = cd_positions[-1]
    return any(cls == "strong" for cls in classes[last_cd + 1:])


def _strong_attempts(window: list[dict]) -> list[dict]:
    return [item for item in window if is_strong_evidence(item)]


def _strong_fingerprint_count(window: list[dict]) -> int:
    return len({
        str(item.get("structure_fingerprint") or "").strip()
        for item in _strong_attempts(window)
        if str(item.get("structure_fingerprint") or "").strip()
    })


def _strong_roles(window: list[dict]) -> list[str]:
    return sorted({str(item.get("purpose_role") or "") for item in _strong_attempts(window)})


def _strong_days(window: list[dict]) -> int:
    return len({_as_date(item.get("created_at")) for item in _strong_attempts(window)})


def aggregate_conditions(evidence: dict, window: list[dict]) -> dict[str, bool]:
    """Evaluate AGG conditions C1-C6 over the window (only meaningful for strong evidence)."""
    c1 = len(_strong_attempts(window)) >= 2

    c2 = _strong_fingerprint_count(window) >= 2

    c3 = DUAL_ROLES.issubset(set(_strong_roles(window)))

    c4 = _c4_unrepaired_weakness(evidence, window)

    c5 = _strong_days(window) >= 2

    c6 = window_ratio(window) >= RATIO_STRONG

    return {"C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5, "C6": c6}


def _verdict(code: str, decision: str, reason: str, *, is_strong: bool, attrs: dict) -> dict:
    return {
        "code": code,
        "decision": decision,
        "reason": reason,
        "is_strong": is_strong,
        "attrs": attrs,
    }


def decide_verdict(evidence: dict, window: list[dict] | None = None) -> dict:
    """Decide the verdict for one eligible judgment event (proposal §2.2 R1-R6).

    `window` is the node's rolling-90-day list of eligible attempts and must
    include `evidence` (C1 counts the current attempt; C4/C5/C6 read the
    window). If omitted, defaults to a single-attempt window.
    """
    if window is None:
        window = [evidence]
    window = list(window)

    ratio = _ratio(evidence)

    if not is_eligible(evidence):  # R6: gate fail / practice / manual / no voice
        return _verdict(
            VERDICT_NO_CHANGE,
            "no_change_ineligible",
            "Evidence does not meet judgment-event eligibility (gate/purpose/hint/"
            "voice/manual/analysis); NO_CHANGE is never stored.",
            is_strong=False,
            attrs={"reason_code": "ineligible", "ratio": ratio, "eligible": False},
        )

    if evidence.get("blocking_evidence"):  # R1
        return _verdict(
            VERDICT_D,
            "D_blocking",
            "Blocking evidence (explicit cannot-start / prerequisite break) -> D candidate.",
            is_strong=False,
            attrs={"reason_code": "blocking", "ratio": ratio, "eligible": True},
        )

    if evidence.get("result") == "wrong" or ratio < RATIO_WEAK:  # R2
        reason_code = "wrong" if evidence.get("result") == "wrong" else "ratio_below_0.60"
        return _verdict(
            VERDICT_C,
            "C_weak",
            f"Wrong result or ratio {ratio:.3f} < 0.60 -> C (weak band).",
            is_strong=False,
            attrs={"reason_code": reason_code, "ratio": ratio, "eligible": True},
        )

    if (
        evidence.get("result") == "partial"
        or _explanation_score(evidence) < EXPLANATION_SCORE_MIN
        or has_reasoning_gap(evidence)
    ):  # R3
        if has_reasoning_gap(evidence):
            reason_code = "reasoning_gap"
        elif evidence.get("result") == "partial":
            reason_code = "partial"
        else:
            reason_code = "explanation_below_2"
        return _verdict(
            VERDICT_C,
            "C_weak",
            "Partial result, explanation_score < 2, or reasoning gap -> C "
            "(overrides high-score B/A; prevents 'answer right, process missing').",
            is_strong=False,
            attrs={"reason_code": reason_code, "ratio": ratio, "eligible": True},
        )

    if is_strong_evidence(evidence):  # R4
        conds = aggregate_conditions(evidence, window)
        satisfied = sorted(c for c, ok in conds.items() if ok)
        failed = sorted(c for c, ok in conds.items() if not ok)
        strong_count = len(_strong_attempts(window))
        if not failed:  # AGG all satisfied -> A
            return _verdict(
                VERDICT_A,
                "A_agg_satisfied",
                "Strong evidence and window AGG conditions C1-C6 all satisfied -> A.",
                is_strong=True,
                attrs={
                    "reason_code": "agg_satisfied",
                    "ratio": ratio,
                    "window_ratio": window_ratio(window),
                    "strong_count": strong_count,
                    "fingerprint_count": _strong_fingerprint_count(window),
                    "roles": _strong_roles(window),
                    "natural_days": _strong_days(window),
                    "satisfied": satisfied,
                    "failed": failed,
                    "eligible": True,
                },
            )
        return _verdict(
            VERDICT_B,
            "B_strong_agg_incomplete",
            "Strong single evidence but window AGG not fully satisfied "
            f"(failed: {', '.join(failed)}) -> B, not A.",
            is_strong=True,
            attrs={
                "reason_code": "agg_incomplete",
                "ratio": ratio,
                "window_ratio": window_ratio(window),
                "strong_count": strong_count,
                "fingerprint_count": _strong_fingerprint_count(window),
                "roles": _strong_roles(window),
                "natural_days": _strong_days(window),
                "satisfied": satisfied,
                "failed": failed,
                "eligible": True,
            },
        )

    if (
        evidence.get("result") == "correct"
        and RATIO_WEAK <= ratio < RATIO_STRONG
        and _explanation_score(evidence) >= EXPLANATION_SCORE_MIN
        and evidence.get("reasoning_soundness") == STRONG_SOUNDNESS
    ):  # R5
        return _verdict(
            VERDICT_B,
            "B_correct_60_85",
            f"Correct with ratio {ratio:.3f} in [0.60, 0.85) and sound explanation -> B.",
            is_strong=False,
            attrs={"reason_code": "correct_60_85", "ratio": ratio, "eligible": True},
        )

    return _verdict(  # R6
        VERDICT_NO_CHANGE,
        "no_change_no_valid_evidence",
        "No valid evidence (missing reasoning info / unclassifiable) -> NO_CHANGE, never stored.",
        is_strong=False,
        attrs={"reason_code": "no_valid_evidence", "ratio": ratio, "eligible": True},
    )


# Proposal §2.2 names the contract mastery_verdict(evidence, window);
# decide_verdict is the canonical entry point, this is a compatibility alias.
mastery_verdict = decide_verdict
