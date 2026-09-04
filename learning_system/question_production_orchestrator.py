"""Stable orchestration for the Node -> QF -> Slot -> Brief -> Candidate flow.

Skills only generate and validate payloads. This module owns ordering, persistence,
fan-out, idempotency, and explicit retry semantics.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from datetime import timedelta
from typing import Any, Protocol

from .question_production_persistence import Persistence, default_persistences
from .question_production_promotion import promote_run
from .question_production_audit import record_event
from .question_production_skills import Generator, ValidationResult, build_live_question_production_skills, build_question_production_skills


STAGES = ("qf_design", "slot_design", "brief_generation", "candidate_generation")
ARTIFACT_TYPES = {
    "qf_design": "qf",
    "slot_design": "slot",
    "brief_generation": "brief",
    "candidate_generation": "candidate",
}
STAGE_INPUTS = {
    "qf_design": (),
    "slot_design": ("qf",),
    "brief_generation": ("slot",),
    "candidate_generation": ("brief",),
}


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _unique_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for error in errors:
        key = (str(error.get("code") or "validation_failed"), str(error.get("message") or ""))
        if key not in seen:
            seen.add(key)
            unique.append(error)
    return unique


class Skill(Protocol):
    """One production skill; it must not invoke another skill or write storage."""

    def run(self, payload: dict[str, Any]) -> list[dict[str, Any]]: ...

    def validate(self, payload: dict[str, Any], output: dict[str, Any]) -> ValidationResult | list[str]: ...

    def review(self, payload: dict[str, Any], output: list[dict[str, Any]]) -> dict[str, Any]: ...

    def validate_review(self, payload: dict[str, Any], output: list[dict[str, Any]], review: dict[str, Any]) -> ValidationResult: ...


class ProductionOrchestrator:
    _run_lock = RLock()

    def __init__(self, conn: sqlite3.Connection, *, skills: dict[str, Skill], persistences: dict[str, Persistence] | None = None, require_semantic_review: bool = True, max_workers: int = 4, max_attempts: int = 3, lease_seconds: int = 300):
        unknown = set(skills) - set(STAGES)
        missing = set(STAGES) - set(skills)
        if unknown or missing:
            raise ValueError(f"skills must exactly cover stages; missing={sorted(missing)}, unknown={sorted(unknown)}")
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self.conn = conn
        self.skills = skills
        self.persistences = persistences or default_persistences()
        if set(self.persistences) != set(STAGES):
            raise ValueError("persistences must exactly cover production stages")
        self.require_semantic_review = require_semantic_review
        self.max_workers = max_workers
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.owner = f"worker-{uuid.uuid4().hex[:12]}"

    def run(self, node_id: str, node: dict[str, Any]) -> dict[str, Any]:
        if node.get("node_id") != node_id:
            raise ValueError("node_id must match node payload")
        input_digest = _digest(node)
        run, created = self._get_or_create_run(node_id, node, input_digest)
        if run["status"] == "completed":
            return self.get_run(run["id"])
        if run["status"] == "failed":
            raise ValueError("run has failed; use explicit retry")
        if run["status"] == "paused":
            raise ValueError("run is paused; use resume explicitly")
        if not created:
            raise ValueError("run is already running; use explicit recovery after its lease expires")
        try:
            self._run_stage_range(run["id"], 0, len(STAGES))
            self._set_run_status(run["id"], "completed", "", generation=run["run_generation"])
        except Exception as exc:
            self._set_run_status(run["id"], "failed", str(exc), generation=run["run_generation"])
        return self.get_run(run["id"])

    def rerun(
        self,
        node_id: str,
        node: dict[str, Any],
        *,
        source_run_id: str,
    ) -> dict[str, Any]:
        """Start a fresh full run while preserving the source run unchanged."""
        if node.get("node_id") != node_id:
            raise ValueError("node_id must match node payload")
        source = self._run_row(source_run_id)
        if source["node_id"] != node_id:
            raise ValueError("source run belongs to a different node")
        rerun_node = {
            "node_id": node_id,
            "node": deepcopy(node),
            "rerun_context": {
                "source_run_id": source_run_id,
                "rerun_id": uuid.uuid4().hex[:12],
            },
        }
        run, created = self._get_or_create_run(
            node_id,
            rerun_node,
            _digest(rerun_node),
        )
        if not created:
            raise ValueError("rerun could not create a new production run")
        try:
            self._run_stage_range(run["id"], 0, len(STAGES))
            self._set_run_status(run["id"], "completed", "", generation=run["run_generation"])
        except Exception as exc:
            self._set_run_status(run["id"], "failed", str(exc), generation=run["run_generation"])
        return self.get_run(run["id"])

    def run_until(self, node_id: str, node: dict[str, Any], until_stage: str) -> dict[str, Any]:
        """Run through one named stage and persist a resumable checkpoint."""
        if until_stage not in STAGES:
            raise ValueError(f"unknown production stage: {until_stage}")
        if node.get("node_id") != node_id:
            raise ValueError("node_id must match node payload")
        run, created = self._get_or_create_run(node_id, node, _digest(node))
        if not created:
            if run["status"] == "completed":
                return self.get_run(run["id"])
            raise ValueError("run already exists; use resume, retry, or recover explicitly")
        try:
            self._run_stage_range(run["id"], 0, STAGES.index(until_stage) + 1)
            self._set_run_status(run["id"], "paused", f"paused after {until_stage}", generation=run["run_generation"])
        except Exception as exc:
            self._set_run_status(run["id"], "failed", str(exc), generation=run["run_generation"])
        return self.get_run(run["id"])

    def revise_structure(
        self,
        node_id: str,
        node: dict[str, Any],
        *,
        source_run_id: str,
        feedback: list[dict[str, Any] | str],
    ) -> dict[str, Any]:
        """Create a new QF/Slot revision run without entering Brief or Candidate."""
        if node.get("node_id") != node_id:
            raise ValueError("node_id must match node payload")
        if not str(source_run_id or "").strip():
            raise ValueError("source_run_id is required for structure revision")
        if not isinstance(feedback, list) or not feedback:
            raise ValueError("structure revision requires non-empty feedback")
        revision_context = {
            "source_run_id": source_run_id,
            "feedback": deepcopy(feedback),
        }
        revision_node = {
            "node_id": node_id,
            "node": deepcopy(node),
            "revision_context": revision_context,
        }
        existing_revision = self.conn.execute(
            "select status from production_runs where node_id=? and input_digest_sha256=?",
            (node_id, _digest(revision_node)),
        ).fetchone()
        if existing_revision and existing_revision["status"] == "failed":
            revision_node["revision_context"] = {
                **revision_context,
                "revision_attempt": uuid.uuid4().hex[:12],
            }
        run, created = self._get_or_create_run(node_id, revision_node, _digest(revision_node))
        if not created:
            return self.get_run(run["id"])
        try:
            self._run_stage_range(run["id"], 0, 2)
            self._set_run_status(run["id"], "paused", "paused after structure revision", generation=run["run_generation"])
        except Exception as exc:
            self._set_run_status(run["id"], "failed", str(exc), generation=run["run_generation"])
        return self.get_run(run["id"])

    def resume(self, run_id: str, until_stage: str | None = None) -> dict[str, Any]:
        """Resume a paused checkpoint without re-running completed stages."""
        if until_stage is not None and until_stage not in STAGES:
            raise ValueError(f"unknown production stage: {until_stage}")
        run = self._claim_run(run_id, expected_status="paused")
        try:
            completed = {row["stage_name"] for row in self.conn.execute("select stage_name from production_stages where run_id=? and status='completed'", (run_id,)).fetchall()}
            start = next((index for index, stage in enumerate(STAGES) if stage not in completed), len(STAGES))
            end = STAGES.index(until_stage) + 1 if until_stage is not None else len(STAGES)
            self._run_stage_range(run_id, start, end)
            if end < len(STAGES):
                self._set_run_status(run_id, "paused", f"paused after {STAGES[end - 1]}", generation=run["run_generation"])
            else:
                self._set_run_status(run_id, "completed", "", generation=run["run_generation"])
        except Exception as exc:
            self._set_run_status(run_id, "failed", str(exc), generation=run["run_generation"])
        return self.get_run(run_id)

    def retry(self, run_id: str) -> dict[str, Any]:
        run = self._claim_run(run_id, expected_status="failed")
        failed = self.conn.execute(
            "select stage_name from production_stages where run_id=? and status in ('rejected','blocked') order by updated_at desc limit 1",
            (run_id,),
        ).fetchone()
        if not failed:
            raise ValueError("failed run has no failed stage")
        try:
            start = STAGES.index(failed["stage_name"])
            failed_keys = {
                row["logical_key"]
                for row in self.conn.execute(
                    "select logical_key from production_stages where run_id=? and stage_name=? and status in ('rejected','blocked')",
                    (run_id, failed["stage_name"]),
                ).fetchall()
            }
            self._invalidate_descendants(run_id, failed["stage_name"], failed_keys)
            self.conn.commit()
            self._run_stage_range(
                run_id,
                start,
                len(STAGES),
                force_retry_keys=failed_keys,
            )
            incomplete = self.conn.execute(
                "select count(*) from production_stages where run_id=? and status <> 'completed'",
                (run_id,),
            ).fetchone()[0]
            if incomplete:
                raise ValueError("retry completed with incomplete production stages")
            self._set_run_status(run_id, "completed", "", generation=run["run_generation"])
        except Exception as exc:
            self._set_run_status(run_id, "failed", str(exc), generation=run["run_generation"])
        return self.get_run(run_id)

    def recover(self, run_id: str) -> dict[str, Any]:
        """Explicitly reclaim an expired running run after a crashed worker."""
        run = self._claim_run(run_id, expected_status="running", require_expired=True)
        try:
            rows = self.conn.execute(
                "select stage_name,logical_key from production_stages where run_id=? and status='running' order by updated_at, id",
                (run_id,),
            ).fetchall()
            if rows:
                first_stage = min(STAGES.index(row["stage_name"]) for row in rows)
                running_keys = {row["logical_key"] for row in rows if row["stage_name"] == STAGES[first_stage]}
            else:
                completed = {row["stage_name"] for row in self.conn.execute("select stage_name from production_stages where run_id=? and status='completed'", (run_id,)).fetchall()}
                if len(completed) == len(STAGES):
                    self._set_run_status(run_id, "completed", "", generation=run["run_generation"])
                    return self.get_run(run_id)
                first_stage = next(index for index, name in enumerate(STAGES) if name not in completed)
                running_keys = set()
            self._invalidate_descendants(run_id, STAGES[first_stage], running_keys)
            self.conn.commit()
            self._run_stage_range(
                run_id,
                first_stage,
                len(STAGES),
                force_retry_keys=running_keys,
            )
            self._set_run_status(run_id, "completed", "", generation=run["run_generation"])
        except Exception as exc:
            self._set_run_status(run_id, "failed", str(exc), generation=run["run_generation"])
        return self.get_run(run_id)

    def requeue_invalid_candidates(self, run_id: str) -> dict[str, Any]:
        """Revalidate stored candidates and regenerate only newly invalid ones."""
        current = self._run_row(run_id)
        if current["status"] not in {"completed", "paused", "failed"}:
            raise ValueError("candidate revalidation requires a completed, paused, or failed run")
        run = self._claim_run(run_id, expected_status=current["status"])
        invalid_keys: set[str] = set()
        try:
            rows = self.conn.execute(
                "select * from production_stages where run_id=? and stage_name='candidate_generation' and status in ('completed','rejected','blocked') order by logical_key",
                (run_id,),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["input_json"] or "{}")
                latest_artifact = self.conn.execute(
                    "select payload_json from production_artifacts where run_id=? and stage_id=? and artifact_type='candidate' order by artifact_attempt desc limit 1",
                    (run_id, row["id"]),
                ).fetchone()
                if not latest_artifact and row["status"] in {"rejected", "blocked"}:
                    errors = [{
                        "code": "candidate_revalidation_required",
                        "message": str(row["error_reason"] or "candidate requires revalidation"),
                        "severity": "error",
                    }]
                    key = row["logical_key"]
                    invalid_keys.add(key)
                    self.conn.execute(
                        "update production_stages set status='rejected',attempt_count=0,max_attempts=max(max_attempts,3),output_json='[]',output_digest_sha256='',validation_errors_json=?,validation_result_json=?,error_reason=?,lease_owner=?,lease_expires_at=?,run_generation=?,updated_at=? where id=?",
                        (
                            json.dumps(errors, ensure_ascii=False),
                            json.dumps({"status": "rejected", "errors": errors, "reason": "revalidated against current candidate schema"}, ensure_ascii=False),
                            "candidate revalidation required",
                            self.owner,
                            self._lease_deadline(),
                            run["run_generation"],
                            _now(),
                            row["id"],
                        ),
                    )
                    record_event(
                        self.conn,
                        run_id=run_id,
                        stage_id=row["id"],
                        stage_name="candidate_generation",
                        logical_key=key,
                        step_name="schema_validator",
                        event_type="schema_validator",
                        attempt=int(row["attempt_count"]),
                        status="rejected",
                        input_value=json.loads(row["input_json"] or "{}"),
                        output_value={"status": "rejected", "errors": errors},
                        errors=errors,
                        completed_at=_now(),
                    )
                    record_event(
                        self.conn,
                        run_id=run_id,
                        stage_id=row["id"],
                        stage_name="candidate_generation",
                        logical_key=key,
                        step_name="persistence",
                        event_type="persistence",
                        attempt=int(row["attempt_count"]),
                        status="skipped",
                        input_value={},
                        output_value={"status": "skipped", "reason": "candidate_revalidation_required"},
                        errors=errors,
                        completed_at=_now(),
                    )
                    continue
                output = [json.loads(latest_artifact["payload_json"])] if latest_artifact else None
                if not output:
                    continue
                errors: list[dict[str, Any]] = []
                for item in output:
                    validation = self.skills["candidate_generation"].validate(deepcopy(payload), deepcopy(item))
                    if isinstance(validation, ValidationResult) and validation.status != "passed":
                        errors.extend(validation.errors)
                    elif not isinstance(validation, ValidationResult):
                        errors.extend({"code": str(error), "message": str(error), "severity": "error"} for error in validation)
                if not errors:
                    continue
                key = row["logical_key"]
                invalid_keys.add(key)
                historical_attempt = int(self.conn.execute(
                    "select coalesce(max(artifact_attempt),0) from production_artifacts where stage_id=? and artifact_type='candidate'",
                    (row["id"],),
                ).fetchone()[0])
                self.conn.execute(
                    "update production_stages set status='rejected',attempt_count=?,max_attempts=max(max_attempts,?),output_json='[]',output_digest_sha256='',validation_errors_json=?,validation_result_json=?,error_reason=?,lease_owner=?,lease_expires_at=?,run_generation=?,updated_at=? where id=?",
                    (
                        historical_attempt,
                        historical_attempt + 2,
                        json.dumps(_unique_errors(errors), ensure_ascii=False),
                        json.dumps({"status": "rejected", "errors": _unique_errors(errors), "reason": "revalidated against current candidate schema"}, ensure_ascii=False),
                        "candidate revalidation failed",
                        self.owner,
                        self._lease_deadline(),
                        run["run_generation"],
                        _now(),
                        row["id"],
                    ),
                )
                record_event(
                    self.conn,
                    run_id=run_id,
                    stage_id=row["id"],
                    stage_name="candidate_generation",
                    logical_key=key,
                    step_name="schema_validator",
                    event_type="schema_validator",
                    attempt=int(row["attempt_count"]),
                    status="rejected",
                    input_value={"payload": payload, "items": output},
                    output_value={"status": "rejected", "errors": _unique_errors(errors)},
                    errors=_unique_errors(errors),
                    completed_at=_now(),
                )
                record_event(
                    self.conn,
                    run_id=run_id,
                    stage_id=row["id"],
                    stage_name="candidate_generation",
                    logical_key=key,
                    step_name="persistence",
                    event_type="persistence",
                    attempt=int(row["attempt_count"]),
                    status="skipped",
                    input_value={},
                    output_value={"status": "skipped", "reason": "candidate_revalidation_failed"},
                    errors=_unique_errors(errors),
                    completed_at=_now(),
                )
            self.conn.commit()
            if invalid_keys:
                self._execute_stage(run_id, "candidate_generation", force_retry_keys=invalid_keys)
            self._set_run_status(run_id, "completed", "", generation=run["run_generation"])
        except Exception as exc:
            self._set_run_status(run_id, "failed", str(exc), generation=run["run_generation"])
        return self.get_run(run_id)

    def promote(
        self,
        run_id: str,
        *,
        question_bank_version: str,
        graph_version: str,
        manifest_id: str | None = None,
    ) -> dict[str, Any]:
        """Explicitly stage reviewed candidates in the formal question bank."""
        return promote_run(
            self.conn,
            run_id=run_id,
            question_bank_version=question_bank_version,
            graph_version=graph_version,
            manifest_id=manifest_id,
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = dict(self._run_row(run_id))
        run["run_id"] = run["id"]
        run["node"] = json.loads(run.pop("input_json"))
        run["stages"] = []
        rows = self.conn.execute(
            "select * from production_stages where run_id=? order by case stage_name when 'qf_design' then 1 when 'slot_design' then 2 when 'brief_generation' then 3 else 4 end, logical_key",
            (run_id,),
        ).fetchall()
        for row in rows:
            stage = dict(row)
            stage["input"] = json.loads(stage.pop("input_json"))
            stage["output"] = json.loads(stage.pop("output_json"))
            stage["validation_errors"] = json.loads(stage.pop("validation_errors_json"))
            stage["validation_result"] = json.loads(stage.pop("validation_result_json"))
            stage["dependency_ids"] = json.loads(stage.pop("dependency_ids_json"))
            stage["audit_events"] = [
                dict(event)
                for event in self.conn.execute(
                    "select * from production_audit_events where stage_id=? order by created_at, id",
                    (row["id"],),
                ).fetchall()
            ]
            for event in stage["audit_events"]:
                event["input"] = json.loads(event.pop("input_json"))
                event["output"] = json.loads(event.pop("output_json"))
                event["errors"] = json.loads(event.pop("error_json"))
            stage["artifacts"] = [
                dict(artifact)
                for artifact in self.conn.execute(
                    "select id,artifact_type,logical_key,parent_artifact_ids_json,payload_json,input_digest_sha256,output_digest_sha256,artifact_attempt from production_artifacts where stage_id=? order by logical_key,artifact_attempt",
                    (row["id"],),
                ).fetchall()
            ]
            for artifact in stage["artifacts"]:
                artifact["parent_artifact_ids"] = json.loads(artifact.pop("parent_artifact_ids_json"))
                artifact["payload"] = json.loads(artifact.pop("payload_json"))
            run["stages"].append(stage)
        return run

    def _source_structure_snapshot(self, run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read completed source structure without mutating the source Run."""
        qfs: list[dict[str, Any]] = []
        slots: list[dict[str, Any]] = []
        for row in self.conn.execute(
            "select stage_name,output_json from production_stages where run_id=? and status='completed' and stage_name in ('qf_design','slot_design') order by id",
            (run_id,),
        ).fetchall():
            values = json.loads(row["output_json"] or "[]")
            if row["stage_name"] == "qf_design":
                qfs.extend(value for value in values if isinstance(value, dict))
            else:
                slots.extend(value for value in values if isinstance(value, dict))
        return qfs, slots

    def _get_or_create_run(self, node_id: str, node: dict[str, Any], input_digest: str) -> tuple[sqlite3.Row, bool]:
        with self._run_lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self.conn.execute(
                    "select * from production_runs where node_id=? and input_digest_sha256=?",
                    (node_id, input_digest),
                ).fetchone()
                if existing:
                    self.conn.commit()
                    return existing, False
                run_id = f"PR-{uuid.uuid4().hex[:12]}"
                now = _now()
                self.conn.execute(
                    "insert into production_runs(id,node_id,input_json,input_digest_sha256,status,error_reason,lease_owner,lease_expires_at,run_generation,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, node_id, json.dumps(node, ensure_ascii=False, sort_keys=True), input_digest, "running", "", self.owner, self._lease_deadline(), 1, now, now),
                )
                self.conn.commit()
                return self._run_row(run_id), True
            except Exception:
                self.conn.rollback()
                raise

    def _run_row(self, run_id: str) -> sqlite3.Row:
        row = self.conn.execute("select * from production_runs where id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"unknown production run: {run_id}")
        return row

    def _set_run_status(self, run_id: str, status: str, error: str, *, generation: int) -> None:
        if status == "completed":
            incomplete = self.conn.execute(
                "select count(*) from production_stages where run_id=? and status <> 'completed'",
                (run_id,),
            ).fetchone()[0]
            if incomplete:
                raise ValueError("cannot complete run with incomplete production stages")
        cursor = self.conn.execute(
            "update production_runs set status=?, error_reason=?, lease_owner='', lease_expires_at=null, updated_at=? where id=? and lease_owner=? and run_generation=?",
            (status, error[:1000], _now(), run_id, self.owner, generation),
        )
        if cursor.rowcount != 1:
            raise ValueError("production run ownership lost")
        self.conn.commit()

    def _assert_ownership(self, run: sqlite3.Row) -> None:
        if run["lease_owner"] != self.owner or int(run["run_generation"] or 1) < 1 or self._lease_expired(run["lease_expires_at"]):
            raise _OwnershipLost("production run ownership lost or lease expired")

    def _claim_run(self, run_id: str, *, expected_status: str, require_expired: bool = False) -> sqlite3.Row:
        with self._run_lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                run = self._run_row(run_id)
                if run["status"] != expected_status:
                    raise ValueError(f"only {expected_status} runs can be claimed")
                if require_expired and not self._lease_expired(run["lease_expires_at"]):
                    raise ValueError("run lease has not expired")
                generation = int(run["run_generation"] or 1) + 1
                self.conn.execute(
                    "update production_runs set status='running',lease_owner=?,lease_expires_at=?,run_generation=?,error_reason='',updated_at=? where id=? and status=?",
                    (self.owner, self._lease_deadline(), generation, _now(), run_id, expected_status),
                )
                self.conn.commit()
                return self._run_row(run_id)
            except Exception:
                self.conn.rollback()
                raise

    def _lease_deadline(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)).isoformat(timespec="microseconds")

    @staticmethod
    def _lease_expired(value: str | None) -> bool:
        if not value:
            return True
        return datetime.fromisoformat(value) <= datetime.now(timezone.utc)

    def _run_stage_range(
        self,
        run_id: str,
        start: int,
        end: int,
        *,
        force_retry_keys: set[str] | None = None,
    ) -> None:
        for index in range(start, end):
            self._execute_stage(
                run_id,
                STAGES[index],
                force_retry_keys=force_retry_keys if index == start else None,
            )

    def _execute_stage(
        self,
        run_id: str,
        stage: str,
        *,
        force_retry_keys: set[str] | None = None,
    ) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown production stage: {stage}")
        inputs = self._stage_inputs(run_id, stage)
        if not inputs:
            raise ValueError(f"stage {stage} has no runnable inputs")
        keys = [self._input_key(stage, payload) for payload in inputs]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{stage} input contains duplicate logical keys")
        prepared = []
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for payload in inputs:
                context = self._prepare_one(run_id, stage, payload, force_retry=str(payload.get("key") or "") in (force_retry_keys or set()))
                if context is not None:
                    prepared.append(context)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        while prepared:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(prepared))) as executor:
                future_map = {
                    executor.submit(self._run_and_validate, stage, context["payload"]): index
                    for index, context in enumerate(prepared)
                }
                results = self._collect_results_with_lease_renewal(
                    run_id,
                    stage,
                    prepared,
                    future_map,
                )
            first_error = None
            retry_keys: set[str] = set()
            for context, result in zip(prepared, results):
                try:
                    retryable = self._can_retry_current_stage(stage, context, result, force_retry_keys)
                    self._finish_one(run_id, stage, context, result, allow_retry=retryable)
                    if retryable:
                        retry_keys.add(str(context["payload"].get("key") or ""))
                except Exception as exc:
                    first_error = first_error or exc
            if first_error:
                raise first_error
            if not retry_keys:
                return
            retry_inputs = {
                self._input_key(stage, payload): payload
                for payload in self._stage_inputs(run_id, stage)
            }
            prepared = []
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                for key in sorted(retry_keys):
                    payload = retry_inputs.get(key)
                    if payload is None:
                        raise ValueError(f"missing retry input for {stage}/{key}")
                    context = self._prepare_one(run_id, stage, payload, force_retry=True)
                    if context is not None:
                        prepared.append(context)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _can_retry_current_stage(
        self,
        stage: str,
        context: dict[str, Any],
        result: dict[str, Any],
        force_retry_keys: set[str] | None,
    ) -> bool:
        if result["status"] not in {"rejected", "blocked"} or context["attempt"] >= context["max_attempts"]:
            return False
        if not self.require_semantic_review and str(context["payload"].get("key") or "") not in (force_retry_keys or set()):
            return False
        validation = result.get("validation_result")
        review = validation.get("semantic_review") if isinstance(validation, dict) else None
        if not isinstance(review, dict):
            return True
        return (
            review.get("recovery_action") == "retry_current_stage"
            and review.get("recovery_stage") == stage
        )

    def _collect_results_with_lease_renewal(
        self,
        run_id: str,
        stage: str,
        contexts: list[dict[str, Any]],
        future_map: dict[Any, int],
    ) -> list[dict[str, Any]]:
        """Wait for model work while renewing leases from the DB-owning thread."""
        results: list[dict[str, Any] | None] = [None] * len(contexts)
        pending = set(future_map)
        interval = max(0.05, min(float(self.lease_seconds) / 3.0, 5.0))
        while pending:
            done, pending = wait(pending, timeout=interval, return_when=FIRST_COMPLETED)
            for future in done:
                results[future_map[future]] = future.result()
            if pending:
                self._renew_leases(run_id, stage, contexts)
        self._renew_leases(run_id, stage, contexts)
        return [result for result in results if result is not None]

    def _renew_leases(self, run_id: str, stage: str, contexts: list[dict[str, Any]]) -> None:
        if not contexts:
            return
        generation = contexts[0]["generation"]
        now = _now()
        deadline = self._lease_deadline()
        cursor = self.conn.execute(
            "update production_runs set lease_expires_at=?,updated_at=? where id=? and lease_owner=? and run_generation=? and status='running' and lease_expires_at > ?",
            (deadline, now, run_id, self.owner, generation, now),
        )
        if cursor.rowcount != 1:
            raise _OwnershipLost("production run ownership lost or lease expired")
        stage_ids = [context["stage_id"] for context in contexts]
        marks = ",".join("?" for _ in stage_ids)
        cursor = self.conn.execute(
            f"update production_stages set lease_expires_at=?,updated_at=? where id in ({marks}) and lease_owner=? and run_generation=? and status='running' and lease_expires_at > ?",
            [deadline, now, *stage_ids, self.owner, generation, now],
        )
        if cursor.rowcount != len(stage_ids):
            raise _OwnershipLost(f"{stage} stage ownership lost or lease expired")
        self.conn.commit()

    def _invalidate_descendants(self, run_id: str, stage: str, logical_keys: set[str]) -> None:
        """Remove stale downstream projections before an explicit retry/recovery."""
        stage_index = STAGES.index(stage)
        invalidated_artifacts: set[str] = set()
        rows = self.conn.execute(
            "select id,logical_key from production_stages where run_id=? and stage_name=?",
            (run_id, stage),
        ).fetchall()
        for row in rows:
            if row["logical_key"] not in logical_keys:
                continue
            artifact_rows = self.conn.execute("select id from production_artifacts where stage_id=?", (row["id"],)).fetchall()
            invalidated_artifacts.update(item["id"] for item in artifact_rows)
        for downstream in STAGES[stage_index + 1:]:
            affected_rows = []
            for row in self.conn.execute(
                "select id,dependency_ids_json from production_stages where run_id=? and stage_name=?",
                (run_id, downstream),
            ).fetchall():
                dependencies = set(json.loads(row["dependency_ids_json"] or "[]"))
                if dependencies & invalidated_artifacts:
                    affected_rows.append(row)
            next_invalidated: set[str] = set()
            for row in affected_rows:
                artifacts = self.conn.execute("select id from production_artifacts where stage_id=?", (row["id"],)).fetchall()
                next_invalidated.update(item["id"] for item in artifacts)
                self.conn.execute(
                    "update production_stages set status='pending',lease_owner='',lease_expires_at=null,output_json='[]',output_digest_sha256='',validation_errors_json='[]',validation_result_json='{}',updated_at=? where id=?",
                    (_now(), row["id"]),
                )
            invalidated_artifacts = next_invalidated

    def _stage_inputs(self, run_id: str, stage: str) -> list[dict[str, Any]]:
        if stage == "qf_design":
            run = self._run_row(run_id)
            payload = {"node_id": run["node_id"], **json.loads(run["input_json"]), "key": run["node_id"]}
            revision_context = payload.get("revision_context")
            if isinstance(revision_context, dict) and revision_context.get("source_run_id"):
                source_qfs, _ = self._source_structure_snapshot(revision_context["source_run_id"])
                payload["previous_qfs"] = source_qfs
            previous = self.conn.execute(
                "select validation_errors_json from production_stages where run_id=? and stage_name=? and logical_key=? and status in ('rejected','blocked')",
                (run_id, stage, run["node_id"]),
            ).fetchone()
            if previous:
                payload["previous_validation_errors"] = json.loads(previous["validation_errors_json"] or "[]")
            return [payload]
        parent_type = STAGE_INPUTS[stage][0]
        parent_stage = STAGES[STAGES.index(stage) - 1]
        parent_rows = self.conn.execute(
            "select id,logical_key,output_json,status,dependency_ids_json from production_stages where run_id=? and stage_name=? and logical_key <> '__blocked__' order by logical_key",
            (run_id, parent_stage),
        ).fetchall()
        if not parent_rows or any(row["status"] != "completed" for row in parent_rows):
            raise ValueError(f"stage {stage} is blocked by {parent_stage}")
        inputs = []
        run = self._run_row(run_id)
        node = json.loads(run["input_json"])
        for row in parent_rows:
            for payload in json.loads(row["output_json"]):
                if not isinstance(payload, dict):
                    raise ValueError(f"{parent_stage} output must contain objects")
                key = self._input_key(stage, payload)
                enriched = {**payload, "key": key, "node": node}
                if isinstance(node.get("revision_context"), dict):
                    revision_context = deepcopy(node["revision_context"])
                    enriched["revision_context"] = revision_context
                    source_run_id = revision_context.get("source_run_id")
                    if source_run_id and stage == "qf_design":
                        source_qfs, _ = self._source_structure_snapshot(source_run_id)
                        enriched["previous_qfs"] = source_qfs
                    elif source_run_id and stage == "slot_design":
                        _, source_slots = self._source_structure_snapshot(source_run_id)
                        enriched["previous_slots"] = [
                            value for value in source_slots
                            if value.get("qf_id") == payload.get("qf_id")
                        ]
                previous = self.conn.execute(
                    "select validation_errors_json from production_stages where run_id=? and stage_name=? and logical_key=? and status in ('rejected','blocked')",
                    (run_id, stage, key),
                ).fetchone()
                if previous:
                    enriched["previous_validation_errors"] = json.loads(previous["validation_errors_json"] or "[]")
                if stage == "slot_design":
                    enriched["qf"] = payload
                elif stage == "brief_generation":
                    enriched["slot"] = payload
                    dependencies = json.loads(row["dependency_ids_json"] or "[]") if "dependency_ids_json" in row.keys() else []
                    qf = self._artifact_payloads(run_id, dependencies, "qf")
                    if qf:
                        enriched["qf"] = qf[0]
                elif stage == "candidate_generation":
                    enriched["brief"] = payload
                inputs.append(enriched)
        return inputs

    def _artifact_payloads(self, run_id: str, artifact_ids: list[str], artifact_type: str) -> list[dict[str, Any]]:
        if not artifact_ids:
            return []
        marks = ",".join("?" for _ in artifact_ids)
        rows = self.conn.execute(
            f"select payload_json from production_artifacts where run_id=? and artifact_type=? and id in ({marks}) order by id",
            [run_id, artifact_type, *artifact_ids],
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def _prepare_one(self, run_id: str, stage: str, payload: dict[str, Any], *, force_retry: bool) -> dict[str, Any] | None:
        key = str(payload.get("key") or "").strip()
        if not key:
            raise ValueError(f"{stage} input requires a logical key")
        input_digest = _digest(payload)
        run = self._run_row(run_id)
        self._assert_ownership(run)
        generation = int(run["run_generation"] or 1)
        existing = self.conn.execute(
            "select * from production_stages where run_id=? and stage_name=? and logical_key=?",
            (run_id, stage, key),
        ).fetchone()
        if existing and existing["status"] == "completed" and not force_retry:
            if existing["input_digest_sha256"] != input_digest:
                raise ValueError(f"immutable stage input changed: {stage}/{key}")
            return None
        stage_id = existing["id"] if existing else f"PS-{uuid.uuid4().hex[:12]}"
        stage_attempt = int(existing["attempt_count"] or 0) + 1 if existing else 1
        historical_artifact = self.conn.execute(
            "select coalesce(max(artifact_attempt), 0) as max_attempt from production_artifacts where stage_id=? and artifact_type=?",
            (stage_id, ARTIFACT_TYPES[stage]),
        ).fetchone()["max_attempt"]
        attempt = max(stage_attempt, int(historical_artifact or 0) + 1)
        max_attempts = int(existing["max_attempts"] or self.max_attempts) if existing else self.max_attempts
        if attempt > max_attempts:
            raise ValueError(f"retry limit reached for {stage}/{key}")
        dependencies = self._dependency_ids(run_id, stage, payload)
        now = _now()
        if existing and existing["status"] in {"rejected", "blocked"} and not force_retry:
            raise ValueError(f"stage {stage}/{key} requires explicit retry")
        if existing:
            self.conn.execute(
                "update production_stages set status='running',attempt_count=?,lease_owner=?,lease_expires_at=?,run_generation=?,input_json=?,input_digest_sha256=?,output_json='[]',output_digest_sha256='',validation_errors_json='[]',validation_result_json='{}',dependency_ids_json=?,error_reason='',updated_at=? where id=?",
                (attempt, self.owner, self._lease_deadline(), generation, json.dumps(payload, ensure_ascii=False, sort_keys=True), input_digest, json.dumps(dependencies), now, stage_id),
            )
        else:
            self.conn.execute(
                "insert into production_stages(id,run_id,stage_name,logical_key,status,attempt_count,max_attempts,lease_owner,lease_expires_at,run_generation,input_json,input_digest_sha256,output_json,output_digest_sha256,validation_errors_json,dependency_ids_json,error_reason,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (stage_id, run_id, stage, key, "running", attempt, self.max_attempts, self.owner, self._lease_deadline(), generation, json.dumps(payload, ensure_ascii=False, sort_keys=True), input_digest, "[]", "", "[]", json.dumps(dependencies), "", now, now),
            )
        return {"stage_id": stage_id, "payload": payload, "input_digest": input_digest, "dependencies": dependencies, "generation": generation, "attempt": attempt, "max_attempts": max_attempts}

    def _run_and_validate(self, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        input_snapshot = deepcopy(payload)
        validation_result: ValidationResult | None = None
        semantic_review: dict[str, Any] | None = None
        audit_events: list[dict[str, Any]] = []
        def audit(event_type: str, status: str, input_value: Any, output_value: Any, errors: list[Any] | None = None) -> None:
            audit_events.append({
                "step_name": event_type,
                "event_type": event_type,
                "status": status,
                "input": deepcopy(input_value),
                "output": deepcopy(output_value),
                "errors": list(errors or []),
            })
        try:
            output = self.skills[stage].run(deepcopy(input_snapshot))
            if not isinstance(output, list) or not output or any(not isinstance(item, dict) for item in output):
                audit("generator", "failed", input_snapshot, output if "output" in locals() else {}, ["skill output must be a non-empty list of objects"])
                raise ValueError("skill output must be a non-empty list of objects")
            audit("generator", "completed", input_snapshot, output)
            errors: list[dict[str, Any]] = []
            for item in output:
                validation = self.skills[stage].validate(deepcopy(input_snapshot), item)
                if isinstance(validation, ValidationResult):
                    if validation.status != "passed":
                        errors.extend(validation.errors)
                        validation_result = validation
                    else:
                        validation_result = validation
                else:
                    errors.extend({"code": str(error), "message": str(error), "severity": "error"} for error in validation)
                    validation_result = None
                errors.extend({"code": code, "message": code, "severity": "error"} for code in self._lineage_errors(stage, input_snapshot, item))
            schema_output = {"status": "rejected" if errors else "passed", "errors": errors, "items": output}
            audit("schema_validator", "rejected" if errors else "completed", {"payload": input_snapshot, "items": output}, schema_output, errors)
            if errors:
                raise _ValidationFailure(_unique_errors(errors), validation_result=validation_result)
            skill = self.skills[stage]
            reviewer = getattr(skill, "review", None)
            configured_marker = getattr(skill, "semantic_reviewer_configured", None)
            reviewer_configured = (
                bool(configured_marker)
                if configured_marker is not None
                else callable(reviewer)
            )
            if self.require_semantic_review and not reviewer_configured:
                validation_result = ValidationResult.rejected(
                    [{"code": "semantic_reviewer_missing", "message": f"{stage} 未配置语义 Reviewer", "severity": "error"}],
                    target_stage=stage,
                    reason="生产流程禁止跳过语义 Reviewer",
                )
                audit("semantic_reviewer", "failed", {**input_snapshot, "stage": stage}, {}, validation_result.errors)
                raise _ValidationFailure(validation_result.errors, validation_result=validation_result)
            if self.require_semantic_review:
                review_payload = {**input_snapshot, "stage": stage}
                try:
                    semantic_review = reviewer(deepcopy(review_payload), deepcopy(output))
                    audit("semantic_reviewer", "completed", {"payload": review_payload, "items": output}, semantic_review)
                except Exception as exc:
                    audit("semantic_reviewer", "failed", {"payload": review_payload, "items": output}, {}, [str(exc)])
                    raise
                review_validation = skill.validate_review(deepcopy(review_payload), deepcopy(output), deepcopy(semantic_review))
                validation_result = review_validation
                audit("reviewer_validator", "completed" if review_validation.status == "passed" else "rejected", {"items": output, "review": semantic_review}, self._validation_result_json(review_validation), review_validation.errors)
                if review_validation.status != "passed":
                    review_errors = list(review_validation.errors)
                    for issue in semantic_review.get("issues", []):
                        review_errors.append({"code": "semantic_review_issue", "message": issue, "severity": "error"})
                    raise _ValidationFailure(_unique_errors(review_errors), validation_result=review_validation, semantic_review=semantic_review)
            else:
                semantic_review = {"status": "skipped", "decision": "not_configured", "score": None, "issues": [], "repair_instructions": []}
                audit("semantic_reviewer", "skipped", {"payload": input_snapshot, "stage": stage}, semantic_review)
                audit("reviewer_validator", "skipped", {"items": output, "review": semantic_review}, {"status": "skipped"})
            return {"status": "completed", "output": output, "output_digest": _digest(output), "errors": [], "validation_result": self._validation_result_json(validation_result, semantic_review=semantic_review), "audit_events": audit_events}
        except Exception as exc:
            errors = exc.errors if isinstance(exc, _ValidationFailure) else [str(exc)]
            if not audit_events or audit_events[-1]["status"] not in {"rejected", "failed"}:
                audit("stage", "rejected" if isinstance(exc, _ValidationFailure) else "failed", input_snapshot, {}, errors)
            return {"status": "rejected" if isinstance(exc, _ValidationFailure) else "blocked", "output": [], "output_digest": "", "errors": errors, "error": str(exc), "validation_result": self._validation_result_json(getattr(exc, "validation_result", None), status="rejected" if isinstance(exc, _ValidationFailure) else "blocked", semantic_review=getattr(exc, "semantic_review", semantic_review)), "audit_events": audit_events}

    @staticmethod
    def _validation_result_json(result: ValidationResult | None, *, status: str = "passed", semantic_review: dict[str, Any] | None = None) -> dict[str, Any]:
        if result is None:
            value = {"status": status, "errors": [], "warnings": [], "retry_allowed": status == "rejected", "target_stage": None, "max_attempts": None, "reason": ""}
            if semantic_review is not None:
                value["semantic_review"] = semantic_review
            return value
        value = {
            "status": result.status,
            "errors": result.errors,
            "warnings": result.warnings,
            "retry_allowed": result.retry_allowed,
            "target_stage": result.target_stage,
            "max_attempts": result.max_attempts,
            "reason": result.reason,
            "validator_version": result.validator_version,
        }
        if semantic_review is not None:
            value["semantic_review"] = semantic_review
        return value

    @staticmethod
    def _lineage_errors(stage: str, payload: dict[str, Any], output: dict[str, Any]) -> list[str]:
        if stage == "qf_design":
            return [] if output.get("node_id") == payload.get("node_id") else ["output_node_id_mismatch"]
        parent_type = STAGE_INPUTS[stage][0]
        field = f"{parent_type}_id"
        return [] if output.get(field) == payload.get(field) else [f"output_{field}_mismatch"]

    def _finish_one(self, run_id: str, stage: str, context: dict[str, Any], result: dict[str, Any], *, allow_retry: bool = False) -> None:
        stage_id = context["stage_id"]
        audit_events = result.get("audit_events") or []

        def write_audit_events() -> None:
            for event in audit_events:
                record_event(
                    self.conn,
                    run_id=run_id,
                    stage_id=stage_id,
                    stage_name=stage,
                    logical_key=str(context["payload"].get("key") or ""),
                    step_name=event["step_name"],
                    event_type=event["event_type"],
                    attempt=context["attempt"],
                    status=event["status"],
                    input_value=event["input"],
                    output_value=event["output"],
                    errors=event.get("errors"),
                    completed_at=_now(),
                )

        if result["status"] in {"rejected", "blocked"}:
            cursor = self.conn.execute(
                "update production_stages set status=?,validation_errors_json=?,validation_result_json=?,error_reason=?,updated_at=? where id=? and lease_owner=? and run_generation=? and lease_expires_at > ?",
                (result["status"], json.dumps(result["errors"], ensure_ascii=False), json.dumps(result["validation_result"], ensure_ascii=False), result.get("error", "")[:1000], _now(), stage_id, self.owner, context["generation"], _now()),
            )
            if cursor.rowcount != 1:
                raise _OwnershipLost("production stage ownership lost")
            write_audit_events()
            record_event(
                self.conn,
                run_id=run_id,
                stage_id=stage_id,
                stage_name=stage,
                logical_key=str(context["payload"].get("key") or ""),
                step_name="persistence",
                event_type="persistence",
                attempt=context["attempt"],
                status="skipped",
                input_value=result.get("output") or {},
                output_value={"status": "skipped", "reason": "upstream_step_failed"},
                errors=result.get("errors"),
                completed_at=_now(),
            )
            self.conn.commit()
            if allow_retry:
                return
            self._block_descendants(run_id, stage)
            raise ValueError(result.get("error", "skill execution failed"))
        output = result["output"]
        output_digest = result["output_digest"]
        try:
            keys = [self._artifact_key(stage, item) for item in output]
            if len(keys) != len(set(keys)):
                raise ValueError(f"{stage} output contains duplicate logical keys")
            cursor = self.conn.execute(
                "update production_stages set status='completed',lease_owner='',lease_expires_at=null,output_json=?,output_digest_sha256=?,validation_result_json=?,updated_at=? where id=? and lease_owner=? and run_generation=? and lease_expires_at > ?",
                (json.dumps(output, ensure_ascii=False, sort_keys=True), output_digest, json.dumps(result["validation_result"], ensure_ascii=False), _now(), stage_id, self.owner, context["generation"], _now()),
            )
            if cursor.rowcount != 1:
                raise _OwnershipLost("production stage ownership lost")
            self.persistences[stage].persist(
                self.conn,
                run_id=run_id,
                stage_id=stage_id,
                output=output,
                parent_artifact_ids=context["dependencies"],
                input_digest=context["input_digest"],
                output_digest=output_digest,
                artifact_attempt=context["attempt"],
            )
            write_audit_events()
            record_event(
                self.conn,
                run_id=run_id,
                stage_id=stage_id,
                stage_name=stage,
                logical_key=str(context["payload"].get("key") or ""),
                step_name="persistence",
                event_type="persistence",
                attempt=context["attempt"],
                status="completed",
                input_value=output,
                output_value={"artifact_type": ARTIFACT_TYPES[stage], "items": output},
                completed_at=_now(),
            )
            self.conn.commit()
        except _OwnershipLost:
            self.conn.rollback()
            raise
        except Exception:
            self.conn.rollback()
            self.conn.execute(
                "update production_stages set status='blocked',validation_errors_json=?,error_reason=?,updated_at=? where id=? and lease_owner=? and run_generation=? and lease_expires_at > ?",
                (json.dumps(["artifact_persistence_failed"], ensure_ascii=False), "artifact persistence failed", _now(), stage_id, self.owner, context["generation"], _now()),
            )
            write_audit_events()
            record_event(
                self.conn,
                run_id=run_id,
                stage_id=stage_id,
                stage_name=stage,
                logical_key=str(context["payload"].get("key") or ""),
                step_name="persistence",
                event_type="persistence",
                attempt=context["attempt"],
                status="failed",
                input_value=output,
                output_value={},
                errors=["artifact_persistence_failed"],
                completed_at=_now(),
            )
            self.conn.commit()
            self._block_descendants(run_id, stage)
            raise

    def _dependency_ids(self, run_id: str, stage: str, payload: dict[str, Any]) -> list[str]:
        if stage == "qf_design":
            return []
        parent_type = STAGE_INPUTS[stage][0]
        parent_id = payload.get(f"{parent_type}_id")
        if not parent_id:
            raise ValueError(f"{stage} input is missing parent {parent_type}_id")
        parent_stage = STAGES[STAGES.index(stage) - 1]
        rows = self.conn.execute(
            "select a.id from production_artifacts a join production_stages s on s.id=a.stage_id where a.run_id=? and a.artifact_type=? and a.logical_key=? and s.run_id=? and s.stage_name=? and s.status='completed' order by a.artifact_attempt desc limit 1",
            (run_id, parent_type, str(parent_id), run_id, parent_stage),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError(f"{stage} input parent {parent_type}/{parent_id} is not exactly one artifact in this run")
        return [row["id"] for row in rows]

    def _artifact_key(self, stage: str, item: dict[str, Any]) -> str:
        artifact_type = ARTIFACT_TYPES[stage]
        key = str(item.get(f"{artifact_type}_id") or "").strip()
        if not key:
            raise ValueError(f"{stage} output requires {artifact_type}_id")
        return key

    def _input_key(self, stage: str, payload: dict[str, Any]) -> str:
        if stage == "qf_design":
            key = payload.get("node_id")
        else:
            parent_type = STAGE_INPUTS[stage][0]
            key = payload.get(f"{ARTIFACT_TYPES[stage]}_id") or payload.get(f"{parent_type}_id")
        key = str(key or "").strip()
        if not key:
            raise ValueError(f"{stage} input requires its entity id")
        return key

    def _block_descendants(self, run_id: str, failed_stage: str) -> None:
        start = STAGES.index(failed_stage) + 1
        if start >= len(STAGES):
            return
        names = STAGES[start:]
        marks = ",".join("?" for _ in names)
        self.conn.execute(
            f"update production_stages set status='blocked',error_reason=? where run_id=? and stage_name in ({marks}) and status='pending'",
            (f"blocked by {failed_stage}", run_id, *names),
        )
        self.conn.commit()


class _ValidationFailure(ValueError):
    def __init__(self, errors: list[dict[str, Any]], *, validation_result: ValidationResult | None = None, semantic_review: dict[str, Any] | None = None):
        self.errors = errors
        self.validation_result = validation_result
        self.semantic_review = semantic_review
        super().__init__("skill validation failed: " + ",".join(str(error.get("code") or "validation_failed") for error in errors))


class _OwnershipLost(RuntimeError):
    pass


def create_question_production_orchestrator(
    conn: sqlite3.Connection,
    *,
    generators: dict[str, Generator],
    reviewers: dict[str, Any] | None = None,
    persistences: dict[str, Persistence] | None = None,
    require_semantic_review: bool = True,
    max_workers: int = 4,
    max_attempts: int = 3,
    lease_seconds: int = 300,
) -> ProductionOrchestrator:
    """Build the production pipeline from four independent stage generators."""

    return ProductionOrchestrator(
        conn,
        skills=build_question_production_skills(generators, reviewers=reviewers),
        persistences=persistences,
        require_semantic_review=require_semantic_review,
        max_workers=max_workers,
        max_attempts=max_attempts,
        lease_seconds=lease_seconds,
    )


def create_live_question_production_orchestrator(
    conn: sqlite3.Connection,
    *,
    max_workers: int = 4,
    max_attempts: int = 3,
    lease_seconds: int = 300,
) -> ProductionOrchestrator:
    """Build the production workflow backed by the configured live model routes."""
    return ProductionOrchestrator(
        conn,
        skills=build_live_question_production_skills(),
        persistences=default_persistences(),
        require_semantic_review=True,
        max_workers=max_workers,
        max_attempts=max_attempts,
        lease_seconds=lease_seconds,
    )
