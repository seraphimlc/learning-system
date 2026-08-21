"""Durable asynchronous question-production pipeline for v20.

The queue owns scheduling, leases, retries and state transitions. Semantic
decisions stay in stage handlers supplied by the model adapters. A rejected
brief never reaches concrete-question generation and never blocks another
slot.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .v20_receipts import SHA256_PATTERN, canonical_json, sha256_json


PIPELINE_SCHEMA_VERSION = "question-production-async-pipeline.v20.1"
TERMINAL_STAGES = frozenset({"brief_review", "question_review"})
QUEUE_STATUSES = frozenset(
    {
        "BRIEF_GENERATION_QUEUED",
        "BRIEF_GENERATION_RUNNING",
        "BRIEF_REVIEW_QUEUED",
        "BRIEF_REVIEW_RUNNING",
        "QUESTION_GENERATION_QUEUED",
        "QUESTION_GENERATION_RUNNING",
        "QUESTION_REVIEW_QUEUED",
        "QUESTION_REVIEW_RUNNING",
        "BRIEF_REVIEWED",
        "STAGED",
        "ACCEPTED",
        "BLOCKED",
    }
)
READY_BY_HANDLER = {
    "brief_generation": "BRIEF_GENERATION_QUEUED",
    "brief_review": "BRIEF_REVIEW_QUEUED",
    "question_generation": "QUESTION_GENERATION_QUEUED",
    "question_review": "QUESTION_REVIEW_QUEUED",
}
RUNNING_BY_HANDLER = {
    "brief_generation": "BRIEF_GENERATION_RUNNING",
    "brief_review": "BRIEF_REVIEW_RUNNING",
    "question_generation": "QUESTION_GENERATION_RUNNING",
    "question_review": "QUESTION_REVIEW_RUNNING",
}
MAX_DEFAULT_ATTEMPTS = 3


class AsyncPipelineError(RuntimeError):
    pass


class PipelineLeaseLost(AsyncPipelineError):
    pass


@dataclass(frozen=True)
class StageResult:
    """A handler's semantic result after local schema validation."""

    outcome: str
    artifact_ref: str = ""
    artifact_sha256: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "outcome": self.outcome,
            "artifact_ref": self.artifact_ref,
            "artifact_sha256": self.artifact_sha256,
            "reason": self.reason,
        }


Handler = Callable[[dict[str, Any]], StageResult | dict[str, Any]]


def _now() -> float:
    return time.time()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AsyncPipelineError(f"{field} must be nonempty")
    return value


def _sha(value: Any, field: str, *, allow_empty: bool = True) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise AsyncPipelineError(f"{field} must be a SHA-256 digest")
    return value


def _slot_digest(slot: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in slot.items() if key != "slot_sha256"})


def _queue_digest(queue: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in queue.items() if key != "queue_sha256"})


def _settled_queue_status(queue: dict[str, Any]) -> str | None:
    successful_terminal_statuses = (
        {"BRIEF_REVIEWED"}
        if queue["terminal_stage"] == "brief_review"
        else {"STAGED", "ACCEPTED"}
    )
    statuses = {slot["status"] for slot in queue["slots"]}
    if statuses and statuses <= successful_terminal_statuses and "BLOCKED" not in statuses:
        return "COMPLETE"
    if statuses and statuses <= successful_terminal_statuses | {"BLOCKED"}:
        return "BLOCKED"
    return None


def _validate_result(value: StageResult | dict[str, Any]) -> StageResult:
    if isinstance(value, StageResult):
        result = value
    elif isinstance(value, dict):
        if set(value) != {"outcome", "artifact_ref", "artifact_sha256", "reason"}:
            raise AsyncPipelineError("stage result fields are incomplete or unknown")
        result = StageResult(**value)
    else:
        raise AsyncPipelineError("stage handler must return StageResult or object")
    if result.outcome not in {"PASS", "RETRY", "BLOCKED"}:
        raise AsyncPipelineError("stage result outcome is invalid")
    if result.artifact_ref and not isinstance(result.artifact_ref, str):
        raise AsyncPipelineError("stage result artifact_ref is invalid")
    _sha(result.artifact_sha256, "stage result artifact_sha256")
    if not isinstance(result.reason, str):
        raise AsyncPipelineError("stage result reason is invalid")
    if bool(result.artifact_ref) != bool(result.artifact_sha256):
        raise AsyncPipelineError("stage result artifact reference and digest must be paired")
    if result.outcome != "PASS" and (result.artifact_ref or result.artifact_sha256):
        raise AsyncPipelineError("non-PASS stage results cannot carry an artifact")
    return result


def _validate_result_for_handler(
    handler_name: str, value: StageResult | dict[str, Any]
) -> StageResult:
    result = _validate_result(value)
    if handler_name not in RUNNING_BY_HANDLER:
        raise AsyncPipelineError(f"unknown handler: {handler_name}")
    if handler_name in {"brief_generation", "question_generation"} and result.outcome == "PASS":
        if not result.artifact_ref or not result.artifact_sha256:
            raise AsyncPipelineError(
                "PASS generation results require an artifact reference and digest"
            )
    return result


def _validate_slot(slot: Any) -> dict[str, Any]:
    fields = {
        "slot_id", "operation_key", "status", "brief_attempt", "question_attempt",
        "brief_ref", "brief_sha256", "question_ref", "question_sha256",
        "last_error", "lease_owner", "lease_expires_at", "updated_at", "slot_sha256",
    }
    if not isinstance(slot, dict) or set(slot) != fields:
        raise AsyncPipelineError("pipeline slot fields are incomplete or unknown")
    _text(slot["slot_id"], "slot_id")
    if slot["operation_key"] != f"v20:{slot['slot_id']}":
        raise AsyncPipelineError("slot operation_key is invalid")
    if slot["status"] not in QUEUE_STATUSES:
        raise AsyncPipelineError("pipeline slot status is invalid")
    for field in ("brief_attempt", "question_attempt"):
        if isinstance(slot[field], bool) or not isinstance(slot[field], int) or slot[field] < 0:
            raise AsyncPipelineError(f"{field} is invalid")
    for field in ("brief_ref", "question_ref", "last_error", "lease_owner"):
        if not isinstance(slot[field], str):
            raise AsyncPipelineError(f"{field} is invalid")
    for field in ("brief_sha256", "question_sha256"):
        _sha(slot[field], field)
    if isinstance(slot["lease_expires_at"], bool) or not isinstance(slot["lease_expires_at"], (int, float)):
        raise AsyncPipelineError("lease_expires_at is invalid")
    if isinstance(slot["updated_at"], bool) or not isinstance(slot["updated_at"], (int, float)):
        raise AsyncPipelineError("updated_at is invalid")
    if slot["slot_sha256"] != _slot_digest(slot):
        raise AsyncPipelineError("slot digest does not match content")
    return deepcopy(slot)


def validate_queue(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "run_id", "batch_id", "status", "max_brief_attempts",
        "max_question_attempts", "terminal_stage", "slots", "created_at", "updated_at",
        "queue_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise AsyncPipelineError("pipeline queue fields are incomplete or unknown")
    if value["schema_version"] != PIPELINE_SCHEMA_VERSION:
        raise AsyncPipelineError("unsupported async pipeline schema")
    _text(value["run_id"], "run_id")
    _text(value["batch_id"], "batch_id")
    if value["status"] not in {"RUNNING", "COMPLETE", "BLOCKED"}:
        raise AsyncPipelineError("pipeline queue status is invalid")
    if value["terminal_stage"] not in TERMINAL_STAGES:
        raise AsyncPipelineError("pipeline terminal_stage is invalid")
    for field in ("max_brief_attempts", "max_question_attempts"):
        if isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] < 1:
            raise AsyncPipelineError(f"{field} is invalid")
    if not isinstance(value["slots"], list) or not value["slots"]:
        raise AsyncPipelineError("pipeline slots must be nonempty")
    slots = [_validate_slot(slot) for slot in value["slots"]]
    if len({slot["slot_id"] for slot in slots}) != len(slots):
        raise AsyncPipelineError("pipeline slot ids must be unique")
    for field in ("created_at", "updated_at"):
        if isinstance(value[field], bool) or not isinstance(value[field], (int, float)):
            raise AsyncPipelineError(f"{field} is invalid")
    if value["queue_sha256"] != _queue_digest({**value, "slots": slots}):
        raise AsyncPipelineError("pipeline queue digest does not match content")
    forbidden_statuses = {
        "QUESTION_GENERATION_QUEUED",
        "QUESTION_GENERATION_RUNNING",
        "QUESTION_REVIEW_QUEUED",
        "QUESTION_REVIEW_RUNNING",
        "STAGED",
    }
    if value["terminal_stage"] == "brief_review" and any(
        slot["status"] in forbidden_statuses for slot in slots
    ):
        raise AsyncPipelineError(
            "brief_review terminal queues cannot contain concrete-question stages"
        )
    return deepcopy({**value, "slots": slots})


def _new_slot(slot_id: str, now: float) -> dict[str, Any]:
    slot = {
        "slot_id": _text(slot_id, "slot_id"),
        "operation_key": f"v20:{slot_id}",
        "status": "BRIEF_GENERATION_QUEUED",
        "brief_attempt": 0,
        "question_attempt": 0,
        "brief_ref": "",
        "brief_sha256": "",
        "question_ref": "",
        "question_sha256": "",
        "last_error": "",
        "lease_owner": "",
        "lease_expires_at": 0.0,
        "updated_at": now,
        "slot_sha256": "",
    }
    slot["slot_sha256"] = _slot_digest(slot)
    return slot


def build_queue(
    slot_ids: Iterable[str],
    *,
    batch_id: str = "pilot",
    run_id: str | None = None,
    max_brief_attempts: int = MAX_DEFAULT_ATTEMPTS,
    max_question_attempts: int = MAX_DEFAULT_ATTEMPTS,
    terminal_stage: str = "question_review",
) -> dict[str, Any]:
    if terminal_stage not in TERMINAL_STAGES:
        raise AsyncPipelineError("terminal_stage must be brief_review or question_review")
    now = _now()
    slots = [_new_slot(slot_id, now) for slot_id in slot_ids]
    if not slots:
        raise AsyncPipelineError("at least one slot is required")
    queue = {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "run_id": run_id or f"v20-async-{uuid.uuid4().hex[:16]}",
        "batch_id": _text(batch_id, "batch_id"),
        "status": "RUNNING",
        "max_brief_attempts": max_brief_attempts,
        "max_question_attempts": max_question_attempts,
        "terminal_stage": terminal_stage,
        "slots": slots,
        "created_at": now,
        "updated_at": now,
        "queue_sha256": "",
    }
    queue["queue_sha256"] = _queue_digest(queue)
    return validate_queue(queue)


def build_question_queue_from_reviewed_briefs(
    project_root: Path | str,
    slot_ids: Iterable[str],
    *,
    batch_id: str = "pilot",
    run_id: str | None = None,
    max_question_attempts: int = MAX_DEFAULT_ATTEMPTS,
) -> dict[str, Any]:
    """Start concrete production from already published REVIEWED briefs.

    This is deliberately a different constructor from ``build_queue``: it
    cannot invent or review a brief, and it never creates a question job for a
    missing or non-REVIEWED brief. Full-bank activation is unaffected.
    """
    root = Path(project_root)
    queue = build_queue(
        slot_ids,
        batch_id=batch_id,
        run_id=run_id,
        max_question_attempts=max_question_attempts,
        terminal_stage="question_review",
    )
    for slot in queue["slots"]:
        brief_path = root / "data/question_banks/v20/slot_brief_reviewed" / f"{slot['slot_id']}.json"
        try:
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AsyncPipelineError(f"reviewed brief is unavailable: {slot['slot_id']}") from exc
        if not isinstance(brief, dict) or brief.get("status") != "REVIEWED":
            raise AsyncPipelineError(f"slot brief is not REVIEWED: {slot['slot_id']}")
        if brief.get("slot_id") != slot["slot_id"] or not isinstance(brief.get("brief_sha256"), str):
            raise AsyncPipelineError(f"reviewed brief identity is invalid: {slot['slot_id']}")
        slot["brief_ref"] = brief_path.relative_to(root).as_posix()
        slot["brief_sha256"] = brief["brief_sha256"]
        slot["status"] = "QUESTION_GENERATION_QUEUED"
        slot["slot_sha256"] = _slot_digest(slot)
    queue["queue_sha256"] = _queue_digest(queue)
    return validate_queue(queue)


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_: Any) -> None:
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


class AsyncPipelineStore:
    """Atomic queue persistence with a process-level file lock."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.telemetry_path = self.path.with_suffix(".telemetry.jsonl")
        self._thread_lock = threading.RLock()

    def record_timing(self, record: dict[str, Any]) -> None:
        """Append one stage timing without changing the queue contract."""
        with self._thread_lock, _FileLock(self.telemetry_path.with_suffix(self.telemetry_path.suffix + ".lock")):
            self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            with self.telemetry_path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _load_unlocked(self) -> dict[str, Any]:
        try:
            return validate_queue(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise AsyncPipelineError(f"unable to load async pipeline queue: {self.path}") from exc

    def _write_unlocked(self, queue: dict[str, Any]) -> dict[str, Any]:
        checked = deepcopy(queue)
        checked["queue_sha256"] = _queue_digest(checked)
        checked = validate_queue(checked)
        checked["updated_at"] = _now()
        checked["queue_sha256"] = _queue_digest(checked)
        checked = validate_queue(checked)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        fd, name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(canonical_json(checked) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return checked

    def load(self) -> dict[str, Any]:
        with self._thread_lock, _FileLock(self.lock_path):
            return self._load_unlocked()

    def save(self, queue: dict[str, Any]) -> dict[str, Any]:
        with self._thread_lock, _FileLock(self.lock_path):
            return self._write_unlocked(queue)

    def initialize(self, queue: dict[str, Any]) -> dict[str, Any]:
        with self._thread_lock, _FileLock(self.lock_path):
            if self.path.exists():
                existing = self._load_unlocked()
                expected = validate_queue(queue)
                if existing != expected:
                    raise AsyncPipelineError("async pipeline queue already exists with different content")
                return existing
            return self._write_unlocked(queue)

    def recover_expired(self, *, now: float | None = None) -> dict[str, Any]:
        current = _now() if now is None else float(now)
        with self._thread_lock, _FileLock(self.lock_path):
            queue = self._load_unlocked()
            changed = False
            for slot in queue["slots"]:
                if slot["status"].endswith("_RUNNING") and slot["lease_expires_at"] <= current:
                    handler = next(
                        key for key, value in RUNNING_BY_HANDLER.items() if value == slot["status"]
                    )
                    slot["status"] = READY_BY_HANDLER[handler]
                    slot["lease_owner"] = ""
                    slot["lease_expires_at"] = 0.0
                    slot["last_error"] = "expired lease recovered"
                    slot["slot_sha256"] = _slot_digest(slot)
                    changed = True
            return self._write_unlocked(queue) if changed else queue

    def reconcile_status(self) -> dict[str, Any]:
        """Settle a queue whose slots have all reached terminal states."""
        with self._thread_lock, _FileLock(self.lock_path):
            queue = self._load_unlocked()
            settled = _settled_queue_status(queue)
            if settled is None or queue["status"] == settled:
                return queue
            queue["status"] = settled
            return self._write_unlocked(queue)

    def claim(self, *, handler_name: str, owner: str, lease_seconds: float = 300.0) -> dict[str, Any] | None:
        if handler_name not in READY_BY_HANDLER:
            raise AsyncPipelineError(f"unknown handler: {handler_name}")
        ready = READY_BY_HANDLER[handler_name]
        running = RUNNING_BY_HANDLER[handler_name]
        with self._thread_lock, _FileLock(self.lock_path):
            queue = self._load_unlocked()
            if queue["terminal_stage"] == "brief_review" and handler_name in {
                "question_generation",
                "question_review",
            }:
                return None
            for slot in sorted(queue["slots"], key=lambda item: item["slot_id"]):
                if slot["status"] == ready:
                    slot["status"] = running
                    slot["lease_owner"] = _text(owner, "owner")
                    slot["lease_expires_at"] = _now() + float(lease_seconds)
                    slot["updated_at"] = _now()
                    slot["slot_sha256"] = _slot_digest(slot)
                    self._write_unlocked(queue)
                    return deepcopy(slot)
            return None

    def apply(
        self,
        *,
        handler_name: str,
        slot_id: str,
        owner: str,
        result: StageResult | dict[str, Any],
    ) -> dict[str, Any]:
        result = _validate_result_for_handler(handler_name, result)
        with self._thread_lock, _FileLock(self.lock_path):
            queue = self._load_unlocked()
            slot = next((item for item in queue["slots"] if item["slot_id"] == slot_id), None)
            if slot is None:
                raise AsyncPipelineError(f"slot is missing from queue: {slot_id}")
            running = RUNNING_BY_HANDLER[handler_name]
            if slot["status"] != running or slot["lease_owner"] != owner:
                raise PipelineLeaseLost(f"slot is not owned by {owner}: {slot_id}")
            if handler_name == "brief_generation":
                slot["brief_attempt"] += 1
                if result.outcome == "PASS":
                    slot["brief_ref"] = result.artifact_ref
                    slot["brief_sha256"] = result.artifact_sha256
                    slot["status"] = "BRIEF_REVIEW_QUEUED"
                elif result.outcome == "RETRY" and slot["brief_attempt"] < queue["max_brief_attempts"]:
                    slot["status"] = "BRIEF_GENERATION_QUEUED"
                else:
                    slot["status"] = "BLOCKED"
            elif handler_name == "brief_review":
                if result.outcome == "PASS":
                    if result.artifact_ref:
                        slot["brief_ref"] = result.artifact_ref
                        slot["brief_sha256"] = result.artifact_sha256
                    slot["status"] = (
                        "BRIEF_REVIEWED"
                        if queue["terminal_stage"] == "brief_review"
                        else "QUESTION_GENERATION_QUEUED"
                    )
                elif result.outcome == "RETRY" and slot["brief_attempt"] < queue["max_brief_attempts"]:
                    slot["status"] = "BRIEF_GENERATION_QUEUED"
                else:
                    slot["status"] = "BLOCKED"
            elif handler_name == "question_generation":
                slot["question_attempt"] += 1
                if result.outcome == "PASS":
                    slot["question_ref"] = result.artifact_ref
                    slot["question_sha256"] = result.artifact_sha256
                    slot["status"] = "QUESTION_REVIEW_QUEUED"
                elif result.outcome == "RETRY" and slot["question_attempt"] < queue["max_question_attempts"]:
                    slot["status"] = "QUESTION_GENERATION_QUEUED"
                else:
                    slot["status"] = "BLOCKED"
            elif handler_name == "question_review":
                if result.outcome == "PASS":
                    if result.artifact_ref:
                        slot["question_ref"] = result.artifact_ref
                        slot["question_sha256"] = result.artifact_sha256
                    # STAGED is the immutable artifact checkpoint. ACCEPTED is
                    # the queue's terminal admission decision after the full
                    # configured reviewer route has passed.
                    slot["status"] = "ACCEPTED"
                elif result.outcome == "RETRY" and slot["question_attempt"] < queue["max_question_attempts"]:
                    slot["status"] = "QUESTION_GENERATION_QUEUED"
                else:
                    slot["status"] = "BLOCKED"
            slot["last_error"] = result.reason
            slot["lease_owner"] = ""
            slot["lease_expires_at"] = 0.0
            slot["updated_at"] = _now()
            slot["slot_sha256"] = _slot_digest(slot)
            settled = _settled_queue_status(queue)
            if settled is not None:
                queue["status"] = settled
            return self._write_unlocked(queue)


class AsyncQuestionPipeline:
    """Run independent stage workers until this queue has no runnable jobs."""

    def __init__(
        self,
        store: AsyncPipelineStore,
        handlers: dict[str, Handler],
        *,
        concurrency: dict[str, int] | None = None,
        lease_seconds: float = 300.0,
    ) -> None:
        missing = set(READY_BY_HANDLER) - set(handlers)
        if missing:
            raise AsyncPipelineError(f"missing stage handlers: {sorted(missing)}")
        self.store = store
        self.handlers = handlers
        self.concurrency = {key: 1 for key in READY_BY_HANDLER}
        self.concurrency.update(concurrency or {})
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in self.concurrency.values()):
            raise AsyncPipelineError("stage concurrency must be positive integers")
        self.lease_seconds = lease_seconds

    def _submit_ready(
        self,
        executors: dict[str, ThreadPoolExecutor],
        futures: dict[Future[Any], tuple[str, str, str, float, float]],
    ) -> None:
        for handler_name in READY_BY_HANDLER:
            occupied = sum(1 for item in futures.values() if item[0] == handler_name)
            while occupied < self.concurrency[handler_name]:
                owner = f"async-{handler_name}-{uuid.uuid4().hex[:10]}"
                slot = self.store.claim(
                    handler_name=handler_name,
                    owner=owner,
                    lease_seconds=self.lease_seconds,
                )
                if slot is None:
                    break
                started_at = _now()
                started_monotonic = time.monotonic()
                future = executors[handler_name].submit(self.handlers[handler_name], deepcopy(slot))
                futures[future] = (
                    handler_name,
                    slot["slot_id"],
                    owner,
                    started_at,
                    started_monotonic,
                )
                occupied += 1

    def run(self) -> dict[str, Any]:
        self.store.recover_expired()
        executors = {
            name: ThreadPoolExecutor(max_workers=self.concurrency[name], thread_name_prefix=f"v20-{name}")
            for name in READY_BY_HANDLER
        }
        futures: dict[Future[Any], tuple[str, str, str, float, float]] = {}
        completed = 0
        try:
            self._submit_ready(executors, futures)
            while futures:
                done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in done:
                    handler_name, slot_id, owner, started_at, started_monotonic = futures.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:  # handler boundary; keep this slot isolated
                        result = StageResult(outcome="BLOCKED", reason=f"handler failed: {exc}")
                    try:
                        result = _validate_result_for_handler(handler_name, result)
                    except AsyncPipelineError as exc:
                        result = StageResult(
                            outcome="BLOCKED",
                            reason=f"invalid stage result: {exc}",
                        )
                    self.store.record_timing(
                        {
                            "schema_version": "question-production-stage-timing.v20",
                            "run_id": self.store.load()["run_id"],
                            "slot_id": slot_id,
                            "handler": handler_name,
                            "started_at": started_at,
                            "finished_at": _now(),
                            "duration_ms": round((time.monotonic() - started_monotonic) * 1000, 3),
                            "outcome": result.outcome,
                        }
                    )
                    try:
                        self.store.apply(
                            handler_name=handler_name,
                            slot_id=slot_id,
                            owner=owner,
                            result=result,
                        )
                    except PipelineLeaseLost:
                        # A stale result must never overwrite a newer owner. The
                        # next run can recover the expired lease and continue.
                        continue
                    completed += 1
                self._submit_ready(executors, futures)
            queue = self.store.reconcile_status()
            return {
                "schema_version": PIPELINE_SCHEMA_VERSION,
                "run_id": queue["run_id"],
                "batch_id": queue["batch_id"],
                "terminal_stage": queue["terminal_stage"],
                "completed_stage_jobs": completed,
                "queue_status": queue["status"],
                "slot_statuses": {slot["slot_id"]: slot["status"] for slot in queue["slots"]},
            }
        finally:
            for executor in executors.values():
                executor.shutdown(wait=True)
