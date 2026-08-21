"""v51 runtime wiring seam for the unified mastery rules (M2.5 part 5b).

Pure module: no I/O, no sqlite, no runtime calls — the testable seam between
the v51 daily_runtime judgment site (`_record_evaluation_update`,
daily_runtime.py:13468) and the unified mastery rules. It composes the M2.5-1..4
primitives (learning_system/mastery_rules.py) and the 5a data bridge
(learning_system/mastery_bridge.py) into one decision function:

    judge_v51_evaluation(current_row, history_rows, decision_history,
                         evaluation_output, current_status, deterministic)
        -> unified judgment result (verdict / new status / counter /
           downgrade or recheck signals)

Composition (task M2.5-5b step 2; proposal §2.2/§2.3/§5):

    normalize_evidence(current) -> build_window(history, current)
        -> decide_verdict(evidence, window)             # R1-R6 + AGG C1-C6
        -> apply_llm_tightening(verdict, recommendation)  # §5 只收紧不放宽
        -> transition_status(status, verdict, window, counter)  # §2.3 table

Inputs (all plain dicts; see mastery_bridge for the external row shape):

    current_row / history_rows: judgment-event rows for the node — the current
        attempt plus its 90-day eligible history as read by the wiring layer.
    decision_history: the node's mastery_decisions rows (append-only history)
        used to derive the §2.3 unique consecutive C/D counter. Legacy rows
        without a stored unified verdict are mapped from new_status_code
        (A/B/C/D are the unified verdict codes for stored outcomes).
    evaluation_output: the v51 evaluation output dict; its
        mastery_recommendation (6-enum) is the §5 evidence-interpretation
        label fed to apply_llm_tightening (只收紧不放宽). Empty/missing ->
        no tightening. Unknown enum values raise (fail loud, like the bridge).
    current_status: the node's stored status (A/B/C/D) or None (未建档).
    deterministic: True when this judgment runs on the deterministic path
        (LLM evaluation unavailable: deterministic_runtime / mock / replay /
        no recommendation). Enforces proposal §5.4 "确定性路径只产 weak/emerging
        -> 从不 A": a would-be A verdict is demoted to B (under-claiming over
        over-claiming, §2.3 升降级不对称).

The result is the *judgment only*: NO_CHANGE is never stored (applied=False,
status left untouched), `mastery_decisions`/`learner_node_status` persistence
belongs to the wiring layer (M2.5-5b wiring, unchanged write mechanism).

Run: python3 -m unittest tests.test_mastery_v51_adapter
"""

from __future__ import annotations

from learning_system import mastery_bridge as bridge
from learning_system import mastery_rules as rules

# ---------------------------------------------------------------------------
# v51-compatible decision labels (kept for report / consumer compatibility;
# the old vocabulary: prerequisite_blocked / stable_for_now / basic_understanding
# / current_node_weak / preserve_accumulated_status).
# ---------------------------------------------------------------------------

DECISION_BLOCKED = "prerequisite_blocked"
DECISION_A = "stable_for_now"
DECISION_B = "basic_understanding"
DECISION_C = "current_node_weak"
DECISION_PRESERVE = "preserve_accumulated_status"

# transition_status reason_code -> short Chinese annotation appended to the
# stored reason so the archived trace reflects the unified verdict (the base
# reason text is the evaluation_output.reason, as before).
_REASON_ANNOTATIONS = {
    "blocking_d": "阻断性证据：节点判定为 D（前置断点/无法启动）。",
    "promote_a": "窗口 AGG 全满足（≥2 条强证据、≥2 指纹、双角色、跨 2 天、无未修复薄弱、窗口比例≥0.85）：升 A。",
    "promote_b": "确定性证据支持：升/建档为 B。",
    "keep_a": "单条证据不足以覆盖已累积 A 档：保持 A（防单条覆盖累积档案）。",
    "keep_b": "判定证据支持保持 B。",
    "keep_c": "窗口强证据不足 2 条：防单条翻案，保持 C。",
    "keep_d": "节点处于回查/修复中：保持 D。",
    "cd_count": "连续 C/D 判定计数 +1。",
    "cd_trigger_downgrade": "连续 3 次 C/D 判定：A/B 直接降为 C（无逐级阶梯）并触发回查，计数清零。",
    "cd_trigger_recheck": "连续 3 次 C/D 判定：触发回查，计数清零（状态保持）。",
    "unfiled_c": "首次 C/D 判定：有据建档为 C（薄弱）。",
    "no_change": "无有效判定证据：NO_CHANGE 不落库（没测过 ≠ 薄弱）。",
}


def decision_history_events(rows) -> list[dict]:
    """Map the node's mastery_decisions rows to §2.3 counter events (legacy-aware).

    For each row the unified 5-value verdict is read from verdict_or_code (alias
    "verdict"); when absent, the legacy stored outcome new_status_code is used
    (A/B/C/D are the unified verdict codes for stored outcomes — NO_CHANGE is
    never stored). Rows without any usable verdict raise (fail loud, mirroring
    mastery_bridge._extract_verdict). The result is exactly the event shape
    bridge.to_counter_events / rules.cd_counter consume.
    """
    prepared = []
    for row in rows:
        verdict = row.get("verdict_or_code") or row.get("verdict")
        if verdict in (None, ""):
            verdict = row.get("new_status_code")
        if verdict not in rules.VERDICTS:
            raise ValueError(
                "mastery_decisions row carries no unified verdict: expected "
                "'verdict_or_code' (alias 'verdict') or the legacy stored "
                f"'new_status_code' in A/B/C/D, got row {row!r}"
            )
        prepared.append({
            "verdict_or_code": verdict,
            "created_at": row.get("created_at"),
            "is_manual": row.get("is_manual", False),
        })
    return bridge.to_counter_events(prepared)


def _decision_label(transition: dict, verdict_code: str) -> str:
    """Map a transition result to the v51-compatible decision label."""
    reason_code = transition["reason_code"]
    status = transition["status"]
    if reason_code == "blocking_d":
        return DECISION_BLOCKED
    if status == rules.VERDICT_A:
        return DECISION_A if verdict_code == rules.VERDICT_A else DECISION_PRESERVE
    if status == rules.VERDICT_B:
        return DECISION_B
    if status == rules.VERDICT_C:
        return DECISION_C
    if status == rules.VERDICT_D:
        return DECISION_BLOCKED
    return DECISION_C


def _compose_reason(evaluation_output: dict, transition: dict) -> str:
    """Human reason: the evaluation_output.reason (kept verbatim, as before)
    plus the unified-verdict annotation (short Chinese trace)."""
    base = str(evaluation_output.get("reason") or "").strip()
    annotation = _REASON_ANNOTATIONS.get(transition["reason_code"], "")
    composed = "｜".join(part for part in (base, annotation) if part)
    return composed or str(transition.get("reason") or "")


def judge_v51_evaluation(
    *,
    current_row: dict,
    history_rows=(),
    decision_history=(),
    evaluation_output: dict | None = None,
    current_status: str | None = None,
    deterministic: bool = False,
) -> dict:
    """Unified mastery judgment for one v51 evaluation event (§2.2/§2.3/§5).

    Returns:
        {
          "applied": bool,          # False only for NO_CHANGE (never stored)
          "verdict": str,           # D | C | B | A | NO_CHANGE
          "status": str | None,     # new stored status (None = 未建档)
          "counter": int,           # §2.3 counter AFTER this event (to persist)
          "previous_counter": int,  # counter derived from decision_history
          "recheck": bool,          # 回查 signal (count reached 3)
          "downgrade": bool,        # stored status fell A/B -> C/D
          "decision": str,          # v51-compatible decision label
          "reason": str,            # composed human reason
          "reason_code": str,       # transition_status reason_code (trace)
          "verdict_reason": str,    # decide_verdict/LLM reason (English trace)
          "attrs": dict,            # verdict attrs + §5/§5.4 provenance
          "old_status": str | None,
        }
    """
    evaluation_output = evaluation_output or {}

    recommendation = evaluation_output.get("mastery_recommendation")
    if recommendation is not None:
        recommendation = str(recommendation)
    if recommendation not in (None, "") and recommendation not in rules.LLM_RECOMMENDATIONS:
        raise ValueError(
            f"mastery_recommendation must be one of {sorted(rules.LLM_RECOMMENDATIONS)} "
            f"or empty, got {recommendation!r}"
        )

    evidence = bridge.normalize_evidence(current_row)
    window = bridge.build_window(list(history_rows), current_row)
    verdict = rules.decide_verdict(evidence, window)
    verdict = rules.apply_llm_tightening(verdict, recommendation or None)

    attrs = dict(verdict.get("attrs") or {})
    attrs["deterministic"] = bool(deterministic)
    if deterministic and verdict["code"] == rules.VERDICT_A:
        # §5.4: the deterministic path only yields weak/emerging labels and
        # never stores A (LLM evaluation unavailable -> under-claiming wins).
        verdict = dict(verdict)
        verdict["code"] = rules.VERDICT_B
        verdict["is_strong"] = False
        verdict["decision"] = "B_deterministic_a_suppressed"
        verdict["reason"] = (
            f"{verdict['reason']} | §5.4 deterministic path: A suppressed to B "
            "(LLM evaluation unavailable; deterministic labels never store A)."
        )
        attrs["deterministic_a_suppressed"] = True
        attrs["original_code"] = rules.VERDICT_A
        verdict["attrs"] = attrs

    previous_counter = rules.cd_counter(decision_history_events(list(decision_history)))
    transition = rules.transition_status(
        current_status, verdict["code"], window, previous_counter
    )

    status = transition["status"]
    verdict_code = verdict["code"]
    applied = verdict_code != rules.VERDICT_NO_CHANGE
    downgrade = bool(
        current_status in (rules.VERDICT_A, rules.VERDICT_B)
        and status in (rules.VERDICT_C, rules.VERDICT_D)
        and current_status != status
    )

    return {
        "applied": applied,
        "verdict": verdict_code,
        "status": status,
        "counter": transition["counter"],
        "previous_counter": previous_counter,
        "recheck": bool(transition["recheck"]),
        "downgrade": downgrade,
        "decision": _decision_label(transition, verdict_code) if applied else "no_change",
        "reason": _compose_reason(evaluation_output, transition),
        "reason_code": transition["reason_code"],
        "verdict_reason": verdict["reason"],
        "attrs": attrs,
        "old_status": current_status,
    }
