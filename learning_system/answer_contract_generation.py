from __future__ import annotations

import json
import sqlite3
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from . import (
    answer_contract_activation,
    answer_contract_batch_v2,
    assessment_policy,
    db,
    internal_agents,
    model_router,
    question_fingerprints,
    semantic_agents,
)


AGENT_KEY = "answer_contract_designer_agent"
PHASE = "answer_contract_design"
REVIEWER_AGENT_KEY = "answer_contract_reviewer_agent"
REVIEWER_PHASE = "answer_contract_review"
DESIGN_SOURCE = "semantic_designer_local_compiler.v1"
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (20.0, 60.0)
MAX_RETRY_AFTER_SECONDS = 180.0
ITEM_WALL_SECONDS = 180.0

RunClaim = answer_contract_batch_v2.RunClaim
BatchATestHooks = answer_contract_batch_v2.BatchATestHooks
BatchASkeletonBlocked = answer_contract_batch_v2.BatchASkeletonBlocked
BatchALifecycleObserver = answer_contract_batch_v2.BatchALifecycleObserver
EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION = (
    answer_contract_batch_v2.EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
)
CANARY_DEFAULT_MODEL_CALL_CAP = (
    answer_contract_batch_v2.CANARY_DEFAULT_MODEL_CALL_CAP
)
CANARY_HARD_MODEL_CALL_CAP = answer_contract_batch_v2.CANARY_HARD_MODEL_CALL_CAP
CANARY_DEFAULT_PROVIDER_ATTEMPT_CAP = (
    answer_contract_batch_v2.CANARY_DEFAULT_PROVIDER_ATTEMPT_CAP
)
CANARY_HARD_PROVIDER_ATTEMPT_CAP = (
    answer_contract_batch_v2.CANARY_HARD_PROVIDER_ATTEMPT_CAP
)
CANARY_DEFAULT_MAX_ITEMS = answer_contract_batch_v2.CANARY_DEFAULT_MAX_ITEMS
CANARY_HARD_MAX_ITEMS = answer_contract_batch_v2.CANARY_HARD_MAX_ITEMS
CANARY_DEFAULT_WALL_SECONDS = (
    answer_contract_batch_v2.CANARY_DEFAULT_WALL_SECONDS
)
CANARY_HARD_WALL_SECONDS = answer_contract_batch_v2.CANARY_HARD_WALL_SECONDS


class DesignRunError(RuntimeError):
    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


def _digest(value: Any) -> str:
    return question_fingerprints.canonical_sha256(value)


def _receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "receipt_digest_sha256": _digest(payload)}


def _valid_receipt(payload: Any) -> bool:
    if not isinstance(payload, dict) or "receipt_digest_sha256" not in payload:
        return False
    body = {
        key: value
        for key, value in payload.items()
        if key != "receipt_digest_sha256"
    }
    return payload["receipt_digest_sha256"] == _digest(body)


def _safe_component(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty path component")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe {field}")
    return value


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _question_digest(question: dict[str, Any]) -> str:
    return _digest(
        {
            "question_id": question["id"],
            "item_version": question["item_version"],
            "node_id": question["node_id"],
            "kind": question["kind"],
            "prompt": question["prompt"],
            "answer_format": question.get("answer_format"),
            "expected_answer": question.get("expected_answer"),
            "solution_steps": question.get("solution_steps") or [],
        }
    )


def build_design_packet(
    *,
    question: dict[str, Any],
    skeleton: dict[str, Any],
    graph_version: str,
    bank_version: str,
    review_record_id: str = "",
) -> dict[str, Any]:
    if not isinstance(question, dict) or not isinstance(skeleton, dict):
        raise TypeError("question and skeleton must be mappings")
    if skeleton != assessment_policy.build_contract_skeleton(question):
        raise ValueError("design skeleton is not authoritative for the question")
    question_digest = _question_digest(question)
    profile_digest = _digest(skeleton)
    item_handle = "design-item-" + _digest(
        {
            "question_id": question["id"],
            "item_version": question["item_version"],
            "question_digest_sha256": question_digest,
            "profile_digest_sha256": profile_digest,
        }
    )[:20]
    sealed_skeleton = {**deepcopy(skeleton), "item_handle": item_handle}
    generation_input_digest = _digest(
        {
            "item_handle": item_handle,
            "question_id": question["id"],
            "item_version": question["item_version"],
            "node_id": question["node_id"],
            "graph_version": graph_version,
            "bank_version": bank_version,
            "question_digest_sha256": question_digest,
            "profile_digest_sha256": profile_digest,
        }
    )
    return {
        "item_handle": item_handle,
        "question_id": question["id"],
        "item_version": question["item_version"],
        "node_id": question["node_id"],
        "question_kind": question["kind"],
        "graph_version": graph_version,
        "bank_version": bank_version,
        "review_record_id": review_record_id,
        "question_digest_sha256": question_digest,
        "profile_digest_sha256": profile_digest,
        "generation_input_digest_sha256": generation_input_digest,
        "skeleton": sealed_skeleton,
        "question": {
            "prompt": question["prompt"],
            "answer_format": question.get("answer_format"),
            "expected_answer": deepcopy(question.get("expected_answer")),
            "solution_steps": deepcopy(question.get("solution_steps") or []),
        },
    }


def semantic_design_request(
    packet: dict[str, Any],
) -> semantic_agents.SemanticAgentRequest:
    if not isinstance(packet, dict):
        raise TypeError("design packet must be a mapping")
    trusted_context = {
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "item_handle": packet["item_handle"],
        "question_id": packet["question_id"],
        "item_version": packet["item_version"],
        "node_id": packet["node_id"],
        "question_kind": packet["question_kind"],
        "graph_version": packet["graph_version"],
        "bank_version": packet["bank_version"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "profile_digest_sha256": packet["profile_digest_sha256"],
        "generation_input_digest_sha256": packet[
            "generation_input_digest_sha256"
        ],
        "profile_version": packet["skeleton"]["profile_version"],
        "slots": deepcopy(packet["skeleton"]["slots"]),
    }
    return semantic_agents.SemanticAgentRequest(
        agent_key=AGENT_KEY,
        phase=PHASE,
        trusted_context=trusted_context,
        untrusted_payload={"question": deepcopy(packet["question"])},
        provider_mode="live_model",
        source_refs={
            "question_digest_sha256": packet["question_digest_sha256"]
        },
    )


def build_design_plan(
    conn: sqlite3.Connection, project_root: Path
) -> dict[str, Any]:
    del project_root
    ledger = answer_contract_activation._active_ledger(conn)
    bank_version = str(ledger["question_bank_version"])
    questions = answer_contract_activation._authoritative_questions(
        conn, bank_version
    )
    contract = internal_agents.load_v5_contract_for_agent(AGENT_KEY)
    route = model_router.answer_contract_design_route()
    items = [
        build_design_packet(
            question=question,
            skeleton=assessment_policy.build_contract_skeleton(question),
            graph_version=str(ledger.get("graph_version") or ""),
            bank_version=bank_version,
            review_record_id=review_record_id,
        )
        for question, review_record_id in questions
    ]
    plan = {
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "bank_version": bank_version,
        "graph_version": str(ledger.get("graph_version") or ""),
        "model_alias": route.model_alias,
        "prompt_version_id": contract["prompt_version_id"],
        "response_schema_version": contract["response_schema_version"],
        "prompt_template_sha256": internal_agents.file_sha256(
            internal_agents.prompt_path_for_contract(contract)
        ),
        "response_schema_sha256": internal_agents.canonical_json_sha256(
            contract["response_schema"]
        ),
        "items": items,
    }
    plan["plan_digest_sha256"] = _digest(plan)
    return plan


def persisted_draft_for_review(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    review_record_id: str,
) -> tuple[str, dict[str, Any], str] | None:
    row = conn.execute(
        """
        select * from answer_contracts
        where question_id = ? and item_version = ? and status = 'review_pending'
        order by contract_version desc, created_at desc, id desc
        limit 1
        """,
        (question["id"], question["item_version"]),
    ).fetchone()
    if not row:
        return None
    if row["review_record_id"] != review_record_id:
        raise ValueError("persisted draft question review lineage is stale")
    skeleton = assessment_policy.build_contract_skeleton(question)
    packet = build_design_packet(
        question=question,
        skeleton=skeleton,
        graph_version=row["graph_version"],
        bank_version=row["question_bank_version"],
        review_record_id=review_record_id,
    )
    if row["question_digest_sha256"] != packet["question_digest_sha256"]:
        raise ValueError("persisted draft question digest is stale")
    if (
        row["generation_input_digest_sha256"]
        != packet["generation_input_digest_sha256"]
    ):
        raise ValueError("persisted draft generation input is stale")
    checkpoint = db.json_load(row["review_receipt_json"], {})
    contract = internal_agents.load_v5_contract_for_agent(AGENT_KEY)
    route = model_router.answer_contract_design_route()
    plan = {
        "bank_version": packet["bank_version"],
        "model_alias": route.model_alias,
        "prompt_version_id": contract["prompt_version_id"],
        "prompt_template_sha256": internal_agents.file_sha256(
            internal_agents.prompt_path_for_contract(contract)
        ),
        "response_schema_version": contract["response_schema_version"],
        "response_schema_sha256": internal_agents.canonical_json_sha256(
            contract["response_schema"]
        ),
    }
    validate_design_checkpoint(
        plan,
        packet,
        checkpoint,
        conn=conn,
        require_live=True,
    )
    compiled = checkpoint["compiled_contract"]
    _validate_generation_row(row, packet, compiled, checkpoint)
    draft = {
        "stable_contract_id": row["stable_contract_id"],
        "contract_version": int(row["contract_version"]),
        **deepcopy(compiled),
        "status": "review_pending",
        "design_source": DESIGN_SOURCE,
    }
    return row["id"], draft, row["contract_digest_sha256"]


def make_live_designer(
    conn: sqlite3.Connection,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    route = model_router.answer_contract_design_route()
    if not route.enabled:
        raise ValueError("model_not_configured")

    def designer(packet: dict[str, Any]) -> dict[str, Any]:
        request = semantic_design_request(packet)
        envelope = semantic_agents.call_answer_contract_designer_agent(request)
        if (
            envelope.agent_key != AGENT_KEY
            or envelope.phase != PHASE
            or envelope.status != "accepted"
            or envelope.provider_mode != "live_model"
        ):
            raise ValueError("answer contract designer did not return accepted live lineage")
        compiled = _compiled_contract(packet, envelope.output)
        del compiled
        contract = internal_agents.load_v5_contract_for_agent(AGENT_KEY)
        route_meta = envelope.route_meta or {}
        expected_meta = {
            "prompt_template_sha256": internal_agents.file_sha256(
                internal_agents.prompt_path_for_contract(contract)
            ),
            "rendered_prompt_sha256": semantic_agents.rendered_prompt_sha256_for_request(
                request
            ),
            "response_schema_sha256": internal_agents.canonical_json_sha256(
                contract["response_schema"]
            ),
        }
        if any(route_meta.get(field) != value for field, value in expected_meta.items()):
            raise ValueError("answer contract designer route metadata mismatch")
        input_refs = {
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "item_handle": packet["item_handle"],
            "question_digest_sha256": packet["question_digest_sha256"],
            "profile_digest_sha256": packet["profile_digest_sha256"],
        }
        run_id = f"AR-{uuid.uuid4().hex[:12]}"
        output_digest = _digest(envelope.output)
        with conn:
            conn.execute(
                """
                insert into agent_runs(
                  id, agent_key, engine_type, session_id, phase, trigger,
                  input_refs_json, input_digest_sha256, prompt_version_id,
                  prompt_template_sha256, rendered_prompt_sha256, model_provider,
                  model_name, model_alias, model_params_json,
                  response_schema_version, response_schema_sha256, status,
                  confidence, output_json, output_digest_sha256,
                  validation_errors_json, error_reason, created_at
                ) values (?, ?, 'internal_learning_agent', null, ?,
                          'answer_contract_generation', ?, ?, ?, ?, ?, 'openai',
                          ?, ?, ?, ?, ?, 'accepted', ?, ?, ?, '[]', '', ?)
                """,
                (
                    run_id,
                    AGENT_KEY,
                    PHASE,
                    db.json_dump(input_refs),
                    _digest(input_refs),
                    contract["prompt_version_id"],
                    expected_meta["prompt_template_sha256"],
                    expected_meta["rendered_prompt_sha256"],
                    route.model,
                    route.model_alias,
                    db.json_dump({"temperature": 0}),
                    contract["response_schema_version"],
                    expected_meta["response_schema_sha256"],
                    float(envelope.confidence),
                    db.json_dump(envelope.output),
                    output_digest,
                    db.now_iso(),
                ),
            )
        return {
            "agent_key": AGENT_KEY,
            "phase": PHASE,
            "status": "accepted",
            "provider_mode": "live_model",
            "question_digest_sha256": packet["question_digest_sha256"],
            "profile_digest_sha256": packet["profile_digest_sha256"],
            "agent_run_id": run_id,
            "generator_run_id": run_id,
            "transport_endpoint": route_meta.get(
                "structured_json_endpoint", "responses"
            ),
            "structured_json_mode": route_meta.get(
                "structured_json_mode", "json_schema"
            ),
            "output": deepcopy(envelope.output),
        }

    designer.transport_timeout_seconds = float(route.timeout_seconds)  # type: ignore[attr-defined]
    designer.current_transport_timeout_seconds = float(route.timeout_seconds)  # type: ignore[attr-defined]
    designer.transport_endpoint = "responses"  # type: ignore[attr-defined]
    designer.structured_json_mode = "json_schema"  # type: ignore[attr-defined]
    return designer


def _compiled_contract(
    packet: dict[str, Any], output: dict[str, Any]
) -> dict[str, Any]:
    contract_meta = internal_agents.load_v5_contract_for_agent(AGENT_KEY)
    if (
        not isinstance(output, dict)
        or set(output) != {"schema_version", "items"}
        or output.get("schema_version")
        != contract_meta["response_schema_version"]
    ):
        raise ValueError("designer output schema lineage mismatch")
    question = {
        "id": packet["question_id"],
        "item_version": packet["item_version"],
        "node_id": packet["node_id"],
        "kind": packet["question_kind"],
        **deepcopy(packet["question"]),
    }
    compiled = assessment_policy.compile_answer_contract(
        question, packet["skeleton"], output["items"]
    )
    return compiled


def _exact_live_designer_run(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    packet: dict[str, Any],
    checkpoint: dict[str, Any],
) -> sqlite3.Row:
    run_id = checkpoint.get("agent_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("design checkpoint requires a live generator_run_id")
    row = conn.execute("select * from agent_runs where id = ?", (run_id,)).fetchone()
    if not row:
        raise ValueError("designer agent run does not exist")
    request = semantic_design_request(packet)
    expected = {
        "agent_key": AGENT_KEY,
        "engine_type": "internal_learning_agent",
        "phase": PHASE,
        "trigger": "answer_contract_generation",
        "status": "accepted",
        "model_provider": "openai",
        "model_name": plan["model_alias"],
        "model_alias": plan["model_alias"],
        "prompt_version_id": plan["prompt_version_id"],
        "prompt_template_sha256": plan["prompt_template_sha256"],
        "rendered_prompt_sha256": semantic_agents.rendered_prompt_sha256_for_request(
            request
        ),
        "response_schema_version": plan["response_schema_version"],
        "response_schema_sha256": plan["response_schema_sha256"],
        "input_digest_sha256": _digest(
            {
                "question_id": packet["question_id"],
                "item_version": packet["item_version"],
                "item_handle": packet["item_handle"],
                "question_digest_sha256": packet["question_digest_sha256"],
                "profile_digest_sha256": packet["profile_digest_sha256"],
            }
        ),
        "output_digest_sha256": _digest(checkpoint["output"]),
        "error_reason": "",
    }
    if any(row[field] != value for field, value in expected.items()):
        raise ValueError("designer agent run lineage is not exact live evidence")
    if float(row["confidence"] or 0) < 0.8:
        raise ValueError("designer agent run confidence is below 0.8")
    if db.json_load(row["input_refs_json"], {}) != {
        "question_id": packet["question_id"],
        "item_version": packet["item_version"],
        "item_handle": packet["item_handle"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "profile_digest_sha256": packet["profile_digest_sha256"],
    }:
        raise ValueError("designer agent run input refs mismatch")
    if db.json_load(row["model_params_json"], {}) != {"temperature": 0}:
        raise ValueError("designer agent run model params mismatch")
    if db.json_load(row["validation_errors_json"], []) != []:
        raise ValueError("designer agent run has validation errors")
    if db.json_load(row["output_json"], None) != checkpoint["output"]:
        raise ValueError("designer agent run output mismatch")
    return row


def _checkpoint_path(root: Path, packet: dict[str, Any]) -> Path:
    root = root.absolute()
    target = (
        root
        / _safe_component(packet["bank_version"], "bank_version")
        / _safe_component(packet["node_id"], "node_id")
        / f"{_safe_component(packet['question_id'], 'question_id')}.json"
    )
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("design checkpoint escapes root") from exc
    return target


def _failure_checkpoint_path(root: Path, packet: dict[str, Any]) -> Path:
    return _checkpoint_path(root, packet).with_suffix(".failure.json")


def _retryable(exc: Exception) -> bool:
    if getattr(exc, "retryable", False):
        return True
    if getattr(exc, "status_code", None) in {429, 500, 502, 503, 504}:
        return True
    return model_router.is_retryable_model_call_error(exc)


def _retry_delay(exc: Exception, attempt_index: int) -> float:
    base = BACKOFF_SECONDS[min(attempt_index, len(BACKOFF_SECONDS) - 1)]
    retry_after = getattr(exc, "retry_after_seconds", None)
    if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool):
        return max(base, min(MAX_RETRY_AFTER_SECONDS, max(0.0, float(retry_after))))
    return base


def _error_metadata(exc: Exception, designer: Any) -> dict[str, Any]:
    endpoint = (
        getattr(exc, "endpoint", "")
        or getattr(designer, "transport_endpoint", "")
        or "responses"
    )
    mode = (
        getattr(exc, "structured_json_mode", "")
        or getattr(designer, "structured_json_mode", "")
        or "json_schema"
    )
    return {
        "error_type": type(exc).__name__,
        "message": str(exc)[:800],
        "status_code": getattr(exc, "status_code", None),
        "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
        "transport_endpoint": endpoint,
        "structured_json_mode": mode,
    }


def _terminal_failure_receipt(
    plan: dict[str, Any],
    packet: dict[str, Any],
    *,
    attempts: list[dict[str, Any]],
    model_calls: int,
    wall_time_seconds: float,
    wall_deadline_seconds: float,
    error: Exception,
    designer: Any,
) -> dict[str, Any]:
    return _receipt(
        {
            "sealed": True,
            "status": "terminal_failure",
            "agent_key": AGENT_KEY,
            "phase": PHASE,
            "bank_version": plan["bank_version"],
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "question_digest_sha256": packet["question_digest_sha256"],
            "profile_digest_sha256": packet["profile_digest_sha256"],
            "generation_input_digest_sha256": packet[
                "generation_input_digest_sha256"
            ],
            "item_handle": packet["item_handle"],
            "attempt_budget": MAX_ATTEMPTS,
            "attempt_count": len(attempts),
            "model_calls": model_calls,
            "wall_time_seconds": round(max(0.0, wall_time_seconds), 6),
            "wall_deadline_seconds": float(wall_deadline_seconds),
            "attempts": deepcopy(attempts),
            "terminal_error": _error_metadata(error, designer),
            "activation_eligible": False,
        }
    )


def _load_terminal_failure(
    path: Path, plan: dict[str, Any], packet: dict[str, Any]
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = {
        "sealed": True,
        "status": "terminal_failure",
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "bank_version": plan["bank_version"],
        "question_id": packet["question_id"],
        "item_version": packet["item_version"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "profile_digest_sha256": packet["profile_digest_sha256"],
        "generation_input_digest_sha256": packet[
            "generation_input_digest_sha256"
        ],
        "item_handle": packet["item_handle"],
        "attempt_budget": MAX_ATTEMPTS,
        "activation_eligible": False,
    }
    if not _valid_receipt(receipt):
        return None
    if any(receipt.get(key) != value for key, value in expected.items()):
        return None
    if receipt.get("attempt_count") != len(receipt.get("attempts") or []):
        return None
    if receipt.get("model_calls") != receipt.get("attempt_count"):
        return None
    return receipt


def _accepted_checkpoint(
    plan: dict[str, Any],
    packet: dict[str, Any],
    envelope: dict[str, Any],
    *,
    attempts: list[dict[str, Any]],
    model_calls: int,
    wall_time_seconds: float,
    wall_deadline_seconds: float,
) -> dict[str, Any]:
    expected = {
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "status": "accepted",
        "provider_mode": "live_model",
        "question_digest_sha256": packet["question_digest_sha256"],
        "profile_digest_sha256": packet["profile_digest_sha256"],
    }
    if not isinstance(envelope, dict) or any(
        envelope.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("designer envelope lineage mismatch")
    run_id = envelope.get("agent_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("live designer envelope requires an agent run id")
    if envelope.get("generator_run_id") != run_id:
        raise ValueError("live designer envelope generator run lineage mismatch")
    compiled = _compiled_contract(packet, envelope.get("output"))
    return _receipt(
        {
            "sealed": True,
            "status": "accepted",
            "agent_key": AGENT_KEY,
            "phase": PHASE,
            "provider_mode": "live_model",
            "agent_run_id": run_id,
            "generator_run_id": run_id,
            "model_alias": plan["model_alias"],
            "prompt_version_id": plan["prompt_version_id"],
            "prompt_template_sha256": plan["prompt_template_sha256"],
            "response_schema_version": plan["response_schema_version"],
            "response_schema_sha256": plan["response_schema_sha256"],
            "bank_version": plan["bank_version"],
            "question_id": packet["question_id"],
            "item_version": packet["item_version"],
            "question_digest_sha256": packet["question_digest_sha256"],
            "profile_digest_sha256": packet["profile_digest_sha256"],
            "generation_input_digest_sha256": packet[
                "generation_input_digest_sha256"
            ],
            "item_handle": packet["item_handle"],
            "attempt_budget": MAX_ATTEMPTS,
            "attempt_count": len(attempts),
            "attempts": deepcopy(attempts),
            "model_calls": model_calls,
            "wall_time_seconds": round(max(0.0, wall_time_seconds), 6),
            "wall_deadline_seconds": float(wall_deadline_seconds),
            "transport_endpoint": envelope.get(
                "transport_endpoint", "responses"
            ),
            "structured_json_mode": envelope.get(
                "structured_json_mode", "json_schema"
            ),
            "output": deepcopy(envelope["output"]),
            "compiled_contract": compiled,
            "compiled_contract_digest_sha256": _digest(compiled),
            "activation_eligible": False,
        }
    )


def _execute_design_packet(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    packet: dict[str, Any],
    designer: Callable[[dict[str, Any]], dict[str, Any]],
    failure_path: Path,
    *,
    sleep_fn: Callable[[float], None],
    monotonic_fn: Callable[[], float],
    wall_deadline_seconds: float,
) -> dict[str, Any]:
    prior_failure = _load_terminal_failure(failure_path, plan, packet)
    if prior_failure is not None:
        raise DesignRunError(
            str(prior_failure["terminal_error"].get("message") or "terminal design failure"),
            {
                "status": "terminal_failure",
                "question_id": packet["question_id"],
                "attempt_count": prior_failure["attempt_count"],
                "model_calls": prior_failure["model_calls"],
                "failure_receipt_path": str(failure_path),
                "resumed_terminal_failure": True,
            },
        )
    if wall_deadline_seconds <= 0:
        raise ValueError("item wall deadline must be positive")
    start = monotonic_fn()
    attempts: list[dict[str, Any]] = []
    model_calls = 0
    last_error: Exception | None = None
    configured_timeout = getattr(designer, "transport_timeout_seconds", None)
    call_timeout = (
        float(configured_timeout)
        if isinstance(configured_timeout, (int, float))
        and not isinstance(configured_timeout, bool)
        and configured_timeout > 0
        else 0.0
    )
    for attempt_index in range(MAX_ATTEMPTS):
        remaining = wall_deadline_seconds - max(0.0, monotonic_fn() - start)
        if remaining <= 0:
            last_error = TimeoutError("design item wall deadline exhausted")
            break
        if call_timeout and hasattr(designer, "current_transport_timeout_seconds"):
            designer.current_transport_timeout_seconds = max(  # type: ignore[attr-defined]
                0.01, min(call_timeout, remaining)
            )
        call_started = monotonic_fn()
        model_calls += 1
        try:
            envelope = designer(deepcopy(packet))
            accepted_attempt = {
                "attempt": attempt_index + 1,
                "outcome": "accepted",
                "duration_seconds": round(
                    max(0.0, monotonic_fn() - call_started), 6
                ),
                "transport_endpoint": envelope.get(
                    "transport_endpoint", "responses"
                ),
                "structured_json_mode": envelope.get(
                    "structured_json_mode", "json_schema"
                ),
            }
            checkpoint = _accepted_checkpoint(
                plan,
                packet,
                envelope,
                attempts=[*attempts, accepted_attempt],
                model_calls=model_calls,
                wall_time_seconds=max(0.0, monotonic_fn() - start),
                wall_deadline_seconds=wall_deadline_seconds,
            )
            validate_design_checkpoint(
                plan,
                packet,
                checkpoint,
                conn=conn,
                require_live=True,
            )
            attempts.append(accepted_attempt)
            failure_path.unlink(missing_ok=True)
            return checkpoint
        except Exception as exc:
            last_error = exc
            retryable = _retryable(exc)
            attempt_meta = {
                "attempt": attempt_index + 1,
                "outcome": "retryable_failure" if retryable else "terminal_failure",
                "duration_seconds": round(
                    max(0.0, monotonic_fn() - call_started), 6
                ),
                "retryable": retryable,
                **_error_metadata(exc, designer),
            }
            attempts.append(attempt_meta)
            if not retryable or attempt_index + 1 >= MAX_ATTEMPTS:
                break
            delay = _retry_delay(exc, attempt_index)
            remaining_after = wall_deadline_seconds - max(
                0.0, monotonic_fn() - start
            )
            if remaining_after <= delay:
                break
            attempt_meta["sleep_seconds"] = delay
            sleep_fn(delay)
    if last_error is None:
        last_error = TimeoutError("design item wall deadline exhausted")
    terminal = _terminal_failure_receipt(
        plan,
        packet,
        attempts=attempts,
        model_calls=model_calls,
        wall_time_seconds=max(0.0, monotonic_fn() - start),
        wall_deadline_seconds=wall_deadline_seconds,
        error=last_error,
        designer=designer,
    )
    _atomic_write(failure_path, terminal)
    raise DesignRunError(
        str(last_error),
        {
            "status": "terminal_failure",
            "question_id": packet["question_id"],
            "attempt_count": len(attempts),
            "model_calls": model_calls,
            "failure_receipt_path": str(failure_path),
        },
    ) from last_error


def validate_design_checkpoint(
    plan: dict[str, Any],
    packet: dict[str, Any],
    checkpoint: Any,
    *,
    conn: sqlite3.Connection | None = None,
    require_live: bool = False,
) -> dict[str, Any]:
    if not _valid_receipt(checkpoint):
        raise ValueError("design checkpoint receipt digest is invalid")
    expected = {
        "sealed": True,
        "status": "accepted",
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "bank_version": plan["bank_version"],
        "question_id": packet["question_id"],
        "item_version": packet["item_version"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "profile_digest_sha256": packet["profile_digest_sha256"],
        "generation_input_digest_sha256": packet[
            "generation_input_digest_sha256"
        ],
        "item_handle": packet["item_handle"],
    }
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError("design checkpoint lineage mismatch")
    compiled = _compiled_contract(packet, checkpoint.get("output"))
    if checkpoint.get("compiled_contract") != compiled:
        raise ValueError("design checkpoint compiled contract was tampered")
    if checkpoint.get("compiled_contract_digest_sha256") != _digest(compiled):
        raise ValueError("design checkpoint compiled contract digest mismatch")
    if require_live:
        if conn is None:
            raise ValueError("live design checkpoint validation requires a database")
        if checkpoint.get("provider_mode") != "live_model":
            raise ValueError("only live designer evidence can persist a draft")
        _exact_live_designer_run(conn, plan, packet, checkpoint)
    return checkpoint


def _contract_body(
    packet: dict[str, Any],
    compiled: dict[str, Any],
    *,
    stable_id: str,
    contract_version: int,
) -> dict[str, Any]:
    return {
        **compiled,
        "stable_contract_id": stable_id,
        "contract_version": contract_version,
        "graph_version": packet["graph_version"],
        "question_bank_version": packet["bank_version"],
        "question_digest_sha256": packet["question_digest_sha256"],
        "generation_input_digest_sha256": packet[
            "generation_input_digest_sha256"
        ],
        "design_source": DESIGN_SOURCE,
        "status": "review_pending",
    }


def _generation_row(
    conn: sqlite3.Connection, packet: dict[str, Any]
) -> sqlite3.Row | None:
    return conn.execute(
        """
        select * from answer_contracts
        where question_id = ? and item_version = ?
          and generation_input_digest_sha256 = ?
        limit 1
        """,
        (
            packet["question_id"],
            packet["item_version"],
            packet["generation_input_digest_sha256"],
        ),
    ).fetchone()


def _validate_generation_row(
    row: sqlite3.Row,
    packet: dict[str, Any],
    compiled: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    body = _contract_body(
        packet,
        compiled,
        stable_id=row["stable_contract_id"],
        contract_version=int(row["contract_version"]),
    )
    if row["contract_digest_sha256"] != _digest(body):
        raise ValueError("persisted draft contract digest does not recompute")
    if row["generator_run_id"] != checkpoint["agent_run_id"]:
        raise ValueError("persisted draft generator run mismatch")
    if row["review_receipt_sha256"] != checkpoint["receipt_digest_sha256"]:
        raise ValueError("persisted draft design receipt mismatch")
    if db.json_load(row["review_receipt_json"], {}) != checkpoint:
        raise ValueError("persisted draft design receipt content mismatch")
    if db.json_load(row["reference_solution_json"], {}) != compiled[
        "reference_solution"
    ]:
        raise ValueError("persisted draft reference solution mismatch")
    if db.json_load(row["score_points_json"], []) != compiled["score_points"]:
        raise ValueError("persisted draft score points mismatch")
    return dict(row)


def _persist_draft_contract(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    packet: dict[str, Any],
    compiled: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    validate_design_checkpoint(
        plan,
        packet,
        checkpoint,
        conn=conn,
        require_live=True,
    )
    stable_id = f"AC-{packet['question_id']}"
    existing = _generation_row(conn, packet)
    if existing:
        return _validate_generation_row(existing, packet, compiled, checkpoint)
    conn.execute("pragma busy_timeout = 2000")
    for race_attempt in range(3):
        try:
            if conn.in_transaction:
                conn.commit()
            conn.execute("begin immediate")
            existing = _generation_row(conn, packet)
            if existing:
                conn.commit()
                return _validate_generation_row(
                    existing, packet, compiled, checkpoint
                )
            version_row = conn.execute(
                """
                select coalesce(max(contract_version), 0) as max_version
                from answer_contracts where stable_contract_id = ?
                """,
                (stable_id,),
            ).fetchone()
            version = int(version_row["max_version"] or 0) + 1
            body = _contract_body(
                packet,
                compiled,
                stable_id=stable_id,
                contract_version=version,
            )
            digest = _digest(body)
            now = db.now_iso()
            row_id = "ACD-" + packet["generation_input_digest_sha256"][:16]
            conn.execute(
                """
                insert into answer_contracts(
                  id, stable_contract_id, question_id, item_version,
                  contract_version, contract_digest_sha256,
                  question_digest_sha256, graph_version,
                  question_bank_version, reference_solution_json,
                  score_points_json, generator_version,
                  generation_input_digest_sha256, generator_run_id,
                  review_record_id, review_receipt_json,
                  review_receipt_sha256, fingerprint_policy_version,
                  prompt_instance_fingerprint, core_structure_fingerprint,
                  status, rejection_reason_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          '', '', '', 'review_pending', '{}', ?, ?)
                """,
                (
                    row_id,
                    stable_id,
                    packet["question_id"],
                    packet["item_version"],
                    version,
                    digest,
                    packet["question_digest_sha256"],
                    packet["graph_version"],
                    packet["bank_version"],
                    db.json_dump(compiled["reference_solution"]),
                    db.json_dump(compiled["score_points"]),
                    DESIGN_SOURCE,
                    packet["generation_input_digest_sha256"],
                    checkpoint["agent_run_id"],
                    packet.get("review_record_id") or None,
                    db.json_dump(checkpoint),
                    checkpoint["receipt_digest_sha256"],
                    now,
                    now,
                ),
            )
            conn.commit()
            row = _generation_row(conn, packet)
            if not row:
                raise ValueError("persisted draft could not be read back")
            return _validate_generation_row(row, packet, compiled, checkpoint)
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
            conn.rollback()
            existing = _generation_row(conn, packet)
            if existing:
                return _validate_generation_row(
                    existing, packet, compiled, checkpoint
                )
            if (
                isinstance(exc, sqlite3.OperationalError)
                and "locked" in str(exc).lower()
                and race_attempt < 2
            ):
                time.sleep((0.02, 0.05)[race_attempt])
                continue
            raise ValueError("draft generation transaction did not converge") from exc
    raise ValueError("draft generation transaction did not converge")


def run_design(
    conn: sqlite3.Connection,
    project_root: Path,
    designer: Callable[[dict[str, Any]], dict[str, Any]],
    checkpoint_root: Path,
    *,
    max_items: int | None = None,
    probe_question_id: str | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] | None = None,
    item_wall_seconds: float | None = None,
) -> dict[str, Any]:
    if not callable(designer):
        raise TypeError("designer must be callable")
    if max_items is not None and (
        isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 0
    ):
        raise ValueError("max_items must be a nonnegative integer or None")
    plan = build_design_plan(conn, project_root)
    if probe_question_id is not None:
        if max_items not in {None, 1}:
            raise ValueError("probe_question_id can process only one item")
        selected = [
            packet
            for packet in plan["items"]
            if packet["question_id"] == probe_question_id
        ]
        if len(selected) != 1:
            raise ValueError("probe question is not in the authoritative design plan")
    else:
        selected = plan["items"] if max_items is None else plan["items"][:max_items]
    monotonic = monotonic_fn or time.monotonic
    wall_deadline = float(
        item_wall_seconds
        if item_wall_seconds is not None
        else model_router.answer_contract_design_route().timeout_seconds
    )
    processed = 0
    reused = 0
    model_calls = 0
    attempt_count = 0
    checkpoint_paths = []
    for packet in selected:
        path = _checkpoint_path(checkpoint_root, packet)
        checkpoint = None
        if path.is_file():
            try:
                checkpoint = validate_design_checkpoint(
                    plan,
                    packet,
                    json.loads(path.read_text(encoding="utf-8")),
                    conn=conn,
                    require_live=True,
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                checkpoint = None
        if checkpoint is not None:
            _persist_draft_contract(
                conn,
                plan,
                packet,
                checkpoint["compiled_contract"],
                checkpoint,
            )
            reused += 1
            checkpoint_paths.append(str(path))
            continue
        failure_path = _failure_checkpoint_path(checkpoint_root, packet)
        try:
            checkpoint = _execute_design_packet(
                conn,
                plan,
                packet,
                designer,
                failure_path,
                sleep_fn=sleep_fn,
                monotonic_fn=monotonic,
                wall_deadline_seconds=wall_deadline,
            )
        except DesignRunError as exc:
            exc.report.update(
                {
                    "processed_items": processed,
                    "reused_items": reused,
                    "model_calls": model_calls
                    + int(exc.report.get("model_calls") or 0),
                    "attempt_count": attempt_count
                    + int(exc.report.get("attempt_count") or 0),
                }
            )
            raise
        _atomic_write(path, checkpoint)
        _persist_draft_contract(
            conn,
            plan,
            packet,
            checkpoint["compiled_contract"],
            checkpoint,
        )
        checkpoint_paths.append(str(path))
        processed += 1
        model_calls += int(checkpoint["model_calls"])
        attempt_count += int(checkpoint["attempt_count"])
    return {
        "bank_version": plan["bank_version"],
        "considered_items": len(selected),
        "processed_items": processed,
        "reused_items": reused,
        "model_calls": model_calls,
        "attempt_count": attempt_count,
        "item_wall_seconds": wall_deadline,
        "checkpoint_paths": checkpoint_paths,
    }


def revise_rejected_contract(
    *,
    question: dict[str, Any],
    rejected_contract: dict[str, Any],
    rejection_route: dict[str, Any],
    skeleton: dict[str, Any],
    designer_items: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_route = {
        "owner": "answer_contract",
        "action": "regenerate_contract_draft",
        "reason_code": "answer_contract_rejected",
        "preserve_bound_node": True,
    }
    if rejection_route != expected_route:
        raise ValueError("only contract-only rejection can revise a contract version")
    if rejected_contract.get("status") != "rejected":
        raise ValueError("only a rejected contract can be revised")
    for field, question_field in (
        ("question_id", "id"),
        ("item_version", "item_version"),
        ("node_id", "node_id"),
    ):
        if rejected_contract.get(field) != question.get(question_field):
            raise ValueError("rejected contract question lineage changed")
    compiled = assessment_policy.compile_answer_contract(
        question, skeleton, designer_items
    )
    revised = {
        **compiled,
        "stable_contract_id": rejected_contract["stable_contract_id"],
        "contract_version": int(rejected_contract["contract_version"]) + 1,
        "question_bank_version": question["item_version"],
        "status": "review_pending",
    }
    revised["contract_digest_sha256"] = _digest(revised)
    return revised


def audit_activation_readiness(
    expected_items: list[dict[str, Any]],
    design_receipts: list[dict[str, Any]],
    review_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = {
        (item.get("question_id"), item.get("item_version"))
        for item in expected_items
        if isinstance(item, dict)
    }

    def accepted(
        receipts: list[dict[str, Any]], agent_key: str, phase: str
    ) -> tuple[set[tuple[Any, Any]], bool]:
        found = set()
        role_valid = True
        for receipt in receipts:
            if not isinstance(receipt, dict):
                role_valid = False
                continue
            key = (receipt.get("question_id"), receipt.get("item_version"))
            if (
                key not in expected
                or receipt.get("status") != "accepted"
                or receipt.get("agent_key") != agent_key
                or receipt.get("phase") != phase
                or not receipt.get("agent_run_id")
                or not isinstance(receipt.get("receipt_digest_sha256"), str)
                or len(receipt["receipt_digest_sha256"]) != 64
            ):
                role_valid = False
                continue
            found.add(key)
        return found, role_valid

    designs, design_role_valid = accepted(design_receipts, AGENT_KEY, PHASE)
    reviews, review_role_valid = accepted(
        review_receipts, REVIEWER_AGENT_KEY, REVIEWER_PHASE
    )
    blockers = []
    if len(expected) != 1120:
        blockers.append("expected_inventory_must_equal_1120")
    if not design_role_valid:
        blockers.append("designer_receipt_invalid")
    if not review_role_valid:
        blockers.append("independent_review_required")
    design_missing = len(expected.difference(designs))
    review_missing = len(expected.difference(reviews))
    if design_missing:
        blockers.append("design_receipts_incomplete")
    if review_missing:
        blockers.append("review_receipts_incomplete")
    return {
        "expected_items": len(expected),
        "design_accepted": len(designs),
        "review_accepted": len(reviews),
        "design_missing": design_missing,
        "review_missing": review_missing,
        "blockers": blockers,
        "activation_ready": not blockers,
    }


def _review_issue_set_digest(issues: Any) -> str:
    if not isinstance(issues, list):
        raise TypeError("contract review issues must be a list")
    normalized = sorted(
        (
            {
                "code": str(issue.get("code") or ""),
                "slot_key": issue.get("slot_key"),
                "detail": str(issue.get("detail") or ""),
                "repairable": issue.get("repairable") is True,
            }
            for issue in issues
            if isinstance(issue, dict)
        ),
        key=lambda issue: (
            issue["code"],
            str(issue["slot_key"] or ""),
            issue["detail"],
        ),
    )
    if len(normalized) != len(issues):
        raise TypeError("contract review issues must be structured mappings")
    return _digest(normalized)


def reduce_contract_repair_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(history, list) or not history:
        raise ValueError("contract repair history must be a nonempty list")
    if len(history) > 3:
        raise ValueError("contract repair history cannot exceed three versions")
    digests = []
    issue_digests = []
    verdicts = []
    versions = []
    for entry in history:
        if not isinstance(entry, dict):
            raise TypeError("contract repair history entries must be mappings")
        version = entry.get("contract_version")
        digest = entry.get("contract_digest_sha256")
        verdict = entry.get("review_verdict")
        if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
            raise ValueError("contract repair versions must be positive integers")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("contract repair history requires contract digests")
        if verdict not in {"approved", "rejected"}:
            raise ValueError("contract repair verdict must be approved or rejected")
        versions.append(version)
        digests.append(digest)
        issue_digests.append(_review_issue_set_digest(entry.get("issues") or []))
        verdicts.append(verdict)
    if versions != list(range(1, len(history) + 1)):
        raise ValueError("contract repair versions must be contiguous from one")
    for index in range(1, len(history)):
        if (
            digests[index] == digests[index - 1]
            and issue_digests[index] == issue_digests[index - 1]
            and verdicts[index] == "rejected"
        ):
            return {
                "status": "contract_repair_exhausted",
                "reason_code": "repeated_contract_digest_and_issue_set",
                "terminal_contract_version": versions[index],
                "activation_eligible": False,
            }
    if verdicts[-1] == "approved":
        return {
            "status": "approved",
            "reason_code": "",
            "terminal_contract_version": versions[-1],
            "activation_eligible": False,
        }
    if len(history) == 3:
        return {
            "status": "contract_repair_exhausted",
            "reason_code": "repair_version_limit_reached",
            "terminal_contract_version": versions[-1],
            "activation_eligible": False,
        }
    return {
        "status": "contract_repair_required",
        "reason_code": "review_rejected",
        "terminal_contract_version": versions[-1],
        "activation_eligible": False,
    }


def _validate_repair_versions(
    context: dict[str, Any], versions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    required_context = {"question_id", "item_version", "stable_contract_id"}
    if not isinstance(context, dict) or set(context) != required_context:
        raise ValueError("contract repair context fields must match exactly")
    validated = deepcopy(versions)
    design_runs = set()
    review_runs = set()
    previous = None
    for index, entry in enumerate(validated, start=1):
        if not isinstance(entry, dict) or "contract" not in entry:
            raise ValueError("contract repair versions require contract payloads")
        contract = entry["contract"]
        if not isinstance(contract, dict):
            raise TypeError("contract repair contract must be a mapping")
        if (
            contract.get("question_id") != context["question_id"]
            or contract.get("item_version") != context["item_version"]
            or contract.get("stable_contract_id") != context["stable_contract_id"]
            or contract.get("contract_version") != index
        ):
            raise ValueError("contract repair context or version lineage mismatch")
        claimed_digest = contract.get("contract_digest_sha256")
        body = {
            key: value
            for key, value in contract.items()
            if key != "contract_digest_sha256"
        }
        if claimed_digest != _digest(body):
            raise ValueError("contract repair contract digest is invalid")
        if previous is None:
            if contract.get("parent_contract") is not None:
                raise ValueError("initial contract cannot have a parent contract")
        else:
            expected_parent = {
                "stable_contract_id": previous["stable_contract_id"],
                "contract_version": previous["contract_version"],
                "contract_digest_sha256": previous["contract_digest_sha256"],
            }
            if contract.get("parent_contract") != expected_parent:
                raise ValueError("contract repair parent lineage mismatch")
        design_run = entry.get("design_run_id") or (entry.get("design_receipt") or {}).get(
            "agent_run_id"
        )
        review_run = entry.get("review_run_id") or (entry.get("review_receipt") or {}).get(
            "agent_run_id"
        )
        if not isinstance(design_run, str) or not design_run:
            raise ValueError("contract repair requires a fresh designer run")
        if not isinstance(review_run, str) or not review_run:
            raise ValueError("contract repair requires a fresh reviewer run")
        if design_run in design_runs or review_run in review_runs or design_run == review_run:
            raise ValueError("contract repair agent runs must be fresh and independent")
        design_runs.add(design_run)
        review_runs.add(review_run)
        previous = contract
    if design_runs.intersection(review_runs):
        raise ValueError("designer and reviewer run lineage must be independent")
    return validated


def build_contract_repair_checkpoint(
    context: dict[str, Any], versions: list[dict[str, Any]]
) -> dict[str, Any]:
    validated = _validate_repair_versions(context, versions)
    reduction_history = [
        {
            "contract_version": entry["contract"]["contract_version"],
            "contract_digest_sha256": entry["contract"]["contract_digest_sha256"],
            "review_verdict": entry.get("review_verdict")
            or (entry.get("review_receipt") or {}).get("verdict"),
            "issues": deepcopy(
                entry.get("issues")
                if "issues" in entry
                else (entry.get("review_receipt") or {}).get("issues") or []
            ),
        }
        for entry in validated
    ]
    return _receipt(
        {
            "sealed": True,
            "schema_version": "answer-contract-repair-checkpoint.v2",
            "context": deepcopy(context),
            "versions": validated,
            "reduction": reduce_contract_repair_history(reduction_history),
        }
    )


def resume_contract_repair_state(
    context: dict[str, Any], checkpoint: dict[str, Any]
) -> dict[str, Any]:
    if not _valid_receipt(checkpoint):
        raise ValueError("contract repair checkpoint receipt is invalid")
    if (
        checkpoint.get("sealed") is not True
        or checkpoint.get("schema_version")
        != "answer-contract-repair-checkpoint.v2"
        or checkpoint.get("context") != context
    ):
        raise ValueError("contract repair checkpoint lineage mismatch")
    versions = _validate_repair_versions(context, checkpoint.get("versions"))
    rebuilt = build_contract_repair_checkpoint(context, versions)
    if rebuilt != checkpoint:
        raise ValueError("contract repair checkpoint was tampered")
    return {
        "context": deepcopy(context),
        "versions": versions,
        "reduction": deepcopy(checkpoint["reduction"]),
    }


def _repair_checkpoint_path(root: Path, question_id: str) -> Path:
    root = root.resolve()
    safe_question_id = _safe_component(question_id, "question_id")
    path = (root / safe_question_id / "repair-chain.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("contract repair checkpoint escapes root") from exc
    return path


def _normalized_agent_receipt(
    value: dict[str, Any], *, agent_key: str, phases: set[str]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("contract repair agent receipt must be a mapping")
    if (
        value.get("agent_key") != agent_key
        or value.get("phase") not in phases
        or value.get("provider_mode") != "live_model"
        or value.get("status", "accepted") != "accepted"
        or not isinstance(value.get("agent_run_id"), str)
        or not value["agent_run_id"]
    ):
        raise ValueError("contract repair requires exact live agent lineage")
    return deepcopy(value)


def _proposed_semantic_items(
    question: dict[str, Any], parent: dict[str, Any], version: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    skeleton = assessment_policy.build_contract_skeleton_v2(question)
    handle = f"design-v2-{question['id']}-contract-{version}"
    skeleton = {**deepcopy(skeleton), "item_handle": handle}
    catalog = skeleton["allowed_slot_catalog"]
    selected_count = max(2, min(4, len(parent["score_points"]), len(catalog)))
    items = []
    for slot in catalog[:selected_count]:
        anchor_key = slot["allowed_source_anchor_keys"][0]
        anchor = skeleton["reference_anchors"][anchor_key]
        items.append(
            {
                "item_handle": handle,
                "slot_key": slot["slot_key"],
                "criterion": (
                    f"Shows the observable result for {slot['slot_key']}: "
                    f"{anchor['claim']}."
                ),
                "reference_evidence": {
                    "claim": anchor["claim"],
                    "source_anchor_keys": [anchor_key],
                    "derivation_scope": "direct",
                },
                "confidence": 0.95,
            }
        )
    return skeleton, items


def _validate_initial_repair_version(
    question: dict[str, Any], initial_version: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(question, dict) or not isinstance(initial_version, dict):
        raise TypeError("repair question and initial_version must be mappings")
    contract = deepcopy(initial_version.get("contract"))
    if not isinstance(contract, dict):
        raise ValueError("initial repair version requires a contract")
    if (
        contract.get("question_id") != question.get("id")
        or contract.get("item_version") != question.get("item_version")
        or contract.get("contract_version") != 1
        or not isinstance(contract.get("stable_contract_id"), str)
        or not contract["stable_contract_id"]
    ):
        raise ValueError("initial contract and question lineage mismatch")
    if question.get("node_id") and contract.get("node_id") not in {
        None,
        question["node_id"],
    }:
        raise ValueError("initial contract node lineage mismatch")
    claimed_digest = contract.get("contract_digest_sha256")
    body = {
        key: value
        for key, value in contract.items()
        if key != "contract_digest_sha256"
    }
    if claimed_digest != _digest(body):
        raise ValueError("initial contract digest is invalid")
    points = contract.get("score_points")
    components = (contract.get("reference_solution") or {}).get("components")
    if (
        not isinstance(points, list)
        or not 2 <= len(points) <= 4
        or not isinstance(components, list)
        or not components
        or sum(int(point.get("points") or 0) for point in points) != 10
        or not any(point.get("required_for_pass") is True for point in points)
    ):
        raise ValueError("initial contract scoring authority is invalid")
    component_keys = {
        component.get("key")
        for component in components
        if isinstance(component, dict)
    }
    if any(
        not isinstance(point, dict)
        or point.get("reference_component_key") not in component_keys
        for point in points
    ):
        raise ValueError("initial contract reference component lineage is invalid")
    design_receipt = _normalized_agent_receipt(
        initial_version.get("design_receipt"),
        agent_key=AGENT_KEY,
        phases={PHASE, "answer_contract_design_v2"},
    )
    review_receipt = _normalized_agent_receipt(
        initial_version.get("review_receipt"),
        agent_key=REVIEWER_AGENT_KEY,
        phases={REVIEWER_PHASE, "answer_contract_review_v2"},
    )
    if review_receipt.get("verdict") not in {"approved", "rejected"}:
        raise ValueError("initial review verdict is invalid")
    if not isinstance(review_receipt.get("issues"), list):
        raise TypeError("initial review issues must be a list")
    if design_receipt["agent_run_id"] == review_receipt["agent_run_id"]:
        raise ValueError("initial designer and reviewer runs must be independent")
    return contract, design_receipt, review_receipt


def run_contract_repair_loop(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    question: dict[str, Any],
    initial_version: dict[str, Any],
    designer_callable: Callable[[dict[str, Any]], dict[str, Any]],
    reviewer_callable: Callable[[dict[str, Any]], dict[str, Any]],
    checkpoint_root: Path,
) -> dict[str, Any]:
    if not callable(designer_callable) or not callable(reviewer_callable):
        raise TypeError("contract repair designer and reviewer must be callable")
    if not Path(project_root).resolve().is_dir():
        raise ValueError("project_root must be an existing directory")
    db.init_schema(conn)
    authoritative_rows = conn.execute(
        "select * from question_items where id = ?",
        (question.get("id"),),
    ).fetchall()
    if authoritative_rows:
        if len(authoritative_rows) != 1:
            raise ValueError("repair question identity is not unique")
        authoritative = db.row_to_question(authoritative_rows[0])
        for field in (
            "id",
            "item_version",
            "node_id",
            "kind",
            "prompt",
            "answer_format",
            "expected_answer",
            "solution_steps",
        ):
            if authoritative.get(field) != question.get(field):
                raise ValueError(f"repair question authority mismatch: {field}")
    contract, design_receipt, review_receipt = _validate_initial_repair_version(
        question, initial_version
    )
    versions = [
        {
            "contract": contract,
            "design_receipt": design_receipt,
            "review_receipt": review_receipt,
        }
    ]
    context = {
        "question_id": contract["question_id"],
        "item_version": contract["item_version"],
        "stable_contract_id": contract["stable_contract_id"],
    }
    checkpoint_path = _repair_checkpoint_path(checkpoint_root, question["id"])
    initial_history = [
        {
            "contract": contract,
            "design_receipt": design_receipt,
            "review_receipt": review_receipt,
            "design_run_id": design_receipt["agent_run_id"],
            "review_run_id": review_receipt["agent_run_id"],
            "review_verdict": review_receipt["verdict"],
            "issues": deepcopy(review_receipt["issues"]),
        }
    ]
    initial_reduction = reduce_contract_repair_history(
        [
            {
                "contract_version": 1,
                "contract_digest_sha256": contract["contract_digest_sha256"],
                "review_verdict": review_receipt["verdict"],
                "issues": deepcopy(review_receipt["issues"]),
            }
        ]
    )
    if initial_reduction["status"] == "approved":
        _atomic_write(
            checkpoint_path,
            build_contract_repair_checkpoint(context, initial_history),
        )
        return {
            "status": "approved",
            "reason_code": "",
            "versions": versions,
            "activation_eligible": False,
            "checkpoint_path": str(checkpoint_path),
            "reused_checkpoint": False,
        }
    if checkpoint_path.is_file():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            resumed = resume_contract_repair_state(context, checkpoint)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            resumed = None
        if resumed is not None:
            versions = [
                {
                    "contract": deepcopy(entry["contract"]),
                    "design_receipt": deepcopy(entry.get("design_receipt") or {}),
                    "review_receipt": deepcopy(entry.get("review_receipt") or {}),
                }
                for entry in resumed["versions"]
            ]
            reduction = resumed["reduction"]
            if reduction["status"] != "contract_repair_required":
                return {
                    "status": reduction["status"],
                    "reason_code": reduction["reason_code"],
                    "versions": versions,
                    "activation_eligible": False,
                    "checkpoint_path": str(checkpoint_path),
                    "reused_checkpoint": True,
                }
    used_design_runs = {design_receipt["agent_run_id"]}
    used_review_runs = {review_receipt["agent_run_id"]}
    for entry in versions[1:]:
        used_design_runs.add(entry["design_receipt"]["agent_run_id"])
        used_review_runs.add(entry["review_receipt"]["agent_run_id"])
    for version in range(len(versions) + 1, 4):
        parent = versions[-1]["contract"]
        issues = deepcopy(versions[-1]["review_receipt"].get("issues") or [])
        skeleton, proposed_items = _proposed_semantic_items(
            question, parent, version
        )
        designer_packet = {
            "question": deepcopy(question),
            "contract_version": version,
            "parent_contract": {
                "stable_contract_id": parent["stable_contract_id"],
                "contract_version": parent["contract_version"],
                "contract_digest_sha256": parent["contract_digest_sha256"],
            },
            "reviewer_issues": issues,
            "skeleton": skeleton,
            "proposed_semantic_items": proposed_items,
        }
        design = _normalized_agent_receipt(
            designer_callable(deepcopy(designer_packet)),
            agent_key=AGENT_KEY,
            phases={PHASE, "answer_contract_design_v2"},
        )
        if design["agent_run_id"] in used_design_runs | used_review_runs:
            raise ValueError("contract repair designer run must be fresh")
        used_design_runs.add(design["agent_run_id"])
        semantic_items = design.get("semantic_items")
        if not isinstance(semantic_items, list) or not semantic_items:
            raise ValueError("contract repair designer returned no semantic items")
        compiled = assessment_policy.compile_answer_contract_v2(
            question, skeleton, semantic_items
        )
        new_contract = {
            **compiled,
            "stable_contract_id": contract["stable_contract_id"],
            "contract_version": version,
            "parent_contract": deepcopy(designer_packet["parent_contract"]),
            "repair_iteration": version - 1,
        }
        new_contract["contract_digest_sha256"] = _digest(new_contract)
        reviewer_packet = {
            "question": deepcopy(question),
            "contract": deepcopy(new_contract),
            "contract_version": version,
        }
        review = _normalized_agent_receipt(
            reviewer_callable(deepcopy(reviewer_packet)),
            agent_key=REVIEWER_AGENT_KEY,
            phases={REVIEWER_PHASE, "answer_contract_review_v2"},
        )
        if review["agent_run_id"] in used_design_runs | used_review_runs:
            raise ValueError("contract repair reviewer run must be fresh and independent")
        used_review_runs.add(review["agent_run_id"])
        if review.get("verdict") not in {"approved", "rejected"}:
            raise ValueError("contract repair reviewer verdict is invalid")
        if not isinstance(review.get("issues"), list):
            raise TypeError("contract repair reviewer issues must be a list")
        versions.append(
            {
                "contract": new_contract,
                "design_receipt": design,
                "review_receipt": review,
            }
        )
        checkpoint_versions = [
            {
                **entry,
                "design_run_id": entry["design_receipt"]["agent_run_id"],
                "review_run_id": entry["review_receipt"]["agent_run_id"],
                "review_verdict": entry["review_receipt"].get("verdict"),
                "issues": deepcopy(entry["review_receipt"].get("issues") or []),
            }
            for entry in versions
        ]
        _atomic_write(
            checkpoint_path,
            build_contract_repair_checkpoint(context, checkpoint_versions),
        )
        reduction = reduce_contract_repair_history(
            [
                {
                    "contract_version": entry["contract"]["contract_version"],
                    "contract_digest_sha256": entry["contract"][
                        "contract_digest_sha256"
                    ],
                    "review_verdict": entry["review_receipt"].get("verdict"),
                    "issues": deepcopy(entry["review_receipt"].get("issues") or []),
                }
                for entry in versions
            ]
        )
        if reduction["status"] != "contract_repair_required":
            return {
                "status": reduction["status"],
                "reason_code": reduction["reason_code"],
                "versions": versions,
                "activation_eligible": False,
                "checkpoint_path": str(checkpoint_path),
                "reused_checkpoint": False,
            }
    raise AssertionError("contract repair loop did not reach a terminal state")


def build_contract_canary_plan(
    conn: sqlite3.Connection, project_root: Path
) -> dict[str, Any]:
    from . import answer_contract_generation_v2

    return answer_contract_generation_v2.plan_canary_questions(conn, project_root)


def audit_contract_canary_readiness(
    plan: dict[str, Any],
    outcomes: list[dict[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    body = {key: value for key, value in plan.items() if key != "plan_digest_sha256"}
    if plan.get("plan_digest_sha256") != _digest(body):
        raise ValueError("contract canary plan digest is invalid")
    expected = {item["question_id"] for item in plan.get("items") or []}
    seen = set()
    approved = 0
    authoritative_approved = 0
    unauthenticated_approved = 0
    explicit_routes = 0
    policy_block_routes = 0
    unrouted = 0
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            raise TypeError("contract canary outcomes must be mappings")
        question_id = outcome.get("question_id")
        if question_id not in expected or question_id in seen:
            unrouted += 1
            continue
        seen.add(question_id)
        if outcome.get("outcome") == "approved":
            approved += 1
            contract_id = outcome.get("contract_id")
            exact = False
            if conn is not None and isinstance(contract_id, str) and contract_id:
                contract_row = conn.execute(
                    "select question_id from answer_contracts where id = ?",
                    (contract_id,),
                ).fetchone()
                if contract_row and contract_row["question_id"] == question_id:
                    readiness = answer_contract_activation.v2_contract_activation_readiness(
                        conn, contract_id
                    )
                    exact = bool(readiness["activation_eligible"])
            if exact:
                authoritative_approved += 1
            else:
                unauthenticated_approved += 1
            continue
        route = outcome.get("repair_route")
        valid_route = False
        base_route_fields = {
            "owner",
            "action",
            "reason_code",
            "preserve_bound_node",
        }
        if (
            outcome.get("outcome") == "routed"
            and isinstance(route, dict)
            and base_route_fields.issubset(route)
            and isinstance(route["reason_code"], str)
            and route["reason_code"]
            and isinstance(route["preserve_bound_node"], bool)
        ):
            contract_reasons = {
                "criterion_bundled",
                "criterion_overlap",
                "criterion_unobservable",
                "reference_evidence_broad",
                "reference_evidence_missing",
                "derived_grounding_invalid",
                "presentation_only_scored",
                "prompt_demand_missing",
                "slot_not_allowed",
                "low_confidence",
                "other_contract_issue",
            }
            question_reasons = {
                "question_incorrect",
                "reference_answer_incorrect",
                "question_node_misaligned",
                "evidence_role_misaligned",
            }
            policy_reasons = {
                "score_weight_invalid",
                "mastery_dimension_invalid",
                "required_for_pass_invalid",
            }
            valid_route = (
                route["owner"] == "answer_contract"
                and set(route) == base_route_fields
                and route["action"] == "regenerate_contract_draft"
                and route["reason_code"] in contract_reasons
                and route["preserve_bound_node"] is True
            ) or (
                route["owner"] == "question_bank"
                and set(route) == base_route_fields
                and route["action"] == "new_immutable_question_version"
                and route["reason_code"] in question_reasons
                and route["preserve_bound_node"] is True
            ) or (
                route["owner"] == "assessment_policy"
                and route["action"] == "revise_policy_catalog"
                and route["reason_code"] in policy_reasons
                and route["preserve_bound_node"] is True
                and set(route)
                == base_route_fields
                | {
                    "question_kind",
                    "profile_version",
                    "profile_digest_sha256",
                    "selected_slot_keys",
                    "contract_digest_sha256",
                    "reviewer_run_id",
                    "review_schema_version",
                    "requires_new_profile_digest",
                    "existing_contract_activation_allowed",
                }
                and isinstance(route["question_kind"], str)
                and bool(route["question_kind"])
                and isinstance(route["profile_version"], str)
                and bool(route["profile_version"])
                and isinstance(route["selected_slot_keys"], list)
                and bool(route["selected_slot_keys"])
                and len(set(route["selected_slot_keys"]))
                == len(route["selected_slot_keys"])
                and all(
                    isinstance(value, str) and value
                    for value in route["selected_slot_keys"]
                )
                and all(
                    isinstance(route[field], str)
                    and len(route[field]) == 64
                    for field in (
                        "profile_digest_sha256",
                        "contract_digest_sha256",
                    )
                )
                and isinstance(route["reviewer_run_id"], str)
                and bool(route["reviewer_run_id"])
                and route["requires_new_profile_digest"] is True
                and route["existing_contract_activation_allowed"] is False
            )
        if valid_route:
            explicit_routes += 1
            if route["owner"] == "assessment_policy":
                policy_block_routes += 1
        else:
            unrouted += 1
    missing = len(expected.difference(seen))
    collection_complete = missing == 0 and unrouted == 0
    canary_passed = (
        collection_complete
        and authoritative_approved == len(expected)
        and unauthenticated_approved == 0
        and explicit_routes == 0
    )
    return {
        "planned_count": len(expected),
        "approved_count": approved,
        "authoritative_approved_count": authoritative_approved,
        "unauthenticated_approved_count": unauthenticated_approved,
        "explicit_route_count": explicit_routes,
        "assessment_policy_block_count": policy_block_routes,
        "missing_count": missing,
        "unrouted_count": unrouted,
        "collection_complete": collection_complete,
        "canary_passed": canary_passed,
        "canary_ready": canary_passed,
        "activation_ready": False,
    }


def build_v2_probe_plan(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    question_id: str,
) -> dict[str, Any]:
    from . import answer_contract_generation_v2

    if not Path(project_root).resolve().is_dir():
        raise ValueError("project_root must be an existing directory")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("v2 probe question_id must be nonempty")
    ledger = answer_contract_activation._active_ledger(conn)
    authoritative = [
        (question, review_record_id)
        for question, review_record_id in answer_contract_activation._authoritative_questions(
            conn, str(ledger["question_bank_version"])
        )
        if question["id"] == question_id
    ]
    if len(authoritative) != 1:
        raise ValueError("v2 probe requires exactly one authoritative active question")
    question, review_record_id = authoritative[0]
    packet = answer_contract_generation_v2.build_design_packet_v2(
        question=question,
        graph_version=str(ledger.get("graph_version") or ""),
        bank_version=str(ledger["question_bank_version"]),
        review_record_id=review_record_id,
    )
    plan = {
        "schema_version": "answer-contract-v2-probe-plan.v1",
        "question_id": question["id"],
        "item_version": question["item_version"],
        "node_id": question["node_id"],
        "question_kind": question["kind"],
        "bank_version": str(ledger["question_bank_version"]),
        "graph_version": str(ledger.get("graph_version") or ""),
        "review_record_id": review_record_id,
        "question_digest_sha256": packet["question_digest_sha256"],
        "generation_input_digest_sha256": packet[
            "generation_input_digest_sha256"
        ],
    }
    plan["plan_digest_sha256"] = _digest(plan)
    return {**plan, "question": question}


def make_live_designer_v2(
    conn: sqlite3.Connection,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    from . import answer_contract_generation_v2

    return answer_contract_generation_v2.make_live_designer_v2(conn)


def make_live_reviewer_v2(
    conn: sqlite3.Connection,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    from . import answer_contract_generation_v2

    return answer_contract_generation_v2.make_live_reviewer_v2(conn)


def run_contract_repair_loop_v2(
    conn: sqlite3.Connection,
    *,
    question: dict[str, Any],
    graph_version: str,
    bank_version: str,
    review_record_id: str,
    designer: Callable[[dict[str, Any]], dict[str, Any]],
    reviewer: Callable[[dict[str, Any]], dict[str, Any]],
    checkpoint_root: Path,
) -> dict[str, Any]:
    from . import answer_contract_generation_v2

    return answer_contract_generation_v2.run_contract_repair_loop(
        conn,
        question=question,
        graph_version=graph_version,
        bank_version=bank_version,
        review_record_id=review_record_id,
        designer=designer,
        reviewer=reviewer,
        checkpoint_root=checkpoint_root,
    )


def run_live_v2_probe(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    question_id: str,
    checkpoint_root: Path,
) -> dict[str, Any]:
    db.init_schema(conn)
    plan = build_v2_probe_plan(
        conn, project_root, question_id=question_id
    )
    result = run_contract_repair_loop_v2(
        conn,
        question=deepcopy(plan["question"]),
        graph_version=plan["graph_version"],
        bank_version=plan["bank_version"],
        review_record_id=plan["review_record_id"],
        designer=make_live_designer_v2(conn),
        reviewer=make_live_reviewer_v2(conn),
        checkpoint_root=checkpoint_root,
    )
    versions = result.get("versions") or []
    repair_routes = [
        deepcopy(classification["repair_route"])
        for classification in (
            version.get("classification")
            for version in versions
            if isinstance(version, dict)
        )
        if isinstance(classification, dict)
        and isinstance(classification.get("repair_route"), dict)
    ]
    semantic_response_valid = result.get("status") not in {
        "terminal_failure",
        "checkpoint_lineage_invalid",
    }
    return {
        "mode": "answer_contract_v2_live_probe",
        "question_id": question_id,
        "bank_version": plan["bank_version"],
        "plan_digest_sha256": plan["plan_digest_sha256"],
        "transport_pass": semantic_response_valid and bool(versions),
        "semantic_response_valid": semantic_response_valid,
        "semantic_approval": result.get("status") == "approved",
        "activation_eligible": False,
        "repair_routes": repair_routes,
        **result,
        "activation_eligible": False,
    }


def effective_evidence_role(question: dict[str, Any]) -> str:
    return answer_contract_batch_v2.effective_evidence_role(question)


def batch_v2_skeleton_blocked_report(operation: str) -> dict[str, Any]:
    return answer_contract_batch_v2.skeleton_blocked_report(operation)


def canonical_v2_batch_db_lock_path(conn: sqlite3.Connection) -> Path:
    return answer_contract_batch_v2.canonical_db_lock_path(conn)


def acquire_v2_batch_db_lock(
    conn: sqlite3.Connection,
    *,
    hooks: BatchATestHooks | None = None,
) -> answer_contract_batch_v2.CanonicalDBRunLock:
    return answer_contract_batch_v2.acquire_canonical_db_run_lock(
        conn, hooks=hooks
    )


def build_v2_batch_plan(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    run_kind: str,
    canary_receipt_path: Path | None = None,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    return answer_contract_batch_v2.build_v2_batch_plan(
        conn,
        project_root,
        run_kind=run_kind,
        canary_receipt_path=canary_receipt_path,
        hooks=hooks,
    )


def preflight_v2_canary(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    run_id: str,
    claim: RunClaim,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    return answer_contract_batch_v2.preflight_v2_canary(
        conn,
        project_root,
        run_id=run_id,
        claim=claim,
        hooks=hooks,
    )


def create_or_resume_v2_run(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    plan: dict[str, Any],
    checkpoint_root: Path,
    model_call_cap: int = (
        answer_contract_batch_v2.CANARY_DEFAULT_MODEL_CALL_CAP
    ),
    provider_attempt_cap: int = (
        answer_contract_batch_v2.CANARY_DEFAULT_PROVIDER_ATTEMPT_CAP
    ),
    hooks: BatchATestHooks | None = None,
) -> tuple[dict[str, Any], RunClaim]:
    return answer_contract_batch_v2.create_or_resume_v2_run(
        conn,
        project_root,
        plan=plan,
        checkpoint_root=checkpoint_root,
        model_call_cap=model_call_cap,
        provider_attempt_cap=provider_attempt_cap,
        hooks=hooks,
    )


def run_v2_canary(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    designer: Callable[[dict[str, Any]], dict[str, Any]] | None,
    reviewer: Callable[[dict[str, Any]], dict[str, Any]] | None,
    checkpoint_root: Path,
    model_call_cap: int = (
        answer_contract_batch_v2.CANARY_DEFAULT_MODEL_CALL_CAP
    ),
    provider_attempt_cap: int = (
        answer_contract_batch_v2.CANARY_DEFAULT_PROVIDER_ATTEMPT_CAP
    ),
    max_items: int = answer_contract_batch_v2.CANARY_DEFAULT_MAX_ITEMS,
    invocation_wall_seconds: float = (
        answer_contract_batch_v2.CANARY_DEFAULT_WALL_SECONDS
    ),
    lifecycle_observer: BatchALifecycleObserver | None = None,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    return answer_contract_batch_v2.run_v2_canary(
        conn,
        project_root,
        designer=designer,
        reviewer=reviewer,
        checkpoint_root=checkpoint_root,
        model_call_cap=model_call_cap,
        provider_attempt_cap=provider_attempt_cap,
        max_items=max_items,
        invocation_wall_seconds=invocation_wall_seconds,
        lifecycle_observer=lifecycle_observer,
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
    return answer_contract_batch_v2.audit_v2_generation_run(
        conn,
        project_root,
        run_id=run_id,
        checkpoint_root=checkpoint_root,
        hooks=hooks,
    )


def verify_v2_generation_receipt(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    receipt_path: Path,
    checkpoint_root: Path,
    hooks: BatchATestHooks | None = None,
) -> dict[str, Any]:
    return answer_contract_batch_v2.verify_v2_generation_receipt(
        conn,
        project_root,
        receipt_path=receipt_path,
        checkpoint_root=checkpoint_root,
        hooks=hooks,
    )
