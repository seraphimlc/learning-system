from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import agents, auto_review, daily_runtime, db, evolution, internal_agents, job_queue, knowledge_cards, knowledge_map, model_router, orchestrator, planner, question_bank


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app/local_learning_system"
ANSWER_UPLOAD_ROOT = PROJECT_ROOT / "data/uploads/answers"
ANSWER_UPLOAD_RELATIVE_PREFIX = "data/uploads/answers"
MAX_ANSWER_PHOTO_BYTES = 8 * 1024 * 1024
MAX_JSON_BODY_BYTES = 12 * 1024 * 1024
ALLOWED_ANSWER_PHOTO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
CHILD_SESSION_HANDLE = "current-learning-group"
CHILD_SCHEMA_VERSION = "2.0.0-child-skeleton"
V3_CHILD_SCHEMA_VERSION = daily_runtime.V3_CHILD_SCHEMA_VERSION
OPERATOR_SCHEMA_VERSION = "1.4.0"
CHILD_UI_STATES = (
    "loading",
    "empty",
    "active_task",
    "saving",
    "save_error",
    "upload_error",
    "all_submitted_reviewing",
    "review_ready",
    "blocked",
    "load_error",
)
CHILD_DTO_FORBIDDEN_KEYS = {
    "node_id",
    "node_name",
    "graph",
    "question_id",
    "attempt_id",
    "session_id",
    "plan_id",
    "plan_key",
    "model",
    "provider",
    "agent",
    "rubric",
    "ocr_confidence",
    "queue",
    "job_id",
    "planner_blocked",
    "quality_gates",
    "task_count",
    "policy",
    "planner_policy_version",
    "planning_signal_refs",
}


class ChildAPIProjection:
    """v2 child-safe projection shell; route handlers delegate here."""

    schema_version = CHILD_SCHEMA_VERSION
    session_handle = CHILD_SESSION_HANDLE
    forbidden_keys = CHILD_DTO_FORBIDDEN_KEYS

    @staticmethod
    def bootstrap(conn: sqlite3.Connection) -> dict[str, Any]:
        return _child_bootstrap(conn)

    @staticmethod
    def completion(result: dict[str, Any]) -> dict[str, Any]:
        return _child_close_projection(result)

    @staticmethod
    def submission(*, grading_status: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
        return _child_submission_projection(grading_status=grading_status, attachments=attachments)


class OperatorAPIProjection:
    """v2 operator/Codex projection shell; ids and audit evidence stay here only."""

    schema_version = OPERATOR_SCHEMA_VERSION

    @staticmethod
    def bootstrap(conn: sqlite3.Connection) -> dict[str, Any]:
        return _bootstrap(conn)


class V3ChildAPIProjection:
    """v3 child-safe projection shell; enabled only by V3_DAILY_RUNTIME_ENABLED."""

    schema_version = V3_CHILD_SCHEMA_VERSION

    @staticmethod
    def bootstrap(conn: sqlite3.Connection) -> dict[str, Any]:
        payload = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT).load_or_create_daily_flow()
        return daily_runtime.canonicalize_v5_child_payload(payload)


class BackgroundReviewWorker:
    """Durable async review seam; current runtime stays in-process and DB-backed."""

    job_type = "answer_review"
    active_states = tuple(db.ACTIVE_BACKGROUND_JOB_STATUSES)
    terminal_states = tuple(sorted(db.BACKGROUND_JOB_STATUSES - db.ACTIVE_BACKGROUND_JOB_STATUSES))

    @staticmethod
    def idempotency_key(*, session_id: str, attempt_id: str | None = None) -> str:
        return f"{BackgroundReviewWorker.job_type}:{session_id}:{attempt_id or ''}"


def _child_safe_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()[:limit]
    replacements = {
        "模型": "关系",
        "图谱": "学习安排",
        "节点": "这一块",
        "Agent": "",
        "agent": "",
        "Codex": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _parse_env_file_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_local_env_file(path: Path | None = None) -> list[str]:
    """Load gitignored local runtime config for direct server starts."""
    env_path = path or PROJECT_ROOT / ".env.local"
    if not env_path.is_file():
        return []
    loaded: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if key in os.environ:
            continue
        os.environ[key] = _parse_env_file_value(raw_value)
        loaded.append(key)
    return loaded


def _startup_ai_status_lines() -> list[str]:
    routes = [
        ("answer review", model_router.answer_analysis_route()),
        ("question design", model_router.question_designer_route()),
        ("answer photo OCR", model_router.answer_photo_vision_route()),
    ]
    lines = []
    for label, route in routes:
        if route.enabled:
            lines.append(f"AI {label}: enabled model={route.model} provider={route.provider} base_url={route.base_url}")
        else:
            lines.append(f"AI {label}: disabled; missing API key")
    return lines


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _attachment_url(attachment: dict) -> dict:
    return {**attachment, "url": f"/api/attachments/{attachment['id']}"}


def _parse_answer_photo_data_url(data_url: str) -> tuple[str, bytes]:
    if not isinstance(data_url, str):
        raise ValueError("Invalid answer photo data URL")
    match = re.fullmatch(r"data:([^;,]+);base64,(.*)", data_url, flags=re.DOTALL)
    if not match:
        raise ValueError("Invalid answer photo data URL")

    content_type = match.group(1).lower()
    if content_type not in ALLOWED_ANSWER_PHOTO_TYPES:
        raise ValueError("Unsupported answer photo content type")

    encoded = match.group(2)
    max_encoded_size = ((MAX_ANSWER_PHOTO_BYTES + 2) // 3) * 4 + 1024
    if len(encoded) > max_encoded_size:
        raise ValueError("Answer photo exceeds 8 MB limit")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid answer photo data URL") from exc

    if not data:
        raise ValueError("Answer photo is empty")
    if len(data) > MAX_ANSWER_PHOTO_BYTES:
        raise ValueError("Answer photo exceeds 8 MB limit")
    if not _looks_like_allowed_image(content_type, data):
        raise ValueError("Invalid answer photo image data")
    return content_type, data


def _looks_like_allowed_image(content_type: str, data: bytes) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def _safe_answer_photo_filename(original_name: str | None, content_type: str, attempt_id: str) -> str:
    name = (original_name or "answer").replace("\\", "/")
    stem = Path(name).name
    stem = Path(stem).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    if not stem:
        stem = "answer"
    stem = stem[:80]
    extension = ALLOWED_ANSWER_PHOTO_TYPES[content_type]
    return f"{attempt_id}-{uuid.uuid4().hex[:8]}-{stem}{extension}"


def _error_tags_for_payload(payload: dict, result: str) -> list[str]:
    if "error_tags" in payload:
        tags = payload.get("error_tags") or []
    else:
        tags = [] if result == "correct" else ["general"]
    return tags


def _answer_analysis_from_payload(payload: dict) -> dict | None:
    if "answer_analysis" in payload:
        analysis = payload.get("answer_analysis")
    elif "analysis" in payload:
        analysis = payload.get("analysis")
    else:
        return None
    if analysis in (None, ""):
        return None
    if not isinstance(analysis, dict):
        raise ValueError("answer_analysis must be an object")
    db.validate_answer_analysis(analysis)
    return analysis


def _agent_contract_metadata(agent_key: str) -> dict:
    role = internal_agents.INTERNAL_AGENT_ROLES[agent_key]
    contract = internal_agents.load_contract(role["contract_key"])
    prompt_path = internal_agents.prompt_path_for_contract(contract)
    return {
        "prompt_version_id": contract.get("prompt_version_id", ""),
        "prompt_template_sha256": internal_agents.file_sha256(prompt_path) if prompt_path.exists() else "",
        "response_schema_version": contract.get("response_schema_version", ""),
        "response_schema_sha256": db._digest_json(contract),
    }


def _review_to_attempt_grade(review: dict) -> dict | None:
    if review.get("needs_ai_review", review.get("needs_codex_review")):
        return None
    return {
        "result": review["result"],
        "score_points": float(review["score_points"]),
        "max_points": float(review.get("max_points", 2)),
        "error_tags": review["error_tags"],
        "parent_note": review["parent_note"],
        "answer_analysis": review.get("analysis"),
        "review_meta": review.get("ai_review"),
        "explanation_score": review["explanation_score"],
        "blocking_evidence": bool(review["blocking_evidence"]),
    }


def _model_audit_from_review(review: dict) -> dict[str, Any]:
    ai_review = review.get("ai_review") if isinstance(review.get("ai_review"), dict) else {}
    return {
        "model_provider": str(ai_review.get("provider") or ""),
        "model_name": str(ai_review.get("model") or ""),
        "model_alias": str(ai_review.get("model_alias") or ""),
        "model_params": {},
    }


def _review_engine_type(review: dict) -> str:
    return "model" if _model_audit_from_review(review)["model_name"] else "hybrid"


def _background_review_concurrency() -> int:
    try:
        value = int(os.environ.get("AI_BACKGROUND_REVIEW_CONCURRENCY", "4"))
    except ValueError:
        value = 4
    return max(1, min(value, 8))


def _review_audit_output(
    review: dict,
    *,
    grading_status: str,
    result: str | None = None,
    score_points: float | None = None,
) -> dict:
    ai_review = review.get("ai_review") if isinstance(review.get("ai_review"), dict) else {}
    output = {
        "grading_status": grading_status,
        "needs_ai_review": bool(review.get("needs_ai_review", review.get("needs_codex_review"))),
        "ai_review_status": ai_review.get("status", ""),
    }
    if result is not None:
        output["result"] = result
    if score_points is not None:
        output["score_points"] = score_points
    vision = ai_review.get("vision")
    if isinstance(vision, dict):
        output["vision"] = {
            "status": vision.get("status", ""),
            "confidence": float(vision.get("confidence") or 0.0),
            "provider": vision.get("provider", ""),
            "model": vision.get("model", ""),
            "model_alias": vision.get("model_alias", ""),
            "has_transcript": bool(vision.get("has_transcript")),
            "transcript_preview": str(vision.get("transcript") or "")[:240],
            "math_object_count": len(vision.get("math_objects", [])) if isinstance(vision.get("math_objects"), list) else 0,
        }
    return output


def _child_close_projection(result: dict) -> dict:
    session = result.get("session") if isinstance(result.get("session"), dict) else {}
    message = result.get("child_message") or {
        "pending_message": "答案已经保存。系统会继续看你的步骤和思路，然后安排下一步。",
        "child_action": "可以先休息。",
    }
    if (
        result.get("closure_status") == "planned"
        and isinstance(message, dict)
        and not message.get("review_points")
    ):
        review_points = _review_points_from_answer_package(result)
        if review_points:
            message = {**message, "review_points": review_points}
    if result.get("closure_status") == "waiting_ai":
        message = {
            "pending_message": "答案已经保存。通常半分钟到一分半完成批阅；超过两分钟会自动重试。",
            "child_action": "可以先休息，不用守着页面。",
        }
    elif result.get("closure_status") == "blocked":
        blocked_reason = result.get("blocked_reason") or result.get("closure_result", {}).get("blocked_reason", "")
        if blocked_reason == "ai_review_unavailable":
            message = {
                "pending_message": "答案已经保存，但现在暂时没有连上，不能继续看结果。系统恢复后会继续处理这组答案。",
                "child_action": "可以先休息，不用自己反复刷新。",
            }
        else:
            message = {
                "pending_message": "答案已经保存。现在暂时不能继续看结果。",
                "child_action": "可以先休息，稍后回来会继续。",
            }
    internal_agents.validate_child_safe_message(message)
    safe = {
        "session": {
            "handle": CHILD_SESSION_HANDLE,
            "state": _child_session_state(session.get("status"), result.get("closure_status")),
        },
        "closure_status": result.get("closure_status"),
        "child_message": message,
    }
    return safe


def _review_points_from_answer_package(result: dict) -> list[dict[str, str]]:
    answer_package = result.get("answer_analysis") if isinstance(result.get("answer_analysis"), dict) else {}
    attempts = answer_package.get("attempts") if isinstance(answer_package.get("attempts"), list) else []
    labels = {
        "correct": "基本通过",
        "partial": "还差一步",
        "wrong": "需要重做",
    }
    points = []
    for position, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict):
            continue
        label = labels.get(str(attempt.get("result") or ""), "已保存")
        gap = (
            attempt.get("process_gap")
            or attempt.get("child_answer_summary")
            or "这题还需要把关键步骤和理由写清楚。"
        )
        prompt = attempt.get("next_child_prompt")
        text = _child_safe_text(gap, 180)
        if prompt:
            text = f"{text} 下一次先写：{_child_safe_text(prompt, 150)}"
        points.append({
            "title": _child_safe_text(f"第{position}题：{label}", 80),
            "text": _child_safe_text(text, 340),
        })
    return points


def _bootstrap(conn: sqlite3.Connection) -> dict:
    readiness = db.readiness(conn)
    planner_blocked = None
    try:
        today_plan = planner.latest_or_create_plan(conn)
    except planner.PlannerPlanError as exc:
        today_plan = None
        planner_blocked = {
            "blocked_reason": "planner_quality_gate_failed",
            "message": str(exc),
            "quality_gates": exc.quality_gates,
            "task_count": exc.task_count,
        }
    weak_nodes = []
    for status_row in db.current_learner_node_status_rows(conn)[:12]:
        node = db.get_graph_node(conn, status_row["node_id"])
        weak_nodes.append({
            **status_row,
            "name": node.get("name", ""),
            "stage": node.get("stage", ""),
            "domain": node.get("domain", ""),
        })
    question_coverage = [
        dict(row) for row in conn.execute(
            """
            select n.id as node_id, n.name, n.stage, n.priority,
                   sum(case when q.source_type = 'graph_generated' then 1 else 0 end) as practice_count,
                   sum(case when q.source_type = 'graph_generated' and q.item_version = ? then 1 else 0 end) as current_practice_count,
                   sum(case when q.source_type = 'diagnostic' then 1 else 0 end) as diagnostic_count,
                   sum(case when q.source_type = 'evolved' then 1 else 0 end) as evolved_count
            from graph_nodes n
            left join question_items q on q.node_id = n.id
            group by n.id
            order by n.sequence_band, n.id
            """,
            (question_bank.QUESTION_BANK_VERSION,),
        ).fetchall()
    ]
    profiles = [
        dict(row) for row in conn.execute(
            "select agent_key, display_name, revision, profile_json, updated_at from agent_profiles order by agent_key"
        ).fetchall()
    ]
    pending_attempts = db.pending_attempts(conn)
    for attempt in pending_attempts:
        attempt["attachments"] = [_attachment_url(attachment) for attachment in attempt["attachments"]]
    recent_attempts = db.recent_attempts(conn, 20)
    for attempt in recent_attempts:
        attempt["attachments"] = [_attachment_url(attachment) for attachment in attempt["attachments"]]
    return {
        "schema_version": OPERATOR_SCHEMA_VERSION,
        "readiness": readiness,
        "today_plan": today_plan,
        "planner_blocked": planner_blocked,
        "pending_attempts": pending_attempts,
        "recent_attempts": recent_attempts,
        "weak_nodes": weak_nodes,
        "question_coverage": question_coverage,
        "agent_profiles": profiles,
        "agent_reports": agents.build_agent_reports(conn),
        "evolution_events": evolution.recent_events(conn),
    }


def _child_question(question: dict) -> dict:
    return {
        "prompt": question.get("prompt", ""),
        "answer_format": question.get("answer_format", "关键步骤 + 答案"),
    }


def _child_task(task: dict, position: int) -> dict:
    return planner.PlanTaskDTO.child_safe(
        task,
        position=position,
        kind_label=_child_task_type_label(task.get("task_type")),
    )


def _child_plan(plan: dict) -> dict:
    return {
        "title": plan.get("title"),
        "display_key": _child_plan_key(plan),
        "tasks": [_child_task(task, index + 1) for index, task in enumerate(plan.get("tasks", []))],
        "created_at": plan.get("created_at"),
    }


def _child_task_type_label(task_type: str | None) -> str:
    return {
        "learn": "新知识",
        "remediate": "再稳一下",
        "rollback": "先补一步",
        "prerequisite_probe": "准备一下",
        "retest": "小检查",
        "practice": "练习",
        "diagnostic": "小检测",
    }.get(task_type or "", "学习")


def _child_session_state(status: str | None, closure_status: str | None = None) -> str:
    if status == "closed" and closure_status == "planned":
        return "ready_for_next"
    if closure_status == "waiting_ai":
        return "reviewing"
    if closure_status == "blocked":
        return "needs_system_recovery"
    if status == "closed":
        return "finished"
    return "active"


def _child_plan_key(plan: dict) -> str:
    created_at = str(plan.get("created_at") or "")
    title = str(plan.get("title") or "plan")
    source = f"{title}|{created_at}|{len(plan.get('tasks', []))}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _plan_from_generated_row(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    plan = {
        "id": row["id"],
        "title": row["title"],
        "plan_policy_version": row["planner_policy_version"],
        "planner_policy_version": row["planner_policy_version"],
        "tasks": db.json_load(row["tasks_json"], []),
        "created_at": row["created_at"],
    }
    meta = db.json_load(row["plan_meta_json"], {})
    if isinstance(meta, dict):
        plan["round_size"] = meta.get("round_size", len(plan.get("tasks", [])))
        plan["primary_target_node_id"] = meta.get("primary_target_node_id", "")
        plan["round_structure"] = meta.get("round_structure") or planner.round_structure(plan.get("tasks", []))
        plan["planning_signal_refs"] = meta.get("planning_signal_refs") or planner.planning_signal_refs(plan.get("tasks", []))
        plan["quality_gates"] = meta.get("quality_gates") or planner.quality_gates(conn, plan.get("tasks", []))
        plan["confidence"] = float(meta.get("confidence", 1.0) or 1.0)
    if row["planner_policy_version"] != planner.PLANNER_POLICY_VERSION:
        return None
    if not planner.plan_uses_current_active_bank(conn, plan):
        return None
    return plan


def _generated_plan_by_id(conn: sqlite3.Connection, plan_id: str | None) -> dict | None:
    if not plan_id:
        return None
    row = conn.execute(
        """
        select id, title, tasks_json, planner_policy_version, plan_meta_json, created_at
        from generated_plans
        where id = ?
        """,
        (plan_id,),
    ).fetchone()
    return _plan_from_generated_row(conn, row)


def _latest_generated_plan_row(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        """
        select id, title, tasks_json, planner_policy_version, plan_meta_json, created_at
        from generated_plans
        order by created_at desc, rowid desc
        limit 1
        """
    ).fetchone()
    return _plan_from_generated_row(conn, row)


def _child_session_has_active_attempts(conn: sqlite3.Connection, session_id: str) -> bool:
    return bool(conn.execute(
        """
        select 1
        from attempts
        where session_id = ?
          and evidence_status = 'active'
        limit 1
        """,
        (session_id,),
    ).fetchone())


def _current_child_plan_context(conn: sqlite3.Connection) -> tuple[dict, dict | None]:
    """Freeze child-visible tasks to the open learning session, if one exists."""
    commit_discovered_recovery = not conn.in_transaction
    db.retire_stale_child_learning_sessions(conn, commit=commit_discovered_recovery)
    latest_plan = _latest_generated_plan_row(conn)
    open_contexts: list[tuple[dict, dict]] = []
    for open_session in _open_child_sessions(conn):
        session_plan = _generated_plan_by_id(conn, open_session.get("plan_id"))
        if not session_plan:
            if open_session.get("plan_id"):
                closure_result = {
                    "closure_status": "blocked",
                    "blocked_reason": "stale_planning_evidence_session_retired",
                    "plan_id": open_session.get("plan_id"),
                    "current_planner_policy_version": planner.PLANNER_POLICY_VERSION,
                }
                db.update_session_closure_state(
                    conn,
                    session_id=open_session["id"],
                    status="closed",
                    closure_status="blocked",
                    closure_result=closure_result,
                    closed_at=db.now_iso(),
                    commit=commit_discovered_recovery,
                )
            continue
        open_contexts.append((session_plan, open_session))

    for session_plan, open_session in open_contexts:
        if _child_session_has_active_attempts(conn, open_session["id"]) or open_session.get("status") == "closing":
            return session_plan, open_session

    for session_plan, open_session in open_contexts:
        if not latest_plan or latest_plan.get("id") == session_plan.get("id"):
            return session_plan, open_session
    plan = planner.latest_or_create_plan(conn)
    return plan, _latest_child_session_for_plan(conn, plan.get("id"))


def _question_positions(plan: dict) -> dict[str, int]:
    return {
        task.get("question_id"): index + 1
        for index, task in enumerate(plan.get("tasks", []))
        if task.get("question_id")
    }


def _latest_child_session_for_plan(conn: sqlite3.Connection, plan_id: str | None) -> dict | None:
    if not plan_id:
        return None
    rows = conn.execute(
        """
        select id
        from learning_sessions
        where mode = 'child_learning_group'
          and plan_id = ?
        order by created_at desc, id desc
        """,
        (plan_id,),
    ).fetchall()
    for row in rows:
        session = db.get_learning_session(conn, row["id"])
        if db.learning_session_questions_are_current(conn, session):
            return session
    return None


def _open_child_sessions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        select id
        from learning_sessions
        where mode = 'child_learning_group'
          and status != 'closed'
        order by created_at desc, id desc
        """
    ).fetchall()
    sessions: list[dict] = []
    for row in rows:
        session = db.get_learning_session(conn, row["id"])
        if db.learning_session_questions_are_current(conn, session):
            sessions.append(session)
    return sessions


def _latest_open_child_session(conn: sqlite3.Connection) -> dict | None:
    sessions = _open_child_sessions(conn)
    if sessions:
        return sessions[0]
    return None


def _latest_child_session(conn: sqlite3.Connection) -> dict | None:
    rows = conn.execute(
        """
        select id
        from learning_sessions
        where mode = 'child_learning_group'
        order by created_at desc, id desc
        """
    ).fetchall()
    for row in rows:
        session = db.get_learning_session(conn, row["id"])
        if db.learning_session_questions_are_current(conn, session):
            return session
    return None


def _latest_closed_child_session_for_next_plan(conn: sqlite3.Connection, plan_id: str | None) -> dict | None:
    if not plan_id:
        return None
    rows = conn.execute(
        """
        select id
        from learning_sessions
        where mode = 'child_learning_group'
          and status = 'closed'
          and closure_status = 'planned'
          and next_plan_id = ?
        order by closed_at desc, created_at desc, id desc
        """,
        (plan_id,),
    ).fetchall()
    for row in rows:
        session = db.get_learning_session(conn, row["id"])
        if db.learning_session_questions_are_current(conn, session):
            return session
    return None


def _child_group_projection(conn: sqlite3.Connection, session: dict | None, plan: dict) -> dict:
    if not session:
        return {
            "handle": CHILD_SESSION_HANDLE,
            "state": "not_started",
            "submitted_task_positions": [],
        }
    positions = _question_positions(plan)
    attempts = db.attempts_for_session(conn, session["id"])
    submitted_positions = sorted({
        positions[attempt["question_id"]]
        for attempt in attempts
        if attempt.get("question_id") in positions
    })
    return {
        "handle": CHILD_SESSION_HANDLE,
        "state": _child_session_state(session.get("status"), session.get("closure_status")),
        "submitted_task_positions": submitted_positions,
    }


def _child_submission_projection(*, grading_status: str, attachments: list[dict]) -> dict:
    return {
        "submission_state": "saved",
        "review_state": "reviewed" if grading_status == "graded" else "being_reviewed",
        "child_message": {
            "pending_message": "答案已经保存。系统会继续看你的步骤、照片和思路，然后安排下一步。",
            "child_action": "继续下一题；如果这一组做完了，可以休息。",
        },
        "attachments_saved": len(attachments),
    }


def _child_planner_recovery_projection() -> dict[str, Any]:
    child_message = {
        "pending_message": "系统正在整理下一组题目和学习记录。",
        "child_action": "可以先休息一下，稍后回来会继续。",
    }
    internal_agents.validate_child_safe_message(child_message)
    return {
        "schema_version": CHILD_SCHEMA_VERSION,
        "today_plan": {
            "title": "系统正在整理下一组",
            "display_key": "system-recovery",
            "tasks": [],
            "created_at": db.now_iso(),
        },
        "learning_group": {
            "handle": CHILD_SESSION_HANDLE,
            "state": "needs_system_recovery",
            "submitted_task_positions": [],
        },
        "completion": {
            "closure_status": "blocked",
            "child_message": child_message,
        },
    }


def _child_planner_recovery_error() -> dict[str, str]:
    return {"error": "系统正在整理下一组题目和学习记录，可以稍后再试。"}


def _is_child_public_post_path(path: str) -> bool:
    return (
        path == "/api/child-submissions"
        or path == "/api/learning-sessions"
        or (path.startswith("/api/learning-sessions/") and path.endswith("/complete"))
    )


def _child_bootstrap(conn: sqlite3.Connection) -> dict:
    today_plan, latest_session = _current_child_plan_context(conn)
    return {
        "schema_version": CHILD_SCHEMA_VERSION,
        "today_plan": _child_plan(today_plan),
        "learning_group": _child_group_projection(conn, latest_session, today_plan),
    }


class LearningHandler(BaseHTTPRequestHandler):
    db_path: Path
    answer_upload_root: Path
    background_lock = threading.Lock()
    background_sessions: set[str] = set()
    background_session_rerun: set[str] = set()
    v3_background_lock = threading.Lock()
    v3_background_flows: set[str] = set()
    v3_background_flow_rerun: set[str] = set()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _conn(self) -> sqlite3.Connection:
        return db.connect(self.db_path)

    def _send_json(self, payload: object, status: int = 200) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            raise ValueError("Request body too large")
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/bootstrap":
            with closing(self._conn()) as conn:
                self._send_json(OperatorAPIProjection.bootstrap(conn))
            return
        if parsed.path == "/api/child-bootstrap":
            payload = self._child_bootstrap_response()
            self._send_json(payload)
            return
        if parsed.path == "/api/knowledge-map":
            with closing(self._conn()) as conn:
                try:
                    payload = knowledge_map.KnowledgeMapService(
                        conn,
                        project_root=PROJECT_ROOT,
                    ).child_projection()
                except knowledge_map.KnowledgeMapError as exc:
                    self._send_json(exc.child_payload(), status=exc.status)
                    return
                self._send_json(payload)
            return
        if parsed.path == "/api/knowledge-cards/number-line":
            try:
                payload = knowledge_cards.KnowledgeCardService(
                    project_root=PROJECT_ROOT,
                ).child_projection_for_node("M-G7-NUMBER-LINE")
            except knowledge_cards.KnowledgeCardError:
                self._send_json({
                    "schema_version": "knowledge-card-child.v1",
                    "state": "unavailable",
                    "message": "这张学习卡还在准备中。",
                }, status=503)
                return
            self._send_json(payload)
            return
        if parsed.path == "/api/knowledge-cards/preview":
            query = parse_qs(parsed.query)
            node_id = str((query.get("node_id") or ["M-G7-NUMBER-LINE"])[0] or "M-G7-NUMBER-LINE")
            draft = str((query.get("draft") or [""])[0]).lower() in {"1", "true", "yes"}
            try:
                service = knowledge_cards.KnowledgeCardService(project_root=PROJECT_ROOT)
                payload = (
                    service.child_projection_for_v2_draft_node(node_id)
                    if draft
                    else service.child_projection_for_node(node_id)
                )
            except (FileNotFoundError, json.JSONDecodeError, knowledge_cards.KnowledgeCardError):
                self._send_json({
                    "schema_version": "knowledge-card-child-preview.v1",
                    "state": "unavailable",
                    "message": "这张学习卡还在准备中。",
                }, status=503)
                return
            self._send_json(payload)
            return
        if parsed.path == "/api/operator/daily-flow/today":
            with closing(self._conn()) as conn:
                self._send_json(self._v3_runtime(conn).operator_inspect_today())
            return
        if parsed.path == "/api/questions":
            with closing(self._conn()) as conn:
                rows = conn.execute(
                    "select * from question_items order by source_type, node_id, id limit 500"
                ).fetchall()
                self._send_json({"questions": [db.row_to_question(row) for row in rows]})
            return
        if parsed.path == "/api/evolution-events":
            with closing(self._conn()) as conn:
                self._send_json({"events": evolution.recent_events(conn, 50)})
            return
        if parsed.path == "/api/agent-reports":
            with closing(self._conn()) as conn:
                self._send_json({"agent_reports": agents.build_agent_reports(conn)})
            return
        if parsed.path.startswith("/api/attachments/"):
            self._serve_attachment(parsed.path)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/knowledge-map/select":
                payload = self._read_json()
                with closing(self._conn()) as conn:
                    try:
                        result = knowledge_map.KnowledgeMapService(
                            conn,
                            project_root=PROJECT_ROOT,
                        ).select_target(child_key="single-child", request=payload)
                    except knowledge_map.KnowledgeMapError as exc:
                        self._send_json(exc.child_payload(), status=exc.status)
                        return
                    self._send_json(result)
                return
            if parsed.path == "/api/daily-flow/review/start":
                payload = self._read_json()
                if not daily_runtime.v3_daily_runtime_enabled():
                    self._send_json(daily_runtime.disabled_child_payload(), status=409)
                    return
                with closing(self._conn()) as conn:
                    try:
                        result = self._v3_runtime(conn).start_review_mode(
                            client_day_key=payload.get("client_day_key"),
                        )
                    except daily_runtime.ChildSafeRuntimeError as exc:
                        self._send_json(exc.child_payload(), status=exc.status)
                        return
                    self._send_json(daily_runtime.canonicalize_v5_child_payload(result))
                    return
            if parsed.path == "/api/current-step/submit":
                payload = self._read_json()
                if not daily_runtime.v3_daily_runtime_enabled():
                    self._send_json(daily_runtime.disabled_child_payload(), status=409)
                    return
                flow_to_process = ""
                with closing(self._conn()) as conn:
                    try:
                        command = daily_runtime.CurrentStepSubmission.from_payload(payload)
                        result = self._v3_runtime(conn).persist_child_response(command)
                        row = conn.execute(
                            "select flow_id from flow_steps where step_handle = ? limit 1",
                            (command.step_handle,),
                        ).fetchone()
                        flow_to_process = row["flow_id"] if row else ""
                    except daily_runtime.ChildSafeRuntimeError as exc:
                        self._send_json(exc.child_payload(), status=exc.status)
                        return
                    if flow_to_process:
                        self._start_v3_flow_processing(flow_to_process)
                    self._send_json(daily_runtime.canonicalize_v5_child_payload(result))
                    return
            if parsed.path == "/api/current-step/continue":
                payload = self._read_json()
                if not daily_runtime.v3_daily_runtime_enabled():
                    self._send_json(daily_runtime.disabled_child_payload(), status=409)
                    return
                with closing(self._conn()) as conn:
                    try:
                        result = self._v3_runtime(conn).continue_current_step(
                            step_handle=str(payload.get("step_handle") or ""),
                            position=int(payload.get("position") or 0),
                            stuck=bool(payload.get("stuck", False)),
                        )
                    except daily_runtime.ChildSafeRuntimeError as exc:
                        self._send_json(exc.child_payload(), status=exc.status)
                        return
                    self._send_json(daily_runtime.canonicalize_v5_child_payload(result))
                    return
            if parsed.path == "/api/daily-flow/new-knowledge/start":
                payload = self._read_json()
                if not daily_runtime.v3_daily_runtime_enabled():
                    self._send_json(daily_runtime.disabled_child_payload(), status=409)
                    return
                with closing(self._conn()) as conn:
                    try:
                        result = self._v3_runtime(conn).start_new_knowledge_from_checkpoint(
                            client_day_key=payload.get("client_day_key"),
                        )
                    except daily_runtime.ChildSafeRuntimeError as exc:
                        self._send_json(exc.child_payload(), status=exc.status)
                        return
                    self._send_json(daily_runtime.canonicalize_v5_child_payload(result))
                    return
            if parsed.path == "/api/daily-flow/finish":
                payload = self._read_json()
                if not daily_runtime.v3_daily_runtime_enabled():
                    self._send_json(daily_runtime.disabled_child_payload(), status=409)
                    return
                with closing(self._conn()) as conn:
                    try:
                        result = self._v3_runtime(conn).finish_ready_checkpoint(
                            client_day_key=payload.get("client_day_key"),
                        )
                    except daily_runtime.ChildSafeRuntimeError as exc:
                        self._send_json(exc.child_payload(), status=exc.status)
                        return
                    self._send_json(daily_runtime.canonicalize_v5_child_payload(result))
                    return
            if parsed.path == "/api/child-submissions":
                payload = self._read_json()
                result = self._create_child_submission(payload, allow_raw_ids=False, async_review=True)
                self._send_json(result)
                return
            if parsed.path == "/api/operator/child-submissions":
                payload = self._read_json()
                result = self._create_child_submission(payload, allow_raw_ids=True, async_review=False)
                self._send_json(result)
                return
            if parsed.path == "/api/learning-sessions":
                payload = self._read_json()
                with closing(self._conn()) as conn:
                    plan = planner.latest_or_create_plan(conn)
                    with conn:
                        session = db.create_learning_session_for_plan(
                            conn,
                            plan,
                            title=payload.get("title") or plan.get("title") or "学习任务组",
                            commit=False,
                        )
                        db.record_agent_run(
                            conn,
                            agent_key="session_orchestrator_agent",
                            engine_type="deterministic",
                            session_id=session["id"],
                            phase="session_start",
                            trigger=f"learning_session_start:{session['id']}",
                            input_refs={
                                "plan_id": plan.get("id"),
                                "question_ids": session.get("expected_question_ids", []),
                            },
                            status="accepted",
                            confidence=1.0,
                            output={
                                "session_id": session["id"],
                                "expected_question_count": len(session.get("expected_question_ids", [])),
                            },
                            commit=False,
                            **_agent_contract_metadata("session_orchestrator_agent"),
                        )
                        db.record_agent_run(
                            conn,
                            agent_key="planner_agent",
                            engine_type="deterministic",
                            session_id=session["id"],
                            phase="plan_assignment",
                            trigger=f"learning_session_start:{session['id']}",
                            input_refs={
                                "plan_id": plan.get("id"),
                                "question_ids": session.get("expected_question_ids", []),
                            },
                            status="accepted",
                            confidence=1.0,
                            output={
                                "plan_id": plan.get("id"),
                                "plan_policy_version": plan.get("plan_policy_version", plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION)),
                                "planner_policy_version": plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION),
                                "task_count": len(plan.get("tasks", [])),
                                "round_size": plan.get("round_size", len(plan.get("tasks", []))),
                                "primary_target_node_id": plan.get("primary_target_node_id", ""),
                                "round_structure": plan.get("round_structure") or planner.round_structure(plan.get("tasks", [])),
                                "planning_signal_refs": plan.get("planning_signal_refs") or planner.planning_signal_refs(plan.get("tasks", [])),
                                "quality_gates": plan.get("quality_gates") or planner.quality_gates(conn, plan.get("tasks", [])),
                                "confidence": plan.get("confidence", 1.0),
                            },
                            commit=False,
                            **_agent_contract_metadata("planner_agent"),
                        )
                    self._send_json({
                        "session": {
                            "handle": CHILD_SESSION_HANDLE,
                            "state": "active",
                            "submitted_task_positions": [],
                        },
                        "plan": _child_plan(plan),
                    })
                return
            if parsed.path == "/api/operator/learning-sessions":
                payload = self._read_json()
                with closing(self._conn()) as conn:
                    plan = planner.latest_or_create_plan(conn)
                    with conn:
                        session = db.create_learning_session_for_plan(
                            conn,
                            plan,
                            title=payload.get("title") or plan.get("title") or "学习任务组",
                            commit=False,
                        )
                        db.record_agent_run(
                            conn,
                            agent_key="session_orchestrator_agent",
                            engine_type="deterministic",
                            session_id=session["id"],
                            phase="session_start",
                            trigger=f"learning_session_start:{session['id']}",
                            input_refs={
                                "plan_id": plan.get("id"),
                                "question_ids": session.get("expected_question_ids", []),
                            },
                            status="accepted",
                            confidence=1.0,
                            output={
                                "session_id": session["id"],
                                "expected_question_count": len(session.get("expected_question_ids", [])),
                            },
                            commit=False,
                            **_agent_contract_metadata("session_orchestrator_agent"),
                        )
                        db.record_agent_run(
                            conn,
                            agent_key="planner_agent",
                            engine_type="deterministic",
                            session_id=session["id"],
                            phase="plan_assignment",
                            trigger=f"learning_session_start:{session['id']}",
                            input_refs={
                                "plan_id": plan.get("id"),
                                "question_ids": session.get("expected_question_ids", []),
                            },
                            status="accepted",
                            confidence=1.0,
                            output={
                                "plan_id": plan.get("id"),
                                "plan_policy_version": plan.get("plan_policy_version", plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION)),
                                "planner_policy_version": plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION),
                                "task_count": len(plan.get("tasks", [])),
                                "round_size": plan.get("round_size", len(plan.get("tasks", []))),
                                "primary_target_node_id": plan.get("primary_target_node_id", ""),
                                "round_structure": plan.get("round_structure") or planner.round_structure(plan.get("tasks", [])),
                                "planning_signal_refs": plan.get("planning_signal_refs") or planner.planning_signal_refs(plan.get("tasks", [])),
                                "quality_gates": plan.get("quality_gates") or planner.quality_gates(conn, plan.get("tasks", [])),
                                "confidence": plan.get("confidence", 1.0),
                            },
                            commit=False,
                            **_agent_contract_metadata("planner_agent"),
                        )
                    self._send_json({"session": session, "plan": _child_plan(plan)})
                return
            if parsed.path.startswith("/api/operator/learning-sessions/") and parsed.path.endswith("/complete"):
                session_id = parsed.path.removeprefix("/api/operator/learning-sessions/").removesuffix("/complete").strip("/")
                if not session_id or "/" in session_id:
                    raise ValueError("Invalid learning session id")
                result = self._close_learning_session(session_id, child_safe=False)
                self._send_json(result)
                return
            if parsed.path.startswith("/api/learning-sessions/") and parsed.path.endswith("/complete"):
                session_id = parsed.path.removeprefix("/api/learning-sessions/").removesuffix("/complete").strip("/")
                if not session_id or "/" in session_id:
                    raise ValueError("Invalid learning session id")
                if session_id != CHILD_SESSION_HANDLE:
                    raise ValueError("Child learning completion must use the current learning group handle")
                session_id = self._current_child_session_id()
                result = self._close_learning_session(session_id, child_safe=True)
                self._send_json(result)
                return
            if parsed.path == "/api/attempts":
                payload = self._read_json()
                result = self._create_graded_attempt(payload)
                self._send_json(result)
                return
            if parsed.path.startswith("/api/attempts/") and parsed.path.endswith("/grade"):
                payload = self._read_json()
                attempt_id = parsed.path.removeprefix("/api/attempts/").removesuffix("/grade").strip("/")
                if not attempt_id or "/" in attempt_id:
                    raise ValueError("Invalid attempt id")
                result = self._grade_attempt(attempt_id, payload)
                self._send_json(result)
                return
            if parsed.path.startswith("/api/attempts/") and parsed.path.endswith("/analysis"):
                payload = self._read_json()
                attempt_id = parsed.path.removeprefix("/api/attempts/").removesuffix("/analysis").strip("/")
                if not attempt_id or "/" in attempt_id:
                    raise ValueError("Invalid attempt id")
                result = self._update_attempt_analysis(attempt_id, payload)
                self._send_json(result)
                return
            if parsed.path.startswith("/api/attempts/") and parsed.path.endswith("/invalidate"):
                payload = self._read_json()
                attempt_id = parsed.path.removeprefix("/api/attempts/").removesuffix("/invalidate").strip("/")
                if not attempt_id or "/" in attempt_id:
                    raise ValueError("Invalid attempt id")
                result = self._invalidate_attempt(attempt_id, payload)
                self._send_json(result)
                return
            if parsed.path == "/api/evolve":
                payload = self._read_json()
                with closing(self._conn()) as conn:
                    with conn:
                        result = orchestrator.run_maintenance_evolution(conn, trigger=payload.get("trigger", "manual"))
                    self._send_json(result)
                return
            if parsed.path == "/api/plans/generate":
                with closing(self._conn()) as conn:
                    with conn:
                        try:
                            plan = planner.generate_next_plan(conn, commit=False)
                        except planner.PlannerPlanError as exc:
                            db.record_agent_run(
                                conn,
                                agent_key="planner_agent",
                                engine_type="deterministic",
                                session_id=None,
                                phase="manual_plan_generation",
                                trigger=f"manual_plan_generation_blocked:{db.now_iso()}",
                                input_refs={},
                                status="error",
                                confidence=0.0,
                                output={
                                    "blocked_reason": "planner_quality_gate_failed",
                                    "quality_gates": exc.quality_gates,
                                    "task_count": exc.task_count,
                                    "planner_policy_version": planner.PLANNER_POLICY_VERSION,
                                },
                                error_reason=str(exc),
                                commit=False,
                                **_agent_contract_metadata("planner_agent"),
                            )
                            self._send_json({
                                "status": "blocked",
                                "blocked_reason": "planner_quality_gate_failed",
                                "message": str(exc),
                                "quality_gates": exc.quality_gates,
                                "task_count": exc.task_count,
                            }, status=409)
                            return
                        db.record_agent_run(
                            conn,
                            agent_key="planner_agent",
                            engine_type="deterministic",
                            session_id=None,
                            phase="manual_plan_generation",
                            trigger=f"manual_plan_generation:{plan['id']}",
                            input_refs={"plan_id": plan["id"]},
                            status="accepted",
                            confidence=1.0,
                            output={
                                "plan_id": plan["id"],
                                "plan_policy_version": plan.get("plan_policy_version", plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION)),
                                "planner_policy_version": plan.get("planner_policy_version", planner.PLANNER_POLICY_VERSION),
                                "task_count": len(plan.get("tasks", [])),
                                "round_size": plan.get("round_size", len(plan.get("tasks", []))),
                                "primary_target_node_id": plan.get("primary_target_node_id", ""),
                                "round_structure": plan.get("round_structure") or planner.round_structure(plan.get("tasks", [])),
                                "planning_signal_refs": plan.get("planning_signal_refs") or planner.planning_signal_refs(plan.get("tasks", [])),
                                "quality_gates": plan.get("quality_gates") or planner.quality_gates(conn, plan.get("tasks", [])),
                                "confidence": plan.get("confidence", 1.0),
                                "node_ids": [task.get("node_id") for task in plan.get("tasks", [])],
                                "question_ids": [task.get("question_id") for task in plan.get("tasks", [])],
                            },
                            commit=False,
                            **_agent_contract_metadata("planner_agent"),
                        )
                    self._send_json(plan)
                return
            self._send_error(404, "Unknown API endpoint")
        except knowledge_map.KnowledgeMapError as exc:
            self._send_json(exc.child_payload(), status=exc.status)
        except planner.PlannerPlanError as exc:
            if _is_child_public_post_path(parsed.path):
                self._send_json(_child_planner_recovery_error(), status=409)
                return
            self._send_json({
                "status": "blocked",
                "blocked_reason": "planner_quality_gate_failed",
                "message": str(exc),
                "quality_gates": exc.quality_gates,
                "task_count": exc.task_count,
            }, status=409)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._send_error(400, str(exc))
        except sqlite3.DatabaseError:
            self._send_error(500, "Database error")

    def _answer_photo_from_payload(self, payload: dict) -> dict | None:
        if not payload.get("answer_photo_data_url"):
            return None
        content_type, data = _parse_answer_photo_data_url(payload["answer_photo_data_url"])
        return {
            "content_type": content_type,
            "data": data,
            "data_url": payload["answer_photo_data_url"],
            "original_name": payload.get("answer_photo_name") or "",
            "byte_size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def _resolve_child_submission_target(
        self,
        conn: sqlite3.Connection,
        payload: dict,
        *,
        allow_raw_ids: bool,
    ) -> tuple[dict, str, bool]:
        if not allow_raw_ids:
            forbidden_internal_keys = {"question_id", "session_id", "attempt_id"}
            if any(key in payload for key in forbidden_internal_keys):
                raise ValueError("Child submissions use task position, not internal ids")
        if payload.get("question_id"):
            question = db.get_question(conn, payload["question_id"])
            if not db.is_child_schedulable_question(conn, question):
                raise ValueError("Question is not available for the current learning group; refresh the learning group")
            session_id = payload.get("session_id")
            if not session_id:
                session_id = db.create_session(
                    conn,
                    payload.get("session_title", "孩子提交"),
                    mode="child_submission",
                    commit=False,
                )
            return question, session_id, False

        plan, session = _current_child_plan_context(conn)
        tasks = plan.get("tasks", [])
        try:
            task_position = int(payload.get("task_position", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("请选择要提交的题目") from exc
        if task_position < 1 or task_position > len(tasks):
            raise ValueError("请选择要提交的题目")
        question = db.get_question(conn, tasks[task_position - 1]["question_id"])
        if payload.get("session_handle") not in (None, "", CHILD_SESSION_HANDLE):
            raise ValueError("学习组状态已过期，请刷新后再试")
        if not session or session.get("plan_id") != plan.get("id"):
            session = db.create_learning_session_for_plan(
                conn,
                plan,
                title=payload.get("session_title") or "孩子今日学习",
                commit=False,
            )
            db.record_agent_run(
                conn,
                agent_key="session_orchestrator_agent",
                engine_type="deterministic",
                session_id=session["id"],
                phase="session_start",
                trigger=f"learning_session_start:{session['id']}",
                input_refs={
                    "plan_id": plan.get("id"),
                    "question_ids": session.get("expected_question_ids", []),
                },
                status="accepted",
                confidence=1.0,
                output={
                    "session_id": session["id"],
                    "expected_question_count": len(session.get("expected_question_ids", [])),
                },
                commit=False,
                **_agent_contract_metadata("session_orchestrator_agent"),
            )
        return question, session["id"], True

    def _queued_review_meta(self) -> dict:
        if auto_review._ai_enabled():
            return {
                "status": "queued",
                "reason": "saved for asynchronous answer analysis",
            }
        return {
            "status": "not_configured",
            "reason": "AI evaluator is not configured; answer is saved for later analysis",
        }

    def _create_child_submission(self, payload: dict, *, allow_raw_ids: bool, async_review: bool) -> dict:
        answer_photo = self._answer_photo_from_payload(payload)
        answer_raw = payload.get("answer_raw", "")
        if not answer_raw.strip() and answer_photo is None:
            raise ValueError("Child submission needs written answer or answer photo")
        written_files: list[Path] = []
        enqueue_session_id: str | None = None
        with closing(self._conn()) as conn:
            try:
                with conn:
                    question, session_id, child_safe = self._resolve_child_submission_target(
                        conn,
                        payload,
                        allow_raw_ids=allow_raw_ids,
                    )
                    session = db.get_learning_session(conn, session_id)
                    db.assert_learning_session_questions_current(conn, session)
                    if session.get("status") != "active" or session.get("closure_status") not in {"not_started", "blocked"}:
                        raise ValueError("Learning session is not accepting submissions")
                    expected = set(session.get("expected_question_ids") or [])
                    if expected and question["id"] not in expected:
                        raise ValueError("Question does not belong to this learning session")
                    duplicate = conn.execute(
                        """
                        select 1 from attempts
                        where session_id = ?
                          and question_id = ?
                          and evidence_status = 'active'
                        limit 1
                        """,
                        (session_id, question["id"]),
                    ).fetchone()
                    if duplicate:
                        raise ValueError("Question already has an active submission in this learning session")
                    if async_review:
                        review = {
                            "needs_ai_review": True,
                            "ai_review": self._queued_review_meta(),
                            "confidence": 0.0,
                        }
                    else:
                        review = auto_review.review_child_answer(
                            question,
                            answer_raw,
                            has_photo=answer_photo is not None,
                            answer_photo_data_url=answer_photo["data_url"] if answer_photo else None,
                        )
                    needs_ai_review = bool(review.get("needs_ai_review", review.get("needs_codex_review")))
                    grading_status = "pending_review" if needs_ai_review else "graded"
                    review_max_points = float(review.get("max_points", 2))
                    attempt_id = db.record_attempt(
                        conn,
                        session_id=session_id,
                        question_id=question["id"],
                        node_id=question["node_id"],
                        result="submitted" if needs_ai_review else review["result"],
                        score_points=0 if needs_ai_review else float(review["score_points"]),
                        max_points=review_max_points,
                        error_tags=[] if needs_ai_review else review["error_tags"],
                        answer_raw=answer_raw,
                        parent_note="" if needs_ai_review else review["parent_note"],
                        answer_analysis=None if needs_ai_review else review.get("analysis"),
                        review_meta=review.get("ai_review"),
                        explanation_score=None if needs_ai_review else review["explanation_score"],
                        blocking_evidence=False if needs_ai_review else bool(review["blocking_evidence"]),
                        grading_status=grading_status,
                        commit=False,
                    )
                    attachments = []
                    if answer_photo is not None:
                        attachment, path = self._save_answer_photo(conn, attempt_id, answer_photo)
                        written_files.append(path)
                        attachments.append(_attachment_url(attachment))
                    if async_review:
                        db.enqueue_background_job(
                            conn,
                            job_type="answer_review",
                            session_id=session_id,
                            attempt_id=attempt_id,
                            payload={
                                "question_id": question["id"],
                                "has_photo": answer_photo is not None,
                            },
                            commit=False,
                        )
                    db.record_agent_run(
                        conn,
                        agent_key="answer_analysis_agent",
                        engine_type=_review_engine_type(review),
                        session_id=session_id,
                        phase="answer_analysis",
                        trigger=f"child_submission:{attempt_id}",
                        input_refs={
                            "attempt_id": attempt_id,
                            "question_id": question["id"],
                            "has_photo": answer_photo is not None,
                        },
                        prompt_version_id="2026-07-05.answer-review.prompt.v1",
                        status="pending" if needs_ai_review else "accepted",
                        confidence=float(review.get("confidence", 0.0)) if not needs_ai_review else 0.0,
                        output=_review_audit_output(
                            review,
                            grading_status=grading_status,
                            result="submitted" if needs_ai_review else review.get("result"),
                            score_points=None if needs_ai_review else float(review.get("score_points", 0.0)),
                        ),
                        commit=False,
                        **_model_audit_from_review(review),
                    )
                    if async_review and auto_review._ai_enabled():
                        enqueue_session_id = session_id
                child_message = {
                    "pending_message": "答案已经保存。系统会继续看你的步骤、照片和思路，然后安排下一步。",
                    "child_action": "继续下一题；如果这一组做完了，可以休息。",
                }
                internal_agents.validate_child_safe_message(child_message)
                if enqueue_session_id:
                    self._start_background_session_processing(enqueue_session_id)
                if child_safe:
                    return ChildAPIProjection.submission(grading_status=grading_status, attachments=attachments)
                return {
                    "attempt_id": attempt_id,
                    "session_id": session_id,
                    "question_id": question["id"],
                    "grading_status": grading_status,
                    "child_message": child_message,
                    "attachments": attachments,
                }
            except Exception:
                for path in written_files:
                    path.unlink(missing_ok=True)
                raise

    def _current_child_session_id(self) -> str:
        with closing(self._conn()) as conn:
            plan, session = _current_child_plan_context(conn)
            if not session:
                session = _latest_closed_child_session_for_next_plan(conn, plan.get("id"))
            if not session:
                open_session = _latest_open_child_session(conn)
                if open_session and open_session.get("plan_id") in {"", None, plan.get("id")}:
                    session = open_session
            if not session:
                raise ValueError("还没有开始这一组")
            return session["id"]

    def _create_graded_attempt(self, payload: dict) -> dict:
        answer_photo = self._answer_photo_from_payload(payload)
        written_files: list[Path] = []
        with closing(self._conn()) as conn:
            try:
                with conn:
                    question = db.get_question(conn, payload["question_id"])
                    answer_analysis = _answer_analysis_from_payload(payload)
                    session_id = db.create_session(
                        conn,
                        payload.get("session_title", "本地学习记录"),
                        mode="local_app",
                        commit=False,
                    )
                    attempt_id = db.record_attempt(
                        conn,
                        session_id=session_id,
                        question_id=question["id"],
                        node_id=question["node_id"],
                        result=payload.get("result", "wrong"),
                        score_points=float(payload.get("score_points", 0)),
                        max_points=float(payload.get("max_points", 2)),
                        error_tags=_error_tags_for_payload(payload, payload.get("result", "wrong")),
                        answer_raw=payload.get("answer_raw", ""),
                        parent_note=payload.get("parent_note", ""),
                        answer_analysis=answer_analysis,
                        review_meta={"agent_key": "manual_api_review", "status": "graded"},
                        explanation_score=payload.get("explanation_score"),
                        blocking_evidence=bool(payload.get("blocking_evidence", False)),
                        commit=False,
                    )
                    db.record_agent_run(
                        conn,
                        agent_key="answer_analysis_agent",
                        engine_type="manual_maintenance",
                        session_id=session_id,
                        phase="answer_analysis",
                        trigger=f"manual_api_attempt:{attempt_id}",
                        input_refs={
                            "attempt_id": attempt_id,
                            "question_id": question["id"],
                            "has_answer_analysis": answer_analysis is not None,
                        },
                        status="accepted",
                        confidence=1.0,
                        output={
                            "grading_status": "graded",
                            "result": payload.get("result", "wrong"),
                            "analysis_agent": (answer_analysis or {}).get("agent_key", ""),
                        },
                        commit=False,
                        **_agent_contract_metadata("answer_analysis_agent"),
                    )
                    attachments = []
                    if answer_photo is not None:
                        attachment, path = self._save_answer_photo(conn, attempt_id, answer_photo)
                        written_files.append(path)
                        attachments.append(_attachment_url(attachment))
                return {
                    "attempt_id": attempt_id,
                    "node_id": question["node_id"],
                    "answer_analysis": answer_analysis or {},
                    "attachments": attachments,
                }
            except Exception:
                for path in written_files:
                    path.unlink(missing_ok=True)
                raise

    def _v3_runtime(self, conn: sqlite3.Connection) -> daily_runtime.DailyLearningRuntime:
        return daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)

    def _grade_attempt(self, attempt_id: str, payload: dict) -> dict:
        result = payload.get("result", "wrong")
        error_tags = _error_tags_for_payload(payload, result)
        answer_analysis = _answer_analysis_from_payload(payload)
        with closing(self._conn()) as conn:
            with conn:
                attempt = db.grade_attempt(
                    conn,
                    attempt_id=attempt_id,
                    result=result,
                    score_points=float(payload.get("score_points", 0)),
                    max_points=float(payload.get("max_points", 2)),
                    error_tags=error_tags,
                    answer_raw=payload.get("answer_raw") if "answer_raw" in payload else None,
                    parent_note=payload.get("parent_note", ""),
                    answer_analysis=answer_analysis,
                    review_meta={"agent_key": "manual_api_review", "status": "graded"},
                    explanation_score=payload.get("explanation_score"),
                    blocking_evidence=bool(payload.get("blocking_evidence", False)),
                    commit=False,
                )
                db.record_agent_run(
                    conn,
                    agent_key="answer_analysis_agent",
                    engine_type="manual_maintenance",
                    session_id=attempt["session_id"],
                    phase="answer_analysis",
                    trigger=f"manual_api_grade:{attempt_id}",
                    input_refs={
                        "attempt_id": attempt_id,
                        "question_id": attempt["question_id"],
                        "has_answer_analysis": answer_analysis is not None,
                    },
                    status="accepted",
                    confidence=1.0,
                    output={
                        "grading_status": "graded",
                        "result": attempt["result"],
                        "score_points": attempt["score_points"],
                        "analysis_agent": (answer_analysis or {}).get("agent_key", ""),
                    },
                    commit=False,
                    **_agent_contract_metadata("answer_analysis_agent"),
                )
            attachments = [_attachment_url(attachment) for attachment in db.attachments_for_attempt(conn, attempt_id)]
            return {
                "attempt_id": attempt_id,
                "node_id": attempt["node_id"],
                "grading_status": "graded",
                "answer_analysis": attempt["answer_analysis"],
                "attachments": attachments,
            }

    def _update_attempt_analysis(self, attempt_id: str, payload: dict) -> dict:
        analysis = _answer_analysis_from_payload(payload)
        if not analysis:
            raise ValueError("answer_analysis must be a non-empty object")
        with closing(self._conn()) as conn:
            with conn:
                attempt = db.update_attempt_answer_analysis(
                    conn,
                    attempt_id=attempt_id,
                    answer_analysis=analysis,
                    commit=False,
                )
                db.record_agent_run(
                    conn,
                    agent_key="answer_analysis_agent",
                    engine_type="manual_maintenance",
                    session_id=attempt["session_id"],
                    phase="answer_analysis_backfill",
                    trigger=f"manual_api_analysis:{attempt_id}",
                    input_refs={
                        "attempt_id": attempt_id,
                        "question_id": attempt["question_id"],
                    },
                    status="accepted",
                    confidence=1.0,
                    output={
                        "grading_status": attempt["grading_status"],
                        "analysis_agent": analysis.get("agent_key", ""),
                    },
                    commit=False,
                    **_agent_contract_metadata("answer_analysis_agent"),
                )
            return {
                "attempt_id": attempt_id,
                "node_id": attempt["node_id"],
                "grading_status": attempt["grading_status"],
                "answer_analysis": attempt["answer_analysis"],
            }

    def _close_learning_session(self, session_id: str, *, child_safe: bool = True) -> dict:
        with closing(self._conn()) as conn:
            with conn:
                result = orchestrator.close_learning_session(conn, session_id)
        if result.get("closure_status") == "waiting_ai" and auto_review._ai_enabled():
            self._start_background_session_processing(session_id)
        elif result.get("closure_status") == "waiting_ai" and not auto_review._ai_enabled():
            result = self._mark_ai_review_unavailable(session_id, result)
        return _child_close_projection(result) if child_safe else result

    def _mark_ai_review_unavailable(self, session_id: str, result: dict) -> dict:
        unavailable = {
            **result,
            "closure_status": "blocked",
            "blocked_reason": "ai_review_unavailable",
            "next_plan": None,
            "child_message": {
                "pending_message": "答案已经保存，但系统批阅服务暂时没有连上。系统恢复后会继续处理这组答案。",
                "child_action": "可以先休息，不用自己反复刷新。",
            },
        }
        with closing(self._conn()) as conn:
            with conn:
                try:
                    session = db.get_learning_session(conn, session_id)
                except KeyError:
                    return unavailable
                session = db.update_session_closure_state(
                    conn,
                    session_id=session_id,
                    status=session.get("status", "closing"),
                    closure_status="blocked",
                    closure_result=unavailable,
                    commit=False,
                )
                db.record_agent_run(
                    conn,
                    agent_key="session_orchestrator_agent",
                    engine_type="deterministic",
                    session_id=session_id,
                    phase="background_answer_analysis",
                    trigger=f"ai_review_unavailable:{session_id}",
                    input_refs={
                        "session_id": session_id,
                        "pending_attempt_ids": result.get("attempt_summary", {}).get("pending_attempt_ids", []),
                    },
                    prompt_version_id="2026-07-05.session-orchestrator.prompt.v1",
                    status="error",
                    confidence=0.0,
                    output={"closure_status": "blocked", "blocked_reason": "ai_review_unavailable"},
                    error_reason="AI evaluator route is not configured; waiting_ai cannot be recovered.",
                    commit=False,
                )
                unavailable["session"] = session
        return unavailable

    def _child_bootstrap_response(self) -> dict:
        if daily_runtime.v3_daily_runtime_enabled():
            due_flow_ids: list[str] = []
            with closing(self._conn()) as conn:
                payload = V3ChildAPIProjection.bootstrap(conn)
                now = db.now_iso()
                v5_job_types = tuple(sorted(job_queue.V5_MODEL_JOB_TYPES))
                v5_job_type_placeholders = ",".join("?" for _ in v5_job_types)
                due_flow_ids = [
                    row["flow_id"]
                    for row in conn.execute(
                        f"""
                        select distinct flow_id
                        from background_jobs
                        where flow_id is not null
                          and flow_id <> ''
                          and job_type in ({v5_job_type_placeholders})
                          and (
                            (status = 'queued' and (available_at is null or available_at <= ?))
                            or (status = 'retry' and (retry_after is null or retry_after <= ?))
                            or (status in ('claimed','running') and lease_expires_at is not null and lease_expires_at <= ?)
                          )
                        order by flow_id
                        """,
                        (*v5_job_types, now, now, now),
                    ).fetchall()
                ]
            for flow_id in due_flow_ids:
                self._start_v3_flow_processing(flow_id)
            return payload
        session_to_recover: str | None = None
        with closing(self._conn()) as conn:
            try:
                today_plan, latest_session = _current_child_plan_context(conn)
            except planner.PlannerPlanError as exc:
                return _child_planner_recovery_projection()
            previous_closed_session = _latest_closed_child_session_for_next_plan(conn, today_plan.get("id"))
            payload = {
                "schema_version": CHILD_SCHEMA_VERSION,
                "today_plan": _child_plan(today_plan),
                "learning_group": _child_group_projection(conn, latest_session, today_plan),
            }
            if latest_session and latest_session.get("closure_status") in {"waiting_ai", "blocked"}:
                closure_result = dict(latest_session.get("closure_result") or {})
                closure_result.setdefault("closure_status", latest_session.get("closure_status"))
                closure_result.setdefault("blocked_reason", closure_result.get("blocked_reason", ""))
                if closure_result.get("blocked_reason") != "incomplete_session":
                    closure_result["session"] = latest_session
                    payload["completion"] = _child_close_projection(closure_result)
            elif previous_closed_session and previous_closed_session.get("closure_status") == "planned":
                closure_result = dict(previous_closed_session.get("closure_result") or {})
                closure_result.setdefault("closure_status", "planned")
                closure_result["session"] = previous_closed_session
                payload["completion"] = _child_close_projection(closure_result)
            if (
                latest_session
                and latest_session.get("status") != "closed"
                and (
                    latest_session.get("closure_status") == "waiting_ai"
                    or (
                        latest_session.get("closure_status") == "blocked"
                        and latest_session.get("closure_result", {}).get("blocked_reason") == "ai_review_unavailable"
                    )
                )
            ):
                session_to_recover = latest_session["id"]
        if session_to_recover and auto_review._ai_enabled():
            self._start_background_session_processing(session_to_recover)
        return payload

    def _start_background_session_processing(self, session_id: str) -> None:
        with self.background_lock:
            if session_id in self.background_sessions:
                self.background_session_rerun.add(session_id)
                return
            self.background_sessions.add(session_id)
        self._spawn_background_session_thread(session_id)

    def _spawn_background_session_thread(self, session_id: str) -> None:
        thread = threading.Thread(
            target=self._background_process_session,
            args=(session_id,),
            daemon=True,
        )
        thread.start()

    def _background_process_session(self, session_id: str) -> None:
        try:
            max_passes = max(1, int(os.environ.get("AI_BACKGROUND_REVIEW_MAX_PASSES", "3")))
            for index in range(max_passes):
                with closing(self._conn()) as conn:
                    processing = self._process_pending_session_answers(conn, session_id)
                    session = db.get_learning_session(conn, session_id)
                    summary = db.session_completion_summary(conn, session_id)
                    ready_to_close = not summary["missing_question_ids"] or session.get("status") == "closing"
                    close_result = None
                    if ready_to_close:
                        with conn:
                            close_result = orchestrator.close_learning_session(conn, session_id)
                if close_result is not None and close_result.get("closure_status") != "waiting_ai":
                    return
                pending_after = close_result.get("attempt_summary", summary).get("pending_attempt_ids", []) if close_result else summary.get("pending_attempt_ids", [])
                if not pending_after or not auto_review._ai_enabled():
                    return
                if index < max_passes - 1:
                    time.sleep(min(2 ** index, 5))
        except Exception as exc:
            self._record_background_session_error(session_id, exc)
            return
        finally:
            restart = False
            with self.background_lock:
                if session_id in self.background_session_rerun:
                    self.background_session_rerun.discard(session_id)
                    restart = True
                else:
                    self.background_sessions.discard(session_id)
            if restart:
                self._spawn_background_session_thread(session_id)

    def _record_background_session_error(self, session_id: str, exc: Exception) -> None:
        reason = f"{type(exc).__name__}: {exc}"[:800]
        try:
            with closing(self._conn()) as conn:
                with conn:
                    try:
                        session = db.get_learning_session(conn, session_id)
                    except KeyError:
                        session = {}
                    closure_result = dict(session.get("closure_result") or {})
                    closure_result["background_error"] = {
                        "phase": "background_answer_analysis",
                        "reason": reason,
                        "created_at": db.now_iso(),
                    }
                    if session:
                        db.update_session_closure_state(
                            conn,
                            session_id=session_id,
                            status=session.get("status", "closing"),
                            closure_status=session.get("closure_status", "waiting_ai"),
                            closure_result=closure_result,
                            commit=False,
                        )
                    db.record_agent_run(
                        conn,
                        agent_key="session_orchestrator_agent",
                        engine_type="hybrid",
                        session_id=session_id,
                        phase="background_answer_analysis",
                        trigger=f"background_session_error:{session_id}:{db.now_iso()}",
                        input_refs={"session_id": session_id},
                        prompt_version_id="2026-07-05.session-orchestrator.prompt.v1",
                        status="error",
                        confidence=0.0,
                        output={"closure_status": closure_result.get("closure_status", "waiting_ai")},
                        error_reason=reason,
                        commit=False,
                    )
        except Exception:
            return

    @classmethod
    def _start_existing_background_work(cls) -> None:
        worker = object.__new__(cls)
        worker.db_path = cls.db_path
        worker.answer_upload_root = cls.answer_upload_root
        try:
            with closing(db.connect(cls.db_path)) as conn:
                session_ids = db.pending_background_session_ids(conn) if auto_review._ai_enabled() else []
                now = db.now_iso()
                v5_job_types = tuple(sorted(job_queue.V5_MODEL_JOB_TYPES))
                v5_job_type_placeholders = ",".join("?" for _ in v5_job_types)
                v3_flow_ids = [
                    row["flow_id"]
                    for row in conn.execute(
                        f"""
                        select distinct flow_id
                        from background_jobs
                        where flow_id is not null
                          and flow_id <> ''
                          and job_type in ({v5_job_type_placeholders})
                          and (
                            (status = 'queued' and (available_at is null or available_at <= ?))
                            or (status = 'retry' and (retry_after is null or retry_after <= ?))
                            or (status in ('claimed','running') and lease_expires_at is not null and lease_expires_at <= ?)
                          )
                        order by flow_id
                        """,
                        (*v5_job_types, now, now, now),
                    ).fetchall()
                ] if daily_runtime.v3_daily_runtime_enabled() else []
        except sqlite3.DatabaseError:
            return
        for session_id in session_ids:
            worker._start_background_session_processing(session_id)
        for flow_id in v3_flow_ids:
            worker._start_v3_flow_processing(flow_id)

    def _start_v3_flow_processing(self, flow_id: str) -> None:
        self._start_v5_flow_processing(flow_id)

    def _start_v5_flow_processing(self, flow_id: str) -> None:
        if not flow_id:
            return
        with self.v3_background_lock:
            if flow_id in self.v3_background_flows:
                self.v3_background_flow_rerun.add(flow_id)
                return
            self.v3_background_flows.add(flow_id)
        self._spawn_v5_flow_thread(flow_id)

    def _spawn_v3_flow_thread(self, flow_id: str) -> None:
        self._spawn_v5_flow_thread(flow_id)

    def _spawn_v5_flow_thread(self, flow_id: str) -> None:
        thread = threading.Thread(
            target=self._background_process_v5_flow,
            args=(flow_id,),
            daemon=True,
        )
        thread.start()

    def _background_process_v3_flow(self, flow_id: str) -> None:
        self._background_process_v5_flow(flow_id)

    def _background_process_v5_flow(self, flow_id: str) -> None:
        try:
            max_jobs = max(1, int(os.environ.get("V5_DAILY_FLOW_WORKER_MAX_JOBS", os.environ.get("V3_DAILY_FLOW_WORKER_MAX_JOBS", "20"))))
            worker_id = f"v5-daily-flow-{uuid.uuid4().hex[:8]}"
            for _ in range(max_jobs):
                with closing(self._conn()) as conn:
                    result = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT).process_next_background_job(
                        worker_id=worker_id,
                        flow_id=flow_id,
                    )
                if not result.get("processed"):
                    break
                if result.get("job_status") in {"blocked", "waiting"}:
                    break
        except Exception as exc:
            self._record_v5_flow_worker_error(flow_id, exc)
            return
        finally:
            restart = False
            with self.v3_background_lock:
                if flow_id in self.v3_background_flow_rerun:
                    self.v3_background_flow_rerun.discard(flow_id)
                    restart = True
                else:
                    self.v3_background_flows.discard(flow_id)
            if restart:
                self._spawn_v5_flow_thread(flow_id)

    def _record_v5_flow_worker_error(self, flow_id: str, exc: Exception) -> None:
        reason = f"{type(exc).__name__}: {exc}"[:800]
        try:
            with closing(self._conn()) as conn:
                with conn:
                    conn.execute(
                        """
                        update background_jobs
                        set last_error = ?,
                            updated_at = ?
                        where flow_id = ?
                          and job_type in ('answer_analysis','evaluation_update','planner_decision','teaching_generation')
                          and status in ('queued','claimed','running','retry')
                        """,
                        (reason, db.now_iso(), flow_id),
                    )
        except Exception:
            return

    def _answer_photo_data_url_for_attempt(self, conn: sqlite3.Connection, attempt_id: str) -> str | None:
        attachments = db.attachments_for_attempt(conn, attempt_id)
        for attachment in attachments:
            if attachment["kind"] != "answer_photo" or attachment["content_type"] not in ALLOWED_ANSWER_PHOTO_TYPES:
                continue
            filename = attachment["filename"]
            if not filename or "/" in filename or "\\" in filename or Path(filename).name != filename:
                continue
            target = (self.answer_upload_root.resolve() / filename).resolve()
            if target.parent != self.answer_upload_root.resolve() or not target.is_file():
                continue
            data = target.read_bytes()
            if (
                len(data) != int(attachment["byte_size"])
                or hashlib.sha256(data).hexdigest() != attachment["sha256"]
                or not _looks_like_allowed_image(attachment["content_type"], data)
            ):
                continue
            encoded = base64.b64encode(data).decode("ascii")
            return f"data:{attachment['content_type']};base64,{encoded}"
        return None

    def _process_pending_session_answers(self, conn: sqlite3.Connection, session_id: str) -> dict:
        session = db.get_learning_session(conn, session_id)
        if session.get("mode") != "child_learning_group":
            return {"processed": 0, "still_pending": 0, "skipped": "not_child_learning_group"}
        db.assert_learning_session_questions_current(conn, session)
        rows = conn.execute(
            """
            select *
            from attempts
            where session_id = ?
              and grading_status = 'pending_review'
              and evidence_status = 'active'
            order by created_at, id
            """,
            (session_id,),
        ).fetchall()
        jobs = []
        for index, row in enumerate(rows):
            attempt = db.attempt_row_to_dict(row)
            question = db.get_question(conn, attempt["question_id"])
            photo_data_url = self._answer_photo_data_url_for_attempt(conn, attempt["id"])
            with conn:
                db.enqueue_background_job(
                    conn,
                    job_type="answer_review",
                    session_id=session_id,
                    attempt_id=attempt["id"],
                    payload={
                        "question_id": question["id"],
                        "has_photo": photo_data_url is not None,
                        "source": "pending_attempt_recovery",
                    },
                    commit=False,
                )
                db.mark_background_job_running(
                    conn,
                    job_type="answer_review",
                    session_id=session_id,
                    attempt_id=attempt["id"],
                    commit=False,
                )
            jobs.append({
                "index": index,
                "attempt": attempt,
                "question": question,
                "photo_data_url": photo_data_url,
            })

        def review_job(job: dict[str, Any]) -> dict[str, Any]:
            photo_data_url = job["photo_data_url"]
            review = auto_review.review_child_answer(
                job["question"],
                job["attempt"]["answer_raw"],
                has_photo=photo_data_url is not None,
                answer_photo_data_url=photo_data_url,
            )
            return {**job, "review": review}

        processed = 0
        still_pending = 0
        concurrency = min(len(jobs), _background_review_concurrency())
        if concurrency <= 1:
            reviewed_jobs = [review_job(job) for job in jobs]
        else:
            with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="answer-review") as executor:
                futures = [executor.submit(review_job, job) for job in jobs]
                reviewed_jobs = [future.result() for future in as_completed(futures)]
            reviewed_jobs.sort(key=lambda job: int(job["index"]))

        for reviewed_job in reviewed_jobs:
            attempt = reviewed_job["attempt"]
            question = reviewed_job["question"]
            photo_data_url = reviewed_job["photo_data_url"]
            review = reviewed_job["review"]
            grade = _review_to_attempt_grade(review)
            with conn:
                if grade is None:
                    still_pending += 1
                    conn.execute(
                        "update attempts set review_meta_json = ? where id = ?",
                        (db.json_dump(review.get("ai_review", {"status": "pending", "reason": review.get("reason", "")})), attempt["id"]),
                    )
                    db.finish_background_job(
                        conn,
                        job_type="answer_review",
                        session_id=session_id,
                        attempt_id=attempt["id"],
                        status="waiting",
                        last_error=str(review.get("reason") or review.get("parent_note") or ""),
                        commit=False,
                    )
                    db.record_agent_run(
                        conn,
                        agent_key="answer_analysis_agent",
                        engine_type=_review_engine_type(review),
                        session_id=session_id,
                        phase="answer_analysis",
                        trigger=f"background_review_pending:{attempt['id']}:{db.now_iso()}",
                        input_refs={
                            "attempt_id": attempt["id"],
                            "question_id": question["id"],
                            "has_photo": photo_data_url is not None,
                        },
                        prompt_version_id="2026-07-05.answer-review.prompt.v1",
                        status="pending",
                        confidence=0.0,
                        output=_review_audit_output(review, grading_status="pending_review"),
                        commit=False,
                        **_model_audit_from_review(review),
                    )
                    continue
                latest = db.get_attempt(conn, attempt["id"])
                if latest["grading_status"] != "pending_review" or latest.get("evidence_status") != "active":
                    db.finish_background_job(
                        conn,
                        job_type="answer_review",
                        session_id=session_id,
                        attempt_id=attempt["id"],
                        status="succeeded",
                        commit=False,
                    )
                    continue
                db.grade_attempt(
                    conn,
                    attempt_id=attempt["id"],
                    answer_raw=None,
                    commit=False,
                    **grade,
                )
                db.finish_background_job(
                    conn,
                    job_type="answer_review",
                    session_id=session_id,
                    attempt_id=attempt["id"],
                    status="succeeded",
                    commit=False,
                )
                processed += 1
                db.record_agent_run(
                    conn,
                    agent_key="answer_analysis_agent",
                    engine_type=_review_engine_type(review),
                    session_id=session_id,
                    phase="answer_analysis",
                    trigger=f"background_review_graded:{attempt['id']}:{db.now_iso()}",
                    input_refs={
                        "attempt_id": attempt["id"],
                        "question_id": question["id"],
                        "has_photo": photo_data_url is not None,
                    },
                    prompt_version_id="2026-07-05.answer-review.prompt.v1",
                    status="accepted",
                    confidence=float(review.get("confidence", 0.0)),
                    output=_review_audit_output(
                        review,
                        grading_status="graded",
                        result=grade["result"],
                        score_points=grade["score_points"],
                    ),
                    commit=False,
                    **_model_audit_from_review(review),
                )
        return {"processed": processed, "still_pending": still_pending, "concurrency": concurrency}

    def _invalidate_attempt(self, attempt_id: str, payload: dict) -> dict:
        with closing(self._conn()) as conn:
            with conn:
                attempt = db.invalidate_attempt(
                    conn,
                    attempt_id=attempt_id,
                    evidence_note=payload.get("evidence_note", ""),
                    commit=False,
                )
            return {
                "attempt_id": attempt_id,
                "node_id": attempt["node_id"],
                "grading_status": attempt["grading_status"],
                "evidence_status": attempt["evidence_status"],
                "evidence_note": attempt["evidence_note"],
            }

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            path = "/index.html"
        target = (APP_ROOT / path.lstrip("/")).resolve()
        if not str(target).startswith(str(APP_ROOT.resolve())) or not target.is_file():
            self._send_error(404, "Not found")
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _save_answer_photo(self, conn: sqlite3.Connection, attempt_id: str, answer_photo: dict) -> tuple[dict, Path]:
        upload_root = self.answer_upload_root.resolve()
        filename = _safe_answer_photo_filename(answer_photo["original_name"], answer_photo["content_type"], attempt_id)
        target = (upload_root / filename).resolve()
        if target.parent != upload_root:
            raise ValueError("Invalid answer photo filename")
        upload_root.mkdir(parents=True, exist_ok=True)
        temp_target = (upload_root / f".{filename}.tmp").resolve()
        target_created = False
        try:
            temp_target.write_bytes(answer_photo["data"])
            temp_target.replace(target)
            target_created = True
            attachment = db.record_attempt_attachment(
                conn,
                attempt_id=attempt_id,
                kind="answer_photo",
                original_filename=answer_photo["original_name"],
                filename=filename,
                content_type=answer_photo["content_type"],
                byte_size=answer_photo["byte_size"],
                sha256=answer_photo["sha256"],
                relative_path=f"{ANSWER_UPLOAD_RELATIVE_PREFIX}/{filename}",
                commit=False,
            )
        except Exception:
            temp_target.unlink(missing_ok=True)
            if target_created:
                target.unlink(missing_ok=True)
            raise
        return attachment, target

    def _serve_attachment(self, path: str) -> None:
        prefix = "/api/attachments/"
        attachment_id = unquote(path[len(prefix):])
        if not attachment_id or "/" in attachment_id or "\\" in attachment_id:
            self._send_error(404, "Not found")
            return
        try:
            with closing(self._conn()) as conn:
                attachment = db.get_attachment(conn, attachment_id)
        except KeyError:
            self._send_error(404, "Not found")
            return
        if attachment["kind"] != "answer_photo" or attachment["content_type"] not in ALLOWED_ANSWER_PHOTO_TYPES:
            self._send_error(404, "Not found")
            return
        filename = attachment["filename"]
        if not filename or "/" in filename or "\\" in filename or Path(filename).name != filename:
            self._send_error(404, "Not found")
            return
        upload_root = self.answer_upload_root.resolve()
        target = (upload_root / filename).resolve()
        if target.parent != upload_root or not target.is_file():
            self._send_error(404, "Not found")
            return
        body = target.read_bytes()
        if (
            len(body) != int(attachment["byte_size"])
            or hashlib.sha256(body).hexdigest() != attachment["sha256"]
            or not _looks_like_allowed_image(attachment["content_type"], body)
        ):
            self._send_error(409, "Attachment file does not match recorded metadata")
            return
        self.send_response(200)
        self.send_header("Content-Type", attachment["content_type"])
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(
    db_path: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    upload_root: Path | None = None,
) -> ThreadingHTTPServer:
    class BoundHandler(LearningHandler):
        pass

    BoundHandler.db_path = db_path
    BoundHandler.answer_upload_root = upload_root or ANSWER_UPLOAD_ROOT
    BoundHandler.background_lock = threading.Lock()
    BoundHandler.background_sessions = set()
    BoundHandler.background_session_rerun = set()
    BoundHandler.v3_background_lock = threading.Lock()
    BoundHandler.v3_background_flows = set()
    BoundHandler.v3_background_flow_rerun = set()
    if _should_reconcile_v3_uploads(db_path, BoundHandler.answer_upload_root):
        with closing(db.connect(db_path)) as conn:
            daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT).reconcile_answer_uploads()
    httpd = ThreadingHTTPServer((host, port), BoundHandler)
    BoundHandler._start_existing_background_work()
    return httpd


def _should_reconcile_v3_uploads(db_path: Path, upload_root: Path | None = None) -> bool:
    if not daily_runtime.v3_daily_runtime_enabled():
        return False
    try:
        resolved = db_path.resolve()
        expected_db = (PROJECT_ROOT / "data/local_learning_system.sqlite").resolve()
        resolved_upload_root = (upload_root or ANSWER_UPLOAD_ROOT).resolve()
        return resolved == expected_db and resolved_upload_root == ANSWER_UPLOAD_ROOT.resolve()
    except OSError:
        return False


def start_test_server(db_path: Path, upload_root: Path | None = None) -> tuple[ThreadingHTTPServer, str]:
    httpd = make_server(db_path, port=0, upload_root=upload_root)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    return httpd, f"http://{host}:{port}"


def main() -> None:
    loaded_env_keys = _load_local_env_file()
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data/local_learning_system.sqlite"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--upload-root", default=str(ANSWER_UPLOAD_ROOT))
    args = parser.parse_args()
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db.connect(db_path) as conn:
        db.init_schema(conn)
        if not _db_has_active_seed_assets(conn):
            db.seed_from_assets(conn, PROJECT_ROOT)
    httpd = make_server(db_path, args.host, args.port, upload_root=Path(args.upload_root))
    print(f"Serving local learning system at http://{args.host}:{args.port}", flush=True)
    if loaded_env_keys:
        print(f"Loaded local runtime env from .env.local: {', '.join(loaded_env_keys)}", flush=True)
    for line in _startup_ai_status_lines():
        print(line, flush=True)
    httpd.serve_forever()


def _db_has_active_seed_assets(conn: sqlite3.Connection) -> bool:
    try:
        graph_nodes = int(conn.execute("select count(*) from graph_nodes").fetchone()[0])
        questions = int(conn.execute("select count(*) from question_items").fetchone()[0])
        active_ledgers = int(
            conn.execute(
                "select count(*) from question_bank_version_ledger where status = 'active'"
            ).fetchone()[0]
        )
    except sqlite3.DatabaseError:
        return False
    return graph_nodes > 0 and questions > 0 and active_ledgers == 1


if __name__ == "__main__":
    main()
