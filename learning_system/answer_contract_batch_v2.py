"""Batch A v2 generation skeleton.

This module owns batch-level state and exclusion contracts. Per-question semantic
generation remains in ``answer_contract_generation_v2``. All orchestration entry
points fail closed until the Batch A test-design gate authorizes implementation.
"""

from __future__ import annotations

import fcntl
import hashlib
import itertools
import json
import math
import os
import secrets
import sqlite3
import stat
import time
import uuid
import weakref
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol

from . import model_router, question_fingerprints


RUN_SCHEMA_VERSION = "answer_contract_generation_run.v1"
PREFLIGHT_SCHEMA_VERSION = "answer_contract_v2_batch_preflight.v1"
PROVIDER_CHAIN_SCHEMA_VERSION = "answer_contract_v2_provider_chain.v2"
AGENT_LINEAGE_SCHEMA_VERSION = "answer_contract_v2_agent_lineage.v2"
CANARY_RECEIPT_SCHEMA_VERSION = "answer_contract_v2_canary_receipt.v1"
EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION = (
    "answer_contract_effective_evidence_role.v1"
)
EFFECTIVE_EVIDENCE_ROLE_POLICY = {
    "version": EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION,
    "source_precedence": ["evidence_role", "evidence_goal", "direct"],
    "normalization": "strip_nonempty_string",
    "invalid_type": "reject",
}
EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256 = (
    question_fingerprints.canonical_sha256(EFFECTIVE_EVIDENCE_ROLE_POLICY)
)

RUN_KIND_CANARY = "canary40"
RUN_KIND_FULL = "full1120"
CANARY_ITEM_COUNT = 40
CANARY_DEFAULT_MODEL_CALL_CAP = 240
CANARY_HARD_MODEL_CALL_CAP = 720
CANARY_DEFAULT_PROVIDER_ATTEMPT_CAP = 840
CANARY_HARD_PROVIDER_ATTEMPT_CAP = 2_520
CANARY_DEFAULT_MAX_ITEMS = 40
CANARY_HARD_MAX_ITEMS = 40
CANARY_DEFAULT_WALL_SECONDS = 14_400.0
CANARY_HARD_WALL_SECONDS = 43_200.0
HEARTBEAT_INTERVAL_SECONDS = 15.0
MAX_RETRY_AFTER_SECONDS = 120.0

RUN_STATUSES = frozenset(
    {
        "planned",
        "preflight_running",
        "running",
        "completed_passed",
        "completed_blocked",
        "interrupted",
        "blocked_integrity",
        "cap_exhausted",
        "commit_unknown",
        "committed_unverified",
    }
)
RUN_TERMINAL_STATUSES = frozenset(
    {
        "completed_passed",
        "completed_blocked",
        "blocked_integrity",
        "cap_exhausted",
    }
)
RUN_ITEM_STATUSES = frozenset(
    {
        "pending",
        "running",
        "approved",
        "routed",
        "terminal_failure",
        "interrupted",
        "blocked_integrity",
        "reused_approved",
    }
)
SEMANTIC_ATTEMPT_STATUSES = frozenset(
    {
        "reserved",
        "provider_calling",
        "accepted",
        "semantic_rejected",
        "transport_failed",
        "interrupted",
        "provider_result_unknown",
        "commit_unknown",
        "committed_unverified",
    }
)
PROVIDER_ATTEMPT_STATUSES = frozenset(
    {
        "reserved",
        "calling",
        "response_received",
        "retryable_failure",
        "terminal_failure",
        "provider_result_unknown",
        "interrupted",
    }
)

SKELETON_BLOCKER = "answer_contract_v2_batch_a_orchestration_not_implemented"
SELECTION_POLICY_VERSION = "answer_contract_v2_canary_selection.v1"
ORACLE_POLICY_VERSION = "answer_contract_v2_batch_oracles.v1"
SCORING_POLICY_VERSION = "answer_contract_v2_scoring_policy_gate.v1"

REQUIRED_AUTHORITY_FOREIGN_KEYS = {
    "answer_contract_generation_runs": frozenset(
        {("parent_canary_run_id", "answer_contract_generation_runs", "id")}
    ),
    "answer_contract_generation_run_items": frozenset(
        {
            (
                "designer_batch_attempt_id",
                "answer_contract_generation_attempts",
                "id",
            ),
            (
                "reviewer_batch_attempt_id",
                "answer_contract_generation_attempts",
                "id",
            ),
        }
    ),
    "agent_runs": frozenset(
        {("batch_attempt_id", "answer_contract_generation_attempts", "id")}
    ),
    "answer_contracts": frozenset(
        {
            (
                "generator_batch_attempt_id",
                "answer_contract_generation_attempts",
                "id",
            ),
            (
                "review_batch_attempt_id",
                "answer_contract_generation_attempts",
                "id",
            ),
        }
    ),
}


class BatchASkeletonBlocked(RuntimeError):
    def __init__(self, operation: str) -> None:
        self.report = skeleton_blocked_report(operation)
        super().__init__(SKELETON_BLOCKER)


class BatchARunLocked(RuntimeError):
    def __init__(self, lock_path: Path) -> None:
        self.report = {
            "status": "run_locked",
            "lock_path": str(lock_path),
            "model_calls": 0,
            "provider_attempts": 0,
            "production_authority": False,
            "activation_eligible": False,
        }
        super().__init__("answer contract v2 Batch A run is already locked")


class BatchASchemaMigrationRequired(RuntimeError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__("answer contract v2 Batch A schema migration_required")


class BatchAStopRequested(RuntimeError):
    pass


class BatchACommitUncertain(RuntimeError):
    def __init__(self, status: str, batch_attempt_id: str) -> None:
        self.status = status
        self.batch_attempt_id = batch_attempt_id
        super().__init__(status)


@dataclass(frozen=True)
class RunClaim:
    run_id: str
    operation_generation: int
    claim_token: str
    owner_pid: int
    invocation_id: str
    claimed_at: str
    heartbeat_at: str

    def __post_init__(self) -> None:
        text_fields = (
            self.run_id,
            self.claim_token,
            self.invocation_id,
            self.claimed_at,
            self.heartbeat_at,
        )
        if any(not isinstance(value, str) or not value.strip() for value in text_fields):
            raise ValueError("RunClaim string fields must be nonempty")
        if self.operation_generation < 1:
            raise ValueError("RunClaim operation_generation must be positive")
        if self.owner_pid < 1:
            raise ValueError("RunClaim owner_pid must be positive")


_BATCH_ATTEMPT_CONTEXT_SEAL = object()
_ISSUED_BATCH_ATTEMPT_CONTEXTS: weakref.WeakSet[BatchAttemptContext] = (
    weakref.WeakSet()
)


class BatchAttemptContext:
    """Opaque DB-backed semantic-attempt authority.

    Instances are created only by ``load_batch_attempt_context``. Every consumer
    must revalidate the committed row and current CAS claim before use.
    """

    __slots__ = (
        "__seal",
        "__database_path",
        "__database_identity_digest_sha256",
        "__claim_token",
        "__batch_attempt_id",
        "__run_id",
        "__run_item_id",
        "__role",
        "__contract_version_index",
        "__semantic_attempt_index",
        "__effective_evidence_role",
        "__effective_evidence_role_policy_version",
        "__operation_generation",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        _seal: object,
        database_path: str,
        database_identity_digest_sha256: str,
        claim_token: str,
        batch_attempt_id: str,
        run_id: str,
        run_item_id: str,
        role: str,
        contract_version_index: int,
        semantic_attempt_index: int,
        effective_evidence_role: str,
        effective_evidence_role_policy_version: str,
        operation_generation: int,
    ) -> None:
        if _seal is not _BATCH_ATTEMPT_CONTEXT_SEAL:
            raise TypeError("BatchAttemptContext is opaque")
        self.__seal = _seal
        self.__database_path = database_path
        self.__database_identity_digest_sha256 = (
            database_identity_digest_sha256
        )
        self.__claim_token = claim_token
        self.__batch_attempt_id = batch_attempt_id
        self.__run_id = run_id
        self.__run_item_id = run_item_id
        self.__role = role
        self.__contract_version_index = contract_version_index
        self.__semantic_attempt_index = semantic_attempt_index
        self.__effective_evidence_role = effective_evidence_role
        self.__effective_evidence_role_policy_version = (
            effective_evidence_role_policy_version
        )
        self.__operation_generation = operation_generation

    @property
    def batch_attempt_id(self) -> str:
        return self.__batch_attempt_id

    @property
    def run_id(self) -> str:
        return self.__run_id

    @property
    def run_item_id(self) -> str:
        return self.__run_item_id

    @property
    def role(self) -> str:
        return self.__role

    @property
    def contract_version_index(self) -> int:
        return self.__contract_version_index

    @property
    def semantic_attempt_index(self) -> int:
        return self.__semantic_attempt_index

    @property
    def effective_evidence_role(self) -> str:
        return self.__effective_evidence_role

    @property
    def effective_evidence_role_policy_version(self) -> str:
        return self.__effective_evidence_role_policy_version


class BatchALifecycleObserver(Protocol):
    transport_observer: model_router.StructuredTransportLifecycleObserver

    def semantic_attempt_reserved(self, context: BatchAttemptContext) -> None:
        ...

    def semantic_attempt_finished(
        self, context: BatchAttemptContext, *, outcome: str
    ) -> None:
        ...


def _new_claim_token() -> str:
    return secrets.token_urlsafe(32)


def _new_invocation_id() -> str:
    return "ACINV-" + uuid.uuid4().hex


def _new_batch_attempt_id() -> str:
    return "ACBA-" + uuid.uuid4().hex


@dataclass(frozen=True)
class BatchATestHooks:
    wall_time: Callable[[], float] = time.time
    monotonic: Callable[[], float] = time.monotonic
    pid: Callable[[], int] = os.getpid
    new_claim_token: Callable[[], str] = _new_claim_token
    new_invocation_id: Callable[[], str] = _new_invocation_id
    new_batch_attempt_id: Callable[[], str] = _new_batch_attempt_id
    open_file: Callable[[str, int, int], int] = os.open
    close_file: Callable[[int], None] = os.close
    chmod_file: Callable[[int, int], None] = os.fchmod
    flock: Callable[[int, int], None] = fcntl.flock
    stop_requested: Callable[[], bool] = lambda: False


@dataclass
class CanonicalDBRunLock:
    path: Path
    fd: int
    hooks: BatchATestHooks = field(repr=False)
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        try:
            self.hooks.flock(self.fd, fcntl.LOCK_UN)
        finally:
            self.hooks.close_file(self.fd)
            self.released = True

    def __enter__(self) -> CanonicalDBRunLock:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


def effective_evidence_role(question: Mapping[str, Any]) -> str:
    if not isinstance(question, Mapping):
        raise TypeError("question must be a mapping")
    normalized: dict[str, str] = {}
    for field_name in ("evidence_role", "evidence_goal"):
        value = question.get(field_name)
        if value is None:
            normalized[field_name] = ""
            continue
        if not isinstance(value, str):
            raise ValueError("effective evidence role source must be a string")
        normalized[field_name] = value.strip()
    return (
        normalized["evidence_role"]
        or normalized["evidence_goal"]
        or "direct"
    )


def claim_token_digest(claim_token: str) -> str:
    if not isinstance(claim_token, str) or not claim_token:
        raise ValueError("claim_token must be a nonempty string")
    return question_fingerprints.canonical_sha256(
        {"claim_token": claim_token}
    )


def batch_schema_authority_report(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    missing = []
    for table_name, required in REQUIRED_AUTHORITY_FOREIGN_KEYS.items():
        actual = {
            (str(row[3]), str(row[2]), str(row[4]))
            for row in conn.execute(f"pragma foreign_key_list({table_name})")
        }
        for source_column, target_table, target_column in sorted(
            required.difference(actual)
        ):
            missing.append(
                {
                    "table": table_name,
                    "column": source_column,
                    "target_table": target_table,
                    "target_column": target_column,
                }
            )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": "ready" if not missing else "migration_required",
        "missing_foreign_keys": missing,
        "production_authority": not missing,
    }


def require_batch_schema_authority(conn: sqlite3.Connection) -> None:
    report = batch_schema_authority_report(conn)
    if report["status"] != "ready":
        raise BatchASchemaMigrationRequired(report)


def _database_authority_identity(
    conn: sqlite3.Connection,
) -> tuple[str, str]:
    rows = conn.execute("pragma database_list").fetchall()
    main_paths = [str(row[2]) for row in rows if str(row[1]) == "main"]
    if len(main_paths) != 1 or not main_paths[0]:
        raise ValueError("Batch A authority requires one file-backed main database")
    resolved = str(Path(main_paths[0]).expanduser().resolve(strict=True))
    return resolved, question_fingerprints.canonical_sha256(
        {"resolved_main_db_path": resolved}
    )


def _context_row(
    conn: sqlite3.Connection, batch_attempt_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        select
          attempt.id as batch_attempt_id,
          attempt.run_id,
          attempt.run_item_id,
          attempt.claim_generation,
          attempt.claim_token_digest_sha256,
          attempt.role,
          attempt.contract_version_index,
          attempt.semantic_attempt_index,
          attempt.status as attempt_status,
          item.effective_evidence_role,
          item.effective_evidence_role_policy_version,
          run.operation_generation,
          run.claim_token,
          run.claim_owner_pid,
          run.claim_invocation_id,
          run.status as run_status,
          run.effective_evidence_role_policy_version as run_role_policy_version,
          run.effective_evidence_role_policy_digest_sha256 as run_role_policy_digest
        from answer_contract_generation_attempts attempt
        join answer_contract_generation_run_items item
          on item.id = attempt.run_item_id and item.run_id = attempt.run_id
        join answer_contract_generation_runs run on run.id = attempt.run_id
        where attempt.id = ?
        """,
        (batch_attempt_id,),
    ).fetchone()


def _validate_claim_row(row: sqlite3.Row, claim: RunClaim) -> None:
    if any(
        (
            row["run_id"] != claim.run_id,
            int(row["operation_generation"]) != claim.operation_generation,
            row["claim_token"] != claim.claim_token,
            int(row["claim_owner_pid"] or 0) != claim.owner_pid,
            row["claim_invocation_id"] != claim.invocation_id,
            int(row["claim_generation"]) != claim.operation_generation,
            row["claim_token_digest_sha256"]
            != claim_token_digest(claim.claim_token),
        )
    ):
        raise ValueError("batch attempt does not match the current CAS claim")


def load_batch_attempt_context(
    conn: sqlite3.Connection,
    *,
    batch_attempt_id: str,
    claim: RunClaim,
    expected_role: str,
) -> BatchAttemptContext:
    if conn.in_transaction:
        raise ValueError("batch attempt must be committed before context load")
    require_batch_schema_authority(conn)
    if expected_role not in {"designer", "reviewer"}:
        raise ValueError("expected_role is invalid")
    if not isinstance(batch_attempt_id, str) or not batch_attempt_id:
        raise ValueError("batch_attempt_id must be a nonempty string")
    row = _context_row(conn, batch_attempt_id)
    if row is None:
        raise ValueError("committed batch semantic attempt does not exist")
    _validate_claim_row(row, claim)
    if row["role"] != expected_role:
        raise ValueError("batch semantic attempt role mismatch")
    if row["attempt_status"] not in {
        "reserved",
        "provider_calling",
        "accepted",
    }:
        raise ValueError("batch semantic attempt is not loadable")
    if (
        row["run_status"] != "running"
        or row["effective_evidence_role_policy_version"]
        != EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
        or row["run_role_policy_version"]
        != EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
        or row["run_role_policy_digest"]
        != EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256
        or not isinstance(row["effective_evidence_role"], str)
        or not row["effective_evidence_role"].strip()
    ):
        raise ValueError("batch attempt effective-role or run authority mismatch")
    database_path, database_identity_digest = _database_authority_identity(conn)
    context = BatchAttemptContext(
        _seal=_BATCH_ATTEMPT_CONTEXT_SEAL,
        database_path=database_path,
        database_identity_digest_sha256=database_identity_digest,
        claim_token=claim.claim_token,
        batch_attempt_id=row["batch_attempt_id"],
        run_id=row["run_id"],
        run_item_id=row["run_item_id"],
        role=row["role"],
        contract_version_index=int(row["contract_version_index"]),
        semantic_attempt_index=int(row["semantic_attempt_index"]),
        effective_evidence_role=row["effective_evidence_role"],
        effective_evidence_role_policy_version=row[
            "effective_evidence_role_policy_version"
        ],
        operation_generation=int(row["operation_generation"]),
    )
    _ISSUED_BATCH_ATTEMPT_CONTEXTS.add(context)
    return context


_BATCH_CONTEXT_STAGE_STATUSES = {
    "request": {"reserved", "provider_calling", "accepted"},
    "router_binding": {"provider_calling"},
    "agent_run_persistence": {"provider_calling"},
    "contract_persistence": {"accepted"},
}


def _require_issued_context(context: BatchAttemptContext) -> None:
    if (
        type(context) is not BatchAttemptContext
        or context._BatchAttemptContext__seal is not _BATCH_ATTEMPT_CONTEXT_SEAL
        or context not in _ISSUED_BATCH_ATTEMPT_CONTEXTS
    ):
        raise TypeError("batch attempt context is not authoritative")


def _validate_context_on_connection(
    context: BatchAttemptContext,
    conn: sqlite3.Connection,
    *,
    expected_role: str,
    stage: str,
) -> BatchAttemptContext:
    _require_issued_context(context)
    if stage not in _BATCH_CONTEXT_STAGE_STATUSES:
        raise ValueError("batch context validation stage is invalid")
    require_batch_schema_authority(conn)
    _database_path, database_identity_digest = _database_authority_identity(conn)
    if database_identity_digest != (
        context._BatchAttemptContext__database_identity_digest_sha256
    ):
        raise ValueError("actual write database identity does not match batch context")
    row = _context_row(conn, context.batch_attempt_id)
    if row is None:
        raise ValueError("batch semantic attempt disappeared")
    if any(
        (
            row["role"] != expected_role,
            context.role != expected_role,
            row["run_id"] != context.run_id,
            row["run_item_id"] != context.run_item_id,
            int(row["operation_generation"])
            != context._BatchAttemptContext__operation_generation,
            row["claim_token"] != context._BatchAttemptContext__claim_token,
            int(row["claim_generation"])
            != context._BatchAttemptContext__operation_generation,
            row["claim_token_digest_sha256"]
            != claim_token_digest(context._BatchAttemptContext__claim_token),
            row["attempt_status"] not in _BATCH_CONTEXT_STAGE_STATUSES[stage],
            row["effective_evidence_role"]
            != context.effective_evidence_role,
            row["effective_evidence_role_policy_version"]
            != context.effective_evidence_role_policy_version,
            row["run_role_policy_version"]
            != EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION,
            row["run_role_policy_digest"]
            != EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256,
            row["run_status"] != "running",
        )
    ):
        raise ValueError("batch attempt context is stale or forged")
    return context


def validate_batch_attempt_context(
    context: BatchAttemptContext,
    *,
    expected_role: str,
    stage: str,
) -> BatchAttemptContext:
    _require_issued_context(context)
    conn = sqlite3.connect(context._BatchAttemptContext__database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    try:
        return _validate_context_on_connection(
            context,
            conn,
            expected_role=expected_role,
            stage=stage,
        )
    finally:
        conn.close()


_BATCH_WRITE_SCOPE_SEAL = object()
_ISSUED_BATCH_WRITE_SCOPES: weakref.WeakSet[BatchAuthorityWriteScope] = (
    weakref.WeakSet()
)


class BatchAuthorityWriteScope:
    __slots__ = (
        "__seal",
        "connection",
        "stage",
        "context_ids",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        _seal: object,
        connection: sqlite3.Connection,
        stage: str,
        context_ids: tuple[int, ...],
    ) -> None:
        if _seal is not _BATCH_WRITE_SCOPE_SEAL:
            raise TypeError("BatchAuthorityWriteScope is opaque")
        self.__seal = _seal
        self.connection = connection
        self.stage = stage
        self.context_ids = context_ids


def require_batch_authority_write_scope(
    scope: BatchAuthorityWriteScope,
    *,
    conn: sqlite3.Connection,
    context: BatchAttemptContext,
    stage: str,
) -> None:
    if (
        type(scope) is not BatchAuthorityWriteScope
        or scope._BatchAuthorityWriteScope__seal is not _BATCH_WRITE_SCOPE_SEAL
        or scope not in _ISSUED_BATCH_WRITE_SCOPES
        or scope.connection is not conn
        or scope.stage != stage
        or id(context) not in scope.context_ids
    ):
        raise TypeError("batch authority write scope is not valid for this persistence")


def validate_completed_batch_agent_result(
    conn: sqlite3.Connection,
    context: BatchAttemptContext,
    *,
    agent_run_id: str,
    role: str,
    write_scope: BatchAuthorityWriteScope | None = None,
) -> bool:
    if role not in {"designer", "reviewer"}:
        raise ValueError("batch semantic result role is invalid")
    if write_scope is not None:
        require_batch_authority_write_scope(
            write_scope,
            conn=conn,
            context=context,
            stage="contract_persistence",
        )
    _validate_context_on_connection(
        context,
        conn,
        expected_role=role,
        stage="contract_persistence",
    )
    row = conn.execute(
        """
        select attempt.*, run.designer_prompt_digest_sha256,
               run.designer_schema_digest_sha256,
               run.designer_route_digest_sha256,
               run.reviewer_prompt_digest_sha256,
               run.reviewer_schema_digest_sha256,
               run.reviewer_route_digest_sha256,
               agent.batch_attempt_id as agent_batch_attempt_id,
               agent.agent_key as persisted_agent_key,
               agent.phase as persisted_phase,
               agent.status as persisted_agent_status,
               agent.prompt_template_sha256 as persisted_prompt_digest,
               agent.response_schema_sha256 as persisted_schema_digest,
               agent.output_digest_sha256 as persisted_output_digest,
               agent.input_refs_json as persisted_input_refs_json
        from answer_contract_generation_attempts attempt
        join answer_contract_generation_runs run on run.id = attempt.run_id
        join agent_runs agent on agent.id = attempt.agent_run_id
        where attempt.id = ? and attempt.agent_run_id = ?
        """,
        (context.batch_attempt_id, agent_run_id),
    ).fetchone()
    if row is None:
        raise ValueError("batch semantic result has no exact persisted agent run")
    expected_agent = (
        "answer_contract_designer_agent"
        if role == "designer"
        else "answer_contract_reviewer_agent"
    )
    expected_phase = (
        "answer_contract_design_v2"
        if role == "designer"
        else "answer_contract_review_v2"
    )
    prompt_column = f"{role}_prompt_digest_sha256"
    schema_column = f"{role}_schema_digest_sha256"
    route_column = f"{role}_route_digest_sha256"
    request = json.loads(row["request_json"])
    trusted = request.get("trusted_context") if isinstance(request, dict) else None
    source_refs = request.get("source_refs") if isinstance(request, dict) else None
    input_refs = json.loads(row["persisted_input_refs_json"] or "{}")
    if any(
        (
            row["status"] != "accepted",
            row["local_verdict"] != "accepted",
            row["agent_batch_attempt_id"] != context.batch_attempt_id,
            row["persisted_agent_key"] != expected_agent,
            row["persisted_phase"] != expected_phase,
            row["persisted_agent_status"] != "accepted",
            row["prompt_digest_sha256"] != row[prompt_column],
            row["schema_digest_sha256"] != row[schema_column],
            row["route_digest_sha256"] != row[route_column],
            row["persisted_prompt_digest"] != row[prompt_column],
            row["persisted_schema_digest"] != row[schema_column],
            row["output_digest_sha256"] != row["persisted_output_digest"],
            row["request_digest_sha256"] != _digest(request),
            not isinstance(trusted, dict),
            not isinstance(source_refs, dict),
            trusted.get("batch_attempt_id") != context.batch_attempt_id
            if isinstance(trusted, dict)
            else True,
            source_refs.get("batch_attempt_id") != context.batch_attempt_id
            if isinstance(source_refs, dict)
            else True,
            trusted.get("effective_evidence_role")
            != context.effective_evidence_role
            if isinstance(trusted, dict)
            else True,
            input_refs.get("batch_attempt_id") != context.batch_attempt_id,
        )
    ):
        raise ValueError("batch semantic result lineage is not exact")
    return True


@contextmanager
def batch_authority_write_scope(
    conn: sqlite3.Connection,
    *,
    contexts: tuple[tuple[str, BatchAttemptContext], ...],
    stage: str,
) -> Iterator[BatchAuthorityWriteScope]:
    if not contexts:
        raise ValueError("batch authority write scope requires context")
    savepoint_name = "ac_batch_" + uuid.uuid4().hex
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("begin immediate")
    else:
        conn.execute(f"savepoint {savepoint_name}")
    try:
        for expected_role, context in contexts:
            _require_issued_context(context)
            cursor = conn.execute(
                """
                update answer_contract_generation_runs
                set heartbeat_at = heartbeat_at
                where id = ? and operation_generation = ?
                  and claim_token = ? and status = 'running'
                """,
                (
                    context.run_id,
                    context._BatchAttemptContext__operation_generation,
                    context._BatchAttemptContext__claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("actual write connection does not hold current CAS claim")
            _validate_context_on_connection(
                context,
                conn,
                expected_role=expected_role,
                stage=stage,
            )
        scope = BatchAuthorityWriteScope(
            _seal=_BATCH_WRITE_SCOPE_SEAL,
            connection=conn,
            stage=stage,
            context_ids=tuple(id(context) for _role, context in contexts),
        )
        _ISSUED_BATCH_WRITE_SCOPES.add(scope)
        yield scope
        if owns_transaction:
            conn.commit()
        else:
            conn.execute(f"release savepoint {savepoint_name}")
    except Exception:
        if owns_transaction:
            conn.rollback()
        else:
            conn.execute(f"rollback to savepoint {savepoint_name}")
            conn.execute(f"release savepoint {savepoint_name}")
        raise


@contextmanager
def bind_batch_attempt_transport(
    context: BatchAttemptContext,
    observer: model_router.StructuredTransportLifecycleObserver,
    *,
    wall_deadline_monotonic: float | None = None,
) -> Iterator[model_router.StructuredTransportLifecycleBinding]:
    validated = validate_batch_attempt_context(
        context,
        expected_role=context.role,
        stage="router_binding",
    )
    binding = model_router._new_structured_transport_lifecycle_binding(
        batch_attempt_id=validated.batch_attempt_id,
        observer=observer,
        wall_deadline_monotonic=wall_deadline_monotonic,
    )
    with model_router.bind_structured_transport_lifecycle(binding) as bound:
        yield bound


def stale_after_seconds(max_route_timeout_seconds: float) -> float:
    if (
        isinstance(max_route_timeout_seconds, bool)
        or not isinstance(max_route_timeout_seconds, (int, float))
        or max_route_timeout_seconds <= 0
    ):
        raise ValueError("max_route_timeout_seconds must be positive")
    return float(
        max(
            300,
            math.ceil(
                max_route_timeout_seconds
                + MAX_RETRY_AFTER_SECONDS
                + HEARTBEAT_INTERVAL_SECONDS
            ),
        )
    )


def canonical_db_lock_path(conn: sqlite3.Connection) -> Path:
    rows = conn.execute("pragma database_list").fetchall()
    main_paths = [str(row[2]) for row in rows if str(row[1]) == "main"]
    if len(main_paths) != 1 or not main_paths[0]:
        raise ValueError("Batch A requires one file-backed main SQLite database")
    configured_path = Path(main_paths[0]).expanduser()
    if configured_path.is_symlink():
        raise ValueError("Batch A main SQLite path must not be a symlink")
    db_path = configured_path.resolve(strict=True)
    if not db_path.is_file():
        raise ValueError("Batch A main SQLite path must be a regular file")
    lock_name = question_fingerprints.canonical_sha256(
        {"resolved_main_db_path": str(db_path)}
    )
    return db_path.parent / ".answer-contract-v2-locks" / f"{lock_name}.lock"


def acquire_canonical_db_run_lock(
    conn: sqlite3.Connection,
    *,
    hooks: BatchATestHooks | None = None,
) -> CanonicalDBRunLock:
    active_hooks = hooks or BatchATestHooks()
    lock_path = canonical_db_lock_path(conn)
    lock_root = lock_path.parent
    if lock_root.exists():
        root_stat = lock_root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or lock_root.is_symlink():
            raise ValueError("Batch A lock root must be a real directory")
        if stat.S_IMODE(root_stat.st_mode) & 0o022:
            raise ValueError("Batch A lock root must not be group/world writable")
    else:
        lock_root.mkdir(mode=0o700, parents=False)

    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = active_hooks.open_file(str(lock_path), flags, 0o600)
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("Batch A lock file must be regular")
        active_hooks.chmod_file(fd, 0o600)
        active_hooks.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        active_hooks.close_file(fd)
        raise BatchARunLocked(lock_path) from exc
    except Exception:
        active_hooks.close_file(fd)
        raise
    return CanonicalDBRunLock(path=lock_path, fd=fd, hooks=active_hooks)


def new_batch_attempt_id(*, hooks: BatchATestHooks | None = None) -> str:
    value = (hooks or BatchATestHooks()).new_batch_attempt_id()
    if not isinstance(value, str) or not value.startswith("ACBA-"):
        raise ValueError("batch_attempt_id hook returned an invalid value")
    return value


def skeleton_blocked_report(operation: str) -> dict[str, Any]:
    return {
        "mode": "answer_contract_v2_batch_a_skeleton",
        "operation": operation,
        "status": "skeleton_blocked",
        "error": SKELETON_BLOCKER,
        "production_authority": False,
        "activation_eligible": False,
        "model_calls": 0,
        "provider_attempts": 0,
        "receipt": None,
    }


def _raise_skeleton(operation: str) -> None:
    raise BatchASkeletonBlocked(operation)


def _validate_canary_limits(
    *,
    model_call_cap: int,
    provider_attempt_cap: int,
    max_items: int,
    invocation_wall_seconds: float,
) -> None:
    integer_limits = (
        (model_call_cap, CANARY_HARD_MODEL_CALL_CAP, "model_call_cap"),
        (
            provider_attempt_cap,
            CANARY_HARD_PROVIDER_ATTEMPT_CAP,
            "provider_attempt_cap",
        ),
    )
    for value, hard_maximum, field_name in integer_limits:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > hard_maximum
        ):
            raise ValueError(f"{field_name} is outside the Batch A hard limit")
    if max_items != CANARY_ITEM_COUNT:
        raise ValueError("Batch A max_items must equal forty")
    if (
        isinstance(invocation_wall_seconds, bool)
        or not isinstance(invocation_wall_seconds, (int, float))
        or invocation_wall_seconds <= 0
        or invocation_wall_seconds > CANARY_HARD_WALL_SECONDS
    ):
        raise ValueError("invocation_wall_seconds is outside the Batch A hard limit")


def _digest(value: Any) -> str:
    return question_fingerprints.canonical_sha256(value)


def _now_iso(hooks: BatchATestHooks | None = None) -> str:
    value = (hooks or BatchATestHooks()).wall_time()
    return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()


def _iso_timestamp(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _stop_is_requested(hooks: BatchATestHooks | None) -> bool:
    return bool((hooks or BatchATestHooks()).stop_requested())


def _heartbeat(
    conn: sqlite3.Connection,
    claim: RunClaim,
    *,
    hooks: BatchATestHooks | None,
    force: bool = False,
) -> None:
    active_hooks = hooks or BatchATestHooks()
    now_epoch = float(active_hooks.wall_time())
    row = conn.execute(
        "select heartbeat_at, heartbeat_interval_seconds from answer_contract_generation_runs where id = ?",
        (claim.run_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Batch A heartbeat run disappeared")
    if not force and now_epoch - _iso_timestamp(row["heartbeat_at"]) < float(
        row["heartbeat_interval_seconds"]
    ):
        return
    now = datetime.fromtimestamp(now_epoch, tz=timezone.utc).isoformat()
    with _immediate_transaction(conn):
        cursor = conn.execute(
            """
            update answer_contract_generation_runs
            set heartbeat_at = ?, updated_at = ?
            where id = ? and operation_generation = ? and claim_token = ?
              and status in ('preflight_running','running')
            """,
            (
                now,
                now,
                claim.run_id,
                claim.operation_generation,
                claim.claim_token,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Batch A heartbeat lost its CAS claim")


def _interrupt_claimed_run(
    conn: sqlite3.Connection,
    claim: RunClaim,
    *,
    reason_code: str,
    hooks: BatchATestHooks | None,
) -> dict[str, Any]:
    now = _now_iso(hooks)
    with _immediate_transaction(conn):
        cursor = conn.execute(
            """
            update answer_contract_generation_runs
            set status = 'interrupted', heartbeat_at = ?, interrupted_at = ?,
                last_error_class = 'interrupted', last_error = ?, updated_at = ?
            where id = ? and operation_generation = ? and claim_token = ?
              and status in ('preflight_running','running')
            """,
            (
                now,
                now,
                reason_code,
                now,
                claim.run_id,
                claim.operation_generation,
                claim.claim_token,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Batch A interruption lost its CAS claim")
    counters = conn.execute(
        "select model_calls, provider_attempts from answer_contract_generation_runs where id = ?",
        (claim.run_id,),
    ).fetchone()
    return {
        "status": "interrupted",
        "run_id": claim.run_id,
        "reason_code": reason_code,
        "model_calls": int(counters["model_calls"]),
        "provider_attempts": int(counters["provider_attempts"]),
        "production_authority": False,
        "activation_eligible": False,
        "receipt": None,
    }


@contextmanager
def _immediate_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    savepoint = "ac_batch_state_" + uuid.uuid4().hex
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("begin immediate")
    else:
        conn.execute(f"savepoint {savepoint}")
    try:
        yield
        if owns_transaction:
            conn.commit()
        else:
            conn.execute(f"release savepoint {savepoint}")
    except Exception:
        if owns_transaction:
            conn.rollback()
        else:
            conn.execute(f"rollback to savepoint {savepoint}")
            conn.execute(f"release savepoint {savepoint}")
        raise


def _valid_digest_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    claimed = payload.get("receipt_digest_sha256")
    if not isinstance(claimed, str):
        return False
    body = {
        key: value
        for key, value in payload.items()
        if key != "receipt_digest_sha256"
    }
    return claimed == _digest(body)


def _route_commitment(route: model_router.ModelRoute) -> dict[str, Any]:
    status = model_router.route_status(route).as_dict()
    return {
        "agent_key": route.agent_key,
        "task": route.task,
        "provider": route.provider,
        "model": route.model,
        "model_alias": route.model_alias,
        "base_url": route.base_url,
        "timeout_seconds": float(route.timeout_seconds),
        "model_params": dict(route.model_params),
        "enabled": bool(route.enabled),
        "json_modes": status["json_modes"],
        "endpoints": status["endpoints"],
    }


def _validate_review_candidate_serialization(
    conn: sqlite3.Connection, bank_version: str
) -> None:
    from . import db

    rows = conn.execute(
        """
        select qrr.id, qrr.candidate_sha256, qi.id as question_id,
               qi.item_version, qi.raw_json
        from question_review_records qrr
        join question_items qi
          on qi.id = qrr.question_id and qi.item_version = qrr.item_version
        where qi.item_version = ?
          and qrr.review_status = 'approved'
          and qrr.active_eligible = 1
        order by qrr.id
        """,
        (bank_version,),
    ).fetchall()
    for row in rows:
        raw_json = str(row["raw_json"])
        candidate = db.json_load(raw_json, None)
        if not isinstance(candidate, dict):
            raise ValueError("active question candidate JSON is invalid")
        canonical_digest = _digest(candidate)
        stored_digest = str(row["candidate_sha256"])
        legacy_digest = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        if stored_digest not in {legacy_digest, canonical_digest}:
            raise ValueError("question review candidate digest is not canonical or legacy-exact")


def _plan_authority(
    conn: sqlite3.Connection,
    project_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    del project_root
    from . import (
        answer_contract_activation,
        answer_contract_generation_v2,
        assessment_policy,
        db,
        internal_agents,
    )

    ledger = answer_contract_activation._active_ledger(conn)
    bank_version = str(ledger["question_bank_version"])
    _validate_review_candidate_serialization(conn, bank_version)
    rows = conn.execute(
        """
        select qi.*, qrr.id as active_review_record_id,
               qrr.candidate_sha256 as active_candidate_sha256,
               qrr.reviewer_run_id as active_reviewer_run_id,
               ar.status as active_reviewer_run_status
        from question_items qi
        join question_review_records qrr
          on qrr.question_id = qi.id
         and qrr.item_version = qi.item_version
         and qrr.review_status = 'approved'
         and qrr.active_eligible = 1
        join agent_runs ar on ar.id = qrr.reviewer_run_id
        where qi.item_version = ?
        order by qi.node_id, qi.id, qrr.id
        """,
        (bank_version,),
    ).fetchall()
    question_rows = []
    seen_question_ids = set()
    for row in rows:
        question = db.row_to_question(row)
        review_record_id = str(question.pop("active_review_record_id", ""))
        question.pop("active_candidate_sha256", "")
        reviewer_run_id = str(question.pop("active_reviewer_run_id", ""))
        reviewer_run_status = str(question.pop("active_reviewer_run_status", ""))
        if question["id"] in seen_question_ids:
            raise ValueError("question has multiple active generation review records")
        seen_question_ids.add(question["id"])
        if (
            not review_record_id
            or not reviewer_run_id
            or reviewer_run_status != "accepted"
        ):
            raise ValueError(
                f"question generation review lineage is invalid: {question['id']}"
            )
        question["_answer_contract_generation_required"] = True
        question_rows.append((question, review_record_id))
    if len(question_rows) != 1120:
        raise ValueError("Batch A requires the exact 1120-question active bank")
    authoritative = []
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for question, review_record_id in question_rows:
        raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
        role = effective_evidence_role(raw)
        item = {
            "question_id": question["id"],
            "item_version": question["item_version"],
            "question_digest_sha256": answer_contract_generation_v2._question_digest(
                question
            ),
            "node_id": question["node_id"],
            "kind": question["kind"],
            "effective_evidence_role": role,
            "effective_evidence_role_policy_version": (
                EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
            ),
            "review_record_id": review_record_id,
        }
        authoritative.append(item)
        by_kind.setdefault(question["kind"], []).append(item)
    if set(by_kind) != set(assessment_policy.ACTIVE_QUESTION_KINDS):
        raise ValueError("Batch A requires all twenty active question kinds")

    design_contract, review_contract = answer_contract_generation_v2._contract_versions()
    design_route = model_router.answer_contract_design_v2_route()
    review_route = model_router.answer_contract_review_v2_route()
    profile_commitments = []
    questions_by_id = {question["id"]: question for question, _ in question_rows}
    for kind in sorted(by_kind):
        sample = questions_by_id[sorted(by_kind[kind], key=lambda row: row["question_id"])[0]["question_id"]]
        skeleton = assessment_policy.build_contract_skeleton_v2(sample)
        profile_commitments.append(
            {
                "kind": kind,
                "profile_version": skeleton["profile_version"],
                "profile_digest_sha256": _digest(skeleton),
            }
        )
    prompt_schema = {
        "designer_prompt_digest_sha256": internal_agents.file_sha256(
            internal_agents.prompt_path_for_contract(design_contract)
        ),
        "designer_schema_digest_sha256": internal_agents.canonical_json_sha256(
            design_contract["response_schema"]
        ),
        "reviewer_prompt_digest_sha256": internal_agents.file_sha256(
            internal_agents.prompt_path_for_contract(review_contract)
        ),
        "reviewer_schema_digest_sha256": internal_agents.canonical_json_sha256(
            review_contract["response_schema"]
        ),
    }
    authority = {
        "ledger_id": str(ledger["id"]),
        "bank_version": bank_version,
        "manifest_sha256": str(ledger.get("manifest_sha256") or ""),
        "graph_version": str(ledger.get("graph_version") or ""),
        "selection_source_digest_sha256": _digest(
            sorted(
                authoritative,
                key=lambda row: (
                    row["kind"],
                    row["node_id"],
                    row["effective_evidence_role"],
                    row["question_id"],
                    row["item_version"],
                ),
            )
        ),
        "generator_policy_digest_sha256": _digest(
            {
                "generator_version": answer_contract_generation_v2.GENERATOR_VERSION,
                "max_contract_versions": answer_contract_generation_v2.MAX_CONTRACT_VERSIONS,
                "max_semantic_attempts": answer_contract_generation_v2.MAX_ATTEMPTS,
                "profiles": profile_commitments,
            }
        ),
        "designer_route": _route_commitment(design_route),
        "reviewer_route": _route_commitment(review_route),
        **prompt_schema,
    }
    return authority, authoritative, by_kind


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise TypeError("Batch A plan must be a mapping")
    values = deepcopy(dict(plan))
    claimed = values.pop("plan_digest_sha256", None)
    if claimed != _digest(values):
        raise ValueError("Batch A plan digest is invalid")
    if values.get("run_kind") != RUN_KIND_CANARY:
        raise ValueError("Batch A plan kind is invalid")
    items = values.get("items")
    if not isinstance(items, list) or len(items) != CANARY_ITEM_COUNT:
        raise ValueError("Batch A plan must contain exactly forty items")
    return dict(plan)


def build_v2_batch_plan(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    run_kind: str,
    canary_receipt_path: Path | None = None,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    del canary_receipt_path, hooks
    if run_kind == RUN_KIND_FULL:
        raise BatchASkeletonBlocked("batch_b_out_of_scope")
    if run_kind != RUN_KIND_CANARY:
        raise ValueError("run_kind must be canary40 for Batch A")
    require_batch_schema_authority(conn)
    authority, authoritative, by_kind = _plan_authority(conn, project_root)
    selected = []
    selection_audit = []
    ordinal = 0
    for kind in sorted(by_kind):
        candidates = sorted(
            by_kind[kind],
            key=lambda row: (
                row["node_id"],
                row["effective_evidence_role"],
                row["question_id"],
                row["item_version"],
            ),
        )
        pairs = sorted(
            itertools.combinations(candidates, 2),
            key=lambda pair: (
                -(pair[0]["node_id"] != pair[1]["node_id"]),
                -(
                    pair[0]["effective_evidence_role"]
                    != pair[1]["effective_evidence_role"]
                ),
                tuple(
                    (
                        row["node_id"],
                        row["effective_evidence_role"],
                        row["question_id"],
                        row["item_version"],
                    )
                    for row in pair
                ),
            ),
        )
        if not pairs:
            raise ValueError(f"Batch A kind has fewer than two questions: {kind}")
        pair = pairs[0]
        pair_rows = sorted(
            pair,
            key=lambda row: (
                row["node_id"],
                row["effective_evidence_role"],
                row["question_id"],
                row["item_version"],
            ),
        )
        selection_audit.append(
            {
                "kind": kind,
                "candidate_set_digest_sha256": _digest(candidates),
                "candidate_count": len(candidates),
                "different_node_available": any(
                    left["node_id"] != right["node_id"]
                    for left, right in itertools.combinations(candidates, 2)
                ),
                "different_effective_evidence_role_available": any(
                    left["effective_evidence_role"]
                    != right["effective_evidence_role"]
                    for left, right in itertools.combinations(candidates, 2)
                ),
                "selected_question_ids": [row["question_id"] for row in pair_rows],
            }
        )
        for row in pair_rows:
            selected.append({"ordinal": ordinal, **deepcopy(row)})
            ordinal += 1
    plan_body = {
        "run_schema_version": RUN_SCHEMA_VERSION,
        "run_kind": RUN_KIND_CANARY,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "effective_evidence_role_policy_version": (
            EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
        ),
        "effective_evidence_role_policy_digest_sha256": (
            EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256
        ),
        "expected_item_count": CANARY_ITEM_COUNT,
        "active_bank_question_count": len(authoritative),
        "items": selected,
        "selection_audit": selection_audit,
        **authority,
        "designer_route_digest_sha256": _digest(authority["designer_route"]),
        "reviewer_route_digest_sha256": _digest(authority["reviewer_route"]),
    }
    return {**plan_body, "plan_digest_sha256": _digest(plan_body)}


def _require_current_claim(
    conn: sqlite3.Connection,
    claim: RunClaim,
    *,
    allowed_statuses: set[str],
) -> sqlite3.Row:
    row = conn.execute(
        "select * from answer_contract_generation_runs where id = ?",
        (claim.run_id,),
    ).fetchone()
    if not row or any(
        (
            int(row["operation_generation"]) != claim.operation_generation,
            row["claim_token"] != claim.claim_token,
            int(row["claim_owner_pid"] or 0) != claim.owner_pid,
            row["claim_invocation_id"] != claim.invocation_id,
            row["status"] not in allowed_statuses,
        )
    ):
        raise ValueError("Batch A CAS claim is not current")
    return row


def _claim_from_row(row: sqlite3.Row | Mapping[str, Any]) -> RunClaim:
    values = dict(row)
    return RunClaim(
        run_id=values["id"],
        operation_generation=int(values["operation_generation"]),
        claim_token=str(values["claim_token"]),
        owner_pid=int(values["claim_owner_pid"]),
        invocation_id=str(values["claim_invocation_id"]),
        claimed_at=str(values["claimed_at"]),
        heartbeat_at=str(values["heartbeat_at"]),
    )


def preflight_v2_canary(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    run_id: str,
    claim: RunClaim,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    from . import answer_contract_activation, answer_contract_generation_v2

    if run_id != claim.run_id:
        raise ValueError("Batch A preflight run identity mismatch")
    rebuilt = build_v2_batch_plan(conn, project_root, run_kind=RUN_KIND_CANARY)
    oracle_blockers = []
    policy_blockers = []
    _authority, authoritative_items, _by_kind = _plan_authority(
        conn, project_root
    )
    authoritative_ids = {item["question_id"] for item in authoritative_items}
    for question_id in sorted(
        answer_contract_activation.KNOWN_MISBOUND_IDS.intersection(authoritative_ids)
    ):
        oracle_blockers.append(
            {
                "owner": "question_bank",
                "reason_code": "known_misbound_oracle",
                "question_id": question_id,
            }
        )
    for question in authoritative_items:
        for reason_code in answer_contract_generation_v2.v2_scoring_policy_activation_blockers(
            {
                "question_id": question["question_id"],
                "question_bank_version": rebuilt["bank_version"],
            }
        ):
            policy_blockers.append(
                {
                    "owner": "assessment_policy",
                    "reason_code": reason_code,
                    "question_id": question["question_id"],
                    "kind": question["kind"],
                }
            )
    for role, route_key in (
        ("designer", "designer_route"),
        ("reviewer", "reviewer_route"),
    ):
        if not rebuilt[route_key]["enabled"]:
            policy_blockers.append(
                {
                    "owner": "model_configuration",
                    "reason_code": f"{role}_model_not_configured",
                }
            )
    ordered_active_items = sorted(
        authoritative_items,
        key=lambda item: (
            item["question_id"],
            item["item_version"],
        ),
    )
    active_bank_set_digest = _digest(ordered_active_items)
    payload = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "run_id": run_id,
        "plan_digest_sha256": rebuilt["plan_digest_sha256"],
        "active_bank_set_digest_sha256": active_bank_set_digest,
        "oracle_policy_version": ORACLE_POLICY_VERSION,
        "oracle_blockers": oracle_blockers,
        "deterministic_blocker_registry_digest_sha256": _digest(
            {
                "policy_version": ORACLE_POLICY_VERSION,
                "known_misbound_question_ids": sorted(
                    answer_contract_activation.KNOWN_MISBOUND_IDS
                ),
            }
        ),
        "scanned_active_question_count": len(ordered_active_items),
        "scanned_active_question_set_digest_sha256": active_bank_set_digest,
        "scoring_policy_digest_sha256": _digest(
            {
                "policy_version": SCORING_POLICY_VERSION,
                "question_ids": sorted(
                    answer_contract_generation_v2.V12_SCORING_POLICY_GATE_QUESTION_IDS
                ),
                "bank_version": "2026-07-08.bank.v11",
                "reason_code": (
                    "v12_scoring_policy_gate_required_for_clock_verification"
                ),
            }
        ),
        "policy_blockers": policy_blockers,
        "effective_evidence_role_policy_version": (
            EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
        ),
        "effective_evidence_role_policy_digest_sha256": (
            EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256
        ),
        "effective_evidence_role_set_digest_sha256": _digest(
            [
                {
                    "question_id": item["question_id"],
                    "item_version": item["item_version"],
                    "effective_evidence_role": item[
                        "effective_evidence_role"
                    ],
                    "effective_evidence_role_policy_version": item[
                        "effective_evidence_role_policy_version"
                    ],
                }
                for item in ordered_active_items
            ]
        ),
        "selection_audit": deepcopy(rebuilt["selection_audit"]),
        "preflight_pass": not oracle_blockers and not policy_blockers,
    }
    preflight_digest = _digest(payload)
    payload_json = question_fingerprints.canonical_json(payload)
    now = _now_iso(hooks)
    with _immediate_transaction(conn):
        row = _require_current_claim(
            conn,
            claim,
            allowed_statuses={"preflight_running", "running"},
        )
        if row["plan_digest_sha256"] != rebuilt["plan_digest_sha256"]:
            raise ValueError("Batch A preflight plan changed after claim")
        status = "running" if payload["preflight_pass"] else "completed_blocked"
        conn.execute(
            """
            update answer_contract_generation_runs
            set preflight_status = ?, preflight_payload_json = ?,
                preflight_digest_sha256 = ?, status = ?,
                last_error_class = ?, last_error = ?, updated_at = ?,
                completed_at = case when ? = 'completed_blocked' then ? else completed_at end
            where id = ? and operation_generation = ? and claim_token = ?
            """,
            (
                "passed" if payload["preflight_pass"] else "blocked",
                payload_json,
                preflight_digest,
                status,
                "" if payload["preflight_pass"] else "preflight_blocked",
                json.dumps(
                    oracle_blockers + policy_blockers,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
                status,
                now,
                claim.run_id,
                claim.operation_generation,
                claim.claim_token,
            ),
        )
    return {
        "status": status,
        "run_id": run_id,
        "preflight_digest_sha256": preflight_digest,
        "preflight": payload,
        "blockers": oracle_blockers + policy_blockers,
        "model_calls": 0,
        "provider_attempts": 0,
        "production_authority": False,
        "activation_eligible": False,
        "receipt": None,
    }


def _persisted_preflight(run: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.loads(str(run.get("preflight_payload_json") or "{}"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != PREFLIGHT_SCHEMA_VERSION
        or payload.get("run_id") != run.get("id")
        or payload.get("plan_digest_sha256") != run.get("plan_digest_sha256")
        or _digest(payload) != run.get("preflight_digest_sha256")
    ):
        raise ValueError("Batch A persisted preflight authority is invalid")
    return payload


def _provider_attempt_rows(
    conn: sqlite3.Connection, batch_attempt_id: str
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            select * from answer_contract_generation_provider_attempts
            where batch_attempt_id = ? order by candidate_ordinal
            """,
            (batch_attempt_id,),
        ).fetchall()
    ]


def _has_exact_provider_response_chain(
    conn: sqlite3.Connection, batch_attempt_id: str
) -> bool:
    rows = _provider_attempt_rows(conn, batch_attempt_id)
    return bool(rows) and any(
        row["status"] == "response_received"
        and isinstance(row.get("response_digest_sha256"), str)
        and bool(row["response_digest_sha256"])
        and bool(row.get("call_started_at"))
        and bool(row.get("response_at"))
        and bool(row.get("finished_at"))
        for row in rows
    )


def _canonical_provider_chain(
    conn: sqlite3.Connection,
    attempt: Mapping[str, Any],
    *,
    agent_output_digest_sha256: str,
    agent_run_authority: Mapping[str, Any],
) -> dict[str, Any]:
    request = json.loads(str(attempt.get("request_json") or "{}"))
    if (
        not isinstance(request, dict)
        or attempt.get("request_digest_sha256") != _digest(request)
        or not isinstance(request.get("source_refs"), dict)
        or not agent_output_digest_sha256
    ):
        raise ValueError("provider chain semantic request authority is invalid")
    rows = _provider_attempt_rows(conn, str(attempt["id"]))
    if not rows or not _has_exact_provider_response_chain(conn, str(attempt["id"])):
        raise ValueError("provider chain has no exact response_received boundary")
    ordinals = [int(row["candidate_ordinal"]) for row in rows]
    if len(set(ordinals)) != len(ordinals) or any(value < 0 for value in ordinals):
        raise ValueError("provider chain candidate ordinals are invalid")
    provider_attempts = [
        {
            "provider_attempt_id": row["id"],
            "candidate_ordinal": int(row["candidate_ordinal"]),
            "endpoint": row["endpoint"],
            "structured_json_mode": row["structured_json_mode"],
            "request_digest_sha256": row["request_digest_sha256"],
            "status": row["status"],
            "http_status": row["http_status"],
            "retry_after_seconds": row["retry_after_seconds"],
            "response_digest_sha256": row["response_digest_sha256"],
            "error_class": row["error_class"],
            "call_started_at": row["call_started_at"],
            "response_at": row["response_at"],
            "finished_at": row["finished_at"],
        }
        for row in rows
    ]
    body = {
        "schema_version": PROVIDER_CHAIN_SCHEMA_VERSION,
        "batch_attempt_id": attempt["id"],
        "role": attempt["role"],
        "route_digest_sha256": attempt["route_digest_sha256"],
        "semantic_request_digest_sha256": attempt["request_digest_sha256"],
        "request_source_refs_digest_sha256": _digest(request["source_refs"]),
        "agent_output_digest_sha256": agent_output_digest_sha256,
        "agent_run_authority": deepcopy(dict(agent_run_authority)),
        "provider_attempts": provider_attempts,
    }
    return {**body, "provider_chain_digest_sha256": _digest(body)}


def _agent_and_provider_commitment(
    conn: sqlite3.Connection,
    attempt: Mapping[str, Any],
    agent: Mapping[str, Any],
) -> dict[str, Any]:
    from . import internal_agents, semantic_agents

    run = conn.execute(
        "select * from answer_contract_generation_runs where id = ?",
        (attempt["run_id"],),
    ).fetchone()
    if run is None:
        raise ValueError("orphan semantic run authority is missing")
    expected_agent = (
        "answer_contract_designer_agent"
        if attempt["role"] == "designer"
        else "answer_contract_reviewer_agent"
    )
    expected_phase = (
        "answer_contract_design_v2"
        if attempt["role"] == "designer"
        else "answer_contract_review_v2"
    )
    expected_trigger = (
        "answer_contract_generation_v2"
        if attempt["role"] == "designer"
        else "answer_contract_review_v2"
    )
    route = (
        model_router.answer_contract_design_v2_route()
        if attempt["role"] == "designer"
        else model_router.answer_contract_review_v2_route()
    )
    contract = internal_agents.load_contract_for_agent_version(
        expected_agent, "v2"
    )
    request = json.loads(str(attempt["request_json"] or "{}"))
    trusted = request.get("trusted_context") if isinstance(request, dict) else None
    source_refs = request.get("source_refs") if isinstance(request, dict) else None
    input_refs = json.loads(str(agent.get("input_refs_json") or "{}"))
    output = json.loads(str(agent.get("output_json") or "{}"))
    model_params = json.loads(str(agent.get("model_params_json") or "{}"))
    validation_errors = json.loads(
        str(agent.get("validation_errors_json") or "[]")
    )
    confidence = agent.get("confidence")
    error_reason = agent.get("error_reason")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not isinstance(validation_errors, list)
        or not all(isinstance(value, str) for value in validation_errors)
        or not isinstance(error_reason, str)
    ):
        raise ValueError("agent lineage outcome metadata is malformed")
    agent_run_authority = {
        "id": agent.get("id"),
        "batch_attempt_id": agent.get("batch_attempt_id"),
        "agent_key": agent.get("agent_key"),
        "engine_type": agent.get("engine_type"),
        "session_id": agent.get("session_id"),
        "phase": agent.get("phase"),
        "trigger": agent.get("trigger"),
        "input_refs_json": agent.get("input_refs_json"),
        "input_digest_sha256": agent.get("input_digest_sha256"),
        "provider_mode": agent.get("provider_mode"),
        "route_digest_sha256": agent.get("route_digest_sha256"),
        "semantic_request_digest_sha256": agent.get(
            "semantic_request_digest_sha256"
        ),
        "request_source_refs_digest_sha256": agent.get(
            "request_source_refs_digest_sha256"
        ),
        "prompt_version_id": agent.get("prompt_version_id"),
        "prompt_template_sha256": agent.get("prompt_template_sha256"),
        "rendered_prompt_sha256": agent.get("rendered_prompt_sha256"),
        "model_provider": agent.get("model_provider"),
        "model_name": agent.get("model_name"),
        "model_alias": agent.get("model_alias"),
        "model_params_json": agent.get("model_params_json"),
        "response_schema_version": agent.get("response_schema_version"),
        "response_schema_sha256": agent.get("response_schema_sha256"),
        "status": agent.get("status"),
        "confidence": float(confidence),
        "output_json": agent.get("output_json"),
        "output_digest_sha256": agent.get("output_digest_sha256"),
        "validation_errors_json": agent.get("validation_errors_json"),
        "error_reason": error_reason,
        "created_at": agent.get("created_at"),
    }
    prompt_column = f"{attempt['role']}_prompt_digest_sha256"
    schema_column = f"{attempt['role']}_schema_digest_sha256"
    route_column = f"{attempt['role']}_route_digest_sha256"
    try:
        request_object = semantic_agents.SemanticAgentRequest(
            agent_key=request["agent_key"],
            phase=request["phase"],
            trusted_context=deepcopy(request["trusted_context"]),
            untrusted_payload=deepcopy(request["untrusted_payload"]),
            provider_mode=request["provider_mode"],
            source_refs=deepcopy(request["source_refs"]),
            contract_version_suffix=request["contract_version_suffix"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("agent lineage semantic request is malformed") from exc
    expected_prompt_digest = internal_agents.file_sha256(
        internal_agents.prompt_path_for_contract(contract)
    )
    expected_schema_digest = internal_agents.canonical_json_sha256(
        contract["response_schema"]
    )
    expected_rendered_prompt_digest = (
        semantic_agents.rendered_prompt_sha256_for_request(request_object)
    )
    if any(
        (
            attempt["request_digest_sha256"] != _digest(request),
            attempt["prompt_digest_sha256"] != run[prompt_column],
            attempt["schema_digest_sha256"] != run[schema_column],
            attempt["route_digest_sha256"] != run[route_column],
            agent.get("batch_attempt_id") != attempt["id"],
            agent.get("agent_key") != expected_agent,
            agent.get("phase") != expected_phase,
            agent.get("trigger") != expected_trigger,
            agent.get("engine_type") != "internal_learning_agent",
            agent.get("status") != "accepted",
            agent.get("provider_mode") != "live_model",
            agent.get("model_provider") != route.provider,
            agent.get("model_name") != route.model,
            agent.get("model_alias") != route.model_alias,
            model_params != dict(route.model_params),
            agent.get("prompt_version_id") != contract["prompt_version_id"],
            agent.get("prompt_template_sha256") != expected_prompt_digest,
            agent.get("prompt_template_sha256") != attempt["prompt_digest_sha256"],
            agent.get("rendered_prompt_sha256")
            != expected_rendered_prompt_digest,
            agent.get("response_schema_version")
            != contract["response_schema_version"],
            agent.get("response_schema_sha256") != expected_schema_digest,
            agent.get("response_schema_sha256") != attempt["schema_digest_sha256"],
            agent.get("input_digest_sha256") != _digest(input_refs),
            agent.get("output_digest_sha256") != _digest(output),
            not isinstance(trusted, dict),
            not isinstance(source_refs, dict),
            trusted.get("batch_attempt_id") != attempt["id"]
            if isinstance(trusted, dict)
            else True,
            source_refs.get("batch_attempt_id") != attempt["id"]
            if isinstance(source_refs, dict)
            else True,
            input_refs.get("batch_attempt_id") != attempt["id"],
            any(
                input_refs.get(key) != value
                for key, value in source_refs.items()
            )
            if isinstance(source_refs, dict)
            else True,
        )
    ):
        raise ValueError("orphan semantic agent lineage is not exact")
    provider_chain = _canonical_provider_chain(
        conn,
        attempt,
        agent_output_digest_sha256=str(agent["output_digest_sha256"]),
        agent_run_authority=agent_run_authority,
    )
    body = {
        "schema_version": AGENT_LINEAGE_SCHEMA_VERSION,
        "batch_attempt_id": attempt["id"],
        "role": attempt["role"],
        "provider_mode": "live_model",
        "model_provider": route.provider,
        "model_name": route.model,
        "model_alias": route.model_alias,
        "model_params": dict(route.model_params),
        "trigger": expected_trigger,
        "agent_key": expected_agent,
        "phase": expected_phase,
        "prompt_version_id": contract["prompt_version_id"],
        "prompt_template_sha256": expected_prompt_digest,
        "rendered_prompt_sha256": expected_rendered_prompt_digest,
        "response_schema_version": contract["response_schema_version"],
        "response_schema_sha256": expected_schema_digest,
        "route_digest_sha256": attempt["route_digest_sha256"],
        "semantic_request": request,
        "semantic_request_digest_sha256": attempt["request_digest_sha256"],
        "source_refs": deepcopy(source_refs),
        "source_refs_digest_sha256": _digest(source_refs),
        "input_refs": input_refs,
        "input_refs_digest_sha256": _digest(input_refs),
        "output": output,
        "output_digest_sha256": agent["output_digest_sha256"],
        "confidence": float(confidence),
        "validation_errors": validation_errors,
        "error_reason": error_reason,
        "agent_run_authority": deepcopy(agent_run_authority),
        "provider_chain": provider_chain,
        "provider_chain_digest_sha256": provider_chain[
            "provider_chain_digest_sha256"
        ],
    }
    lineage = {**body, "agent_lineage_digest_sha256": _digest(body)}
    return {
        "request_source_refs_digest_sha256": provider_chain[
            "request_source_refs_digest_sha256"
        ],
        "agent_input_refs_digest_sha256": _digest(input_refs),
        "provider_chain": provider_chain,
        "agent_lineage": lineage,
    }


def _persist_agent_provider_commitment(
    conn: sqlite3.Connection,
    attempt: Mapping[str, Any],
    agent: Mapping[str, Any],
) -> dict[str, Any]:
    commitment = _agent_and_provider_commitment(conn, attempt, agent)
    chain = commitment["provider_chain"]
    lineage = commitment["agent_lineage"]
    existing_lineage_digest = str(
        attempt.get("agent_lineage_digest_sha256") or ""
    )
    if existing_lineage_digest:
        stored_lineage = json.loads(
            str(attempt.get("agent_lineage_payload_json") or "{}")
        )
        if any(
            (
                stored_lineage != lineage,
                existing_lineage_digest
                != lineage["agent_lineage_digest_sha256"],
                str(agent.get("agent_lineage_digest_sha256") or "")
                != lineage["agent_lineage_digest_sha256"],
            )
        ):
            raise ValueError("complete agent lineage commitment changed")
    conn.execute(
        """
        update answer_contract_generation_attempts
        set request_source_refs_digest_sha256 = ?,
            agent_input_refs_digest_sha256 = ?,
            provider_chain_payload_json = ?, provider_chain_digest_sha256 = ?,
            agent_lineage_payload_json = ?, agent_lineage_digest_sha256 = ?
        where id = ?
        """,
        (
            commitment["request_source_refs_digest_sha256"],
            commitment["agent_input_refs_digest_sha256"],
            question_fingerprints.canonical_json(chain),
            chain["provider_chain_digest_sha256"],
            question_fingerprints.canonical_json(lineage),
            lineage["agent_lineage_digest_sha256"],
            attempt["id"],
        ),
    )
    conn.execute(
        """
        update agent_runs
        set route_digest_sha256 = ?, semantic_request_digest_sha256 = ?,
            request_source_refs_digest_sha256 = ?,
            provider_chain_digest_sha256 = ?, agent_lineage_digest_sha256 = ?
        where id = ? and batch_attempt_id = ?
        """,
        (
            attempt["route_digest_sha256"],
            attempt["request_digest_sha256"],
            commitment["request_source_refs_digest_sha256"],
            chain["provider_chain_digest_sha256"],
            lineage["agent_lineage_digest_sha256"],
            agent["id"],
            attempt["id"],
        ),
    )
    return lineage


def persisted_agent_lineage(
    conn: sqlite3.Connection,
    *,
    batch_attempt_id: str,
    agent_run_id: str,
) -> dict[str, Any]:
    attempt = conn.execute(
        "select * from answer_contract_generation_attempts where id = ?",
        (batch_attempt_id,),
    ).fetchone()
    agent = conn.execute(
        "select * from agent_runs where id = ? and batch_attempt_id = ?",
        (agent_run_id, batch_attempt_id),
    ).fetchone()
    if not attempt or not agent:
        raise ValueError("persisted agent lineage authority is missing")
    expected = _agent_and_provider_commitment(conn, dict(attempt), dict(agent))
    chain = expected["provider_chain"]
    lineage = expected["agent_lineage"]
    stored_chain = json.loads(
        str(attempt["provider_chain_payload_json"] or "{}")
    )
    stored_lineage = json.loads(
        str(attempt["agent_lineage_payload_json"] or "{}")
    )
    if any(
        (
            stored_chain != chain,
            attempt["provider_chain_digest_sha256"]
            != chain["provider_chain_digest_sha256"],
            stored_lineage != lineage,
            attempt["agent_lineage_digest_sha256"]
            != lineage["agent_lineage_digest_sha256"],
            attempt["request_source_refs_digest_sha256"]
            != expected["request_source_refs_digest_sha256"],
            attempt["agent_input_refs_digest_sha256"]
            != expected["agent_input_refs_digest_sha256"],
            agent["route_digest_sha256"] != attempt["route_digest_sha256"],
            agent["semantic_request_digest_sha256"]
            != attempt["request_digest_sha256"],
            agent["request_source_refs_digest_sha256"]
            != expected["request_source_refs_digest_sha256"],
            agent["provider_chain_digest_sha256"]
            != chain["provider_chain_digest_sha256"],
            agent["agent_lineage_digest_sha256"]
            != lineage["agent_lineage_digest_sha256"],
        )
    ):
        raise ValueError("persisted complete agent lineage is not exact")
    return lineage


def persisted_provider_chain(
    conn: sqlite3.Connection,
    *,
    batch_attempt_id: str,
    agent_run_id: str,
) -> dict[str, Any]:
    return persisted_agent_lineage(
        conn,
        batch_attempt_id=batch_attempt_id,
        agent_run_id=agent_run_id,
    )["provider_chain"]


def _reconcile_unresolved_attempts_before_claim(
    conn: sqlite3.Connection,
    run: Mapping[str, Any],
    *,
    hooks: BatchATestHooks | None,
) -> str | None:
    unresolved = conn.execute(
        """
        select * from answer_contract_generation_attempts
        where run_id = ? and status in ('reserved','provider_calling')
        order by reserved_at, id
        """,
        (run["id"],),
    ).fetchall()
    if not unresolved:
        return None
    now_epoch = float((hooks or BatchATestHooks()).wall_time())
    heartbeat_epoch = _iso_timestamp(
        run.get("heartbeat_at") or run.get("claimed_at")
    )
    if now_epoch - heartbeat_epoch <= float(run["stale_after_seconds"]):
        return "fresh_unresolved_provider_calling"

    now = datetime.fromtimestamp(now_epoch, tz=timezone.utc).isoformat()
    reconciliation = []
    integrity_blocked = False
    for attempt_row in unresolved:
        attempt = dict(attempt_row)
        providers = _provider_attempt_rows(conn, attempt["id"])
        agents = conn.execute(
            "select * from agent_runs where batch_attempt_id = ? order by id",
            (attempt["id"],),
        ).fetchall()
        if len(agents) > 1:
            integrity_blocked = True
            reconciliation.append(
                {"batch_attempt_id": attempt["id"], "outcome": "multiple_agent_runs"}
            )
            continue
        if len(agents) == 1:
            agent = dict(agents[0])
            try:
                _persist_agent_provider_commitment(conn, attempt, agent)
            except (TypeError, ValueError, json.JSONDecodeError, sqlite3.Error):
                integrity_blocked = True
                reconciliation.append(
                    {"batch_attempt_id": attempt["id"], "outcome": "orphan_mismatch"}
                )
                continue
            conn.execute(
                """
                update answer_contract_generation_attempts
                set status = 'accepted', agent_run_id = ?,
                    output_digest_sha256 = ?, local_verdict = 'accepted',
                    result_at = ?, finished_at = ?
                where id = ? and status in ('reserved','provider_calling')
                """,
                (
                    agent["id"],
                    agent["output_digest_sha256"],
                    now,
                    now,
                    attempt["id"],
                ),
            )
            reconciliation.append(
                {"batch_attempt_id": attempt["id"], "outcome": "orphan_attached"}
            )
            continue
        if providers:
            conn.execute(
                """
                update answer_contract_generation_attempts
                set status = 'provider_result_unknown',
                    error_class = 'provider_result_unknown',
                    reason_code = 'stale_provider_calling_without_exact_agent_run',
                    result_at = ?, finished_at = ?
                where id = ? and status in ('reserved','provider_calling')
                """,
                (now, now, attempt["id"]),
            )
            conn.execute(
                """
                update answer_contract_generation_provider_attempts
                set status = 'provider_result_unknown', finished_at = coalesce(finished_at, ?)
                where batch_attempt_id = ? and status in ('reserved','calling')
                """,
                (now, attempt["id"]),
            )
            reconciliation.append(
                {"batch_attempt_id": attempt["id"], "outcome": "provider_result_unknown"}
            )
        else:
            conn.execute(
                """
                update answer_contract_generation_attempts
                set status = 'interrupted', error_class = 'interrupted',
                    reason_code = 'stale_reservation_without_provider_attempt',
                    result_at = ?, finished_at = ?
                where id = ? and status in ('reserved','provider_calling')
                """,
                (now, now, attempt["id"]),
            )
            reconciliation.append(
                {"batch_attempt_id": attempt["id"], "outcome": "interrupted_before_provider"}
            )

    run_status = "blocked_integrity" if integrity_blocked else "interrupted"
    conn.execute(
        """
        update answer_contract_generation_runs
        set status = ?, last_error_class = 'stale_attempt_reconciliation',
            last_error = ?, interrupted_at = coalesce(interrupted_at, ?),
            updated_at = ?
        where id = ?
        """,
        (
            run_status,
            question_fingerprints.canonical_json(reconciliation),
            now,
            now,
            run["id"],
        ),
    )
    conn.execute(
        """
        update answer_contract_generation_run_items
        set status = case when status in ('pending','running','terminal_failure')
                          then 'interrupted' else status end,
            updated_at = ?
        where run_id = ?
          and id in (
            select run_item_id from answer_contract_generation_attempts
            where run_id = ? and status in (
              'interrupted','provider_result_unknown','accepted'
            )
          )
        """,
        (now, run["id"], run["id"]),
    )
    return "blocked_integrity" if integrity_blocked else "stale_attempt_reconciled"


def _scan_commit_uncertainty(
    conn: sqlite3.Connection,
    run: Mapping[str, Any],
    *,
    resolve: bool,
    hooks: BatchATestHooks | None,
    checkpoint_root: Path | None = None,
) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        select * from answer_contract_generation_attempts
        where run_id = ? and status in ('commit_unknown','committed_unverified')
        order by reserved_at, id
        """,
        (run["id"],),
    ).fetchall()
    if not rows:
        return None
    resolutions = []
    all_exact = True
    integrity_error = ""
    for row in rows:
        attempt = dict(row)
        agents = conn.execute(
            "select * from agent_runs where batch_attempt_id = ? order by id",
            (attempt["id"],),
        ).fetchall()
        if len(agents) != 1:
            all_exact = False
            if len(agents) > 1:
                integrity_error = "commit uncertainty has multiple agent runs"
            resolutions.append(
                {
                    "batch_attempt_id": attempt["id"],
                    "prior_status": attempt["status"],
                    "resolution": "unresolved_agent_cardinality",
                    "agent_count": len(agents),
                }
            )
            continue
        try:
            lineage = persisted_agent_lineage(
                conn,
                batch_attempt_id=attempt["id"],
                agent_run_id=agents[0]["id"],
            )
        except (TypeError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
            all_exact = False
            integrity_error = str(exc)
            resolutions.append(
                {
                    "batch_attempt_id": attempt["id"],
                    "prior_status": attempt["status"],
                    "resolution": "integrity_mismatch",
                }
            )
            continue
        resolutions.append(
            {
                "batch_attempt_id": attempt["id"],
                "prior_status": attempt["status"],
                "resolution": "exact_agent_result_confirmed",
                "agent_run_id": agents[0]["id"],
                "run_item_id": attempt["run_item_id"],
                "role": attempt["role"],
                "contract_version_index": int(
                    attempt["contract_version_index"]
                ),
                "agent_lineage_digest_sha256": lineage[
                    "agent_lineage_digest_sha256"
                ],
            }
        )
        item = conn.execute(
            "select * from answer_contract_generation_run_items where id = ? and run_id = ?",
            (attempt["run_item_id"], run["id"]),
        ).fetchone()
        run_id_column = f"{attempt['role']}_run_id"
        attempt_id_column = f"{attempt['role']}_batch_attempt_id"
        if (
            item is None
            or item["status"] in {"approved", "reused_approved"}
            or item[run_id_column] not in {None, "", agents[0]["id"]}
            or item[attempt_id_column] not in {None, "", attempt["id"]}
        ):
            all_exact = False
            integrity_error = "commit uncertainty item projection conflicts with DB"
    if integrity_error:
        return {
            "status": "blocked_integrity",
            "reason_code": integrity_error[:800],
            "resolutions": resolutions,
        }
    if not resolve or not all_exact:
        return {
            "status": str(run.get("status") or "committed_unverified"),
            "reason_code": "commit_uncertainty_requires_deterministic_audit",
            "resolutions": resolutions,
        }
    failure_paths: list[Path] = []
    if checkpoint_root is not None:
        for resolution in resolutions:
            item = conn.execute(
                "select node_id, question_id from answer_contract_generation_run_items where id = ?",
                (resolution["run_item_id"],),
            ).fetchone()
            if item is None:
                raise ValueError("commit uncertainty recovery item disappeared")
            failure_paths.append(
                checkpoint_root.resolve()
                / str(run["bank_version"])
                / str(item["node_id"])
                / str(item["question_id"])
                / (
                    f"contract-version-{resolution['contract_version_index'] + 1}."
                    f"{resolution['role']}.failure.json"
                )
            )
        for failure_path in failure_paths:
            try:
                failure_path.unlink(missing_ok=True)
            except OSError as exc:
                return {
                    "status": "blocked_integrity",
                    "reason_code": f"commit uncertainty failure projection cleanup failed: {exc}"[:800],
                    "resolutions": resolutions,
                }
    now = _now_iso(hooks)
    with _immediate_transaction(conn):
        for resolution in resolutions:
            cursor = conn.execute(
                """
                update answer_contract_generation_attempts
                set status = 'accepted', local_verdict = 'accepted',
                    error_class = '', reason_code = '',
                    result_at = coalesce(result_at, ?),
                    finished_at = coalesce(finished_at, ?)
                where id = ? and status in ('commit_unknown','committed_unverified')
                """,
                (now, now, resolution["batch_attempt_id"]),
            )
            if cursor.rowcount != 1:
                raise ValueError("commit uncertainty resolution lost its exact state")
            role = resolution["role"]
            cursor = conn.execute(
                f"""
                update answer_contract_generation_run_items
                set status = 'interrupted', {role}_run_id = ?,
                    {role}_batch_attempt_id = ?, terminal_class = '',
                    terminal_reason_code = '', terminal_at = null,
                    checkpoint_digest_sha256 = '',
                    checkpoint_projection_json = '[]', updated_at = ?
                where id = ? and run_id = ?
                  and status not in ('approved','reused_approved')
                  and coalesce({role}_run_id, '') in ('', ?)
                  and coalesce({role}_batch_attempt_id, '') in ('', ?)
                """,
                (
                    resolution["agent_run_id"],
                    resolution["batch_attempt_id"],
                    now,
                    resolution["run_item_id"],
                    run["id"],
                    resolution["agent_run_id"],
                    resolution["batch_attempt_id"],
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "commit uncertainty item projection lost its exact state"
                )
        conn.execute(
            """
            update answer_contract_generation_runs
            set status = 'interrupted', last_error_class = '',
                last_error = 'commit_uncertainty_resolved_exact_db_facts',
                terminal_count = (
                  select count(*) from answer_contract_generation_run_items
                  where run_id = ? and status in (
                    'terminal_failure','routed','blocked_integrity'
                  )
                ),
                interrupted_at = coalesce(interrupted_at, ?), updated_at = ?
            where id = ? and status in (
              'commit_unknown','committed_unverified','interrupted','running'
            )
            """,
            (run["id"], now, now, run["id"]),
        )
    return {
        "status": "interrupted",
        "reason_code": "commit_uncertainty_resolved_exact_db_facts",
        "resolutions": resolutions,
    }


def create_or_resume_v2_run(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    plan: Mapping[str, Any],
    checkpoint_root: Path,
    model_call_cap: int = CANARY_DEFAULT_MODEL_CALL_CAP,
    provider_attempt_cap: int = CANARY_DEFAULT_PROVIDER_ATTEMPT_CAP,
    hooks: BatchATestHooks | None = None,
) -> tuple[dict[str, Any], RunClaim]:
    _validate_canary_limits(
        model_call_cap=model_call_cap,
        provider_attempt_cap=provider_attempt_cap,
        max_items=CANARY_ITEM_COUNT,
        invocation_wall_seconds=CANARY_DEFAULT_WALL_SECONDS,
    )
    del project_root
    require_batch_schema_authority(conn)
    values = _validate_plan(plan)
    checkpoint_root.resolve().mkdir(parents=True, exist_ok=True)
    run_identity = _digest(
        {
            "run_schema_version": RUN_SCHEMA_VERSION,
            "run_kind": RUN_KIND_CANARY,
            "plan_digest_sha256": values["plan_digest_sha256"],
            "model_call_cap": model_call_cap,
            "provider_attempt_cap": provider_attempt_cap,
            "item_wall_seconds": 180.0,
        }
    )
    run_id = "ACGR-A-" + run_identity[:24]
    now = _now_iso(hooks)
    active_hooks = hooks or BatchATestHooks()
    with _immediate_transaction(conn):
        row = conn.execute(
            "select * from answer_contract_generation_runs where run_identity_digest_sha256 = ?",
            (run_identity,),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                insert into answer_contract_generation_runs(
                  id, run_schema_version, run_kind, run_identity_digest_sha256,
                  ledger_id, bank_version, manifest_sha256, graph_version,
                  plan_digest_sha256, selection_policy_version,
                  selection_source_digest_sha256,
                  effective_evidence_role_policy_version,
                  effective_evidence_role_policy_digest_sha256,
                  generator_policy_digest_sha256,
                  designer_prompt_digest_sha256, designer_schema_digest_sha256,
                  designer_route_digest_sha256,
                  reviewer_prompt_digest_sha256, reviewer_schema_digest_sha256,
                  reviewer_route_digest_sha256,
                  expected_item_count, new_item_count, model_call_cap,
                  provider_attempt_cap, item_wall_seconds,
                  heartbeat_interval_seconds, stale_after_seconds,
                  preflight_status, status, created_at, updated_at
                ) values (
                  ?, ?, 'canary40', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, 40, 40, ?, ?, 180.0, ?, ?, 'pending', 'planned', ?, ?
                )
                """,
                (
                    run_id,
                    RUN_SCHEMA_VERSION,
                    run_identity,
                    values["ledger_id"],
                    values["bank_version"],
                    values["manifest_sha256"],
                    values["graph_version"],
                    values["plan_digest_sha256"],
                    values["selection_policy_version"],
                    values["selection_source_digest_sha256"],
                    EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION,
                    EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256,
                    values["generator_policy_digest_sha256"],
                    values["designer_prompt_digest_sha256"],
                    values["designer_schema_digest_sha256"],
                    values["designer_route_digest_sha256"],
                    values["reviewer_prompt_digest_sha256"],
                    values["reviewer_schema_digest_sha256"],
                    values["reviewer_route_digest_sha256"],
                    model_call_cap,
                    provider_attempt_cap,
                    HEARTBEAT_INTERVAL_SECONDS,
                    stale_after_seconds(
                        max(
                            float(values["designer_route"]["timeout_seconds"]),
                            float(values["reviewer_route"]["timeout_seconds"]),
                        )
                    ),
                    now,
                    now,
                ),
            )
            for item in values["items"]:
                item_id = "ACGI-" + _digest(
                    {
                        "run_id": run_id,
                        "question_id": item["question_id"],
                        "item_version": item["item_version"],
                    }
                )[:24]
                conn.execute(
                    """
                    insert into answer_contract_generation_run_items(
                      id, run_id, ordinal, question_id, item_version,
                      question_digest_sha256, node_id, kind,
                      effective_evidence_role,
                      effective_evidence_role_policy_version,
                      review_record_id, status, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        item_id,
                        run_id,
                        item["ordinal"],
                        item["question_id"],
                        item["item_version"],
                        item["question_digest_sha256"],
                        item["node_id"],
                        item["kind"],
                        item["effective_evidence_role"],
                        EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION,
                        item["review_record_id"],
                        now,
                        now,
                    ),
                )
            row = conn.execute(
                "select * from answer_contract_generation_runs where id = ?",
                (run_id,),
            ).fetchone()
        else:
            if any(
                (
                    row["id"] != run_id,
                    row["run_kind"] != RUN_KIND_CANARY,
                    row["plan_digest_sha256"] != values["plan_digest_sha256"],
                    int(row["expected_item_count"]) != CANARY_ITEM_COUNT,
                    int(row["model_call_cap"]) != model_call_cap,
                    int(row["provider_attempt_cap"]) != provider_attempt_cap,
                )
            ):
                raise ValueError("Batch A canonical run identity conflict")
            stored_items = [
                dict(item)
                for item in conn.execute(
                    "select * from answer_contract_generation_run_items where run_id = ? order by ordinal",
                    (run_id,),
                ).fetchall()
            ]
            if len(stored_items) != CANARY_ITEM_COUNT or any(
                stored["question_id"] != planned["question_id"]
                or stored["item_version"] != planned["item_version"]
                or stored["question_digest_sha256"]
                != planned["question_digest_sha256"]
                or stored["effective_evidence_role"]
                != planned["effective_evidence_role"]
                for stored, planned in zip(stored_items, values["items"])
            ):
                raise ValueError("Batch A persisted run items conflict with the plan")
        resume_action = None
        uncertainty = _scan_commit_uncertainty(
            conn,
            dict(row),
            resolve=False,
            hooks=hooks,
        )
        if uncertainty is not None:
            result = dict(row)
            result["_resume_action"] = "commit_uncertainty_requires_audit"
            result["_resume_report"] = uncertainty
            result["status"] = uncertainty["status"]
            return result, _claim_from_row(row)
        if row["status"] not in RUN_TERMINAL_STATUSES:
            resume_action = _reconcile_unresolved_attempts_before_claim(
                conn,
                dict(row),
                hooks=hooks,
            )
        if resume_action is not None:
            row = conn.execute(
                "select * from answer_contract_generation_runs where id = ?",
                (run_id,),
            ).fetchone()
            result = dict(row)
            result["_resume_action"] = resume_action
            return result, _claim_from_row(row)
        if row["status"] in RUN_TERMINAL_STATUSES:
            return dict(row), _claim_from_row(row)
        generation = int(row["operation_generation"] or 0) + 1
        claim_token = active_hooks.new_claim_token()
        invocation_id = active_hooks.new_invocation_id()
        owner_pid = int(active_hooks.pid())
        if not claim_token or not invocation_id or owner_pid < 1:
            raise ValueError("Batch A claim hooks returned invalid authority")
        conn.execute(
            """
            update answer_contract_generation_runs
            set operation_generation = ?, claim_token = ?, claim_owner_pid = ?,
                claim_invocation_id = ?, claimed_at = ?, heartbeat_at = ?,
                preflight_status = 'pending', status = 'preflight_running',
                started_at = coalesce(started_at, ?), updated_at = ?
            where id = ?
            """,
            (
                generation,
                claim_token,
                owner_pid,
                invocation_id,
                now,
                now,
                now,
                now,
                run_id,
            ),
        )
        row = conn.execute(
            "select * from answer_contract_generation_runs where id = ?",
            (run_id,),
        ).fetchone()
        return dict(row), _claim_from_row(row)


def _semantic_request_payload(request: Any) -> dict[str, Any]:
    return {
        "agent_key": request.agent_key,
        "phase": request.phase,
        "trusted_context": deepcopy(request.trusted_context),
        "untrusted_payload": deepcopy(request.untrusted_payload),
        "provider_mode": request.provider_mode,
        "source_refs": deepcopy(request.source_refs),
        "contract_version_suffix": request.contract_version_suffix,
    }


class _BatchProviderAttemptObserver:
    def __init__(
        self,
        conn: sqlite3.Connection,
        claim: RunClaim,
        run_item_id: str,
        provider_attempt_cap: int,
        external_observer: model_router.StructuredTransportLifecycleObserver | None,
        hooks: BatchATestHooks | None,
    ) -> None:
        self.conn = conn
        self.claim = claim
        self.run_item_id = run_item_id
        self.provider_attempt_cap = provider_attempt_cap
        self.external_observer = external_observer
        self.hooks = hooks

    def provider_attempt_started(
        self, context: model_router.StructuredTransportAttemptContext
    ) -> None:
        if _stop_is_requested(self.hooks):
            raise BatchAStopRequested("signal_requested")
        _heartbeat(self.conn, self.claim, hooks=self.hooks)
        now = _now_iso(self.hooks)
        attempt_id = "ACPA-" + _digest(
            {
                "batch_attempt_id": context.batch_attempt_id,
                "candidate_ordinal": context.candidate_ordinal,
            }
        )[:24]
        with _immediate_transaction(self.conn):
            run = _require_current_claim(
                self.conn, self.claim, allowed_statuses={"running"}
            )
            if int(run["provider_attempts"]) >= self.provider_attempt_cap:
                raise ValueError("Batch A provider_attempt_cap exhausted")
            semantic = self.conn.execute(
                "select id, run_id, run_item_id, status from answer_contract_generation_attempts where id = ?",
                (context.batch_attempt_id,),
            ).fetchone()
            if (
                not semantic
                or semantic["run_id"] != self.claim.run_id
                or semantic["run_item_id"] != self.run_item_id
                or semantic["status"] != "provider_calling"
            ):
                raise ValueError("provider attempt has no current semantic authority")
            self.conn.execute(
                """
                insert into answer_contract_generation_provider_attempts(
                  id, batch_attempt_id, candidate_ordinal, endpoint,
                  structured_json_mode, request_digest_sha256, status,
                  reserved_at, call_started_at
                ) values (?, ?, ?, ?, ?, ?, 'calling', ?, ?)
                """,
                (
                    attempt_id,
                    context.batch_attempt_id,
                    context.candidate_ordinal,
                    context.endpoint,
                    context.structured_json_mode,
                    context.request_digest_sha256,
                    now,
                    now,
                ),
            )
            self.conn.execute(
                "update answer_contract_generation_runs set provider_attempts = provider_attempts + 1, updated_at = ? where id = ?",
                (now, self.claim.run_id),
            )
            self.conn.execute(
                "update answer_contract_generation_run_items set provider_attempts = provider_attempts + 1, updated_at = ? where id = ?",
                (now, self.run_item_id),
            )
        if self.external_observer is not None:
            self.external_observer.provider_attempt_started(context)

    def provider_attempt_finished(
        self,
        context: model_router.StructuredTransportAttemptContext,
        outcome: model_router.StructuredTransportAttemptOutcome,
    ) -> None:
        _heartbeat(self.conn, self.claim, hooks=self.hooks)
        status = outcome.outcome
        if status not in {
            "response_received",
            "retryable_failure",
            "terminal_failure",
            "provider_result_unknown",
            "interrupted",
        }:
            status = "terminal_failure"
        now = _now_iso(self.hooks)
        with _immediate_transaction(self.conn):
            _require_current_claim(
                self.conn, self.claim, allowed_statuses={"running"}
            )
            cursor = self.conn.execute(
                """
                update answer_contract_generation_provider_attempts
                set status = ?, http_status = ?, retry_after_seconds = ?,
                    response_digest_sha256 = ?, error_class = ?, error_message = ?,
                    response_at = case when ? = 'response_received' then ? else response_at end,
                    finished_at = ?
                where batch_attempt_id = ? and candidate_ordinal = ?
                  and status = 'calling'
                """,
                (
                    status,
                    outcome.status_code,
                    outcome.retry_after_seconds,
                    outcome.response_digest_sha256,
                    outcome.error_class,
                    outcome.error_message[:800],
                    status,
                    now,
                    now,
                    context.batch_attempt_id,
                    context.candidate_ordinal,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("provider attempt completion is not idempotent-current")
        if self.external_observer is not None:
            self.external_observer.provider_attempt_finished(context, outcome)


class _BatchSemanticCallback:
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        plan: Mapping[str, Any],
        claim: RunClaim,
        run_item_id: str,
        role: str,
        callback: Callable[[dict[str, Any]], dict[str, Any]],
        lifecycle_observer: BatchALifecycleObserver | None,
        model_call_cap: int,
        provider_attempt_cap: int,
        wall_deadline_monotonic: float,
        hooks: BatchATestHooks | None,
    ) -> None:
        self.conn = conn
        self.plan = plan
        self.claim = claim
        self.run_item_id = run_item_id
        self.role = role
        self.callback = callback
        self.lifecycle_observer = lifecycle_observer
        self.model_call_cap = model_call_cap
        self.provider_attempt_cap = provider_attempt_cap
        self.wall_deadline_monotonic = wall_deadline_monotonic
        self.hooks = hooks
        self.production_live_adapter = bool(
            getattr(callback, "production_live_adapter", False)
        )
        self.transport_timeout_seconds = float(
            getattr(callback, "transport_timeout_seconds", 180.0)
        )
        self.current_transport_timeout_seconds = self.transport_timeout_seconds
        self.transport_endpoint = str(
            getattr(callback, "transport_endpoint", "responses")
        )
        self.structured_json_mode = str(
            getattr(callback, "structured_json_mode", "json_schema")
        )

    def _reserve(self, packet: dict[str, Any]) -> BatchAttemptContext:
        from . import answer_contract_generation_v2

        if _stop_is_requested(self.hooks):
            raise BatchAStopRequested("signal_requested")
        _heartbeat(self.conn, self.claim, hooks=self.hooks)
        version_index = int(packet.get("repair_iteration") or 0)
        now = _now_iso(self.hooks)
        with _immediate_transaction(self.conn):
            run = _require_current_claim(
                self.conn, self.claim, allowed_statuses={"running"}
            )
            if int(run["model_calls"]) >= self.model_call_cap:
                raise ValueError("Batch A model_call_cap exhausted")
            next_index = int(
                self.conn.execute(
                    """
                    select coalesce(max(semantic_attempt_index), 0) + 1
                    from answer_contract_generation_attempts
                    where run_item_id = ? and role = ? and contract_version_index = ?
                    """,
                    (self.run_item_id, self.role, version_index),
                ).fetchone()[0]
            )
            if next_index > 3:
                raise ValueError("Batch A semantic attempt budget exhausted")
            attempt_id = new_batch_attempt_id(hooks=self.hooks)
            prompt_digest = self.plan[f"{self.role}_prompt_digest_sha256"]
            schema_digest = self.plan[f"{self.role}_schema_digest_sha256"]
            route_digest = self.plan[f"{self.role}_route_digest_sha256"]
            self.conn.execute(
                """
                insert into answer_contract_generation_attempts(
                  id, run_id, run_item_id, claim_generation,
                  claim_token_digest_sha256, role, contract_version_index,
                  semantic_attempt_index, request_json, request_digest_sha256,
                  prompt_digest_sha256, schema_digest_sha256, route_digest_sha256,
                  status, reserved_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, 'reserved', ?)
                """,
                (
                    attempt_id,
                    self.claim.run_id,
                    self.run_item_id,
                    self.claim.operation_generation,
                    claim_token_digest(self.claim.claim_token),
                    self.role,
                    version_index,
                    next_index,
                    _digest({}),
                    prompt_digest,
                    schema_digest,
                    route_digest,
                    now,
                ),
            )
            self.conn.execute(
                "update answer_contract_generation_runs set model_calls = model_calls + 1, updated_at = ? where id = ?",
                (now, self.claim.run_id),
            )
            self.conn.execute(
                "update answer_contract_generation_run_items set model_calls = model_calls + 1, status = 'running', started_at = coalesce(started_at, ?), updated_at = ? where id = ?",
                (now, now, self.run_item_id),
            )
        context = load_batch_attempt_context(
            self.conn,
            batch_attempt_id=attempt_id,
            claim=self.claim,
            expected_role=self.role,
        )
        request = (
            answer_contract_generation_v2.semantic_design_request_v2(
                packet, batch_context=context
            )
            if self.role == "designer"
            else answer_contract_generation_v2.semantic_review_request_v2(
                packet, batch_context=context
            )
        )
        request_payload = _semantic_request_payload(request)
        with _immediate_transaction(self.conn):
            _require_current_claim(
                self.conn, self.claim, allowed_statuses={"running"}
            )
            cursor = self.conn.execute(
                """
                update answer_contract_generation_attempts
                set request_json = ?, request_digest_sha256 = ?,
                    status = 'provider_calling', provider_calling_at = ?
                where id = ? and status = 'reserved'
                """,
                (
                    json.dumps(
                        request_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    _digest(request_payload),
                    now,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Batch A semantic attempt reservation lost")
        if self.lifecycle_observer is not None:
            self.lifecycle_observer.semantic_attempt_reserved(context)
        return context

    def _finish(
        self,
        context: BatchAttemptContext,
        *,
        status: str,
        outcome: str,
        agent_run_id: str = "",
        output_digest_sha256: str = "",
        local_verdict: str = "none",
        error_class: str = "",
        reason_code: str = "",
    ) -> None:
        now = _now_iso(self.hooks)
        with _immediate_transaction(self.conn):
            _require_current_claim(
                self.conn, self.claim, allowed_statuses={"running"}
            )
            if agent_run_id and status in {"accepted", "committed_unverified"}:
                attempt_row = self.conn.execute(
                    "select * from answer_contract_generation_attempts where id = ?",
                    (context.batch_attempt_id,),
                ).fetchone()
                agent_row = self.conn.execute(
                    "select * from agent_runs where id = ? and batch_attempt_id = ?",
                    (agent_run_id, context.batch_attempt_id),
                ).fetchone()
                if not attempt_row or not agent_row:
                    raise ValueError("semantic completion lacks exact agent authority")
                _persist_agent_provider_commitment(
                    self.conn,
                    dict(attempt_row),
                    dict(agent_row),
                )
            cursor = self.conn.execute(
                """
                update answer_contract_generation_attempts
                set status = ?, agent_run_id = nullif(?, ''),
                    output_digest_sha256 = ?, local_verdict = ?,
                    error_class = ?, reason_code = ?, result_at = ?, finished_at = ?
                where id = ? and status = 'provider_calling'
                """,
                (
                    status,
                    agent_run_id,
                    output_digest_sha256,
                    local_verdict,
                    error_class,
                    reason_code,
                    now,
                    now,
                    context.batch_attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Batch A semantic attempt completion lost")
        if self.lifecycle_observer is not None:
            self.lifecycle_observer.semantic_attempt_finished(
                context, outcome=outcome
            )

    def __call__(self, packet: dict[str, Any]) -> dict[str, Any]:
        from . import answer_contract_generation_v2

        if hasattr(self.callback, "current_transport_timeout_seconds"):
            self.callback.current_transport_timeout_seconds = (
                self.current_transport_timeout_seconds
            )
        context = self._reserve(packet)
        callback_packet = deepcopy(packet)
        callback_packet["_batch_attempt_id"] = context.batch_attempt_id
        callback_packet["_batch_attempt_context"] = context
        external_transport = (
            self.lifecycle_observer.transport_observer
            if self.lifecycle_observer is not None
            else None
        )
        provider_observer = _BatchProviderAttemptObserver(
            self.conn,
            self.claim,
            self.run_item_id,
            self.provider_attempt_cap,
            external_transport,
            self.hooks,
        )
        try:
            with bind_batch_attempt_transport(
                context,
                provider_observer,
                wall_deadline_monotonic=self.wall_deadline_monotonic,
            ):
                result = self.callback(callback_packet)
            if not isinstance(result, dict):
                raise TypeError("Batch A semantic callback must return a mapping")
            agent_run_id = str(result.get("agent_run_id") or "")
            output = result.get("output")
            if not agent_run_id or not isinstance(output, dict):
                raise ValueError("Batch A callback result lacks exact agent evidence")
            agent = self.conn.execute(
                "select batch_attempt_id, status, output_digest_sha256 from agent_runs where id = ?",
                (agent_run_id,),
            ).fetchone()
            output_digest = _digest(output)
            if (
                not agent
                or agent["batch_attempt_id"] != context.batch_attempt_id
                or agent["status"] != "accepted"
                or agent["output_digest_sha256"] != output_digest
            ):
                raise ValueError("Batch A callback agent evidence is not exact")
            if not _has_exact_provider_response_chain(
                self.conn, context.batch_attempt_id
            ):
                raise ValueError(
                    "Batch A callback lacks an exact response_received provider chain"
                )
            self._finish(
                context,
                status="accepted",
                outcome="accepted",
                agent_run_id=agent_run_id,
                output_digest_sha256=output_digest,
                local_verdict="accepted",
            )
            lineage = persisted_agent_lineage(
                self.conn,
                batch_attempt_id=context.batch_attempt_id,
                agent_run_id=agent_run_id,
            )
            chain = lineage["provider_chain"]
            return {
                **result,
                "agent_lineage": lineage,
                "agent_lineage_digest_sha256": lineage[
                    "agent_lineage_digest_sha256"
                ],
                "provider_chain": chain,
                "provider_chain_digest_sha256": chain[
                    "provider_chain_digest_sha256"
                ],
                "_batch_attempt_context": context,
            }
        except BatchAStopRequested:
            self._finish(
                context,
                status="interrupted",
                outcome="interrupted",
                error_class="interrupted",
                reason_code="signal_requested",
            )
            raise
        except answer_contract_generation_v2.LocalSemanticRejection as exc:
            report = exc.report
            self._finish(
                context,
                status="semantic_rejected",
                outcome="semantic_rejected",
                agent_run_id=str(report.get("agent_run_id") or ""),
                output_digest_sha256=str(
                    report.get("output_digest_sha256") or ""
                ),
                local_verdict="compiler_rejected",
                error_class=type(exc).__name__,
                reason_code=str(report.get("local_issue_code") or ""),
            )
            raise
        except sqlite3.Error as exc:
            attempt_row = self.conn.execute(
                "select * from answer_contract_generation_attempts where id = ?",
                (context.batch_attempt_id,),
            ).fetchone()
            agents = self.conn.execute(
                "select * from agent_runs where batch_attempt_id = ? order by id",
                (context.batch_attempt_id,),
            ).fetchall()
            if attempt_row and len(agents) == 1:
                try:
                    _agent_and_provider_commitment(
                        self.conn,
                        dict(attempt_row),
                        dict(agents[0]),
                    )
                except (TypeError, ValueError, json.JSONDecodeError, sqlite3.Error):
                    pass
                else:
                    if attempt_row["status"] == "accepted":
                        now = _now_iso(self.hooks)
                        with _immediate_transaction(self.conn):
                            cursor = self.conn.execute(
                                """
                                update answer_contract_generation_attempts
                                set status = 'committed_unverified',
                                    error_class = ?, reason_code = ?,
                                    result_at = coalesce(result_at, ?),
                                    finished_at = coalesce(finished_at, ?)
                                where id = ? and status = 'accepted'
                                """,
                                (
                                    type(exc).__name__,
                                    "commit_returned_exception_after_success",
                                    now,
                                    now,
                                    context.batch_attempt_id,
                                ),
                            )
                            if cursor.rowcount != 1:
                                raise ValueError(
                                    "commit-after-success uncertainty state changed"
                                )
                    elif attempt_row["status"] == "provider_calling":
                        self._finish(
                            context,
                            status="committed_unverified",
                            outcome="committed_unverified",
                            agent_run_id=agents[0]["id"],
                            output_digest_sha256=agents[0]["output_digest_sha256"],
                            error_class=type(exc).__name__,
                            reason_code="post_agent_commit_read_failure",
                        )
                    elif attempt_row["status"] != "committed_unverified":
                        raise ValueError(
                            "commit uncertainty has contradictory attempt state"
                        )
                    raise BatchACommitUncertain(
                        "committed_unverified", context.batch_attempt_id
                    ) from exc
            self._finish(
                context,
                status="commit_unknown",
                outcome="commit_unknown",
                error_class=type(exc).__name__,
                reason_code="post_provider_commit_state_unknown",
            )
            raise BatchACommitUncertain(
                "commit_unknown", context.batch_attempt_id
            ) from exc
        except Exception as exc:
            self._finish(
                context,
                status="transport_failed",
                outcome="transport_failed",
                error_class=type(exc).__name__,
                reason_code=str(exc)[:800],
            )
            raise


def _recovered_designer_callback(
    conn: sqlite3.Connection,
    *,
    claim: RunClaim,
    item: Mapping[str, Any],
) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    from . import answer_contract_generation_v2

    designer_run_id = str(item.get("designer_run_id") or "")
    batch_attempt_id = str(item.get("designer_batch_attempt_id") or "")
    reviewer_run_id = str(item.get("reviewer_run_id") or "")
    reviewer_attempt_id = str(item.get("reviewer_batch_attempt_id") or "")
    if not designer_run_id and not batch_attempt_id:
        return None
    if (
        not designer_run_id
        or not batch_attempt_id
        or reviewer_run_id
        or reviewer_attempt_id
    ):
        raise ValueError("recovered designer projection is incomplete")
    attempt = conn.execute(
        "select * from answer_contract_generation_attempts where id = ?",
        (batch_attempt_id,),
    ).fetchone()
    agent = conn.execute(
        "select * from agent_runs where id = ? and batch_attempt_id = ?",
        (designer_run_id, batch_attempt_id),
    ).fetchone()
    if not attempt or not agent or any(
        (
            attempt["run_id"] != claim.run_id,
            attempt["run_item_id"] != item["id"],
            attempt["role"] != "designer",
            attempt["status"] != "accepted",
            attempt["local_verdict"] != "accepted",
            attempt["agent_run_id"] != designer_run_id,
            agent["status"] != "accepted",
        )
    ):
        raise ValueError("recovered designer DB authority is not exact")
    persisted_agent_lineage(
        conn,
        batch_attempt_id=batch_attempt_id,
        agent_run_id=designer_run_id,
    )
    with _immediate_transaction(conn):
        _require_current_claim(conn, claim, allowed_statuses={"running"})
        cursor = conn.execute(
            """
            update answer_contract_generation_attempts
            set claim_generation = ?, claim_token_digest_sha256 = ?
            where id = ? and run_id = ? and run_item_id = ?
              and role = 'designer' and status = 'accepted'
              and agent_run_id = ? and local_verdict = 'accepted'
            """,
            (
                claim.operation_generation,
                claim_token_digest(claim.claim_token),
                batch_attempt_id,
                claim.run_id,
                item["id"],
                designer_run_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("recovered designer claim rebind lost exact authority")
    context = load_batch_attempt_context(
        conn,
        batch_attempt_id=batch_attempt_id,
        claim=claim,
        expected_role="designer",
    )
    attempt = conn.execute(
        "select * from answer_contract_generation_attempts where id = ?",
        (batch_attempt_id,),
    ).fetchone()
    agent = conn.execute(
        "select * from agent_runs where id = ? and batch_attempt_id = ?",
        (designer_run_id, batch_attempt_id),
    ).fetchone()
    if not attempt or not agent:
        raise ValueError("recovered designer authority disappeared")
    request_payload = json.loads(str(attempt["request_json"] or "{}"))
    output = json.loads(str(agent["output_json"] or "{}"))
    lineage = persisted_agent_lineage(
        conn,
        batch_attempt_id=batch_attempt_id,
        agent_run_id=designer_run_id,
    )
    provider_chain = lineage["provider_chain"]
    response_attempts = [
        row
        for row in provider_chain["provider_attempts"]
        if row["status"] == "response_received"
    ]
    if len(response_attempts) != 1:
        raise ValueError("recovered designer provider response is not singular")
    response_attempt = response_attempts[0]
    used = False

    def recovered(packet: dict[str, Any]) -> dict[str, Any]:
        nonlocal used
        if used:
            raise ValueError("recovered designer authority cannot be replayed twice")
        expected_request = answer_contract_generation_v2.semantic_design_request_v2(
            packet,
            batch_context=context,
        )
        expected_payload = _semantic_request_payload(expected_request)
        if any(
            (
                request_payload != expected_payload,
                attempt["request_digest_sha256"] != _digest(expected_payload),
                agent["output_digest_sha256"] != _digest(output),
            )
        ):
            raise ValueError("recovered designer request or output is not exact")
        used = True
        return {
            "agent_key": agent["agent_key"],
            "phase": agent["phase"],
            "status": agent["status"],
            "provider_mode": agent["provider_mode"],
            "agent_run_id": agent["id"],
            "transport_endpoint": response_attempt["endpoint"],
            "structured_json_mode": response_attempt[
                "structured_json_mode"
            ],
            "output": deepcopy(output),
            "agent_lineage": deepcopy(lineage),
            "agent_lineage_digest_sha256": lineage[
                "agent_lineage_digest_sha256"
            ],
            "provider_chain": deepcopy(provider_chain),
            "provider_chain_digest_sha256": provider_chain[
                "provider_chain_digest_sha256"
            ],
            "_batch_attempt_context": context,
        }

    return recovered


def _question_for_run_item(
    conn: sqlite3.Connection, item: Mapping[str, Any]
) -> dict[str, Any]:
    from . import answer_contract_generation_v2, db

    row = conn.execute(
        "select * from question_items where id = ? and item_version = ?",
        (item["question_id"], item["item_version"]),
    ).fetchone()
    if row is None:
        raise ValueError("Batch A planned question disappeared")
    question = db.row_to_question(row)
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    if any(
        (
            question["node_id"] != item["node_id"],
            question["kind"] != item["kind"],
            answer_contract_generation_v2._question_digest(question)
            != item["question_digest_sha256"],
            effective_evidence_role(raw) != item["effective_evidence_role"],
        )
    ):
        raise ValueError("Batch A planned question authority changed")
    return question


def _checkpoint_projection_for_item(
    conn: sqlite3.Connection,
    checkpoint_root: Path,
    run: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    require_final_contract: bool,
    recover_missing: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    root = (
        checkpoint_root.resolve()
        / str(run["bank_version"])
        / str(item["node_id"])
        / str(item["question_id"])
    )
    paths = sorted(root.glob("contract-version-*.json")) if root.is_dir() else []
    stored_projection = json.loads(
        str(item.get("checkpoint_projection_json") or "[]")
    )
    if not isinstance(stored_projection, list):
        raise ValueError("Batch A checkpoint DB projection is malformed")
    if not paths and recover_missing and stored_projection:
        stored_commitments = []
        for entry in stored_projection:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"name", "payload"}
                or not isinstance(entry["name"], str)
                or Path(entry["name"]).name != entry["name"]
                or not isinstance(entry["payload"], dict)
                or not _valid_digest_payload(entry["payload"])
            ):
                raise ValueError("Batch A checkpoint DB projection is invalid")
            stored_commitments.append(
                {
                    "name": entry["name"],
                    "receipt_digest_sha256": entry["payload"][
                        "receipt_digest_sha256"
                    ],
                }
            )
        if item.get("checkpoint_digest_sha256") != _digest(stored_commitments):
            raise ValueError("Batch A checkpoint DB projection digest mismatch")
        for entry in stored_projection:
            _atomic_write_json(root / entry["name"], entry["payload"])
        paths = sorted(root.glob("contract-version-*.json"))
    if not paths:
        if require_final_contract:
            raise ValueError("Batch A approved item checkpoint is missing")
        return "", []
    commitments = []
    projection = []
    final_found = False
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Batch A checkpoint is unreadable") from exc
        if not _valid_digest_payload(payload):
            raise ValueError("Batch A checkpoint receipt digest is invalid")
        if any(
            (
                payload.get("question_id") != item["question_id"],
                payload.get("item_version") != item["item_version"],
                payload.get("question_digest_sha256")
                != item["question_digest_sha256"],
            )
        ):
            raise ValueError("Batch A checkpoint question lineage mismatch")
        contract_id = payload.get("contract_id")
        if contract_id:
            contract = conn.execute(
                "select contract_digest_sha256 from answer_contracts where id = ?",
                (contract_id,),
            ).fetchone()
            if (
                not contract
                or contract["contract_digest_sha256"]
                != payload.get("contract_digest_sha256")
            ):
                raise ValueError("Batch A checkpoint contract lineage mismatch")
            if contract_id == item.get("contract_id"):
                final_found = True
        commitments.append(
            {
                "name": path.name,
                "receipt_digest_sha256": payload["receipt_digest_sha256"],
            }
        )
        projection.append({"name": path.name, "payload": payload})
    if require_final_contract and not final_found:
        raise ValueError("Batch A final contract checkpoint is missing")
    checkpoint_digest = _digest(commitments)
    if stored_projection and stored_projection != projection:
        raise ValueError("Batch A checkpoint projection conflicts with DB")
    if item.get("checkpoint_digest_sha256") not in {"", checkpoint_digest}:
        raise ValueError("Batch A checkpoint commitment conflicts with DB")
    return checkpoint_digest, projection


def _validate_historical_attempt(
    conn: sqlite3.Connection,
    run: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    role: str,
    attempt_id: str,
    agent_run_id: str,
) -> dict[str, Any]:
    attempt = conn.execute(
        "select * from answer_contract_generation_attempts where id = ?",
        (attempt_id,),
    ).fetchone()
    agent = conn.execute(
        "select * from agent_runs where id = ?",
        (agent_run_id,),
    ).fetchone()
    if not attempt or not agent:
        raise ValueError("Batch A item semantic lineage is missing")
    expected_agent = (
        "answer_contract_designer_agent"
        if role == "designer"
        else "answer_contract_reviewer_agent"
    )
    expected_phase = (
        "answer_contract_design_v2"
        if role == "designer"
        else "answer_contract_review_v2"
    )
    request = json.loads(attempt["request_json"])
    trusted = request.get("trusted_context") if isinstance(request, dict) else None
    source_refs = request.get("source_refs") if isinstance(request, dict) else None
    input_refs = json.loads(agent["input_refs_json"] or "{}")
    current_attempt_owner = (
        attempt["run_id"] == run["id"]
        and attempt["run_item_id"] == item["id"]
    )
    reused_attempt_owner = False
    if item.get("status") == "reused_approved" and not current_attempt_owner:
        source_item = conn.execute(
            "select * from answer_contract_generation_run_items where id = ?",
            (attempt["run_item_id"],),
        ).fetchone()
        source_run = conn.execute(
            "select * from answer_contract_generation_runs where id = ?",
            (attempt["run_id"],),
        ).fetchone()
        if source_item and source_run:
            source_run_values = dict(source_run)
            try:
                source_preflight = _persisted_preflight(source_run_values)
            except (TypeError, ValueError, json.JSONDecodeError):
                source_preflight = {}
            reused_attempt_owner = all(
                (
                    source_run["status"] == "completed_passed",
                    source_run["bank_version"] == run["bank_version"],
                    source_run["manifest_sha256"] == run["manifest_sha256"],
                    source_run["graph_version"] == run["graph_version"],
                    source_run["generator_policy_digest_sha256"]
                    == run["generator_policy_digest_sha256"],
                    source_run["effective_evidence_role_policy_version"]
                    == run["effective_evidence_role_policy_version"],
                    source_run["effective_evidence_role_policy_digest_sha256"]
                    == run["effective_evidence_role_policy_digest_sha256"],
                    source_item["run_id"] == source_run["id"],
                    source_item["question_id"] == item["question_id"],
                    source_item["item_version"] == item["item_version"],
                    source_item["question_digest_sha256"]
                    == item["question_digest_sha256"],
                    source_item["review_record_id"] == item["review_record_id"],
                    source_item["status"] in {"approved", "reused_approved"},
                    source_preflight.get("preflight_pass") is True,
                )
            )
    if any(
        (
            not current_attempt_owner and not reused_attempt_owner,
            attempt["role"] != role,
            attempt["status"] != "accepted",
            attempt["local_verdict"] != "accepted",
            attempt["agent_run_id"] != agent_run_id,
            agent["batch_attempt_id"] != attempt_id,
            agent["agent_key"] != expected_agent,
            agent["phase"] != expected_phase,
            agent["status"] != "accepted",
            attempt["request_digest_sha256"] != _digest(request),
            attempt["prompt_digest_sha256"]
            != run[f"{role}_prompt_digest_sha256"],
            attempt["schema_digest_sha256"]
            != run[f"{role}_schema_digest_sha256"],
            attempt["route_digest_sha256"]
            != run[f"{role}_route_digest_sha256"],
            agent["prompt_template_sha256"]
            != run[f"{role}_prompt_digest_sha256"],
            agent["response_schema_sha256"]
            != run[f"{role}_schema_digest_sha256"],
            agent["output_digest_sha256"]
            != attempt["output_digest_sha256"],
            not isinstance(trusted, dict),
            not isinstance(source_refs, dict),
            trusted.get("batch_attempt_id") != attempt_id
            if isinstance(trusted, dict)
            else True,
            source_refs.get("batch_attempt_id") != attempt_id
            if isinstance(source_refs, dict)
            else True,
            trusted.get("effective_evidence_role")
            != item["effective_evidence_role"]
            if isinstance(trusted, dict)
            else True,
            input_refs.get("batch_attempt_id") != attempt_id,
        )
    ):
        raise ValueError("Batch A item semantic lineage is not exact")
    agent_lineage = persisted_agent_lineage(
        conn,
        batch_attempt_id=attempt_id,
        agent_run_id=agent_run_id,
    )
    provider_chain = agent_lineage["provider_chain"]
    return {
        "attempt": dict(attempt),
        "agent": dict(agent),
        "request": request,
        "provider_attempts": _provider_attempt_rows(conn, attempt_id),
        "provider_chain": provider_chain,
        "agent_lineage": agent_lineage,
    }


def _reuse_existing_contract_if_exact(
    conn: sqlite3.Connection,
    run: Mapping[str, Any],
    item: Mapping[str, Any],
    checkpoint_root: Path,
    *,
    hooks: BatchATestHooks | None,
) -> bool:
    from . import answer_contract_generation_v2

    candidates = conn.execute(
        """
        select * from answer_contracts
        where question_id = ? and item_version = ?
          and question_digest_sha256 = ?
          and graph_version = ? and question_bank_version = ?
          and review_record_id = ? and generator_version = ?
          and status = 'approved'
        order by contract_version, id
        """,
        (
            item["question_id"],
            item["item_version"],
            item["question_digest_sha256"],
            run["graph_version"],
            run["bank_version"],
            item["review_record_id"],
            answer_contract_generation_v2.GENERATOR_VERSION,
        ),
    ).fetchall()
    if not candidates:
        return False
    eligible = []
    errors = []
    for contract_row in candidates:
        contract = dict(contract_row)
        provisional = {
            **dict(item),
            "status": "reused_approved",
            "contract_id": contract["id"],
            "contract_version": contract["contract_version"],
            "contract_digest_sha256": contract["contract_digest_sha256"],
            "designer_run_id": contract["generator_run_id"],
            "reviewer_run_id": contract["review_run_id"],
            "designer_batch_attempt_id": contract[
                "generator_batch_attempt_id"
            ],
            "reviewer_batch_attempt_id": contract["review_batch_attempt_id"],
            "checkpoint_digest_sha256": "",
        }
        try:
            authority = _validate_item_authority(
                conn,
                run,
                provisional,
                checkpoint_root,
                require_checkpoint=True,
            )
        except (TypeError, ValueError, sqlite3.Error) as exc:
            errors.append(str(exc))
            continue
        eligible.append((contract, authority))
    if len(eligible) != 1:
        reason = (
            "multiple exact eligible v2 contracts"
            if len(eligible) > 1
            else "preexisting v2 contract authority conflict: "
            + "; ".join(errors[:3])
        )
        raise ValueError(reason)
    contract, authority = eligible[0]
    now = _now_iso(hooks)
    with _immediate_transaction(conn):
        cursor = conn.execute(
            """
            update answer_contract_generation_run_items
            set status = 'reused_approved', contract_id = ?,
                contract_version = ?, contract_digest_sha256 = ?,
                designer_run_id = ?, reviewer_run_id = ?,
                designer_batch_attempt_id = ?, reviewer_batch_attempt_id = ?,
                checkpoint_digest_sha256 = ?, checkpoint_projection_json = ?,
                terminal_class = '',
                terminal_reason_code = '', updated_at = ?
            where id = ? and run_id = ? and status in ('pending','interrupted')
            """,
            (
                contract["id"],
                contract["contract_version"],
                contract["contract_digest_sha256"],
                contract["generator_run_id"],
                contract["review_run_id"],
                contract["generator_batch_attempt_id"],
                contract["review_batch_attempt_id"],
                authority["checkpoint_digest_sha256"],
                question_fingerprints.canonical_json(
                    authority["checkpoint_projection"]
                ),
                now,
                item["id"],
                run["id"],
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Batch A reused contract item state changed")
    return True


def _validate_item_authority(
    conn: sqlite3.Connection,
    run: Mapping[str, Any],
    item: Mapping[str, Any],
    checkpoint_root: Path,
    *,
    require_checkpoint: bool,
) -> dict[str, Any]:
    from . import answer_contract_generation_v2, assessment_policy, db

    question = _question_for_run_item(conn, item)
    contract = conn.execute(
        "select * from answer_contracts where id = ?",
        (item.get("contract_id"),),
    ).fetchone()
    if not contract:
        raise ValueError("Batch A approved item contract is missing")
    contract_values = dict(contract)
    if any(
        (
            item.get("status") not in {"approved", "reused_approved"},
            contract_values["question_id"] != item["question_id"],
            contract_values["item_version"] != item["item_version"],
            contract_values["question_digest_sha256"]
            != item["question_digest_sha256"],
            contract_values["graph_version"] != run["graph_version"],
            contract_values["question_bank_version"] != run["bank_version"],
            contract_values["review_record_id"] != item["review_record_id"],
            contract_values["contract_digest_sha256"]
            != item["contract_digest_sha256"],
            contract_values["status"] != "approved",
            contract_values["generator_version"]
            != answer_contract_generation_v2.GENERATOR_VERSION,
            bool(
                answer_contract_generation_v2.v2_scoring_policy_activation_blockers(
                    contract_values
                )
            ),
        )
    ):
        raise ValueError("Batch A approved contract authority mismatch")
    design_attempt_id = str(contract_values.get("generator_batch_attempt_id") or "")
    review_attempt_id = str(contract_values.get("review_batch_attempt_id") or "")
    if any(
        (
            design_attempt_id != item.get("designer_batch_attempt_id"),
            review_attempt_id != item.get("reviewer_batch_attempt_id"),
            contract_values["generator_run_id"] != item.get("designer_run_id"),
            contract_values["review_run_id"] != item.get("reviewer_run_id"),
        )
    ):
        raise ValueError("Batch A approved contract attempt lineage mismatch")
    design = _validate_historical_attempt(
        conn,
        run,
        item,
        role="designer",
        attempt_id=design_attempt_id,
        agent_run_id=contract_values["generator_run_id"],
    )
    review = _validate_historical_attempt(
        conn,
        run,
        item,
        role="reviewer",
        attempt_id=review_attempt_id,
        agent_run_id=contract_values["review_run_id"],
    )
    design_receipt = db.json_load(contract_values["design_receipt_json"], {})
    review_receipt = db.json_load(contract_values["review_receipt_json"], {})
    design_output = db.json_load(design["agent"]["output_json"], {})
    review_output = db.json_load(review["agent"]["output_json"], {})
    review_items = review_output.get("items") if isinstance(review_output, dict) else None
    if (
        not _valid_digest_payload(design_receipt)
        or not _valid_digest_payload(review_receipt)
        or design_receipt.get("agent_run_id") != contract_values["generator_run_id"]
        or design_receipt.get("batch_attempt_id") != design_attempt_id
        or design_receipt.get("agent_lineage") != design["agent_lineage"]
        or design_receipt.get("agent_lineage_digest_sha256")
        != design["agent_lineage"]["agent_lineage_digest_sha256"]
        or design_receipt.get("provider_chain") != design["provider_chain"]
        or design_receipt.get("provider_chain_digest_sha256")
        != design["provider_chain"]["provider_chain_digest_sha256"]
        or contract_values.get("generator_provider_chain_digest_sha256")
        != design["provider_chain"]["provider_chain_digest_sha256"]
        or design_receipt.get("output_digest_sha256") != _digest(design_output)
        or design_receipt.get("exact_live_lineage") is not True
        or review_receipt.get("agent_run_id") != contract_values["review_run_id"]
        or review_receipt.get("batch_attempt_id") != review_attempt_id
        or review_receipt.get("agent_lineage") != review["agent_lineage"]
        or review_receipt.get("agent_lineage_digest_sha256")
        != review["agent_lineage"]["agent_lineage_digest_sha256"]
        or review_receipt.get("provider_chain") != review["provider_chain"]
        or review_receipt.get("provider_chain_digest_sha256")
        != review["provider_chain"]["provider_chain_digest_sha256"]
        or contract_values.get("review_provider_chain_digest_sha256")
        != review["provider_chain"]["provider_chain_digest_sha256"]
        or review_receipt.get("output_digest_sha256") != _digest(review_output)
        or review_receipt.get("contract_digest_sha256")
        != contract_values["contract_digest_sha256"]
        or review_receipt.get("exact_live_lineage") is not True
        or not isinstance(review_items, list)
        or len(review_items) != 1
        or review_items[0].get("contract_verdict") != "approved"
        or review_items[0].get("issues") != []
        or float(review_items[0].get("confidence") or 0) < 0.8
    ):
        raise ValueError("Batch A approved contract receipts are invalid")
    score_points = db.json_load(contract_values["score_points_json"], None)
    reference_solution = db.json_load(
        contract_values["reference_solution_json"], None
    )
    if not isinstance(score_points, list) or not isinstance(reference_solution, dict):
        raise ValueError("Batch A approved contract content is malformed")
    skeleton = assessment_policy.build_contract_skeleton_v2(question)
    scoring_targets = [
        {
            key: deepcopy(point[key])
            for key in (
                "key",
                "criterion",
                "dimension",
                "required_for_pass",
                "reference_component",
            )
        }
        for point in score_points
    ]
    compiled = {
        "question_id": question["id"],
        "item_version": question["item_version"],
        "node_id": question["node_id"],
        "question_kind": question["kind"],
        "reference_solution": reference_solution,
        "scoring_targets": scoring_targets,
        "score_points": score_points,
        "design_profile_version": skeleton["profile_version"],
        "status": "draft_designed_v2",
    }
    if _digest(compiled) != contract_values["contract_digest_sha256"]:
        raise ValueError("Batch A approved contract digest is not reproducible")
    checkpoint_digest, checkpoint_projection = _checkpoint_projection_for_item(
        conn,
        checkpoint_root,
        run,
        item,
        require_final_contract=require_checkpoint,
        recover_missing=require_checkpoint,
    )
    return {
        "question_id": item["question_id"],
        "item_version": item["item_version"],
        "question_digest_sha256": item["question_digest_sha256"],
        "node_id": item["node_id"],
        "kind": item["kind"],
        "effective_evidence_role": item["effective_evidence_role"],
        "contract_id": contract_values["id"],
        "contract_version": int(contract_values["contract_version"]),
        "contract_digest_sha256": contract_values["contract_digest_sha256"],
        "designer_run_id": contract_values["generator_run_id"],
        "reviewer_run_id": contract_values["review_run_id"],
        "designer_batch_attempt_id": design_attempt_id,
        "reviewer_batch_attempt_id": review_attempt_id,
        "designer_provider_chain": design["provider_chain"],
        "reviewer_provider_chain": review["provider_chain"],
        "designer_agent_lineage": design["agent_lineage"],
        "reviewer_agent_lineage": review["agent_lineage"],
        "designer_provider_chain_digest_sha256": design["provider_chain"][
            "provider_chain_digest_sha256"
        ],
        "reviewer_provider_chain_digest_sha256": review["provider_chain"][
            "provider_chain_digest_sha256"
        ],
        "checkpoint_digest_sha256": checkpoint_digest,
        "checkpoint_projection": checkpoint_projection,
    }


def _blocked_integrity_report(
    conn: sqlite3.Connection,
    run_id: str,
    reason: str,
    hooks: BatchATestHooks | None,
) -> dict[str, Any]:
    now = _now_iso(hooks)
    with _immediate_transaction(conn):
        conn.execute(
            """
            update answer_contract_generation_runs
            set status = 'blocked_integrity', last_error_class = 'integrity_error',
                last_error = ?, terminal_count = terminal_count + 1,
                updated_at = ?, completed_at = coalesce(completed_at, ?)
            where id = ? and status <> 'blocked_integrity'
            """,
            (reason[:800], now, now, run_id),
        )
    row = conn.execute(
        "select model_calls, provider_attempts from answer_contract_generation_runs where id = ?",
        (run_id,),
    ).fetchone()
    return {
        "status": "blocked_integrity",
        "run_id": run_id,
        "reason_code": reason[:800],
        "model_calls": int(row["model_calls"] if row else 0),
        "provider_attempts": int(row["provider_attempts"] if row else 0),
        "production_authority": False,
        "activation_eligible": False,
        "receipt": None,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8") as handle:
            json.dump(
                dict(payload),
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _canonical_canary_receipt(
    run: Mapping[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    preflight = _persisted_preflight(run)
    if (
        run.get("preflight_status") != "passed"
        or preflight.get("preflight_pass") is not True
        or not run.get("completed_at")
    ):
        raise ValueError("Batch A receipt lacks completed preflight authority")
    body = {
        "receipt_schema_version": CANARY_RECEIPT_SCHEMA_VERSION,
        "receipt_kind": RUN_KIND_CANARY,
        "status": "sealed",
        "run_id": run["id"],
        "run_identity_digest_sha256": run["run_identity_digest_sha256"],
        "ledger_id": run["ledger_id"],
        "bank_version": run["bank_version"],
        "manifest_sha256": run["manifest_sha256"],
        "graph_version": run["graph_version"],
        "plan_digest_sha256": run["plan_digest_sha256"],
        "preflight_digest_sha256": run["preflight_digest_sha256"],
        "effective_evidence_role_policy_version": (
            EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
        ),
        "effective_evidence_role_policy_digest_sha256": (
            EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256
        ),
        "checkpoint_commitment_sha256": _digest(
            [
                {
                    "question_id": item["question_id"],
                    "checkpoint_digest_sha256": item[
                        "checkpoint_digest_sha256"
                    ],
                }
                for item in items
            ]
        ),
        "model_calls": int(run["model_calls"]),
        "provider_attempts": int(run["provider_attempts"]),
        "completed_at": run["completed_at"],
        "production_authority_scope": "canary_generation_gate_only",
        "production_authority": False,
        "activation_eligible": False,
        "items": items,
    }
    return {**body, "receipt_digest_sha256": _digest(body)}


def _integrity_audit_report(
    run: Mapping[str, Any], reason: str
) -> dict[str, Any]:
    preflight = None
    try:
        preflight = _persisted_preflight(run)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {
        "status": "blocked_integrity",
        "run_id": run.get("id"),
        "reason_code": reason[:800],
        "model_calls": int(run.get("model_calls") or 0),
        "provider_attempts": int(run.get("provider_attempts") or 0),
        "preflight": preflight,
        "production_authority": False,
        "activation_eligible": False,
        "receipt": None,
    }


def _seal_canary_receipt(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    run_id: str,
    claim: RunClaim,
    checkpoint_root: Path,
    hooks: BatchATestHooks | None,
) -> dict[str, Any]:
    del project_root
    receipt_path = (
        checkpoint_root.resolve()
        / "batch-a"
        / run_id
        / "canary-receipt.json"
    )
    with _immediate_transaction(conn):
        run_row = _require_current_claim(
            conn, claim, allowed_statuses={"running"}
        )
        run = dict(run_row)
        existing = conn.execute(
            "select * from answer_contract_generation_receipts where run_id = ?",
            (run_id,),
        ).fetchone()
        if existing:
            raise ValueError("running Batch A run already has a receipt")
        item_rows = conn.execute(
            "select * from answer_contract_generation_run_items where run_id = ? order by ordinal",
            (run_id,),
        ).fetchall()
        if len(item_rows) != CANARY_ITEM_COUNT:
            raise ValueError("Batch A completion requires forty items")
        items = [
            _validate_item_authority(
                conn,
                run,
                dict(item),
                checkpoint_root,
                require_checkpoint=True,
            )
            for item in item_rows
        ]
        semantic_count = conn.execute(
            "select count(*) from answer_contract_generation_attempts where run_id = ?",
            (run_id,),
        ).fetchone()[0]
        provider_count = conn.execute(
            """
            select count(*)
            from answer_contract_generation_provider_attempts provider
            join answer_contract_generation_attempts attempt
              on attempt.id = provider.batch_attempt_id
            where attempt.run_id = ?
            """,
            (run_id,),
        ).fetchone()[0]
        if (
            int(run["model_calls"]) != int(semantic_count)
            or int(run["provider_attempts"]) != int(provider_count)
        ):
            raise ValueError("Batch A completion counters are not exact")
        completed_at = _now_iso(hooks)
        cursor = conn.execute(
            """
            update answer_contract_generation_runs
            set completed_at = ?, updated_at = ?
            where id = ? and operation_generation = ? and claim_token = ?
              and status = 'running' and completed_at is null
            """,
            (
                completed_at,
                completed_at,
                run_id,
                claim.operation_generation,
                claim.claim_token,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Batch A completion timestamp lost its CAS claim")
        run = dict(
            conn.execute(
                "select * from answer_contract_generation_runs where id = ?",
                (run_id,),
            ).fetchone()
        )
        receipt = _canonical_canary_receipt(run, items)
        receipt_id = "ACRC-A-" + receipt["receipt_digest_sha256"][:24]
        conn.execute(
            """
            insert into answer_contract_generation_receipts(
              id, run_id, receipt_schema_version, receipt_kind,
              receipt_digest_sha256, payload_json, completed_at, status
            ) values (?, ?, ?, 'canary40', ?, ?, ?, 'sealed')
            """,
            (
                receipt_id,
                run_id,
                CANARY_RECEIPT_SCHEMA_VERSION,
                receipt["receipt_digest_sha256"],
                question_fingerprints.canonical_json(receipt),
                completed_at,
            ),
        )
        cursor = conn.execute(
            """
            update answer_contract_generation_runs
            set status='completed_passed', updated_at=?
            where id=? and operation_generation=? and claim_token=? and status='running'
            """,
            (
                completed_at,
                run_id,
                claim.operation_generation,
                claim.claim_token,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Batch A completion lost its CAS claim")
    _atomic_write_json(receipt_path, receipt)
    return {
        "status": "completed_passed",
        "run_id": run_id,
        "plan_digest_sha256": run["plan_digest_sha256"],
        "model_calls": int(run["model_calls"]),
        "provider_attempts": int(run["provider_attempts"]),
        "item_count": CANARY_ITEM_COUNT,
        "items": items,
        "preflight": _persisted_preflight(run),
        "receipt": receipt,
        "receipt_path": str(receipt_path),
        "production_authority": False,
        "activation_eligible": False,
    }
def run_v2_canary(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    designer: Callable[[dict[str, Any]], dict[str, Any]] | None,
    reviewer: Callable[[dict[str, Any]], dict[str, Any]] | None,
    checkpoint_root: Path,
    model_call_cap: int = CANARY_DEFAULT_MODEL_CALL_CAP,
    provider_attempt_cap: int = CANARY_DEFAULT_PROVIDER_ATTEMPT_CAP,
    max_items: int = CANARY_DEFAULT_MAX_ITEMS,
    invocation_wall_seconds: float = CANARY_DEFAULT_WALL_SECONDS,
    lifecycle_observer: BatchALifecycleObserver | None = None,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    if not callable(designer) or not callable(reviewer):
        raise TypeError("Batch A designer and reviewer must be callable")
    _validate_canary_limits(
        model_call_cap=model_call_cap,
        provider_attempt_cap=provider_attempt_cap,
        max_items=max_items,
        invocation_wall_seconds=invocation_wall_seconds,
    )
    from . import answer_contract_generation_v2, db

    started = (hooks or BatchATestHooks()).monotonic()
    wall_deadline = started + float(invocation_wall_seconds)
    with acquire_canonical_db_run_lock(conn, hooks=hooks):
        plan = build_v2_batch_plan(
            conn, project_root, run_kind=RUN_KIND_CANARY, hooks=hooks
        )
        run, claim = create_or_resume_v2_run(
            conn,
            project_root,
            plan=plan,
            checkpoint_root=checkpoint_root,
            model_call_cap=model_call_cap,
            provider_attempt_cap=provider_attempt_cap,
            hooks=hooks,
        )
        if run.get("_resume_action"):
            resume_report = run.get("_resume_report") or {}
            return {
                "status": run["status"],
                "run_id": run["id"],
                "reason_code": resume_report.get(
                    "reason_code", run["_resume_action"]
                ),
                "uncertainty_resolution": resume_report.get(
                    "resolutions", []
                ),
                "model_calls": int(run["model_calls"]),
                "provider_attempts": int(run["provider_attempts"]),
                "production_authority": False,
                "activation_eligible": False,
                "receipt": None,
            }
        if run["status"] == "completed_passed":
            try:
                return audit_v2_generation_run(
                    conn,
                    project_root,
                    run_id=run["id"],
                    checkpoint_root=checkpoint_root,
                    hooks=hooks,
                )
            except (TypeError, ValueError) as exc:
                return _blocked_integrity_report(
                    conn, run["id"], str(exc), hooks
                )
        if run["status"] == "completed_blocked":
            preflight_payload = None
            try:
                preflight_payload = _persisted_preflight(run)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            return {
                "status": "completed_blocked",
                "run_id": run["id"],
                "model_calls": int(run["model_calls"]),
                "provider_attempts": int(run["provider_attempts"]),
                "production_authority": False,
                "activation_eligible": False,
                "receipt": None,
                "preflight": preflight_payload,
                "blockers": json.loads(run["last_error"] or "[]"),
            }
        if run["status"] == "blocked_integrity":
            return _blocked_integrity_report(
                conn, run["id"], str(run["last_error"] or "blocked_integrity"), hooks
            )
        preflight = preflight_v2_canary(
            conn,
            project_root,
            run_id=run["id"],
            claim=claim,
            hooks=hooks,
        )
        if preflight["status"] == "completed_blocked":
            return preflight
        _heartbeat(conn, claim, hooks=hooks, force=True)
        if _stop_is_requested(hooks):
            return _interrupt_claimed_run(
                conn,
                claim,
                reason_code="signal_requested",
                hooks=hooks,
            )

        items = conn.execute(
            "select * from answer_contract_generation_run_items where run_id = ? order by ordinal",
            (run["id"],),
        ).fetchall()
        if len(items) != CANARY_ITEM_COUNT:
            return _blocked_integrity_report(
                conn, run["id"], "Batch A run item count changed", hooks
            )
        for item_row in items:
            _heartbeat(conn, claim, hooks=hooks)
            if _stop_is_requested(hooks):
                return _interrupt_claimed_run(
                    conn,
                    claim,
                    reason_code="signal_requested",
                    hooks=hooks,
                )
            if (hooks or BatchATestHooks()).monotonic() >= wall_deadline:
                now = _now_iso(hooks)
                with _immediate_transaction(conn):
                    _require_current_claim(
                        conn, claim, allowed_statuses={"running"}
                    )
                    conn.execute(
                        "update answer_contract_generation_runs set status='interrupted', last_error_class='wall_deadline', last_error='invocation_wall_deadline_exhausted', interrupted_at=?, updated_at=? where id=?",
                        (now, now, run["id"]),
                    )
                return {
                    "status": "interrupted",
                    "run_id": run["id"],
                    "reason_code": "invocation_wall_deadline_exhausted",
                    "production_authority": False,
                    "activation_eligible": False,
                    "receipt": None,
                }
            item = dict(
                conn.execute(
                    "select * from answer_contract_generation_run_items where id = ?",
                    (item_row["id"],),
                ).fetchone()
            )
            if item["status"] in {"approved", "reused_approved"}:
                try:
                    _validate_item_authority(
                        conn,
                        run,
                        item,
                        checkpoint_root,
                        require_checkpoint=bool(item["checkpoint_digest_sha256"]),
                    )
                except (TypeError, ValueError, sqlite3.Error) as exc:
                    return _blocked_integrity_report(
                        conn, run["id"], str(exc), hooks
                    )
                continue
            try:
                if _reuse_existing_contract_if_exact(
                    conn,
                    run,
                    item,
                    checkpoint_root,
                    hooks=hooks,
                ):
                    continue
            except (TypeError, ValueError, sqlite3.Error) as exc:
                return _blocked_integrity_report(
                    conn, run["id"], str(exc), hooks
                )
            question = _question_for_run_item(conn, item)
            try:
                wrapped_designer = _recovered_designer_callback(
                    conn,
                    claim=claim,
                    item=item,
                )
            except (TypeError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
                return _blocked_integrity_report(
                    conn, run["id"], str(exc), hooks
                )
            if wrapped_designer is None:
                wrapped_designer = _BatchSemanticCallback(
                    conn=conn,
                    plan=plan,
                    claim=claim,
                    run_item_id=item["id"],
                    role="designer",
                    callback=designer,
                    lifecycle_observer=lifecycle_observer,
                    model_call_cap=model_call_cap,
                    provider_attempt_cap=provider_attempt_cap,
                    wall_deadline_monotonic=wall_deadline,
                    hooks=hooks,
                )
            wrapped_reviewer = _BatchSemanticCallback(
                conn=conn,
                plan=plan,
                claim=claim,
                run_item_id=item["id"],
                role="reviewer",
                callback=reviewer,
                lifecycle_observer=lifecycle_observer,
                model_call_cap=model_call_cap,
                provider_attempt_cap=provider_attempt_cap,
                wall_deadline_monotonic=wall_deadline,
                hooks=hooks,
            )
            try:
                result = answer_contract_generation_v2.run_contract_repair_loop(
                    conn,
                    question=question,
                    graph_version=run["graph_version"],
                    bank_version=run["bank_version"],
                    review_record_id=item["review_record_id"],
                    designer=wrapped_designer,
                    reviewer=wrapped_reviewer,
                    checkpoint_root=checkpoint_root,
                )
            except BatchAStopRequested:
                return _interrupt_claimed_run(
                    conn,
                    claim,
                    reason_code="signal_requested",
                    hooks=hooks,
                )
            except BatchACommitUncertain as exc:
                now = _now_iso(hooks)
                with _immediate_transaction(conn):
                    _require_current_claim(
                        conn, claim, allowed_statuses={"running"}
                    )
                    conn.execute(
                        """
                        update answer_contract_generation_run_items
                        set status = 'interrupted', terminal_class = ?,
                            terminal_reason_code = ?, terminal_at = ?, updated_at = ?
                        where id = ?
                        """,
                        (exc.status, exc.batch_attempt_id, now, now, item["id"]),
                    )
                    conn.execute(
                        """
                        update answer_contract_generation_runs
                        set status = ?, last_error_class = ?, last_error = ?,
                            interrupted_at = ?, updated_at = ?
                        where id = ?
                        """,
                        (
                            exc.status,
                            exc.status,
                            exc.batch_attempt_id,
                            now,
                            now,
                            run["id"],
                        ),
                    )
                current_run = conn.execute(
                    "select model_calls, provider_attempts from answer_contract_generation_runs where id = ?",
                    (run["id"],),
                ).fetchone()
                return {
                    "status": exc.status,
                    "run_id": run["id"],
                    "reason_code": exc.batch_attempt_id,
                    "model_calls": int(current_run["model_calls"]),
                    "provider_attempts": int(current_run["provider_attempts"]),
                    "production_authority": False,
                    "activation_eligible": False,
                    "receipt": None,
                }
            except Exception as exc:
                now = _now_iso(hooks)
                with _immediate_transaction(conn):
                    _require_current_claim(
                        conn, claim, allowed_statuses={"running"}
                    )
                    conn.execute(
                        "update answer_contract_generation_run_items set status='terminal_failure', terminal_class=?, terminal_reason_code=?, terminal_at=?, updated_at=? where id=?",
                        (type(exc).__name__, str(exc)[:800], now, now, item["id"]),
                    )
                    conn.execute(
                        "update answer_contract_generation_runs set status='interrupted', terminal_count=terminal_count+1, last_error_class=?, last_error=?, interrupted_at=?, updated_at=? where id=?",
                        (type(exc).__name__, str(exc)[:800], now, now, run["id"]),
                    )
                current_run = conn.execute(
                    "select model_calls, provider_attempts from answer_contract_generation_runs where id = ?",
                    (run["id"],),
                ).fetchone()
                return {
                    "status": "interrupted",
                    "run_id": run["id"],
                    "error_class": type(exc).__name__,
                    "reason_code": str(exc)[:800],
                    "model_calls": int(current_run["model_calls"]),
                    "provider_attempts": int(current_run["provider_attempts"]),
                    "production_authority": False,
                    "activation_eligible": False,
                    "receipt": None,
                }
            if result.get("status") != "approved" or not result.get(
                "final_contract_id"
            ):
                now = _now_iso(hooks)
                with _immediate_transaction(conn):
                    _require_current_claim(
                        conn, claim, allowed_statuses={"running"}
                    )
                    conn.execute(
                        "update answer_contract_generation_run_items set status='routed', terminal_class=?, terminal_reason_code=?, terminal_at=?, updated_at=? where id=?",
                        (
                            str(result.get("status") or "not_approved"),
                            str(result.get("reason_code") or result.get("status") or "")[:800],
                            now,
                            now,
                            item["id"],
                        ),
                    )
                    conn.execute(
                        "update answer_contract_generation_runs set status='completed_blocked', terminal_count=terminal_count+1, last_error_class='item_not_approved', last_error=?, completed_at=?, updated_at=? where id=?",
                        (
                            json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)[:4000],
                            now,
                            now,
                            run["id"],
                        ),
                    )
                current_run = conn.execute(
                    "select * from answer_contract_generation_runs where id = ?",
                    (run["id"],),
                ).fetchone()
                return {
                    "status": "completed_blocked",
                    "run_id": run["id"],
                    "item_result": result,
                    "model_calls": int(current_run["model_calls"]),
                    "provider_attempts": int(current_run["provider_attempts"]),
                    "production_authority": False,
                    "activation_eligible": False,
                    "receipt": None,
                }
            contract = conn.execute(
                "select * from answer_contracts where id = ?",
                (result["final_contract_id"],),
            ).fetchone()
            if not contract:
                return _blocked_integrity_report(
                    conn, run["id"], "approved Batch A contract disappeared", hooks
                )
            contract = dict(contract)
            design_attempt = conn.execute(
                "select batch_attempt_id from agent_runs where id = ?",
                (contract["generator_run_id"],),
            ).fetchone()
            review_attempt = conn.execute(
                "select batch_attempt_id from agent_runs where id = ?",
                (contract["review_run_id"],),
            ).fetchone()
            if not design_attempt or not review_attempt:
                return _blocked_integrity_report(
                    conn, run["id"], "approved contract lacks batch attempts", hooks
                )
            provisional_item = {
                **item,
                "status": "approved",
                "contract_id": contract["id"],
                "contract_version": contract["contract_version"],
                "contract_digest_sha256": contract["contract_digest_sha256"],
                "designer_run_id": contract["generator_run_id"],
                "reviewer_run_id": contract["review_run_id"],
                "designer_batch_attempt_id": design_attempt["batch_attempt_id"],
                "reviewer_batch_attempt_id": review_attempt["batch_attempt_id"],
                "checkpoint_digest_sha256": "",
            }
            checkpoint_digest, checkpoint_projection = _checkpoint_projection_for_item(
                conn,
                checkpoint_root,
                run,
                provisional_item,
                require_final_contract=True,
            )
            now = _now_iso(hooks)
            with _immediate_transaction(conn):
                _require_current_claim(
                    conn, claim, allowed_statuses={"running"}
                )
                conn.execute(
                    """
                    update answer_contract_generation_run_items
                    set status='approved', contract_id=?, contract_version=?,
                        contract_digest_sha256=?, designer_run_id=?, reviewer_run_id=?,
                        designer_batch_attempt_id=?, reviewer_batch_attempt_id=?,
                        checkpoint_digest_sha256=?, checkpoint_projection_json=?,
                        updated_at=?
                    where id=?
                    """,
                    (
                        contract["id"],
                        contract["contract_version"],
                        contract["contract_digest_sha256"],
                        contract["generator_run_id"],
                        contract["review_run_id"],
                        design_attempt["batch_attempt_id"],
                        review_attempt["batch_attempt_id"],
                        checkpoint_digest,
                        question_fingerprints.canonical_json(
                            checkpoint_projection
                        ),
                        now,
                        item["id"],
                    ),
                )
        return _seal_canary_receipt(
            conn,
            project_root,
            run_id=run["id"],
            claim=claim,
            checkpoint_root=checkpoint_root,
            hooks=hooks,
        )


def audit_v2_generation_run(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    run_id: str,
    checkpoint_root: Path,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    run_row = conn.execute(
        "select * from answer_contract_generation_runs where id = ?",
        (run_id,),
    ).fetchone()
    if not run_row or run_row["run_kind"] != RUN_KIND_CANARY:
        raise ValueError("Batch A generation run does not exist")
    run = dict(run_row)
    if run["status"] != "completed_passed":
        uncertainty = _scan_commit_uncertainty(
            conn,
            run,
            resolve=True,
            hooks=hooks,
            checkpoint_root=checkpoint_root,
        )
        if uncertainty is not None:
            refreshed = dict(
                conn.execute(
                    "select * from answer_contract_generation_runs where id = ?",
                    (run_id,),
                ).fetchone()
            )
            return {
                "status": uncertainty["status"],
                "run_id": run_id,
                "reason_code": uncertainty["reason_code"],
                "uncertainty_resolution": uncertainty["resolutions"],
                "model_calls": int(refreshed["model_calls"]),
                "provider_attempts": int(refreshed["provider_attempts"]),
                "production_authority": False,
                "activation_eligible": False,
                "receipt": None,
            }
        raise ValueError("Batch A historical receipt audit requires completed_passed")
    try:
        preflight = _persisted_preflight(run)
        item_rows = conn.execute(
            "select * from answer_contract_generation_run_items where run_id = ? order by ordinal",
            (run_id,),
        ).fetchall()
        if len(item_rows) != CANARY_ITEM_COUNT:
            raise ValueError("Batch A run does not contain forty items")
        items = [
            _validate_item_authority(
                conn,
                run,
                dict(item),
                checkpoint_root,
                require_checkpoint=True,
            )
            for item in item_rows
        ]
        semantic_count = conn.execute(
            "select count(*) from answer_contract_generation_attempts where run_id = ?",
            (run_id,),
        ).fetchone()[0]
        provider_count = conn.execute(
            """
            select count(*)
            from answer_contract_generation_provider_attempts provider
            join answer_contract_generation_attempts attempt
              on attempt.id = provider.batch_attempt_id
            where attempt.run_id = ?
            """,
            (run_id,),
        ).fetchone()[0]
        if (
            int(run["model_calls"]) != int(semantic_count)
            or int(run["provider_attempts"]) != int(provider_count)
        ):
            raise ValueError("Batch A cumulative counters do not match attempts")
        expected_receipt = _canonical_canary_receipt(run, items)
        receipt_rows = conn.execute(
            "select * from answer_contract_generation_receipts where run_id = ?",
            (run_id,),
        ).fetchall()
        if len(receipt_rows) != 1:
            raise ValueError("completed Batch A run lacks one canonical receipt")
        receipt_row = receipt_rows[0]
        expected_payload_json = question_fingerprints.canonical_json(
            expected_receipt
        )
        if any(
            (
                receipt_row["receipt_schema_version"]
                != CANARY_RECEIPT_SCHEMA_VERSION,
                receipt_row["receipt_kind"] != RUN_KIND_CANARY,
                receipt_row["status"] != "sealed",
                receipt_row["completed_at"] != run["completed_at"],
                receipt_row["receipt_digest_sha256"]
                != expected_receipt["receipt_digest_sha256"],
                receipt_row["payload_json"] != expected_payload_json,
            )
        ):
            raise ValueError("Batch A persisted receipt differs from DB facts")
        receipt_path = (
            checkpoint_root.resolve()
            / "batch-a"
            / run_id
            / "canary-receipt.json"
        )
        if receipt_path.exists():
            projected_receipt = json.loads(
                receipt_path.read_text(encoding="utf-8")
            )
            if projected_receipt != expected_receipt:
                raise ValueError("Batch A receipt projection conflicts with DB")
        else:
            _atomic_write_json(receipt_path, expected_receipt)
    except (TypeError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        return _integrity_audit_report(run, str(exc))

    current_authority = True
    try:
        plan = build_v2_batch_plan(
            conn, project_root, run_kind=RUN_KIND_CANARY
        )
        current_authority = not any(
            (
                run["plan_digest_sha256"] != plan["plan_digest_sha256"],
                run["bank_version"] != plan["bank_version"],
                run["manifest_sha256"] != plan["manifest_sha256"],
                run["graph_version"] != plan["graph_version"],
            )
        )
    except (TypeError, ValueError, sqlite3.Error):
        current_authority = False
    return {
        "status": "completed_passed" if current_authority else "not_current_authority",
        "run_id": run_id,
        "plan_digest_sha256": run["plan_digest_sha256"],
        "model_calls": int(run["model_calls"]),
        "provider_attempts": int(run["provider_attempts"]),
        "item_count": len(items),
        "items": items,
        "preflight": preflight,
        "receipt": expected_receipt,
        "production_authority": False,
        "activation_eligible": False,
    }


def verify_v2_generation_receipt(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    receipt_path: Path,
    checkpoint_root: Path,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    del hooks
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Batch A receipt is unreadable") from exc
    exact_fields = {
        "receipt_schema_version",
        "receipt_kind",
        "status",
        "run_id",
        "run_identity_digest_sha256",
        "ledger_id",
        "bank_version",
        "manifest_sha256",
        "graph_version",
        "plan_digest_sha256",
        "preflight_digest_sha256",
        "effective_evidence_role_policy_version",
        "effective_evidence_role_policy_digest_sha256",
        "checkpoint_commitment_sha256",
        "model_calls",
        "provider_attempts",
        "completed_at",
        "production_authority_scope",
        "production_authority",
        "activation_eligible",
        "items",
        "receipt_digest_sha256",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != exact_fields
        or not _valid_digest_payload(receipt)
        or receipt.get("receipt_schema_version")
        != CANARY_RECEIPT_SCHEMA_VERSION
        or receipt.get("receipt_kind") != RUN_KIND_CANARY
        or receipt.get("status") != "sealed"
        or receipt.get("production_authority_scope")
        != "canary_generation_gate_only"
        or receipt.get("production_authority") is not False
        or receipt.get("activation_eligible") is not False
    ):
        raise ValueError("Batch A receipt contract is invalid")
    persisted = conn.execute(
        "select * from answer_contract_generation_receipts where run_id = ?",
        (receipt["run_id"],),
    ).fetchone()
    if (
        not persisted
        or persisted["receipt_digest_sha256"]
        != receipt["receipt_digest_sha256"]
        or json.loads(persisted["payload_json"]) != receipt
    ):
        raise ValueError("Batch A receipt is not DB-authoritative")
    report = audit_v2_generation_run(
        conn,
        project_root,
        run_id=receipt["run_id"],
        checkpoint_root=checkpoint_root,
    )
    if (
        report.get("status") != "completed_passed"
        or report.get("receipt") != receipt
    ):
        raise ValueError("Batch A receipt does not match the current DB audit")
    return report
