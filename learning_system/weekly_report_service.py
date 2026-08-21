"""Weekly summary (周信) generation service — M4-3.

Contract: docs/design/specs/2026-08-20-child-learning-companion-design.md
§6.1 (一页纸周信) / §6.2 (学期报告 = 周信聚合模板) +
docs/design/specs/2026-08-20-mastery-criteria-proposal.md §4 (A1 硬要求).

Role
----
Product-layer, read-mostly reporting service. This module aggregates the
week's data into one `weekly_summary` row and is the *only* writer of that
table (M4-1 schema). It never touches `mastery_decisions` /
`learner_node_status` / `error_cause_log` / `manual_error_entries` —
it only reads them (查询纪律: 周信/简报素材可聚合现有表，语义只能读三张新表;
mastery 判定不得读取 daily_all_correct_confirmations — 本服务也只做证据范围标注).

The one write = the `weekly_summary` row, via single-statement UPSERT
(`INSERT ... ON CONFLICT ... DO UPDATE SET ...`), which keeps the
M4-1 append-only scan (tests/test_db_schema_m4.py AppendOnlyContractTestCase)
green: no UPDATE/DELETE statements reference the four M4 tables in the
service layer; the acknowledge status flip is the documented column-scoped
exception (status/acknowledged_at), payload columns stay insert-only, rows are
never deleted.

Weekly-letter content (§6.1)
---------------------------
- 本周覆盖节点 (coverage_json): union of daily_summaries.touched_node_ids_json
  and attempts.node_id for rows created inside the ISO week.
- 当周 A/B/C/D 快照 (node_status_snapshot_json): all learner_node_status rows
  (the archive state; per-node updated_at recorded). taken_at = the week-close
  boundary (Monday 00:00 UTC of the next week) — the letter covers the state
  as of week close.
- 状态变化 (weekly_snapshot_diff): compare the previous week's archived
  snapshot with the current state ("哪些绿了" material). 若无上周存档 →
  全部记为 new.
- 错因分布 (error_distribution_json): error_cause_log rows created inside the
  week with trust_status IN ('counted','rule_hit') aggregated by error_tag
  (分布查询纪律 — pending_parent 一律不计入).
- 证据范围三分类 (evidence_scope): system_only / with_manual / with_all_correct.
  - with_manual: ≥1 manual_error_entries row created inside the week whose
    trust_status is counted/rule_hit (即"计入"分布的手动补录);
  - with_all_correct: ≥1 daily_all_correct_confirmations row whose
    confirm_date falls inside the week's calendar dates;
  - priority choice (documented): with_manual > with_all_correct > system_only
    — manual errors are the stronger qualification of the error-pattern
    statement; both booleans are surfaced in the result for transparency.
- A1 硬要求 (异常提示): the §2.3 unique consecutive C/D counter (derived from
  mastery_decisions via rules.cd_counter over judgment events with
  created_at < week close; verdict read as new_status_code → the
  decision_payload_json.unified_verdict.verdict trace; rows without any usable
  verdict are skipped conservatively — under-claiming, counted and surfaced)
  ≥ 2 → the node MUST enter narrative as "已连续 N 次 C/D，注意" (计数≥2 提示先行,
  第 3 次才改档). The service injects this itself — it never trusts the LLM
  callback for the mandatory warning, and force-appends the warning text when
  the narrative text lacks it.

Failure paths / degradation (§6.1)
----------------------------------
- narrative_fn 失败/异常或返回非预期 → 降级为模板填充 (覆盖列表 + 状态变化表 +
  错因一句话 + 下周重点 + 预警), 不阻塞, narrative_json.degraded=True;
- narrative_fn=None → 直接用模板;
- 未确认 → status='unacknowledged' 存档不丢, 可补看 (list_weekly_summaries);
- 缺勤 → 调用侧跳过 (本服务不生成该周).

Idempotency choice (iso_week unique)
------------------------------------
Regenerating an existing iso_week UPSERTs: the payload columns +
generated_at are refreshed and status resets to 'unacknowledged'
(acknowledged_at cleared) — a regenerate is a *new letter version* and dad
should re-confirm it; the row id is preserved. Chosen over "return existing"
because late-arriving data (e.g. 补录) must be reflected in the letter.

acknowledge_weekly_summary additionally triggers the 周信批量确认通道
(design §3.1 / proposal §3 会审修订): manual_entry_service.confirm_week_manual_errors
batch-upgrades that week's unconfirmed M0 entries to M1 (idempotent).
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import date, datetime, timezone, timedelta

from learning_system import db
from learning_system import mastery_rules as rules
from learning_system import manual_entry_service as mes

_STATUS_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}

_SCOPE_LABELS = {
    "system_only": "仅系统内",
    "with_manual": "含手动补录",
    "with_all_correct": "含全对确认",
}

_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")

# 分布查询纪律: 只统计这些 trust_status (对齐 manual_entry_service).
_TRUST_PLACEHOLDERS = ",".join("?" for _ in mes.DISTRIBUTION_TRUST_STATUSES)

WEEKLY_SUMMARY_UPSERT_SQL = """
    insert into weekly_summary(
      id, iso_week, status, node_status_snapshot_json, coverage_json,
      error_distribution_json, evidence_scope, narrative_json,
      generated_at, acknowledged_at
    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    on conflict(iso_week) do update set
      status = excluded.status,
      node_status_snapshot_json = excluded.node_status_snapshot_json,
      coverage_json = excluded.coverage_json,
      error_distribution_json = excluded.error_distribution_json,
      evidence_scope = excluded.evidence_scope,
      narrative_json = excluded.narrative_json,
      generated_at = excluded.generated_at,
      acknowledged_at = excluded.acknowledged_at
"""

ACKNOWLEDGE_UPSERT_SQL = """
    insert into weekly_summary(
      id, iso_week, status, node_status_snapshot_json, coverage_json,
      error_distribution_json, evidence_scope, narrative_json,
      generated_at, acknowledged_at
    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    on conflict(id) do update set
      status = excluded.status,
      acknowledged_at = excluded.acknowledged_at
"""


def generate_weekly_summary(
    conn: sqlite3.Connection,
    *,
    iso_week: str,
    narrative_fn=None,
    commit: bool = True,
) -> dict:
    """Generate and persist one weekly_summary row for the given ISO week.

    Args:
        conn: sqlite3 connection (row_factory=Row) with the M4 schema.
        iso_week: ISO week key like ``2026-W34`` (Monday 00:00 UTC boundary).
        narrative_fn: optional injected narrative callback
            ``fn(payload: dict) -> dict``; must return a dict with a non-empty
            ``"text"`` string, else the letter degrades to the deterministic
            template. ``None`` uses the template directly. Never trusted for
            the mandatory A1 warnings.
        commit: commit the write (default True, M4-2 style).

    Returns the full letter dict: id/iso_week/status + parsed payload columns +
    a1_warnings/status_changes (letter material) + upserted flag.
    """
    year, week = _parse_iso_week(iso_week)
    start_iso, end_iso = _iso_week_bounds(year, week)
    prev_year, prev_week = _prev_iso_week(year, week)
    prev_iso_week = f"{prev_year:04d}-W{prev_week:02d}"
    now = db.now_iso()

    snapshot = _snapshot(conn, end_iso)
    coverage = _week_coverage(conn, start_iso, end_iso)
    distribution = _week_error_distribution(conn, start_iso, end_iso)
    scope, scope_flags = _evidence_scope(conn, start_iso, end_iso, year, week)
    warnings, unclassifiable = _a1_warnings(conn, end_iso)
    changes = weekly_snapshot_diff(conn, prev_iso_week, iso_week)

    payload = {
        "iso_week": iso_week,
        "previous_iso_week": prev_iso_week,
        "node_status_snapshot_json": snapshot,
        "coverage_json": coverage,
        "error_distribution_json": distribution,
        "evidence_scope": scope,
        "a1_warnings": warnings,
        "status_changes": changes,
    }
    narrative = _assemble_narrative(payload, narrative_fn)

    was_existing = _week_exists(conn, iso_week)
    row_id = _upsert_week(
        conn, iso_week, snapshot, coverage, distribution, scope, narrative, now,
    )
    if commit:
        conn.commit()

    return {
        "id": row_id,
        "iso_week": iso_week,
        "status": "unacknowledged",
        "node_status_snapshot_json": snapshot,
        "coverage_json": coverage,
        "error_distribution_json": distribution,
        "evidence_scope": scope,
        "narrative_json": narrative,
        "generated_at": now,
        "acknowledged_at": None,
        "a1_warnings": warnings,
        "status_changes": changes,
        "evidence_scope_flags": scope_flags,
        "a1_unclassifiable_rows": unclassifiable,
        "upserted": was_existing,
    }


def list_weekly_summaries(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict]:
    """周信历史存档列表 (爸爸可补看), newest iso_week first, payloads parsed."""
    rows = conn.execute(
        "select * from weekly_summary order by iso_week desc limit ?", (limit,)
    ).fetchall()
    return [_row_result(row) for row in rows]


def acknowledge_weekly_summary(
    conn: sqlite3.Connection,
    summary_id: str,
    *,
    acknowledged_by: str = "parent",
    commit: bool = True,
) -> dict:
    """Mark a weekly letter acknowledged and fire the 周信批量确认通道.

    status → 'acknowledged' + acknowledged_at (first time; re-acknowledge is
    idempotent and keeps the original timestamp). Then runs
    ``manual_entry_service.confirm_week_manual_errors`` for the letter's week —
    that week's unconfirmed M0 manual entries are batch-upgraded to M1
    (等效逐题确认, proposal §3 会审修订). Raises ValueError for an unknown
    summary_id.
    """
    row = conn.execute(
        "select * from weekly_summary where id = ?", (summary_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown weekly_summary id: {summary_id!r}")

    now = db.now_iso()
    acknowledged_at = row["acknowledged_at"] or now
    conn.execute(
        ACKNOWLEDGE_UPSERT_SQL,
        (
            row["id"], row["iso_week"], "acknowledged",
            row["node_status_snapshot_json"], row["coverage_json"],
            row["error_distribution_json"], row["evidence_scope"],
            row["narrative_json"], row["generated_at"], acknowledged_at,
        ),
    )
    batch = mes.confirm_week_manual_errors(
        conn, iso_week=row["iso_week"], confirmed_by=acknowledged_by,
    )
    if commit:
        conn.commit()

    return {
        "summary_id": row["id"],
        "iso_week": row["iso_week"],
        "status": "acknowledged",
        "acknowledged_at": acknowledged_at,
        "acknowledged_by": acknowledged_by,
        "batch_confirmed": batch,
    }


def weekly_snapshot_diff(
    conn: sqlite3.Connection, iso_week_prev: str, iso_week_curr: str
) -> dict:
    """Read-only status-change diff between two ISO weeks (周信"哪些绿了"素材).

    Reads the archived node_status_snapshot_json of both weeks from
    weekly_summary; when the curr week has no archive row yet, the live
    learner_node_status state is used instead. Missing prev → all curr nodes
    are "new". Returns changes (only actual changes), improved/worsened/new/
    removed/turned_a lists and unchanged_count.
    """
    prev = _load_snapshot(conn, iso_week_prev)
    curr = _load_snapshot(conn, iso_week_curr)
    if curr is None:
        curr = _live_snapshot(conn)
    prev_nodes = prev["nodes"] if prev else {}
    curr_nodes = curr["nodes"] if curr else {}

    changes: list[dict] = []
    improved: list[str] = []
    worsened: list[str] = []
    new: list[str] = []
    removed: list[str] = []
    turned_a: list[str] = []
    unchanged = 0

    for node_id in sorted(set(prev_nodes) | set(curr_nodes)):
        prev_entry = prev_nodes.get(node_id)
        curr_entry = curr_nodes.get(node_id)
        prev_status = prev_entry["status_code"] if prev_entry else None
        curr_status = curr_entry["status_code"] if curr_entry else None
        if prev_status is None and curr_status is None:
            continue
        if prev_status is None:
            direction = "new"
            new.append(node_id)
        elif curr_status is None:
            direction = "removed"
            removed.append(node_id)
        elif prev_status == curr_status:
            direction = "unchanged"
            unchanged += 1
        elif _status_rank(curr_status) > _status_rank(prev_status):
            direction = "improved"
            improved.append(node_id)
            if curr_status == "A":
                turned_a.append(node_id)
        else:
            direction = "worsened"
            worsened.append(node_id)

        if direction != "unchanged":
            changes.append({
                "node_id": node_id,
                "prev": prev_status,
                "curr": curr_status,
                "direction": direction,
            })

    return {
        "iso_week_prev": iso_week_prev,
        "iso_week_curr": iso_week_curr,
        "changes": changes,
        "improved": improved,
        "worsened": worsened,
        "new": new,
        "removed": removed,
        "turned_a": turned_a,
        "unchanged_count": unchanged,
    }


# ---------------------------------------------------------------------------
# aggregation helpers
# ---------------------------------------------------------------------------


def _snapshot(conn: sqlite3.Connection, taken_at: str) -> dict:
    """All learner_node_status rows as the week's A/B/C/D time snapshot."""
    rows = conn.execute(
        "select node_id, status_code, updated_at from learner_node_status"
    ).fetchall()
    return {
        "taken_at": taken_at,
        "nodes": {
            row["node_id"]: {
                "status_code": row["status_code"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        },
    }


def _live_snapshot(conn: sqlite3.Connection) -> dict:
    return _snapshot(conn, db.now_iso())


def _load_snapshot(conn: sqlite3.Connection, iso_week: str) -> dict | None:
    row = conn.execute(
        "select node_status_snapshot_json from weekly_summary where iso_week = ?",
        (iso_week,),
    ).fetchone()
    if row is None:
        return None
    return db.json_load(row["node_status_snapshot_json"], fallback={})


def _week_coverage(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> dict:
    """Union of daily_summaries touched nodes and attempts nodes in the week."""
    nodes: set[str] = set()
    ds_ids: list[str] = []
    for row in conn.execute(
        "select id, touched_node_ids_json from daily_summaries"
        " where created_at >= ? and created_at < ?",
        (start_iso, end_iso),
    ):
        ds_ids.append(row["id"])
        for node_id in db.json_load(row["touched_node_ids_json"], fallback=[]):
            if isinstance(node_id, str) and node_id:
                nodes.add(node_id)
    attempt_ids: list[str] = []
    for row in conn.execute(
        "select id, node_id from attempts"
        " where created_at >= ? and created_at < ?",
        (start_iso, end_iso),
    ):
        attempt_ids.append(row["id"])
        nodes.add(row["node_id"])
    return {
        "nodes": sorted(nodes),
        "daily_summary_ids": sorted(ds_ids),
        "attempt_ids": sorted(attempt_ids),
    }


def _week_error_distribution(
    conn: sqlite3.Connection, start_iso: str, end_iso: str
) -> dict[str, int]:
    """error_tag → count for the week; only counted/rule_hit (分布查询纪律)."""
    rows = conn.execute(
        f"select error_tag, count(*) as n from error_cause_log"
        f" where created_at >= ? and created_at < ?"
        f" and trust_status in ({_TRUST_PLACEHOLDERS})"
        f" group by error_tag order by error_tag",
        (start_iso, end_iso, *mes.DISTRIBUTION_TRUST_STATUSES),
    ).fetchall()
    return {row["error_tag"]: row["n"] for row in rows}


def _evidence_scope(
    conn: sqlite3.Connection, start_iso: str, end_iso: str, year: int, week: int
) -> tuple[str, dict]:
    """Infer the §6.1 evidence-scope classification for the week.

    Priority (documented choice): with_manual > with_all_correct > system_only.
    """
    monday, next_monday = _week_dates(year, week)
    manual = conn.execute(
        f"select 1 from manual_error_entries"
        f" where created_at >= ? and created_at < ?"
        f" and trust_status in ({_TRUST_PLACEHOLDERS}) limit 1",
        (start_iso, end_iso, *mes.DISTRIBUTION_TRUST_STATUSES),
    ).fetchone()
    all_correct = conn.execute(
        "select 1 from daily_all_correct_confirmations"
        " where confirm_date >= ? and confirm_date < ? limit 1",
        (monday.isoformat(), next_monday.isoformat()),
    ).fetchone()
    has_manual = manual is not None
    has_all_correct = all_correct is not None
    if has_manual:
        scope = "with_manual"
    elif has_all_correct:
        scope = "with_all_correct"
    else:
        scope = "system_only"
    return scope, {"has_manual": has_manual, "has_all_correct": has_all_correct}


def _a1_warnings(conn: sqlite3.Connection, end_iso: str) -> tuple[list[dict], int]:
    """§4 A1 hard requirement: nodes whose consecutive C/D counter ≥ 2.

    The counter is derived from mastery_decisions judgment events with
    created_at < the week-close boundary, using the authoritative
    rules.cd_counter (trigger at 3 resets — a node that already downgraded
    this week shows 0 and surfaces via the status-change table instead).
    Rows without any usable verdict (legacy, no unified trace) are skipped —
    the conservative under-claiming direction — and counted so the caller can
    see the scan's coverage.
    """
    rows = conn.execute(
        "select node_id, created_at, new_status_code, decision_payload_json"
        " from mastery_decisions where created_at < ? order by node_id, created_at",
        (end_iso,),
    ).fetchall()
    events_by_node: dict[str, list[dict]] = {}
    unclassifiable = 0
    for row in rows:
        verdict = _verdict_from_decision_row(row)
        if verdict == "":
            unclassifiable += 1
            continue
        events_by_node.setdefault(row["node_id"], []).append({
            "verdict": verdict,
            "is_manual": False,
        })
    warnings = []
    for node_id in sorted(events_by_node):
        count = rules.cd_counter(events_by_node[node_id])
        if count >= 2:
            warnings.append({
                "node_id": node_id,
                "cd_count": count,
                "message": f"已连续 {count} 次 C/D，注意",
            })
    return warnings, unclassifiable


def _verdict_from_decision_row(row: sqlite3.Row) -> str:
    """Unified verdict of one mastery_decisions row; '' when unusable.

    Fallback chain mirrors mastery_v2_adapter.decision_history_events:
    the stored new_status_code (A/B/C/D are unified verdict codes for stored
    outcomes) → the decision_payload_json.unified_verdict.verdict trace.
    Lenient: rows with neither are skipped (under-claiming), not raised.
    """
    verdict = row["new_status_code"]
    if verdict in rules.VERDICTS:
        return verdict
    payload = db.json_load(row["decision_payload_json"], fallback={})
    if isinstance(payload, dict):
        trace = payload.get("unified_verdict")
        if isinstance(trace, dict):
            trace_verdict = trace.get("verdict")
            if trace_verdict in rules.VERDICTS:
                return trace_verdict
    return ""


# ---------------------------------------------------------------------------
# narrative assembly (LLM callback + template degradation)
# ---------------------------------------------------------------------------


def _assemble_narrative(payload: dict, narrative_fn) -> dict:
    """Build narrative_json; A1 warnings are always injected by the service."""
    a1_warnings = payload["a1_warnings"]
    template_parts = _template_parts(payload)
    source = "template"
    text = _render_template(template_parts, payload)

    if narrative_fn is not None:
        try:
            narr = narrative_fn(payload)
            if (
                isinstance(narr, dict)
                and isinstance(narr.get("text"), str)
                and narr["text"].strip()
            ):
                source = "llm"
                text = narr["text"].strip()
        except Exception:
            pass  # degrade to the template below

    if source != "llm":
        source = "template"
        text = _render_template(template_parts, payload)

    # A1 硬要求: 预警必须进 narrative. 结构化字段由服务自身注入 (不信任 LLM),
    # 且文本缺失时强制追加, 保证下游只读 text 也看得到.
    injected = False
    if a1_warnings and "已连续" not in text:
        suffix = "；".join(f"{w['node_id']} {w['message']}" for w in a1_warnings)
        text = f"{text}\n异常提示：{suffix}"
        injected = True

    return {
        "source": source,
        "text": text,
        "template": template_parts,
        "a1_warnings": a1_warnings,
        "degraded": source == "template",
        "warning_injected_into_text": injected,
    }


def _template_parts(payload: dict) -> dict:
    coverage = payload["coverage_json"]
    if coverage["nodes"]:
        coverage_line = "本周覆盖节点：" + "、".join(coverage["nodes"])
    else:
        coverage_line = "本周覆盖节点：无"

    changes = payload["status_changes"]
    if changes["improved"]:
        status_line = "状态变化：" + "、".join(f"{n} 绿了" for n in changes["improved"])
    elif changes["changes"]:
        status_line = "状态变化：" + "；".join(
            f"{c['node_id']} {c['prev'] or '—'}→{c['curr'] or '—'}"
            for c in changes["changes"]
        )
    else:
        status_line = "状态变化：无"

    distribution = payload["error_distribution_json"]
    scope_label = _SCOPE_LABELS[payload["evidence_scope"]]
    if distribution:
        top_tag, top_count = _top_tag(distribution)
        error_line = (
            f"错因模式：本周主要错因「{top_tag}」共 {top_count} 次"
            f"（证据范围：{scope_label}）"
        )
    else:
        error_line = f"错因模式：本周无明显错因（证据范围：{scope_label}）"

    return {
        "coverage_line": coverage_line,
        "status_change_line": status_line,
        "error_pattern_line": error_line,
        "next_week_focus": _next_week_focus(payload),
        "anomaly_lines": [
            f"{w['node_id']} {w['message']}" for w in payload["a1_warnings"]
        ],
    }


def _render_template(parts: dict, payload: dict) -> str:
    lines = [
        parts["coverage_line"],
        parts["status_change_line"],
        parts["error_pattern_line"],
        "下周重点：" + parts["next_week_focus"],
    ]
    lines.extend(f"异常提示：{line}" for line in parts["anomaly_lines"])
    return "\n".join(lines)


def _next_week_focus(payload: dict) -> str:
    if payload["a1_warnings"]:
        names = "、".join(w["node_id"] for w in payload["a1_warnings"])
        return f"优先处理连续 C/D 预警节点 {names}"
    distribution = payload["error_distribution_json"]
    if distribution:
        top_tag, top_count = _top_tag(distribution)
        return f"继续巩固「{top_tag}」类错因（本周 {top_count} 次）"
    return "按学习计划继续推进"


def _top_tag(distribution: dict[str, int]) -> tuple[str, int]:
    """Deterministic top tag: highest count, ties broken by tag order."""
    return sorted(distribution.items(), key=lambda kv: (-kv[1], kv[0]))[0]


# ---------------------------------------------------------------------------
# persistence helpers
# ---------------------------------------------------------------------------


def _week_exists(conn: sqlite3.Connection, iso_week: str) -> bool:
    return (
        conn.execute(
            "select 1 from weekly_summary where iso_week = ?", (iso_week,)
        ).fetchone()
        is not None
    )


def _upsert_week(
    conn: sqlite3.Connection,
    iso_week: str,
    snapshot: dict,
    coverage: dict,
    distribution: dict,
    scope: str,
    narrative: dict,
    generated_at: str,
) -> str:
    """Write/refresh the weekly_summary row; returns the effective row id."""
    existing = conn.execute(
        "select id from weekly_summary where iso_week = ?", (iso_week,)
    ).fetchone()
    row_id = existing["id"] if existing else f"WS-{uuid.uuid4().hex[:12]}"
    conn.execute(
        WEEKLY_SUMMARY_UPSERT_SQL,
        (
            row_id, iso_week, "unacknowledged",
            db.json_dump(snapshot), db.json_dump(coverage),
            db.json_dump(distribution), scope, db.json_dump(narrative),
            generated_at, None,
        ),
    )
    return row_id


def _row_result(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "iso_week": row["iso_week"],
        "status": row["status"],
        "node_status_snapshot_json": db.json_load(
            row["node_status_snapshot_json"], fallback={}
        ),
        "coverage_json": db.json_load(row["coverage_json"], fallback={}),
        "error_distribution_json": db.json_load(
            row["error_distribution_json"], fallback={}
        ),
        "evidence_scope": row["evidence_scope"],
        "narrative_json": db.json_load(row["narrative_json"], fallback={}),
        "generated_at": row["generated_at"],
        "acknowledged_at": row["acknowledged_at"],
    }


# ---------------------------------------------------------------------------
# ISO week helpers (aligned with manual_entry_service._iso_week_bounds style)
# ---------------------------------------------------------------------------


def _parse_iso_week(iso_week: str) -> tuple[int, int]:
    match = _ISO_WEEK_RE.match(iso_week)
    if not match:
        raise ValueError(f"invalid iso_week format (expected YYYY-Www), got: {iso_week!r}")
    year, week = int(match.group(1)), int(match.group(2))
    if not (1 <= week <= 53):
        raise ValueError(f"iso week out of range (1-53), got: {iso_week!r}")
    return year, week


def _week_dates(year: int, week: int) -> tuple[date, date]:
    """Monday of the ISO week → Monday of the next week (as date objects)."""
    # Jan 4 is always in ISO week 1; its Monday starts the first ISO week.
    jan4 = date(year, 1, 4)
    monday_w1 = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = monday_w1 + timedelta(weeks=week - 1)
    return monday, monday + timedelta(weeks=1)


def _iso_week_bounds(year: int, week: int) -> tuple[str, str]:
    """Monday 00:00 UTC of the ISO week → Monday 00:00 UTC of the next week,
    as ISO-8601 strings comparable with `db.now_iso()` created_at values."""
    monday, next_monday = _week_dates(year, week)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    end = datetime(
        next_monday.year, next_monday.month, next_monday.day, tzinfo=timezone.utc
    )
    return start.isoformat(), end.isoformat()


def _prev_iso_week(year: int, week: int) -> tuple[int, int]:
    """The ISO week immediately before (year, week); handles year rollover."""
    if week > 1:
        return year, week - 1
    iso_year, iso_week, _ = date(year - 1, 12, 28).isocalendar()
    return iso_year, iso_week


def _status_rank(status_code: str) -> int:
    return _STATUS_RANK.get(status_code, 0)
