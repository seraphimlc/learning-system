"""Durable step-level audit events for question production."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def record_event(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    stage_id: str | None,
    stage_name: str,
    logical_key: str = "",
    step_name: str,
    event_type: str,
    attempt: int,
    status: str,
    input_value: Any = None,
    output_value: Any = None,
    errors: list[Any] | None = None,
    created_at: str | None = None,
    completed_at: str | None = None,
) -> str:
    if status not in {"started", "completed", "rejected", "failed", "skipped"}:
        raise ValueError(f"invalid audit event status: {status}")
    input_value = {} if input_value is None else input_value
    output_value = {} if output_value is None else output_value
    errors = list(errors or [])
    event_id = f"PAE-{uuid.uuid4().hex[:12]}"
    input_json = json.dumps(input_value, ensure_ascii=False, sort_keys=True)
    output_json = json.dumps(output_value, ensure_ascii=False, sort_keys=True)
    conn.execute(
        """
        insert into production_audit_events(
          id,run_id,stage_id,stage_name,logical_key,step_name,event_type,
          attempt,status,input_json,output_json,input_digest_sha256,
          output_digest_sha256,error_json,created_at,completed_at
        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            run_id,
            stage_id,
            stage_name,
            logical_key,
            step_name,
            event_type,
            int(attempt),
            status,
            input_json,
            output_json,
            _digest(input_value),
            _digest(output_value),
            json.dumps(errors, ensure_ascii=False, sort_keys=True),
            created_at or _now(),
            completed_at,
        ),
    )
    return event_id
