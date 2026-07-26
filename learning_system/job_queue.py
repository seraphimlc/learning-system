from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from . import db


V3_JOB_TYPES = {
    "answer_analysis",
    "group_answer_analysis",
    "evidence_validation",
    "evaluation_update",
    "planner_decision",
    "teaching_generation",
    "answer_review",
    "stuck_interruption",
}
V3_JOB_PAYLOAD_SCHEMA_VERSION = "2026-07-10.v3.job-payload.skeleton"
V5_MODEL_JOB_TYPES = {
    "answer_analysis",
    "group_answer_analysis",
    "evaluation_update",
    "planner_decision",
    "teaching_generation",
}
V5_RESERVED_DETERMINISTIC_JOB_TYPES = {"evidence_validation", "stuck_interruption"}
V5_JOB_TYPES = V5_MODEL_JOB_TYPES | V5_RESERVED_DETERMINISTIC_JOB_TYPES
V5_JOB_PAYLOAD_SCHEMA_VERSION = "2026-07-11.v5.model-job.v1"
V5_ACTIVE_STATUSES = {"queued", "claimed", "running", "waiting", "retry"}
V5_TERMINAL_STATUSES = {"succeeded", "blocked", "dead_letter"}
V5_NON_RUNNABLE_STATUSES = {"waiting", "blocked", "dead_letter", "succeeded"}
V5_RETRY_BACKOFF_SECONDS = (20, 60, 180)


class JobLeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class JobQueueResult:
    job_id: str
    status: str
    reused_existing: bool = False
    applied: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "reused_existing": self.reused_existing,
            "applied": self.applied,
        }


class JobQueue:
    """Small SQLite queue adapter.

    `background_jobs.run_count` is the count of actual execution starts. It is
    incremented only by `start()` after a worker owns the lease. Retry/recover
    transitions only move status and schedule backoff; they do not count as an
    additional execution attempt.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def enqueue(
        self,
        job_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
        *,
        depends_on_job_id: str | None = None,
        commit: bool = True,
    ) -> JobQueueResult:
        if job_type not in V3_JOB_TYPES:
            raise ValueError(f"Invalid v3 job type: {job_type}")
        if not idempotency_key:
            raise ValueError("v3 job idempotency_key is required")
        session_id = str(payload.get("legacy_session_id") or payload.get("session_id") or "")
        if not session_id:
            raise ValueError("v3 job payload requires legacy_session_id")
        if _is_v5_idempotency_key(idempotency_key) and job_type == "teaching_generation" and payload.get("new_knowledge_request"):
            required = ("payload_schema_version", "flow_id", "graph_version", "question_bank_version", "target_node_id")
        else:
            required = ("payload_schema_version", "flow_id", "flow_step_id", "attempt_id", "graph_version", "question_bank_version")
        missing = [key for key in required if not payload.get(key)]
        if missing:
            raise ValueError("v3 job payload missing required lineage: " + ", ".join(missing))

        existing = self.conn.execute(
            """
            select id, status
            from background_jobs
            where idempotency_key = ?
              and status in ('queued','claimed','running','waiting','retry')
            order by created_at desc, id desc
            limit 1
            """,
            (idempotency_key,),
        ).fetchone()
        if existing:
            return JobQueueResult(job_id=existing["id"], status=existing["status"], reused_existing=True)
        if _is_v5_idempotency_key(idempotency_key):
            # Terminal same-key retries are explicit recovery decisions: enqueue reuses
            # blocked/dead_letter/succeeded rows instead of silently forking a new stage.
            terminal = self.terminal_stage_for_key(idempotency_key)
            if terminal:
                return JobQueueResult(job_id=terminal["id"], status=terminal["status"], reused_existing=True)

        now = db.now_iso()
        job_id = f"BJ-{uuid.uuid4().hex[:12]}"
        depends_on = list(payload.get("depends_on") or [])
        if depends_on_job_id:
            depends_on.append(depends_on_job_id)
        self.conn.execute(
            """
            insert into background_jobs(
              id, job_type, session_id, attempt_id, status, run_count,
              payload_json, last_error, created_at, updated_at, started_at, finished_at,
              idempotency_key, flow_id, flow_revision, flow_step_id, step_revision,
              attempt_version, analysis_version, graph_version, question_bank_version,
              question_id, review_record_id, candidate_packet_id, depends_on_json,
              depends_on_job_id, provider_mode, payload_schema_version, available_at,
              route_meta_json
            ) values (?, ?, ?, ?, 'queued', 0, ?, '', ?, ?, null, null,
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                session_id,
                payload.get("attempt_id"),
                db.json_dump(payload),
                now,
                now,
                idempotency_key,
                payload.get("flow_id"),
                int(payload.get("flow_revision") or 0),
                payload.get("flow_step_id"),
                int(payload.get("step_revision") or 0),
                int(payload.get("attempt_version") or 0),
                int(payload.get("analysis_version") or 0),
                payload.get("graph_version"),
                payload.get("question_bank_version"),
                payload.get("question_id"),
                str(payload.get("review_record_id") or ""),
                str(payload.get("candidate_packet_id") or ""),
                db.json_dump(depends_on),
                depends_on_job_id,
                str(payload.get("provider_mode") or "not_configured"),
                str(payload.get("payload_schema_version") or _default_payload_schema_version(job_type, idempotency_key)),
                str(payload.get("available_at") or now),
                db.json_dump(payload.get("route_meta") or {}),
            ),
        )
        if commit:
            self.conn.commit()
        return JobQueueResult(job_id=job_id, status="queued")

    def claim(
        self,
        worker_id: str,
        now: str,
        limit: int = 1,
        *,
        lease_seconds: int = 60,
        flow_id: str | None = None,
    ) -> list[dict[str, Any]]:
        flow_filter = "and flow_id = ?" if flow_id else ""
        params: list[Any] = [now, now]
        if flow_id:
            params.append(flow_id)
        params.append(int(limit))
        rows = self.conn.execute(
            f"""
            select id
            from background_jobs
            where (
                (status = 'queued' and (available_at is null or available_at <= ?))
                or (status = 'retry' and (retry_after is null or retry_after <= ?))
              )
              {flow_filter}
              and (
                depends_on_job_id is null
                or exists (
                  select 1
                  from background_jobs dep
                  where dep.id = background_jobs.depends_on_job_id
                    and dep.status = 'succeeded'
                )
              )
            order by created_at, id
            limit ?
            """,
            params,
        ).fetchall()
        claimed: list[dict[str, Any]] = []
        for row in rows:
            lease_expires_at = _add_seconds(now, lease_seconds)
            claim_token = uuid.uuid4().hex
            updated = self.conn.execute(
                """
                update background_jobs
                set status = 'claimed',
                    lease_owner = ?,
                    claim_generation = claim_generation + 1,
                    claim_token = ?,
                    locked_at = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                where id = ?
                  and (status = 'queued' or status = 'retry')
                """,
                (worker_id, claim_token, now, lease_expires_at, now, row["id"]),
            ).rowcount
            if updated:
                job = self.conn.execute("select * from background_jobs where id = ?", (row["id"],)).fetchone()
                claimed.append(dict(job))
        self.conn.commit()
        return claimed

    def start(
        self,
        job_id: str,
        worker_id: str,
        *,
        claim_generation: int | None = None,
        claim_token: str | None = None,
        now: str | None = None,
    ) -> JobQueueResult:
        return self._transition_for_owner(
            job_id,
            worker_id,
            "claimed",
            "running",
            started=True,
            claim_generation=claim_generation,
            claim_token=claim_token,
            now=now,
        )

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        claim_generation: int | None = None,
        claim_token: str | None = None,
        lease_seconds: int = 60,
        now: str | None = None,
    ) -> JobQueueResult:
        now = now or db.now_iso()
        updated = self.conn.execute(
            """
            update background_jobs
            set updated_at = ?, lease_expires_at = ?
            where id = ?
              and lease_owner = ?
              and status in ('claimed','running')
              and (lease_expires_at is null or lease_expires_at > ?)
              and (? is null or claim_generation = ?)
              and (? is null or claim_token = ?)
            """,
            (
                now,
                _add_seconds(now, lease_seconds),
                job_id,
                worker_id,
                now,
                claim_generation,
                claim_generation,
                claim_token,
                claim_token,
            ),
        ).rowcount
        self.conn.commit()
        return JobQueueResult(job_id=job_id, status="running", applied=bool(updated))

    def finish(
        self,
        job_id: str,
        worker_id: str,
        result_refs: dict[str, Any] | None = None,
        *,
        claim_generation: int | None = None,
        claim_token: str | None = None,
        now: str | None = None,
    ) -> JobQueueResult:
        return self._finish(
            job_id,
            "succeeded",
            worker_id=worker_id,
            result_refs=result_refs or {},
            claim_generation=claim_generation,
            claim_token=claim_token,
            now=now,
        )

    def retry(
        self,
        job_id: str,
        worker_id: str,
        reason: str,
        retry_after: str,
        *,
        claim_generation: int | None = None,
        claim_token: str | None = None,
        now: str | None = None,
    ) -> JobQueueResult:
        now = now or db.now_iso()
        updated = self.conn.execute(
            """
            update background_jobs
            set status = 'retry',
                last_error = ?,
                retry_after = ?,
                available_at = ?,
                updated_at = ?
            where id = ?
              and lease_owner = ?
              and status in ('claimed','running')
              and (lease_expires_at is null or lease_expires_at > ?)
              and (? is null or claim_generation = ?)
              and (? is null or claim_token = ?)
            """,
            (
                reason[:800],
                retry_after,
                retry_after,
                now,
                job_id,
                worker_id,
                now,
                claim_generation,
                claim_generation,
                claim_token,
                claim_token,
            ),
        ).rowcount
        self.conn.commit()
        return JobQueueResult(job_id=job_id, status="retry", applied=bool(updated))

    def wait(self, job_id: str, worker_id: str, dependency_reason: str, *, claim_generation: int | None = None, claim_token: str | None = None, now: str | None = None, commit: bool = True) -> JobQueueResult:
        return self._finish(job_id, "waiting", worker_id=worker_id, blocked_reason=dependency_reason, claim_generation=claim_generation, claim_token=claim_token, now=now, commit=commit)

    def block(self, job_id: str, worker_id: str, reason: str, *, claim_generation: int | None = None, claim_token: str | None = None, now: str | None = None, commit: bool = True) -> JobQueueResult:
        return self._finish(job_id, "blocked", worker_id=worker_id, blocked_reason=reason, claim_generation=claim_generation, claim_token=claim_token, now=now, commit=commit)

    def dead_letter(self, job_id: str, worker_id: str, reason: str, *, claim_generation: int | None = None, claim_token: str | None = None, now: str | None = None, commit: bool = True) -> JobQueueResult:
        return self._finish(job_id, "dead_letter", worker_id=worker_id, blocked_reason=reason, claim_generation=claim_generation, claim_token=claim_token, now=now, commit=commit)

    def fence_business_commit(
        self,
        job_id: str,
        worker_id: str,
        *,
        claim_generation: int,
        claim_token: str,
        lease_seconds: int = 180,
        now: str | None = None,
    ) -> JobQueueResult:
        now = now or db.now_iso()
        updated = self.conn.execute(
            """
            update background_jobs
            set updated_at = ?, lease_expires_at = ?
            where id = ?
              and lease_owner = ?
              and claim_generation = ?
              and claim_token = ?
              and status = 'running'
              and lease_expires_at is not null
              and lease_expires_at > ?
            """,
            (
                now,
                _add_seconds(now, lease_seconds),
                job_id,
                worker_id,
                int(claim_generation),
                claim_token,
                now,
            ),
        ).rowcount
        return JobQueueResult(job_id=job_id, status="running", applied=bool(updated))

    def recover(self, now: str) -> dict[str, int]:
        expired = self.conn.execute(
            """
            update background_jobs
            set status = 'retry',
                last_error = case when last_error = '' then 'lease expired' else last_error end,
                updated_at = ?
            where status in ('claimed','running')
              and lease_expires_at is not null
              and lease_expires_at <= ?
            """,
            (now, now),
        ).rowcount
        due = self.conn.execute(
            """
            update background_jobs
            set status = 'queued',
                updated_at = ?
            where status = 'retry'
              and (retry_after is null or retry_after <= ?)
            """,
            (now, now),
        ).rowcount
        self.conn.commit()
        return {"expired_leases_retried": expired, "due_retries_requeued": due, "missing_attempt_jobs_created": 0}

    def find_by_idempotency_key(self, idempotency_key: str, *, include_terminal: bool = False) -> dict[str, Any] | None:
        statuses = tuple(V5_ACTIVE_STATUSES | (V5_TERMINAL_STATUSES if include_terminal else set()))
        placeholders = ",".join("?" for _ in statuses)
        row = self.conn.execute(
            f"""
            select *
            from background_jobs
            where idempotency_key = ?
              and status in ({placeholders})
            order by created_at desc, id desc
            limit 1
            """,
            (idempotency_key, *statuses),
        ).fetchone()
        return dict(row) if row else None

    def terminal_stage_for_key(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self.find_by_idempotency_key(idempotency_key, include_terminal=True)
        if row and row.get("status") in V5_TERMINAL_STATUSES:
            return row
        return None

    @staticmethod
    def v5_retry_after_seconds(run_count: int) -> int:
        completed_attempts = max(1, int(run_count or 1))
        index = max(0, min(completed_attempts - 1, len(V5_RETRY_BACKOFF_SECONDS) - 1))
        return V5_RETRY_BACKOFF_SECONDS[index]

    @staticmethod
    def v5_max_attempts(job_type: str) -> int:
        return 3 if job_type in V5_MODEL_JOB_TYPES else 1

    def _transition_for_owner(
        self,
        job_id: str,
        worker_id: str,
        from_status: str,
        to_status: str,
        *,
        started: bool = False,
        claim_generation: int | None = None,
        claim_token: str | None = None,
        now: str | None = None,
    ) -> JobQueueResult:
        now = now or db.now_iso()
        started_clause = ", started_at = coalesce(started_at, ?)" if started else ""
        run_count_clause = ", run_count = run_count + 1" if started else ""
        params: tuple[Any, ...]
        if started:
            params = (to_status, now, now, job_id, worker_id, from_status, now, claim_generation, claim_generation, claim_token, claim_token)
        else:
            params = (to_status, now, job_id, worker_id, from_status, now, claim_generation, claim_generation, claim_token, claim_token)
        updated = self.conn.execute(
            f"""
            update background_jobs
            set status = ?,
                updated_at = ?
                {started_clause}
                {run_count_clause}
            where id = ?
              and lease_owner = ?
              and status = ?
              and (lease_expires_at is null or lease_expires_at > ?)
              and (? is null or claim_generation = ?)
              and (? is null or claim_token = ?)
            """,
            params,
        ).rowcount
        self.conn.commit()
        return JobQueueResult(job_id=job_id, status=to_status, applied=bool(updated))

    def _finish(
        self,
        job_id: str,
        status: str,
        *,
        worker_id: str,
        result_refs: dict[str, Any] | None = None,
        blocked_reason: str = "",
        claim_generation: int | None = None,
        claim_token: str | None = None,
        now: str | None = None,
        commit: bool = True,
    ) -> JobQueueResult:
        now = now or db.now_iso()
        updated = self.conn.execute(
            """
            update background_jobs
            set status = ?,
                updated_at = ?,
                finished_at = case when ? in ('succeeded','blocked','dead_letter') then ? else finished_at end,
                result_refs_json = ?,
                blocked_reason = ?,
                dead_letter_reason = case when ? = 'dead_letter' then ? else dead_letter_reason end
            where id = ?
              and lease_owner = ?
              and status in ('claimed','running')
              and (lease_expires_at is null or lease_expires_at > ?)
              and (? is null or claim_generation = ?)
              and (? is null or claim_token = ?)
            """,
            (
                status,
                now,
                status,
                now,
                db.json_dump(result_refs or {}),
                blocked_reason[:800],
                status,
                blocked_reason[:800],
                job_id,
                worker_id,
                now,
                claim_generation,
                claim_generation,
                claim_token,
                claim_token,
            ),
        ).rowcount
        if commit:
            self.conn.commit()
        return JobQueueResult(job_id=job_id, status=status, applied=bool(updated))


def _add_seconds(value: str, seconds: int) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.fromisoformat(db.now_iso())
    return (parsed + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


def _is_v5_idempotency_key(value: str) -> bool:
    return str(value).startswith("v5:")


def _default_payload_schema_version(job_type: str, idempotency_key: str) -> str:
    if job_type in V5_JOB_TYPES or _is_v5_idempotency_key(idempotency_key):
        return V5_JOB_PAYLOAD_SCHEMA_VERSION
    return V3_JOB_PAYLOAD_SCHEMA_VERSION
