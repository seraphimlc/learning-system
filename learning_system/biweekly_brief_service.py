"""Biweekly pedagogy brief service (M5) — 爸爸/教研看的数据简报 (只读聚合).

Contract: docs/design/specs/2026-08-20-child-learning-companion-design.md
§6.1/§6.2 (学期报告=周信聚合模板的形态) + P2 双周教研简报 (标注证据范围),
素材给 权衡 (解读数据简报) / 知几 / 爸爸 (决策).

Role
----
Read-mostly, 纯生成不落盘: aggregates the trailing ``period_weeks`` ISO weeks
(ending at ``end_iso_week``) into one structured dict + 一句话摘要. 零写入,
不新增表 — 简报可随时重生成, 无需存档 (weekly_summary 已按月存档周快照).

四块聚合
--------
1. 错因分布 (error_distribution): error_cause_log 周期内
   trust_status IN ('counted','rule_hit') 的行按 error_tag 聚合
   (分布查询纪律, 对齐 manual_entry_service.DISTRIBUTION_TRUST_STATUSES;
   pending_parent 一律不计入) — "哪类错反复出现".
2. 状态停滞 (stalled_nodes): "卡住"清单 — 周期开始前已是 C/D、现在仍 C/D、
   且周期内从未升到 C/D 之上 (无 B/A 判定事件) 的节点. 无判定史时回退:
   learner_node_status.updated_at < 周期起点 视为"周期前已是 C/D";
   周期内才落为 C/D 且无史 → 不宣称"连续 2 周卡住" (不假装).
3. 异常耗时 (high_attempt_nodes): 周期内 attempts 数异常的节点 —
   简单启发式: 次数 ≥ 3 且 ≥ 2× 该周期有作答节点的平均题量
   (防"碰巧多一题"误报; attempts 表无时长字段, 用题量作代理指标).
4. 周信联动 (weekly_letters / unacknowledged_weeks): 周期内 weekly_summary
   的 A1 预警 (narrative_json.a1_warnings) 与确认状态; 缺失周按未确认处理
   (爸爸可补看).

证据范围三分类 (§3.1, 双周简报必须标注): with_manual > with_all_correct
> system_only — 与 weekly_report_service 同优先序.

narrative_fn 注入: fn(payload) -> {"text": str}; 异常/非预期/None → 降级
模板一句话摘要 (不阻塞, narrative.degraded=True), 同 weekly_report 模式.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone, timedelta

from learning_system import db
from learning_system import manual_entry_service as mes

_STATUS_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
_VERDICTS = frozenset(_STATUS_RANK)

_SCOPE_LABELS = {
    "system_only": "仅系统内",
    "with_manual": "含手动补录",
    "with_all_correct": "含全对确认",
}

_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")

_TRUST_PLACEHOLDERS = ",".join("?" for _ in mes.DISTRIBUTION_TRUST_STATUSES)

# 停滞判定: 周期内出现过 B/A (rank > C) 事件 → 不算"从未升档".
_CD_CEILING_RANK = _STATUS_RANK["C"]

_MIN_ATTEMPTS_TO_FLAG = 3


def generate_biweekly_brief(
    conn: sqlite3.Connection,
    *,
    end_iso_week: str,
    period_weeks: int = 2,
    narrative_fn=None,
) -> dict:
    """Generate one biweekly pedagogy brief (纯生成, 不落盘).

    Args:
        conn: sqlite3 connection (row_factory=Row) with the M4 schema.
        end_iso_week: the last ISO week of the period, like ``2026-W34``.
        period_weeks: how many trailing ISO weeks the brief covers (default 2).
        narrative_fn: optional injected narrative callback
            ``fn(payload: dict) -> dict``; must return a dict with a non-empty
            ``"text"`` string, else the brief degrades to the deterministic
            template. ``None`` uses the template directly.

    Returns the structured brief dict (period / error_distribution /
    evidence_scope / stalled_nodes / high_attempt_nodes / attempts_total /
    weekly_letters / unacknowledged_weeks / narrative / generated_at).
    """
    year, week = _parse_iso_week(end_iso_week)
    if not isinstance(period_weeks, int) or isinstance(period_weeks, bool) \
            or period_weeks < 1:
        raise ValueError(
            f"period_weeks must be a positive int, got: {period_weeks!r}"
        )

    iso_weeks = _trailing_iso_weeks(year, week, period_weeks)
    first_year, first_week = _parse_iso_week(iso_weeks[0])
    window_start, _ = _iso_week_bounds(first_year, first_week)
    _, window_end = _iso_week_bounds(year, week)
    # 全对确认的日期窗口 (calendar dates of the period's Mondays).
    monday_first, _ = _week_dates(first_year, first_week)
    _, monday_after_end = _week_dates(year, week)

    distribution = _period_error_distribution(conn, window_start, window_end)
    scope, scope_flags = _period_evidence_scope(
        conn, window_start, window_end, monday_first, monday_after_end
    )
    stalled = _stalled_nodes(conn, window_start, window_end)
    high_attempts, attempts_total = _high_attempt_nodes(
        conn, window_start, window_end
    )
    letters, unacknowledged = _weekly_letter_linkage(conn, iso_weeks)

    payload = {
        "period": {
            "end_iso_week": end_iso_week,
            "iso_weeks": iso_weeks,
            "period_weeks": period_weeks,
            "window_start": window_start,
            "window_end": window_end,
        },
        "error_distribution": distribution,
        "evidence_scope": scope,
        "stalled_nodes": stalled,
        "high_attempt_nodes": high_attempts,
        "attempts_total": attempts_total,
        "weekly_letters": letters,
        "unacknowledged_weeks": unacknowledged,
    }
    narrative = _assemble_narrative(payload, narrative_fn)

    return {
        **payload,
        "evidence_scope_flags": scope_flags,
        "narrative": narrative,
        "generated_at": db.now_iso(),
    }


# ---------------------------------------------------------------------------
# aggregation helpers
# ---------------------------------------------------------------------------


def _period_error_distribution(
    conn: sqlite3.Connection, window_start: str, window_end: str
) -> dict[str, int]:
    """error_tag → count over the period; only counted/rule_hit (分布纪律)."""
    rows = conn.execute(
        f"select error_tag, count(*) as n from error_cause_log"
        f" where created_at >= ? and created_at < ?"
        f" and trust_status in ({_TRUST_PLACEHOLDERS})"
        f" group by error_tag order by error_tag",
        (window_start, window_end, *mes.DISTRIBUTION_TRUST_STATUSES),
    ).fetchall()
    return {row["error_tag"]: row["n"] for row in rows}


def _period_evidence_scope(
    conn: sqlite3.Connection,
    window_start: str,
    window_end: str,
    monday_first: date,
    monday_after_end: date,
) -> tuple[str, dict]:
    """§3.1 evidence-scope classification for the period (same priority as
    weekly_report_service: with_manual > with_all_correct > system_only)."""
    manual = conn.execute(
        f"select 1 from manual_error_entries"
        f" where created_at >= ? and created_at < ?"
        f" and trust_status in ({_TRUST_PLACEHOLDERS}) limit 1",
        (window_start, window_end, *mes.DISTRIBUTION_TRUST_STATUSES),
    ).fetchone()
    all_correct = conn.execute(
        "select 1 from daily_all_correct_confirmations"
        " where confirm_date >= ? and confirm_date < ? limit 1",
        (monday_first.isoformat(), monday_after_end.isoformat()),
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


def _stalled_nodes(
    conn: sqlite3.Connection, window_start: str, window_end: str
) -> list[dict]:
    """"卡住"清单: 周期前已是 C/D、现在仍 C/D、且周期内从未升到 C/D 之上.

    判定 (保守, 不假装):
    - 当前状态取 learner_node_status.status_code (回退到最近一次有效判定);
    - 周期开始前状态取最近一次 created_at < window_start 的有效判定;
    - 无判定史时回退: learner_node_status.updated_at < window_start 视为
      "周期前已是 C/D";
    - 周期内出现 B/A 判定事件 → 曾升档 → 不算卡住 (即使又回落).
    """
    rows = conn.execute(
        "select node_id, new_status_code, created_at from mastery_decisions"
        " order by node_id, created_at"
    ).fetchall()
    events_by_node: dict[str, list[dict]] = {}
    for row in rows:
        if row["new_status_code"] not in _VERDICTS:
            continue
        events_by_node.setdefault(row["node_id"], []).append({
            "verdict": row["new_status_code"],
            "created_at": row["created_at"],
        })

    names = {
        row["id"]: row["name"]
        for row in conn.execute("select id, name from graph_nodes").fetchall()
    }
    status_rows = {
        row["node_id"]: row
        for row in conn.execute(
            "select node_id, status_code, updated_at from learner_node_status"
        ).fetchall()
    }

    stalled: list[dict] = []
    for node_id, events in sorted(events_by_node.items()):
        entry = _stalled_for_node(
            node_id, events, status_rows, names, window_start, window_end
        )
        if entry is not None:
            stalled.append(entry)
    # 无判定史、但状态在周期前已是 C/D 的节点 (learner 状态回退路径).
    for node_id in sorted(set(status_rows) - set(events_by_node)):
        entry = _stalled_for_node(
            node_id, [], status_rows, names, window_start, window_end
        )
        if entry is not None:
            stalled.append(entry)
    return stalled


def _stalled_for_node(
    node_id: str,
    events: list[dict],
    status_rows: dict[str, sqlite3.Row],
    names: dict[str, str],
    window_start: str,
    window_end: str,
) -> dict | None:
    st = status_rows.get(node_id)
    current = st["status_code"] if st and st["status_code"] in _VERDICTS else None
    last_verdict = events[-1]["verdict"] if events else None
    if current is None:
        current = last_verdict
    if current not in ("C", "D"):
        return None

    status_at_start = _last_verdict_before(events, window_start)
    if status_at_start in ("C", "D"):
        # 判定史支持: 周期前已是 C/D; 周期内是否出现过 B/A?
        if _upgraded_above_cd(events, window_start, window_end):
            return None
        evidence = "decision_history"
    elif status_at_start is None:
        # 无判定史: 用 learner 状态更新时间证明"周期前已是 C/D".
        if st is None or st["updated_at"] >= window_start:
            return None  # 周期内才落为 C/D 且无史 → 不宣称连续 2 周
        if _upgraded_above_cd(events, window_start, window_end):
            return None
        evidence = "status_predates_period"
    else:
        # status_at_start in (A, B): 周期前已在 C/D 之上 → 不算卡住.
        return None

    return {
        "node_id": node_id,
        "name": names.get(node_id, node_id),
        "status": current,
        "evidence": evidence,
    }


def _upgraded_above_cd(
    events: list[dict], window_start: str, window_end: str
) -> bool:
    """Any B/A (rank > C) verdict event within the period window."""
    for e in events:
        if e["created_at"] < window_start:
            continue
        if e["created_at"] >= window_end:
            break
        if _status_rank(e["verdict"]) > _CD_CEILING_RANK:
            return True
    return False


def _last_verdict_before(events: list[dict], boundary: str) -> str | None:
    result = None
    for e in events:
        if e["created_at"] >= boundary:
            break
        result = e["verdict"]
    return result


def _status_rank(status_code: str) -> int:
    return _STATUS_RANK.get(status_code, 0)


def _high_attempt_nodes(
    conn: sqlite3.Connection, window_start: str, window_end: str
) -> tuple[list[dict], int]:
    """周期内 attempts 数异常的节点 (简单启发式: ≥3 且 ≥ 2× 均值)."""
    rows = conn.execute(
        "select node_id, count(*) as n from attempts"
        " where created_at >= ? and created_at < ?"
        " group by node_id",
        (window_start, window_end),
    ).fetchall()
    if not rows:
        return [], 0
    totals = {row["node_id"]: row["n"] for row in rows}
    attempts_total = sum(totals.values())
    mean = attempts_total / len(totals)
    threshold = max(_MIN_ATTEMPTS_TO_FLAG, 2 * mean)
    names = {
        row["id"]: row["name"]
        for row in conn.execute("select id, name from graph_nodes").fetchall()
    }
    flagged = [
        {"node_id": node_id, "name": names.get(node_id, node_id), "attempts": n}
        for node_id, n in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= threshold
    ]
    return flagged, attempts_total


def _weekly_letter_linkage(
    conn: sqlite3.Connection, iso_weeks: list[str]
) -> tuple[list[dict], list[str]]:
    """周信联动: 周期内 weekly_summary 的 A1 预警与确认状态 (缺失周按未确认)."""
    letters: list[dict] = []
    unacknowledged: list[str] = []
    for iso_week in iso_weeks:
        row = conn.execute(
            "select status, evidence_scope, narrative_json from weekly_summary"
            " where iso_week = ?",
            (iso_week,),
        ).fetchone()
        if row is None:
            letters.append({
                "iso_week": iso_week,
                "exists": False,
                "status": None,
                "evidence_scope": None,
                "a1_warnings": [],
            })
            unacknowledged.append(iso_week)
            continue
        narrative = db.json_load(row["narrative_json"], fallback={})
        warnings = narrative.get("a1_warnings", []) if isinstance(narrative, dict) \
            else []
        letters.append({
            "iso_week": iso_week,
            "exists": True,
            "status": row["status"],
            "evidence_scope": row["evidence_scope"],
            "a1_warnings": warnings,
        })
        if row["status"] != "acknowledged":
            unacknowledged.append(iso_week)
    return letters, unacknowledged


# ---------------------------------------------------------------------------
# narrative assembly (LLM callback + template degradation)
# ---------------------------------------------------------------------------


def _assemble_narrative(payload: dict, narrative_fn) -> dict:
    template_parts = _template_parts(payload)
    source = "template"
    text = _render_template(template_parts)

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
        text = _render_template(template_parts)

    return {
        "source": source,
        "text": text,
        "template": template_parts,
        "degraded": source == "template",
    }


def _template_parts(payload: dict) -> dict:
    weeks = payload["period"]["iso_weeks"]
    period_label = f"{weeks[0]}~{weeks[-1]}"
    scope_label = _SCOPE_LABELS[payload["evidence_scope"]]

    distribution = payload["error_distribution"]
    if distribution:
        top_tag, top_count = sorted(
            distribution.items(), key=lambda kv: (-kv[1], kv[0])
        )[0]
        error_line = f"错因集中在「{top_tag}」共 {top_count} 次（证据范围：{scope_label}）"
    else:
        error_line = f"无明显错因（证据范围：{scope_label}）"

    stalled = payload["stalled_nodes"]
    if stalled:
        names = "、".join(s["name"] for s in stalled)
        stalled_line = f"{len(stalled)} 个节点卡在 C/D 未升档：{names}"
    else:
        stalled_line = "无卡住节点"

    high = payload["high_attempt_nodes"]
    if high:
        parts = "、".join(f"{n['name']}（{n['attempts']} 次）" for n in high)
        attempts_line = f"作答量偏多：{parts}"
    else:
        attempts_line = "作答量正常"

    unack = payload["unacknowledged_weeks"]
    letters_line = f"周信未确认：{'、'.join(unack)}" if unack else "周信均已确认"

    return {
        "period_label": period_label,
        "error_line": error_line,
        "stalled_line": stalled_line,
        "attempts_line": attempts_line,
        "letters_line": letters_line,
    }


def _render_template(parts: dict) -> str:
    return (
        f"双周教研简报（{parts['period_label']}）：{parts['error_line']}；"
        f"{parts['stalled_line']}；{parts['attempts_line']}；{parts['letters_line']}。"
    )


# ---------------------------------------------------------------------------
# ISO week helpers (aligned with weekly_report_service / manual_entry_service)
# ---------------------------------------------------------------------------


def _parse_iso_week(iso_week: str) -> tuple[int, int]:
    match = _ISO_WEEK_RE.match(iso_week)
    if not match:
        raise ValueError(f"invalid iso_week format (expected YYYY-Www), got: {iso_week!r}")
    year, week = int(match.group(1)), int(match.group(2))
    if not (1 <= week <= 53):
        raise ValueError(f"iso week out of range (1-53), got: {iso_week!r}")
    return year, week


def _trailing_iso_weeks(year: int, week: int, count: int) -> list[str]:
    """The last ``count`` ISO weeks ending at (year, week), oldest first."""
    result = []
    y, w = year, week
    for _ in range(count):
        result.append(f"{y:04d}-W{w:02d}")
        y, w = _prev_iso_week(y, w)
    result.reverse()
    return result


def _prev_iso_week(year: int, week: int) -> tuple[int, int]:
    """The ISO week immediately before (year, week); handles year rollover."""
    if week > 1:
        return year, week - 1
    iso_year, iso_week, _ = date(year - 1, 12, 28).isocalendar()
    return iso_year, iso_week


def _week_dates(year: int, week: int) -> tuple[date, date]:
    """Monday of the ISO week → Monday of the next week (as date objects)."""
    jan4 = date(year, 1, 4)
    monday_w1 = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = monday_w1 + timedelta(weeks=week - 1)
    return monday, monday + timedelta(weeks=1)


def _iso_week_bounds(year: int, week: int) -> tuple[str, str]:
    """Monday 00:00 UTC of the ISO week → Monday 00:00 UTC of the next week,
    as ISO-8601 strings comparable with `db.now_iso()` created_at values."""
    monday, next_monday = _week_dates(year, week)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    end = datetime(next_monday.year, next_monday.month, next_monday.day,
                   tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()
