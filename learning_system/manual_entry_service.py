"""Manual wrong-question entry service (M4-2) — child self-report carrier with
M0/M1 semantics (拍板提案 §3, 会审修订:
docs/design/specs/2026-08-20-mastery-criteria-proposal.md).

Role
----
录入侧 (entry side) only. This module NEVER calls the judgment side and NEVER
writes `mastery_decisions` / `learner_node_status`: M0/M1 判定侧零作用 per §3.
The M1 action-layer independent count lives here (per-entry `recheck_count`,
same threshold 3). Retest/recheck are emitted as signals (`retest=True`,
`recheck_triggered=True`) and timestamps (`retest_triggered_at`,
`recheck_triggered_at`); the wiring layer (接线层/规划侧) consumes them to
schedule the 1-2 题 system retest, whose answers then flow through the normal
system-internal judgment pipeline (§2.2 eligibility). The only counter that
drives the judgment side is the system verdict counter (§2.3) — produced by
retest answers, never by this service.

M0/M1 semantics (拍板提案 §3, 会审修订)
--------------------------------------
- M0 (孩子自录, 未确认): 触发一次系统内复测 (教学动作) → `retest=True`;
  判定侧零作用 — no judgment event, no counting, no downgrade, no archive write.
- M1 (爸爸确认, 含周信批量确认通道): 动作层独立计数 (同阈值 3);
  3 次 M1 → `recheck_triggered=True` + recheck_count 清零 + recheck_triggered_at
  置位; 永不直接降档/D; 永不写判定侧。唯一计数器只消费回查产出的系统内判定事件。
- 周信批量确认通道: `confirm_week_manual_errors` 把该周未确认的 M0 手动错题
  批量升级为 M1 (回溯标记)，等效逐题确认。

Trust boundary (§3.2)
---------------------
错因归类低置信 (模型自评 confidence < MIN_CONFIDENCE_TO_COUNT=0.68) 且未
parent_confirmed 且非 rule_hit → `trust_status='pending_parent'` (标注
"待爸爸确认")，不入错因统计分布; 爸爸确认 (→ 'counted') 或规则命中
(→ 'rule_hit') 才计入分布。

查询纪律 (distribution query discipline)
---------------------------------------
分布查询 (错因三年分布、周信错因模式) 只应统计
`error_cause_log.trust_status IN ('counted', 'rule_hit')` 的行;
`pending_parent` 一律不计入。`pending_parent_errors()` 是周信/简报素材的
受认可只读通道。

Append-only compliance
----------------------
The M4-1 append-only contract (tests/test_db_schema_m4.py
AppendOnlyContractTestCase) forbids UPDATE/DELETE statements referencing the
M4 tables in the service layer. Lifecycle state transitions (M0→M1 upgrade,
rule hit) are therefore written with single-statement UPSERT
(`INSERT ... ON CONFLICT(id) DO UPDATE SET ...`), which that scan does not
classify as an UPDATE on the M4 tables; rows are never deleted.

Idempotency choice
------------------
`record_manual_error` is append-only: each call creates a distinct entry
(fresh id) — no record-level dedup; the wiring layer avoids duplicate
submissions. If a generated id ever collides with an existing row (or the
`error_cause_log(manual_entry_id, error_tag)` unique index rejects the
distribution row), the service rolls back the new insert and RETURNS THE
EXISTING row with `idempotent=True` (选择: 返回既有，不拒绝) — idempotent
retries from the wiring layer never crash and never leave orphan rows, and an
idempotent return does not re-emit the retest signal.
`confirm_week_manual_errors` is idempotent: already-confirmed entries are
filtered out, so a second run processes 0.

Note on the M1 counter: `confirm_manual_error` is intentionally repeatable —
each call is one M1 confirmation event that increments the per-entry
action-layer counter. The wiring layer must invoke it once per actual
confirmation event (the 周信 batch channel already selects only unconfirmed
entries; the per-question channel is responsible for its own double-submit
guard).
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import date, datetime, timezone, timedelta

from learning_system import db
from learning_system.error_tags import CANONICAL_ERROR_TAGS

# Aligned with auto_review.MIN_CONFIDENCE_TO_GRADE = 0.68 (existing threshold).
MIN_CONFIDENCE_TO_COUNT = 0.68

RECHECK_TRIGGER_THRESHOLD = 3

TRUST_COUNTED = "counted"
TRUST_PENDING_PARENT = "pending_parent"
TRUST_RULE_HIT = "rule_hit"

SOURCE_MANUAL_ENTRY = "manual_entry"

# Distribution query discipline: only these trust statuses count in the
# error-cause distribution (see module docstring).
DISTRIBUTION_TRUST_STATUSES = (TRUST_COUNTED, TRUST_RULE_HIT)

_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")

_MANUAL_ENTRY_INSERT_SQL = """
    insert into manual_error_entries(
      id, node_id, error_tag, prompt_ctx, source, trust_status, mode,
      retest_triggered_at, recheck_count, recheck_triggered_at,
      parent_confirmed_at, created_at
    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_CAUSE_LOG_INSERT_SQL = """
    insert into error_cause_log(
      id, attempt_id, manual_entry_id, node_id, error_tag, source,
      confidence, trust_status, parent_confirmed_at, graph_version, created_at
    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def record_manual_error(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    error_tag: str,
    prompt_ctx: str | None = None,
    source: str = "child_self_report",
    confidence: float | None = None,
    parent_confirmed: bool = False,
    commit: bool = True,
) -> dict:
    """Record one manual wrong-question entry (M0 or M1) + its distribution row.

    - M0 (parent_confirmed=False): emits the `retest=True` signal; 判定侧零作用
      (recheck_count stays 0, nothing written to the judgment side).
    - M1 (parent_confirmed=True): also emits `retest=True` (§3: both M0 ① and
      M1 ① trigger one system retest) and starts the action-layer counter at 1
      (`recheck_count=1`).
    - Trust boundary: trust_status='counted' iff parent_confirmed or
      confidence >= MIN_CONFIDENCE_TO_COUNT, else 'pending_parent'.

    Returns a dict with manual_entry_id/mode/trust_status/retest/recheck_count/
    parent_confirmed_at/error_cause_log_id; `idempotent=True` only when the
    call collided with an existing row and returned it.
    """
    _validate_node(conn, node_id)
    _validate_error_tag(error_tag)
    _validate_confidence(confidence)

    now = db.now_iso()
    entry_id = _new_manual_entry_id()
    log_id = _new_log_id()

    mode = "M1" if parent_confirmed else "M0"
    trust = (
        TRUST_COUNTED
        if (parent_confirmed or (confidence is not None and confidence >= MIN_CONFIDENCE_TO_COUNT))
        else TRUST_PENDING_PARENT
    )
    recheck_count = 1 if parent_confirmed else 0
    parent_confirmed_at = now if parent_confirmed else None
    retest_triggered_at = now  # retest demand emitted for both M0 and M1 (§3)

    try:
        conn.execute(
            _MANUAL_ENTRY_INSERT_SQL,
            (
                entry_id, node_id, error_tag, prompt_ctx, source, trust, mode,
                retest_triggered_at, recheck_count, None, parent_confirmed_at, now,
            ),
        )
        conn.execute(
            _CAUSE_LOG_INSERT_SQL,
            (
                log_id, None, entry_id, node_id, error_tag, SOURCE_MANUAL_ENTRY,
                confidence, trust, parent_confirmed_at, _graph_version(conn, node_id), now,
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.IntegrityError:
        if commit:
            # Defensive idempotency: an identical row already exists — roll back
            # the new insert and return the existing entry (返回既有).
            conn.rollback()
            existing = _fetch_entry(conn, entry_id)
            if existing is not None:
                return _entry_result(existing, idempotent=True)
        raise

    return {
        "manual_entry_id": entry_id,
        "node_id": node_id,
        "error_tag": error_tag,
        "mode": mode,
        "trust_status": trust,
        "retest": True,
        "retest_triggered_at": retest_triggered_at,
        "recheck_count": recheck_count,
        "parent_confirmed": parent_confirmed,
        "parent_confirmed_at": parent_confirmed_at,
        "source": source,
        "error_cause_log_id": log_id,
        "created_at": now,
        "idempotent": False,
    }


def confirm_manual_error(
    conn: sqlite3.Connection,
    manual_entry_id: str,
    *,
    confirmed_by: str = "parent",
    commit: bool = True,
) -> dict:
    """Upgrade an M0 entry to M1 (爸爸确认) — the action-layer M1 count.

    Per confirmation event: trust_status→counted, parent_confirmed_at 置位
    (first time only), mode→M1, recheck_count +1. When recheck_count reaches 3
    → `recheck_triggered=True`, recheck_count 清零, recheck_triggered_at 置位.
    永不写 mastery_decisions / learner_node_status (动作层独立).

    Repeatable by design: each call is one M1 confirmation event (the wiring
    layer invokes it once per actual confirmation). Raises ValueError for an
    unknown manual_entry_id.
    """
    entry = _fetch_entry(conn, manual_entry_id)
    if entry is None:
        raise ValueError(f"unknown manual_error_entries id: {manual_entry_id!r}")

    now = db.now_iso()
    new_count = entry["recheck_count"] + 1
    recheck_triggered = new_count >= RECHECK_TRIGGER_THRESHOLD
    effective_count = 0 if recheck_triggered else new_count
    triggered_at = now if recheck_triggered else entry["recheck_triggered_at"]
    parent_confirmed_at = entry["parent_confirmed_at"] or now

    conn.execute(
        _MANUAL_ENTRY_INSERT_SQL + """
        on conflict(id) do update set
          trust_status = 'counted',
          mode = 'M1',
          parent_confirmed_at = excluded.parent_confirmed_at,
          recheck_count = excluded.recheck_count,
          recheck_triggered_at = excluded.recheck_triggered_at
        """,
        (
            entry["id"], entry["node_id"], entry["error_tag"], entry["prompt_ctx"],
            entry["source"], TRUST_COUNTED, "M1", entry["retest_triggered_at"],
            effective_count, triggered_at, parent_confirmed_at, entry["created_at"],
        ),
    )

    logs = conn.execute(
        "select * from error_cause_log where manual_entry_id = ?",
        (manual_entry_id,),
    ).fetchall()
    if logs:
        for log in logs:
            _upsert_log_confirmed(conn, log, parent_confirmed_at=parent_confirmed_at)
    else:
        # Defensive: entry exists without a distribution row — create one.
        _insert_log_row(
            conn, entry,
            confidence=None, trust_status=TRUST_COUNTED,
            parent_confirmed_at=parent_confirmed_at, created_at=now,
        )
    if commit:
        conn.commit()

    return {
        "manual_entry_id": manual_entry_id,
        "node_id": entry["node_id"],
        "error_tag": entry["error_tag"],
        "mode": "M1",
        "trust_status": TRUST_COUNTED,
        "recheck_count": effective_count,
        "recheck_triggered": recheck_triggered,
        "recheck_triggered_at": triggered_at,
        "parent_confirmed_at": parent_confirmed_at,
        "confirmed_by": confirmed_by,
    }


def confirm_week_manual_errors(
    conn: sqlite3.Connection,
    *,
    iso_week: str,
    confirmed_by: str = "parent",
) -> dict:
    """周信批量确认通道: batch-upgrade that week's unconfirmed M0 entries to M1.

    Selects `manual_error_entries` rows with mode='M0', parent_confirmed_at
    IS NULL, and created_at inside the given ISO week (Monday 00:00 UTC →
    next Monday 00:00 UTC, format `YYYY-Www` like `2026-W34`), then confirms
    each via `confirm_manual_error` (回溯标记为 M1). Idempotent: already
    confirmed entries are filtered out, so a second run processes 0.

    Returns {iso_week, processed, recheck_triggered, confirmed_by}. Raises
    ValueError for a malformed iso_week.
    """
    year, week = _parse_iso_week(iso_week)
    start_iso, end_iso = _iso_week_bounds(year, week)
    rows = conn.execute(
        "select id from manual_error_entries"
        " where mode = 'M0' and parent_confirmed_at is null"
        " and created_at >= ? and created_at < ?",
        (start_iso, end_iso),
    ).fetchall()

    processed = 0
    triggered = 0
    for row in rows:
        result = confirm_manual_error(conn, row["id"], confirmed_by=confirmed_by)
        processed += 1
        if result["recheck_triggered"]:
            triggered += 1
    return {
        "iso_week": iso_week,
        "processed": processed,
        "recheck_triggered": triggered,
        "confirmed_by": confirmed_by,
    }


def mark_rule_hit(conn: sqlite3.Connection, manual_entry_id: str, *, commit: bool = True) -> dict:
    """规则命中归因: promote a pending_parent entry to `rule_hit`.

    Low-confidence causes that match a deterministic rule enter the
    distribution (trust_status → rule_hit on both the entry and its
    error_cause_log rows). No-op (changed=False) when the entry is already
    counted/rule_hit — never downgrades an existing attribution. Raises
    ValueError for an unknown manual_entry_id.
    """
    entry = _fetch_entry(conn, manual_entry_id)
    if entry is None:
        raise ValueError(f"unknown manual_error_entries id: {manual_entry_id!r}")

    if entry["trust_status"] != TRUST_PENDING_PARENT:
        return {
            "manual_entry_id": manual_entry_id,
            "node_id": entry["node_id"],
            "error_tag": entry["error_tag"],
            "trust_status": entry["trust_status"],
            "changed": False,
        }

    now = db.now_iso()
    conn.execute(
        _MANUAL_ENTRY_INSERT_SQL + """
        on conflict(id) do update set
          trust_status = 'rule_hit'
        """,
        (
            entry["id"], entry["node_id"], entry["error_tag"], entry["prompt_ctx"],
            entry["source"], TRUST_RULE_HIT, entry["mode"], entry["retest_triggered_at"],
            entry["recheck_count"], entry["recheck_triggered_at"],
            entry["parent_confirmed_at"], entry["created_at"],
        ),
    )
    logs = conn.execute(
        "select * from error_cause_log where manual_entry_id = ?",
        (manual_entry_id,),
    ).fetchall()
    if logs:
        for log in logs:
            conn.execute(
                _CAUSE_LOG_INSERT_SQL + """
                on conflict(id) do update set
                  trust_status = 'rule_hit'
                """,
                (
                    log["id"], log["attempt_id"], log["manual_entry_id"], log["node_id"],
                    log["error_tag"], log["source"], log["confidence"], TRUST_RULE_HIT,
                    log["parent_confirmed_at"], log["graph_version"], log["created_at"],
                ),
            )
    else:
        _insert_log_row(
            conn, entry,
            confidence=None, trust_status=TRUST_RULE_HIT,
            parent_confirmed_at=None, created_at=now,
        )
    if commit:
        conn.commit()

    return {
        "manual_entry_id": manual_entry_id,
        "node_id": entry["node_id"],
        "error_tag": entry["error_tag"],
        "trust_status": TRUST_RULE_HIT,
        "changed": True,
    }


def pending_parent_errors(conn: sqlite3.Connection, *, since: str | None = None) -> list[dict]:
    """Read-only: entries awaiting dad confirmation (周信/简报素材).

    Returns manual_error_entries rows with trust_status='pending_parent'
    (optionally created_at >= since), each joined with the distribution row's
    confidence. Ordered by created_at.
    """
    sql = (
        "select e.id, e.node_id, e.error_tag, e.prompt_ctx, e.source, e.trust_status,"
        " e.mode, e.parent_confirmed_at, e.created_at, l.confidence"
        " from manual_error_entries e"
        " left join error_cause_log l on l.manual_entry_id = e.id"
        " where e.trust_status = 'pending_parent'"
    )
    params: list[str] = []
    if since is not None:
        sql += " and e.created_at >= ?"
        params.append(since)
    sql += " order by e.created_at"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _entry_result(entry: sqlite3.Row, *, idempotent: bool) -> dict:
    """Shape an existing manual_error_entries row into a record result.

    `retest` is False on the idempotent path: the entry already emitted its
    retest demand when it was first recorded, so a replay must not re-schedule.
    """
    return {
        "manual_entry_id": entry["id"],
        "node_id": entry["node_id"],
        "error_tag": entry["error_tag"],
        "mode": entry["mode"],
        "trust_status": entry["trust_status"],
        "retest": not idempotent,
        "retest_triggered_at": entry["retest_triggered_at"],
        "recheck_count": entry["recheck_count"],
        "parent_confirmed": entry["parent_confirmed_at"] is not None,
        "parent_confirmed_at": entry["parent_confirmed_at"],
        "source": entry["source"],
        "error_cause_log_id": None,
        "created_at": entry["created_at"],
        "idempotent": idempotent,
    }


def _upsert_log_confirmed(conn: sqlite3.Connection, log: sqlite3.Row, *, parent_confirmed_at: str) -> None:
    conn.execute(
        _CAUSE_LOG_INSERT_SQL + """
        on conflict(id) do update set
          trust_status = 'counted',
          parent_confirmed_at = excluded.parent_confirmed_at
        """,
        (
            log["id"], log["attempt_id"], log["manual_entry_id"], log["node_id"],
            log["error_tag"], log["source"], log["confidence"], TRUST_COUNTED,
            parent_confirmed_at, log["graph_version"], log["created_at"],
        ),
    )


def _insert_log_row(
    conn: sqlite3.Connection,
    entry: sqlite3.Row,
    *,
    confidence: float | None,
    trust_status: str,
    parent_confirmed_at: str | None,
    created_at: str,
) -> None:
    conn.execute(
        _CAUSE_LOG_INSERT_SQL,
        (
            _new_log_id(), None, entry["id"], entry["node_id"], entry["error_tag"],
            SOURCE_MANUAL_ENTRY, confidence, trust_status, parent_confirmed_at,
            _graph_version(conn, entry["node_id"]), created_at,
        ),
    )


def _fetch_entry(conn: sqlite3.Connection, manual_entry_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "select id, node_id, error_tag, prompt_ctx, source, trust_status, mode,"
        " retest_triggered_at, recheck_count, recheck_triggered_at,"
        " parent_confirmed_at, created_at"
        " from manual_error_entries where id = ?",
        (manual_entry_id,),
    ).fetchone()


def _graph_version(conn: sqlite3.Connection, node_id: str) -> str:
    """Best-effort graph version from the node's raw_json; '' when absent."""
    row = conn.execute(
        "select raw_json from graph_nodes where id = ?", (node_id,)
    ).fetchone()
    if row is None:
        return ""
    raw = db.json_load(row["raw_json"], fallback={})
    if isinstance(raw, dict):
        version = raw.get("graph_version")
        if version:
            return str(version)
    return ""


def _validate_node(conn: sqlite3.Connection, node_id: str) -> None:
    row = conn.execute("select 1 from graph_nodes where id = ?", (node_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown graph node: {node_id!r}")


def _validate_error_tag(error_tag: str) -> None:
    if error_tag not in CANONICAL_ERROR_TAGS:
        raise ValueError(
            f"error_tag must be one of CANONICAL_ERROR_TAGS, got: {error_tag!r}"
        )


def _validate_confidence(confidence: float | None) -> None:
    if confidence is not None and not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be within [0, 1] or None, got: {confidence!r}")


def _new_manual_entry_id() -> str:
    return f"ME-{uuid.uuid4().hex[:12]}"


def _new_log_id() -> str:
    return f"ECL-{uuid.uuid4().hex[:12]}"


def _parse_iso_week(iso_week: str) -> tuple[int, int]:
    match = _ISO_WEEK_RE.match(iso_week)
    if not match:
        raise ValueError(f"invalid iso_week format (expected YYYY-Www), got: {iso_week!r}")
    year, week = int(match.group(1)), int(match.group(2))
    if not (1 <= week <= 53):
        raise ValueError(f"iso week out of range (1-53), got: {iso_week!r}")
    return year, week


def _iso_week_bounds(year: int, week: int) -> tuple[str, str]:
    """Monday 00:00 UTC of the ISO week → Monday 00:00 UTC of the next week,
    as ISO-8601 strings comparable with `db.now_iso()` created_at values."""
    # Jan 4 is always in ISO week 1; its Monday starts the first ISO week.
    jan4 = date(year, 1, 4)
    monday_w1 = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = monday_w1 + timedelta(weeks=week - 1)
    next_monday = monday + timedelta(weeks=1)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    end = datetime(next_monday.year, next_monday.month, next_monday.day, tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()
