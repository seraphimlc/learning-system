from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ATTEMPT_STATE_SCHEMA_VERSION = "2026-07-25.codex-admin.production-attempt-state.v1"
_EXECUTION_CONTRACT_PATHS = (
    "agent_contracts/question_candidate.v1.json",
    "agent_contracts/question_candidate_batch.v1.json",
    "agent_contracts/admin_question_expert_review.v1.json",
    "prompts/question_candidate.v1.md",
    "prompts/question_candidate_batch.v1.md",
    "prompts/admin_question_expert_review.v1.md",
    "admin/question_generation.py",
    "admin/expert_review.py",
    "admin/production_workflow.py",
    "admin/qa_review.py",
    "admin/semantic_collision.py",
    "admin/staging.py",
)


class ContentAttemptBudgetExhausted(RuntimeError):
    pass


_STATE_LOCKS: dict[str, threading.Lock] = {}
_STATE_LOCKS_GUARD = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def production_execution_contract_sha256() -> str:
    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for relative_path in _EXECUTION_CONTRACT_PATHS:
        path = package_root / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class ProductionAttemptLedger:
    def __init__(
        self,
        *,
        root: Path,
        artifact_root: Path,
        staged_bank_path: Path,
        requirement_id: str,
        slot_id: str,
        max_content_attempts: int,
        apply: bool,
    ) -> None:
        if not requirement_id or not slot_id:
            raise ValueError("production attempt state requires requirement_id and slot_id")
        if max_content_attempts < 1 or max_content_attempts > 5:
            raise ValueError("max_content_attempts must be between 1 and 5")
        self.root = root
        self.artifact_root = artifact_root
        self.staged_bank_path = staged_bank_path if staged_bank_path.is_absolute() else root / staged_bank_path
        self.requirement_id = requirement_id
        self.slot_id = slot_id
        self.requested_max_content_attempts = max_content_attempts
        self.apply = apply
        self.execution_contract_sha256 = production_execution_contract_sha256()
        locator_input = "|".join(
            [
                str(self.staged_bank_path.resolve()),
                requirement_id,
                slot_id,
                self.execution_contract_sha256,
            ]
        )
        self.locator_id = hashlib.sha256(locator_input.encode("utf-8")).hexdigest()[:20]
        self.state_path = (
            artifact_root
            / "data/admin/production_attempt_state"
            / f"ATTEMPT-{self.locator_id}.json"
        )
        self.lock_path = self.state_path.with_suffix(".lock")
        self._memory_state: dict[str, Any] | None = None
        self._ensure_state()

    def _thread_lock(self) -> threading.Lock:
        key = str(self.state_path.resolve())
        with _STATE_LOCKS_GUARD:
            lock = _STATE_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                _STATE_LOCKS[key] = lock
            return lock

    def _new_state(self) -> dict[str, Any]:
        bank_digest = _sha256_file(self.staged_bank_path)
        identity_input = "|".join(
            [
                bank_digest,
                self.requirement_id,
                self.slot_id,
                self.execution_contract_sha256,
            ]
        )
        now = _utc_now()
        return {
            "schema_version": ATTEMPT_STATE_SCHEMA_VERSION,
            "state_id": "ATTEMPT-" + hashlib.sha256(identity_input.encode("utf-8")).hexdigest()[:20],
            "locator_id": self.locator_id,
            "staged_bank_path": str(self.staged_bank_path),
            "staged_bank_digest": bank_digest,
            "question_requirement_id": self.requirement_id,
            "slot_id": self.slot_id,
            "execution_contract_sha256": self.execution_contract_sha256,
            "max_content_attempts": self.requested_max_content_attempts,
            "content_attempts_consumed": 0,
            "provider_transport_attempt_count": 0,
            "provider_transport_retry_count": 0,
            "crash_recovery_count": 0,
            "pending_content_attempt": None,
            "pending_review_checkpoint": None,
            "pending_stage_checkpoint": None,
            "resume_rejection_path": "",
            "provider_transport_events": [],
            "history": [],
            "created_at": now,
            "updated_at": now,
        }

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.apply:
            if self._memory_state is None:
                self._memory_state = self._new_state()
            return json.loads(json.dumps(self._memory_state))
        if not self.state_path.exists():
            return self._new_state()
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != ATTEMPT_STATE_SCHEMA_VERSION:
            raise ValueError("ADMIN_PRODUCTION_ATTEMPT_STATE_UNSUPPORTED_SCHEMA")
        if payload.get("question_requirement_id") != self.requirement_id or payload.get("slot_id") != self.slot_id:
            raise ValueError("ADMIN_PRODUCTION_ATTEMPT_STATE_IDENTITY_MISMATCH")
        if payload.get("execution_contract_sha256") != self.execution_contract_sha256:
            raise ValueError("ADMIN_PRODUCTION_ATTEMPT_STATE_CONTRACT_MISMATCH")
        return payload

    def _save_unlocked(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _utc_now()
        if self.apply:
            _atomic_write_json(self.state_path, state)
        else:
            self._memory_state = json.loads(json.dumps(state))

    def _mutate(self, callback: Callable[[dict[str, Any]], Any]) -> Any:
        with self._thread_lock():
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    state = self._load_unlocked()
                    state["max_content_attempts"] = min(
                        int(state.get("max_content_attempts") or self.requested_max_content_attempts),
                        self.requested_max_content_attempts,
                    )
                    result = callback(state)
                    self._save_unlocked(state)
                    return result
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _ensure_state(self) -> None:
        self._mutate(lambda _state: None)

    def snapshot(self) -> dict[str, Any]:
        return self._mutate(lambda state: json.loads(json.dumps(state)))

    def begin_content_attempt(self) -> dict[str, Any]:
        def begin(state: dict[str, Any]) -> dict[str, Any]:
            pending = state.get("pending_content_attempt")
            if isinstance(pending, dict):
                state["crash_recovery_count"] = int(state.get("crash_recovery_count") or 0) + 1
                state["history"].append(
                    {
                        "event": "pending_attempt_recovered",
                        "lease_id": pending.get("lease_id"),
                        "content_attempt": pending.get("content_attempt"),
                        "at": _utc_now(),
                    }
                )
                return dict(pending)
            consumed = int(state.get("content_attempts_consumed") or 0)
            maximum = int(state.get("max_content_attempts") or 0)
            if consumed >= maximum:
                raise ContentAttemptBudgetExhausted(
                    f"ADMIN_PRODUCTION_CONTENT_ATTEMPT_BUDGET_EXHAUSTED: {consumed}/{maximum}"
                )
            content_attempt = consumed + 1
            lease = {
                "lease_id": f"{state['state_id']}:{content_attempt}",
                "content_attempt": content_attempt,
                "started_at": _utc_now(),
            }
            state["pending_content_attempt"] = lease
            state["history"].append(
                {
                    "event": "content_attempt_started",
                    "lease_id": lease["lease_id"],
                    "content_attempt": content_attempt,
                    "at": _utc_now(),
                }
            )
            return dict(lease)

        return self._mutate(begin)

    def record_provider_transport_attempts(
        self,
        lease: dict[str, Any],
        *,
        stage: str,
        attempts: list[dict[str, Any]],
    ) -> None:
        def record(state: dict[str, Any]) -> None:
            existing_ids = {
                str(event.get("event_id") or "")
                for event in state.get("provider_transport_events") or []
            }
            for index, attempt in enumerate(attempts):
                event_payload = {
                    "lease_id": lease.get("lease_id"),
                    "content_attempt": lease.get("content_attempt"),
                    "stage": stage,
                    "ordinal": index,
                    "outcome": str(attempt.get("outcome") or ""),
                    "status_code": attempt.get("status_code"),
                    "request_digest_sha256": str(attempt.get("request_digest_sha256") or ""),
                }
                event_id = hashlib.sha256(
                    json.dumps(event_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                if event_id in existing_ids:
                    continue
                existing_ids.add(event_id)
                event_payload["event_id"] = event_id
                event_payload["recorded_at"] = _utc_now()
                state["provider_transport_events"].append(event_payload)
                state["provider_transport_attempt_count"] = int(
                    state.get("provider_transport_attempt_count") or 0
                ) + 1
                if event_payload["outcome"] == "retryable_failure":
                    state["provider_transport_retry_count"] = int(
                        state.get("provider_transport_retry_count") or 0
                    ) + 1

        self._mutate(record)

    def complete_content_attempt(
        self,
        lease: dict[str, Any],
        *,
        consumed: bool,
        outcome: str,
    ) -> None:
        def complete(state: dict[str, Any]) -> None:
            pending = state.get("pending_content_attempt")
            if not isinstance(pending, dict) or pending.get("lease_id") != lease.get("lease_id"):
                raise ValueError("ADMIN_PRODUCTION_ATTEMPT_LEASE_MISMATCH")
            if consumed:
                state["content_attempts_consumed"] = max(
                    int(state.get("content_attempts_consumed") or 0),
                    int(lease.get("content_attempt") or 0),
                )
            state["history"].append(
                {
                    "event": "content_attempt_completed",
                    "lease_id": lease.get("lease_id"),
                    "content_attempt": lease.get("content_attempt"),
                    "consumed": bool(consumed),
                    "outcome": outcome,
                    "at": _utc_now(),
                }
            )
            state["pending_content_attempt"] = None

        self._mutate(complete)

    def save_pending_stage_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        if checkpoint.get("collision_required") is not True:
            raise ValueError("ADMIN_PRODUCTION_CHECKPOINT_COLLISION_REQUIRED")
        if checkpoint.get("collision_required") and checkpoint.get("collision_reviewed"):
            required = (
                "semantic_collision_json_path",
                "semantic_collision_json_sha256",
                "candidate_set_sha256",
                "base_staged_bank_sha256",
                "base_staged_snapshot_sha256",
                "collision_decision",
            )
            if any(not checkpoint.get(key) for key in required):
                raise ValueError("ADMIN_PRODUCTION_CHECKPOINT_COLLISION_BINDING_MISSING")
            decision = checkpoint.get("collision_decision")
            if not isinstance(decision, dict) or decision.get("decision") != "PASS":
                raise ValueError("ADMIN_PRODUCTION_CHECKPOINT_COLLISION_BINDING_INVALID")
            if str(decision.get("candidate_item_id") or "") != str(checkpoint.get("item_id") or ""):
                raise ValueError("ADMIN_PRODUCTION_CHECKPOINT_COLLISION_BINDING_ITEM_MISMATCH")

        def save(state: dict[str, Any]) -> None:
            state["pending_stage_checkpoint"] = json.loads(json.dumps(checkpoint))
            state["history"].append(
                {
                    "event": "pending_stage_checkpoint_saved",
                    "item_id": checkpoint.get("item_id"),
                    "at": _utc_now(),
                }
            )

        self._mutate(save)

    def save_pending_review_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        def save(state: dict[str, Any]) -> None:
            state["pending_review_checkpoint"] = json.loads(json.dumps(checkpoint))
            state["history"].append(
                {
                    "event": "pending_review_checkpoint_saved",
                    "item_id": checkpoint.get("item_id"),
                    "at": _utc_now(),
                }
            )

        self._mutate(save)

    def pending_review_checkpoint(self) -> dict[str, Any] | None:
        snapshot = self.snapshot()
        checkpoint = snapshot.get("pending_review_checkpoint")
        return json.loads(json.dumps(checkpoint)) if isinstance(checkpoint, dict) else None

    def clear_pending_review_checkpoint(self, *, outcome: str) -> None:
        def clear(state: dict[str, Any]) -> None:
            checkpoint = state.get("pending_review_checkpoint")
            state["history"].append(
                {
                    "event": "pending_review_checkpoint_cleared",
                    "item_id": checkpoint.get("item_id") if isinstance(checkpoint, dict) else "",
                    "outcome": outcome,
                    "at": _utc_now(),
                }
            )
            state["pending_review_checkpoint"] = None

        self._mutate(clear)

    def pending_stage_checkpoint(self) -> dict[str, Any] | None:
        snapshot = self.snapshot()
        checkpoint = snapshot.get("pending_stage_checkpoint")
        return json.loads(json.dumps(checkpoint)) if isinstance(checkpoint, dict) else None

    def clear_pending_stage_checkpoint(self, *, outcome: str) -> None:
        def clear(state: dict[str, Any]) -> None:
            checkpoint = state.get("pending_stage_checkpoint")
            state["history"].append(
                {
                    "event": "pending_stage_checkpoint_cleared",
                    "item_id": checkpoint.get("item_id") if isinstance(checkpoint, dict) else "",
                    "outcome": outcome,
                    "at": _utc_now(),
                }
            )
            state["pending_stage_checkpoint"] = None

        self._mutate(clear)

    def set_resume_rejection_path(self, path: str) -> None:
        self._mutate(lambda state: state.__setitem__("resume_rejection_path", path))

    def resume_rejection_path(self) -> str:
        return str(self.snapshot().get("resume_rejection_path") or "")
