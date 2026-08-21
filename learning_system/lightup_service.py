"""Lightup node progress service (M5) — 动机层 ① 孩子可见的进度视图.

Contract: docs/design/specs/2026-08-20-child-learning-companion-design.md
§6.3 (动机层: 每节课结束"点亮图谱节点"即时反馈) — 读聚合, 只读.

Role
----
Read-mostly, child-facing progress view. Aggregates `learner_node_status`
(当前 A/B/C/D), `graph_nodes` (名称/阶段) and `mastery_decisions`
(append-only 判定史) into one simple snapshot. 本服务零写入, 不新增表.

Semantics / 保守原则
--------------------
- 未建档节点 (不在 learner_node_status) → status='unknown', **不假装掌握**
  (unknown 不计入 mastered).
- 本周点亮 ("哪些绿了") 只依据 mastery_decisions 判定史判定方向:
  - status_at_week_start = 本周开始前最后一次有效判定的 new_status_code;
  - current = 本周结束前 (as-of 周闭) 最后一次有效判定;
  - 点亮 ⇔ status_at_week_start 存在 (有既往状态) 且
    rank(current) > rank(status_at_week_start) (净提升, 含 B/C/D→A 与任意升档).
  - 无既往判定史 (首次判定) → 方向不可知 → 不宣称点亮 (不假装掌握);
    降档/平档本周事件不点亮.
- 里程碑 (recent_milestones) = mastery_decisions 升档事件 (rank 上升),
  最近 N 条, 每条带 节点名/from/to/日期 (孩子可读, name 字段带出).

本周边界: 默认当前 ISO 周 (UTC), 可注入 ``iso_week`` 便于测试/回放.
ISO 周边界算法与 weekly_report_service / manual_entry_service 的私有
副本一致 (本仓库既有模式: 各服务私有复制, 不互相 import 私有函数).

输出形状保持简单 (孩子页面直接消费): nodes / summary / this_week /
recent_milestones.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone, timedelta

from learning_system import db

_STATUS_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
_VERDICTS = frozenset(_STATUS_RANK)

_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def lightup_snapshot(
    conn: sqlite3.Connection,
    *,
    iso_week: str | None = None,
    milestones: int = 5,
) -> dict:
    """Snapshot the child's progress view (点亮图谱节点即时反馈素材).

    Args:
        conn: sqlite3 connection (row_factory=Row) with the M4 schema.
        iso_week: ISO week key like ``2026-W34`` (Monday 00:00 UTC boundary)
            used for "本周点亮"; defaults to the current UTC ISO week.
        milestones: how many recent upgrade events to keep (default 5).

    Returns a plain dict:
        generated_at, iso_week,
        nodes: {node_id: {name, stage, status, updated_at}} (all graph nodes;
               status 'unknown' when not yet archived),
        summary: {total, mastered, by_stage: {stage: {total, mastered}},
                 progress_line},
        this_week: {iso_week, lit_up_node_ids, lit_up: [{node_id, name,
                   from, to}]},
        recent_milestones: [{node_id, name, from, to, date}] newest first.
    """
    if milestones < 0:
        raise ValueError(f"milestones must be >= 0, got: {milestones!r}")
    week_key = iso_week if iso_week is not None else _current_iso_week()
    year, week = _parse_iso_week(week_key)
    week_start, week_end = _iso_week_bounds(year, week)

    graph_rows = conn.execute(
        "select id, name, stage from graph_nodes order by id"
    ).fetchall()
    status_rows = {
        row["node_id"]: row
        for row in conn.execute(
            "select node_id, status_code, updated_at, status_revision"
            " from learner_node_status"
        ).fetchall()
    }

    nodes: dict[str, dict] = {}
    for row in graph_rows:
        st = status_rows.get(row["id"])
        status_code = st["status_code"] if st else None
        nodes[row["id"]] = {
            "name": row["name"],
            "stage": row["stage"],
            "status": status_code if status_code in _VERDICTS else "unknown",
            "updated_at": st["updated_at"] if st else None,
        }

    events_by_node, upgrades = _decision_timeline(conn, graph_rows)

    lit_up: list[dict] = []
    for node_id in sorted(events_by_node):
        change = _lit_up_this_week(events_by_node[node_id], week_start, week_end)
        if change is not None:
            lit_up.append({
                "node_id": node_id,
                "name": nodes[node_id]["name"],
                "from": change[0],
                "to": change[1],
            })

    recent = sorted(
        upgrades,
        key=lambda u: (u["date"], u["node_id"], u["from"], u["to"]),
        reverse=True,
    )[:milestones]

    mastered = sum(1 for n in nodes.values() if n["status"] == "A")
    by_stage: dict[str, dict] = {}
    for n in nodes.values():
        bucket = by_stage.setdefault(n["stage"], {"total": 0, "mastered": 0})
        bucket["total"] += 1
        if n["status"] == "A":
            bucket["mastered"] += 1
    total = len(nodes)

    return {
        "generated_at": db.now_iso(),
        "iso_week": week_key,
        "nodes": nodes,
        "summary": {
            "total": total,
            "mastered": mastered,
            "by_stage": dict(sorted(by_stage.items())),
            "progress_line": f"已点亮 {mastered} / {total} 个节点",
        },
        "this_week": {
            "iso_week": week_key,
            "lit_up_node_ids": [e["node_id"] for e in lit_up],
            "lit_up": lit_up,
        },
        "recent_milestones": recent,
    }


# ---------------------------------------------------------------------------
# aggregation helpers
# ---------------------------------------------------------------------------


def _decision_timeline(
    conn: sqlite3.Connection,
    graph_rows: list[sqlite3.Row],
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Per-node ordered verdict timeline + all upgrade events (milestones).

    Only rows whose new_status_code is a usable verdict (A/B/C/D) participate;
    legacy rows ('' / NO_CHANGE) are skipped conservatively. An upgrade event
    is one whose verdict ranks higher than the node's *previous event* verdict
    (first event never counts — 无既往状态不算升档).
    """
    rows = conn.execute(
        "select node_id, new_status_code, created_at from mastery_decisions"
        " order by node_id, created_at"
    ).fetchall()
    events_by_node: dict[str, list[dict]] = {}
    upgrades: list[dict] = []
    names = {r["id"]: r["name"] for r in graph_rows}

    for row in rows:
        verdict = row["new_status_code"]
        if verdict not in _VERDICTS:
            continue
        events = events_by_node.setdefault(row["node_id"], [])
        prev = events[-1]["verdict"] if events else None
        events.append({"verdict": verdict, "created_at": row["created_at"]})
        if prev is not None and _status_rank(verdict) > _status_rank(prev):
            upgrades.append({
                "node_id": row["node_id"],
                "name": names.get(row["node_id"], row["node_id"]),
                "from": prev,
                "to": verdict,
                "date": row["created_at"],
            })
    return events_by_node, upgrades


def _lit_up_this_week(
    events: list[dict], week_start: str, week_end: str
) -> tuple[str, str] | None:
    """Net-improvement vs the week-start status, as of week close.

    Returns (from, to) when the node had a prior status (before the week) and
    its week-close verdict ranks strictly higher — i.e. a genuine 升档 happened
    this week. First-ever decisions (no prior status) return None: 方向不可知
    → 不假装掌握.
    """
    status_at_start = _last_verdict_before(events, week_start)
    current = _last_verdict_before(events, week_end)
    if status_at_start is None or current is None:
        return None
    if _status_rank(current) <= _status_rank(status_at_start):
        return None
    return status_at_start, current


def _last_verdict_before(events: list[dict], boundary: str) -> str | None:
    """Effective status just before ``boundary`` (last verdict < boundary)."""
    result = None
    for e in events:
        if e["created_at"] >= boundary:
            break
        result = e["verdict"]
    return result


def _status_rank(status_code: str) -> int:
    return _STATUS_RANK.get(status_code, 0)


# ---------------------------------------------------------------------------
# ISO week helpers (aligned with weekly_report_service / manual_entry_service)
# ---------------------------------------------------------------------------


def _current_iso_week() -> str:
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


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
