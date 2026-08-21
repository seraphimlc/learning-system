"""v2 runtime wiring seam for the unified mastery rules (M2.5 part 5c).

Pure module: no I/O, no sqlite, no runtime calls — the testable seam between
the flow_nodes v2 orchestrator judgment site (`_mastery_decision_from_status`
/ `_status_update_from_evaluation`, orchestrator.py) and the unified mastery
rules. It composes the M2.5-1..4 primitives (learning_system/mastery_rules.py)
and the 5a data bridge (learning_system/mastery_bridge.py) into one decision
function, following the validated 5b pattern:

    judge_v2_node(evidence_rows, decision_history, current_status)
        -> unified judgment result (verdict / new status / counter /
           downgrade or recheck signals)

Composition (task M2.5-5c step 2; proposal §2.2/§2.3):

    normalize_evidence(row) -> build_window(history, row)
        -> decide_verdict(row, window)     # R1-R6 + window AGG C1-C6
        -> transition_status(status, verdict, window, counter)  # §2.3 table

Judgment-event granularity (§2.2): one eligible attempt = one judgment
event; flow_nodes' session-level aggregate judgment is retired. The v2
orchestrator judges at session close, per node, aggregating the session's
attempts — this adapter folds those attempts chronologically as judgment
events (each event decides against its own decision-time 90-day window,
`mastery_bridge.build_window`), carrying the §2.3 counter and stored status
across the fold. The result is the node's state after the whole session; the
wiring persists exactly one mastery_decisions row + one learner_node_status
row per node per session (落库机制不动, per task M2.5-5c step 4).

Inputs (all plain dicts; see mastery_bridge for the external row shape):

    evidence_rows: the node's judgment-event rows in chronological order —
        this session's usable attempts plus the node's prior active attempts
        within the rolling 90-day window, as read by the wiring layer.
        Rows are normalized (bridge.normalize_evidence) and filtered by
        rules.is_eligible; ineligible rows are not judgment events (§2.2
        eligibility) and never enter the window.
    decision_history: the node's mastery_decisions rows (append-only
        history) used to derive the §2.3 unique consecutive C/D counter
        before this session. Each row's unified verdict is read from
        verdict_or_code (alias "verdict"), then the stored new_status_code
        (A/B/C/D are the unified verdict codes for stored outcomes), then the
        decision_payload_json.unified_verdict.verdict trace written by the
        5c wiring. Rows without a readable verdict raise (fail loud,
        mirroring mastery_v51_adapter.decision_history_events / the bridge's
        _extract_verdict). NO_CHANGE rows are dropped at mapping time
        (§2.3 "NO_CHANGE 事件跳过").
    current_status: the node's stored status (A/B/C/D) or None (未建档).

The result is the *judgment only*: NO_CHANGE is never stored (applied=False,
status left untouched), `mastery_decisions`/`learner_node_status` persistence
belongs to the wiring layer (unchanged write mechanism). The v2 path has no
LLM evaluation recommendation (build_mastery_evaluation_package is fully
deterministic), so no §5 tightening is applied here.

The decision/closure_result labels preserve the legacy v2 vocabulary
(_mastery_decision_from_status) so archival consumers (agent handoff,
reports, mastery_decisions.decision) keep their shape; only the derivation
changes: verdict=A -> stretch_ready/mastered, B -> basic_understanding/
repaired_not_mastered, C -> current_node_weak/repaired_not_mastered,
D -> prerequisite_blocked/prerequisite_blocked, NO_CHANGE ->
not_enough_evidence/pending_analysis (never stored).

Run: python3 -m unittest tests.test_mastery_v2_adapter
"""

from __future__ import annotations

import json as _json
from datetime import date, datetime

from learning_system import mastery_bridge as bridge
from learning_system import mastery_rules as rules

# ---------------------------------------------------------------------------
# v2-compatible decision labels (kept for report / consumer compatibility;
# the legacy vocabulary from orchestrator._mastery_decision_from_status:
# prerequisite_blocked / current_node_weak / basic_understanding /
# stable_understanding / stretch_ready / not_enough_evidence).
# ---------------------------------------------------------------------------

DECISION_BLOCKED = "prerequisite_blocked"
DECISION_A = "stretch_ready"
DECISION_B = "basic_understanding"
DECISION_C = "current_node_weak"
DECISION_NO_CHANGE = "not_enough_evidence"

CLOSURE_MASTERED = "mastered"
CLOSURE_REPAIRED_NOT_MASTERED = "repaired_not_mastered"
CLOSURE_BLOCKED = "prerequisite_blocked"
CLOSURE_PENDING_ANALYSIS = "pending_analysis"

# transition_status reason_code -> short Chinese annotation appended to the
# stored reason so the archived trace reflects the unified verdict.
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


def _payload_verdict(row: dict) -> str:
    """The unified verdict recorded in a v2 mastery_decisions payload trace."""
    payload = row.get("decision_payload_json")
    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except ValueError:
            payload = None
    if isinstance(payload, dict):
        trace = payload.get("unified_verdict")
        if isinstance(trace, dict):
            verdict = trace.get("verdict")
            if verdict in rules.VERDICTS:
                return verdict
    return ""


def _as_date(value):
    """Mirror of mastery_bridge._as_date (private there): normalize created_at.

    Kept as a local pure copy so the adapter does not reach into a private
    helper; semantics identical: date/datetime passthrough, "YYYY-MM-DD[ T...]"
    strings parsed, anything else raises ValueError.
    """
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


def decision_history_events(rows) -> list[dict]:
    """Map the node's mastery_decisions rows to §2.3 counter events (legacy-aware).

    For each row the unified 5-value verdict is read from verdict_or_code
    (alias "verdict"), then the legacy stored outcome new_status_code, then
    the decision_payload_json.unified_verdict.verdict trace written by the
    M2.5-5c wiring (the v2 insert keeps the payload; new_status_code is set
    by the wiring's post-update for consistency). Rows without any usable
    verdict raise (fail loud, mirroring mastery_v51_adapter). The result is
    exactly the event shape bridge.to_counter_events / rules.cd_counter
    consume.
    """
    prepared = []
    for row in rows:
        verdict = row.get("verdict_or_code") or row.get("verdict")
        if verdict in (None, ""):
            verdict = row.get("new_status_code")
        if verdict in (None, ""):
            verdict = _payload_verdict(row)
        if verdict not in rules.VERDICTS:
            raise ValueError(
                "mastery_decisions row carries no unified verdict: expected "
                "'verdict_or_code' (alias 'verdict'), the legacy stored "
                "'new_status_code' in A/B/C/D, or the "
                "'decision_payload_json.unified_verdict.verdict' trace, "
                f"got row {row!r}"
            )
        prepared.append({
            "verdict_or_code": verdict,
            "created_at": row.get("created_at"),
            "is_manual": row.get("is_manual", False),
        })
    return bridge.to_counter_events(prepared)


def _decision_label(verdict_code: str) -> str:
    """Map a verdict to the v2-compatible decision label.

    Verdict-based (not status-based) so the archived label matches the legacy
    _mastery_decision_from_status vocabulary for the same evidence: a narrow
    strong on an accumulated A node was labeled "basic_understanding", not
    "stretch_ready" — the label describes this judgment event, the stored
    status may be preserved by the §2.3 table.
    """
    if verdict_code == rules.VERDICT_D:
        return DECISION_BLOCKED
    if verdict_code == rules.VERDICT_A:
        return DECISION_A
    if verdict_code == rules.VERDICT_B:
        return DECISION_B
    if verdict_code == rules.VERDICT_C:
        return DECISION_C
    return DECISION_NO_CHANGE


def _closure_result(verdict_code: str) -> str:
    """The v2-compatible closure_result for a verdict (legacy vocabulary)."""
    if verdict_code == rules.VERDICT_D:
        return CLOSURE_BLOCKED
    if verdict_code == rules.VERDICT_A:
        return CLOSURE_MASTERED
    if verdict_code in (rules.VERDICT_B, rules.VERDICT_C):
        return CLOSURE_REPAIRED_NOT_MASTERED
    return CLOSURE_PENDING_ANALYSIS


def _compose_reason(reason_base: str, transition: dict) -> str:
    """Human reason: the wiring-provided base text plus the unified annotation."""
    base = str(reason_base or "").strip()
    annotation = _REASON_ANNOTATIONS.get(transition["reason_code"], "")
    composed = "｜".join(part for part in (base, annotation) if part)
    return composed or str(transition.get("reason") or "")


def _no_change_result(current_status, *, previous_counter, reason_code,
                      reason, event_count=0) -> dict:
    """The canonical NO_CHANGE result (never stored)."""
    return {
        "applied": False,
        "verdict": rules.VERDICT_NO_CHANGE,
        "status": current_status,
        "counter": previous_counter,
        "previous_counter": previous_counter,
        "recheck": False,
        "downgrade": False,
        "decision": DECISION_NO_CHANGE,
        "closure_result": CLOSURE_PENDING_ANALYSIS,
        "reason": reason,
        "reason_code": reason_code,
        "verdict_reason": reason,
        "attrs": {
            "reason_code": reason_code,
            "event_count": event_count,
            "eligible_count": event_count,
        },
        "old_status": current_status,
        "events": [],
    }


def judge_v2_node(
    *,
    evidence_rows=(),
    decision_history=(),
    current_status=None,
    reason_base="",
) -> dict:
    """Unified mastery judgment for one v2 node evaluation (§2.2/§2.3).

    Folds the node's eligible judgment-event rows chronologically: each event
    decides its verdict against its own decision-time 90-day window, and the
    §2.3 transition table (plus the consecutive C/D counter) carries state
    across the fold. The returned result reflects the node's state after the
    whole session.

    Args:
        evidence_rows: the node's judgment-event rows (external shape), this
            session's usable attempts plus prior 90-day history, in any
            order (sorted internally by created_at).
        decision_history: the node's mastery_decisions rows before this
            session (counter derivation).
        current_status: the stored status (A/B/C/D) or None (未建档).
        reason_base: human base text for the stored reason (the wiring passes
            the evaluation's why/why_not_advance text); the adapter appends
            the unified-verdict annotation.

    Returns:
        {
          "applied": bool,          # False only for NO_CHANGE (never stored)
          "verdict": str,           # D | C | B | A | NO_CHANGE (last event)
          "status": str | None,     # new stored status (None = 未建档)
          "counter": int,           # §2.3 counter AFTER the session's events
          "previous_counter": int,  # counter derived from decision_history
          "recheck": bool,          # 回查 signal (count reached 3)
          "downgrade": bool,        # stored status fell A/B -> C/D
          "decision": str,          # v2-compatible decision label
          "closure_result": str,    # v2-compatible closure result
          "reason": str,            # composed human reason
          "reason_code": str,       # transition_status reason_code (trace)
          "verdict_reason": str,    # decide_verdict reason (English trace)
          "attrs": dict,            # verdict attrs + fold trace
          "old_status": str | None,
          "events": list,           # per-event {attempt_id, verdict,
                                    #   reason_code, counter} trace
        }
    """
    previous_counter = rules.cd_counter(decision_history_events(list(decision_history)))

    normalized = []
    for row in evidence_rows:
        normalized.append(bridge.normalize_evidence(row))
    ordered = sorted(
        normalized,
        key=lambda e: (
            _as_date(e["created_at"]),
            str(e.get("attempt_id") or ""),
        ),
    )
    events = [e for e in ordered if rules.is_eligible(e)]

    if not events:
        return _no_change_result(
            current_status,
            previous_counter=previous_counter,
            reason_code="no_change",
            reason="无有效判定证据：NO_CHANGE 不落库（没测过 ≠ 薄弱）。",
        )

    counter = previous_counter
    status = current_status
    last_applied = None  # (row, verdict, transition) of the last real event
    trace: list[dict] = []
    for index, row in enumerate(events):
        window = bridge.build_window(events[:index], row)
        verdict = rules.decide_verdict(row, window)
        transition = rules.transition_status(status, verdict["code"], window, counter)
        counter = transition["counter"]
        status = transition["status"]
        trace.append({
            "attempt_id": row.get("attempt_id"),
            "verdict": verdict["code"],
            "reason_code": transition["reason_code"],
            "counter": counter,
        })
        if verdict["code"] != rules.VERDICT_NO_CHANGE:
            last_applied = (row, verdict, transition)

    if last_applied is None:
        return _no_change_result(
            current_status,
            previous_counter=previous_counter,
            reason_code="no_change",
            reason="无有效判定证据：NO_CHANGE 不落库（没测过 ≠ 薄弱）。",
            event_count=len(events),
        )

    row, verdict, transition = last_applied
    verdict_code = verdict["code"]
    downgrade = bool(
        current_status in (rules.VERDICT_A, rules.VERDICT_B)
        and transition["status"] in (rules.VERDICT_C, rules.VERDICT_D)
        and current_status != transition["status"]
    )
    attrs = dict(verdict.get("attrs") or {})
    attrs["event_count"] = len(events)
    attrs["eligible_count"] = len(events)
    attrs["fold_attempt_ids"] = [e.get("attempt_id") for e in events]

    return {
        "applied": True,
        "verdict": verdict_code,
        "status": transition["status"],
        "counter": counter,
        "previous_counter": previous_counter,
        "recheck": bool(transition["recheck"]),
        "downgrade": downgrade,
        "decision": _decision_label(verdict_code),
        "closure_result": _closure_result(verdict_code),
        "reason": _compose_reason(reason_base, transition),
        "reason_code": transition["reason_code"],
        "verdict_reason": verdict["reason"],
        "attrs": attrs,
        "old_status": current_status,
        "events": trace,
    }
