from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from . import (
    answer_contract_review,
    db,
    internal_agents,
    model_router,
    question_fingerprints,
    semantic_agents,
)


AGENT_KEY = "answer_contract_reviewer_agent"
PHASE = "answer_contract_review"
MODEL_ALIAS = "gpt-5.5"
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (20, 60)
SHARD_WALL_SECONDS = 180.0
MAX_RETRY_AFTER_SECONDS = 180.0
KNOWN_MISBOUND_IDS = frozenset()


class ReviewRunError(RuntimeError):
    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report
        self.active_bank_version = str(report.get("bank_version") or "")


def _canonical_digest(value: Any) -> str:
    return question_fingerprints.canonical_sha256(value)


def _receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "receipt_digest_sha256": _canonical_digest(payload)}


def _valid_receipt_digest(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or "receipt_digest_sha256" not in payload:
        return False
    body = {key: value for key, value in payload.items() if key != "receipt_digest_sha256"}
    return payload["receipt_digest_sha256"] == _canonical_digest(body)


def _safe_component(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty path component")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe {field}")
    if Path(value).name != value:
        raise ValueError(f"unsafe {field}")
    return value


def _checkpoint_dir(root: Path, bank_version: str, node_id: str) -> Path:
    root = root.resolve()
    target = (root / _safe_component(bank_version, "bank_version") / _safe_component(node_id, "node_id")).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("checkpoint path escapes checkpoint root") from exc
    return target


def _checkpoint_path(root: Path, bank_version: str, node_id: str, shard_index: int) -> Path:
    if isinstance(shard_index, bool) or not isinstance(shard_index, int) or shard_index < 0:
        raise ValueError("shard_index must be a nonnegative integer")
    return _checkpoint_dir(root, bank_version, node_id) / f"shard-{shard_index}.json"


def _failure_checkpoint_path(
    root: Path, bank_version: str, node_id: str, shard_index: int
) -> Path:
    return _checkpoint_path(root, bank_version, node_id, shard_index).with_suffix(
        ".failure.json"
    )


def _probe_checkpoint_path(
    root: Path, bank_version: str, node_id: str, item_count: int
) -> Path:
    if isinstance(item_count, bool) or not isinstance(item_count, int) or not 1 <= item_count <= answer_contract_review.SHARD_SIZE:
        raise ValueError("probe item count must be between one and five")
    return _checkpoint_dir(root, bank_version, node_id) / f"probe-{item_count}-items.json"


def _probe_question_checkpoint_path(
    root: Path, bank_version: str, node_id: str, question_id: str
) -> Path:
    safe_question_id = _safe_component(question_id, "question_id")
    return (
        _checkpoint_dir(root, bank_version, node_id)
        / f"probe-question-{safe_question_id}.json"
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _active_ledger(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "select * from question_bank_version_ledger where status = 'active' order by id"
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("exactly one active question-bank ledger row is required")
    return dict(rows[0])


def _authoritative_questions(
    conn: sqlite3.Connection, bank_version: str
) -> list[tuple[dict[str, Any], str]]:
    rows = conn.execute(
        """
        select qi.*, qrr.id as active_review_record_id
        from question_items qi
        join question_review_records qrr
          on qrr.question_id = qi.id
         and qrr.item_version = qi.item_version
         and qrr.review_status = 'approved'
         and qrr.active_eligible = 1
        where qi.item_version = ?
        order by qi.node_id, qi.id
        """,
        (bank_version,),
    ).fetchall()
    results = []
    seen = set()
    for row in rows:
        question = db.row_to_question(row)
        review_record_id = question.pop("active_review_record_id", None)
        if question["id"] in seen:
            raise ValueError("question has multiple active review records")
        seen.add(question["id"])
        if not db.question_review_record_allows_active_use(conn, question, review_record_id):
            raise ValueError(f"question review lineage is invalid: {question['id']}")
        question["_answer_contract_generation_required"] = True
        results.append((question, str(review_record_id)))
    return results


def _question_digest(question: dict[str, Any]) -> str:
    return _canonical_digest(
        {
            "question_id": question["id"],
            "item_version": question["item_version"],
            "node_id": question["node_id"],
            "kind": question["kind"],
            "prompt": question["prompt"],
            "answer_format": question["answer_format"],
            "expected_answer": question["expected_answer"],
            "solution_steps": question["solution_steps"],
        }
    )


def _stored_draft_contract(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    review_record_id: str,
) -> tuple[str, dict[str, Any], str] | None:
    from . import answer_contract_generation

    return answer_contract_generation.persisted_draft_for_review(
        conn,
        question,
        review_record_id,
    )


def _review_item(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    review_record_id: str,
) -> dict[str, Any]:
    stored = _stored_draft_contract(conn, question, review_record_id)
    if stored is None:
        raise ValueError(
            "answer contract design draft is missing for exact question version: "
            f"{question['id']}@{question['item_version']}"
        )
    contract_id, versioned_draft, contract_digest = stored
    design_source = "persisted_exact_version_draft"
    return {
        "review_item_handle": "review-item-"
        + _canonical_digest(
            {
                "question_id": question["id"],
                "item_version": question["item_version"],
                "review_record_id": review_record_id,
                "contract_id": contract_id,
                "contract_version": versioned_draft["contract_version"],
                "contract_digest_sha256": contract_digest,
            }
        )[:20],
        "question_id": question["id"],
        "item_version": question["item_version"],
        "question_digest_sha256": _question_digest(question),
        "contract_id": contract_id,
        "contract_version": versioned_draft["contract_version"],
        "contract_digest_sha256": contract_digest,
        "node_id": question["node_id"],
        "kind": question["kind"],
        "evidence_role": str(
            question.get("evidence_role")
            or question.get("evidence_goal")
            or "direct"
        ),
        "review_record_id": review_record_id,
        "design_source": design_source,
        "question": {
            "prompt": question["prompt"],
            "answer_format": question["answer_format"],
            "expected_answer": question["expected_answer"],
            "solution_steps": deepcopy(question["solution_steps"]),
        },
        "draft_contract": versioned_draft,
    }


def _authoritative_probe_question(
    conn: sqlite3.Connection,
    bank_version: str,
    question_id: str,
) -> tuple[dict[str, Any], str]:
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("probe question id must be a nonempty string")
    rows = conn.execute(
        """
        select qi.*, qrr.id as active_review_record_id
        from question_items qi
        join question_review_records qrr
          on qrr.question_id = qi.id
         and qrr.item_version = qi.item_version
         and qrr.review_status = 'approved'
         and qrr.active_eligible = 1
        where qi.id = ? and qi.item_version = ?
        order by qrr.id
        """,
        (question_id, bank_version),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError(
            "probe question review lineage requires exactly one authoritative active record"
        )
    question = db.row_to_question(rows[0])
    review_record_id = question.pop("active_review_record_id", None)
    if not db.question_review_record_allows_active_use(
        conn, question, review_record_id
    ):
        raise ValueError("probe question review lineage is invalid")
    question["_answer_contract_generation_required"] = True
    return question, str(review_record_id)


def build_probe_review_plan(
    conn: sqlite3.Connection,
    project_root: Path,
    question_id: str,
) -> dict[str, Any]:
    del project_root
    ledger = _active_ledger(conn)
    bank_version = str(ledger["question_bank_version"])
    question, review_record_id = _authoritative_probe_question(
        conn, bank_version, question_id
    )
    item = _review_item(conn, question, review_record_id)

    contract = internal_agents.load_v5_contract_for_agent(AGENT_KEY)
    model_route = model_router.answer_contract_review_route()
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    prompt_digest = internal_agents.file_sha256(prompt_path)
    schema_digest = internal_agents.canonical_json_sha256(
        contract["response_schema"]
    )
    route_policy = {
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "model_provider": "openai",
        "model_alias": model_route.model_alias,
        "concurrency": 1,
        "shard_size": answer_contract_review.SHARD_SIZE,
        "maximum_attempts": MAX_ATTEMPTS,
        "backoff_seconds": list(BACKOFF_SECONDS),
        "prompt_version_id": contract["prompt_version_id"],
        "response_schema_version": contract["response_schema_version"],
        "prompt_template_sha256": prompt_digest,
        "response_schema_digest_sha256": schema_digest,
    }
    shard = {
        "node_id": item["node_id"],
        "shard_index": 0,
        "items": [item],
    }
    shard["shard_digest_sha256"] = answer_contract_review.shard_digest(
        shard["items"]
    )
    node = {
        "node_id": item["node_id"],
        "node_context": db.get_graph_node(conn, item["node_id"]),
        "items": [item],
        "shards": [shard],
    }
    plan = {
        "bank_version": bank_version,
        "ledger_id": ledger["id"],
        "graph_version": ledger.get("graph_version") or "",
        "manifest_id": ledger.get("manifest_id") or "",
        "manifest_sha256": ledger.get("manifest_sha256") or "",
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "model_alias": model_route.model_alias,
        "prompt_version_id": contract["prompt_version_id"],
        "response_schema_version": contract["response_schema_version"],
        "minimum_confidence": float(
            contract.get("minimum_confidence_to_apply") or 0.8
        ),
        "prompt_template_sha256": prompt_digest,
        "response_schema_digest_sha256": schema_digest,
        "route_policy": route_policy,
        "route_policy_digest_sha256": _canonical_digest(route_policy),
        "persisted_draft_count": 1,
        "injected_test_draft_count": 0,
        "probe_only": True,
        "probe_question_id": question_id,
        "nodes": [node],
    }
    plan["plan_digest_sha256"] = _canonical_digest(plan)
    return plan


def build_review_plan(
    conn: sqlite3.Connection, project_root: Path
) -> dict[str, Any]:
    ledger = _active_ledger(conn)
    bank_version = str(ledger["question_bank_version"])
    question_rows = _authoritative_questions(conn, bank_version)
    if not question_rows:
        raise ValueError("active question bank has no authoritative reviewed questions")
    item_count = len(question_rows)
    node_count = len({question["node_id"] for question, _review_id in question_rows})
    if int(ledger.get("item_count") or 0) not in {0, item_count}:
        raise ValueError("active ledger item_count mismatch")
    if int(ledger.get("node_count") or 0) not in {0, node_count}:
        raise ValueError("active ledger node_count mismatch")

    contract = internal_agents.load_v5_contract_for_agent(AGENT_KEY)
    model_route = model_router.answer_contract_review_route()
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    prompt_digest = internal_agents.file_sha256(prompt_path)
    schema_digest = internal_agents.canonical_json_sha256(
        contract["response_schema"]
    )
    route_policy = {
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "model_provider": "openai",
        "model_alias": model_route.model_alias,
        "concurrency": 1,
        "shard_size": answer_contract_review.SHARD_SIZE,
        "maximum_attempts": MAX_ATTEMPTS,
        "backoff_seconds": list(BACKOFF_SECONDS),
        "prompt_version_id": contract["prompt_version_id"],
        "response_schema_version": contract["response_schema_version"],
        "prompt_template_sha256": prompt_digest,
        "response_schema_digest_sha256": schema_digest,
    }
    route_digest = _canonical_digest(route_policy)

    items = [
        _review_item(conn, question, review_id)
        for question, review_id in question_rows
    ]
    shards = answer_contract_review.plan_review_shards(items)
    shards_by_node: dict[str, list[dict[str, Any]]] = {}
    items_by_node: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        items_by_node.setdefault(item["node_id"], []).append(item)
    for shard in shards:
        shards_by_node.setdefault(shard["node_id"], []).append(shard)

    nodes = []
    for node_id in sorted(items_by_node):
        node_items = sorted(items_by_node[node_id], key=lambda item: item["question_id"])
        node_shards = sorted(shards_by_node[node_id], key=lambda shard: shard["shard_index"])
        if len(node_items) != 20 or len(node_shards) != 4:
            raise ValueError(f"node review partition is incomplete: {node_id}")
        nodes.append(
            {
                "node_id": node_id,
                "node_context": db.get_graph_node(conn, node_id),
                "items": node_items,
                "shards": node_shards,
            }
        )
    if len(nodes) != 56 or len(shards) != 224:
        raise ValueError("active bank review plan must contain 56 nodes and 224 shards")

    plan = {
        "bank_version": bank_version,
        "ledger_id": ledger["id"],
        "graph_version": ledger.get("graph_version") or "",
        "manifest_id": ledger.get("manifest_id") or "",
        "manifest_sha256": ledger.get("manifest_sha256") or "",
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "model_alias": model_route.model_alias,
        "prompt_version_id": contract["prompt_version_id"],
        "response_schema_version": contract["response_schema_version"],
        "minimum_confidence": float(contract.get("minimum_confidence_to_apply") or 0.8),
        "prompt_template_sha256": prompt_digest,
        "response_schema_digest_sha256": schema_digest,
        "route_policy": route_policy,
        "route_policy_digest_sha256": route_digest,
        "persisted_draft_count": sum(
            item["design_source"] == "persisted_exact_version_draft"
            for item in items
        ),
        "injected_test_draft_count": sum(
            item["design_source"] == "injected_test_profile_draft"
            for item in items
        ),
        "nodes": nodes,
    }
    plan["plan_digest_sha256"] = _canonical_digest(plan)
    return plan


def _packet(plan: dict[str, Any], node: dict[str, Any], shard: dict[str, Any]) -> dict[str, Any]:
    packet = {
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "bank_version": plan["bank_version"],
        "node_id": node["node_id"],
        "node_context": deepcopy(node["node_context"]),
        "shard_index": shard["shard_index"],
        "shard_digest_sha256": shard["shard_digest_sha256"],
        "prompt_version_id": plan["prompt_version_id"],
        "response_schema_version": plan["response_schema_version"],
        "minimum_confidence": plan["minimum_confidence"],
        "model_alias": plan["model_alias"],
        "prompt_template_sha256": plan["prompt_template_sha256"],
        "response_schema_digest_sha256": plan["response_schema_digest_sha256"],
        "route_policy_digest_sha256": plan["route_policy_digest_sha256"],
        "items": deepcopy(shard["items"]),
    }
    packet["rendered_prompt_sha256"] = _rendered_prompt_digest(packet)
    return packet


def _review_item_handles(packet: dict[str, Any]) -> list[str]:
    return [str(item["review_item_handle"]) for item in packet["items"]]


def _trusted_review_context(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_key": packet["agent_key"],
        "phase": packet["phase"],
        "bank_version": packet["bank_version"],
        "node_id": packet["node_id"],
        "shard_index": packet["shard_index"],
        "shard_digest_sha256": packet["shard_digest_sha256"],
        "prompt_version_id": packet["prompt_version_id"],
        "response_schema_version": packet["response_schema_version"],
        "minimum_confidence": packet["minimum_confidence"],
        "model_alias": packet["model_alias"],
        "prompt_template_sha256": packet["prompt_template_sha256"],
        "response_schema_digest_sha256": packet[
            "response_schema_digest_sha256"
        ],
        "route_policy_digest_sha256": packet["route_policy_digest_sha256"],
        "review_item_count": len(packet["items"]),
        "item_handles": _review_item_handles(packet),
    }


def _untrusted_review_payload(packet: dict[str, Any]) -> dict[str, Any]:
    lineage_fields = {
        "stable_contract_id",
        "contract_version",
        "question_id",
        "item_version",
        "node_id",
        "question_digest_sha256",
        "contract_digest_sha256",
        "review_record_id",
    }
    handles = _review_item_handles(packet)
    items = []
    for handle, item in zip(handles, packet["items"]):
        contract_content = {
            key: deepcopy(value)
            for key, value in item["draft_contract"].items()
            if key not in lineage_fields
        }
        items.append(
            {
                "item_handle": handle,
                "bound_node_id": item["node_id"],
                "kind": item["kind"],
                "evidence_role": item["evidence_role"],
                "question": deepcopy(item["question"]),
                "draft_contract": contract_content,
            }
        )
    return {
        "node_context": deepcopy(packet["node_context"]),
        "items": items,
    }


def _semantic_review_request(
    packet: dict[str, Any],
    *,
    transport_timeout_seconds: float | None = None,
) -> semantic_agents.SemanticAgentRequest:
    return semantic_agents.SemanticAgentRequest(
        agent_key=AGENT_KEY,
        phase=PHASE,
        trusted_context=_trusted_review_context(packet),
        untrusted_payload=_untrusted_review_payload(packet),
        provider_mode="live_model",
        source_refs={"shard_digest_sha256": packet["shard_digest_sha256"]},
        transport_timeout_seconds=transport_timeout_seconds,
    )


def _retryable(exc: Exception) -> bool:
    if getattr(exc, "retryable", False):
        return True
    if getattr(exc, "status_code", None) in {429, 500, 502, 503, 504}:
        return True
    return model_router.is_retryable_model_call_error(exc)


def _retry_delay(exc: Exception, attempt_index: int) -> float:
    base = float(BACKOFF_SECONDS[min(attempt_index, len(BACKOFF_SECONDS) - 1)])
    retry_after = getattr(exc, "retry_after_seconds", None)
    if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool):
        return max(base, min(MAX_RETRY_AFTER_SECONDS, max(0.0, float(retry_after))))
    return base


def _attempt_error_metadata(exc: Exception) -> dict[str, Any]:
    endpoint = getattr(exc, "endpoint", "") or "responses"
    return {
        "error_type": type(exc).__name__,
        "message": str(exc)[:800],
        "error": str(exc)[:800],
        "status_code": getattr(exc, "status_code", None),
        "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
        "endpoint": endpoint,
        "transport_endpoint": endpoint,
        "structured_json_mode": getattr(exc, "structured_json_mode", "") or "json_schema",
    }


def _terminal_failure_receipt(
    plan: dict[str, Any],
    node: dict[str, Any],
    shard: dict[str, Any],
    *,
    attempts: list[dict[str, Any]],
    model_calls: int,
    wall_time_seconds: float,
    wall_deadline_seconds: float,
    error: Exception,
    probe_only: bool,
) -> dict[str, Any]:
    return _receipt(
        {
            "sealed": True,
            "status": "terminal_failure",
            "agent_key": AGENT_KEY,
            "phase": PHASE,
            "bank_version": plan["bank_version"],
            "node_id": node["node_id"],
            "shard_index": shard["shard_index"],
            "shard_digest_sha256": shard["shard_digest_sha256"],
            "item_count": len(shard["items"]),
            "probe_only": probe_only,
            "attempt_budget": MAX_ATTEMPTS,
            "attempt_count": len(attempts),
            "model_calls": model_calls,
            "wall_time_seconds": round(max(0.0, wall_time_seconds), 6),
            "wall_deadline_seconds": float(wall_deadline_seconds),
            "retryable": _retryable(error),
            "terminal_error": _attempt_error_metadata(error),
            "attempts": deepcopy(attempts),
            "transport_pass": False,
            "semantic_response_valid": False,
            "semantic_approval": False,
            "repair_issues": [],
            "repair_routes": [],
            "activation_eligible": False,
            "live_semantic_pass": False,
        }
    )


def _load_terminal_failure(
    path: Path,
    plan: dict[str, Any],
    node: dict[str, Any],
    shard: dict[str, Any],
    *,
    probe_only: bool,
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
        "node_id": node["node_id"],
        "shard_index": shard["shard_index"],
        "shard_digest_sha256": shard["shard_digest_sha256"],
        "item_count": len(shard["items"]),
        "probe_only": probe_only,
        "attempt_budget": MAX_ATTEMPTS,
        "transport_pass": False,
        "semantic_response_valid": False,
        "semantic_approval": False,
        "repair_issues": [],
        "repair_routes": [],
        "activation_eligible": False,
        "live_semantic_pass": False,
    }
    if not _valid_receipt_digest(receipt):
        return None
    if any(receipt.get(field) != value for field, value in expected.items()):
        return None
    if receipt.get("attempt_count") != len(receipt.get("attempts") or []):
        return None
    if receipt.get("model_calls") != receipt.get("attempt_count"):
        return None
    return receipt


def _rendered_prompt_digest(packet: dict[str, Any]) -> str:
    return semantic_agents.rendered_prompt_sha256_for_request(
        _semantic_review_request(packet)
    )


def _derive_evidence_scope(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    shard: dict[str, Any],
    packet: dict[str, Any],
    envelope: dict[str, Any],
) -> tuple[str, str | None]:
    run_id = envelope.get("agent_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return "injected_test_fixture", None
    row = conn.execute("select * from agent_runs where id = ?", (run_id,)).fetchone()
    if not row:
        return "injected_test_fixture", run_id
    semantic_output = envelope.get("semantic_output")
    if not isinstance(semantic_output, dict):
        semantic_output = envelope.get("output")
    output_digest = _canonical_digest(semantic_output)
    expected_values = {
        "agent_key": AGENT_KEY,
        "engine_type": "internal_learning_agent",
        "phase": PHASE,
        "trigger": "contract_activation_review",
        "status": "accepted",
        "model_provider": "openai",
        "model_name": plan["model_alias"],
        "model_alias": plan["model_alias"],
        "prompt_version_id": plan["prompt_version_id"],
        "prompt_template_sha256": plan["prompt_template_sha256"],
        "rendered_prompt_sha256": _rendered_prompt_digest(packet),
        "response_schema_version": plan["response_schema_version"],
        "response_schema_sha256": plan["response_schema_digest_sha256"],
        "input_digest_sha256": shard["shard_digest_sha256"],
        "output_digest_sha256": output_digest,
        "error_reason": "",
    }
    if any(row[field] != value for field, value in expected_values.items()):
        return "injected_test_fixture", run_id
    if db.json_load(row["input_refs_json"], {}) != {
        "shard_digest_sha256": shard["shard_digest_sha256"]
    }:
        return "injected_test_fixture", run_id
    if db.json_load(row["model_params_json"], {}) != {"temperature": 0}:
        return "injected_test_fixture", run_id
    if db.json_load(row["validation_errors_json"], []) != []:
        return "injected_test_fixture", run_id
    if db.json_load(row["output_json"], None) != semantic_output:
        return "injected_test_fixture", run_id
    return "live_model_call", run_id


def _validate_envelope(
    plan: dict[str, Any],
    shard: dict[str, Any],
    envelope: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if not isinstance(envelope, dict):
        raise TypeError("reviewer envelope must be a mapping")
    expected = {
        "agent_key": AGENT_KEY,
        "phase": PHASE,
        "status": "accepted",
        "provider_mode": "live_model",
        "model_alias": plan["model_alias"],
        "prompt_version_id": plan["prompt_version_id"],
        "response_schema_version": plan["response_schema_version"],
        "route_policy_digest_sha256": plan["route_policy_digest_sha256"],
        "shard_digest_sha256": shard["shard_digest_sha256"],
    }
    if any(envelope.get(field) != value for field, value in expected.items()):
        raise ValueError("reviewer envelope lineage mismatch")
    output = envelope.get("output")
    if not isinstance(output, dict) or output.get("schema_version") != plan["response_schema_version"]:
        raise ValueError("reviewer output schema version mismatch")
    semantic_output = envelope.get("semantic_output")
    output_items = output.get("items")
    if (
        semantic_output is None
        and isinstance(output_items, list)
        and output_items
        and all(isinstance(item, dict) and "item_handle" in item for item in output_items)
    ):
        semantic_output = deepcopy(output)
        rebound = answer_contract_review.bind_semantic_review_results(
            shard["items"],
            semantic_output["items"],
            item_handles=[item["review_item_handle"] for item in shard["items"]],
        )
        output = {
            "schema_version": semantic_output["schema_version"],
            "items": rebound,
        }
        envelope["semantic_output"] = semantic_output
        envelope["output"] = output
    if semantic_output is not None:
        if (
            not isinstance(semantic_output, dict)
            or semantic_output.get("schema_version") != plan["response_schema_version"]
        ):
            raise ValueError("semantic reviewer output schema version mismatch")
        rebound = answer_contract_review.bind_semantic_review_results(
            shard["items"],
            semantic_output.get("items"),
            item_handles=[item["review_item_handle"] for item in shard["items"]],
        )
        if output.get("items") != rebound:
            raise ValueError("locally bound reviewer output does not match semantic output")
    validated = answer_contract_review.validate_review_items(
        shard["items"],
        output.get("items"),
        provider_mode="live_model",
        minimum_confidence=plan["minimum_confidence"],
    )
    shard_receipt = answer_contract_review.build_shard_receipt(
        shard,
        validated,
        provider_mode="live_model",
    )
    if shard_receipt is None:
        raise ValueError("reviewer output did not complete the shard")
    return validated, shard_receipt, _semantic_review_state(validated)


def _semantic_repair_issues(
    validated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues = []
    for item in validated:
        lineage = {
            "question_id": item["question_id"],
            "item_version": item["item_version"],
            "contract_id": item["contract_id"],
            "contract_version": item["contract_version"],
            "bound_node_id": item["bound_node_id"],
        }
        route = item.get("repair_route")
        if isinstance(route, dict):
            issues.append(
                {
                    **lineage,
                    "issue_type": str(route["reason_code"]),
                    "repair_route": deepcopy(route),
                }
            )
        if item.get("needs_retry") is True and not (
            isinstance(route, dict)
            and route.get("reason_code") == "semantic_review_low_confidence"
        ):
            manual_route = {
                "owner": "answer_contract_review",
                "action": "manual_confidence_review",
                "reason_code": "semantic_review_low_confidence",
                "preserve_bound_node": True,
            }
            issues.append(
                {
                    **lineage,
                    "issue_type": manual_route["reason_code"],
                    "repair_route": manual_route,
                }
            )
    return issues


def _semantic_review_state(
    validated: list[dict[str, Any]],
    *,
    evidence_scope: str | None = None,
) -> dict[str, Any]:
    if not validated:
        raise ValueError("semantic reviewer returned no validated items")
    repair_issues = _semantic_repair_issues(validated)
    semantic_approval = all(
        item["review_status"] == "approved" for item in validated
    )
    activation_eligible = (
        evidence_scope == "live_model_call"
        and all(item["activation_eligible"] for item in validated)
    )
    return {
        "transport_pass": evidence_scope == "live_model_call",
        "semantic_response_valid": True,
        "semantic_approval": semantic_approval,
        "activation_eligible": activation_eligible,
        "live_semantic_pass": activation_eligible,
        "repair_issues": repair_issues,
        "repair_routes": [
            deepcopy(issue["repair_route"]) for issue in repair_issues
        ],
    }


def _execute_review_packet(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    node: dict[str, Any],
    shard: dict[str, Any],
    packet: dict[str, Any],
    reviewer: Callable[[dict[str, Any]], dict[str, Any]],
    failure_path: Path,
    *,
    probe_only: bool,
    sleep_fn: Callable[[float], None],
    monotonic_fn: Callable[[], float],
    wall_deadline_seconds: float,
) -> dict[str, Any]:
    prior_failure = _load_terminal_failure(
        failure_path,
        plan,
        node,
        shard,
        probe_only=probe_only,
    )
    if prior_failure is not None:
        report = {
            "status": "terminal_failure",
            "bank_version": plan["bank_version"],
            "node_id": node["node_id"],
            "shard_index": shard["shard_index"],
            "probe_only": probe_only,
            "resumed_terminal_failure": True,
            "attempt_count": prior_failure["attempt_count"],
            "model_calls": prior_failure["model_calls"],
            "wall_time_seconds": prior_failure["wall_time_seconds"],
            "failure_receipt_path": str(failure_path),
            "transport_pass": False,
            "semantic_response_valid": False,
            "semantic_approval": False,
            "repair_issues": [],
            "repair_routes": [],
            "live_semantic_pass": False,
            "activation_eligible": False,
        }
        raise ReviewRunError(
            str(prior_failure.get("terminal_error", {}).get("message") or "terminal review failure"),
            report,
        )

    if wall_deadline_seconds <= 0:
        raise ValueError("wall_deadline_seconds must be positive")
    start = monotonic_fn()
    attempts: list[dict[str, Any]] = []
    model_calls = 0
    last_error: Exception | None = None
    configured_call_timeout = getattr(reviewer, "transport_timeout_seconds", None)
    call_timeout = (
        float(configured_call_timeout)
        if isinstance(configured_call_timeout, (int, float))
        and not isinstance(configured_call_timeout, bool)
        and configured_call_timeout > 0
        else 0.0
    )

    for attempt_index in range(MAX_ATTEMPTS):
        elapsed_before = max(0.0, monotonic_fn() - start)
        remaining = wall_deadline_seconds - elapsed_before
        if remaining <= 0:
            last_error = TimeoutError("review shard wall deadline exhausted before next model call")
            break
        if call_timeout and hasattr(reviewer, "current_transport_timeout_seconds"):
            reviewer.current_transport_timeout_seconds = max(0.01, min(call_timeout, remaining))  # type: ignore[attr-defined]
        call_started = monotonic_fn()
        model_calls += 1
        try:
            envelope = reviewer(deepcopy(packet))
            validated, shard_receipt, _local_state = _validate_envelope(
                plan, shard, envelope
            )
            evidence_scope, agent_run_id = _derive_evidence_scope(
                conn, plan, shard, packet, envelope
            )
            review_state = _semantic_review_state(
                validated,
                evidence_scope=evidence_scope,
            )
            attempts.append(
                {
                    "attempt": attempt_index + 1,
                    "outcome": "accepted",
                    "duration_seconds": round(max(0.0, monotonic_fn() - call_started), 6),
                    "transport_endpoint": envelope.get("transport_endpoint", "responses"),
                    "structured_json_mode": envelope.get("structured_json_mode", "json_schema"),
                }
            )
            if failure_path.exists():
                failure_path.unlink()
            return {
                "envelope": envelope,
                "validated": validated,
                "shard_receipt": shard_receipt,
                "evidence_scope": evidence_scope,
                "agent_run_id": agent_run_id,
                "review_state": review_state,
                "attempts": attempts,
                "attempt_count": len(attempts),
                "model_calls": model_calls,
                "wall_time_seconds": round(max(0.0, monotonic_fn() - start), 6),
            }
        except Exception as exc:
            last_error = exc
            retryable = _retryable(exc)
            attempt_meta = {
                "attempt": attempt_index + 1,
                "outcome": "retryable_failure" if retryable else "terminal_failure",
                "duration_seconds": round(max(0.0, monotonic_fn() - call_started), 6),
                "retryable": retryable,
                **_attempt_error_metadata(exc),
            }
            attempts.append(attempt_meta)
            if not retryable or attempt_index + 1 >= MAX_ATTEMPTS:
                break
            delay = _retry_delay(exc, attempt_index)
            elapsed_after = max(0.0, monotonic_fn() - start)
            remaining_after = wall_deadline_seconds - elapsed_after
            if remaining_after <= delay:
                break
            attempt_meta["sleep_seconds"] = delay
            sleep_fn(delay)

    if last_error is None:
        last_error = TimeoutError("review shard wall deadline exhausted")
    wall_time = max(0.0, monotonic_fn() - start)
    receipt = _terminal_failure_receipt(
        plan,
        node,
        shard,
        attempts=attempts,
        model_calls=model_calls,
        wall_time_seconds=wall_time,
        wall_deadline_seconds=wall_deadline_seconds,
        error=last_error,
        probe_only=probe_only,
    )
    _atomic_write_json(failure_path, receipt)
    report = {
        "status": "terminal_failure",
        "bank_version": plan["bank_version"],
        "node_id": node["node_id"],
        "shard_index": shard["shard_index"],
        "probe_only": probe_only,
        "attempt_count": len(attempts),
        "model_calls": model_calls,
        "wall_time_seconds": receipt["wall_time_seconds"],
        "wall_deadline_seconds": wall_deadline_seconds,
        "failure_receipt_path": str(failure_path),
        "transport_pass": False,
        "semantic_response_valid": False,
        "semantic_approval": False,
        "repair_issues": [],
        "repair_routes": [],
        "live_semantic_pass": False,
        "activation_eligible": False,
    }
    raise ReviewRunError(str(last_error), report) from last_error


def _checkpoint_payload(
    plan: dict[str, Any],
    node: dict[str, Any],
    shard: dict[str, Any],
    envelope: dict[str, Any],
    validated: list[dict[str, Any]],
    shard_receipt: dict[str, Any],
    *,
    attempt_count: int,
    attempts: list[dict[str, Any]],
    model_calls: int,
    wall_time_seconds: float,
    wall_deadline_seconds: float,
    evidence_scope: str,
    agent_run_id: str | None,
    review_state: dict[str, Any],
) -> dict[str, Any]:
    expected_state = _semantic_review_state(
        validated,
        evidence_scope=evidence_scope,
    )
    if review_state != expected_state:
        raise ValueError("review state does not match validated semantic outcome")
    return _receipt(
        {
            "sealed": True,
            "status": "accepted",
            "agent_key": AGENT_KEY,
            "phase": PHASE,
            "provider_mode": "live_model",
            "model_alias": plan["model_alias"],
            "prompt_version_id": plan["prompt_version_id"],
            "response_schema_version": plan["response_schema_version"],
            "prompt_template_sha256": plan["prompt_template_sha256"],
            "response_schema_digest_sha256": plan["response_schema_digest_sha256"],
            "route_policy_digest_sha256": plan["route_policy_digest_sha256"],
            "bank_version": plan["bank_version"],
            "node_id": node["node_id"],
            "shard_index": shard["shard_index"],
            "shard_digest_sha256": shard["shard_digest_sha256"],
            "attempt_count": attempt_count,
            "attempt_budget": MAX_ATTEMPTS,
            "attempts": deepcopy(attempts),
            "model_calls": model_calls,
            "wall_time_seconds": wall_time_seconds,
            "wall_deadline_seconds": wall_deadline_seconds,
            "agent_run_id": agent_run_id,
            "evidence_scope": evidence_scope,
            **deepcopy(expected_state),
            "output": deepcopy(envelope["output"]),
            "semantic_output": deepcopy(
                envelope.get("semantic_output") or envelope["output"]
            ),
            "semantic_output_digest_sha256": _canonical_digest(
                envelope.get("semantic_output") or envelope["output"]
            ),
            "bound_output_digest_sha256": _canonical_digest(envelope["output"]),
            "validated_items": validated,
            "shard_receipt": shard_receipt,
        }
    )


def _load_valid_checkpoint(
    conn: sqlite3.Connection,
    path: Path,
    plan: dict[str, Any],
    node: dict[str, Any],
    shard: dict[str, Any],
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        if not _valid_receipt_digest(checkpoint):
            return None
        required = {
            "sealed": True,
            "status": "accepted",
            "agent_key": AGENT_KEY,
            "phase": PHASE,
            "provider_mode": "live_model",
            "model_alias": plan["model_alias"],
            "prompt_version_id": plan["prompt_version_id"],
            "response_schema_version": plan["response_schema_version"],
            "prompt_template_sha256": plan["prompt_template_sha256"],
            "response_schema_digest_sha256": plan["response_schema_digest_sha256"],
            "route_policy_digest_sha256": plan["route_policy_digest_sha256"],
            "bank_version": plan["bank_version"],
            "node_id": node["node_id"],
            "shard_index": shard["shard_index"],
            "shard_digest_sha256": shard["shard_digest_sha256"],
        }
        if any(checkpoint.get(field) != value for field, value in required.items()):
            return None
        if checkpoint.get("evidence_scope") not in {"injected_test_fixture", "live_model_call"}:
            return None
        bound_output = checkpoint.get("output")
        semantic_output = checkpoint.get("semantic_output")
        if semantic_output is None:
            semantic_output = bound_output
        if checkpoint.get("semantic_output_digest_sha256") not in {
            None,
            _canonical_digest(semantic_output),
        }:
            return None
        if checkpoint.get("bound_output_digest_sha256") not in {
            None,
            _canonical_digest(bound_output),
        }:
            return None
        envelope = {
            "agent_key": checkpoint["agent_key"],
            "phase": checkpoint["phase"],
            "status": checkpoint["status"],
            "provider_mode": checkpoint["provider_mode"],
            "model_alias": checkpoint["model_alias"],
            "prompt_version_id": checkpoint["prompt_version_id"],
            "response_schema_version": checkpoint["response_schema_version"],
            "route_policy_digest_sha256": checkpoint["route_policy_digest_sha256"],
            "shard_digest_sha256": checkpoint["shard_digest_sha256"],
            "agent_run_id": checkpoint.get("agent_run_id"),
            "output": bound_output,
            "semantic_output": semantic_output,
        }
        validated, shard_receipt, _local_state = _validate_envelope(
            plan, shard, envelope
        )
        packet = _packet(plan, node, shard)
        evidence_scope, agent_run_id = _derive_evidence_scope(
            conn, plan, shard, packet, envelope
        )
        if checkpoint.get("validated_items") != validated:
            return None
        if checkpoint.get("shard_receipt") != shard_receipt:
            return None
        expected_state = _semantic_review_state(
            validated,
            evidence_scope=evidence_scope,
        )
        if any(checkpoint.get(field) != value for field, value in expected_state.items()):
            return None
        if checkpoint.get("evidence_scope") != evidence_scope:
            return None
        if checkpoint.get("agent_run_id") != agent_run_id:
            return None
        return checkpoint
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _probe_checkpoint_payload(
    plan: dict[str, Any],
    node: dict[str, Any],
    shard: dict[str, Any],
    execution: dict[str, Any],
    *,
    wall_deadline_seconds: float,
) -> dict[str, Any]:
    checkpoint = _checkpoint_payload(
        plan,
        node,
        shard,
        execution["envelope"],
        execution["validated"],
        execution["shard_receipt"],
        attempt_count=execution["attempt_count"],
        attempts=execution["attempts"],
        model_calls=execution["model_calls"],
        wall_time_seconds=execution["wall_time_seconds"],
        wall_deadline_seconds=wall_deadline_seconds,
        evidence_scope=execution["evidence_scope"],
        agent_run_id=execution["agent_run_id"],
        review_state=execution["review_state"],
    )
    body = {
        key: deepcopy(value)
        for key, value in checkpoint.items()
        if key != "receipt_digest_sha256"
    }
    body.update(
        {
            "probe_only": True,
            "probe_question_id": shard["items"][0]["question_id"],
            "item_count": len(shard["items"]),
            "question_ids": [item["question_id"] for item in shard["items"]],
            "transport_endpoint": execution["envelope"].get(
                "transport_endpoint", "responses"
            ),
            "structured_json_mode": execution["envelope"].get(
                "structured_json_mode", "json_schema"
            ),
            "semantic_evidence_eligible": checkpoint["activation_eligible"],
            "activation_eligible": False,
            "live_semantic_pass": False,
        }
    )
    return _receipt(body)


def _load_valid_probe_checkpoint(
    conn: sqlite3.Connection,
    path: Path,
    plan: dict[str, Any],
    node: dict[str, Any],
    shard: dict[str, Any],
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        if not _valid_receipt_digest(checkpoint):
            return None
        required = {
            "sealed": True,
            "status": "accepted",
            "agent_key": AGENT_KEY,
            "phase": PHASE,
            "provider_mode": "live_model",
            "model_alias": plan["model_alias"],
            "prompt_version_id": plan["prompt_version_id"],
            "response_schema_version": plan["response_schema_version"],
            "prompt_template_sha256": plan["prompt_template_sha256"],
            "response_schema_digest_sha256": plan[
                "response_schema_digest_sha256"
            ],
            "route_policy_digest_sha256": plan["route_policy_digest_sha256"],
            "bank_version": plan["bank_version"],
            "node_id": node["node_id"],
            "shard_index": shard["shard_index"],
            "shard_digest_sha256": shard["shard_digest_sha256"],
            "probe_only": True,
            "probe_question_id": shard["items"][0]["question_id"],
            "item_count": len(shard["items"]),
            "question_ids": [item["question_id"] for item in shard["items"]],
            "activation_eligible": False,
            "live_semantic_pass": False,
        }
        if any(checkpoint.get(field) != value for field, value in required.items()):
            return None
        bound_output = checkpoint.get("output")
        semantic_output = checkpoint.get("semantic_output")
        if semantic_output is None:
            semantic_output = bound_output
        if checkpoint.get("semantic_output_digest_sha256") != _canonical_digest(
            semantic_output
        ):
            return None
        if checkpoint.get("bound_output_digest_sha256") != _canonical_digest(
            bound_output
        ):
            return None
        envelope = {
            "agent_key": checkpoint["agent_key"],
            "phase": checkpoint["phase"],
            "status": checkpoint["status"],
            "provider_mode": checkpoint["provider_mode"],
            "model_alias": checkpoint["model_alias"],
            "prompt_version_id": checkpoint["prompt_version_id"],
            "response_schema_version": checkpoint["response_schema_version"],
            "route_policy_digest_sha256": checkpoint[
                "route_policy_digest_sha256"
            ],
            "shard_digest_sha256": checkpoint["shard_digest_sha256"],
            "agent_run_id": checkpoint.get("agent_run_id"),
            "output": bound_output,
            "semantic_output": semantic_output,
        }
        validated, shard_receipt, _local_state = _validate_envelope(
            plan, shard, envelope
        )
        packet = _packet(plan, node, shard)
        evidence_scope, agent_run_id = _derive_evidence_scope(
            conn, plan, shard, packet, envelope
        )
        expected_state = _semantic_review_state(
            validated, evidence_scope=evidence_scope
        )
        for field in (
            "transport_pass",
            "semantic_response_valid",
            "semantic_approval",
            "repair_issues",
            "repair_routes",
        ):
            if checkpoint.get(field) != expected_state[field]:
                return None
        if checkpoint.get("semantic_evidence_eligible") != expected_state[
            "activation_eligible"
        ]:
            return None
        if checkpoint.get("validated_items") != validated:
            return None
        if checkpoint.get("shard_receipt") != shard_receipt:
            return None
        if checkpoint.get("evidence_scope") != evidence_scope:
            return None
        if checkpoint.get("agent_run_id") != agent_run_id:
            return None
        return checkpoint
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _write_node_receipt(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    node: dict[str, Any],
    checkpoint_root: Path,
) -> dict[str, Any] | None:
    checkpoints = []
    for shard in node["shards"]:
        path = _checkpoint_path(
            checkpoint_root,
            plan["bank_version"],
            node["node_id"],
            shard["shard_index"],
        )
        checkpoint = _load_valid_checkpoint(conn, path, plan, node, shard)
        if checkpoint is None:
            return None
        checkpoints.append(checkpoint)
    scopes = {checkpoint["evidence_scope"] for checkpoint in checkpoints}
    evidence_scope = scopes.pop() if len(scopes) == 1 else "mixed"
    payload = _receipt(
        {
            "sealed": True,
            "status": "complete",
            "bank_version": plan["bank_version"],
            "node_id": node["node_id"],
            "shard_receipt_count": len(checkpoints),
            "item_count": sum(checkpoint["shard_receipt"]["item_count"] for checkpoint in checkpoints),
            "evidence_scope": evidence_scope,
            "transport_pass": all(checkpoint["transport_pass"] for checkpoint in checkpoints),
            "semantic_response_valid": all(
                checkpoint["semantic_response_valid"] for checkpoint in checkpoints
            ),
            "semantic_approval": all(
                checkpoint["semantic_approval"] for checkpoint in checkpoints
            ),
            "activation_eligible": all(checkpoint["activation_eligible"] for checkpoint in checkpoints),
            "live_semantic_pass": all(
                checkpoint["live_semantic_pass"] for checkpoint in checkpoints
            ),
            "repair_issues": [
                deepcopy(issue)
                for checkpoint in checkpoints
                for issue in checkpoint["repair_issues"]
            ],
            "repair_routes": [
                deepcopy(route)
                for checkpoint in checkpoints
                for route in checkpoint["repair_routes"]
            ],
            "shard_receipt_digests": [checkpoint["receipt_digest_sha256"] for checkpoint in checkpoints],
        }
    )
    path = _checkpoint_dir(checkpoint_root, plan["bank_version"], node["node_id"]) / "node-receipt.json"
    _atomic_write_json(path, payload)
    return payload


def make_live_reviewer(
    conn: sqlite3.Connection,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    route = model_router.answer_contract_review_route()
    if not route.enabled:
        raise ValueError("model_not_configured")
    if (
        route.agent_key != AGENT_KEY
        or route.task != PHASE
        or route.provider != "openai"
    ):
        raise ValueError("answer contract review route lineage mismatch")

    def reviewer(packet: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(packet, dict):
            raise TypeError("review packet must be a mapping")
        if (
            packet.get("agent_key") != AGENT_KEY
            or packet.get("phase") != PHASE
            or packet.get("model_alias") != route.model_alias
        ):
            raise ValueError("review packet route lineage mismatch")
        request = _semantic_review_request(
            packet,
            transport_timeout_seconds=getattr(
                reviewer,
                "current_transport_timeout_seconds",
                route.timeout_seconds,
            ),
        )
        source_refs = dict(request.source_refs)
        envelope = semantic_agents.call_answer_contract_reviewer_agent(request)
        if (
            envelope.agent_key != AGENT_KEY
            or envelope.phase != PHASE
            or envelope.status != "accepted"
            or envelope.provider_mode != "live_model"
            or envelope.prompt_version_id != packet["prompt_version_id"]
            or envelope.response_schema_version != packet["response_schema_version"]
        ):
            raise ValueError("semantic reviewer did not return accepted live lineage")
        route_meta = envelope.route_meta
        expected_meta = {
            "prompt_template_sha256": packet["prompt_template_sha256"],
            "rendered_prompt_sha256": _rendered_prompt_digest(packet),
            "response_schema_sha256": packet["response_schema_digest_sha256"],
        }
        if any(route_meta.get(field) != value for field, value in expected_meta.items()):
            raise ValueError("semantic reviewer route metadata mismatch")
        semantic_output = envelope.output
        if (
            not isinstance(semantic_output, dict)
            or semantic_output.get("schema_version") != packet["response_schema_version"]
        ):
            raise ValueError("semantic reviewer output schema mismatch")
        bound_items = answer_contract_review.bind_semantic_review_results(
            packet["items"],
            semantic_output.get("items"),
            item_handles=_review_item_handles(packet),
        )
        output = {
            "schema_version": semantic_output["schema_version"],
            "items": bound_items,
        }
        validated = answer_contract_review.validate_review_items(
            packet["items"],
            output.get("items"),
            provider_mode="live_model",
            minimum_confidence=float(packet["minimum_confidence"]),
        )
        review_state = _semantic_review_state(
            validated,
            evidence_scope="live_model_call",
        )

        run_id = f"AR-{uuid.uuid4().hex[:12]}"
        output_digest = _canonical_digest(semantic_output)
        now = db.now_iso()
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
                ) values (?, ?, 'internal_learning_agent', null, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, 'accepted', ?, ?, ?, '[]', '', ?)
                """,
                (
                    run_id,
                    AGENT_KEY,
                    PHASE,
                    "contract_activation_review",
                    db.json_dump(source_refs),
                    packet["shard_digest_sha256"],
                    packet["prompt_version_id"],
                    packet["prompt_template_sha256"],
                    _rendered_prompt_digest(packet),
                    route.provider,
                    route.model,
                    route.model_alias,
                    db.json_dump(route.model_params),
                    packet["response_schema_version"],
                    packet["response_schema_digest_sha256"],
                    float(envelope.confidence),
                    db.json_dump(semantic_output),
                    output_digest,
                    now,
                ),
            )
        return {
            "agent_key": AGENT_KEY,
            "phase": PHASE,
            "status": "accepted",
            "provider_mode": "live_model",
            "model_alias": route.model_alias,
            "prompt_version_id": packet["prompt_version_id"],
            "prompt_template_sha256": packet["prompt_template_sha256"],
            "rendered_prompt_sha256": _rendered_prompt_digest(packet),
            "response_schema_version": packet["response_schema_version"],
            "response_schema_sha256": packet["response_schema_digest_sha256"],
            "route_policy_digest_sha256": packet["route_policy_digest_sha256"],
            "shard_digest_sha256": packet["shard_digest_sha256"],
            "transport_endpoint": route_meta.get("structured_json_endpoint", "responses"),
            "structured_json_mode": route_meta.get("structured_json_mode", "json_schema"),
            "evidence_scope": "live_model_call",
            "agent_run_id": run_id,
            **review_state,
            "output": deepcopy(output),
            "semantic_output": deepcopy(semantic_output),
        }

    reviewer.transport_timeout_seconds = float(route.timeout_seconds)  # type: ignore[attr-defined]
    reviewer.current_transport_timeout_seconds = float(route.timeout_seconds)  # type: ignore[attr-defined]
    reviewer.transport_endpoint = "responses"  # type: ignore[attr-defined]
    reviewer.structured_json_mode = "json_schema"  # type: ignore[attr-defined]
    return reviewer


def run_live_review(
    conn: sqlite3.Connection,
    project_root: Path,
    reviewer: Callable[[dict[str, Any]], dict[str, Any]],
    checkpoint_root: Path,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] | None = None,
    max_shards: int | None = None,
    shard_wall_seconds: float | None = None,
    probe_question_id: str | None = None,
) -> dict[str, Any]:
    if not callable(reviewer):
        raise TypeError("reviewer must be callable")
    if max_shards is not None and (
        isinstance(max_shards, bool) or not isinstance(max_shards, int) or max_shards < 0
    ):
        raise ValueError("max_shards must be a nonnegative integer or None")
    if probe_question_id is not None:
        if max_shards not in {None, 1}:
            raise ValueError("one-item probe can consider only one shard")
        return run_live_probe(
            conn,
            project_root,
            reviewer,
            checkpoint_root,
            probe_question_id=probe_question_id,
            sleep_fn=sleep_fn,
            monotonic_fn=monotonic_fn,
            shard_wall_seconds=shard_wall_seconds,
        )
    monotonic = monotonic_fn or time.monotonic
    wall_deadline = float(
        shard_wall_seconds
        if shard_wall_seconds is not None
        else model_router.answer_contract_review_route().timeout_seconds
    )
    plan = build_review_plan(conn, project_root)
    considered = 0
    reused = 0
    processed = 0
    model_calls = 0
    attempt_count = 0
    scopes = set()
    reviewed_checkpoints = []
    for node in plan["nodes"]:
        for shard in node["shards"]:
            if max_shards is not None and considered >= max_shards:
                break
            considered += 1
            path = _checkpoint_path(
                checkpoint_root,
                plan["bank_version"],
                node["node_id"],
                shard["shard_index"],
            )
            checkpoint = _load_valid_checkpoint(conn, path, plan, node, shard)
            if checkpoint is not None:
                reused += 1
                scopes.add(checkpoint["evidence_scope"])
                reviewed_checkpoints.append(checkpoint)
                continue
            packet = _packet(plan, node, shard)
            failure_path = _failure_checkpoint_path(
                checkpoint_root,
                plan["bank_version"],
                node["node_id"],
                shard["shard_index"],
            )
            try:
                execution = _execute_review_packet(
                    conn,
                    plan,
                    node,
                    shard,
                    packet,
                    reviewer,
                    failure_path,
                    probe_only=False,
                    sleep_fn=sleep_fn,
                    monotonic_fn=monotonic,
                    wall_deadline_seconds=wall_deadline,
                )
            except ReviewRunError as exc:
                failed_model_calls = int(exc.report.get("model_calls") or 0)
                failed_attempt_count = int(exc.report.get("attempt_count") or 0)
                exc.report.update(
                    {
                        "considered_shards": considered,
                        "processed_shards": processed,
                        "reused_shards": reused,
                        "model_calls": model_calls + failed_model_calls,
                        "attempt_count": attempt_count + failed_attempt_count,
                    }
                )
                raise
            checkpoint = _checkpoint_payload(
                plan,
                node,
                shard,
                execution["envelope"],
                execution["validated"],
                execution["shard_receipt"],
                attempt_count=execution["attempt_count"],
                attempts=execution["attempts"],
                model_calls=execution["model_calls"],
                wall_time_seconds=execution["wall_time_seconds"],
                wall_deadline_seconds=wall_deadline,
                evidence_scope=execution["evidence_scope"],
                agent_run_id=execution["agent_run_id"],
                review_state=execution["review_state"],
            )
            _atomic_write_json(path, checkpoint)
            reviewed_checkpoints.append(checkpoint)
            processed += 1
            model_calls += execution["model_calls"]
            attempt_count += execution["attempt_count"]
            scopes.add(execution["evidence_scope"])
        _write_node_receipt(conn, plan, node, checkpoint_root)
        if max_shards is not None and considered >= max_shards:
            break
    evidence_scope = scopes.pop() if len(scopes) == 1 else ("mixed" if scopes else "none")
    has_checkpoints = bool(reviewed_checkpoints)
    transport_pass = has_checkpoints and all(
        checkpoint["transport_pass"] for checkpoint in reviewed_checkpoints
    )
    semantic_response_valid = has_checkpoints and all(
        checkpoint["semantic_response_valid"] for checkpoint in reviewed_checkpoints
    )
    semantic_approval = has_checkpoints and all(
        checkpoint["semantic_approval"] for checkpoint in reviewed_checkpoints
    )
    activation_eligible = has_checkpoints and all(
        checkpoint["activation_eligible"] for checkpoint in reviewed_checkpoints
    )
    repair_issues = [
        deepcopy(issue)
        for checkpoint in reviewed_checkpoints
        for issue in checkpoint["repair_issues"]
    ]
    return {
        "bank_version": plan["bank_version"],
        "considered_shards": considered,
        "processed_shards": processed,
        "reused_shards": reused,
        "evidence_scope": evidence_scope,
        "transport_pass": transport_pass,
        "semantic_response_valid": semantic_response_valid,
        "semantic_approval": semantic_approval,
        "activation_eligible": activation_eligible,
        "live_semantic_pass": activation_eligible,
        "repair_issues": repair_issues,
        "repair_routes": [
            deepcopy(issue["repair_route"]) for issue in repair_issues
        ],
        "attempt_count": attempt_count,
        "model_calls": model_calls,
        "wall_deadline_seconds": wall_deadline,
    }


def run_live_probe(
    conn: sqlite3.Connection,
    project_root: Path,
    reviewer: Callable[[dict[str, Any]], dict[str, Any]],
    checkpoint_root: Path,
    *,
    probe_items: int = 1,
    probe_question_id: str | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] | None = None,
    shard_wall_seconds: float | None = None,
) -> dict[str, Any]:
    if isinstance(probe_items, bool) or not isinstance(probe_items, int):
        raise TypeError("probe_items must be an integer")
    if not 1 <= probe_items <= answer_contract_review.SHARD_SIZE:
        raise ValueError("probe_items must be between one and five")
    if not callable(reviewer):
        raise TypeError("reviewer must be callable")

    monotonic = monotonic_fn or time.monotonic
    wall_deadline = float(
        shard_wall_seconds
        if shard_wall_seconds is not None
        else model_router.answer_contract_review_route().timeout_seconds
    )
    if probe_question_id is not None:
        plan = build_probe_review_plan(conn, project_root, probe_question_id)
        node = plan["nodes"][0]
        canonical_shard = node["shards"][0]
        selected_items = deepcopy(canonical_shard["items"])
        probe_items = 1
    else:
        plan = build_review_plan(conn, project_root)
        node = plan["nodes"][0]
        canonical_shard = node["shards"][0]
        selected_items = deepcopy(canonical_shard["items"][:probe_items])
    probe_shard = {
        "node_id": canonical_shard["node_id"],
        "shard_index": canonical_shard["shard_index"],
        "items": selected_items,
    }
    probe_shard["shard_digest_sha256"] = answer_contract_review.shard_digest(
        probe_shard["items"]
    )
    packet = _packet(plan, node, probe_shard)
    accepted_path = (
        _probe_question_checkpoint_path(
            checkpoint_root,
            plan["bank_version"],
            node["node_id"],
            probe_question_id,
        )
        if probe_question_id is not None
        else _probe_checkpoint_path(
            checkpoint_root,
            plan["bank_version"],
            node["node_id"],
            probe_items,
        )
    )
    failure_path = accepted_path.with_suffix(".failure.json")

    prior = _load_valid_probe_checkpoint(
        conn, accepted_path, plan, node, probe_shard
    )
    if prior is not None:
        return {
            "status": "accepted",
            "bank_version": plan["bank_version"],
            "probe_only": True,
            "probe_items": probe_items,
            "probe_question_id": probe_shard["items"][0]["question_id"],
            "probe_item_count": probe_items,
            "planned_shard_item_count": len(canonical_shard["items"]),
            "question_ids": deepcopy(prior["question_ids"]),
            "transport_pass": prior["transport_pass"],
            "semantic_response_valid": prior["semantic_response_valid"],
            "semantic_approval": prior["semantic_approval"],
            "live_semantic_pass": False,
            "activation_eligible": False,
            "repair_issues": deepcopy(prior["repair_issues"]),
            "repair_routes": deepcopy(prior["repair_routes"]),
            "attempt_count": 0,
            "model_calls": 0,
            "reused_probe_receipt": True,
            "agent_run_id": prior["agent_run_id"],
            "probe_receipt_path": str(accepted_path),
        }

    execution = _execute_review_packet(
        conn,
        plan,
        node,
        probe_shard,
        packet,
        reviewer,
        failure_path,
        probe_only=True,
        sleep_fn=sleep_fn,
        monotonic_fn=monotonic,
        wall_deadline_seconds=wall_deadline,
    )
    receipt = _probe_checkpoint_payload(
        plan,
        node,
        probe_shard,
        execution,
        wall_deadline_seconds=wall_deadline,
    )
    _atomic_write_json(accepted_path, receipt)
    return {
        "status": "accepted",
        "bank_version": plan["bank_version"],
        "probe_only": True,
        "probe_items": probe_items,
        "probe_question_id": probe_shard["items"][0]["question_id"],
        "probe_item_count": probe_items,
        "planned_shard_item_count": len(canonical_shard["items"]),
        "question_ids": receipt["question_ids"],
        "transport_pass": receipt["transport_pass"],
        "semantic_response_valid": receipt["semantic_response_valid"],
        "semantic_approval": receipt["semantic_approval"],
        "live_semantic_pass": False,
        "activation_eligible": False,
        "repair_issues": deepcopy(receipt["repair_issues"]),
        "repair_routes": deepcopy(receipt["repair_routes"]),
        "attempt_count": execution["attempt_count"],
        "model_calls": execution["model_calls"],
        "wall_time_seconds": execution["wall_time_seconds"],
        "wall_deadline_seconds": wall_deadline,
        "transport_endpoint": receipt["transport_endpoint"],
        "structured_json_mode": receipt["structured_json_mode"],
        "reused_probe_receipt": False,
        "agent_run_id": receipt["agent_run_id"],
        "probe_receipt_path": str(accepted_path),
    }


def _plan_authority(
    conn: sqlite3.Connection, candidate_plan: Any
) -> tuple[bool, dict[str, Any] | None]:
    try:
        rebuilt = build_review_plan(conn, internal_agents.PROJECT_ROOT)
    except (sqlite3.Error, TypeError, ValueError, KeyError, OSError):
        return False, None
    if not isinstance(candidate_plan, dict):
        return False, rebuilt
    claimed_digest = candidate_plan.get("plan_digest_sha256")
    candidate_body = {
        key: value
        for key, value in candidate_plan.items()
        if key != "plan_digest_sha256"
    }
    if claimed_digest != _canonical_digest(candidate_body):
        return False, rebuilt
    if candidate_plan != rebuilt:
        return False, rebuilt
    return True, rebuilt


def audit_review(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    checkpoint_root: Path,
) -> dict[str, Any]:
    authority_ok, rebuilt = _plan_authority(conn, plan)
    authority_plan = rebuilt if rebuilt is not None else plan
    planned_ids = {
        item["question_id"]
        for node in authority_plan.get("nodes", [])
        for item in node.get("items", [])
        if isinstance(item, dict) and "question_id" in item
    } if isinstance(authority_plan, dict) else set()
    known = sorted(KNOWN_MISBOUND_IDS.intersection(planned_ids))
    if not authority_ok:
        blockers = ["plan_authority_mismatch"]
        if known:
            blockers.append("known_misbound_oracle")
        return {
            "bank_version": plan.get("bank_version", "") if isinstance(plan, dict) else "",
            "activation_ready": False,
            "activation_blockers": blockers,
            "missing_shards": [],
            "rejected_question_ids": [],
            "non_live_shards": [],
            "known_misbound_oracles": known,
        }

    missing = []
    rejected = []
    non_live = []
    for node in plan["nodes"]:
        for shard in node["shards"]:
            path = _checkpoint_path(
                checkpoint_root,
                plan["bank_version"],
                node["node_id"],
                shard["shard_index"],
            )
            checkpoint = _load_valid_checkpoint(conn, path, plan, node, shard)
            label = f"{node['node_id']}/shard-{shard['shard_index']}"
            if checkpoint is None:
                missing.append(label)
                continue
            rejected.extend(
                item["question_id"]
                for item in checkpoint["validated_items"]
                if item["review_status"] != "approved"
            )
            if not checkpoint["activation_eligible"]:
                non_live.append(label)
    blockers = []
    if missing:
        blockers.append("missing_shards")
    if rejected:
        blockers.append("rejected_items")
    if non_live:
        blockers.append("non_live_semantic_evidence")
    if int(plan.get("injected_test_draft_count") or 0) > 0:
        blockers.append("generated_design_receipts_required")
    if known:
        blockers.append("known_misbound_oracle")
    return {
        "bank_version": plan["bank_version"],
        "activation_ready": not blockers,
        "activation_blockers": blockers,
        "missing_shards": missing,
        "rejected_question_ids": sorted(set(rejected)),
        "non_live_shards": non_live,
        "known_misbound_oracles": known,
    }


def activate_reviewed_contracts(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    checkpoint_root: Path,
) -> dict[str, Any]:
    audit = audit_review(conn, plan, checkpoint_root)
    if not audit["activation_ready"]:
        raise ValueError(
            "answer-contract activation is blocked: "
            + ",".join(audit["activation_blockers"])
        )
    raise ValueError("activation write path is intentionally not implemented in this slice")


def v2_contract_activation_readiness(
    conn: sqlite3.Connection, contract_id: str
) -> dict[str, Any]:
    from . import answer_contract_generation_v2

    if not isinstance(contract_id, str) or not contract_id:
        raise ValueError("contract_id must be a nonempty string")
    row = conn.execute(
        "select * from answer_contracts where id = ?", (contract_id,)
    ).fetchone()
    if not row:
        raise ValueError("answer contract does not exist")
    blockers = []
    blockers.extend(
        answer_contract_generation_v2.v2_scoring_policy_activation_blockers(row)
    )
    if not answer_contract_generation_v2.contract_row_is_v2_activation_eligible(
        conn, row
    ):
        blockers.append("v2_contract_and_review_receipts_required")
    design_receipt = db.json_load(row["design_receipt_json"], {})
    review_receipt = db.json_load(row["review_receipt_json"], {})
    if not _valid_receipt_digest(design_receipt):
        blockers.append("v2_design_receipt_invalid")
    if not _valid_receipt_digest(review_receipt):
        blockers.append("v2_review_receipt_invalid")
    expected_runs = (
        (
            row["generator_run_id"],
            "answer_contract_designer_agent",
            "answer_contract_design_v2",
        ),
        (
            row["review_run_id"],
            "answer_contract_reviewer_agent",
            "answer_contract_review_v2",
        ),
    )
    for run_id, agent_key, phase in expected_runs:
        run = (
            conn.execute("select * from agent_runs where id = ?", (run_id,)).fetchone()
            if run_id
            else None
        )
        if not run or any(
            (
                run["agent_key"] != agent_key,
                run["phase"] != phase,
                run["status"] != "accepted",
                run["model_provider"] != "openai",
                run["model_name"] != MODEL_ALIAS,
                run["model_alias"] != MODEL_ALIAS,
            )
        ):
            blockers.append(f"{agent_key}_exact_live_run_required")
    return {
        "contract_id": contract_id,
        "contract_version": int(row["contract_version"]),
        "activation_eligible": not blockers,
        "activation_ready": not blockers,
        "blockers": blockers,
    }
