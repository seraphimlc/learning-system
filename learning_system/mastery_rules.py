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

Implemented (M2.5 part 2, §2.3): the unique consecutive C/D counter
(feed_cd_counter / cd_counter) and the state-transition table
(transition_status, incl. T8 "保持 A"). Still out of scope (later M2.5
tasks): §2.4 retest intervals (RETEST_INTERVALS_DAYS), §3 manual-evidence
M0/M1 flows (recheck wiring, action-layer counting), §4 over-diagnosis
linkage, §5 LLM tightening. Recheck *scheduling* is wired elsewhere; this
module only emits the "recheck required" signal (recheck=True).

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

# ---------------------------------------------------------------------------
# §2.3 unique consecutive C/D counter (M2.5 part 2)
# ---------------------------------------------------------------------------
#
# One counter per node, over *system judgment events only* (the events
# decide_verdict produces for eligible attempts). Semantics (proposal §2.3):
#   - scan the node's judgment events in created_at time order;
#   - consecutive verdict ∈ {C, D} increment; verdict ∈ {A, B} resets to 0;
#   - NO_CHANGE events are skipped: neither counted nor breaking the streak
#     ("没测过 ≠ 薄弱" — no event is still no event);
#   - manual (M1) evidence never counts (M1 has its own action-layer counter,
#     §3/§4; it never enters this counter — T13);
#   - count reaching CD_COUNTER_LIMIT (=3) fires the downgrade/recheck signal
#     and resets to 0 ("计数达到 3 → 触发降级/回查并清零").
#
# Input shapes (pure): feed_cd_counter(count, verdict) for the incremental
# "current count + new event" form, cd_counter(events) for the "event
# sequence" form. The wiring layer reads history from mastery_decisions and
# maps each row's decision verdict into an event dict {"verdict": ...,
# "is_manual": ...}.
#
# Interpretation note (ambiguity, per M2.5-1 convention): cd_counter folds
# feed_cd_counter over the whole sequence, so trigger resets are reproduced —
# it derives the same value the operational counter would hold. A retroactive
# "pending trigger" buried in pre-M2.5 history is therefore *not* surfaced by
# cd_counter; the wiring layer bootstraps from the derived value and lets the
# next qualifying event drive the downgrade. This is the conservative choice
# (under-claiming is preferred over over-claiming, §2.3 升降级不对称).

CD_COUNTER_LIMIT = 3


def feed_cd_counter(count: int, verdict: str, *, manual: bool = False) -> dict:
    """One new judgment event updates the consecutive C/D counter (§2.3).

    Args:
        count: the counter value before this event (non-negative int).
        verdict: one of D/C/B/A/NO_CHANGE (output of decide_verdict).
        manual: True when the event is manual M1 evidence — never counted.

    Returns:
        {"count": int, "triggered": bool} — the new counter value, and whether
        this event pushed the streak to CD_COUNTER_LIMIT (trigger fires and the
        count resets to 0).
    """
    if not isinstance(count, int) or count < 0:
        raise ValueError(f"count must be a non-negative int, got {count!r}")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")
    if manual:
        return {"count": count, "triggered": False}
    if verdict in (VERDICT_A, VERDICT_B):
        return {"count": 0, "triggered": False}
    if verdict in (VERDICT_C, VERDICT_D):
        next_count = count + 1
        if next_count >= CD_COUNTER_LIMIT:
            return {"count": 0, "triggered": True}
        return {"count": next_count, "triggered": False}
    # NO_CHANGE: skipped — neither counted nor breaking the streak.
    return {"count": count, "triggered": False}


def cd_counter(events: list[dict]) -> int:
    """Derive the consecutive C/D counter from a judgment-event sequence (§2.3).

    `events` is a chronological list of dicts, each with a "verdict" key in the
    five-value enum and an optional "is_manual" bool. Equivalent to folding
    feed_cd_counter over the sequence (trigger resets reproduced; see the
    interpretation note above).
    """
    count = 0
    for event in events:
        count = feed_cd_counter(
            count, event["verdict"], manual=event.get("is_manual", False)
        )["count"]
    return count


def _transition_result(status, counter, recheck, reason_code, reason):
    return {
        "status": status,
        "counter": counter,
        "recheck": recheck,
        "reason_code": reason_code,
        "reason": reason,
    }


def transition_status(
    current_status: str | None, verdict: str, window: list[dict] | None = None,
    counter: int = 0,
) -> dict:
    """Apply the §2.3 state-transition table to one judgment event.

    Args:
        current_status: None (未建档, no learner_node_status row) or one of
            A/B/C/D (STORAGE_STATES).
        verdict: one of D/C/B/A/NO_CHANGE (output of decide_verdict). R1
            blocking_evidence produces verdict=D, so the table's
            "blocking_evidence" column is the verdict=D branch here.
        window: the rolling evidence window (list of attempt dicts, including
            the current attempt) — read only by the C -> B gate
            "window strong >= 2" (T10/T11).
        counter: the node's consecutive C/D counter value *before* this event.

    Returns:
        {"status": str|None, "counter": int, "recheck": bool,
         "reason": str, "reason_code": str} — new status (None = unfiled),
        counter value to persist, whether a recheck signal fires (count reached
        CD_COUNTER_LIMIT; A/B/C rows, T9), and a machine-readable code.

    Table (proposal §2.3), per row:
        A:   A/B verdict keep A; C/D count (3 -> C, recheck); D -> D
        B:   A -> A; B keeps B; C/D count (3 -> C, recheck); D -> D
        C:   A -> A (AGG already satisfied); B -> B only if window strong >= 2
             else keep C; C/D count (3 -> recheck only); D -> D
        D:   A/B -> B (never A); C/D keeps D; D keeps D
        None: files A/B/C/D on first qualifying verdict; NO_CHANGE never stored

    Downgrade is direct A/B -> C (no A->B->C ladder) and only via the counter
    (3 consecutive C/D); a single strong verdict never overwrites A; upgrade
    is conservative (C -> B needs 2 strong) while downgrade is sensitive
    (§2.3 升降级不对称).
    """
    if current_status is not None and current_status not in STORAGE_STATES:
        raise ValueError(
            f"current_status must be None or one of {sorted(STORAGE_STATES)}, "
            f"got {current_status!r}"
        )
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")
    window = list(window) if window is not None else []

    feed = feed_cd_counter(counter, verdict)
    new_counter = feed["count"]
    triggered = feed["triggered"]

    if verdict == VERDICT_NO_CHANGE:
        return _transition_result(
            current_status, counter, False, "no_change",
            "NO_CHANGE verdict is never stored: status and counter unchanged.",
        )

    if verdict == VERDICT_D:  # R1 blocking evidence -> D (blocking column wins)
        return _transition_result(
            VERDICT_D, new_counter, False, "blocking_d",
            f"Blocking evidence on {current_status!r} -> D (direct jump, "
            "blocking column beats the counter column).",
        )

    if verdict == VERDICT_A:
        if current_status == VERDICT_D:
            return _transition_result(
                VERDICT_B, new_counter, False, "promote_b",
                "D never jumps to A: verdict=A on D -> B (repair confirmed).",
            )
        if current_status == VERDICT_A:
            return _transition_result(
                VERDICT_A, new_counter, False, "keep_a",
                "verdict=A on A keeps A.",
            )
        return _transition_result(
            VERDICT_A, new_counter, False, "promote_a",
            f"verdict=A on {current_status!r} -> A (AGG fully satisfied).",
        )

    if verdict == VERDICT_B:
        if current_status == VERDICT_D:
            return _transition_result(
                VERDICT_B, new_counter, False, "promote_b",
                "D repair confirmed by verdict=B -> B.",
            )
        if current_status == VERDICT_C:
            if len(_strong_attempts(window)) >= 2:
                return _transition_result(
                    VERDICT_B, new_counter, False, "promote_b",
                    "C + window strong >= 2 -> B (T11); single strong is not "
                    "enough (T10, 防单条翻案).",
                )
            return _transition_result(
                VERDICT_C, new_counter, False, "keep_c",
                "C + window strong < 2 keeps C (single strong may be "
                "fluctuation, 防单条翻案).",
            )
        if current_status == VERDICT_B:
            return _transition_result(
                VERDICT_B, new_counter, False, "keep_b",
                "verdict=B on B keeps B.",
            )
        if current_status == VERDICT_A:
            return _transition_result(
                VERDICT_A, new_counter, False, "keep_a",
                "verdict=B on A keeps A (single strong never overwrites the "
                "accumulated A archive, v51 preserve semantics).",
            )
        return _transition_result(
            VERDICT_B, new_counter, False, "promote_b",
            "verdict=B files a previously unfiled node as B.",
        )

    # verdict == VERDICT_C (non-blocking C/D event; D verdict handled above).
    if triggered:
        if current_status in (VERDICT_A, VERDICT_B):
            return _transition_result(
                VERDICT_C, new_counter, True, "cd_trigger_downgrade",
                f"{current_status} + 3 consecutive C/D -> C (direct downgrade, "
                "no ladder), counter reset, recheck fired (T9).",
            )
        return _transition_result(
            VERDICT_C if current_status is None else current_status,
            new_counter, True, "cd_trigger_recheck",
            f"{current_status!r} + 3 consecutive C/D -> counter reset, recheck "
            "fired (C keeps C / D keeps D / unfiled files C).",
        )
    if current_status == VERDICT_D:
        return _transition_result(
            VERDICT_D, new_counter, False, "keep_d",
            "C/D verdict on D keeps D (回查/修复中).",
        )
    if current_status in (VERDICT_A, VERDICT_B, VERDICT_C):
        return _transition_result(
            current_status, new_counter, False, "cd_count",
            f"Consecutive C/D counter {counter} -> {new_counter}; "
            f"{current_status} kept.",
        )
    return _transition_result(
        VERDICT_C, new_counter, False, "unfiled_c",
        "First C/D verdict files a previously unfiled node as C (有据建档即弱).",
    )
