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
(transition_status, incl. T8 "保持 A").

Implemented (M2.5 part 3, §2.4/§3): the retest-interval algorithm
(next_retest_at / RETEST_INTERVALS_DAYS, incl. the 会审修订 B branch) and the
manual-evidence M0/M1 flows (manual_entry: M0 retest signal with zero
judgment-side effect; M1 action-layer independent counting with the same
threshold 3, recheck + reset, never a direct downgrade). Recheck *scheduling*
and question arrangement are wired elsewhere; this module only emits the
signals (recheck=True / retest=True).

Implemented (M2.5 part 4, §4/§5): the over-diagnosis gate rulings
(diagnosis_budget gate #1, recheck_depth_limit gate #2, gate #3 alignment via
the unique counter) and the LLM tightening boundary (apply_llm_tightening /
deterministic_fallback / llm_recommendation_usable, incl. anchors T14/T15).

Still out of scope (later M2.5 tasks): runtime wiring (M2.5-5).

Run: python3 -m unittest tests.test_mastery_rules
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

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


# ---------------------------------------------------------------------------
# §2.4 retest intervals (M2.5 part 3)
# ---------------------------------------------------------------------------
#
# RETEST_INTERVALS_DAYS = [1, 3, 7, 14, 30] (cap 30 days). `depth` is the
# number of verdict=A judgment events since the node's most recent
# status-change-to-A anchor, capped at MAX_RETEST_DEPTH (= 4, the interval
# index cap): next_retest_at(node) = last_A_event_at + intervals[depth].
#
# Retest-pass semantics (会审修订): a retest passes iff it produces
# verdict=A, and verdict=A is decided by decide_verdict's *window-level* AGG
# (C1-C6 over historical strong evidence, §2.2) — never by a single attempt,
# which yields at most B (R4/R5). Hence there is no "single-attempt A ->
# depth+1 -> daily retest death loop": depth advances only after a
# window-level A (T23).
#
# Branch semantics:
#   - verdict=A (窗口级复测通过): depth +1, next retest at intervals[depth].
#   - verdict=B (会审修订): depth unchanged, reschedule at the current
#     interval — depth>=1 -> intervals[depth]; depth=0 (never-A, e.g. the
#     C->B->A path) -> 1 day, or 3 days once >=3 consecutive B verdicts
#     (b_count = consecutive-B judgment-event count including the current
#     event; the caller passes the count BEFORE this event, the returned
#     "b_count" is the value after).
#   - verdict=C/D (复测失败): reset depth 0, interval 1 day. The downgrade
#     itself is driven by the §2.3 unique counter (part 2), not here.
#
# Interpretation note (proposal ambiguity, per M2.5-1 convention): the
# interval lookup for verdict=A uses the *incoming* depth, so the achievement
# event itself schedules +1 day (T16: "A 达成 -> 次日复测(1 天)"), and each
# further verdict=A schedules intervals[new depth] -> 3 -> 7 -> 14 -> 30
# (capped, maintain 30). This is the reading that reproduces the anchor
# sequence [1,3,7,14,30] exactly; the alternative (look up with the
# incremented depth) would schedule +3 days right after A 达成, contradicting
# T16's first step.

RETEST_INTERVALS_DAYS = [1, 3, 7, 14, 30]      # §2.4, cap 30 days
MAX_RETEST_DEPTH = len(RETEST_INTERVALS_DAYS) - 1  # 4: interval index cap
B_COUNT_LONG_INTERVAL_THRESHOLD = 3             # depth=0 B: b_count>=3 -> 3 days


def _retest_result(new_depth, days, b_count, now, reason_code, reason):
    result = {
        "new_depth": new_depth,
        "days": days,
        "b_count": b_count,
        "next_retest_at": None,
        "reason_code": reason_code,
        "reason": reason,
    }
    if now is not None:
        result["next_retest_at"] = _as_date(now) + timedelta(days=days)
    return result


def next_retest_at(depth, verdict, b_count=0, now=None) -> dict:
    """Retest-interval schedule update for one judgment event (§2.4).

    Args:
        depth: verdict=A count since the last status-change-to-A anchor,
            capped at MAX_RETEST_DEPTH. Values above the cap are treated as
            the cap (the "维持 30 天" semantic); negative/non-int raise.
        verdict: one of D/C/B/A/NO_CHANGE (output of decide_verdict).
        b_count: consecutive-B judgment-event count BEFORE this event
            (non-negative int); used only by the depth=0 B branch.
        now: date | datetime | "YYYY-MM-DD" for the absolute next_retest_at
            (date granularity, consistent with _as_date); None skips it.

    Returns:
        {"new_depth", "days", "b_count", "next_retest_at", "reason_code",
         "reason"}: the depth to persist, days until the next retest (the
        wiring layer adds them to `now`), the consecutive-B count after this
        event, the absolute retest date when `now` is given (None for
        NO_CHANGE: never stored -> never rescheduled), and a code/reason.
    """
    if not isinstance(depth, int) or depth < 0:
        raise ValueError(f"depth must be a non-negative int, got {depth!r}")
    if not isinstance(b_count, int) or b_count < 0:
        raise ValueError(f"b_count must be a non-negative int, got {b_count!r}")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")

    if verdict == VERDICT_NO_CHANGE:  # never stored -> never reschedules
        return _retest_result(
            depth, 0, b_count, None, "no_change",
            "NO_CHANGE is never stored: no schedule change.",
        )

    if verdict == VERDICT_A:  # 窗口级复测通过 -> 深度+1, 按当前深度索引排下次
        new_depth = min(depth + 1, MAX_RETEST_DEPTH)
        days = RETEST_INTERVALS_DAYS[min(depth, MAX_RETEST_DEPTH)]
        return _retest_result(
            new_depth, days, 0, now, "a_advance",
            f"verdict=A (window-level AGG pass): depth {depth} -> {new_depth}, "
            f"next retest in {days} day(s).",
        )

    if verdict == VERDICT_B:  # 深度不变, 按当前间隔重排 (会审修订)
        next_b = b_count + 1
        if depth >= 1:
            days = RETEST_INTERVALS_DAYS[min(depth, MAX_RETEST_DEPTH)]
            return _retest_result(
                depth, days, next_b, now, "b_repeat_interval",
                f"verdict=B at depth {depth} (>=1): depth unchanged, reschedule "
                f"at the current interval {days} day(s).",
            )
        days = 3 if next_b >= B_COUNT_LONG_INTERVAL_THRESHOLD else 1
        return _retest_result(
            depth, days, next_b, now, "b_depth0_short_interval",
            f"verdict=B at depth 0 (never-A): {next_b} consecutive B verdict(s) "
            f"-> {days} day(s).",
        )

    # verdict == C/D: 复测失败 -> 归零重置 (深度 0、间隔 1 天)
    return _retest_result(
        0, RETEST_INTERVALS_DAYS[0], 0, now, "cd_reset",
        f"verdict={verdict}: retest failed, depth reset to 0, interval reset "
        "to 1 day.",
    )


# ---------------------------------------------------------------------------
# §3 manual evidence M0/M1 (M2.5 part 3)
# ---------------------------------------------------------------------------
#
# M0 (child self-report, unconfirmed): triggers ONE system-internal retest
# (1-2 questions, same-structure / near-transfer) as a teaching action — this
# module only emits the "retest" signal; the wiring layer arranges the
# questions. Judgment side is zero (会审修订 "未确认 ≠ 薄弱"): M0 itself
# produces no judgment event, no counting, no downgrade, no promotion, no
# archive write.
#
# M1 (child self-report + parent confirmation; the weekly-summary batch
# confirmation backfills previously M0 entries into M1 — a reclassification
# into this same path, carrier marking belongs to M4): also triggers one
# system-internal retest, AND counts on the *action-layer independent
# counter* (threshold 3, deliberately the same number as the unique counter
# CD_COUNTER_LIMIT per §4 "同阈值 3"). 3 consecutive M1 entries trigger the
# recheck (回查) action and reset to 0. M1 never directly downgrades to C/D
# and never writes a judgment event: only the system-internal retest answers
# (decide_verdict on real attempts) feed the §2.3 unique counter, which is
# the only path that can downgrade (T13/T20).
#
# Interpretation notes (proposal ambiguity, per M2.5-1 convention): (1) M0
# leaves the M1 action counter untouched — it neither increments nor resets
# it (zero judgment-side effect); (2) whether a system judgment event between
# two M1 entries breaks the streak is a wiring-layer policy — the caller
# controls what it feeds into `count` (mirroring how cd_counter's caller
# feeds event sequences; T20 assumes no system event interleaves).

MANUAL_MODE_M0 = "M0"
MANUAL_MODE_M1 = "M1"
MANUAL_MODES = frozenset({MANUAL_MODE_M0, MANUAL_MODE_M1})
MANUAL_RECHECK_LIMIT = CD_COUNTER_LIMIT  # 动作层独立计数, 阈值同 3 (§3/§4)


def manual_entry(mode: str, count: int = 0) -> dict:
    """Record one manual-evidence entry (M0/M1, §3) and emit its signals.

    Args:
        mode: "M0" (child self-report, unconfirmed) or "M1" (parent-
            confirmed, including weekly-batch backfill).
        count: the action-layer M1 counter value BEFORE this entry
            (non-negative int; M0 ignores it but must still be valid).

    Returns:
        {"mode", "retest", "counted", "count", "recheck",
         "judgment_event", "downgrade", "reason_code", "reason"}:
        - retest: True for both modes — one system-internal retest signal
          (教学动作; the wiring layer arranges 1-2 questions);
        - counted: True only for M1 (action-layer independent count);
        - count: the action-layer M1 counter AFTER this entry (M0: unchanged;
          M1: +1, reset to 0 when MANUAL_RECHECK_LIMIT is reached);
        - recheck: True when the 3rd consecutive M1 fires the 回查 action;
        - judgment_event / downgrade: always False — M0/M1 never enter the
          judgment side and never directly downgrade.
    """
    if mode not in MANUAL_MODES:
        raise ValueError(f"mode must be one of {sorted(MANUAL_MODES)}, got {mode!r}")
    if not isinstance(count, int) or count < 0:
        raise ValueError(f"count must be a non-negative int, got {count!r}")

    if mode == MANUAL_MODE_M0:
        return {
            "mode": mode,
            "retest": True,
            "counted": False,
            "count": count,
            "recheck": False,
            "judgment_event": False,
            "downgrade": False,
            "reason_code": "m0_retest_only",
            "reason": "M0 (unconfirmed self-report): triggers one system-internal "
                      "retest (teaching action); zero judgment-side effect — no "
                      "judgment event, no counting, no downgrade, no archive write.",
        }

    next_count = count + 1
    if next_count >= MANUAL_RECHECK_LIMIT:
        return {
            "mode": mode,
            "retest": True,
            "counted": True,
            "count": 0,
            "recheck": True,
            "judgment_event": False,
            "downgrade": False,
            "reason_code": "m1_trigger_recheck",
            "reason": f"M1 #{next_count}: action-layer counter reached "
                      f"{MANUAL_RECHECK_LIMIT} -> recheck (回查) triggered and "
                      "counter reset; no downgrade, no judgment event (only "
                      "system-internal retest verdicts enter the unique counter).",
        }
    return {
        "mode": mode,
        "retest": True,
        "counted": True,
        "count": next_count,
        "recheck": False,
        "judgment_event": False,
        "downgrade": False,
        "reason_code": "m1_counted",
        "reason": f"M1 #{next_count} (below {MANUAL_RECHECK_LIMIT}): action-layer "
                  "count incremented; retest triggered; no downgrade.",
    }


# ---------------------------------------------------------------------------
# §4 over-diagnosis gates (M2.5 part 4)
# ---------------------------------------------------------------------------
#
# The three gates of design §2 (proposal §4) do not enter the judgment rules
# themselves; the judgment side provides the ruling signals the gates consume
# (状态降级仅由系统判定事件驱动, 会审修订):
#
#   Gate #1 diagnosis_budget: one diagnostic session on a node asks at most
#     DIAGNOSIS_QUESTION_LIMIT (=5) questions; beyond that the session
#     switches to the mainline (超限转主线). The judgment rules never perceive
#     the question count — decide_verdict consumes only the attempts within
#     the compliant window (the wiring layer passes the budgeted slice as
#     `window`). "已达标" (mastered) = the compliant window's latest verdict is
#     A (window-level AGG, §2.2): the session stops early, before the cap.
#
#   Gate #2 recheck_depth_limit: the judgment side never executes the recheck
#     (回查) — this pure rule tells the recheck driver at which chain depth to
#     narrow. Interpretation (proposal ambiguity, documented): within the
#     limit (depth <= RECHECK_DEPTH_LIMIT = 3) the prereq chain is walked in
#     full; beyond it only C/D (weak) nodes are examined ("默认 3 层，超过只查
#     C/D 节点" — a narrowing, not a hard stop), so critical weak nodes are
#     still found without unbounded chain walking. Unfiled nodes are never
#     rechecked beyond the limit (未建档不阻塞, design:197).
#
#   Gate #3 unique counter (M2.5-2) is the §4 alignment point: 连续 3 次 C/D
#     is the same number everywhere (CD_COUNTER_LIMIT == MANUAL_RECHECK_LIMIT
#     == 3, 同数同义); the counter reaching 3 fires downgrade + recheck +
#     reset, and manual M1 entries never enter it — M1 has its own action-layer
#     count (threshold 3, §3) that only triggers 回查, never the archive.

DIAGNOSIS_QUESTION_LIMIT = 5   # 闸门 #1: 单节点单次诊断题量上限 (default 5)
RECHECK_DEPTH_LIMIT = 3        # 闸门 #2: 回查深度上限 (default 3)


def diagnosis_budget(question_count, *, limit=DIAGNOSIS_QUESTION_LIMIT, mastered=False) -> dict:
    """Gate #1 ruling: how far may one diagnostic session on a node go (§4).

    Args:
        question_count: diagnostic questions already asked in this session
            (non-negative int).
        limit: per-session question cap (default DIAGNOSIS_QUESTION_LIMIT).
        mastered: True when the compliant window's latest verdict is A
            (已达标 — window-level AGG, §2.2). The judgment side only consumes
            the compliant window; this flag is that verdict's signal.

    Returns:
        {"decision", "within_budget", "question_count", "limit",
         "reason_code", "reason"}:
        - "continue": within budget, not yet mastered -> keep diagnosing;
        - "mastered": the node is confirmed mastered (window verdict A) ->
          stop early, before the cap;
        - "switch_mainline": budget exhausted without mastery -> stop
          diagnosing this node, return to the mainline (超限转主线).
    """
    if not isinstance(question_count, int) or question_count < 0:
        raise ValueError(
            f"question_count must be a non-negative int, got {question_count!r}"
        )
    if not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit must be a positive int, got {limit!r}")

    within_budget = question_count < limit

    if mastered:
        return {
            "decision": "mastered",
            "within_budget": within_budget,
            "question_count": question_count,
            "limit": limit,
            "reason_code": "mastered",
            "reason": f"Compliant-window verdict is A (已达标): node confirmed "
                      f"mastered after {question_count} question(s); diagnosis "
                      "stops early, before the cap.",
        }
    if question_count >= limit:
        return {
            "decision": "switch_mainline",
            "within_budget": within_budget,
            "question_count": question_count,
            "limit": limit,
            "reason_code": "exceeded_switch_mainline",
            "reason": f"Diagnosis reached the {limit}-question cap without "
                      "mastery (超限转主线): stop diagnosing this node and "
                      "return to the mainline.",
        }
    return {
        "decision": "continue",
        "within_budget": within_budget,
        "question_count": question_count,
        "limit": limit,
        "reason_code": "within_budget",
        "reason": f"{question_count} question(s) asked, "
                  f"{limit - question_count} remaining within budget: keep "
                  "diagnosing this node.",
    }


def recheck_depth_limit(depth, node_status=None, *, limit=RECHECK_DEPTH_LIMIT) -> dict:
    """Gate #2 rule: at which chain depth does the recheck narrow (§4).

    The judgment side never executes the recheck; this pure rule tells the
    recheck driver where to stop walking the prereq chain in full. See the
    section note for the documented interpretation (narrowing, not a hard
    stop: beyond the limit only C/D nodes are examined).

    Args:
        depth: 1-based depth in the prereq chain under recheck (chain root = 1).
        node_status: the chain node's stored status (A/B/C/D or None for
            unfiled). Only consulted beyond the limit — unfiled nodes are
            never rechecked there (未建档不阻塞, design:197).
        limit: recheck depth cap (default RECHECK_DEPTH_LIMIT).

    Returns:
        {"depth", "limit", "within_limit", "only_cd", "should_recheck",
         "reason_code", "reason"}:
        - within_limit: depth <= limit (full-chain recheck zone);
        - only_cd: True beyond the limit — only C/D nodes are rechecked;
        - should_recheck: within limit -> True; beyond -> node_status in (C, D).
    """
    if not isinstance(depth, int) or depth < 1:
        raise ValueError(
            f"depth must be a positive int (1-based chain depth), got {depth!r}"
        )
    if not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit must be a positive int, got {limit!r}")
    if node_status is not None and node_status not in STORAGE_STATES:
        raise ValueError(
            f"node_status must be None or one of {sorted(STORAGE_STATES)}, "
            f"got {node_status!r}"
        )

    within_limit = depth <= limit
    if within_limit:
        return {
            "depth": depth,
            "limit": limit,
            "within_limit": True,
            "only_cd": False,
            "should_recheck": True,
            "reason_code": "full_recheck",
            "reason": f"Depth {depth} within the {limit}-level limit: recheck "
                      "the prereq chain in full.",
        }
    should = node_status in (VERDICT_C, VERDICT_D)
    return {
        "depth": depth,
        "limit": limit,
        "within_limit": False,
        "only_cd": True,
        "should_recheck": should,
        "reason_code": "cd_only",
        "reason": f"Depth {depth} beyond the {limit}-level limit: only C/D "
                  f"(weak) nodes are rechecked; node_status={node_status!r} "
                  f"-> {'recheck' if should else 'no recheck'}.",
    }


# ---------------------------------------------------------------------------
# §5 LLM participation boundary (M2.5 part 4)
# ---------------------------------------------------------------------------
#
# The evaluation recommendation is规约进 design §3.2's ① 错因归类 (evidence
# interpretation / 证据归类), NOT a third LLM role (§5 point 1): the
# recommendation is a soft "evidence interpretation label" input to the
# judgment, never the status itself — the final verdict is always decided by
# the §2.2 deterministic rules.
#
#   LLM_RECOMMENDATION_CANDIDATE maps the v51 6-enum recommendation to the
#   verdict it *hints at* (§5 point 2): blocked -> D 候选, weak -> C,
#   emerging/likely_stable -> B (single-strong label), stable_for_now -> A
#   候选, no_update -> NO_CHANGE hint.
#
#   apply_llm_tightening(verdict, recommendation) enforces 只收紧不放宽 (hard
#   constraint, §5 point 3): the recommendation may only push the verdict
#   toward the conservative (weaker) end — weak/blocked demote (B->C, B->D,
#   even A->C), while stable_for_now/emerging/likely_stable can never promote
#   (T14/T15). Two documented edges:
#     - NO_CHANGE is never promoted by the LLM (eligibility is deterministic);
#     - no_update never suppresses an actual A/B/C/D verdict (the LLM cannot
#       erase evidence-based judgment; the §5 no_update -> NO_CHANGE hint only
#       aligns with a deterministic NO_CHANGE).
#
#   llm_recommendation_usable(confidence) is the contract confidence gate
#   (evaluation_decision.v2.json:8, minimum_confidence_to_apply = 0.8).
#
#   deterministic_fallback(evidence, window, ...) is the 降级路径 (确定性兜底,
#   §5 point 4): LLM unavailable / low-confidence / mock / replay -> the
#   8/10-score weak judgment (v51 _v51_deterministic_evaluation_output
#   semantics) produces the verdict, so judgment proceeds and state updates
#   are never interrupted — but never A ("确定性路径只产 weak/emerging", §1
#   fact 6). Interpretation (proposal ambiguity, documented): the default 8/10
#   score is derived from the attempt ratio (score = ratio * 10); the wiring
#   layer may pass the actual v51 rubric score via `score`. The result is the
#   weaker of the §2.2 verdict and the label verdict, which keeps the fallback
#   consistent with decide_verdict on the same evidence (e.g. a correct-but-
#   inexplicable attempt stays C) while suppressing A when the LLM is down.

LLM_RECOMMENDATION_BLOCKED = "blocked"
LLM_RECOMMENDATION_WEAK = "weak"
LLM_RECOMMENDATION_EMERGING = "emerging"
LLM_RECOMMENDATION_LIKELY_STABLE = "likely_stable"
LLM_RECOMMENDATION_STABLE_FOR_NOW = "stable_for_now"
LLM_RECOMMENDATION_NO_UPDATE = "no_update"

LLM_RECOMMENDATIONS = frozenset({
    LLM_RECOMMENDATION_BLOCKED,
    LLM_RECOMMENDATION_WEAK,
    LLM_RECOMMENDATION_EMERGING,
    LLM_RECOMMENDATION_LIKELY_STABLE,
    LLM_RECOMMENDATION_STABLE_FOR_NOW,
    LLM_RECOMMENDATION_NO_UPDATE,
})

# recommendation -> the verdict it hints at (§5 point 2: 提示 X 候选).
LLM_RECOMMENDATION_CANDIDATE = {
    LLM_RECOMMENDATION_BLOCKED: VERDICT_D,
    LLM_RECOMMENDATION_WEAK: VERDICT_C,
    LLM_RECOMMENDATION_EMERGING: VERDICT_B,
    LLM_RECOMMENDATION_LIKELY_STABLE: VERDICT_B,
    LLM_RECOMMENDATION_STABLE_FOR_NOW: VERDICT_A,
    LLM_RECOMMENDATION_NO_UPDATE: VERDICT_NO_CHANGE,
}

MINIMUM_LLM_CONFIDENCE = 0.8     # evaluation_decision.v2.json:8 契约置信门槛

DETERMINISTIC_SCORE_MAX = 10     # v51 8/10 分制
DETERMINISTIC_WEAK_SCORE = 8     # score < 8/10 or severe_gap -> weak
FALLBACK_REASONS = frozenset({"llm_unavailable", "low_confidence", "mock", "replay"})

# Weakness order for 只收紧不放宽: A strongest, D weakest ("更保守" = 更弱,
# higher rank). NO_CHANGE is not on the scale and never participates.
_WEAKNESS_RANK = {VERDICT_A: 0, VERDICT_B: 1, VERDICT_C: 2, VERDICT_D: 3}


def _annotated_verdict(verdict, attrs):
    """Return a copy of a verdict dict with replaced attrs (pure)."""
    result = dict(verdict)
    result["attrs"] = dict(attrs)
    return result


def apply_llm_tightening(verdict, llm_recommendation) -> dict:
    """Apply the §5 只收紧不放宽 rule to one deterministic verdict.

    Args:
        verdict: a verdict dict (output of decide_verdict / the deterministic
            fallback path).
        llm_recommendation: one of LLM_RECOMMENDATIONS (v51 6-enum evidence-
            interpretation label), or None when no recommendation exists (no
            tightening; the wiring layer should prefer the deterministic
            fallback in that case).

    Returns:
        A new verdict dict (the input is never mutated) with the
        recommendation recorded in attrs. The code may only move toward the
        conservative (weaker) end: weak/blocked demote (B->C, B->D, A->C);
        the other recommendations never promote (T14/T15) and never suppress
        an actual A/B/C/D verdict. NO_CHANGE is never promoted by the LLM.
    """
    if not isinstance(verdict, dict) or verdict.get("code") not in VERDICTS:
        raise ValueError(
            f"verdict must be a verdict dict with a five-value code, got {verdict!r}"
        )

    attrs = dict(verdict.get("attrs") or {})
    attrs["llm_recommendation"] = llm_recommendation

    if llm_recommendation is None:
        attrs["llm_applied"] = False
        attrs["tightened"] = False
        return _annotated_verdict(verdict, attrs)

    if llm_recommendation not in LLM_RECOMMENDATIONS:
        raise ValueError(
            f"llm_recommendation must be one of {sorted(LLM_RECOMMENDATIONS)} "
            f"or None, got {llm_recommendation!r}"
        )

    attrs["llm_applied"] = True
    code = verdict["code"]
    attrs["original_code"] = code
    candidate = LLM_RECOMMENDATION_CANDIDATE[llm_recommendation]

    if code == VERDICT_NO_CHANGE or candidate == VERDICT_NO_CHANGE:
        # NO_CHANGE is never promoted (eligibility is deterministic); no_update
        # never suppresses an actual verdict (documented edge, §5).
        attrs["tightened"] = False
        return _annotated_verdict(verdict, attrs)

    if _WEAKNESS_RANK[candidate] > _WEAKNESS_RANK[code]:
        attrs["tightened"] = True
        result = _annotated_verdict(verdict, attrs)
        result["code"] = candidate
        result["is_strong"] = False
        result["decision"] = f"{candidate}_tightened_by_llm"
        result["reason"] = (
            f"{verdict['reason']} | LLM '{llm_recommendation}' tightens "
            f"{code} -> {candidate} (只收紧不放宽)."
        )
        return result

    attrs["tightened"] = False
    return _annotated_verdict(verdict, attrs)


def llm_recommendation_usable(confidence, *, minimum_confidence=MINIMUM_LLM_CONFIDENCE) -> bool:
    """§5 confidence gate (contract minimum_confidence_to_apply = 0.8).

    A recommendation without a reported confidence (None) is treated as
    unusable — conservative: the deterministic fallback takes over.
    """
    if confidence is None:
        return False
    return confidence >= minimum_confidence


def _deterministic_label(evidence, *, score=None, severe_gap=False):
    """8/10-score weak judgment (v51 _v51_deterministic_evaluation_output).

    Returns (label_verdict_code, label_name): score < 8 or severe_gap ->
    (C, "weak"); otherwise -> (B, "emerging"). Default score = ratio * 10.
    """
    if score is None:
        score = _ratio(evidence) * DETERMINISTIC_SCORE_MAX
    if severe_gap or score < DETERMINISTIC_WEAK_SCORE:
        return VERDICT_C, "weak"
    return VERDICT_B, "emerging"


def deterministic_fallback(
    evidence, window=None, *, reason="llm_unavailable", score=None, severe_gap=False,
) -> dict:
    """§5 deterministic fallback (LLM unavailable / low-confidence / mock / replay).

    Judgment proceeds and state updates are never interrupted (§5 point 4),
    but the fallback is conservative: it never yields A ("确定性路径只产
    weak/emerging", §1 fact 6). The result is the weaker of (a) the §2.2
    deterministic verdict (decide_verdict over the window) and (b) the 8/10-
    score weak judgment (weak -> C candidate, emerging -> B candidate), which
    keeps the fallback consistent with decide_verdict on the same evidence
    while suppressing A when the LLM is down.

    Args:
        evidence: the attempt dict (same shape as decide_verdict).
        window: the rolling evidence window (default: single-attempt window).
        reason: why the LLM path was bypassed — one of FALLBACK_REASONS
            ("llm_unavailable" | "low_confidence" | "mock" | "replay"),
            recorded as provenance in attrs.
        score: optional override of the 8/10-scale score (default derived
            from score_points/max_points as ratio * 10). The wiring layer
            passes the actual v51 rubric score when available.
        severe_gap: True when the v51 severe-gap signal fires (weak
            regardless of score).
    """
    if reason not in FALLBACK_REASONS:
        raise ValueError(
            f"reason must be one of {sorted(FALLBACK_REASONS)}, got {reason!r}"
        )
    base = decide_verdict(evidence, window)
    attrs = dict(base.get("attrs") or {})
    attrs["llm_fallback"] = True
    attrs["fallback_reason"] = reason

    if base["code"] == VERDICT_NO_CHANGE:
        # Eligibility is deterministic: the fallback never fabricates a
        # judgment event for ineligible / no-valid-evidence attempts.
        attrs["label"] = "no_label"
        return _annotated_verdict(base, attrs)

    label_code, label = _deterministic_label(evidence, score=score, severe_gap=severe_gap)
    attrs["label"] = label
    if _WEAKNESS_RANK[label_code] > _WEAKNESS_RANK[base["code"]]:
        # The weak judgment is more conservative -> it wins (e.g. B -> C on a
        # sub-8/10 score; A suppressed to B when the LLM is down).
        result = _annotated_verdict(base, attrs)
        result["code"] = label_code
        result["is_strong"] = False
        result["decision"] = f"{label_code}_deterministic_fallback"
        result["reason"] = (
            f"{base['reason']} | LLM path unavailable ({reason}): 8/10-score "
            f"weak judgment ({label}) tightens {base['code']} -> {label_code}."
        )
        return result
    # base verdict is as conservative or more; keep it, annotated.
    return _annotated_verdict(base, attrs)
