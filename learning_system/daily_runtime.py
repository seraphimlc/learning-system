from __future__ import annotations

import os
import base64
import binascii
import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import (
    assessment_policy,
    assessment_store,
    auto_review,
    child_prompt,
    db,
    evidence_gate,
    internal_agents,
    job_queue,
    model_router,
    question_bank,
    question_fingerprints,
    question_visuals,
    semantic_agents,
)
from .graph_runtime import GraphRuntimeService


V3_CHILD_SCHEMA_VERSION = "3.0.0-daily-flow"
V3_FEATURE_FLAG = "V3_DAILY_RUNTIME_ENABLED"
KNOWLEDGE_MAP_HOME_POLICY_ENV = "KNOWLEDGE_MAP_HOME_POLICY"
ANSWER_ASSESSMENT_POLICY_ENV = "ANSWER_ASSESSMENT_POLICY"
ACTIVE_FLOW_STATUSES = ("new", "reviewing", "ready_for_new_knowledge", "learning_new", "paused", "blocked")
TERMINAL_FLOW_STATUSES = ("completed", "superseded")
ANSWER_UPLOAD_RELATIVE_PREFIX = "data/uploads/answers"
MAX_ANSWER_PHOTO_BYTES = 8 * 1024 * 1024
ALLOWED_ANSWER_PHOTO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _authoritative_target_asset(
    authority: dict[str, Any],
    *,
    node_id: str,
    action: str,
) -> dict[str, Any] | None:
    assets = list(
        authority.get("assessment", {})
        .get("assets_by_node", {})
        .get(str(node_id or ""), [])
    )
    if not assets:
        return None
    if action == "challenge":
        assets.sort(
            key=lambda item: (
                "stretch" not in str((item.get("question") or {}).get("kind") or ""),
                str(item.get("question_id") or ""),
            )
        )
    else:
        assets.sort(key=lambda item: str(item.get("question_id") or ""))
    return assets[0]


def qualify_knowledge_target_action(
    conn: sqlite3.Connection,
    authority: dict[str, Any],
    *,
    node_id: str,
    action: str,
    status_by_node: dict[str, str] | None = None,
    source_step: sqlite3.Row | dict[str, Any] | None = None,
    preserve_current_step: bool = False,
) -> dict[str, Any]:
    node = authority.get("snapshot", {}).get("nodes", {}).get(str(node_id or "")) or {}
    result_behavior = (
        "wait_for_safe_boundary"
        if source_step and str(source_step["status"] or "") == "analyzing" and not preserve_current_step
        else "enter_now"
    )

    def blocked(reason_code: str, reason: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "reason_code": reason_code,
            "disabled_reason": reason,
            "result_behavior": result_behavior,
            "asset": None,
        }

    if not node or action not in {"diagnostic", "learn", "review", "challenge"}:
        return blocked("target_action_not_supported", "这个开始方式已经变化，请刷新后重新选择。")
    if action in {"learn", "review", "challenge"} and not str(
        node.get("essence_for_child") or ""
    ).strip():
        return blocked(
            "target_content_not_authoritative",
            "这个知识点的学习内容还在准备，暂时不能开始。",
        )
    asset = _authoritative_target_asset(
        authority,
        node_id=str(node_id),
        action=action,
    )
    if asset is None:
        return blocked(
            "target_asset_not_authoritative",
            "这个知识点的小检测和学习材料还没有完成完整审查，暂时不能开始。",
        )
    if action in {"learn", "challenge"}:
        prerequisite_ids = [
            str(candidate)
            for candidate in node.get("prerequisites", [])
            if str(candidate)
        ]
        if prerequisite_ids:
            if status_by_node is None:
                status_by_node = {
                    str(row["node_id"]): str(row["status_code"])
                    for row in db.authoritative_learner_node_status_rows(
                        conn,
                        graph_version=str(authority["snapshot"]["graph_lineage"]),
                        question_bank_version=str(
                            authority["assessment"]["ledger"]["question_bank_version"]
                        ),
                    )
                }
            if any(status_by_node.get(candidate) != "A" for candidate in prerequisite_ids):
                return blocked(
                    "target_prerequisites_not_ready",
                    "前面的准备知识还没有确认稳，请先完成准备知识。",
                )
    return {
        "enabled": True,
        "reason_code": "",
        "disabled_reason": "",
        "result_behavior": result_behavior,
        "asset": asset,
    }


class _ChildSafeAliasKey(str):
    """Dictionary key that keeps legacy in-process lookup while serializing child-safe text."""

    def __new__(cls, child_key: str, legacy_key: str):
        obj = str.__new__(cls, child_key)
        obj._legacy_key = legacy_key
        return obj

    def __hash__(self) -> int:
        return hash(self._legacy_key)

    def __eq__(self, other: object) -> bool:
        return other == self._legacy_key or str.__eq__(self, other)

CHILD_FORBIDDEN_TERMS = (
    "OPENAI_API_KEY",
    "AI_EVALUATOR",
    "API_KEY",
    "OPENAI",
    "response_format",
    "json_schema",
    "base_url",
    "gpt-",
    "deepseek",
    "doubao",
    "graph_version",
    "question_id",
    "attempt_id",
    "session_id",
    "flow_id",
    "step_id",
    "provider",
    "agent",
    "Agent",
    "Codex",
    "rubric",
    "queue",
    "job",
    "OCR",
    "ocr",
    "知识图谱",
    "图谱",
    "节点",
    "模型路由",
)


class ChildSafeRuntimeError(ValueError):
    def __init__(self, message: str, *, status: int = 409, child_action: str = "刷新后再试一次。") -> None:
        super().__init__(message)
        self.status = status
        self.child_action = child_action

    def child_payload(self) -> dict[str, Any]:
        return {
            "schema_version": V3_CHILD_SCHEMA_VERSION,
            "child_state": "blocked",
            "message": {
                "title": "现在还不能继续",
                "body": _child_safe_text(str(self), "系统暂时不能安全判断这一步，请稍后再试。", limit=220),
                "action_label": self.child_action,
            },
        }


@dataclass(frozen=True)
class CurrentStepSubmission:
    step_handle: str
    position: int
    client_idempotency_key: str
    answer_text: str = ""
    answer_photo_data_url: str = ""
    answer_photo_name: str = ""
    interaction_response: dict[str, Any] = field(default_factory=dict)
    stuck: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CurrentStepSubmission":
        try:
            position = int(payload.get("position"))
        except (TypeError, ValueError) as exc:
            raise ChildSafeRuntimeError("这一步的位置已经变了，请刷新后继续。") from exc
        return cls(
            step_handle=str(payload.get("step_handle") or "").strip(),
            position=position,
            client_idempotency_key=str(payload.get("client_idempotency_key") or "").strip(),
            answer_text=str(payload.get("answer_text") or "").strip(),
            answer_photo_data_url=str(payload.get("answer_photo_data_url") or "").strip(),
            answer_photo_name=str(payload.get("answer_photo_name") or "").strip(),
            interaction_response=payload.get("interaction_response") if isinstance(payload.get("interaction_response"), dict) else {},
            stuck=bool(payload.get("stuck", False)),
        )


def _is_explicit_stuck_text(answer_text: str) -> bool:
    """Classify short child intent signals; this is routing, not answer grading."""
    raw = str(answer_text or "").strip()
    if not raw:
        return False
    normalized = raw
    for char in (" ", "\t", "\n", "\r", "。", "，", ",", ".", "！", "!", "？", "?", "～", "~"):
        normalized = normalized.replace(char, "")
    direct_stuck_signals = {
        "不会",
        "我不会",
        "不会做",
        "我不会做",
        "不会了",
        "做不出来",
        "我做不出来",
        "不知道",
        "我不知道",
        "看不懂",
        "我看不懂",
        "卡住",
        "卡住了",
        "我卡住了",
    }
    if normalized in direct_stuck_signals:
        return True
    if len(normalized) > 40:
        return False
    # Longer text is still a routing-only stuck signal when it matches the
    # child UI's own stuck prompts and does not include mathematical work.
    if any(symbol in normalized for symbol in ("=", "+", "-", "×", "÷", "*", "/", "^", "<", ">", "|")):
        return False
    return any(
        phrase in normalized
        for phrase in (
            "我卡住了",
            "卡住了",
            "看不懂题目",
            "题目意思没看懂",
            "不知道第一步",
            "第一步该写什么",
            "算到一半卡住",
            "接不下去了",
            "这道题我不会",
            "这题我不会",
            "题我不会",
        )
    )


def v3_daily_runtime_enabled() -> bool:
    return os.environ.get(V3_FEATURE_FLAG, "0").strip().lower() in {"1", "true", "yes", "on"}


def answer_assessment_v51_enabled() -> bool:
    return os.environ.get(ANSWER_ASSESSMENT_POLICY_ENV, "").strip() == "v5.1"


def knowledge_map_home_policy_requested() -> bool:
    return os.environ.get(KNOWLEDGE_MAP_HOME_POLICY_ENV, "").strip() == "v5.1"


def knowledge_map_home_enabled(
    conn: sqlite3.Connection | None = None,
    *,
    project_root: Path | str | None = None,
) -> bool:
    if not knowledge_map_home_policy_requested() or not answer_assessment_v51_enabled() or conn is None:
        return False
    try:
        from .knowledge_map import KnowledgeMapService

        KnowledgeMapService(conn, project_root=project_root)._runtime_authority()
        return True
    except (OSError, ValueError, sqlite3.DatabaseError):
        return False


def disabled_child_payload() -> dict[str, Any]:
    return {
        "schema_version": V3_CHILD_SCHEMA_VERSION,
        "child_state": "blocked",
        "message": {
            "title": "今天还在使用原来的学习流程",
            "body": "这个入口暂时没有打开。",
            "action_label": "返回当前学习页",
        },
    }


V5_CANONICAL_CHILD_STATE_ALIASES = {
    "choose_review": "start_resume",
    "analyzing": "analyzing_pending",
    "preparing_new_knowledge": "analyzing_pending",
    "teaching": "feedback_teaching",
}


def canonicalize_v5_child_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """External child API projection: keep legacy internals, expose v5 state names."""
    if not isinstance(payload, dict):
        return payload
    child_state = str(payload.get("child_state") or "")
    canonical = V5_CANONICAL_CHILD_STATE_ALIASES.get(child_state)
    if not canonical:
        return payload
    return {**payload, "child_state": canonical}


class DailyLearningRuntime:
    """Daily-flow runtime: deterministic controller for the v5 child loop."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        project_root: Path | str | None = None,
        child_key: str = db.V3_DEFAULT_CHILD_KEY,
    ) -> None:
        self.conn = conn
        self.project_root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
        self.child_key = child_key
        self.graph = GraphRuntimeService(conn, project_root=self.project_root)

    def reconcile_answer_uploads(self) -> dict[str, int]:
        """Remove v3 upload files that are not backed by attachment rows."""
        upload_root = (self.project_root / ANSWER_UPLOAD_RELATIVE_PREFIX).resolve()
        if not upload_root.exists():
            return {"removed_orphan_files": 0, "removed_temp_files": 0}
        referenced = {
            str(row["filename"])
            for row in self.conn.execute(
                """
                select filename
                from attempt_attachments
                where kind = 'answer_photo'
                  and relative_path like ?
                """,
                (f"{ANSWER_UPLOAD_RELATIVE_PREFIX}/%",),
            ).fetchall()
        }
        removed_orphans = 0
        removed_temps = 0
        for path in upload_root.iterdir():
            if not path.is_file():
                continue
            if path.name.startswith(".") and path.name.endswith(".tmp"):
                path.unlink(missing_ok=True)
                removed_temps += 1
                continue
            if path.name not in referenced:
                path.unlink(missing_ok=True)
                removed_orphans += 1
        return {"removed_orphan_files": removed_orphans, "removed_temp_files": removed_temps}

    def load_or_create_daily_flow(self, local_date: str | None = None) -> dict[str, Any]:
        local_date = local_date or date.today().isoformat()
        try:
            graph_version = self.graph.current_graph_version()
        except Exception:
            return self._blocked_projection("学习图谱暂时没有准备好，请稍后再试。")
        recovered_flow_id = ""
        if knowledge_map_home_policy_requested():
            try:
                recovered = self.recover_target_intents(local_date=local_date)
                recovered_flow_id = str(recovered.get("flow_id") or "")
            except Exception as exc:
                from . import knowledge_map

                if not isinstance(exc, knowledge_map.KnowledgeMapError):
                    raise
                savepoint, nested = knowledge_map._begin_write(self.conn, "block_stale_target")
                try:
                    pending = self.conn.execute(
                        """
                        select id from learning_target_intents
                        where child_key = ?
                          and status in ('pending','waiting_for_safe_boundary')
                        order by created_at desc, id desc limit 1
                        """,
                        (self.child_key,),
                    ).fetchone()
                    if pending:
                        self.conn.execute(
                            """
                            update learning_target_intents
                            set status = 'blocked', reason = 'map_authority_unavailable', updated_at = ?
                            where id = ?
                            """,
                            (db.now_iso(), pending["id"]),
                        )
                    knowledge_map._finish_write(self.conn, savepoint, nested)
                except Exception:
                    knowledge_map._rollback_write(self.conn, savepoint, nested)
                    raise
        with self.conn:
            flow = (
                self._flow_by_id(recovered_flow_id)
                if recovered_flow_id
                else None
            ) or self._active_flow(local_date) or self._latest_terminal_flow(local_date)
            if flow is None:
                flow = self._create_daily_flow(local_date, graph_version)
            elif flow["status"] == "blocked":
                self._try_enqueue_recovery_for_blocked_flow(dict(flow))
                flow = self._flow_by_id(flow["id"])
        return self.project_child_state(flow)

    def start_review_mode(self, *, client_day_key: str | None = None) -> dict[str, Any]:
        local_date = (client_day_key or date.today().isoformat())[:10]
        try:
            graph_version = self.graph.current_graph_version()
        except Exception:
            return self._blocked_projection("学习图谱暂时没有准备好，请稍后再试。")
        with self.conn:
            flow = self._active_flow(local_date)
            if flow is None:
                flow = self._create_daily_flow(local_date, graph_version)
            if flow is None:
                return self._blocked_projection("今天的学习记录暂时打不开，请稍后再试。")
            if flow["status"] in TERMINAL_FLOW_STATUSES:
                return self.project_child_state(flow)
            if flow["status"] in {"new", "blocked"}:
                step_id = self._ensure_first_review_step(flow, graph_version)
                now = db.now_iso()
                self.conn.execute(
                    """
                    update daily_flows
                    set mode = 'review_old_knowledge',
                        status = 'reviewing',
                        current_step_id = ?,
                        blocked_reason = '',
                        flow_revision = flow_revision + 1,
                        updated_at = ?
                    where id = ?
                    """,
                    (step_id, now, flow["id"]),
                )
                flow = self._flow_by_id(flow["id"])
        return self.project_child_state(flow)

    def _create_daily_flow(self, local_date: str, graph_version: str) -> sqlite3.Row:
        legacy_session_id = db.create_session(
            self.conn,
            f"v3 daily flow {local_date}",
            mode="daily_flow_v3",
            status="active",
            commit=False,
        )
        now = db.now_iso()
        flow_id = f"DF-{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            insert into daily_flows(
              id, child_key, local_date, mode, status, budget_min, budget_max,
              current_step_id, graph_version, planned_graph_node_ids_json,
              question_bank_version, legacy_session_id, flow_revision,
              created_by_runtime_version, source_plan_id, blocked_reason,
              summary_id, created_at, updated_at
            ) values (?, ?, ?, 'not_selected', 'new', 10, 20, null, ?, '[]', ?, ?, 1, ?, null, '', null, ?, ?)
            """,
            (
                flow_id,
                self.child_key,
                local_date,
                graph_version,
                db.get_active_question_bank_version(self.conn),
                legacy_session_id,
                db.V3_RUNTIME_VERSION,
                now,
                now,
            ),
        )
        flow = self._flow_by_id(flow_id)
        if not flow:
            raise ChildSafeRuntimeError("今天的学习记录暂时打不开，请稍后再试。")
        return flow

    def _target_asset_for_intent(
        self,
        authority: dict[str, Any],
        intent: dict[str, Any],
    ) -> dict[str, Any] | None:
        return _authoritative_target_asset(
            authority,
            node_id=str(intent.get("node_id") or ""),
            action=str(intent.get("action") or ""),
        )

    def _materialize_target_intent_locked(
        self,
        intent_id: str,
        authority: dict[str, Any],
        *,
        local_date: str | None = None,
        planned_position: int | None = None,
        source_next_step_decision_id: str = "",
        preserve_current_step: bool = False,
    ) -> dict[str, Any]:
        target_local_date = local_date or date.today().isoformat()
        intent_row = self.conn.execute(
            "select * from learning_target_intents where id = ?",
            (intent_id,),
        ).fetchone()
        if not intent_row:
            return {"status": "blocked", "reason": "target_intent_missing"}
        intent = dict(intent_row)
        if intent["status"] == "applied":
            flow = self._flow_by_id(str(intent.get("applied_flow_id") or ""))
            step = self.conn.execute(
                "select * from flow_steps where id = ?",
                (intent.get("applied_step_id") or "",),
            ).fetchone()
            if flow and step and step["flow_id"] == flow["id"]:
                return {
                    "status": "applied",
                    "intent": intent,
                    "flow_id": flow["id"],
                    "step_id": step["id"],
                    "reused": True,
                }
            return {"status": "blocked", "reason": "applied_target_lineage_missing"}
        if intent["status"] not in {"pending", "waiting_for_safe_boundary"}:
            return {"status": intent["status"], "reason": intent.get("reason") or ""}
        graph_version = str(authority["snapshot"]["graph_lineage"])
        if intent["graph_version"] != graph_version:
            self.conn.execute(
                """
                update learning_target_intents
                set status = 'blocked', reason = 'target_graph_version_stale', updated_at = ?
                where id = ? and status in ('pending','waiting_for_safe_boundary')
                """,
                (db.now_iso(), intent_id),
            )
            return {"status": "blocked", "reason": "target_graph_version_stale"}
        flow = None
        source_flow_id = str(intent.get("source_flow_id") or "")
        if source_flow_id:
            candidate = self._flow_by_id(source_flow_id)
            if candidate and candidate["status"] not in TERMINAL_FLOW_STATUSES:
                flow = candidate
        if flow is None:
            flow = self._active_flow(target_local_date)
        current_step = None
        if flow and flow["current_step_id"]:
            current_step = self.conn.execute(
                "select * from flow_steps where id = ?",
                (flow["current_step_id"],),
            ).fetchone()
        status_by_node = {
            str(row["node_id"]): str(row["status_code"])
            for row in db.authoritative_learner_node_status_rows(
                self.conn,
                graph_version=str(authority["snapshot"]["graph_lineage"]),
                question_bank_version=str(
                    authority["assessment"]["ledger"]["question_bank_version"]
                ),
            )
        }
        qualification = qualify_knowledge_target_action(
            self.conn,
            authority,
            node_id=str(intent["node_id"]),
            action=str(intent["action"]),
            status_by_node=status_by_node,
            source_step=current_step,
            preserve_current_step=preserve_current_step,
        )
        if not qualification["enabled"]:
            self.conn.execute(
                """
                update learning_target_intents
                set status = 'blocked', reason = ?, updated_at = ?
                where id = ? and status in ('pending','waiting_for_safe_boundary')
                """,
                (qualification["reason_code"], db.now_iso(), intent_id),
            )
            return {
                "status": "blocked",
                "reason": qualification["reason_code"],
                "message": qualification["disabled_reason"],
            }
        if qualification["result_behavior"] == "wait_for_safe_boundary":
            self.conn.execute(
                """
                update learning_target_intents
                set status = 'waiting_for_safe_boundary',
                    reason = 'current_assessment_must_finish', updated_at = ?
                where id = ? and status in ('pending','waiting_for_safe_boundary')
                """,
                (db.now_iso(), intent_id),
            )
            return {"status": "waiting_for_safe_boundary", "reason": "current_assessment_must_finish"}
        asset = qualification["asset"]
        action = str(intent["action"])
        if flow is None:
            flow = self._create_daily_flow(target_local_date, graph_version)
        flow_dict = dict(flow)
        question = asset["question"]
        contract = asset["contract"]
        now = db.now_iso()
        position = int(
            planned_position
            if planned_position is not None
            else self.conn.execute(
                "select count(*) from flow_steps where flow_id = ?",
                (flow_dict["id"],),
            ).fetchone()[0]
            + 1
        )
        step_type = "worked_example" if action == "learn" else ("micro_check" if action == "review" else "question")
        initial_status = "planned" if preserve_current_step else "selected"
        if current_step and not preserve_current_step and current_step["status"] in {
            "selected", "displayed", "blocked"
        }:
            self.conn.execute(
                """
                update flow_steps
                set status = 'superseded', updated_at = ?
                where id = ? and status in ('selected','displayed','blocked')
                  and superseded_by_step_id is null
                """,
                (now, current_step["id"]),
            )
        step_id = self._create_question_step(
            flow_id=flow_dict["id"],
            position=position,
            graph_version=graph_version,
            question=question,
            review_record_id=asset["review_record_id"],
            selection_reason={
                "reason": "knowledge_map_target_intent",
                "target_intent_id": intent_id,
                "target_action": action,
                "source_next_step_decision_id": source_next_step_decision_id or None,
            },
            candidate_packet={},
            support_hint=(
                "先看清这个知识点的关键关系，再完成一题小检查。"
                if action == "learn"
                else "按你平时的方式完成，系统会根据过程判断下一步。"
            ),
            step_type=step_type,
            answer_input_mode="none" if action == "learn" else "text_photo",
            initial_status=initial_status,
            answer_contract=contract,
        )
        if current_step and not preserve_current_step and current_step["id"] != step_id:
            self.conn.execute(
                """
                update flow_steps
                set superseded_by_step_id = ?, updated_at = ?
                where id = ? and status = 'superseded'
                """,
                (step_id, now, current_step["id"]),
            )
        if not preserve_current_step:
            self.conn.execute(
                """
                update daily_flows
                set mode = ?, status = ?, current_step_id = ?,
                    graph_version = ?, question_bank_version = ?,
                    assessment_policy_version = 'v5.1', blocked_reason = '',
                    flow_revision = flow_revision + 1, updated_at = ?
                where id = ? and status not in ('completed','superseded')
                """,
                (
                    "new_knowledge" if action == "learn" else "review_old_knowledge",
                    "learning_new" if action == "learn" else "reviewing",
                    step_id,
                    graph_version,
                    authority["assessment"]["ledger"]["question_bank_version"],
                    now,
                    flow_dict["id"],
                ),
            )
        updated = self.conn.execute(
            """
            update learning_target_intents
            set status = 'applied', applied_flow_id = ?, applied_step_id = ?,
                reason = '', updated_at = ?
            where id = ? and status in ('pending','waiting_for_safe_boundary')
            """,
            (flow_dict["id"], step_id, now, intent_id),
        )
        if updated.rowcount != 1:
            canonical = self.conn.execute(
                "select * from learning_target_intents where id = ?",
                (intent_id,),
            ).fetchone()
            if not canonical or canonical["status"] != "applied":
                raise ValueError("target intent did not converge to one applied step")
        return {
            "status": "applied",
            "intent": dict(
                self.conn.execute(
                    "select * from learning_target_intents where id = ?",
                    (intent_id,),
                ).fetchone()
            ),
            "flow_id": flow_dict["id"],
            "step_id": step_id,
            "reused": False,
        }

    def recover_target_intents(self, *, local_date: str | None = None) -> dict[str, Any]:
        from . import knowledge_map

        savepoint, nested = knowledge_map._begin_write(self.conn, "recover_target")
        try:
            authority = knowledge_map.KnowledgeMapService(
                self.conn,
                project_root=self.project_root,
            )._runtime_authority()
            intent = knowledge_map.newest_pending_intent(
                self.conn,
                child_key=self.child_key,
                graph_version=authority["snapshot"]["graph_lineage"],
            )
            if intent and intent.get("status") == "waiting_for_safe_boundary":
                source_flow = self._flow_by_id(str(intent.get("source_flow_id") or ""))
                source_step = (
                    self.conn.execute(
                        "select * from flow_steps where id = ?",
                        (source_flow["current_step_id"],),
                    ).fetchone()
                    if source_flow and source_flow["current_step_id"]
                    else None
                )
                if source_step and source_step["status"] == "analyzing":
                    active_jobs = self.conn.execute(
                        """
                        select count(*) from background_jobs
                        where flow_step_id = ?
                          and status in ('queued','retry','claimed','running')
                        """,
                        (source_step["id"],),
                    ).fetchone()[0]
                    if not active_jobs:
                        self.conn.execute(
                            """
                            update learning_target_intents
                            set status = 'blocked',
                                reason = 'analyzing_step_has_no_recoverable_job',
                                updated_at = ?
                            where id = ? and status = 'waiting_for_safe_boundary'
                            """,
                            (db.now_iso(), intent["id"]),
                        )
                        knowledge_map._finish_write(self.conn, savepoint, nested)
                        return {
                            "status": "blocked",
                            "reason": "analyzing_step_has_no_recoverable_job",
                        }
            result = (
                {"status": "none"}
                if intent is None
                else self._materialize_target_intent_locked(
                    intent["id"],
                    authority,
                    local_date=local_date,
                )
            )
            knowledge_map._finish_write(self.conn, savepoint, nested)
            return result
        except Exception:
            knowledge_map._rollback_write(self.conn, savepoint, nested)
            raise

    def _plan_pending_target_after_assessment_locked(
        self,
        *,
        flow: dict[str, Any],
        source_step_id: str,
        source_attempt_id: str,
        source_validation_ids: list[str],
        source_mastery_ids: list[str],
        report_label: str,
        planned_position: int,
    ) -> dict[str, Any] | None:
        from . import knowledge_map

        try:
            authority = knowledge_map.KnowledgeMapService(
                self.conn,
                project_root=self.project_root,
            )._runtime_authority()
        except knowledge_map.KnowledgeMapError:
            return None
        intent = knowledge_map.newest_pending_intent(
            self.conn,
            child_key=self.child_key,
            graph_version=authority["snapshot"]["graph_lineage"],
        )
        if not intent:
            return None
        status_by_node = {
            str(row["node_id"]): str(row["status_code"])
            for row in db.authoritative_learner_node_status_rows(
                self.conn,
                graph_version=str(authority["snapshot"]["graph_lineage"]),
                question_bank_version=str(
                    authority["assessment"]["ledger"]["question_bank_version"]
                ),
            )
        }
        source_step = self.conn.execute(
            "select * from flow_steps where id = ?",
            (source_step_id,),
        ).fetchone()
        qualification = qualify_knowledge_target_action(
            self.conn,
            authority,
            node_id=str(intent["node_id"]),
            action=str(intent["action"]),
            status_by_node=status_by_node,
            source_step=source_step,
            preserve_current_step=True,
        )
        if not qualification["enabled"]:
            self.conn.execute(
                """
                update learning_target_intents
                set status = 'blocked', reason = ?, updated_at = ?
                where id = ? and status in ('pending','waiting_for_safe_boundary')
                """,
                (qualification["reason_code"], db.now_iso(), intent["id"]),
            )
            return {
                "status": "blocked",
                "reason": qualification["reason_code"],
                "message": qualification["disabled_reason"],
            }
        decision = self._record_next_step_decision(
            flow=flow,
            action=f"knowledge_target_{intent['action']}",
            report_label=report_label,
            source_step_id=source_step_id,
            source_attempt_ids=[source_attempt_id],
            source_validation_ids=source_validation_ids,
            source_mastery_ids=source_mastery_ids,
            provider_mode="deterministic_runtime",
            reason="孩子已选择新的知识目标；本题评估和掌握写入完成后优先切换。",
            target_node_id=str(intent["node_id"]),
        )
        result = self._materialize_target_intent_locked(
            intent["id"],
            authority,
            planned_position=planned_position,
            source_next_step_decision_id=decision["id"],
            preserve_current_step=True,
        )
        return {**result, "decision": decision}

    def _validated_interaction_response_for_submission(
        self,
        package: dict[str, Any],
        command: CurrentStepSubmission,
    ) -> dict[str, Any]:
        schema = question_bank.normalize_question_interaction_schema(package.get("interaction_schema"))
        if not schema or schema.get("type") == "short_text":
            return {}
        if not command.interaction_response:
            raise ChildSafeRuntimeError("先完成这一步的填空、选择或算式。", status=400, child_action="继续作答")
        response = command.interaction_response
        response_type = str(response.get("type") or schema.get("type") or "")
        if response_type != schema["type"]:
            raise ChildSafeRuntimeError("这一步的作答格式变了，请刷新后继续。", status=400, child_action="刷新")
        normalized: dict[str, Any] = {
            "schema_version": schema.get("schema_version") or question_bank.QUESTION_INTERACTION_SCHEMA_VERSION,
            "type": schema["type"],
            "schema_hash": db._digest_json(schema),
            "fields": [],
            "selected_choices": [],
            "formula": {},
            "explanation_text": _child_safe_text(response.get("explanation_text") or "", "", limit=1200),
        }
        if schema["type"] == "fill_blank":
            values = response.get("values") if isinstance(response.get("values"), dict) else {}
            if not values and isinstance(response.get("fields"), dict):
                values = response.get("fields")
            for field in schema.get("fields") or []:
                value = _child_safe_text(values.get(field["id"]) if isinstance(values, dict) else "", "", limit=240)
                if value:
                    normalized["fields"].append({
                        "id": field["id"],
                        "label": field["label"],
                        "value": value,
                    })
            if not normalized["fields"]:
                raise ChildSafeRuntimeError("至少先填一个空，或者点卡住。", status=400, child_action="继续作答")
        elif schema["type"] in {"single_choice", "multi_choice"}:
            raw_selected = response.get("selected_choices")
            if raw_selected is None:
                raw_selected = response.get("choices")
            if isinstance(raw_selected, str):
                raw_selected = [raw_selected]
            if not isinstance(raw_selected, list):
                raw_selected = []
            allowed = {choice["id"]: choice for choice in schema.get("choices") or []}
            seen: set[str] = set()
            for value in raw_selected:
                choice_id = str(value or "").strip()
                if choice_id not in allowed:
                    raise ChildSafeRuntimeError("选项状态不对，请刷新后重新选择。", status=400, child_action="刷新")
                if choice_id in seen:
                    continue
                seen.add(choice_id)
                normalized["selected_choices"].append({
                    "id": choice_id,
                    "label": allowed[choice_id]["label"],
                })
            if schema["type"] == "single_choice" and len(normalized["selected_choices"]) > 1:
                raise ChildSafeRuntimeError("这一步只能选一个答案。", status=400, child_action="重新选择")
            if not normalized["selected_choices"]:
                raise ChildSafeRuntimeError("先选一个答案，或者点卡住。", status=400, child_action="继续作答")
        elif schema["type"] == "formula_input":
            value = _child_safe_text(
                response.get("formula") if response.get("formula") is not None else response.get("formula_value"),
                "",
                limit=360,
            )
            if not value:
                raise ChildSafeRuntimeError("先写出算式或关系，或者点卡住。", status=400, child_action="继续作答")
            normalized["formula"] = {
                "label": schema.get("formula_label") or schema.get("title") or "算式",
                "value": value,
            }
        if package.get("requires_explanation") and not normalized["explanation_text"]:
            label = _child_safe_text(schema.get("explanation_label") or "说明理由", "说明理由", limit=40)
            raise ChildSafeRuntimeError(f"请先{label}。", status=400, child_action="补充说明")
        return normalized

    def _answer_text_from_interaction_response(self, response: dict[str, Any]) -> str:
        if not response:
            return ""
        labels = {
            "fill_blank": "填空",
            "single_choice": "单选",
            "multi_choice": "多选",
            "formula_input": "公式输入",
        }
        lines = [f"结构化作答：{labels.get(str(response.get('type') or ''), '作答')}"]
        for field in response.get("fields") or []:
            lines.append(f"{field.get('label')}：{field.get('value')}")
        for choice in response.get("selected_choices") or []:
            lines.append(f"选择：{choice.get('label')}")
        formula = response.get("formula") if isinstance(response.get("formula"), dict) else {}
        if formula.get("value"):
            lines.append(f"{formula.get('label') or '算式'}：{formula.get('value')}")
        if response.get("explanation_text"):
            lines.append(f"补充说明：{response.get('explanation_text')}")
        return "\n".join(line for line in lines if str(line or "").strip())

    def persist_child_response(self, command: CurrentStepSubmission) -> dict[str, Any]:
        if not command.step_handle:
            raise ChildSafeRuntimeError("这一步已经过期，请刷新后继续。")
        if not command.client_idempotency_key:
            raise ChildSafeRuntimeError("这次提交没有保存标记，请重新保存一次。")
        if not command.answer_text and not command.answer_photo_data_url and not command.stuck and not command.interaction_response:
            raise ChildSafeRuntimeError("先写一点想法，或上传纸面答案。", status=400, child_action="补充答案")
        step = self.conn.execute(
            """
            select *
            from flow_steps
            where step_handle = ? and position = ?
            limit 1
            """,
            (command.step_handle, command.position),
        ).fetchone()
        if not step or step["status"] not in {"selected", "displayed", "analyzing"}:
            raise ChildSafeRuntimeError("当前没有可以提交的学习步骤，请刷新后继续。")
        step_dict = dict(step)
        if step_dict["step_type"] not in {"question", "micro_check", "standard_check", "variant_check", "clarify_evidence"}:
            raise ChildSafeRuntimeError("这一步不需要保存答案，请点继续。", status=400, child_action="继续")
        package = db.json_load(step_dict.get("prompt_package_json"), {})
        allowed_modes = set(_allowed_response_modes_for_step(step_dict.get("step_type"), package))
        has_text = bool(command.answer_text)
        has_photo = bool(command.answer_photo_data_url)
        if has_photo and not (allowed_modes & {"photo", "text_photo", "clarification"}):
            raise ChildSafeRuntimeError("这一步先不用拍照，请用文字完成。", status=400, child_action="改用文字")
        if has_text and not (allowed_modes & {"text", "text_photo", "clarification"}):
            raise ChildSafeRuntimeError("这一步不需要写答案，请按页面按钮继续。", status=400, child_action="继续")
        explicit_stuck_text = (
            not command.stuck
            and not has_photo
            and _is_explicit_stuck_text(command.answer_text)
        )
        is_stuck_submission = command.stuck or explicit_stuck_text
        interaction_response = {} if is_stuck_submission else self._validated_interaction_response_for_submission(package, command)
        has_interaction = bool(interaction_response)
        if is_stuck_submission and "stuck" not in allowed_modes:
            raise ChildSafeRuntimeError("这一步不能这样提交卡住，请刷新后继续。", status=400, child_action="刷新")
        if command.interaction_response and "interaction" not in allowed_modes:
            raise ChildSafeRuntimeError("这一步不需要这样作答，请按页面要求提交。", status=400, child_action="调整答案")
        if has_text and has_photo and "text_photo" not in allowed_modes and "clarification" not in allowed_modes:
            raise ChildSafeRuntimeError("这一步不能同时提交文字和照片，请按页面要求提交。", status=400, child_action="调整答案")
        if not step_dict.get("question_id") or not step_dict.get("node_id"):
            raise ChildSafeRuntimeError("这一步还没准备好，请刷新后继续。")
        try:
            with self.conn:
                step_dict = self._refresh_step_review_record_if_needed(step_dict)
                duplicate = self._active_attempt_for_step(
                    step_dict["id"],
                    client_idempotency_key=command.client_idempotency_key,
                )
                if duplicate:
                    self._ensure_answer_analysis_job_for_attempt(step_dict, duplicate["id"], source="duplicate_submit")
                    self._mark_step_analyzing(step_dict["id"], duplicate["id"], step_dict["flow_id"])
                    return self.project_child_state(self._flow_by_id(step_dict["flow_id"]))
                existing_attempt = self._active_attempt_for_step(step_dict["id"])
                if existing_attempt:
                    self._ensure_answer_analysis_job_for_attempt(step_dict, existing_attempt["id"], source="existing_active_attempt")
                    self._mark_step_analyzing(step_dict["id"], existing_attempt["id"], step_dict["flow_id"])
                    return self.project_child_state(self._flow_by_id(step_dict["flow_id"]))

                answer_source = (
                    "v3_stuck" if is_stuck_submission
                    else "v3_interaction" if has_interaction
                    else "v3_photo" if command.answer_photo_data_url and not command.answer_text
                    else "v3_text"
                )
                canonical_interaction_answer = self._answer_text_from_interaction_response(interaction_response)
                answer_raw = canonical_interaction_answer if has_interaction else (
                    command.answer_text
                    or ("我卡住了，需要先讲第一步。" if is_stuck_submission else "已上传纸面答案。")
                )
                review_meta = {
                    "status": "queued",
                    "needs_ai_review": True,
                    "stuck": is_stuck_submission,
                    "has_photo": bool(command.answer_photo_data_url),
                    "has_interaction_response": has_interaction,
                    "interaction_schema_hash": interaction_response.get("schema_hash", ""),
                    "answer_photo_name": command.answer_photo_name,
                    "route": "answer_analysis",
                }
                if has_interaction and command.answer_text:
                    review_meta["client_rendered_answer_text"] = _child_safe_text(command.answer_text, "", limit=1200)
                attempt_id = db.record_attempt(
                    self.conn,
                    session_id=self._legacy_session_id_for_flow(step_dict["flow_id"]),
                    question_id=step_dict["question_id"],
                    node_id=step_dict["node_id"],
                    result="submitted",
                    score_points=0,
                    max_points=2,
                    error_tags=[],
                    answer_raw=answer_raw,
                    parent_note="v3 current-step submission queued for asynchronous answer analysis.",
                    review_meta=review_meta,
                    interaction_response=interaction_response,
                    explanation_score=None,
                    grading_status="pending_review",
                    question_bank_version=step_dict["question_bank_version"],
                    commit=False,
                )
                attachment_ids: list[str] = []
                written_paths: list[Path] = []
                try:
                    if command.answer_photo_data_url:
                        attachment, path = self._save_answer_photo(
                            attempt_id=attempt_id,
                            original_name=command.answer_photo_name,
                            data_url=command.answer_photo_data_url,
                        )
                        attachment_ids.append(attachment["id"])
                        written_paths.append(path)
                    self.conn.execute(
                        """
                        update attempts
                        set flow_step_id = ?,
                            graph_version = ?,
                            question_bank_version = ?,
                            attempt_version = 1,
                            analysis_version = 0,
                            analysis_status = 'missing',
                            client_idempotency_key = ?,
                            answer_source = ?,
                            attachment_ids_json = ?,
                            review_record_id = ?,
                            review_meta_json = ?
                        where id = ?
                        """,
                        (
                            step_dict["id"],
                            step_dict["graph_version"],
                            step_dict["question_bank_version"],
                            command.client_idempotency_key,
                            answer_source,
                            db.json_dump(attachment_ids),
                            step_dict["review_record_id"],
                            db.json_dump({**review_meta, "attachment_ids": attachment_ids}),
                            attempt_id,
                        ),
                    )
                    evidence_digest = db._digest_json({
                        "attempt_id": attempt_id,
                        "attempt_version": 1,
                        "flow_step_id": step_dict["id"],
                        "step_revision": int(step_dict["step_revision"] or 1),
                        "question_id": step_dict["question_id"],
                        "review_record_id": step_dict["review_record_id"],
                        "answer_source": answer_source,
                        "answer_raw": answer_raw,
                        "interaction_response": interaction_response,
                        "attachment_ids": attachment_ids,
                        "client_idempotency_key": command.client_idempotency_key,
                    })
                    self.conn.execute(
                        "update attempts set evidence_digest_sha256 = ? where id = ?",
                        (evidence_digest, attempt_id),
                    )
                    if is_stuck_submission and step_dict["step_type"] != "clarify_evidence":
                        self._fast_track_stuck_submission(
                            step_dict=step_dict,
                            attempt_id=attempt_id,
                            answer_raw=answer_raw,
                        )
                    else:
                        job_queue.JobQueue(self.conn).enqueue(
                            "answer_analysis",
                            f"v5:answer_analysis:{attempt_id}:1:{evidence_digest}",
                            {
                                "payload_schema_version": job_queue.V5_JOB_PAYLOAD_SCHEMA_VERSION,
                                "legacy_session_id": self._legacy_session_id_for_flow(step_dict["flow_id"]),
                                "flow_id": step_dict["flow_id"],
                                "flow_revision": int(self._flow_by_id(step_dict["flow_id"])["flow_revision"] or 1),
                                "flow_step_id": step_dict["id"],
                                "step_revision": int(step_dict["step_revision"] or 1),
                                "attempt_id": attempt_id,
                                "attempt_version": 1,
                                "analysis_version": 0,
                                "graph_version": step_dict["graph_version"],
                                "question_bank_version": step_dict["question_bank_version"],
                                "question_id": step_dict["question_id"],
                                "review_record_id": step_dict["review_record_id"],
                                "interaction_response": interaction_response,
                                "interaction_schema_hash": interaction_response.get("schema_hash", ""),
                                "provider_mode": _provider_mode(model_router.answer_analysis_route()),
                                "route_meta": {"route": "answer_analysis", "source": "v5_current_step_submit"},
                            },
                            commit=False,
                        )
                        self._mark_step_analyzing(step_dict["id"], attempt_id, step_dict["flow_id"])
                except Exception:
                    for path in written_paths:
                        path.unlink(missing_ok=True)
                    raise
        except sqlite3.IntegrityError as exc:
            existing_attempt = self._active_attempt_for_step(step_dict["id"])
            if existing_attempt:
                with self.conn:
                    self._ensure_answer_analysis_job_for_attempt(step_dict, existing_attempt["id"], source="integrity_recovery")
                    self._mark_step_analyzing(step_dict["id"], existing_attempt["id"], step_dict["flow_id"])
                return self.project_child_state(self._flow_by_id(step_dict["flow_id"]))
            raise ChildSafeRuntimeError("答案已经在保存中，请稍后刷新。") from exc
        return self.project_child_state(self._flow_by_id(step_dict["flow_id"]))

    def _refresh_step_review_record_if_needed(self, step_dict: dict[str, Any]) -> dict[str, Any]:
        question_id = str(step_dict.get("question_id") or "")
        current_review_record_id = str(step_dict.get("review_record_id") or "")
        if not question_id:
            return step_dict
        try:
            question = db.get_question(self.conn, question_id)
        except KeyError:
            return step_dict
        if current_review_record_id and db.question_review_record_allows_active_use(
            self.conn,
            question,
            current_review_record_id,
        ):
            return step_dict
        rows = self.conn.execute(
            """
            select id
            from question_review_records
            where question_id = ?
              and item_version = ?
              and source_type = ?
              and review_status = 'approved'
              and active_eligible = 1
            order by reviewed_at desc, id desc
            """,
            (question["id"], question.get("item_version"), question.get("source_type")),
        ).fetchall()
        replacement = ""
        for row in rows:
            if db.question_review_record_allows_active_use(self.conn, question, row["id"]):
                replacement = row["id"]
                break
        if not replacement:
            return step_dict
        self.conn.execute(
            "update flow_steps set review_record_id = ?, updated_at = ? where id = ?",
            (replacement, db.now_iso(), step_dict["id"]),
        )
        return {**step_dict, "review_record_id": replacement}

    def _fast_track_stuck_submission(
        self,
        *,
        step_dict: dict[str, Any],
        attempt_id: str,
        answer_raw: str,
    ) -> None:
        """Handle an explicit child-stuck signal without blocking on model calls."""
        if assessment_store.bound_active_contract_for_flow_step(
            self.conn, step_dict["id"]
        ) is not None:
            self._fast_track_v51_stuck_submission(
                step_dict=step_dict,
                attempt_id=attempt_id,
            )
            return
        provider_mode = "deterministic_runtime"
        flow = dict(self._flow_by_id(step_dict["flow_id"]))
        question = db.get_question(self.conn, step_dict["question_id"])
        analysis = self._stuck_answer_analysis(question=question, answer_raw=answer_raw)
        review_meta = {
            "status": "graded",
            "stuck": True,
            "provider_mode": provider_mode,
            "route": "stuck_fast_path",
            "confidence": 1.0,
            "reason": "孩子明确表示不会或卡住；直接进入讲解修复，不等待完整模型批阅链。",
        }
        db.grade_attempt(
            self.conn,
            attempt_id=attempt_id,
            result="wrong",
            score_points=0,
            max_points=2,
            error_tags=["modeling_or_reading", "process_habit"],
            answer_raw=None,
            parent_note="孩子明确表示卡住，系统走确定性快路径进入讲解修复。",
            answer_analysis=analysis,
            review_meta=review_meta,
            explanation_score=0,
            blocking_evidence=False,
            commit=False,
        )
        self.conn.execute(
            """
            update attempts
            set analysis_status = 'valid',
                analysis_version = analysis_version + 1
            where id = ?
            """,
            (attempt_id,),
        )
        self.conn.execute(
            "update flow_steps set attempt_id = ?, updated_at = ? where id = ?",
            (attempt_id, db.now_iso(), step_dict["id"]),
        )
        graded = db.get_attempt(self.conn, attempt_id)
        answer_run = self._record_deterministic_agent_run(
            agent_key="answer_analysis_agent",
            session_id=graded["session_id"],
            phase="answer_analysis",
            trigger=f"v5_answer_analysis_stuck_fast_path:{attempt_id}:{graded.get('analysis_version', 1)}",
            input_refs={
                "attempt_id": attempt_id,
                "question_id": question["id"],
                "flow_id": step_dict["flow_id"],
                "flow_step_id": step_dict["id"],
                "stuck_fast_path": True,
            },
            output={
                "result": "wrong",
                "answer_analysis": analysis,
                "provider_mode": provider_mode,
            },
            confidence=1.0,
            use_v5_contract=True,
        )
        validation = evidence_gate.EvidenceGate(
            self.conn,
            current_graph_version=self.graph.current_graph_version(),
            current_question_bank_version=str(graded.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION),
        ).validate_attempt(
            attempt_id,
            analysis_version=int(graded.get("analysis_version") or 1),
            provider_mode=provider_mode,
            answer_analysis_agent_run_id=answer_run["id"],
            commit=False,
        )
        evaluation = self._record_evaluation_update(
            attempt=graded,
            validation=validation,
            provider_mode=provider_mode,
            evaluation_output={
                "mastery_recommendation": "weak",
                "reason": "孩子明确卡住，说明当前节点不能直接通过；先做针对性讲解，再用小检查确认。",
                "planner_signal": {
                    "next_evidence_goal": "targeted_reteach",
                    "needs_teaching_before_next": True,
                    "needs_prerequisite_probe": False,
                    "target_gap_dimensions": ["model_or_relation", "steps", "check_or_explanation"],
                },
            },
        )
        decision = self._record_next_step_decision(
            flow=flow,
            action="micro_teach",
            report_label=validation.predicate.report_label,
            source_step_id=step_dict["id"],
            source_attempt_ids=[attempt_id],
            source_validation_ids=[validation.validation_id] if validation.validation_id else [],
            source_mastery_ids=[evaluation.get("mastery_decision_id")] if evaluation.get("mastery_decision_id") else [],
            provider_mode=provider_mode,
            reason="孩子明确说卡住，直接讲第一处断点，避免等待完整模型批阅链。",
            target_node_id=graded["node_id"],
        )
        step_count = self.conn.execute(
            "select count(*) from flow_steps where flow_id = ?",
            (step_dict["flow_id"],),
        ).fetchone()[0]
        now = db.now_iso()
        self.conn.execute(
            """
            update flow_steps
            set status = 'completed',
                attempt_id = ?,
                updated_at = ?
            where id = ?
            """,
            (attempt_id, now, step_dict["id"]),
        )
        teaching_step_id = self._create_teaching_repair_step(
            flow=flow,
            source_attempt=graded,
            source_step_id=step_dict["id"],
            source_next_step_decision_id=decision["id"],
            position=int(step_count) + 1,
        )
        self.conn.execute(
            """
            update daily_flows
            set status = 'reviewing',
                current_step_id = ?,
                flow_revision = flow_revision + 1,
                updated_at = ?
            where id = ?
            """,
            (teaching_step_id, now, step_dict["flow_id"]),
        )

    def _fast_track_v51_stuck_submission(
        self,
        *,
        step_dict: dict[str, Any],
        attempt_id: str,
    ) -> None:
        flow = dict(self._flow_by_id(step_dict["flow_id"]))
        review_meta = {
            "status": "support_requested",
            "stuck": True,
            "provider_mode": "deterministic_runtime",
            "route": "v5.1_stuck_support",
            "needs_ai_review": False,
            "reason": "explicit_child_stuck_signal",
        }
        self.conn.execute(
            """
            update attempts
            set grading_status = 'not_scored',
                analysis_status = 'not_required',
                result = 'submitted',
                score_points = 0,
                max_points = 2,
                review_meta_json = ?,
                answer_analysis_json = '{}'
            where id = ?
            """,
            (db.json_dump(review_meta), attempt_id),
        )
        attempt = db.get_attempt(self.conn, attempt_id)
        decision = self._record_next_step_decision(
            flow=flow,
            action="micro_teach",
            report_label="support_requested",
            source_step_id=step_dict["id"],
            source_attempt_ids=[attempt_id],
            source_validation_ids=[],
            source_mastery_ids=[],
            provider_mode="deterministic_runtime",
            reason="孩子明确表示不会；本次不评分、不形成掌握证据，直接提供第一步支持。",
            target_node_id=attempt["node_id"],
        )
        step_count = self.conn.execute(
            "select count(*) from flow_steps where flow_id = ?",
            (step_dict["flow_id"],),
        ).fetchone()[0]
        now = db.now_iso()
        self.conn.execute(
            """
            update flow_steps
            set status = 'completed', attempt_id = ?, updated_at = ?
            where id = ?
            """,
            (attempt_id, now, step_dict["id"]),
        )
        teaching_step_id = self._create_teaching_repair_step(
            flow=flow,
            source_attempt=attempt,
            source_step_id=step_dict["id"],
            source_next_step_decision_id=decision["id"],
            position=int(step_count) + 1,
        )
        self.conn.execute(
            """
            update daily_flows
            set status = 'reviewing', current_step_id = ?,
                flow_revision = flow_revision + 1, updated_at = ?
            where id = ?
            """,
            (teaching_step_id, now, step_dict["flow_id"]),
        )

    def _stuck_answer_analysis(self, *, question: dict[str, Any], answer_raw: str) -> dict[str, Any]:
        solution_steps = [
            str(step).strip()
            for step in (question.get("solution_steps") or [])
            if str(step).strip()
        ] or [
            "先把题目条件改写成一个关系。",
            "再确定第一步要用的规则或模型。",
            "最后完成计算并检查结果是否符合题意。",
        ]
        answer = str(answer_raw or "我卡住了。").strip()
        process_gap = "孩子明确表示不会或卡住，尚未形成可复盘的模型、步骤和检验。"
        analysis = {
            "agent_key": "answer_analysis_agent",
            "optimal_answer": str(question.get("expected_answer") or "见题目参考解法"),
            "optimal_solution_steps": solution_steps,
            "child_answer_summary": f"孩子提交了卡住信号：{answer[:120]}",
            "comparison": [
                {"dimension": "final_answer", "status": "missing", "detail": "没有给出可判断的最终答案。"},
                {"dimension": "model_or_relation", "status": "missing", "detail": "没有写出题目中的核心关系或模型。"},
                {"dimension": "steps", "status": "missing", "detail": "没有形成可复盘的解题步骤。"},
                {"dimension": "symbols_units", "status": "missing", "detail": "没有可检查的符号、单位或表达过程。"},
                {"dimension": "check_or_explanation", "status": "missing", "detail": "没有写出检验或解释。"},
            ],
            "alternative_solutions": [],
            "process_gap": process_gap,
            "no_gap_observed": False,
            "teaching_explanation": "先不用硬算。第一步只要把题目在问什么、已知什么、要用哪条规则说清楚。",
            "next_child_prompt": "看完讲解后，先做一题很小的检查：只写第一步关系或规则。",
        }
        analysis["evaluation_support"] = db.derive_answer_evaluation_support(analysis)
        return analysis

    def continue_current_step(self, *, step_handle: str, position: int, stuck: bool = False) -> dict[str, Any]:
        step_handle = str(step_handle or "").strip()
        if not step_handle:
            raise ChildSafeRuntimeError("这一步已经过期，请刷新后继续。")
        step = self.conn.execute(
            """
            select *
            from flow_steps
            where step_handle = ? and position = ?
            limit 1
            """,
            (step_handle, int(position)),
        ).fetchone()
        if not step:
            raise ChildSafeRuntimeError("当前没有可以继续的学习步骤，请刷新后继续。")
        selection_reason = db.json_load(step["selection_reason_json"], {})
        if step["status"] == "completed" and selection_reason.get("reason") == "v5.1_assessment_feedback":
            return self.project_child_state(self._flow_by_id(step["flow_id"]))
        if step["status"] not in {"selected", "displayed"}:
            raise ChildSafeRuntimeError("当前没有可以继续的学习步骤，请刷新后继续。")
        if step["step_type"] not in {"teaching_repair", "worked_example"}:
            raise ChildSafeRuntimeError("这一步需要先保存答案。", status=400, child_action="保存答案")
        with self.conn:
            flow = dict(self._flow_by_id(step["flow_id"]))
            self.conn.execute(
                "update flow_steps set status = 'completed', updated_at = ? where id = ?",
                (db.now_iso(), step["id"]),
            )
            if selection_reason.get("reason") == "v5.1_assessment_feedback":
                decision_id = str(selection_reason.get("planned_next_step_decision_id") or "")
                next_step = self._visible_step_for_next_step_decision(flow["id"], decision_id)
                if next_step and next_step["id"] != step["id"]:
                    self.conn.execute(
                        "update flow_steps set status = 'selected', updated_at = ? where id = ?",
                        (db.now_iso(), next_step["id"]),
                    )
                    self.conn.execute(
                        """
                        update daily_flows
                        set status = 'reviewing', current_step_id = ?,
                            flow_revision = flow_revision + 1, updated_at = ?
                        where id = ? and status not in ('completed','superseded')
                        """,
                        (next_step["id"], db.now_iso(), flow["id"]),
                    )
                else:
                    self._materialize_blocked_or_summary(
                        flow["id"],
                        reason="no_planned_step_after_assessment_feedback",
                    )
                return self.project_child_state(self._flow_by_id(flow["id"]))
            if stuck:
                db.record_teaching_step_event(
                    self.conn,
                    flow_id=flow["id"],
                    flow_step_id=step["id"],
                    event_type=f"{step['step_type']}_stuck",
                    event_payload={
                        "step_type": step["step_type"],
                        "source_next_step_decision_id": selection_reason.get("source_next_step_decision_id", ""),
                        "new_knowledge_phase": selection_reason.get("new_knowledge_phase", ""),
                    },
                    evidence_status="stuck",
                    source_agent_run_id=str(selection_reason.get("teaching_agent_run_id") or ""),
                    commit=False,
                )
                summary_id = self._ensure_daily_summary(
                    flow,
                    reason="child_still_stuck_after_teaching",
                    target_flow_revision=int(flow.get("flow_revision") or 1) + 1,
                )
                self.conn.execute(
                    """
                    update daily_flows
                    set status = 'completed',
                        summary_id = ?,
                        current_step_id = null,
                        flow_revision = flow_revision + 1,
                        updated_at = ?
                    where id = ?
                    """,
                    (summary_id, db.now_iso(), flow["id"]),
                )
                return self.project_child_state(self._flow_by_id(flow["id"]))
            source_attempt_id = str(db.json_load(step["selection_reason_json"], {}).get("source_attempt_id") or "")
            attempt = db.get_attempt(self.conn, source_attempt_id) if source_attempt_id else None
            if attempt:
                next_selection = self._next_selection_after_attempt(flow, attempt=attempt)
            elif step["step_type"] == "worked_example":
                selected = self._select_question_for_node(
                    step["node_id"],
                    graph_version=flow["graph_version"],
                    flow_id=flow["id"],
                    flow_revision=int(flow.get("flow_revision") or 1) + 1,
                    reason={
                        "reason": "micro_check_after_worked_example",
                        "source_step_id": step["id"],
                        "source_node_id": step["node_id"],
                    },
                    preferred_kinds=["variant", "standard_example", "transfer_retest"],
                    selection_intent="partial_unstable",
                    next_evidence_goal="micro_check_after_worked_example",
                )
                next_selection = {
                    **selected,
                    "action": "micro_check_after_worked_example",
                    "reason": "看完例题后，用一题小检查确认第一步模型是否能自己写出来。",
                } if selected else None
            else:
                next_selection = None
            if not next_selection:
                summary_id = self._ensure_daily_summary(
                    flow,
                    reason="no_micro_check_after_teaching",
                    target_flow_revision=int(flow.get("flow_revision") or 1) + 1,
                )
                self.conn.execute(
                    """
                    update daily_flows
                    set status = 'completed',
                        summary_id = ?,
                        current_step_id = null,
                        flow_revision = flow_revision + 1,
                        updated_at = ?
                    where id = ?
                    """,
                    (summary_id, db.now_iso(), flow["id"]),
                )
                return self.project_child_state(self._flow_by_id(flow["id"]))
            decision = self._record_next_step_decision(
                flow=flow,
                action=next_selection["action"],
                report_label="inferred",
                source_step_id=step["id"],
                source_attempt_ids=[source_attempt_id] if source_attempt_id else [],
                source_validation_ids=[],
                provider_mode="deterministic_runtime",
                reason=f"教学后用一题小检查确认是否修住：{next_selection['reason']}",
                candidate_packet=next_selection.get("candidate_packet"),
                target_node_id=next_selection["question"]["node_id"],
            )
            position_next = int(self.conn.execute(
                "select count(*) from flow_steps where flow_id = ?",
                (flow["id"],),
            ).fetchone()[0]) + 1
            new_step_id = self._create_question_step(
                flow_id=flow["id"],
                position=position_next,
                graph_version=flow["graph_version"],
                question=next_selection["question"],
                review_record_id=next_selection["review_record_id"],
                selection_reason={
                    **(next_selection.get("selection_reason") or {}),
                    "source_next_step_decision_id": decision["id"],
                    "source_attempt_id": source_attempt_id,
                    "reason": "micro_check_after_teaching",
                    "new_knowledge_phase": "micro_check" if step["step_type"] == "worked_example" else "repair_check",
                },
                candidate_packet=next_selection.get("candidate_packet") or {},
                support_hint="刚才讲过的那一点先用上：写清关键关系，再做小检查。",
                step_type="micro_check",
                answer_input_mode="text",
            )
            self.conn.execute(
                """
                update daily_flows
                set status = 'reviewing',
                    current_step_id = ?,
                    flow_revision = flow_revision + 1,
                    updated_at = ?
                where id = ?
                """,
                (new_step_id, db.now_iso(), flow["id"]),
            )
        return self.project_child_state(self._flow_by_id(step["flow_id"]))

    def start_new_knowledge_from_checkpoint(self, *, client_day_key: str | None = None) -> dict[str, Any]:
        local_date = (client_day_key or date.today().isoformat())[:10]
        flow = self._active_flow(local_date)
        if not flow:
            raise ChildSafeRuntimeError("今天的学习记录暂时打不开，请刷新后继续。")
        if flow["status"] != "ready_for_new_knowledge":
            return self.project_child_state(flow)
        with self.conn:
            flow_dict = dict(flow)
            self.conn.execute(
                """
                update flow_steps
                set status = 'completed',
                    updated_at = ?
                where flow_id = ?
                  and status in ('selected','displayed','analyzing')
                  and superseded_by_step_id is null
                """,
                (db.now_iso(), flow["id"]),
            )
            selected = self._select_new_knowledge_target(flow_dict)
            route = model_router.teaching_route()
            provider_mode = _provider_mode(route)
            graph_node = self._graph_node_teaching_packet(selected["question"]["node_id"])
            payload = {
                "payload_schema_version": job_queue.V5_JOB_PAYLOAD_SCHEMA_VERSION,
                "legacy_session_id": flow["legacy_session_id"],
                "job_type": "teaching_generation",
                "new_knowledge_request": True,
                "flow_id": flow["id"],
                "flow_revision": int(flow["flow_revision"] or 1),
                "flow_step_id": "",
                "step_revision": 0,
                "attempt_id": "",
                "attempt_version": 0,
                "analysis_version": 0,
                "graph_version": flow["graph_version"],
                "question_bank_version": flow["question_bank_version"],
                "node_id": selected["question"]["node_id"],
                "target_node_id": selected["question"]["node_id"],
                "question_id": selected["question"]["id"],
                "review_record_id": selected["review_record_id"],
                "provider_mode": provider_mode,
                "graph_node": graph_node,
                "question_package": {
                    "question_id": selected["question"]["id"],
                    "prompt": selected["question"]["prompt"],
                    "reference_answer": selected["question"]["expected_answer"],
                    "solution_steps": selected["question"].get("solution_steps") or [],
                },
                "new_node_eligibility": selected["new_node_eligibility"],
                "route_meta": {"route": "teaching_generation", "source": "v5_new_knowledge_checkpoint"},
            }
            job_queue.JobQueue(self.conn).enqueue(
                "teaching_generation",
                f"v5:teaching_generation:{flow['id']}:{flow['flow_revision']}:{selected['question']['node_id']}:continue_new_knowledge",
                payload,
                commit=False,
            )
            self.conn.execute(
                """
                update daily_flows
                set status = 'learning_new',
                    current_step_id = null,
                    flow_revision = flow_revision + 1,
                    updated_at = ?
                where id = ?
                """,
                (db.now_iso(), flow["id"]),
            )
        return self.project_child_state(self._flow_by_id(flow["id"]))

    def finish_ready_checkpoint(self, *, client_day_key: str | None = None) -> dict[str, Any]:
        local_date = (client_day_key or date.today().isoformat())[:10]
        flow = self._active_flow(local_date)
        if not flow:
            terminal = self._latest_terminal_flow(local_date)
            if terminal:
                return self.project_child_state(terminal)
            raise ChildSafeRuntimeError("今天的学习记录暂时打不开，请刷新后继续。")
        if flow["status"] not in {"ready_for_new_knowledge", "reviewing", "learning_new", "paused", "blocked"}:
            return self.project_child_state(flow)
        return self.complete_summary(flow["id"])

    def complete_summary(self, flow_id: str) -> dict[str, Any]:
        with self.conn:
            flow = self._flow_by_id(flow_id)
            if not flow:
                return self._blocked_projection("今天的学习记录暂时打不开，请稍后再试。")
            flow_dict = dict(flow)
            summary_id = self._ensure_daily_summary(
                flow_dict,
                reason="manual_summary_request",
                target_flow_revision=int(flow_dict.get("flow_revision") or 1) + 1,
            )
            self.conn.execute(
                """
                update daily_flows
                set status = 'completed',
                    summary_id = ?,
                    current_step_id = null,
                    flow_revision = flow_revision + 1,
                    updated_at = ?
                where id = ?
                """,
                (summary_id, db.now_iso(), flow_id),
            )
        return self.project_child_state(self._flow_by_id(flow_id))

    def process_next_background_job(
        self,
        *,
        worker_id: str,
        now: str | None = None,
        flow_id: str | None = None,
    ) -> dict[str, Any]:
        """Claim and process one durable job from the v5 semantic-Agent DAG."""
        queue = job_queue.JobQueue(self.conn)
        now = now or db.now_iso()
        queue.recover(now)
        claimed = queue.claim(worker_id, now, limit=1, lease_seconds=180, flow_id=flow_id)
        if not claimed:
            return {"processed": 0, "status": "idle"}
        job = claimed[0]
        started = queue.start(job["id"], worker_id, now=db.now_iso())
        if not started.applied:
            return {"processed": 0, "status": "claim_lost", "job_id": job["id"]}
        try:
            result = self._handle_v5_background_job(job)
            if result.get("job_status") == "blocked":
                reason = str(result.get("reason") or "v5 model stage blocked")
                with self.conn:
                    queue.block(job["id"], worker_id, reason, commit=False)
                    # Handler-level blocked results are terminal child-visible
                    # outcomes, not a retryable analyzing state. Without this
                    # materialization a downstream model-stage block can leave
                    # the submitted step stuck in `analyzing` even though the
                    # worker has stopped.
                    self._block_flow_after_dead_letter(job, reason)
            elif result.get("job_status") == "waiting":
                reason = str(result.get("reason") or "waiting for clearer evidence")
                with self.conn:
                    queue.wait(job["id"], worker_id, reason, commit=False)
                    self._block_flow_after_dead_letter(job, reason)
            else:
                queue.finish(job["id"], worker_id, result_refs=result)
            return {"processed": 1, **result, "job_id": job["id"]}
        except model_router.ModelCallError as exc:
            current = self.conn.execute("select run_count from background_jobs where id = ?", (job["id"],)).fetchone()
            run_count = int(current["run_count"] if current else (job.get("run_count") or 0))
            retryable = isinstance(exc, model_router.ModelJSONParseError) or model_router.is_retryable_model_call_error(exc)
            max_attempts = (
                2
                if isinstance(exc, model_router.ModelJSONParseError)
                else (job_queue.JobQueue.v5_max_attempts(str(job.get("job_type") or "")) if retryable else 1)
            )
            if run_count >= max_attempts:
                reason = str(exc)[:800]
                with self.conn:
                    queue.block(job["id"], worker_id, reason, commit=False)
                    self._block_flow_after_dead_letter(job, reason)
                return {
                    "processed": 1,
                    "job_status": "blocked",
                    "status": "blocked",
                    "job_id": job["id"],
                    "reason": reason[:240],
                }
            if not retryable:
                reason = str(exc)[:800]
                with self.conn:
                    queue.block(job["id"], worker_id, reason, commit=False)
                    self._block_flow_after_dead_letter(job, reason)
                return {
                    "processed": 1,
                    "job_status": "blocked",
                    "status": "blocked",
                    "job_id": job["id"],
                    "reason": reason[:240],
                }
            retry_after = _iso_add_seconds(db.now_iso(), job_queue.JobQueue.v5_retry_after_seconds(run_count))
            queue.retry(job["id"], worker_id, str(exc), retry_after)
            return {"processed": 1, "status": "retry", "job_id": job["id"], "reason": str(exc)[:240]}
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            with self.conn:
                queue.dead_letter(job["id"], worker_id, reason, commit=False)
                self._block_flow_after_dead_letter(job, reason)
            return {
                "processed": 1,
                "job_status": "dead_letter",
                "job_id": job["id"],
                "reason": reason[:240],
            }

    def _handle_v5_background_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job_type = str(job.get("job_type") or "")
        if job_type == "answer_analysis":
            return self._handle_answer_analysis_job(job)
        if job_type == "evaluation_update":
            return self._handle_evaluation_update_job(job)
        if job_type == "planner_decision":
            return self._handle_planner_decision_job(job)
        if job_type == "teaching_generation":
            return self._handle_teaching_generation_job(job)
        if job_type == "evidence_validation":
            return {
                "job_status": "blocked",
                "reason": "v5 evidence_validation is a deterministic runtime gate, not a runnable model job.",
            }
        return {"job_status": "blocked", "reason": f"unsupported v5 job type: {job_type}"}

    def operator_inspect_today(self, local_date: str | None = None) -> dict[str, Any]:
        local_date = local_date or date.today().isoformat()
        flows = [dict(row) for row in self.conn.execute(
            "select * from daily_flows where child_key = ? and local_date = ? order by created_at desc",
            (self.child_key, local_date),
        ).fetchall()]
        flow_ids = [flow["id"] for flow in flows]
        steps = self._rows_for_flow_ids("flow_steps", flow_ids)
        attempts = self._attempts_for_step_ids([step["id"] for step in steps])
        jobs = self._rows_for_flow_ids("background_jobs", flow_ids)
        validations = self._validations_for_attempt_ids([attempt["id"] for attempt in attempts])
        decisions = self._rows_for_flow_ids("next_step_decisions", flow_ids)
        summaries = self._rows_for_flow_ids("daily_summaries", flow_ids)
        return {
            "schema_version": V3_CHILD_SCHEMA_VERSION,
            "feature_enabled": v3_daily_runtime_enabled(),
            "local_date": local_date,
            "flows": flows,
            "steps": steps,
            "attempts": attempts,
            "jobs": jobs,
            "evidence_validations": validations,
            "next_step_decisions": decisions,
            "daily_summaries": summaries,
        }

    def project_child_state(self, flow: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        if flow is None:
            return self._blocked_projection("今天的学习记录暂时打不开，请稍后再试。")
        flow_dict = dict(flow)
        status = flow_dict.get("status")
        base = {
            "schema_version": V3_CHILD_SCHEMA_VERSION,
            "child_state": "choose_review",
            "message": {
                "title": "开始今天学习",
                "body": "先做当前这一步，后面会根据你的情况安排复习或新知识。",
                "action_label": "开始今天学习",
            },
            "ready_for_new_knowledge": False,
        }
        if status == "new":
            return base
        if status == "ready_for_new_knowledge":
            return {
                **base,
                "child_state": "ready_for_new_knowledge",
                "ready_for_new_knowledge": True,
                "message": {
                    "title": "旧知识复习暂时告一段落",
                    "body": "可以开始一个新的知识点；系统会先准备讲解和小检查。",
                    "action_label": "学一个新知识",
                },
            }
        if status == "learning_new" and not flow_dict.get("current_step_id"):
            return {
                **base,
                "child_state": "preparing_new_knowledge",
                "message": {
                    "title": "正在准备讲解",
                    "body": "正在准备一个新知识的小讲解和小检查。准备好后会出现下一步。",
                    "action_label": "刷新看看",
                },
                "ready_for_new_knowledge": False,
            }
        if status in {"completed", "superseded"}:
            summary = self._latest_summary_for_flow(flow_dict.get("id"))
            return {
                **base,
                "child_state": "summary",
                "summary": summary.get("child_summary") if summary else {
                    "title": "今天先到这里",
                    "labels": {"pending": 1},
                    "next_action": "休息一下，等系统整理下一步。",
                },
            }
        if status == "blocked":
            return self._blocked_projection(flow_dict.get("blocked_reason") or "今天的学习暂时不能安全继续。先休息一下，稍后刷新。")

        step = self._current_visible_step(flow_dict.get("id"))
        if step:
            if step["status"] == "analyzing":
                return self._project_analyzing_step_or_reconcile(base, flow_dict, dict(step))
            child_state = "teaching" if step["step_type"] in {"teaching_repair", "worked_example"} else ("clarify_evidence" if step["step_type"] == "clarify_evidence" else "current_step")
            message = dict(base["message"])
            if child_state == "teaching":
                message = {
                    "title": "先看这一处讲解",
                    "body": "看完后点继续，系统会给一题很小的检查；如果还是卡住，也可以直接说卡住。",
                    "action_label": "继续小检查",
                }
            elif child_state == "clarify_evidence":
                message = {
                    "title": "请补清楚一点",
                    "body": "刚才的答案或照片还不能安全判断。补一段关键步骤，或重新拍一张清楚照片。",
                    "action_label": "保存补充",
                }
            try:
                projected_step = self._project_step(dict(step))
            except (ChildSafeRuntimeError, child_prompt.ChildPromptContractError):
                return self._blocked_projection("当前步骤还没有准备好，请稍后再试。")
            return {
                **base,
                "child_state": child_state,
                "message": message,
                "current_step": projected_step,
            }
        pending_job_projection = self._pending_flow_job_projection(base, flow_dict)
        if pending_job_projection:
            return pending_job_projection
        return self._blocked_projection("当前学习步骤还没有准备好，请稍后再试。")

    def _pending_flow_job_projection(self, base: dict[str, Any], flow: dict[str, Any]) -> dict[str, Any] | None:
        flow_id = str(flow.get("id") or "")
        if not flow_id:
            return None
        row = self.conn.execute(
            """
            select job_type, status
            from background_jobs
            where flow_id = ?
              and job_type in ('answer_analysis','evaluation_update','planner_decision','teaching_generation')
              and status in ('queued','retry','claimed','running')
            order by
              case job_type
                when 'teaching_generation' then 0
                when 'planner_decision' then 1
                when 'evaluation_update' then 2
                else 3
              end,
              created_at desc,
              id desc
            limit 1
            """,
            (flow_id,),
        ).fetchone()
        if not row:
            return None
        job_type = str(row["job_type"] or "")
        title = "正在准备讲解" if job_type == "teaching_generation" else "正在整理下一步"
        body = (
            "答案已经保存。系统正在生成针对这道题的讲解，准备好后会自动出现。"
            if job_type == "teaching_generation"
            else "答案已经保存。系统正在整理分析结果和下一步，准备好后会自动出现。"
        )
        return {
            **base,
            "child_state": "analyzing",
            "message": {
                "title": title,
                "body": body,
                "action_label": "刷新看看",
            },
        }

    def _active_flow(self, local_date: str) -> sqlite3.Row | None:
        placeholders = ",".join("?" for _ in ACTIVE_FLOW_STATUSES)
        return self.conn.execute(
            f"""
            select *
            from daily_flows
            where child_key = ?
              and local_date = ?
              and (
                status in ({placeholders})
                or (status = 'active' and current_step_id is not null)
              )
            order by
              case
                when current_step_id is not null and status in ('active','reviewing','learning_new','paused') then 0
                when status in ('reviewing','learning_new','paused') then 1
                when status = 'ready_for_new_knowledge' then 2
                when status = 'blocked' then 3
                when status = 'new' then 4
                else 5
              end,
              updated_at desc,
              created_at desc,
              id desc
            limit 1
            """,
            (self.child_key, local_date, *ACTIVE_FLOW_STATUSES),
        ).fetchone()

    def current_target_flow(self, local_date: str | None = None) -> sqlite3.Row | None:
        """Return the same current flow authority used by child bootstrap."""
        return self._active_flow(local_date or date.today().isoformat())

    def _latest_terminal_flow(self, local_date: str) -> sqlite3.Row | None:
        placeholders = ",".join("?" for _ in TERMINAL_FLOW_STATUSES)
        return self.conn.execute(
            f"""
            select *
            from daily_flows
            where child_key = ?
              and local_date = ?
              and status in ({placeholders})
            order by updated_at desc, created_at desc, id desc
            limit 1
            """,
            (self.child_key, local_date, *TERMINAL_FLOW_STATUSES),
        ).fetchone()

    def _flow_by_id(self, flow_id: str) -> sqlite3.Row | None:
        return self.conn.execute("select * from daily_flows where id = ?", (flow_id,)).fetchone()

    def _ensure_first_review_step(self, flow: sqlite3.Row, graph_version: str) -> str:
        existing = self.conn.execute(
            """
            select id
            from flow_steps
            where flow_id = ?
              and step_type = 'question'
              and status in ('selected','displayed','analyzing')
              and superseded_by_step_id is null
            order by position desc, created_at desc
            limit 1
            """,
            (flow["id"],),
        ).fetchone()
        if existing:
            return existing["id"]
        selected = self._select_first_review_question(flow=flow, graph_version=graph_version)
        question = selected["question"]
        self._question_visual_for_question(question)
        review_record_id = selected["review_record_id"]
        step_id = self._create_question_step(
            flow_id=flow["id"],
            position=1,
            graph_version=graph_version,
            question=question,
            review_record_id=review_record_id,
            selection_reason=selected.get("selection_reason") or {},
            candidate_packet=selected.get("candidate_packet") or {},
        )
        return step_id

    def _select_first_review_question(self, *, flow: sqlite3.Row | dict[str, Any] | None = None, graph_version: str | None = None) -> dict[str, Any]:
        graph_version = graph_version or self.graph.current_graph_version()
        target_node_ids = self._initial_target_node_ids()
        for node_id in target_node_ids:
            selected = self._select_question_for_node(
                node_id,
                graph_version=graph_version,
                flow_id=str((dict(flow).get("id") if flow else "") or ""),
                flow_revision=int((dict(flow).get("flow_revision") if flow else 1) or 1),
                reason={"reason": "initial_review_target_pool", "target_node_id": node_id},
                selection_intent="initial_review",
            )
            if selected:
                return selected
        active_version = self._question_bank_version_for_flow(str((dict(flow).get("id") if flow else "") or ""))
        fallback_rows = self.conn.execute(
            """
            select distinct q.node_id
            from question_items q
            join question_review_records r
              on r.question_id = q.id
             and r.item_version = q.item_version
             and r.source_type = q.source_type
             and r.review_status = 'approved'
             and r.active_eligible = 1
            where q.item_version = ?
            order by q.node_id
            """,
            (active_version,),
        ).fetchall()
        for row in fallback_rows:
            selected = self._select_question_for_node(
                row["node_id"],
                graph_version=graph_version,
                flow_id=str((dict(flow).get("id") if flow else "") or ""),
                flow_revision=int((dict(flow).get("flow_revision") if flow else 1) or 1),
                reason={"reason": "active_bank_version_fallback", "target_node_id": row["node_id"]},
            )
            if selected:
                return selected
        raise ChildSafeRuntimeError("今天的复习题暂时没有准备好，请稍后再试。")

    def _select_new_knowledge_target(self, flow: dict[str, Any]) -> dict[str, Any]:
        touched = {
            row["node_id"]
            for row in self.conn.execute(
                "select distinct node_id from flow_steps where flow_id = ? and node_id <> ''",
                (flow["id"],),
            ).fetchall()
        }
        rows = self.conn.execute(
            """
            select id
            from graph_nodes
            order by sequence_band, case priority when 'P0' then 0 when 'P1' then 1 else 2 end, id
            """
        ).fetchall()
        fallback: dict[str, Any] | None = None
        for row in rows:
            node_id = row["id"]
            if node_id in touched:
                continue
            node = db.get_graph_node(self.conn, node_id)
            prereq_ids = [str(item) for item in (node.get("prerequisites") or []) if item]
            prereqs = []
            ready = True
            for prereq_id in prereq_ids[:8]:
                status = self._learner_status_for_node(prereq_id)
                prereq_ready = str(status.get("status_code") or "") in {"A", "B"}
                prereqs.append({"node_id": prereq_id, "ready": prereq_ready, "status_code": status.get("status_code", "")})
                ready = ready and prereq_ready
            selected = self._select_question_for_node(
                node_id,
                graph_version=flow["graph_version"],
                flow_id=flow["id"],
                flow_revision=int(flow.get("flow_revision") or 1),
                reason={"reason": "new_knowledge_graph_eligible", "target_node_id": node_id},
                preferred_kinds=["essence_model", "standard_example", "standard_model", "core_representation"],
                selection_intent="new_knowledge_teaching",
                next_evidence_goal="teaching_context",
                prerequisite_ready=ready,
            )
            if not selected:
                continue
            enriched = {
                **selected,
                "new_node_eligibility": {
                    "graph_eligible": ready,
                    "prerequisites": prereqs,
                    "policy": "unseen_node_with_ready_direct_prerequisites",
                },
            }
            if ready:
                return enriched
            if fallback is None and not prereqs:
                fallback = enriched
        if fallback:
            return fallback
        raise ChildSafeRuntimeError("新知识暂时没有准备好，先完成今天总结。")

    def _graph_node_teaching_packet(self, node_id: str) -> dict[str, Any]:
        node = db.get_graph_node(self.conn, node_id)
        raw_contract = node.get("teaching_contract") if isinstance(node.get("teaching_contract"), dict) else {}
        core_model = raw_contract.get("core_model") or raw_contract.get("model") or node.get("teaching_strategy") or ""
        safe_contract = {
            "core_model": _child_safe_text(core_model, "先抓住核心关系，再按关系完成变换。", limit=240),
        }
        return {
            "id": node.get("id"),
            "name": node.get("name"),
            "essence_for_child": _child_safe_text(node.get("essence_for_child"), "先抓住这个知识点的核心关系。", limit=240),
            "mastery_criteria": node.get("mastery_criteria") or [],
            "teaching_contract": safe_contract,
            "question_types": node.get("question_types") or [],
            "common_mistakes": node.get("common_mistakes") or [],
        }

    def _replay_answer_analysis_refs_for_processed_attempt(
        self,
        job: dict[str, Any],
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        """Recover canonical answer-analysis refs after a post-commit crash.

        The answer handler commits the attempt grade, model agent_run,
        evidence_validation and downstream evaluation job in one transaction;
        the queue stores root job result refs immediately afterwards. If the
        process dies between those two steps, replay must reuse committed
        lineage instead of calling the model again or fabricating refs.
        """
        attempt_id = str(attempt.get("id") or job.get("attempt_id") or "")
        base = {"job_status": "succeeded", "reason": "attempt_already_processed", "attempt_id": attempt_id}
        if not attempt_id:
            return base
        run = self.conn.execute(
            """
            select *
            from agent_runs
            where agent_key = 'answer_analysis_agent'
              and phase = 'answer_analysis'
              and (
                trigger like ?
                or input_refs_json like ?
              )
            order by created_at desc, id desc
            limit 1
            """,
            (f"v5_answer_analysis:{attempt_id}:%", f"%{attempt_id}%"),
        ).fetchone()
        if not run:
            return base
        validation = self.conn.execute(
            """
            select *
            from evidence_validations
            where attempt_id = ?
              and answer_analysis_agent_run_id = ?
            order by created_at desc, id desc
            limit 1
            """,
            (attempt_id, run["id"]),
        ).fetchone()
        if not validation:
            return base
        predicate = db.json_load(validation["predicate_result_json"], {})
        eval_job = self.conn.execute(
            """
            select *
            from background_jobs
            where attempt_id = ?
              and job_type = 'evaluation_update'
              and payload_json like ?
              and payload_json like ?
            order by created_at desc, id desc
            limit 1
            """,
            (attempt_id, f"%{validation['id']}%", f"%{run['id']}%"),
        ).fetchone()
        mastery = self.conn.execute(
            """
            select *
            from mastery_decisions
            where source_attempt_ids_json like ?
            order by created_at desc, id desc
            limit 1
            """,
            (f"%{attempt_id}%",),
        ).fetchone()
        decision = self.conn.execute(
            """
            select *
            from next_step_decisions
            where source_attempt_ids_json like ?
            order by created_at desc, id desc
            limit 1
            """,
            (f"%{attempt_id}%",),
        ).fetchone()
        accepted_assessment = assessment_store.accepted_assessment_for_attempt(
            self.conn,
            attempt_id,
            int(attempt.get("attempt_version") or 1),
        )
        if accepted_assessment:
            feedback_step = self.conn.execute(
                """
                select *
                from flow_steps
                where flow_id = ?
                  and step_type = 'teaching_repair'
                  and selection_reason_json like '%v5.1_assessment_feedback%'
                  and selection_reason_json like ?
                order by created_at desc, id desc
                limit 1
                """,
                (str(job.get("flow_id") or ""), f"%{attempt_id}%"),
            ).fetchone()
            return {
                **base,
                "reason": "attempt_already_processed_replayed",
                "answer_analysis_job_id": str(job.get("id") or ""),
                "answer_analysis_agent_run_id": run["id"],
                "assessment_id": accepted_assessment["id"],
                "assessment_version": accepted_assessment["assessment_version"],
                "assessment_digest_sha256": accepted_assessment["assessment_digest_sha256"],
                "evidence_validation_id": validation["id"],
                "gate_status": validation["gate_status"],
                "report_label": str(predicate.get("report_label") or validation["gate_status"]),
                "pipeline_mode": "v5.1_single_semantic_call_deterministic_score",
                "mastery_decision_id": mastery["id"] if mastery else "",
                "next_step_decision_id": decision["id"] if decision else "",
                "feedback_step_id": feedback_step["id"] if feedback_step else "",
                "next_action": "assessment_feedback",
            }
        result = {
            **base,
            "reason": "attempt_already_processed_replayed",
            "answer_analysis_job_id": str(job.get("id") or ""),
            "answer_analysis_agent_run_id": run["id"],
            "evidence_validation_id": validation["id"],
            "gate_status": validation["gate_status"],
            "report_label": str(predicate.get("report_label") or validation["gate_status"]),
            "evaluation_job_id": eval_job["id"] if eval_job else "",
            "mastery_decision_id": mastery["id"] if mastery else "",
            "next_step_decision_id": decision["id"] if decision else "",
            "next_action": (
                "evaluation_update"
                if eval_job
                else (decision["action"] if decision else "already_processed")
            ),
        }
        return result

    def _handle_answer_analysis_job(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = db.json_load(job.get("payload_json"), {})
        attempt_id = str(job.get("attempt_id") or payload.get("attempt_id") or "")
        flow_id = str(job.get("flow_id") or payload.get("flow_id") or "")
        if not attempt_id or not flow_id:
            return {"job_status": "blocked", "reason": "missing_attempt_or_flow_lineage"}
        attempt = db.get_attempt(self.conn, attempt_id)
        if attempt.get("grading_status") != "pending_review":
            return self._replay_answer_analysis_refs_for_processed_attempt(job, attempt)
        question = db.get_question(self.conn, attempt["question_id"])
        photo_data_url = self._answer_photo_data_url_for_attempt(attempt_id)
        route = model_router.answer_analysis_route()
        provider_mode = _provider_mode(route)
        self.conn.execute(
            "update background_jobs set provider_mode = ?, route_meta_json = ? where id = ?",
            (provider_mode, db.json_dump({"route": "answer_analysis", **route.audit_metadata()}), job["id"]),
        )
        photo_ocr = None
        if photo_data_url:
            photo_ocr = auto_review._review_answer_photo(question, attempt["answer_raw"], photo_data_url)
        contract = assessment_store.bound_active_contract_for_flow_step(
            self.conn, str(attempt.get("flow_step_id") or "")
        )
        if contract is not None:
            return self._handle_v51_answer_analysis_job(
                job=job,
                attempt=attempt,
                question=question,
                contract=contract,
                route=route,
                provider_mode=provider_mode,
                photo_ocr=photo_ocr,
            )
        recorded_output = None
        payload_recorded = payload.get("recorded_agent_output") if isinstance(payload.get("recorded_agent_output"), dict) else None
        if payload_recorded is not None:
            recorded_output = payload_recorded
        elif provider_mode in {"recorded_model", "mock_only"} and hasattr(auto_review.review_child_answer, "mock_calls"):
            legacy_review = auto_review.review_child_answer(
                question,
                attempt["answer_raw"],
                has_photo=photo_data_url is not None,
                answer_photo_data_url=photo_data_url,
            )
            if legacy_review.get("needs_ai_review", legacy_review.get("needs_codex_review")):
                return self._handle_pending_answer_analysis(
                    job,
                    attempt=attempt,
                    question=question,
                    review=legacy_review,
                    provider_mode=provider_mode,
                )
            recorded_output = self._semantic_answer_output_from_legacy_review(legacy_review)
        request = self._answer_analysis_request(
            job=job,
            attempt=attempt,
            question=question,
            provider_mode=provider_mode,
            photo_ocr=photo_ocr,
            recorded_output=recorded_output,
        )
        envelope = semantic_agents.call_answer_analysis_agent(request)
        if envelope.status != "accepted":
            pending_review = {
                "status": envelope.status,
                "reason": envelope.error_reason or "answer_analysis_agent blocked",
                "ai_review": {
                    "status": envelope.status,
                    "reason": envelope.error_reason or "answer_analysis_agent blocked",
                    "provider_mode": envelope.provider_mode,
                },
            }
            return self._handle_pending_answer_analysis(
                job,
                attempt=attempt,
                question=question,
                review=pending_review,
                provider_mode=envelope.provider_mode,
            )
        if not isinstance(envelope.output.get("answer_analysis"), dict) or not db.is_valid_answer_analysis(
            self._normalize_answer_analysis_for_attempt(envelope.output.get("answer_analysis") or {})
        ):
            raise model_router.ModelJSONParseError("answer_analysis_agent returned malformed answer_analysis")

        if self._answer_agent_output_requires_clarification(envelope.output, photo_ocr=photo_ocr):
            return self._handle_accepted_unclear_answer_analysis(
                job,
                attempt=attempt,
                question=question,
                envelope=envelope,
                route=route,
                photo_ocr=photo_ocr,
            )

        grade = self._grade_from_answer_agent_output(envelope.output, route=route, provider_mode=envelope.provider_mode, photo_ocr=photo_ocr)
        with self.conn:
            latest = db.get_attempt(self.conn, attempt_id)
            if latest["grading_status"] != "pending_review" or latest.get("evidence_status") != "active":
                return {"job_status": "succeeded", "reason": "attempt_no_longer_active", "attempt_id": attempt_id}
            graded = db.grade_attempt(self.conn, attempt_id=attempt_id, answer_raw=None, commit=False, **grade)
            self.conn.execute(
                """
                update attempts
                set analysis_status = 'valid',
                    analysis_version = analysis_version + 1
                where id = ?
                """,
                (attempt_id,),
            )
            graded = db.get_attempt(self.conn, attempt_id)
            answer_run = self._record_model_agent_run_from_envelope(
                envelope,
                session_id=graded["session_id"],
                trigger=f"v5_answer_analysis:{attempt_id}:{graded.get('analysis_version', 1)}",
                input_refs={
                    "attempt_id": attempt_id,
                    "question_id": question["id"],
                    "flow_id": flow_id,
                    "flow_step_id": graded.get("flow_step_id"),
                    "has_photo": photo_data_url is not None,
                    "trusted_question_package": True,
                    "untrusted_child_answer": True,
                },
                route=route,
            )
            validation = evidence_gate.EvidenceGate(
                self.conn,
                current_graph_version=self.graph.current_graph_version(),
                current_question_bank_version=str(graded.get("question_bank_version") or job.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION),
            ).validate_attempt(
                attempt_id,
                analysis_version=int(graded.get("analysis_version") or 1),
                provider_mode=envelope.provider_mode,
                answer_analysis_agent_run_id=answer_run["id"],
                commit=False,
            )
            eval_job_id = ""
            evaluation: dict[str, Any] = {}
            decision: dict[str, Any] = {}
            if validation.predicate.usable:
                if envelope.provider_mode == "live_model":
                    evaluation = self._record_evaluation_update(
                        attempt=graded,
                        validation=validation,
                        provider_mode=envelope.provider_mode,
                    )
                    if evaluation.get("applied"):
                        decision = self._advance_after_analysis(
                            flow_id=flow_id,
                            source_step_id=str(graded.get("flow_step_id") or payload.get("flow_step_id") or ""),
                            attempt=graded,
                            validation=validation,
                            evaluation=evaluation,
                            provider_mode=envelope.provider_mode,
                        )
                    else:
                        self._materialize_blocked_or_summary(flow_id, reason="evaluation_not_applied")
                else:
                    eval_payload = self._v5_stage_payload(
                        job=job,
                        attempt=graded,
                        job_type="evaluation_update",
                        source_job_ids=[job["id"]],
                        source_agent_run_ids=[answer_run["id"]],
                        source_validation_ids=[validation.validation_id] if validation.validation_id else [],
                        provider_mode=envelope.provider_mode,
                    )
                    eval_result = job_queue.JobQueue(self.conn).enqueue(
                        "evaluation_update",
                        f"v5:evaluation_update:{attempt_id}:{validation.validation_id}:{answer_run['id']}",
                        eval_payload,
                        depends_on_job_id=job["id"],
                        commit=False,
                    )
                    eval_job_id = eval_result.job_id
            else:
                self._block_flow(flow_id, "这一步还不能可靠判断，需要系统恢复或补充更清楚的答案。")
        return {
            "job_status": "succeeded",
            "attempt_id": attempt_id,
            "answer_analysis_job_id": job["id"],
            "answer_analysis_agent_run_id": answer_run["id"],
            "evidence_validation_id": validation.validation_id,
            "gate_status": validation.gate_status,
            "report_label": validation.predicate.report_label,
            "evaluation_job_id": eval_job_id,
            "mastery_decision_id": evaluation.get("mastery_decision_id", ""),
            "next_step_decision_id": decision.get("id", ""),
            "pipeline_mode": "single_live_model_call" if envelope.provider_mode == "live_model" and validation.predicate.usable else "staged_jobs",
            "next_action": (
                decision.get("action")
                or ("evaluation_update" if eval_job_id else "blocked")
            ),
        }

    def _handle_v51_answer_analysis_job(
        self,
        *,
        job: dict[str, Any],
        attempt: dict[str, Any],
        question: dict[str, Any],
        contract: dict[str, Any],
        route: model_router.ModelRoute,
        provider_mode: str,
        photo_ocr: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = db.json_load(job.get("payload_json"), {})
        attempt_id = attempt["id"]
        attempt_version = int(attempt.get("attempt_version") or 1)
        input_digest = question_fingerprints.canonical_sha256(
            {
                "attempt_id": attempt_id,
                "attempt_version": attempt_version,
                "evidence_digest_sha256": attempt.get("evidence_digest_sha256") or "",
                "answer_contract_id": contract["id"],
                "answer_contract_version": contract["contract_version"],
                "answer_contract_digest_sha256": contract["contract_digest_sha256"],
                "photo_ocr": photo_ocr,
            }
        )
        pending = assessment_store.record_pending_assessment(
            self.conn,
            attempt_id=attempt_id,
            attempt_version=attempt_version,
            contract=contract,
            assessment_input_digest_sha256=input_digest,
        )
        recorded_output = (
            payload.get("recorded_agent_output")
            if isinstance(payload.get("recorded_agent_output"), dict)
            else None
        )
        request = self._answer_analysis_request(
            job=job,
            attempt=attempt,
            question=question,
            provider_mode=provider_mode,
            photo_ocr=photo_ocr,
            recorded_output=recorded_output,
            answer_contract=contract,
        )
        envelope = semantic_agents.call_answer_analysis_agent(request)
        if envelope.status != "accepted":
            return self._handle_pending_answer_analysis(
                job,
                attempt=attempt,
                question=question,
                review={
                    "status": envelope.status,
                    "reason": envelope.error_reason or "answer_analysis_agent blocked",
                },
                provider_mode=envelope.provider_mode,
            )

        policy_contract = assessment_store.policy_contract_for_assessment(contract)
        output = envelope.output
        expected_fields = {
            "schema_version",
            "criteria",
            "answer_gap",
            "improvement_direction",
            "expression_judgment",
            "teaching_explanation",
            "confidence",
        }
        expected_contract = internal_agents.load_v5_contract_for_agent(
            "answer_analysis_agent"
        )
        if (
            envelope.agent_key != "answer_analysis_agent"
            or envelope.phase != "answer_analysis"
            or not isinstance(output, dict)
            or set(output) != expected_fields
            or output.get("schema_version")
            != expected_contract["response_schema_version"]
            or envelope.prompt_version_id != expected_contract["prompt_version_id"]
            or envelope.response_schema_version
            != expected_contract["response_schema_version"]
        ):
            raise model_router.ModelJSONParseError(
                "answer_analysis_agent returned malformed answer review v3"
            )
        assessment_policy.validate_criterion_judgments(
            policy_contract, output["criteria"]
        )
        for field in (
            "answer_gap",
            "expression_judgment",
            "teaching_explanation",
        ):
            if not isinstance(output[field], str) or not output[field].strip():
                raise model_router.ModelJSONParseError(
                    f"answer review v3 {field} is invalid"
                )
        if (
            not isinstance(output["improvement_direction"], list)
            or not output["improvement_direction"]
            or not all(
                isinstance(item, str) and item.strip()
                for item in output["improvement_direction"]
            )
        ):
            raise model_router.ModelJSONParseError(
                "answer review v3 improvement_direction is invalid"
            )
        calculated = assessment_policy.calculate_assessment(
            policy_contract, output["criteria"]
        )
        if not calculated["finalized"]:
            raise model_router.ModelJSONParseError(
                "answer review v3 contains unclear criteria"
            )
        reference_answer = self._assessment_reference_answer(contract)
        feedback = {
            "reference_answer": reference_answer,
            "answer_gap": output["answer_gap"],
            "improvement_direction": list(output["improvement_direction"]),
            "expression_judgment": output["expression_judgment"],
            "teaching_explanation": output["teaching_explanation"],
        }
        with self.conn:
            latest = db.get_attempt(self.conn, attempt_id)
            if (
                latest["grading_status"] != "pending_review"
                or latest.get("evidence_status") != "active"
            ):
                return {
                    "job_status": "succeeded",
                    "reason": "attempt_no_longer_active",
                    "attempt_id": attempt_id,
                }
            answer_run = self._record_model_agent_run_from_envelope(
                envelope,
                session_id=latest["session_id"],
                trigger=f"v5_answer_analysis:{attempt_id}:{attempt_version}",
                input_refs={
                    "attempt_id": attempt_id,
                    "question_id": question["id"],
                    "flow_id": str(job.get("flow_id") or payload.get("flow_id") or ""),
                    "flow_step_id": latest.get("flow_step_id"),
                    "assessment_id": pending["id"],
                    "assessment_input_digest_sha256": input_digest,
                    "answer_contract_id": contract["id"],
                    "answer_contract_version": contract["contract_version"],
                    "answer_contract_digest_sha256": contract["contract_digest_sha256"],
                },
                route=route,
            )
            assessment_digest = question_fingerprints.canonical_sha256(
                {
                    "assessment_id": pending["id"],
                    "assessment_version": pending["assessment_version"],
                    "assessment_input_digest_sha256": input_digest,
                    "answer_contract_id": contract["id"],
                    "answer_contract_version": contract["contract_version"],
                    "answer_contract_digest_sha256": contract["contract_digest_sha256"],
                    "criterion_judgments": output["criteria"],
                    "score_out_of_10": calculated["score_out_of_10"],
                    "question_passed": calculated["question_passed"],
                    "feedback": feedback,
                    "answer_analysis_agent_run_id": answer_run["id"],
                    "provider_mode": envelope.provider_mode,
                }
            )
            accepted = assessment_store.accept_assessment(
                self.conn,
                assessment_id=pending["id"],
                criterion_judgments=output["criteria"],
                score_out_of_10=calculated["score_out_of_10"],
                question_passed=calculated["question_passed"],
                feedback=feedback,
                assessment_digest_sha256=assessment_digest,
                answer_analysis_agent_run_id=answer_run["id"],
                provider_mode=envelope.provider_mode,
                commit=False,
            )
            self.conn.execute(
                """
                update attempts
                set analysis_version = analysis_version + 1
                where id = ? and attempt_version = ?
                """,
                (attempt_id, attempt_version),
            )
            graded = db.get_attempt(self.conn, attempt_id)
            validation = evidence_gate.EvidenceGate(
                self.conn,
                current_graph_version=self.graph.current_graph_version(),
                current_question_bank_version=str(
                    graded.get("question_bank_version")
                    or question_bank.QUESTION_BANK_VERSION
                ),
            ).validate_attempt(
                attempt_id,
                analysis_version=int(graded.get("analysis_version") or 1),
                provider_mode=envelope.provider_mode,
                answer_analysis_agent_run_id=answer_run["id"],
                assessment_id=accepted["id"],
                assessment_version=accepted["assessment_version"],
                assessment_digest_sha256=accepted["assessment_digest_sha256"],
                commit=False,
            )
            self.conn.execute(
                """
                update flow_steps
                set status = 'completed', attempt_id = ?, updated_at = ?
                where id = ?
                """,
                (attempt_id, db.now_iso(), graded.get("flow_step_id")),
            )
            flow_id = str(job.get("flow_id") or payload.get("flow_id") or "")
            flow_row = self._flow_by_id(flow_id)
            if not flow_row:
                raise ValueError("answer assessment flow no longer exists")
            flow = dict(flow_row)
            evaluation_output = self._v51_deterministic_evaluation_output(
                contract=contract,
                criterion_judgments=output["criteria"],
                score_out_of_10=calculated["score_out_of_10"],
                question_passed=calculated["question_passed"],
            )
            evaluation = self._record_evaluation_update(
                attempt=graded,
                validation=validation,
                provider_mode="deterministic_runtime",
                evaluation_output=evaluation_output,
            )
            needs_repair = bool(
                not calculated["question_passed"]
                or calculated["score_out_of_10"] < 8
            )
            feedback_position = int(self.conn.execute(
                "select count(*) from flow_steps where flow_id = ?",
                (flow_id,),
            ).fetchone()[0]) + 1
            target_plan = self._plan_pending_target_after_assessment_locked(
                flow=flow,
                source_step_id=str(graded.get("flow_step_id") or ""),
                source_attempt_id=attempt_id,
                source_validation_ids=[validation.validation_id]
                if validation.validation_id
                else [],
                source_mastery_ids=[evaluation.get("mastery_decision_id")]
                if evaluation.get("mastery_decision_id")
                else [],
                report_label=validation.predicate.report_label,
                planned_position=feedback_position + 1,
            )
            if target_plan and target_plan.get("status") == "applied":
                next_selection = None
                decision = target_plan["decision"]
                planned_step_id = str(target_plan["step_id"])
            else:
                next_selection = self._next_selection_after_attempt(
                    flow,
                    attempt=graded,
                )
                next_action = str(
                    (next_selection or {}).get("action") or "summary"
                )
                decision = self._record_next_step_decision(
                    flow=flow,
                    action=next_action,
                    report_label=validation.predicate.report_label,
                    source_step_id=str(graded.get("flow_step_id") or ""),
                    source_attempt_ids=[attempt_id],
                    source_validation_ids=[validation.validation_id]
                    if validation.validation_id
                    else [],
                    source_mastery_ids=[evaluation.get("mastery_decision_id")]
                    if evaluation.get("mastery_decision_id")
                    else [],
                    provider_mode="deterministic_runtime",
                    reason=(
                        str(
                            next_selection.get("reason")
                            or "先展示本题解析，再继续下一题。"
                        )
                        if next_selection
                        else "先展示本题解析；当前没有合适的下一题，随后完成本次总结。"
                    ),
                    candidate_packet=(next_selection or {}).get(
                        "candidate_packet"
                    ),
                    target_node_id=str(
                        ((next_selection or {}).get("question") or {}).get(
                            "node_id"
                        )
                        or graded["node_id"]
                    ),
                )
                planned_step_id = ""
            feedback_step_id = self._create_v51_assessment_feedback_step(
                flow=flow,
                source_attempt=graded,
                source_step_id=str(graded.get("flow_step_id") or ""),
                source_next_step_decision_id=decision["id"],
                position=feedback_position,
                assessment=accepted,
                contract=contract,
                needs_repair=needs_repair,
            )
            if next_selection:
                planned_step_id = self._create_question_step(
                    flow_id=flow_id,
                    position=feedback_position + 1,
                    graph_version=flow["graph_version"],
                    question=next_selection["question"],
                    review_record_id=next_selection["review_record_id"],
                    selection_reason={
                        **(next_selection.get("selection_reason") or {}),
                        "reason": "planned_after_v5.1_assessment_feedback",
                        "source_next_step_decision_id": decision["id"],
                        "source_attempt_id": attempt_id,
                    },
                    candidate_packet=next_selection.get("candidate_packet") or {},
                    support_hint=(
                        "把刚才修正的那一点用上，再完成这道小检查。"
                        if needs_repair
                        else "换一个情境再做一次，确认方法是否稳定。"
                    ),
                    step_type="micro_check" if needs_repair else "question",
                    initial_status="planned",
                )
            self.conn.execute(
                """
                update daily_flows
                set status = 'reviewing', current_step_id = ?,
                    flow_revision = flow_revision + 1, updated_at = ?
                where id = ? and status not in ('completed','superseded')
                """,
                (feedback_step_id, db.now_iso(), flow_id),
            )
        return {
            "job_status": "succeeded",
            "attempt_id": attempt_id,
            "answer_analysis_job_id": job["id"],
            "answer_analysis_agent_run_id": answer_run["id"],
            "assessment_id": accepted["id"],
            "assessment_version": accepted["assessment_version"],
            "assessment_digest_sha256": accepted["assessment_digest_sha256"],
            "evidence_validation_id": validation.validation_id,
            "gate_status": validation.gate_status,
            "report_label": validation.predicate.report_label,
            "pipeline_mode": "v5.1_single_semantic_call_deterministic_score",
            "mastery_decision_id": evaluation.get("mastery_decision_id", ""),
            "next_step_decision_id": decision["id"],
            "feedback_step_id": feedback_step_id,
            "planned_step_id": planned_step_id,
            "next_action": "assessment_feedback",
            "teaching_explanation": output["teaching_explanation"],
        }

    def _v51_deterministic_evaluation_output(
        self,
        *,
        contract: dict[str, Any],
        criterion_judgments: list[dict[str, Any]],
        score_out_of_10: int,
        question_passed: bool,
    ) -> dict[str, Any]:
        status_by_key = {
            str(item.get("criterion_key") or ""): str(item.get("status") or "")
            for item in criterion_judgments
            if isinstance(item, dict)
        }
        totals: dict[str, float] = {}
        earned: dict[str, float] = {}
        weak_dimensions: list[str] = []
        for point in contract.get("score_points") or []:
            if not isinstance(point, dict):
                continue
            dimension = str(point.get("dimension") or "procedure")
            points = float(point.get("points") or 0)
            totals[dimension] = totals.get(dimension, 0.0) + points
            if status_by_key.get(str(point.get("key") or "")) == "met":
                earned[dimension] = earned.get(dimension, 0.0) + points
            elif dimension not in weak_dimensions:
                weak_dimensions.append(dimension)
        dimension_scores = {
            dimension: round(earned.get(dimension, 0.0) / total, 3) if total else 0.0
            for dimension, total in totals.items()
        }
        needs_teaching = bool(not question_passed or score_out_of_10 < 8)
        return {
            "mastery_recommendation": "weak" if needs_teaching else "emerging",
            "dimension_scores": dimension_scores,
            "planner_signal": {
                "next_evidence_goal": "same_structure_retest" if needs_teaching else "near_transfer_retest",
                "needs_teaching_before_next": needs_teaching,
                "needs_prerequisite_probe": False,
                "target_gap_dimensions": weak_dimensions[:6],
            },
            "reason": (
                f"本题确定性得分 {score_out_of_10}/10，关键得分点仍有缺口。"
                if needs_teaching
                else f"本题确定性得分 {score_out_of_10}/10，先记为初步掌握并继续迁移确认。"
            ),
        }

    def _assessment_reference_answer(self, contract: dict[str, Any]) -> str:
        reference = contract.get("reference_solution")
        if not isinstance(reference, dict):
            raise ValueError("answer contract reference solution is missing")
        answer = reference.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer
        if answer is not None:
            rendered = json.dumps(
                answer,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if rendered:
                return rendered
        steps = [
            str(step).strip()
            for step in (reference.get("solution_steps") or [])
            if str(step).strip()
        ]
        if steps:
            return steps[-1]
        raise ValueError("answer contract reference answer is missing")

    def _answer_agent_output_requires_clarification(
        self,
        output: dict[str, Any],
        *,
        photo_ocr: dict[str, Any] | None = None,
    ) -> bool:
        if str(output.get("result") or "") == "unclear":
            return True
        if float(output.get("confidence") or 0.0) < 0.35:
            return True
        support = output.get("evaluation_support") if isinstance(output.get("evaluation_support"), dict) else {}
        if support.get("needs_clearer_evidence") is True or support.get("usable_for_evaluation") is False:
            return True
        if isinstance(photo_ocr, dict):
            if str(photo_ocr.get("status") or "") in {"unclear", "low_confidence", "unusable"}:
                return True
            if float(photo_ocr.get("confidence") or 0.0) < 0.35:
                return True
        return False

    def _handle_accepted_unclear_answer_analysis(
        self,
        job: dict[str, Any],
        *,
        attempt: dict[str, Any],
        question: dict[str, Any],
        envelope: semantic_agents.SemanticAgentEnvelope,
        route: model_router.ModelRoute,
        photo_ocr: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist accepted-but-unusable analysis lineage without fake grading."""
        answer_analysis = self._normalize_answer_analysis_for_attempt(envelope.output.get("answer_analysis") or {})
        reason = _child_safe_text(
            answer_analysis.get("process_gap")
            or answer_analysis.get("child_answer_summary")
            or "这一步证据还不够清楚，不能安全判断。",
            "这一步证据还不够清楚，不能安全判断。",
            limit=500,
        )
        review_status = "photo_ocr_unusable" if isinstance(photo_ocr, dict) and str(photo_ocr.get("status") or "") in {"unclear", "low_confidence", "unusable"} else "unclear"
        with self.conn:
            latest = db.get_attempt(self.conn, attempt["id"])
            if latest["grading_status"] != "pending_review" or latest.get("evidence_status") != "active":
                return {"job_status": "succeeded", "reason": "attempt_no_longer_active", "attempt_id": attempt["id"]}
            next_analysis_version = int(latest.get("analysis_version") or 0) + 1
            review_meta = {
                "status": review_status,
                "provider": route.provider if route.enabled else "",
                "model": route.model if route.enabled else "",
                "model_alias": route.model_alias if route.enabled else "",
                "provider_mode": envelope.provider_mode,
                "confidence": float(envelope.output.get("confidence") or envelope.confidence or 0.0),
                "vision": photo_ocr,
                "reason": reason,
            }
            self.conn.execute(
                """
                update attempts
                set review_meta_json = ?,
                    answer_analysis_json = ?,
                    parent_note = ?,
                    analysis_status = 'missing',
                    analysis_version = analysis_version + 1
                where id = ?
                """,
                (
                    db.json_dump(review_meta),
                    db.json_dump(answer_analysis),
                    reason,
                    attempt["id"],
                ),
            )
            updated_attempt = db.get_attempt(self.conn, attempt["id"])
            answer_run = self._record_model_agent_run_from_envelope(
                envelope,
                session_id=updated_attempt["session_id"],
                trigger=f"v5_answer_analysis:{attempt['id']}:{next_analysis_version}:unclear",
                input_refs={
                    "attempt_id": attempt["id"],
                    "question_id": question["id"],
                    "flow_id": job.get("flow_id"),
                    "flow_step_id": updated_attempt.get("flow_step_id"),
                    "accepted_unclear": True,
                    "has_photo": photo_ocr is not None,
                },
                route=route,
            )
            validation = evidence_gate.EvidenceGate(
                self.conn,
                current_graph_version=self.graph.current_graph_version(),
                current_question_bank_version=str(updated_attempt.get("question_bank_version") or job.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION),
            ).validate_attempt(
                attempt["id"],
                analysis_version=next_analysis_version,
                provider_mode=envelope.provider_mode,
                answer_analysis_agent_run_id=answer_run["id"],
                commit=False,
            )
            source_step = self.conn.execute(
                "select * from flow_steps where id = ?",
                (updated_attempt.get("flow_step_id") or "",),
            ).fetchone()
            if updated_attempt.get("answer_source") == "v3_stuck" and source_step and source_step["step_type"] == "clarify_evidence":
                self.conn.execute(
                    "update flow_steps set status = 'completed', updated_at = ? where id = ?",
                    (db.now_iso(), source_step["id"]),
                )
                flow_id = str(source_step["flow_id"])
                flow = dict(self._flow_by_id(flow_id))
                summary_id = self._ensure_daily_summary(
                    flow,
                    reason="clarify_cannot_provide",
                    target_flow_revision=int(flow.get("flow_revision") or 1) + 1,
                )
                self.conn.execute(
                    """
                    update daily_flows
                    set status = 'completed',
                        summary_id = ?,
                        current_step_id = null,
                        flow_revision = flow_revision + 1,
                        updated_at = ?
                    where id = ?
                    """,
                    (summary_id, db.now_iso(), flow_id),
                )
                return {
                    "job_status": "succeeded",
                    "next_action": "summary",
                    "reason": "clarify_cannot_provide",
                    "attempt_id": attempt["id"],
                    "answer_analysis_agent_run_id": answer_run["id"],
                    "evidence_validation_id": validation.validation_id,
                    "summary_id": summary_id,
                }
            decision = self._create_clarify_step(
                flow_id=str(job.get("flow_id") or ""),
                source_step_id=str(updated_attempt.get("flow_step_id") or ""),
                attempt=updated_attempt,
                validation=validation,
                provider_mode=envelope.provider_mode,
                reason=reason,
            )
            return {
                "job_status": "succeeded",
                "next_action": "clarify_evidence",
                "reason": reason,
                "attempt_id": attempt["id"],
                "answer_analysis_agent_run_id": answer_run["id"],
                "evidence_validation_id": validation.validation_id,
                "next_step_decision_id": decision.get("id"),
            }

    def _handle_evaluation_update_job(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = db.json_load(job.get("payload_json"), {})
        attempt_id = str(job.get("attempt_id") or payload.get("attempt_id") or "")
        flow_id = str(job.get("flow_id") or payload.get("flow_id") or "")
        if not attempt_id or not flow_id:
            return {"job_status": "blocked", "reason": "missing_evaluation_lineage"}
        attempt = db.get_attempt(self.conn, attempt_id)
        validation = self._latest_passed_validation(attempt_id, payload)
        if not validation:
            return {"job_status": "blocked", "reason": "missing_passed_evidence_validation", "attempt_id": attempt_id}
        route = model_router.evaluation_route()
        provider_mode = str(payload.get("provider_mode") or _provider_mode(route))
        self.conn.execute(
            "update background_jobs set provider_mode = ?, route_meta_json = ? where id = ?",
            (provider_mode, db.json_dump({"route": "evaluation_update", **route.audit_metadata()}), job["id"]),
        )
        recorded_eval = payload.get("recorded_agent_output") if isinstance(payload.get("recorded_agent_output"), dict) else None
        if recorded_eval is None and self._can_use_default_recorded_fixture(payload, provider_mode):
            recorded_eval = self._default_recorded_evaluation_output(attempt, validation, payload)
        trusted_context = self._evaluation_trusted_context(
            attempt=attempt,
            validation=validation,
            payload=payload,
        )
        if recorded_eval is not None:
            trusted_context["recorded_agent_output"] = recorded_eval
        envelope = semantic_agents.call_evaluation_agent(semantic_agents.SemanticAgentRequest(
            agent_key="evaluation_agent",
            phase="evaluation_update",
            trusted_context=trusted_context,
            untrusted_payload={"answer_analysis": attempt.get("answer_analysis") or {}},
            provider_mode=provider_mode,
            source_refs=payload,
        ))
        if envelope.status != "accepted":
            return {"job_status": "blocked", "reason": envelope.error_reason or "evaluation_agent blocked", "attempt_id": attempt_id}
        with self.conn:
            self.conn.execute(
                "update background_jobs set provider_mode = ?, route_meta_json = ? where id = ?",
                (
                    envelope.provider_mode,
                    db.json_dump({"route": "evaluation_update", **route.audit_metadata(), **(envelope.route_meta or {})}),
                    job["id"],
                ),
            )
            run = self._record_model_agent_run_from_envelope(
                envelope,
                session_id=attempt["session_id"],
                trigger=f"v5_evaluation_update:{attempt_id}:{validation.validation_id}",
                input_refs={
                    "attempt_id": attempt_id,
                    "evidence_validation_id": validation.validation_id,
                    "source_agent_run_ids": payload.get("source_agent_run_ids") or [],
                },
                route=route,
            )
            evaluation = self._record_evaluation_update(
                attempt=attempt,
                validation=validation,
                provider_mode=envelope.provider_mode,
                evaluation_agent_run_id=run["id"],
                evaluation_output=envelope.output,
            )
            planner_job_id = ""
            if evaluation.get("applied"):
                flow = dict(self._flow_by_id(flow_id))
                candidate_packet = self._candidate_packet_for_planner(flow, attempt)
                planner_payload = self._v5_stage_payload(
                    job=job,
                    attempt=attempt,
                    job_type="planner_decision",
                    source_job_ids=[*(payload.get("source_job_ids") or []), job["id"]],
                    source_agent_run_ids=[*(payload.get("source_agent_run_ids") or []), run["id"]],
                    source_validation_ids=[validation.validation_id] if validation.validation_id else [],
                    source_mastery_ids=[evaluation.get("mastery_decision_id")] if evaluation.get("mastery_decision_id") else [],
                    candidate_packet=candidate_packet,
                    provider_mode=envelope.provider_mode,
                )
                planner_payload["evaluation"] = evaluation
                planner_result = job_queue.JobQueue(self.conn).enqueue(
                    "planner_decision",
                    f"v5:planner_decision:{flow_id}:{flow.get('flow_revision')}:{attempt.get('flow_step_id')}:{run['id']}:{candidate_packet.get('packet_hash', '')}",
                    planner_payload,
                    depends_on_job_id=job["id"],
                    commit=False,
                )
                planner_job_id = planner_result.job_id
            else:
                self._materialize_blocked_or_summary(flow_id, reason="evaluation_not_applied")
        return {
            "job_status": "succeeded",
            "attempt_id": attempt_id,
            "evaluation_job_id": job["id"],
            "evaluation_agent_run_id": run["id"],
            "mastery_decision_id": evaluation.get("mastery_decision_id", ""),
            "planner_job_id": planner_job_id,
        }

    def _handle_planner_decision_job(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = db.json_load(job.get("payload_json"), {})
        attempt_id = str(job.get("attempt_id") or payload.get("attempt_id") or "")
        flow_id = str(job.get("flow_id") or payload.get("flow_id") or "")
        if not attempt_id or not flow_id:
            return {"job_status": "blocked", "reason": "missing_planner_lineage"}
        attempt = db.get_attempt(self.conn, attempt_id)
        flow = dict(self._flow_by_id(flow_id))
        if flow.get("status") in TERMINAL_FLOW_STATUSES:
            return {"job_status": "blocked", "reason": "terminal_flow", "attempt_id": attempt_id}
        packet = payload.get("candidate_packet") if isinstance(payload.get("candidate_packet"), dict) else None
        if not packet:
            packet = self._candidate_packet_for_planner(flow, attempt)
        original_packet = packet
        route = model_router.planner_route()
        provider_mode = str(payload.get("provider_mode") or _provider_mode(route))
        self.conn.execute(
            "update background_jobs set provider_mode = ?, candidate_packet_id = ?, route_meta_json = ? where id = ?",
            (provider_mode, str(packet.get("packet_id") or ""), db.json_dump({"route": "planner_decision", **route.audit_metadata()}), job["id"]),
        )
        recorded = payload.get("recorded_agent_output") if isinstance(payload.get("recorded_agent_output"), dict) else None
        if recorded is None and self._can_use_default_recorded_fixture(payload, provider_mode):
            next_selection = self._next_selection_after_attempt(flow, attempt=attempt)
            if next_selection:
                recorded = {
                    "schema_version": "2026-07-11.planner-next-step.v5.schema.v2",
                    "action": next_selection["action"],
                    "target_node_id": next_selection["question"]["node_id"],
                    "selected_candidate_id": next_selection["question"]["id"],
                    "candidate_packet_id": (next_selection.get("candidate_packet") or packet).get("packet_id", ""),
                    "branch_policy": {
                        "uses_prerequisite_first": next_selection["action"] == "prerequisite_probe",
                        "requires_teaching_generation": False,
                    },
                    "confidence": 0.86,
                    "reason": next_selection["reason"],
                }
                packet = next_selection.get("candidate_packet") or packet
            else:
                recorded = {
                    "schema_version": "2026-07-11.planner-next-step.v5.schema.v2",
                    "action": "summary",
                    "target_node_id": attempt.get("node_id") or "",
                    "selected_candidate_id": "",
                    "candidate_packet_id": packet.get("packet_id", ""),
                    "branch_policy": {"uses_prerequisite_first": False, "requires_teaching_generation": False},
                    "confidence": 0.82,
                    "reason": "No eligible next question found from bounded candidate packet.",
                }
        envelope = semantic_agents.call_planner_agent(semantic_agents.SemanticAgentRequest(
            agent_key="planner_agent",
            phase="planner_decision",
            trusted_context=self._planner_trusted_context(
                flow=flow,
                attempt=attempt,
                payload=payload,
                packet=packet,
                recorded_output=recorded,
            ),
            untrusted_payload={"recent_attempt": {"result": attempt.get("result"), "answer_analysis": attempt.get("answer_analysis") or {}}},
            provider_mode=provider_mode,
            source_refs=payload,
        ))
        if envelope.status != "accepted":
            return {"job_status": "blocked", "reason": envelope.error_reason or "planner_agent blocked", "attempt_id": attempt_id}
        current_flow = self._flow_by_id(flow_id)
        if current_flow and current_flow["status"] in TERMINAL_FLOW_STATUSES:
            return {"job_status": "blocked", "reason": "terminal_flow", "attempt_id": attempt_id}
        action = str(envelope.output.get("action") or "blocked")
        budget = self._interaction_budget(flow)
        if action in {"summary", "blocked"} and budget["completed_interactions"] < budget["minimum"]:
            blocked_reason = str((envelope.output.get("branch_policy") or {}).get("blocked_reason") or "")
            if blocked_reason not in {"child_stuck", "provider_blocked", "no_safe_candidate"}:
                raise model_router.ModelJSONParseError("early summary before budget_min requires explicit safe-stop reason")
        if action not in {
            "same_structure_retest", "near_transfer_retest", "prerequisite_probe", "micro_teach",
            "worked_example", "clarify_evidence", "continue_new_knowledge", "stretch", "summary", "blocked",
        }:
            raise model_router.ModelJSONParseError(f"planner_decision output action is not allowed: {action}")
        envelope_output = dict(envelope.output)
        decision_packet = packet
        output_packet_id = str(envelope_output.get("candidate_packet_id") or "")
        if output_packet_id and output_packet_id == str(original_packet.get("packet_id") or ""):
            decision_packet = original_packet
        envelope_output = self._normalize_planner_output_for_runtime(
            envelope_output,
            attempt=attempt,
            candidate_packet=decision_packet,
        )
        envelope_output = self._force_teaching_before_next_when_required(
            envelope_output,
            attempt=attempt,
            source_mastery_ids=list(payload.get("source_mastery_decision_ids") or []),
        )
        action = str(envelope_output.get("action") or "blocked")
        decision_provider_mode = envelope.provider_mode
        if budget["completed_interactions"] >= budget["maximum"] and action not in {"summary", "blocked"}:
            action = "summary"
            decision_provider_mode = "deterministic_runtime"
            envelope_output = {
                **envelope_output,
                "action": "summary",
                "selected_candidate_id": "",
                "target_node_id": attempt.get("node_id") or "",
                "branch_policy": {
                    **((envelope_output.get("branch_policy") if isinstance(envelope_output.get("branch_policy"), dict) else {})),
                    "blocked_reason": "budget_max",
                },
                "reason": "Reached maximum interaction budget; runtime forced safe summary.",
            }
        with self.conn:
            self.conn.execute(
                "update background_jobs set provider_mode = ?, route_meta_json = ? where id = ?",
                (
                    envelope.provider_mode,
                    db.json_dump({"route": "planner_decision", **route.audit_metadata(), **(envelope.route_meta or {})}),
                    job["id"],
                ),
            )
            run = self._record_model_agent_run_from_envelope(
                envelope,
                session_id=attempt["session_id"],
                trigger=f"v5_planner_decision:{flow_id}:{job['id']}",
                input_refs={
                    "flow_id": flow_id,
                    "attempt_id": attempt_id,
                    "candidate_packet_id": packet.get("packet_id", ""),
                    "source_agent_run_ids": payload.get("source_agent_run_ids") or [],
                },
                route=route,
            )
            decision = self._apply_planner_decision(
                flow=flow,
                attempt=attempt,
                source_step_id=str(payload.get("flow_step_id") or attempt.get("flow_step_id") or ""),
                decision_flow_revision=int(payload.get("flow_revision") or flow.get("flow_revision") or 1),
                output=envelope_output,
                planner_agent_run_id=run["id"],
                provider_mode=decision_provider_mode,
                candidate_packet=decision_packet,
                source_validation_ids=list(payload.get("source_evidence_validation_ids") or []),
                source_mastery_ids=list(payload.get("source_mastery_decision_ids") or []),
            )
            teaching_job_id = ""
            if decision.get("requires_teaching_generation"):
                teaching_payload = self._v5_stage_payload(
                    job=job,
                    attempt=attempt,
                    job_type="teaching_generation",
                    source_job_ids=[*(payload.get("source_job_ids") or []), job["id"]],
                    source_agent_run_ids=[*(payload.get("source_agent_run_ids") or []), run["id"]],
                    source_validation_ids=list(payload.get("source_evidence_validation_ids") or []),
                    source_mastery_ids=list(payload.get("source_mastery_decision_ids") or []),
                    candidate_packet=packet,
                    provider_mode=envelope.provider_mode,
                )
                teaching_payload.update({
                    "planner_decision_id": decision["id"],
                    "target_node_id": decision.get("target_node_id") or attempt.get("node_id"),
                    "action": action,
                })
                teaching_result = job_queue.JobQueue(self.conn).enqueue(
                    "teaching_generation",
                    f"v5:teaching_generation:{flow_id}:{flow.get('flow_revision')}:{decision['id']}:{teaching_payload['target_node_id']}:{action}",
                    teaching_payload,
                    depends_on_job_id=job["id"],
                    commit=False,
                )
                teaching_job_id = teaching_result.job_id
        return {
            "job_status": "succeeded",
            "attempt_id": attempt_id,
            "planner_job_id": job["id"],
            "planner_agent_run_id": run["id"],
            "next_step_decision_id": decision.get("id", ""),
            "next_action": decision.get("action") or action,
            "teaching_job_id": teaching_job_id,
        }

    def _normalize_planner_output_for_runtime(
        self,
        output: dict[str, Any],
        *,
        attempt: dict[str, Any],
        candidate_packet: dict[str, Any],
    ) -> dict[str, Any]:
        selected_candidate_id = str(output.get("selected_candidate_id") or "")
        candidates = {
            str(candidate.get("question_id") or ""): candidate
            for candidate in candidate_packet.get("candidates", [])
            if isinstance(candidate, dict)
        }
        selected = candidates.get(selected_candidate_id) or {}
        action = str(output.get("action") or "")
        if action == "near_transfer_retest" and selected:
            try:
                self._validate_planner_action_role(action=action, selected_candidate=selected)
            except model_router.ModelJSONParseError:
                try:
                    self._validate_planner_action_role(action="same_structure_retest", selected_candidate=selected)
                except model_router.ModelJSONParseError:
                    return output
                branch_policy = output.get("branch_policy") if isinstance(output.get("branch_policy"), dict) else {}
                return {
                    **output,
                    "action": "same_structure_retest",
                    "branch_policy": {
                        **branch_policy,
                        "runtime_normalization": "near_transfer_candidate_role_downgraded_to_same_structure",
                    },
                    "reason": (
                        "Planner requested near transfer, but the selected candidate only supports "
                        "same-structure confirmation; runtime downgraded the action instead of retrying."
                    ),
                }
        if action != "prerequisite_probe":
            return output
        source_node_id = str(attempt.get("node_id") or "")
        selected_node_id = str(selected.get("node_id") or "")
        target_node_id = str(output.get("target_node_id") or selected_node_id)
        if source_node_id and (selected_node_id == source_node_id or target_node_id == source_node_id):
            branch_policy = output.get("branch_policy") if isinstance(output.get("branch_policy"), dict) else {}
            return {
                **output,
                "action": "micro_teach",
                "selected_candidate_id": "",
                "target_node_id": source_node_id,
                "branch_policy": {
                    **branch_policy,
                    "uses_prerequisite_first": False,
                    "requires_teaching_generation": True,
                    "runtime_normalization": "self_prerequisite_probe_to_current_node_teaching",
                },
                "reason": (
                    "Planner selected the current node for a prerequisite probe; "
                    "runtime converted it to targeted teaching on the current node."
                ),
            }
        return output

    def _force_teaching_before_next_when_required(
        self,
        output: dict[str, Any],
        *,
        attempt: dict[str, Any],
        source_mastery_ids: list[str],
    ) -> dict[str, Any]:
        action = str(output.get("action") or "")
        if action not in {"same_structure_retest", "near_transfer_retest", "prerequisite_probe", "stretch"}:
            return output
        if not self._source_mastery_signal_requires_teaching(source_mastery_ids):
            return output
        branch_policy = output.get("branch_policy") if isinstance(output.get("branch_policy"), dict) else {}
        return {
            **output,
            "action": "micro_teach",
            "selected_candidate_id": "",
            "target_node_id": str(attempt.get("node_id") or output.get("target_node_id") or ""),
            "branch_policy": {
                **branch_policy,
                "requires_teaching_generation": True,
                "runtime_normalization": "evaluation_signal_requires_teaching_before_next",
            },
            "reason": (
                "Evaluation required teaching before the next question; "
                "runtime inserted a targeted teaching step before further practice."
            ),
        }

    def _source_mastery_signal_requires_teaching(self, source_mastery_ids: list[str]) -> bool:
        for mastery_id in source_mastery_ids:
            if not mastery_id:
                continue
            row = self.conn.execute(
                "select decision_payload_json from mastery_decisions where id = ?",
                (mastery_id,),
            ).fetchone()
            if not row:
                continue
            payload = db.json_load(row["decision_payload_json"], {})
            signal = payload.get("planner_signal")
            if not isinstance(signal, dict):
                evaluation_output = payload.get("evaluation_agent_output")
                if isinstance(evaluation_output, dict):
                    signal = evaluation_output.get("planner_signal")
            if isinstance(signal, dict) and signal.get("needs_teaching_before_next") is True:
                return True
        return False

    def _handle_teaching_generation_job(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = db.json_load(job.get("payload_json"), {})
        attempt_id = str(job.get("attempt_id") or payload.get("attempt_id") or "")
        flow_id = str(job.get("flow_id") or payload.get("flow_id") or "")
        if not flow_id or (not attempt_id and not payload.get("new_knowledge_request")):
            return {"job_status": "blocked", "reason": "missing_teaching_lineage"}
        attempt = db.get_attempt(self.conn, attempt_id) if attempt_id else {}
        flow = dict(self._flow_by_id(flow_id))
        if flow.get("status") in TERMINAL_FLOW_STATUSES:
            return {"job_status": "blocked", "reason": "terminal_flow", "attempt_id": attempt_id}
        route = model_router.teaching_route()
        provider_mode = str(job.get("provider_mode") or payload.get("provider_mode") or _provider_mode(route))
        recorded = payload.get("recorded_agent_output") if isinstance(payload.get("recorded_agent_output"), dict) else None
        if recorded is None and self._can_use_default_recorded_fixture(payload, provider_mode):
            recorded = self._default_recorded_teaching_output(attempt, payload)
        trusted_context = {
            "attempt_id": attempt_id,
            "graph_node": payload.get("graph_node") if isinstance(payload.get("graph_node"), dict) else {},
            "question_package": payload.get("question_package") if isinstance(payload.get("question_package"), dict) else {},
            "new_node_eligibility": payload.get("new_node_eligibility") if isinstance(payload.get("new_node_eligibility"), dict) else {},
        }
        if recorded is not None:
            trusted_context["recorded_agent_output"] = recorded
        envelope = semantic_agents.call_teaching_agent(semantic_agents.SemanticAgentRequest(
            agent_key="teaching_agent",
            phase="teaching_generation",
            trusted_context=trusted_context,
            untrusted_payload={"answer_analysis": attempt.get("answer_analysis") or {}},
            provider_mode=provider_mode,
            source_refs=payload,
        ))
        if envelope.status != "accepted":
            return {"job_status": "blocked", "reason": envelope.error_reason or "teaching_agent blocked", "attempt_id": attempt_id}
        current_flow = self._flow_by_id(flow_id)
        if current_flow and current_flow["status"] in TERMINAL_FLOW_STATUSES:
            return {"job_status": "blocked", "reason": "terminal_flow", "attempt_id": attempt_id}
        with self.conn:
            self.conn.execute(
                "update background_jobs set provider_mode = ?, route_meta_json = ? where id = ?",
                (
                    envelope.provider_mode,
                    db.json_dump({"route": "teaching_generation", **route.audit_metadata(), **(envelope.route_meta or {})}),
                    job["id"],
                ),
            )
            run = self._record_model_agent_run_from_envelope(
                envelope,
                session_id=attempt.get("session_id") or flow.get("legacy_session_id"),
                trigger=f"v5_teaching_generation:{flow_id}:{job['id']}",
                input_refs={
                    "flow_id": flow_id,
                    "attempt_id": attempt_id,
                    "planner_decision_id": payload.get("planner_decision_id", ""),
                    "target_node_id": payload.get("target_node_id", ""),
                    "new_knowledge_request": bool(payload.get("new_knowledge_request")),
                    "source_agent_run_ids": payload.get("source_agent_run_ids") or [],
                },
                route=route,
            )
            source_decision_id = str(payload.get("planner_decision_id") or "")
            if payload.get("new_knowledge_request") and not source_decision_id:
                decision = self._record_next_step_decision(
                    flow=flow,
                    action="continue_new_knowledge",
                    report_label="confirmed" if envelope.provider_mode == "live_model" else envelope.provider_mode,
                    source_step_id="",
                    source_attempt_ids=[],
                    source_validation_ids=[],
                    provider_mode=envelope.provider_mode,
                    reason=str(envelope.output.get("source_reason") or "accepted new-knowledge teaching package"),
                    target_node_id=str(payload.get("target_node_id") or envelope.output.get("target_node_id") or ""),
                    planner_agent_run_id=run["id"],
                    branch_policy={"new_knowledge": True},
                )
                source_decision_id = decision["id"]
            existing_step = self._visible_step_for_next_step_decision(flow_id, source_decision_id)
            if existing_step:
                return {
                    "job_status": "succeeded",
                    "attempt_id": attempt_id,
                    "teaching_job_id": job["id"],
                    "teaching_agent_run_id": run["id"],
                    "teaching_step_id": existing_step["id"],
                }
            step_id = self._materialize_teaching_step_from_agent(
                flow=flow,
                attempt=attempt,
                source_step_id=str(payload.get("flow_step_id") or attempt.get("flow_step_id") or ""),
                source_next_step_decision_id=source_decision_id,
                payload=payload,
                teaching_output=envelope.output,
                teaching_agent_run_id=run["id"],
            )
            updated = self.conn.execute(
                """
                update daily_flows
                set status = 'reviewing',
                    current_step_id = ?,
                    flow_revision = flow_revision + 1,
                    updated_at = ?
                where id = ?
                  and status not in ('completed','superseded')
                """,
                (step_id, db.now_iso(), flow_id),
            )
            if updated.rowcount == 0:
                self.conn.execute(
                    "update flow_steps set status = 'superseded', updated_at = ? where id = ?",
                    (db.now_iso(), step_id),
                )
                return {"job_status": "blocked", "reason": "terminal_flow", "attempt_id": attempt_id}
        return {
            "job_status": "succeeded",
            "attempt_id": attempt_id,
            "teaching_job_id": job["id"],
            "teaching_agent_run_id": run["id"],
            "teaching_step_id": step_id,
        }

    def _answer_analysis_request(
        self,
        *,
        job: dict[str, Any],
        attempt: dict[str, Any],
        question: dict[str, Any],
        provider_mode: str,
        photo_ocr: dict[str, Any] | None = None,
        recorded_output: dict[str, Any] | None = None,
        answer_contract: dict[str, Any] | None = None,
    ) -> semantic_agents.SemanticAgentRequest:
        graph_node = db.get_graph_node(self.conn, attempt["node_id"])
        trusted_context = {
            "question_package": {
                "question_id": question["id"],
                "node_id": question["node_id"],
                "prompt": question["prompt"],
                "interaction_schema": question_bank.normalize_question_interaction_schema(question.get("interaction_schema")) or {},
                "reference_answer": question["expected_answer"],
                "answer_format": question.get("answer_format"),
                "rubric": question.get("rubric") or {},
                "solution_steps": question.get("solution_steps") or [],
                "kind": question.get("kind") or question.get("variant_level"),
                "difficulty_vector": question.get("difficulty_vector") or {},
            },
            "graph_node": {
                "id": graph_node.get("id"),
                "name": graph_node.get("name"),
                "essence_for_child": graph_node.get("essence_for_child"),
                "mastery_criteria": graph_node.get("mastery_criteria") or [],
            },
            "lineage": {
                "flow_id": str(job.get("flow_id") or ""),
                "flow_step_id": attempt.get("flow_step_id"),
                "attempt_version": attempt.get("attempt_version"),
                "graph_version": attempt.get("graph_version"),
                "question_bank_version": attempt.get("question_bank_version"),
            },
        }
        if recorded_output is not None:
            trusted_context["recorded_agent_output"] = recorded_output
        if answer_contract is not None:
            trusted_context["answer_contract"] = {
                "contract_id": answer_contract["id"],
                "contract_version": answer_contract["contract_version"],
                "contract_digest_sha256": answer_contract[
                    "contract_digest_sha256"
                ],
                "reference_solution": answer_contract["reference_solution"],
                "criteria": [
                    {
                        "criterion_key": point["key"],
                        "criterion": point["criterion"],
                        "dimension": point["dimension"],
                        "required_for_pass": point["required_for_pass"],
                    }
                    for point in answer_contract["score_points"]
                ],
            }
        return semantic_agents.SemanticAgentRequest(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            trusted_context=trusted_context,
            untrusted_payload={
                "child_answer_text": attempt.get("answer_raw") or "",
                "answer_source": attempt.get("answer_source") or "",
                "interaction_response": attempt.get("interaction_response") if isinstance(attempt.get("interaction_response"), dict) else {},
                "photo_ocr_evidence": photo_ocr,
            },
            provider_mode=provider_mode,
            source_refs=db.json_load(job.get("payload_json"), {}),
        )

    def _semantic_answer_output_from_legacy_review(self, review: dict[str, Any]) -> dict[str, Any]:
        analysis = review.get("analysis") if isinstance(review.get("analysis"), dict) else {}
        support = analysis.get("evaluation_support") if isinstance(analysis.get("evaluation_support"), dict) else {}
        if not support:
            support = {
                "usable_for_evaluation": not bool(review.get("blocking_evidence")),
                "evidence_strength": "strong" if review.get("result") == "correct" else "limited",
                "reasoning_soundness": "sound" if int(review.get("explanation_score") or 0) >= 2 else "unclear",
                "dominant_gap_dimensions": list(review.get("error_tags") or []),
            }
        return {
            "schema_version": "2026-07-11.answer-review.v5.schema.v2",
            "result": str(review.get("result") or "partial"),
            "score_points": float(review.get("score_points") or 0),
            "max_points": float(review.get("max_points") or 2),
            "confidence": float(review.get("confidence") or (review.get("ai_review") or {}).get("confidence") or 0),
            "error_tags": list(review.get("error_tags") or []),
            "blocking_evidence": bool(review.get("blocking_evidence")),
            "answer_analysis": analysis,
            "evaluation_support": support,
            "next_evidence_need": "prerequisite_probe" if review.get("blocking_evidence") else "near_transfer_confirmation",
        }

    def _grade_from_answer_agent_output(
        self,
        output: dict[str, Any],
        *,
        route: model_router.ModelRoute,
        provider_mode: str,
        photo_ocr: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = str(output.get("result") or "partial")
        score_points = float(output.get("score_points") if output.get("score_points") is not None else (2 if result == "correct" else (1 if result == "partial" else 0)))
        max_points = float(output.get("max_points") or 2)
        answer_analysis = self._normalize_answer_analysis_for_attempt(
            output.get("answer_analysis") if isinstance(output.get("answer_analysis"), dict) else {},
            result=result,
            error_tags=output.get("error_tags") if isinstance(output.get("error_tags"), list) else [],
            blocking_evidence=bool(output.get("blocking_evidence")),
        )
        comparison = answer_analysis.get("comparison") if isinstance(answer_analysis.get("comparison"), list) else []
        explanation_score = 2 if result == "correct" and any(
            isinstance(item, dict) and item.get("status") == "matched" for item in comparison
        ) else (1 if result == "partial" else 0)
        canonical_error_tags = self._canonical_error_tags_for_answer_output(
            output,
            answer_analysis=answer_analysis,
            result=result,
        )
        return {
            "result": result,
            "score_points": score_points,
            "max_points": max_points,
            "error_tags": canonical_error_tags,
            "parent_note": _child_safe_text(
                answer_analysis.get("teaching_explanation") or answer_analysis.get("process_gap") or output.get("next_evidence_need") or "Answer analysis accepted.",
                "Answer analysis accepted.",
                limit=500,
            ),
            "answer_analysis": {
                **answer_analysis,
            },
            "review_meta": {
                "status": "graded",
                "provider": route.provider if route.enabled else "",
                "model": route.model if route.enabled else "",
                "model_alias": route.model_alias if route.enabled else "",
                "provider_mode": provider_mode,
                "confidence": float(output.get("confidence") or 0.0),
                "vision": photo_ocr,
                "raw_error_tags": [str(tag) for tag in (output.get("error_tags") or []) if str(tag).strip()],
            },
            "explanation_score": explanation_score,
            "blocking_evidence": bool(output.get("blocking_evidence")),
        }

    def _canonical_error_tags_for_answer_output(
        self,
        output: dict[str, Any],
        *,
        answer_analysis: dict[str, Any],
        result: str,
    ) -> list[str]:
        if result == "correct":
            return []
        canonical: list[str] = []

        def add(tag: str) -> None:
            if tag in question_bank.CANONICAL_ERROR_TAGS and tag not in canonical:
                canonical.append(tag)

        def map_tag(raw_tag: Any) -> str:
            text = str(raw_tag or "").strip().lower()
            if text in question_bank.CANONICAL_ERROR_TAGS:
                return text
            if any(token in text for token in ("visual", "diagram", "geometry", "spatial", "图形", "空间")):
                return "visual_spatial"
            if any(token in text for token in ("model", "relation", "reading", "condition", "omitted", "missed", "solution", "quantity", "模型", "关系", "漏", "条件")):
                return "modeling_or_reading"
            if any(token in text for token in ("concept", "absolute", "definition", "property", "equivalence", "概念", "定义", "性质", "绝对值")):
                return "concept_confusion"
            if any(token in text for token in ("symbol", "sign", "negative", "minus", "calculate", "calculation", "arithmetic", "notation", "符号", "负号", "计算")):
                return "calculation_or_symbol"
            if any(token in text for token in ("step", "process", "check", "explain", "verify", "过程", "步骤", "检验", "解释")):
                return "process_habit"
            return "general"

        for raw_tag in output.get("error_tags") or []:
            add(map_tag(raw_tag))
        support = answer_analysis.get("evaluation_support")
        if not isinstance(support, dict):
            support = db.derive_answer_evaluation_support(answer_analysis)
        for dimension in support.get("dominant_gap_dimensions") or []:
            add(auto_review.DIMENSION_GAP_ERROR_TAGS.get(str(dimension), "general"))
        if not canonical:
            add("general")
        return canonical[:4]

    def _normalize_answer_analysis_for_attempt(
        self,
        analysis: dict[str, Any],
        *,
        result: str | None = None,
        error_tags: list[Any] | None = None,
        blocking_evidence: bool = False,
    ) -> dict[str, Any]:
        normalized = dict(analysis)
        normalized["agent_key"] = "answer_analysis_agent"
        raw_gap = str(normalized.get("process_gap") or "").strip()
        if self._answer_analysis_gap_text_means_no_gap(raw_gap):
            raw_gap = ""
        result_value = str(result or "").strip().lower()
        raw_error_tags = [str(tag).strip() for tag in (error_tags or []) if str(tag).strip()]
        has_non_correct_signal = (
            result_value in {"partial", "wrong", "unclear"}
            or bool(raw_error_tags)
            or bool(blocking_evidence)
            or bool(raw_gap)
        )
        comparison = []
        for raw_item in normalized.get("comparison", []):
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            dimension = self._normalize_answer_analysis_dimension(item.get("dimension"))
            if dimension not in db.ANALYSIS_DIMENSIONS:
                continue
            status = self._normalize_answer_analysis_status(
                item.get("status", item.get("judgment", item.get("result")))
            )
            if status not in db.ANALYSIS_STATUSES:
                status = "unclear"
            detail = str(item.get("detail") or item.get("evidence") or item.get("review") or "").strip()
            item.update({"dimension": dimension, "status": status, "detail": detail})
            comparison.append(item)
        by_dimension = {str(item.get("dimension")): item for item in comparison}
        defaults = {
            "final_answer": "最终答案按模型输出的结果判断。",
            "symbols_units": "符号、格式或单位没有发现阻塞证据。",
            "model_or_relation": "核心关系按模型输出判断。",
            "steps": "关键步骤按模型输出判断。",
            "check_or_explanation": "检验或解释按模型输出判断。",
        }
        for dimension, detail in defaults.items():
            if dimension not in by_dimension:
                default_status = "matched"
                if has_non_correct_signal:
                    default_status = "incorrect" if result_value == "wrong" and dimension == "final_answer" else "unclear"
                    detail = "模型没有给出这一维度的可靠比较，暂不能作为掌握证据。"
                by_dimension[dimension] = {"dimension": dimension, "status": default_status, "detail": detail}
            elif not str(by_dimension[dimension].get("detail") or "").strip():
                by_dimension[dimension]["detail"] = defaults[dimension]
        normalized["comparison"] = [by_dimension[key] for key in ("final_answer", "model_or_relation", "steps", "symbols_units", "check_or_explanation")]
        normalized.setdefault("alternative_solutions", [])
        normalized["process_gap"] = raw_gap
        weak_dimensions = [
            str(item.get("dimension"))
            for item in normalized["comparison"]
            if item.get("status") in db.WEAK_ANALYSIS_STATUSES
        ]
        if has_non_correct_signal and not weak_dimensions:
            forced_dimensions = self._answer_analysis_forced_gap_dimensions(
                result=result_value,
                process_gap=raw_gap,
                error_tags=raw_error_tags,
            )
            if not forced_dimensions:
                forced_dimensions = ["model_or_relation", "steps", "check_or_explanation"]
            detail = raw_gap or "模型总评和分维度比较不一致，系统按保守规则保留过程缺口。"
            for item in normalized["comparison"]:
                dimension = str(item.get("dimension") or "")
                if dimension not in forced_dimensions:
                    continue
                if dimension == "final_answer" and result_value == "wrong":
                    item["status"] = "incorrect"
                elif dimension in {"model_or_relation", "symbols_units"} and result_value == "wrong":
                    item["status"] = "incorrect"
                else:
                    item["status"] = "missing" if result_value != "unclear" else "unclear"
                item["detail"] = detail
            weak_dimensions = [
                str(item.get("dimension"))
                for item in normalized["comparison"]
                if item.get("status") in db.WEAK_ANALYSIS_STATUSES
            ]
        if weak_dimensions and not normalized["process_gap"]:
            normalized["process_gap"] = "本次答案还不能作为完整掌握证据：模型总评、错误标签或分维度比较显示存在过程缺口。"
        has_gap = any(item.get("status") in {"missing", "weak", "unclear"} for item in normalized["comparison"])
        normalized["no_gap_observed"] = not has_gap and not bool(str(normalized.get("process_gap") or "").strip())
        normalized["evaluation_support"] = db.derive_answer_evaluation_support(normalized)
        return normalized

    def _normalize_answer_analysis_dimension(self, raw_dimension: Any) -> str:
        text = str(raw_dimension or "").strip().lower().replace("-", "_")
        text = "_".join(text.replace("/", " ").split())
        aliases = {
            "final_answer": "final_answer",
            "answer": "final_answer",
            "conclusion": "final_answer",
            "model": "model_or_relation",
            "relation": "model_or_relation",
            "model_or_relation": "model_or_relation",
            "model_relation": "model_or_relation",
            "steps": "steps",
            "step": "steps",
            "steps_and_transformations": "steps",
            "procedure": "steps",
            "notation": "symbols_units",
            "notation_and_signs": "symbols_units",
            "symbols": "symbols_units",
            "signs": "symbols_units",
            "symbols_units": "symbols_units",
            "unit": "symbols_units",
            "units": "symbols_units",
            "justification": "check_or_explanation",
            "check": "check_or_explanation",
            "explanation": "check_or_explanation",
            "check_or_justification": "check_or_explanation",
            "check_or_explanation": "check_or_explanation",
        }
        return aliases.get(text, text)

    def _normalize_answer_analysis_status(self, raw_status: Any) -> str:
        text = str(raw_status or "").strip().lower().replace("-", "_")
        text = "_".join(text.split())
        aliases = {
            "correct": "matched",
            "right": "matched",
            "ok": "matched",
            "valid": "matched",
            "matched": "matched",
            "match": "matched",
            "matches": "matched",
            "alternative_valid": "alternative_valid",
            "valid_alternative": "alternative_valid",
            "wrong": "incorrect",
            "incorrect": "incorrect",
            "invalid": "incorrect",
            "missing": "missing",
            "incomplete": "missing",
            "partial": "missing",
            "weak": "missing",
            "unclear": "unclear",
            "ambiguous": "unclear",
            "unknown": "unclear",
        }
        return aliases.get(text, text)

    def _answer_analysis_gap_text_means_no_gap(self, gap_text: str) -> bool:
        text = str(gap_text or "").strip().lower()
        if not text:
            return False
        no_gap_markers = (
            "没有明显过程缺口",
            "无明显过程缺口",
            "没有过程缺口",
            "无过程缺口",
            "no obvious process gap",
            "no process gap",
        )
        return any(marker in text for marker in no_gap_markers)

    def _answer_analysis_forced_gap_dimensions(
        self,
        *,
        result: str,
        process_gap: str,
        error_tags: list[str],
    ) -> list[str]:
        dimensions: list[str] = []

        def add(dimension: str) -> None:
            if dimension in db.REQUIRED_ANALYSIS_DIMENSIONS and dimension not in dimensions:
                dimensions.append(dimension)

        if result == "wrong":
            add("final_answer")
        joined = " ".join([process_gap, *error_tags]).lower()
        if any(token in joined for token in ("answer", "final", "conclusion", "答案", "结论", "漏掉", "少了")):
            add("final_answer")
        if any(token in joined for token in ("model", "relation", "concept", "condition", "absolute", "equivalence", "模型", "关系", "概念", "条件", "绝对值", "性质")):
            add("model_or_relation")
        if any(token in joined for token in ("step", "process", "procedure", "transform", "步骤", "过程", "变形", "推导")):
            add("steps")
        if any(token in joined for token in ("symbol", "sign", "negative", "minus", "unit", "bracket", "符号", "负号", "单位", "括号")):
            add("symbols_units")
        if any(token in joined for token in ("check", "verify", "explain", "reason", "检验", "验算", "解释", "说明")):
            add("check_or_explanation")
        return dimensions

    def _blocked_v5_agent_stage(
        self,
        job: dict[str, Any],
        *,
        agent_key: str,
        phase: str,
        reason: str,
    ) -> dict[str, Any]:
        payload = db.json_load(job.get("payload_json"), {})
        envelope = semantic_agents.blocked_envelope(
            agent_key=agent_key,
            phase=phase,
            provider_mode=str(job.get("provider_mode") or payload.get("provider_mode") or "not_configured"),
            reason=reason,
        )
        return {
            "job_status": "blocked",
            "stage": phase,
            "agent_key": agent_key,
            "reason": reason,
            "attempt_id": str(job.get("attempt_id") or payload.get("attempt_id") or ""),
            "flow_id": str(job.get("flow_id") or payload.get("flow_id") or ""),
            "model_envelope": envelope.as_result_refs(),
        }

    def _latest_passed_validation(self, attempt_id: str, payload: dict[str, Any]) -> evidence_gate.EvidenceValidationResult | None:
        validation_ids = [str(item) for item in (payload.get("source_evidence_validation_ids") or []) if item]
        params: list[Any]
        where = "id = ?" if validation_ids else "attempt_id = ?"
        params = [validation_ids[-1] if validation_ids else attempt_id]
        row = self.conn.execute(
            f"""
            select *
            from evidence_validations
            where {where}
            order by created_at desc, id desc
            limit 1
            """,
            params,
        ).fetchone()
        if not row or row["gate_status"] != "passed":
            return None
        predicate_data = db.json_load(row["predicate_result_json"], {})
        predicate = evidence_gate.EvidencePredicateResult(
            usable=bool(predicate_data.get("usable", True)),
            projection_status=str(predicate_data.get("projection_status") or "usable"),
            failed_fields=tuple(predicate_data.get("failed_fields") or []),
            report_label=str(predicate_data.get("report_label") or "confirmed"),
        )
        return evidence_gate.EvidenceValidationResult(
            validation_id=row["id"],
            gate_status=row["gate_status"],
            predicate=predicate,
        )

    def _evaluation_trusted_context(
        self,
        *,
        attempt: dict[str, Any],
        validation: evidence_gate.EvidenceValidationResult,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        node_id = str(attempt.get("node_id") or "")
        graph_version = str(attempt.get("graph_version") or "")
        bank_version = str(attempt.get("question_bank_version") or "")
        graph_node = db.get_graph_node(self.conn, node_id)
        evidence_rows = self.conn.execute(
            """
            select ev.*, a.result, a.score_points, a.max_points, a.explanation_score,
                   a.blocking_evidence, a.analysis_status, a.analysis_version,
                   q.kind, q.question_type, q.variant_level, q.raw_json
            from evidence_validations ev
            join attempts a on a.id = ev.attempt_id
            left join question_items q on q.id = ev.question_id
            where ev.created_at <= ?
            order by ev.created_at desc, ev.id desc
            limit 80
            """,
            (db.now_iso(),),
        ).fetchall()
        usable: list[dict[str, Any]] = []
        exclusions = {
            "pending": 0,
            "stale": 0,
            "mock_only": 0,
            "missing_lineage": 0,
            "other_node": 0,
            "not_passed": 0,
        }
        for row in evidence_rows:
            predicate = db.json_load(row["predicate_result_json"], {})
            provider = str(row["provider_mode"] or "")
            if row["node_id"] != node_id:
                exclusions["other_node"] += 1
                continue
            if row["gate_status"] != "passed" or not bool(predicate.get("usable", True)):
                exclusions["not_passed"] += 1
                continue
            if provider in {"mock_only", "not_configured", "pending", "deterministic_runtime"}:
                exclusions["mock_only" if provider == "mock_only" else "pending"] += 1
                continue
            if row["graph_version"] != graph_version or row["question_bank_version"] != bank_version:
                exclusions["stale"] += 1
                continue
            raw = db.json_load(row["raw_json"], {})
            if not row["answer_analysis_agent_run_id"] or not row["question_id"] or not row["question_bank_version"]:
                exclusions["missing_lineage"] += 1
                continue
            kind = str(row["kind"] or row["variant_level"] or "")
            usable.append({
                "attempt_id": row["attempt_id"],
                "evidence_validation_id": row["id"],
                "answer_analysis_agent_run_id": row["answer_analysis_agent_run_id"],
                "question_id": row["question_id"],
                "question_kind": kind,
                "question_family": row["question_type"] or raw.get("question_type") or "",
                "core_stem_id": raw.get("core_stem_id") or raw.get("math_core_signature") or row["question_id"],
                "difficulty_vector": raw.get("difficulty_vector") if isinstance(raw.get("difficulty_vector"), dict) else {},
                "evidence_role": "near_transfer" if kind in {"transfer_retest", "near_transfer"} else "direct",
                "result": row["result"],
                "score_ratio": float(row["score_points"] or 0) / max(float(row["max_points"] or 1), 1.0),
                "explanation_score": row["explanation_score"],
                "blocking_evidence": bool(row["blocking_evidence"]),
                "provider_mode": provider,
                "trust_label": predicate.get("report_label") or provider,
            })
            if len(usable) >= 8:
                break
        usable.reverse()
        return {
            "attempt_id": attempt["id"],
            "node_id": node_id,
            "evidence_validation_id": validation.validation_id,
            "source_agent_run_ids": payload.get("source_agent_run_ids") or [],
            "node_mastery_criteria": graph_node.get("mastery_criteria") or [],
            "node_summary": {
                "name": graph_node.get("name"),
                "essence_for_child": graph_node.get("essence_for_child"),
            },
            "recent_usable_evidence": usable,
            "evidence_exclusion_counts": exclusions,
            "current_status": self._learner_status_for_node(node_id),
        }

    def _learner_status_for_node(self, node_id: str) -> dict[str, Any]:
        row = self.conn.execute("select * from learner_node_status where node_id = ?", (node_id,)).fetchone()
        return dict(row) if row else {}

    def _planner_trusted_context(
        self,
        *,
        flow: dict[str, Any],
        attempt: dict[str, Any],
        payload: dict[str, Any],
        packet: dict[str, Any],
        recorded_output: dict[str, Any] | None,
    ) -> dict[str, Any]:
        context = {
            "flow_id": flow["id"],
            "attempt_id": attempt["id"],
            "accepted_evaluation_summary": payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {},
            "interaction_budget": self._interaction_budget(flow),
            "pending_summary": self._pending_summary_for_flow(flow["id"]),
            "recent_steps": self._recent_step_summaries(flow["id"]),
            "flow_snapshot": {
                "status": flow.get("status"),
                "flow_revision": flow.get("flow_revision"),
                "graph_version": flow.get("graph_version"),
                "question_bank_version": flow.get("question_bank_version"),
            },
            "candidate_packet": packet,
        }
        if recorded_output is not None:
            context["recorded_agent_output"] = recorded_output
        return context

    def _interaction_budget(self, flow: dict[str, Any]) -> dict[str, int]:
        completed = self.conn.execute(
            """
            select count(*)
            from flow_steps
            where flow_id = ?
              and status in ('completed','analyzing')
            """,
            (flow["id"],),
        ).fetchone()[0]
        minimum = int(flow.get("budget_min") or 10)
        maximum = int(flow.get("budget_max") or 20)
        return {
            "minimum": minimum,
            "maximum": maximum,
            "completed_interactions": int(completed),
            "remaining_to_minimum": max(minimum - int(completed), 0),
            "remaining_to_maximum": max(maximum - int(completed), 0),
        }

    def _pending_summary_for_flow(self, flow_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            select a.id
            from attempts a
            join flow_steps s on s.id = a.flow_step_id
            where s.flow_id = ?
              and (a.grading_status != 'graded' or a.analysis_status in ('missing','operator_attention_required'))
            order by a.created_at desc
            limit 8
            """,
            (flow_id,),
        ).fetchall()
        ids = [row["id"] for row in rows]
        return {"count": len(ids), "attempt_ids": ids}

    def _recent_step_summaries(self, flow_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select position, step_type, status, node_id, question_bank_version
            from flow_steps
            where flow_id = ?
            order by position desc, created_at desc
            limit 8
            """,
            (flow_id,),
        ).fetchall()
        summaries = [
            {
                "position": row["position"],
                "step_type": row["step_type"],
                "status": row["status"],
                "node_id": row["node_id"],
                "question_bank_version": row["question_bank_version"],
            }
            for row in rows
        ]
        return sorted(summaries, key=lambda item: int(item["position"] or 0))

    def _v5_stage_payload(
        self,
        *,
        job: dict[str, Any],
        attempt: dict[str, Any],
        job_type: str,
        source_job_ids: list[str] | None = None,
        source_agent_run_ids: list[str] | None = None,
        source_validation_ids: list[str] | None = None,
        source_mastery_ids: list[str] | None = None,
        candidate_packet: dict[str, Any] | None = None,
        provider_mode: str = "not_configured",
    ) -> dict[str, Any]:
        payload = db.json_load(job.get("payload_json"), {})
        packet = candidate_packet or {}
        stage_payload = {
            "payload_schema_version": job_queue.V5_JOB_PAYLOAD_SCHEMA_VERSION,
            "job_type": job_type,
            "legacy_session_id": attempt["session_id"],
            "flow_id": str(job.get("flow_id") or payload.get("flow_id") or ""),
            "flow_revision": int(job.get("flow_revision") or payload.get("flow_revision") or 1),
            "flow_step_id": str(job.get("flow_step_id") or payload.get("flow_step_id") or attempt.get("flow_step_id") or ""),
            "step_revision": int(job.get("step_revision") or payload.get("step_revision") or 1),
            "attempt_id": attempt["id"],
            "attempt_version": int(attempt.get("attempt_version") or 1),
            "analysis_version": int(attempt.get("analysis_version") or 0),
            "graph_version": attempt.get("graph_version") or "",
            "question_bank_version": attempt.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION,
            "node_id": attempt.get("node_id") or "",
            "question_id": attempt.get("question_id") or "",
            "review_record_id": attempt.get("review_record_id") or "",
            "source_job_ids": [item for item in (source_job_ids or []) if item],
            "source_agent_run_ids": [item for item in (source_agent_run_ids or []) if item],
            "source_evidence_validation_ids": [item for item in (source_validation_ids or []) if item],
            "source_mastery_decision_ids": [item for item in (source_mastery_ids or []) if item],
            "candidate_packet_id": str(packet.get("packet_id") or ""),
            "candidate_packet_hash": str(packet.get("packet_hash") or ""),
            "candidate_packet": packet,
            "provider_mode": provider_mode,
            "route_meta": {"provider_mode": provider_mode, "source": "v5_durable_dag"},
        }
        if provider_mode in {"recorded_model", "mock_only"}:
            stage_payload["recorded_fixture_path"] = f"runtime://v5/default-fixtures/{job_type}"
            stage_payload["route_meta"]["recorded_fixture_path"] = stage_payload["recorded_fixture_path"]
        return stage_payload

    def _can_use_default_recorded_fixture(self, payload: dict[str, Any], provider_mode: str) -> bool:
        if provider_mode not in {"recorded_model", "mock_only"}:
            return False
        if payload.get("recorded_fixture_path") or payload.get("recorded_fixture_id"):
            return True
        route_meta = payload.get("route_meta")
        if isinstance(route_meta, dict) and (route_meta.get("recorded_fixture_path") or route_meta.get("recorded_fixture_id")):
            return True
        if isinstance(route_meta, dict) and str(route_meta.get("source") or "").startswith("v5_red_contract_test"):
            return True
        return False

    def _default_recorded_evaluation_output(
        self,
        attempt: dict[str, Any],
        validation: evidence_gate.EvidenceValidationResult,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        support = (attempt.get("answer_analysis") or {}).get("evaluation_support")
        if not isinstance(support, dict):
            support = {}
        is_gap = bool(attempt.get("result") in {"partial", "wrong"} or attempt.get("blocking_evidence"))
        next_goal = "prerequisite_probe" if attempt.get("blocking_evidence") else ("same_structure_retest" if is_gap else "near_transfer_retest")
        return {
            "schema_version": "2026-07-11.evaluation-decision.v5.schema.v2",
            "node_id": attempt.get("node_id") or "",
            "source_evidence_validation_ids": [validation.validation_id] if validation.validation_id else [],
            "source_answer_analysis_agent_run_ids": list(payload.get("source_agent_run_ids") or []),
            "mastery_recommendation": "weak" if is_gap else "emerging",
            "dimension_scores": {
                "concept": 0.6,
                "model_relation": 0.6,
                "procedure": 0.6,
                "calculation": 0.6,
                "expression_notation": 0.6,
                "transfer": 0.3,
            },
            "planner_signal": {
                "next_evidence_goal": next_goal,
                "needs_teaching_before_next": is_gap,
                "needs_prerequisite_probe": bool(attempt.get("blocking_evidence")),
                "target_gap_dimensions": list(support.get("dominant_gap_dimensions") or [])[:6],
            },
            "confidence": 0.84,
            "reason": "Recorded fixture evaluation envelope derived from accepted answer evidence.",
        }

    def _default_recorded_teaching_output(self, attempt: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        analysis = attempt.get("answer_analysis") or {}
        explanation = _child_safe_text(
            analysis.get("teaching_explanation")
            or analysis.get("process_gap")
            or "先把关键关系写清楚，再做计算和检查。",
            "先把关键关系写清楚，再做计算和检查。",
            limit=420,
        )
        return {
            "schema_version": "2026-07-12.teaching-step.v5.schema.v3",
            "target_node_id": str(payload.get("target_node_id") or attempt.get("node_id") or ""),
            "teaching_step_type": "worked_example" if payload.get("action") == "worked_example" else "teaching_repair",
            "child_title": "先修这一处",
            "teaching_sections": {
                "essence": {
                    "title": "本质",
                    "body": explanation,
                },
                "core_model": {
                    "title": "核心关系",
                    "body": "先找等量关系，再让每一步变形都同时作用在等式两边。",
                },
                "worked_example": {
                    "title": "例题",
                    "problem": "看清题目里的关系，先写出第一步等式变形。",
                    "steps": ["标出已知量和未知量。", "按同一个规则处理等式两边。", "算完后代回原题检查。"],
                    "check": "检查每一项都被同样处理，最后答案能代回原式。",
                },
                "why_it_works": {
                    "title": "为什么成立",
                    "body": "等式两边做同一种允许的变形，关系不会被改变。",
                },
                "next_micro_check": {
                    "title": "小检查",
                    "prompt": "请先说出下一步应该同时处理等式的哪两边。",
                },
            },
            "next_child_action": "看完后继续做一题小检查。",
            "allowed_response_modes": ["continue", "stuck"],
            "confidence": 0.82,
            "source_reason": str(payload.get("action") or "micro_teach"),
        }

    def _candidate_packet_for_planner(self, flow: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
        node_id = str(attempt.get("node_id") or "")
        if attempt.get("blocking_evidence") or attempt.get("result") == "wrong":
            packet = self._bounded_prerequisite_candidate_packet_for_planner(flow, attempt)
            if packet and packet.get("candidate_count"):
                return packet
        source_phase = ""
        if attempt.get("flow_step_id"):
            row = self.conn.execute(
                "select selection_reason_json from flow_steps where id = ?",
                (attempt.get("flow_step_id"),),
            ).fetchone()
            source_reason = db.json_load(row["selection_reason_json"], {}) if row else {}
            source_phase = str(source_reason.get("new_knowledge_phase") or "")
        intent = "general"
        next_goal = ""
        stable_context = {"supported": False, "learner_status": "", "prerequisite_ready": False}
        result = str(attempt.get("result") or "")
        if source_phase in {"micro_check", "repair_check"} and result != "correct":
            intent = "partial_unstable"
        elif result == "partial":
            intent = "partial_unstable"
        elif result == "correct":
            stable_context = self._stable_ready_context(str(attempt.get("node_id") or ""))
            if stable_context["supported"]:
                intent = "stable_ready"
                next_goal = "stretch_readiness"
            else:
                intent = "correct_narrow"
                next_goal = "near_transfer_retest"
        packet = question_bank.QuestionBankService.candidate_packet_for_node(
            self.conn,
            node_id=node_id,
            graph_version=flow["graph_version"],
            flow_id=flow["id"],
            flow_revision=int(flow.get("flow_revision") or 1),
            limit=8,
            exclusions={"recent_question_ids": sorted(self._recent_question_ids_for_flow(flow["id"]))},
            question_bank_version=str(flow.get("question_bank_version") or attempt.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION),
            selection_intent=intent,
            next_evidence_goal=next_goal,
            learner_status=stable_context["learner_status"] if attempt.get("result") == "correct" else "",
            prerequisite_ready=stable_context["prerequisite_ready"] if attempt.get("result") == "correct" else False,
        )
        packet = self._filter_recent_prompt_repetition(packet, flow["id"])
        candidates = list(packet.get("candidates") or [])[:8]
        packet["candidates"] = candidates
        packet["candidate_count"] = len(candidates)
        if not packet.get("packet_hash"):
            packet["packet_hash"] = db._digest_json(packet)
        return packet

    def _bounded_prerequisite_candidate_packet_for_planner(
        self,
        flow: dict[str, Any],
        attempt: dict[str, Any],
    ) -> dict[str, Any] | None:
        source_node_id = str(attempt.get("node_id") or "")
        rollback_nodes = self._direct_rollback_node_ids(source_node_id)
        if not rollback_nodes:
            return None
        recent_question_ids = sorted(self._recent_question_ids_for_flow(flow["id"]))
        flow_revision = int(flow.get("flow_revision") or 1)
        target_error_tags = [str(tag) for tag in (attempt.get("error_tags") or []) if str(tag)]
        aggregate_filter: dict[str, int] = {}
        candidates: list[dict[str, Any]] = []
        per_node_limit = 2 if len(rollback_nodes) <= 4 else 1
        for target_node_id in rollback_nodes:
            packet = question_bank.QuestionBankService.candidate_packet_for_node(
                self.conn,
                node_id=target_node_id,
                graph_version=flow["graph_version"],
                flow_id=flow["id"],
                flow_revision=flow_revision,
                limit=per_node_limit,
                exclusions={"recent_question_ids": recent_question_ids},
                question_bank_version=str(flow.get("question_bank_version") or attempt.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION),
                selection_intent="wrong_blocking",
            )
            for key, value in (packet.get("filter_summary") or {}).items():
                if isinstance(value, int):
                    aggregate_filter[key] = aggregate_filter.get(key, 0) + value
            for candidate in list(packet.get("candidates") or [])[:per_node_limit]:
                if len(candidates) >= 8:
                    break
                enriched = dict(candidate)
                candidate_tags = [str(tag) for tag in (enriched.get("target_error_tags") or []) if str(tag)]
                merged_tags = list(dict.fromkeys([*target_error_tags, *candidate_tags]))
                enriched.update({
                    "relation": "direct_prerequisite",
                    "source_node_id": source_node_id,
                    "target_node_id": target_node_id,
                    "target_error_tags": merged_tags,
                    "evidence_goal": enriched.get("evidence_goal") or "prerequisite_probe",
                    "why_candidate": (
                        f"direct_prerequisite_probe:{source_node_id}->{target_node_id}; "
                        f"{enriched.get('why_candidate') or 'current_lineage_active_use_metadata'}"
                    ),
                })
                candidates.append(enriched)
            if len(candidates) >= 8:
                break
        if not candidates:
            return None
        packet = {
            "packet_id": "CPV5-rollback-" + hashlib.sha256(
                f"{flow['id']}:{flow_revision}:{source_node_id}:{','.join(rollback_nodes)}:{flow['graph_version']}".encode("utf-8")
            ).hexdigest()[:12],
            "packet_schema_version": "2026-07-11.v5.planner-candidate-packet.v1",
            "graph_version": flow["graph_version"],
            "question_bank_version": str(flow.get("question_bank_version") or attempt.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION),
            "target_node_id": source_node_id,
            "source_node_id": source_node_id,
            "flow_id": flow["id"],
            "flow_revision": flow_revision,
            "candidate_count": len(candidates),
            "filter_summary": {
                **aggregate_filter,
                "source_node_id": source_node_id,
                "direct_rollback_node_ids": rollback_nodes,
                "packet_policy": "all_direct_prerequisites_1_to_2_each_max_8",
            },
            "candidates": candidates,
        }
        packet["packet_hash"] = hashlib.sha256(
            json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return packet

    def _direct_rollback_node_ids(self, node_id: str) -> list[str]:
        ordered: list[str] = []
        node = self.graph.get_node(node_id) or {}
        error_diagnosis = node.get("error_diagnosis") if isinstance(node.get("error_diagnosis"), dict) else {}
        for candidate in [*(error_diagnosis.get("rollback_to") or []), *(node.get("prerequisites") or [])]:
            candidate_id = str(candidate or "")
            if candidate_id and candidate_id != node_id and candidate_id not in ordered:
                ordered.append(candidate_id)
        return ordered

    def _validate_planner_action_target(
        self,
        *,
        action: str,
        attempt: dict[str, Any],
        output: dict[str, Any],
        selected_candidate: dict[str, Any],
    ) -> None:
        source_node_id = str(attempt.get("node_id") or "")
        selected_node_id = str(selected_candidate.get("node_id") or "")
        output_target_node_id = str(output.get("target_node_id") or selected_node_id)
        if output_target_node_id and selected_node_id and output_target_node_id != selected_node_id:
            raise model_router.ModelJSONParseError(
                f"illegal planner action target: output target {output_target_node_id} does not match selected candidate node {selected_node_id}"
            )
        if action == "prerequisite_probe":
            legal_targets = set(self._direct_rollback_node_ids(source_node_id))
            if selected_node_id not in legal_targets or output_target_node_id not in legal_targets:
                raise model_router.ModelJSONParseError(
                    f"illegal planner action target: prerequisite_probe target {output_target_node_id or selected_node_id} is not a direct prerequisite of {source_node_id}"
                )
            self._validate_planner_action_role(action=action, selected_candidate=selected_candidate)
            return
        if action in {"same_structure_retest", "near_transfer_retest", "stretch"} and selected_node_id != source_node_id:
            raise model_router.ModelJSONParseError(
                f"illegal planner action target: {action} must stay on source node {source_node_id}, got {selected_node_id}"
            )
        self._validate_planner_action_role(action=action, selected_candidate=selected_candidate)

    def _validate_planner_action_role(self, *, action: str, selected_candidate: dict[str, Any]) -> None:
        slot_role = str(selected_candidate.get("slot_role") or "")
        evidence_role = str(selected_candidate.get("evidence_role") or "")
        kind = str(selected_candidate.get("kind") or "")
        role_text = " ".join([slot_role, evidence_role, kind]).lower()
        if not slot_role and not evidence_role:
            if action in {"near_transfer_retest", "stretch"}:
                raise model_router.ModelJSONParseError(
                    f"action role mismatch: {action} requires explicit transfer/stretch candidate metadata"
                )
            return
        if slot_role == "legacy_mainline" and action in {"same_structure_retest", "prerequisite_probe"}:
            return
        transfer_roles = {
            "near_transfer",
            "integrated_transfer",
            "multi_representation",
            "alternative_method",
            "summary_transfer_check",
            "model_selection",
        }
        repair_roles = {
            "wrong_solution_repair",
            "necessary_condition",
            "prerequisite_probe",
            "calculation_symbol_precision",
            "concept_boundary",
        }
        same_structure_roles = {
            "same_structure_confirmation",
            "standard_model",
            "standard_example",
            "wrong_solution_repair",
            "inverse_check",
            "calculation_symbol_precision",
            "expression_notation",
            "legacy_mainline",
        }
        if action == "near_transfer_retest" and not (
            slot_role in transfer_roles
            or evidence_role in transfer_roles
            or kind in transfer_roles
            or "transfer" in role_text
        ):
            raise model_router.ModelJSONParseError(
                f"action role mismatch: near_transfer_retest cannot use {slot_role or evidence_role or kind}"
            )
        if action == "stretch" and slot_role not in {"stretch_readiness_check", "controlled_stretch"} and "stretch" not in role_text:
            raise model_router.ModelJSONParseError(
                f"action role mismatch: stretch cannot use {slot_role or evidence_role or kind}"
            )
        if action == "same_structure_retest" and slot_role not in same_structure_roles:
            raise model_router.ModelJSONParseError(
                f"action role mismatch: same_structure_retest cannot use {slot_role or evidence_role or kind}"
            )
        if action == "prerequisite_probe" and slot_role not in repair_roles:
            raise model_router.ModelJSONParseError(
                f"action role mismatch: prerequisite_probe cannot use {slot_role or evidence_role or kind}"
            )

    def _record_model_agent_run_from_envelope(
        self,
        envelope: semantic_agents.SemanticAgentEnvelope,
        *,
        session_id: str,
        trigger: str,
        input_refs: dict[str, Any],
        route: model_router.ModelRoute,
    ) -> dict[str, Any]:
        return db.record_agent_run(
            self.conn,
            agent_key=envelope.agent_key,
            engine_type="model",
            session_id=session_id,
            phase=envelope.phase,
            trigger=trigger,
            input_refs=input_refs,
            prompt_version_id=envelope.prompt_version_id,
            prompt_template_sha256=str((envelope.route_meta or {}).get("prompt_template_sha256") or internal_agents.file_sha256(
                internal_agents.prompt_path_for_contract(internal_agents.load_v5_contract_for_agent(envelope.agent_key))
            )),
            rendered_prompt_sha256=str((envelope.route_meta or {}).get("rendered_prompt_sha256") or ""),
            model_provider=route.provider if route.enabled else "",
            model_name=route.model if route.enabled else "",
            model_alias=route.model_alias if route.enabled else "",
            model_params={
                **route.model_params,
                **(envelope.route_meta or {}),
                "trust_mode": envelope.provider_mode,
                "provider_mode": envelope.provider_mode,
            },
            response_schema_version=envelope.response_schema_version,
            response_schema_sha256=str((envelope.route_meta or {}).get("response_schema_sha256") or db._digest_json(
                internal_agents.load_v5_contract_for_agent(envelope.agent_key).get("response_schema") or {}
            )),
            status="accepted" if envelope.status == "accepted" else "error",
            confidence=float(envelope.confidence),
            output=envelope.output,
            validation_errors=list(envelope.validation_errors),
            error_reason=envelope.error_reason[:800],
            commit=False,
        )

    def _materialize_blocked_or_summary(self, flow_id: str, *, reason: str) -> None:
        flow = self._flow_by_id(flow_id)
        if not flow:
            return
        if flow["status"] == "completed" and flow["summary_id"]:
            return
        flow_dict = dict(flow)
        summary_id = self._ensure_daily_summary(
            flow_dict,
            reason=reason,
            target_flow_revision=int(flow_dict.get("flow_revision") or 1) + 1,
        )
        self.conn.execute(
            """
            update daily_flows
            set status = 'completed',
                summary_id = ?,
                current_step_id = null,
                flow_revision = flow_revision + 1,
                updated_at = ?
            where id = ?
            """,
            (summary_id, db.now_iso(), flow_id),
        )

    def _visible_step_for_next_step_decision(self, flow_id: str, decision_id: str) -> dict[str, Any] | None:
        if not flow_id or not decision_id:
            return None
        row = self.conn.execute(
            """
            select *
            from flow_steps
            where flow_id = ?
              and source_next_step_decision_id = ?
              and superseded_by_step_id is null
            order by case when status in ('selected','displayed','analyzing') then 0 else 1 end,
                     created_at, id
            limit 1
            """,
            (flow_id, decision_id),
        ).fetchone()
        return dict(row) if row else None

    def _apply_planner_decision(
        self,
        *,
        flow: dict[str, Any],
        attempt: dict[str, Any],
        source_step_id: str,
        output: dict[str, Any],
        planner_agent_run_id: str,
        provider_mode: str,
        candidate_packet: dict[str, Any],
        source_validation_ids: list[str],
        source_mastery_ids: list[str],
        decision_flow_revision: int | None = None,
    ) -> dict[str, Any]:
        action = str(output.get("action") or "blocked")
        branch_policy = output.get("branch_policy") if isinstance(output.get("branch_policy"), dict) else {}
        selected_candidate_id = str(output.get("selected_candidate_id") or "")
        candidate_by_id = {str(item.get("question_id") or ""): item for item in candidate_packet.get("candidates", [])}
        selected_candidate = candidate_by_id.get(selected_candidate_id)
        if action in {"same_structure_retest", "near_transfer_retest", "prerequisite_probe", "stretch"}:
            if not selected_candidate:
                raise model_router.ModelJSONParseError("illegal planner action target: selected candidate is missing from packet")
            self._validate_planner_action_target(
                action=action,
                attempt=attempt,
                output=output,
                selected_candidate=selected_candidate,
            )
            if not output.get("target_node_id"):
                output = {**output, "target_node_id": selected_candidate.get("node_id")}
        if source_step_id:
            self.conn.execute(
                "update flow_steps set status = 'completed', updated_at = ? where id = ?",
                (db.now_iso(), source_step_id),
            )
        decision_flow = dict(flow)
        if decision_flow_revision:
            decision_flow["flow_revision"] = int(decision_flow_revision)
        decision = self._record_next_step_decision(
            flow=decision_flow,
            action=action,
            report_label="confirmed" if provider_mode == "live_model" else provider_mode,
            source_step_id=source_step_id,
            source_attempt_ids=[attempt["id"]],
            source_validation_ids=source_validation_ids,
            source_mastery_ids=source_mastery_ids,
            provider_mode=provider_mode,
            reason=str(output.get("reason") or action),
            candidate_packet=candidate_packet,
            target_node_id=str(output.get("target_node_id") or attempt.get("node_id") or ""),
            planner_agent_run_id=planner_agent_run_id,
            branch_policy=branch_policy,
        )
        decision["target_node_id"] = str(output.get("target_node_id") or attempt.get("node_id") or "")
        if decision.get("reused_existing"):
            existing_step = self._visible_step_for_next_step_decision(flow["id"], decision["id"])
            if existing_step:
                decision["step_id"] = existing_step["id"]
                return decision
            if action in {"summary", "blocked"}:
                current_flow = self._flow_by_id(flow["id"])
                if current_flow and current_flow["summary_id"]:
                    return decision
        if action in {"micro_teach", "worked_example"} or bool(branch_policy.get("requires_teaching_generation")):
            decision["requires_teaching_generation"] = True
            return decision
        if action in {"summary", "blocked"}:
            self._materialize_blocked_or_summary(flow["id"], reason=str(output.get("reason") or action))
            return decision
        if action == "clarify_evidence":
            validation = self._latest_passed_validation(attempt["id"], {"source_evidence_validation_ids": source_validation_ids})
            if validation:
                self._create_clarify_step(
                    flow_id=flow["id"],
                    source_step_id=source_step_id,
                    attempt=attempt,
                    validation=validation,
                    provider_mode=provider_mode,
                    reason=str(output.get("reason") or "需要补充更清楚的证据。"),
                )
            else:
                self._materialize_blocked_or_summary(flow["id"], reason="planner_clarify_without_validation")
            return decision
        if selected_candidate:
            try:
                question = db.get_question(self.conn, str(selected_candidate["question_id"]))
            except KeyError:
                question = None
            if question:
                source_reason = {}
                if source_step_id:
                    row = self.conn.execute("select selection_reason_json from flow_steps where id = ?", (source_step_id,)).fetchone()
                    source_reason = db.json_load(row["selection_reason_json"], {}) if row else {}
                new_phase = ""
                step_type = "question"
                if source_reason.get("new_knowledge_phase"):
                    normalized = normalize_new_knowledge_transition(
                        previous_phase=str(source_reason.get("new_knowledge_phase") or ""),
                        requested_action=action,
                        candidate_kind=str(selected_candidate.get("kind") or question.get("kind") or ""),
                        audit=source_reason,
                    )
                    action = normalized["action"]
                    new_phase = normalized["new_knowledge_phase"]
                    step_type = normalized["step_type"]
                step_id = self._create_question_step(
                    flow_id=flow["id"],
                    position=int(self.conn.execute("select count(*) from flow_steps where flow_id = ?", (flow["id"],)).fetchone()[0]) + 1,
                    graph_version=flow["graph_version"],
                    question=question,
                    review_record_id=str(selected_candidate.get("review_record_id") or ""),
                    selection_reason={
                        "reason": "planner_agent_selected_candidate",
                        "source_next_step_decision_id": decision["id"],
                        "source_attempt_id": attempt["id"],
                        **({"new_knowledge_phase": new_phase} if new_phase else {}),
                    },
                    candidate_packet=candidate_packet,
                    support_hint="写清关键关系、步骤和检查。",
                    step_type=step_type,
                )
                updated = self.conn.execute(
                    """
                    update daily_flows
                    set status = 'reviewing',
                        current_step_id = ?,
                        flow_revision = flow_revision + 1,
                        updated_at = ?
                    where id = ?
                      and status not in ('completed','superseded')
                    """,
                    (step_id, db.now_iso(), flow["id"]),
                )
                if updated.rowcount == 0:
                    self.conn.execute(
                        "update flow_steps set status = 'superseded', updated_at = ? where id = ?",
                        (db.now_iso(), step_id),
                    )
                return decision
        self._materialize_blocked_or_summary(flow["id"], reason="planner_no_materializable_action")
        return decision

    def _materialize_teaching_step_from_agent(
        self,
        *,
        flow: dict[str, Any],
        attempt: dict[str, Any],
        source_step_id: str,
        source_next_step_decision_id: str,
        payload: dict[str, Any] | None = None,
        teaching_output: dict[str, Any],
        teaching_agent_run_id: str = "",
    ) -> str:
        payload = payload or {}
        question_id = str(attempt.get("question_id") or payload.get("question_id") or (payload.get("question_package") or {}).get("question_id") or "")
        question = db.get_question(self.conn, question_id)
        raw_step_type = str(teaching_output.get("teaching_step_type") or "teaching_repair")
        step_type = "clarify_evidence" if raw_step_type == "clarification" else raw_step_type
        if step_type not in {"teaching_repair", "worked_example", "clarify_evidence"}:
            step_type = "teaching_repair"
        sections = teaching_output.get("teaching_sections") if isinstance(teaching_output.get("teaching_sections"), dict) else {}
        section_texts: list[str] = []
        for key in ("essence", "core_model", "worked_example", "why_it_works", "next_micro_check"):
            section = sections.get(key) if isinstance(sections.get(key), dict) else {}
            if key == "worked_example":
                steps = section.get("steps") if isinstance(section.get("steps"), list) else []
                section_texts.extend([
                    str(section.get("title") or ""),
                    str(section.get("problem") or ""),
                    *[str(item) for item in steps],
                    str(section.get("check") or ""),
                ])
            else:
                section_texts.extend([
                    str(section.get("title") or ""),
                    str(section.get("body") or section.get("prompt") or ""),
                ])
        action_text = str(teaching_output.get("next_child_action") or "").strip()
        if "_" in action_text or action_text.lower() in {"answer_micro_check", "micro_check", "continue_new_knowledge"}:
            action_text = ""
        prompt_text = _child_safe_text(
            str(teaching_output.get("child_title") or "").strip() or "先看这一处讲解",
            "先看这一处讲解",
            limit=120,
        )
        if not sections:
            prompt_text = _child_safe_text(
                "\n\n".join(str(item) for item in (prompt_text, *section_texts, action_text) if item),
                "先把关键关系写清楚，再做计算和检查。",
                limit=900,
            )
        if source_step_id:
            self.conn.execute(
                "update flow_steps set status = 'completed', updated_at = ? where id = ?",
                (db.now_iso(), source_step_id),
            )
        return self._create_question_step(
            flow_id=flow["id"],
            position=int(self.conn.execute("select count(*) from flow_steps where flow_id = ?", (flow["id"],)).fetchone()[0]) + 1,
            graph_version=flow["graph_version"],
            question=question,
            review_record_id=attempt.get("review_record_id") or str(payload.get("review_record_id") or ""),
            selection_reason={
                "reason": "teaching_generation_agent",
                "source_attempt_id": attempt.get("id", ""),
                "source_step_id": source_step_id,
                "source_next_step_decision_id": source_next_step_decision_id,
                "teaching_agent_run_id": teaching_agent_run_id,
                "new_knowledge_phase": "worked_example" if payload.get("new_knowledge_request") else ("repair" if step_type == "teaching_repair" else step_type),
            },
            candidate_packet={},
            support_hint=prompt_text,
            step_type=step_type,
            answer_input_mode="clarification" if step_type == "clarify_evidence" else "none",
            teaching_sections=sections or None,
        )

    def _block_flow_after_dead_letter(self, job: dict[str, Any], reason: str) -> None:
        flow_id = str(job.get("flow_id") or "")
        step_id = str(job.get("flow_step_id") or "")
        flow = self._flow_by_id(flow_id) if flow_id else None
        if flow and flow["status"] in TERMINAL_FLOW_STATUSES:
            return
        if step_id:
            self.conn.execute(
                """
                update flow_steps
                set status = 'blocked',
                    updated_at = ?
                where id = ?
                  and status = 'analyzing'
                """,
                (db.now_iso(), step_id),
            )
        if flow_id:
            self._block_flow(
                flow_id,
                "你的答案已经保存。系统暂时不能安全判断这一步，已经安全停下；可以稍后重试，或先完成今天总结。",
            )

    def _handle_pending_answer_analysis(
        self,
        job: dict[str, Any],
        *,
        attempt: dict[str, Any],
        question: dict[str, Any],
        review: dict[str, Any],
        provider_mode: str,
    ) -> dict[str, Any]:
        ai_review = review.get("ai_review") if isinstance(review.get("ai_review"), dict) else {}
        status = str(ai_review.get("status") or review.get("status") or "pending")
        reason = str(review.get("reason") or ai_review.get("reason") or "answer analysis is pending")
        operator_attention_required = (
            provider_mode == "not_configured"
            or status in {"not_configured", "error"}
            or (
                status == "blocked"
                and str(ai_review.get("provider_mode") or review.get("provider_mode") or "") == "not_configured"
            )
        )
        if operator_attention_required and provider_mode == "not_configured" and "未配置" not in reason:
            reason = f"模型未配置：{reason}"
        with self.conn:
            self.conn.execute(
                """
                update attempts
                set review_meta_json = ?,
                    analysis_status = ?,
                    analysis_version = analysis_version + 1
                where id = ?
                """,
                (
                    db.json_dump(ai_review or {"status": status, "reason": reason}),
                    "operator_attention_required" if operator_attention_required else "missing",
                    attempt["id"],
                ),
            )
            run = self._record_model_agent_run(
                agent_key="answer_analysis_agent",
                session_id=attempt["session_id"],
                phase="answer_analysis",
                trigger=f"v5_answer_analysis_pending:{attempt['id']}:{db.now_iso()}",
                route=model_router.answer_analysis_route(),
                status="error" if operator_attention_required else "pending",
                confidence=0.0,
                input_refs={
                    "attempt_id": attempt["id"],
                    "question_id": question["id"],
                    "flow_id": job.get("flow_id"),
                    "flow_step_id": attempt.get("flow_step_id"),
                },
                output={"review_status": status, "reason": reason[:500]},
                error_reason=reason if operator_attention_required else "",
                route_meta={
                    "provider_mode": provider_mode,
                    **semantic_agents.knowledge_pack_metadata("answer_analysis_agent"),
                },
                use_v5_contract=True,
            )
            validation = evidence_gate.EvidenceGate(
                self.conn,
                current_graph_version=self.graph.current_graph_version(),
                current_question_bank_version=str(attempt.get("question_bank_version") or job.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION),
            ).validate_attempt(
                attempt["id"],
                analysis_version=int(attempt.get("analysis_version") or 0) + 1,
                provider_mode=provider_mode,
                answer_analysis_agent_run_id=run["id"],
                commit=False,
            )
            source_step = self.conn.execute(
                "select * from flow_steps where id = ?",
                (attempt.get("flow_step_id") or "",),
            ).fetchone()
            if attempt.get("answer_source") == "v3_stuck" and source_step and source_step["step_type"] == "clarify_evidence":
                self.conn.execute(
                    "update flow_steps set status = 'completed', updated_at = ? where id = ?",
                    (db.now_iso(), source_step["id"]),
                )
                flow_id = str(source_step["flow_id"])
                flow = dict(self._flow_by_id(flow_id))
                summary_id = self._ensure_daily_summary(
                    flow,
                    reason="clarify_cannot_provide",
                    target_flow_revision=int(flow.get("flow_revision") or 1) + 1,
                )
                self.conn.execute(
                    """
                    update daily_flows
                    set status = 'completed',
                        summary_id = ?,
                        current_step_id = null,
                        flow_revision = flow_revision + 1,
                        updated_at = ?
                    where id = ?
                    """,
                    (summary_id, db.now_iso(), flow_id),
                )
                return {
                    "job_status": "succeeded",
                    "next_action": "summary",
                    "reason": "clarify_cannot_provide",
                    "attempt_id": attempt["id"],
                    "evidence_validation_id": validation.validation_id,
                    "summary_id": summary_id,
                }
            if status in {"photo_ocr_unusable", "low_confidence"}:
                decision = self._create_clarify_step(
                    flow_id=str(job.get("flow_id") or attempt.get("flow_id") or ""),
                    source_step_id=str(attempt.get("flow_step_id") or ""),
                    attempt=attempt,
                    validation=validation,
                    provider_mode=provider_mode,
                    reason=reason,
                )
                return {
                    "job_status": "succeeded",
                    "next_action": "clarify_evidence",
                    "reason": reason,
                    "attempt_id": attempt["id"],
                    "evidence_validation_id": validation.validation_id,
                    "next_step_decision_id": decision.get("id"),
                }
            self._block_flow(
                str(job.get("flow_id") or ""),
                "系统批阅暂时不可用，已经安全停下。稍后恢复后会继续。",
            )
        return {
            "job_status": "blocked",
            "reason": reason,
            "attempt_id": attempt["id"],
            "evidence_validation_id": validation.validation_id,
        }

    def _legacy_session_id_for_flow(self, flow_id: str) -> str:
        flow = self._flow_by_id(flow_id)
        if not flow:
            raise ChildSafeRuntimeError("今天的学习记录暂时打不开，请刷新后继续。")
        if flow["legacy_session_id"]:
            return str(flow["legacy_session_id"])

        recovery_session_id = db.create_session(
            self.conn,
            f"v3 daily flow recovery {flow['local_date']}",
            mode="daily_flow_v3",
            status="active",
            commit=False,
        )
        updated = self.conn.execute(
            """
            update daily_flows
            set legacy_session_id = ?, updated_at = ?
            where id = ? and legacy_session_id is null
            """,
            (recovery_session_id, db.now_iso(), flow_id),
        )
        if updated.rowcount == 1:
            return recovery_session_id

        current = self._flow_by_id(flow_id)
        self.conn.execute("delete from learning_sessions where id = ?", (recovery_session_id,))
        if not current or not current["legacy_session_id"]:
            raise ChildSafeRuntimeError("今天的学习记录暂时打不开，请刷新后继续。")
        return str(current["legacy_session_id"])

    def _active_attempt_for_step(self, flow_step_id: str, *, client_idempotency_key: str | None = None) -> sqlite3.Row | None:
        filters = [
            "flow_step_id = ?",
            "evidence_status = 'active'",
        ]
        params: list[Any] = [flow_step_id]
        if client_idempotency_key is not None:
            filters.append("client_idempotency_key = ?")
            params.append(client_idempotency_key)
        return self.conn.execute(
            f"""
            select id
            from attempts
            where {' and '.join(filters)}
            order by created_at desc, id desc
            limit 1
            """,
            params,
        ).fetchone()

    def _ensure_answer_analysis_job_for_attempt(self, step: dict[str, Any], attempt_id: str, *, source: str) -> None:
        attempt = db.get_attempt(self.conn, attempt_id)
        attempt_version = int(attempt.get("attempt_version") or 1)
        step_revision = int(step.get("step_revision") or 1)
        attachment_ids = list(attempt.get("attachment_ids") or [])
        answer_source = str(attempt.get("answer_source") or "v3_text")
        interaction_response = attempt.get("interaction_response") if isinstance(attempt.get("interaction_response"), dict) else {}
        evidence_digest = db._digest_json({
            "attempt_id": attempt_id,
            "attempt_version": attempt_version,
            "flow_step_id": step["id"],
            "step_revision": step_revision,
            "question_id": step["question_id"],
            "review_record_id": step["review_record_id"],
            "answer_source": answer_source,
            "answer_raw": attempt.get("answer_raw") or "",
            "interaction_response": interaction_response,
            "attachment_ids": attachment_ids,
            "client_idempotency_key": attempt.get("client_idempotency_key") or "",
        })
        self.conn.execute(
            """
            update attempts
            set evidence_digest_sha256 = ?,
                analysis_status = case when analysis_status = '' then 'missing' else analysis_status end,
                graph_version = coalesce(nullif(graph_version, ''), ?),
                question_bank_version = coalesce(nullif(question_bank_version, ''), ?),
                review_record_id = coalesce(nullif(review_record_id, ''), ?)
            where id = ?
            """,
            (
                evidence_digest,
                step["graph_version"],
                step["question_bank_version"],
                step["review_record_id"],
                attempt_id,
            ),
        )
        job_queue.JobQueue(self.conn).enqueue(
            "answer_analysis",
            f"v5:answer_analysis:{attempt_id}:{attempt_version}:{evidence_digest}",
            {
                "payload_schema_version": job_queue.V5_JOB_PAYLOAD_SCHEMA_VERSION,
                "legacy_session_id": self._legacy_session_id_for_flow(step["flow_id"]),
                "flow_id": step["flow_id"],
                "flow_revision": int(self._flow_by_id(step["flow_id"])["flow_revision"] or 1),
                "flow_step_id": step["id"],
                "step_revision": step_revision,
                "attempt_id": attempt_id,
                "attempt_version": attempt_version,
                "analysis_version": int(attempt.get("analysis_version") or 0),
                "graph_version": str(attempt.get("graph_version") or step["graph_version"]),
                "question_bank_version": str(attempt.get("question_bank_version") or step["question_bank_version"]),
                "question_id": str(attempt.get("question_id") or step["question_id"]),
                "review_record_id": str(attempt.get("review_record_id") or step["review_record_id"]),
                "interaction_response": interaction_response,
                "interaction_schema_hash": interaction_response.get("schema_hash", ""),
                "provider_mode": _provider_mode(model_router.answer_analysis_route()),
                "route_meta": {"route": "answer_analysis", "source": source},
            },
            commit=False,
        )

    def _mark_step_analyzing(self, step_id: str, attempt_id: str, flow_id: str) -> None:
        now = db.now_iso()
        self.conn.execute(
            """
            update flow_steps
            set status = 'analyzing',
                attempt_id = ?,
                updated_at = ?
            where id = ?
            """,
            (attempt_id, now, step_id),
        )
        self.conn.execute(
            """
            update daily_flows
            set status = 'reviewing',
                current_step_id = ?,
                updated_at = ?
            where id = ?
            """,
            (step_id, now, flow_id),
        )

    def _save_answer_photo(self, *, attempt_id: str, original_name: str, data_url: str) -> tuple[dict[str, Any], Path]:
        content_type, data = _parse_answer_photo_data_url(data_url)
        upload_root = (self.project_root / ANSWER_UPLOAD_RELATIVE_PREFIX).resolve()
        upload_root.mkdir(parents=True, exist_ok=True)
        filename = _safe_answer_photo_filename(original_name, content_type, attempt_id)
        target = (upload_root / filename).resolve()
        if target.parent != upload_root:
            raise ChildSafeRuntimeError("照片文件名不可用，请重新上传。", status=400, child_action="重新上传")
        temp_target = (upload_root / f".{filename}.tmp").resolve()
        try:
            temp_target.write_bytes(data)
            temp_target.replace(target)
            attachment = db.record_attempt_attachment(
                self.conn,
                attempt_id=attempt_id,
                kind="answer_photo",
                original_filename=original_name,
                filename=filename,
                content_type=content_type,
                byte_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                relative_path=f"{ANSWER_UPLOAD_RELATIVE_PREFIX}/{filename}",
                commit=False,
            )
        except Exception:
            temp_target.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return attachment, target

    def _current_visible_step(self, flow_id: str | None) -> sqlite3.Row | None:
        if not flow_id:
            return None
        return self.conn.execute(
            """
            select *
            from flow_steps
            where flow_id = ?
              and status in ('selected','displayed','analyzing')
              and superseded_by_step_id is null
            order by position desc, created_at desc
            limit 1
            """,
            (flow_id,),
        ).fetchone()

    def _project_analyzing_step_or_reconcile(
        self,
        base: dict[str, Any],
        flow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        job_state = self._analyzing_step_job_state(step)
        if job_state["state"] == "active":
            return {
                **base,
                "child_state": "analyzing",
                "message": {
                    "title": "正在看你的步骤",
                    "body": "答案已经保存。文字通常半分钟左右；有照片可能接近一分钟。不用反复点，页面会自动刷新，结果好了会出现下一步。",
                    "action_label": "刷新看看",
                },
            }
        reason = self._stale_analyzing_child_reason(job_state)
        with self.conn:
            self.conn.execute(
                """
                update flow_steps
                set status = 'blocked',
                    updated_at = ?
                where id = ?
                  and status = 'analyzing'
                """,
                (db.now_iso(), step["id"]),
            )
            self._block_flow(str(flow.get("id") or step.get("flow_id") or ""), reason)
        return self._blocked_projection(reason)

    def _analyzing_step_job_state(self, step: dict[str, Any]) -> dict[str, Any]:
        attempt_id = str(step.get("attempt_id") or "")
        if not attempt_id:
            attempt = self.conn.execute(
                """
                select id
                from attempts
                where flow_step_id = ?
                  and evidence_status = 'active'
                order by created_at desc, id desc
                limit 1
                """,
                (step["id"],),
            ).fetchone()
            attempt_id = str(attempt["id"] if attempt else "")
        if not attempt_id:
            return {"state": "missing_attempt", "status": "", "reason": "no active attempt for analyzing step"}
        rows = [dict(row) for row in self.conn.execute(
            """
            select id, job_type, status, run_count, blocked_reason, dead_letter_reason, last_error
            from background_jobs
            where flow_step_id = ?
              and attempt_id = ?
              and job_type in ('answer_analysis','evaluation_update','planner_decision','teaching_generation')
            order by created_at desc, id desc
            """,
            (step["id"], attempt_id),
        ).fetchall()]
        if not rows:
            return {"state": "missing_job", "status": "", "attempt_id": attempt_id, "reason": "no model job for analyzing step"}
        active_statuses = {"queued", "retry", "claimed", "running"}
        if any(row["status"] in active_statuses for row in rows):
            return {"state": "active", "status": "active", "attempt_id": attempt_id}
        latest = rows[0]
        return {
            "state": str(latest.get("status") or "terminal"),
            "status": str(latest.get("status") or ""),
            "attempt_id": attempt_id,
            "job_id": latest.get("id", ""),
            "job_type": latest.get("job_type", ""),
            "reason": latest.get("blocked_reason") or latest.get("dead_letter_reason") or latest.get("last_error") or "background job is not runnable",
        }

    def _stale_analyzing_child_reason(self, job_state: dict[str, Any]) -> str:
        state = str(job_state.get("state") or "")
        if state == "waiting":
            return "你的答案已经保存。这一步还需要补充更清楚的证据，系统已经安全停下；可以稍后重试，或先完成今天总结。"
        if state in {"blocked", "dead_letter"}:
            return "你的答案已经保存。系统暂时不能安全判断这一步，已经安全停下；可以稍后重试，或先完成今天总结。"
        if state == "missing_job":
            return "你的答案已经保存，但后台批阅任务没有正常启动。系统已经安全停下；稍后恢复后可以继续。"
        return "你的答案已经保存。系统暂时不能确认批阅状态，已经安全停下；可以稍后重试。"

    def _project_step(self, step: dict[str, Any]) -> dict[str, Any]:
        package = db.json_load(step.get("prompt_package_json"), {})
        if step.get("step_type") in {"worked_example", "teaching_repair"}:
            return child_teaching_step_dto({
                **step,
                **{
                    "topic_label": package.get("topic_label") or package.get("title") or "当前步骤",
                    "prompt": package.get("prompt") or "",
                    "answer_input_mode": package.get("answer_input_mode") or "none",
                    "allowed_response_modes": _allowed_response_modes_for_step(step.get("step_type"), package),
                    "upload_enabled": bool(package.get("upload_enabled", False)),
                    "stuck_enabled": bool(package.get("stuck_enabled", True)),
                    "support": {
                        "hint": package.get("hint") or "",
                        "continue_label": package.get("continue_label") or "",
                        "stuck_label": package.get("stuck_label") or "",
                    },
                    "teaching_sections": package.get("teaching_sections") if isinstance(package.get("teaching_sections"), dict) else {},
                    "assessment_feedback": package.get("assessment_feedback") if isinstance(package.get("assessment_feedback"), dict) else {},
                },
            })
        allowed_response_modes = _allowed_response_modes_for_step(
            step.get("step_type"),
            package,
        )
        try:
            child_surface = child_prompt.project_child_surface(
                prompt=package.get("prompt"),
                prompt_format=package.get("prompt_format"),
                interaction_schema=package.get("interaction_schema"),
                allow_legacy=True,
                limit=2000,
            )
        except child_prompt.ChildPromptContractError as exc:
            raise ChildSafeRuntimeError("当前步骤还没有准备好，请稍后再试。") from exc
        stored_projection_sha256 = str(package.get("child_surface_projection_sha256") or "")
        if stored_projection_sha256 and stored_projection_sha256 != child_surface["projection_sha256"]:
            raise ChildSafeRuntimeError("当前步骤还没有准备好，请稍后再试。")
        projected = {
            "step_handle": step.get("step_handle"),
            "position": step.get("position"),
            "kind_label": _kind_label(step.get("step_type")),
            "topic_label": _child_safe_text(package.get("topic_label") or package.get("title") or "当前步骤", "当前步骤"),
            "prompt_format": child_surface["prompt_format"],
            "prompt": child_surface["prompt"],
            "prompt_segments": child_surface["prompt_segments"],
            "child_surface_projection_sha256": child_surface["projection_sha256"],
            "answer_input_mode": str(package.get("answer_input_mode") or "text"),
            "allowed_response_modes": allowed_response_modes,
            "upload_enabled": bool(package.get("upload_enabled", True)),
            "stuck_enabled": bool(package.get("stuck_enabled", True)),
            "state": str(step.get("status") or ""),
            "support": {
                "hint": _child_safe_text(package.get("hint") or "", ""),
                "continue_label": _child_safe_text(package.get("continue_label") or "", "", limit=40),
                "stuck_label": _child_safe_text(package.get("stuck_label") or "", "", limit=40),
            },
        }
        projected["interaction_schema"] = child_surface["interaction_schema"]
        projected["interaction_rendering"] = child_surface["interaction_rendering"]
        question_visual = package.get("question_visual")
        if isinstance(question_visual, dict):
            if set(question_visual) != question_visuals.CHILD_VISUAL_KEYS:
                raise ChildSafeRuntimeError("这道题的图暂时没有准备好，请稍后再试。")
            projected["question_visual"] = {
                key: question_visual[key]
                for key in ("scene_type", "alt_text", "long_description", "scene")
            }
        sections = package.get("teaching_sections")
        if isinstance(sections, dict) and sections:
            projected["teaching_sections"] = _child_safe_teaching_sections(sections)
        _assert_child_safe_projection(projected)
        return projected

    def _blocked_projection(self, body: str) -> dict[str, Any]:
        payload = {
            "schema_version": V3_CHILD_SCHEMA_VERSION,
            "child_state": "blocked",
            "message": {
                "title": "今天的学习暂时不能继续",
                "body": _child_safe_text(body, "系统暂时不能安全判断这一步，请稍后再试。", limit=220),
                "action_label": "稍后再试",
            },
            "ready_for_new_knowledge": False,
        }
        _assert_child_safe_projection(payload)
        return payload

    def _rows_for_flow_ids(self, table: str, flow_ids: list[str]) -> list[dict[str, Any]]:
        if not flow_ids:
            return []
        placeholders = ",".join("?" for _ in flow_ids)
        return [dict(row) for row in self.conn.execute(
            f"select * from {table} where flow_id in ({placeholders}) order by created_at, id",
            flow_ids,
        ).fetchall()]

    def _attempts_for_step_ids(self, step_ids: list[str]) -> list[dict[str, Any]]:
        if not step_ids:
            return []
        placeholders = ",".join("?" for _ in step_ids)
        return [dict(row) for row in self.conn.execute(
            f"select * from attempts where flow_step_id in ({placeholders}) order by created_at, id",
            step_ids,
        ).fetchall()]

    def _validations_for_attempt_ids(self, attempt_ids: list[str]) -> list[dict[str, Any]]:
        if not attempt_ids:
            return []
        placeholders = ",".join("?" for _ in attempt_ids)
        return [dict(row) for row in self.conn.execute(
            f"select * from evidence_validations where attempt_id in ({placeholders}) order by created_at, id",
            attempt_ids,
        ).fetchall()]

    def _initial_target_node_ids(self) -> list[str]:
        target_ids: list[str] = []
        status_by_node: dict[str, dict[str, Any]] = {}
        for row in db.current_learner_node_status_rows(self.conn):
            node_id = str(row.get("node_id") or "")
            if node_id:
                status_by_node[node_id] = row
        weak_order = {"D": 0, "C": 1, "B": 2}
        weak_rows = sorted(
            [
                row for row in status_by_node.values()
                if str(row.get("status_code") or "") in weak_order
            ],
            key=lambda row: (
                weak_order.get(str(row.get("status_code") or ""), 9),
                str(row.get("updated_at") or ""),
                str(row.get("node_id") or ""),
            ),
        )
        due_rows = sorted(
            [
                row for row in status_by_node.values()
                if str(row.get("status_code") or "") == "A" and self._is_mastered_node_due_for_spacing(row)
            ],
            key=lambda row: (
                self._spacing_reference_iso(row),
                str(row.get("node_id") or ""),
            ),
        )
        for row in [*weak_rows, *due_rows]:
            node_id = str(row.get("node_id") or "")
            if node_id and node_id not in target_ids:
                target_ids.append(node_id)
        for node_id in self._active_question_bank_node_ids():
            if node_id not in target_ids and node_id not in status_by_node:
                target_ids.append(node_id)
        rows = self.conn.execute(
            """
            select id
            from graph_nodes
            order by sequence_band, case priority when 'P0' then 0 when 'P1' then 1 else 2 end, id
            """
        ).fetchall()
        for row in rows:
            if row["id"] not in target_ids and row["id"] not in status_by_node:
                target_ids.append(row["id"])
        return target_ids

    def _active_question_bank_node_ids(self) -> list[str]:
        active_version = db.get_active_question_bank_version(self.conn)
        rows = self.conn.execute(
            """
            select q.node_id, min(g.sequence_band) as sequence_band, min(g.priority) as priority
            from question_items q
            join question_review_records r
              on r.question_id = q.id
             and r.item_version = q.item_version
             and r.source_type = q.source_type
             and r.review_status = 'approved'
             and r.active_eligible = 1
            left join graph_nodes g on g.id = q.node_id
            where q.item_version = ?
            group by q.node_id
            order by
              case when q.node_id like 'M-G7-%' then 0 else 1 end,
              coalesce(sequence_band, 999),
              case priority when 'P0' then 0 when 'P1' then 1 else 2 end,
              q.node_id
            """,
            (active_version,),
        ).fetchall()
        return [str(row["node_id"]) for row in rows if row["node_id"]]

    def _is_mastered_node_due_for_spacing(self, status_row: dict[str, Any]) -> bool:
        if str(status_row.get("status_code") or "") != "A":
            return False
        reference_iso = self._spacing_reference_iso(status_row)
        reference = _parse_iso_datetime(reference_iso)
        if reference is None:
            return False
        cadence_days = self._spacing_cadence_days(str(status_row.get("node_id") or ""))
        now = _parse_iso_datetime(db.now_iso())
        if now is None:
            return False
        return now - reference >= timedelta(days=cadence_days)

    def _spacing_reference_iso(self, status_row: dict[str, Any]) -> str:
        node_id = str(status_row.get("node_id") or "")
        decision = self.conn.execute(
            """
            select created_at
            from mastery_decisions
            where node_id = ?
              and applied = 1
              and new_status_code = 'A'
            order by created_at desc, id desc
            limit 1
            """,
            (node_id,),
        ).fetchone()
        if decision and str(decision["created_at"] or ""):
            return str(decision["created_at"])
        return str(status_row.get("updated_at") or "")

    def _spacing_cadence_days(self, node_id: str) -> int:
        try:
            node = db.get_graph_node(self.conn, node_id)
        except KeyError:
            return 7
        summer = node.get("summer_execution") if isinstance(node.get("summer_execution"), dict) else {}
        cadences = summer.get("review_cadence_days") if isinstance(summer.get("review_cadence_days"), list) else []
        for value in cadences:
            try:
                days = int(value)
            except (TypeError, ValueError):
                continue
            if days > 0:
                return days
        return 7

    def _rank_candidates_for_child_step(
        self,
        candidates: list[dict[str, Any]],
        *,
        preferred_kinds: list[str] | None,
        selection_intent: str,
    ) -> list[dict[str, Any]]:
        preferred = {kind: index for index, kind in enumerate(preferred_kinds or [])}

        def score(candidate: dict[str, Any]) -> tuple[int, int, str]:
            kind = str(candidate.get("kind") or "").strip()
            slot_role = str(candidate.get("slot_role") or "").strip()
            evidence_role = str(candidate.get("evidence_role") or "").strip()
            role_text = " ".join([kind, slot_role, evidence_role]).lower()
            level = str(candidate.get("variant_level") or "").strip().upper()
            if selection_intent == "new_knowledge_teaching":
                kind_score = {
                    "standard_model": 130,
                    "standard_example": 120,
                    "essence_model": 110,
                    "core_representation": 105,
                    "representation": 95,
                    "check_strategy": 80,
                    "misconception_probe": 70,
                    "error_spotting": 60,
                    "variant": 55,
                }.get(kind, 45)
                level_score = {"L1": 5, "L2": 12, "L3": 0, "L4": -10}.get(level, 0)
            else:
                kind_score = {
                    "error_spotting": 145,
                    "variant": 138,
                    "transfer_retest": 132,
                    "near_transfer": 132,
                    "reverse_reasoning": 126,
                    "model_selection": 122,
                    "two_method_compare": 118,
                    "boundary_case": 116,
                    "self_correction": 112,
                    "missing_condition": 106,
                    "stretch_transfer": 100,
                    "representation": 92,
                    "symbol_unit_audit": 86,
                    "check_strategy": 82,
                    "communication": 72,
                    "misconception_probe": 62,
                    "standard_example": 55,
                    "explanation_only": 50,
                    "prerequisite_probe": 42,
                    "essence_check": 24,
                }.get(kind, 40)
                level_score = {"L4": 24, "L3": 18, "L2": 2, "L1": -35}.get(level, 0)
            preferred_score = 0
            if kind in preferred:
                preferred_score = 40 - preferred[kind]
            elif any(token and token in role_text for token in preferred):
                preferred_score = 20
            stretch_penalty = -16 if "stretch" in role_text and selection_intent not in {"stretch", "controlled_extension"} else 0
            return (kind_score + level_score + preferred_score + stretch_penalty, -int(candidate.get("recent_seen_count") or 0), str(candidate.get("question_id") or ""))

        return sorted(candidates, key=score, reverse=True)

    def _select_question_for_node(
        self,
        node_id: str,
        *,
        graph_version: str,
        flow_id: str,
        flow_revision: int,
        reason: dict[str, Any],
        preferred_kinds: list[str] | None = None,
        target_error_tags: list[str] | None = None,
        unstable_dimensions: list[str] | None = None,
        selection_intent: str = "general",
        next_evidence_goal: str = "",
        learner_status: str = "",
        prerequisite_ready: bool = False,
    ) -> dict[str, Any] | None:
        recent_question_ids = self._recent_question_ids_for_flow(flow_id)
        packet = question_bank.QuestionBankService.candidate_packet_for_node(
            self.conn,
            node_id=node_id,
            graph_version=graph_version,
            flow_id=flow_id,
            flow_revision=flow_revision,
            limit=8,
            exclusions={"recent_question_ids": sorted(recent_question_ids)},
            question_bank_version=self._question_bank_version_for_flow(flow_id),
            selection_intent=selection_intent,
            next_evidence_goal=next_evidence_goal,
            learner_status=learner_status,
            prerequisite_ready=prerequisite_ready,
        )
        packet = self._filter_recent_prompt_repetition(packet, flow_id)
        flow_question_bank_version = self._question_bank_version_for_flow(flow_id)
        ranked_candidates = self._rank_candidates_for_child_step(
            list(packet.get("candidates") or []),
            preferred_kinds=preferred_kinds,
            selection_intent=selection_intent,
        )
        packet["candidates"] = ranked_candidates
        packet["candidate_count"] = len(ranked_candidates)
        for candidate in ranked_candidates:
            question_id = str(candidate.get("question_id") or "")
            review_record_id = str(candidate.get("review_record_id") or "")
            if not question_id or question_id in recent_question_ids:
                continue
            try:
                question = db.get_question(self.conn, question_id)
            except KeyError:
                continue
            if not db.is_child_schedulable_question(
                self.conn,
                question,
                question_bank_version=flow_question_bank_version,
            ):
                continue
            if not db.question_review_record_allows_active_use(self.conn, question, review_record_id):
                continue
            return {
                "question": question,
                "review_record_id": review_record_id,
                "candidate_packet": packet,
                "selection_reason": {
                    **reason,
                    "candidate_packet_id": packet.get("packet_id", ""),
                    "candidate_packet_hash": packet.get("packet_hash", ""),
                    "candidate_filter_summary": packet.get("filter_summary", {}),
                    "bounded_candidate_count": packet.get("candidate_count", 0),
                },
            }

        if flow_question_bank_version == question_bank.QUESTION_BANK_V12_VERSION:
            return None

        try:
            question = db.find_question_for_node(
                self.conn,
                node_id,
                preferred_kinds=preferred_kinds,
                target_error_tags=target_error_tags,
                unstable_dimensions=unstable_dimensions,
                avoid_question_ids=recent_question_ids,
                rotate_seed=f"{flow_id}:{flow_revision}:{node_id}",
                question_bank_version=self._question_bank_version_for_flow(flow_id),
            )
        except KeyError:
            return None
        review_records = self.conn.execute(
            """
            select id
            from question_review_records
            where question_id = ?
              and item_version = ?
              and source_type = ?
              and active_eligible = 1
            order by reviewed_at desc, id desc
            """,
            (question["id"], question.get("item_version"), question.get("source_type")),
        ).fetchall()
        review_record_id = ""
        for review_record in review_records:
            if db.question_review_record_allows_active_use(self.conn, question, review_record["id"]):
                review_record_id = review_record["id"]
                break
        if not review_record_id:
            return None
        return {
            "question": question,
            "review_record_id": review_record_id,
            "candidate_packet": packet,
            "selection_reason": {
                **reason,
                "candidate_packet_id": packet.get("packet_id", ""),
                "candidate_packet_hash": packet.get("packet_hash", ""),
                "fallback_selection_reason": question.get("selection_reason", ""),
                "fallback_policy": "legacy_v11_find_question_for_node_compatibility",
                "candidate_filter_summary": packet.get("filter_summary", {}),
            },
        }

    def _filter_recent_prompt_repetition(self, packet: dict[str, Any], flow_id: str) -> dict[str, Any]:
        recent_fingerprints = self._recent_question_structure_fingerprints(flow_id)
        if not recent_fingerprints:
            return packet
        candidates = list(packet.get("candidates") or [])
        if not candidates:
            return packet
        kept: list[dict[str, Any]] = []
        excluded = 0
        for candidate in candidates:
            question_id = str(candidate.get("question_id") or "")
            try:
                question = db.get_question(self.conn, question_id)
            except KeyError:
                kept.append(candidate)
                continue
            fingerprint = _question_structure_repetition_fingerprint(question)
            if fingerprint and fingerprint in recent_fingerprints:
                excluded += 1
                continue
            kept.append(candidate)
        filter_summary = packet.get("filter_summary") if isinstance(packet.get("filter_summary"), dict) else {}
        if excluded:
            filter_summary["excluded_recent_prompt_repetition"] = int(filter_summary.get("excluded_recent_prompt_repetition") or 0) + excluded
        if kept:
            packet = {
                **packet,
                "filter_summary": filter_summary,
                "candidates": kept,
                "candidate_count": len(kept),
            }
            packet["packet_hash"] = db._digest_json(packet)
        else:
            filter_summary["recent_prompt_repetition_filter_saturated"] = True
            packet = {**packet, "filter_summary": filter_summary}
        return packet

    def _recent_question_structure_fingerprints(self, flow_id: str) -> set[str]:
        rows = self.conn.execute(
            """
            select q.*
            from flow_steps s
            join question_items q on q.id = s.question_id
            where s.flow_id = ?
              and s.question_id is not null
            order by s.created_at desc, s.id desc
            limit 6
            """,
            (flow_id,),
        ).fetchall()
        fingerprints: set[str] = set()
        for row in rows:
            fingerprint = _question_structure_repetition_fingerprint(db.row_to_question(row))
            if fingerprint:
                fingerprints.add(fingerprint)
        return fingerprints

    def _recent_question_ids_for_flow(self, flow_id: str) -> set[str]:
        if not flow_id:
            return set()
        rows = self.conn.execute(
            """
            select distinct question_id
            from flow_steps
            where flow_id = ?
              and question_id is not null
            order by created_at desc
            limit 40
            """,
            (flow_id,),
        ).fetchall()
        return {str(row["question_id"]) for row in rows if row["question_id"]}

    def _question_bank_version_for_flow(self, flow_id: str) -> str:
        if not flow_id:
            return question_bank.QUESTION_BANK_VERSION
        row = self._flow_by_id(flow_id)
        if not row:
            return question_bank.QUESTION_BANK_VERSION
        return str(dict(row).get("question_bank_version") or question_bank.QUESTION_BANK_VERSION)

    def _create_question_step(
        self,
        *,
        flow_id: str,
        position: int,
        graph_version: str,
        question: dict[str, Any],
        review_record_id: str,
        selection_reason: dict[str, Any],
        candidate_packet: dict[str, Any] | None = None,
        support_hint: str = "",
        step_type: str = "question",
        answer_input_mode: str | None = None,
        teaching_sections: dict[str, Any] | None = None,
        assessment_feedback: dict[str, Any] | None = None,
        initial_status: str = "selected",
        answer_contract: dict[str, Any] | None = None,
    ) -> str:
        question_visual = self._question_visual_for_question(question)
        source_decision_id = str(selection_reason.get("source_next_step_decision_id") or "")
        if source_decision_id:
            existing = self.conn.execute(
                """
                select id
                from flow_steps
                where flow_id = ?
                  and source_next_step_decision_id = ?
                  and superseded_by_step_id is null
                order by created_at, id
                limit 1
                """,
                (flow_id, source_decision_id),
            ).fetchone()
            if existing:
                return existing["id"]
        node = self.conn.execute("select name from graph_nodes where id = ?", (question["node_id"],)).fetchone()
        now = db.now_iso()
        step_id = f"FS-{uuid.uuid4().hex[:12]}"
        packet = candidate_packet or {}
        question_interaction_schema = question.get("interaction_schema") if isinstance(question.get("interaction_schema"), dict) else None
        try:
            question_child_surface = child_prompt.project_child_surface(
                prompt=question.get("prompt"),
                prompt_format=question.get("prompt_format"),
                interaction_schema=question_interaction_schema,
                allow_legacy=True,
                limit=2000,
            )
        except child_prompt.ChildPromptContractError as exc:
            raise ChildSafeRuntimeError(
                "当前步骤还没有准备好，请稍后再试。",
                status=503,
                child_action="稍后重试",
            ) from exc
        normalized_interaction_schema = question_child_surface["interaction_schema"]
        interaction_type = str((normalized_interaction_schema or {}).get("type") or "")
        requires_explanation = bool(
            normalized_interaction_schema
            and normalized_interaction_schema.get("requires_explanation")
        )
        unprompted_process = question_bank.v12_item_requires_unprompted_process_evidence(question)
        child_interaction_schema = question_child_surface["interaction_schema"]
        effective_input_mode = answer_input_mode or (
            "text_photo" if interaction_type == "short_text" else
            "interaction" if question_interaction_schema else
            "clarification" if step_type == "clarify_evidence" else ("text" if step_type == "micro_check" else "text_photo")
        )
        upload_enabled = effective_input_mode in {"photo", "text_photo", "clarification"}
        if step_type == "clarify_evidence":
            prompt = (
                "刚才的答案或照片不够清楚，系统还不能安全判断。\n\n"
                f"原题：{question['prompt']}\n\n"
                "请补一段关键步骤和最后答案，或重新拍一张清楚的纸面过程。"
            )
            hint = support_hint or "补充证据后再保存；如果还是说不清，也可以直接写卡在哪里。"
        elif step_type == "worked_example":
            steps = question.get("solution_steps") or []
            steps_text = "\n".join(f"{index + 1}. {step}" for index, step in enumerate(steps[:4]))
            prompt = (
                f"先看一个例题。\n\n例题：{question['prompt']}\n\n"
                f"一种清楚做法：{question.get('expected_answer') or '先写关键关系，再完成计算。'}"
            )
            if steps_text:
                prompt = f"{prompt}\n\n步骤提示：\n{steps_text}"
            prompt = f"{prompt}\n\n看完后不用在这里答题，下一步做一题很小的检查。"
            hint = support_hint or "看懂每一步为什么成立后点继续；如果哪一步看不懂，直接点还是卡住。"
        elif step_type == "teaching_repair":
            prompt = support_hint or "先把关键关系写清楚，再做计算和检查。"
            hint = "看完后点继续，系统会给一题很小的检查；如果还是卡住，也可以直接说卡住。"
        else:
            prompt = question_child_surface["prompt"]
            hint = support_hint or (
                "按你平时的方式完成；如果卡住了，也可以直接写卡在哪里。"
                if unprompted_process
                else "先写你能确定的规则或关系；如果卡住了，也可以直接写卡在哪里。"
            )
        package_child_surface = question_child_surface
        if step_type not in {"worked_example", "teaching_repair"}:
            package_child_surface = child_prompt.project_child_surface(
                prompt=prompt,
                prompt_format=child_prompt.CHILD_PROMPT_FORMAT,
                interaction_schema=child_interaction_schema,
                allow_legacy=False,
                limit=2000,
            )
        self.conn.execute(
            """
            insert into flow_steps(
              id, flow_id, step_handle, position, step_type, status, graph_version,
              node_id, question_bank_version, question_id, question_item_version,
              review_record_id, expected_evidence_json, prompt_package_json,
              selection_reason_json, source_next_step_decision_id, candidate_packet_id,
              answer_contract_id, answer_contract_version,
              answer_contract_digest_sha256, step_revision, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                step_id,
                flow_id,
                f"step-{uuid.uuid4().hex[:10]}",
                int(position),
                step_type,
                initial_status,
                graph_version,
                question["node_id"],
                question.get("item_version") or question.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION,
                question["id"],
                question.get("item_version") or question_bank.QUESTION_BANK_VERSION,
                review_record_id,
                db.json_dump({"requires_process": True, "allows_stuck": True, "allows_photo": True}),
                db.json_dump({
                    "title": node["name"] if node else "复习小题",
                    "topic_label": node["name"] if node else "复习小题",
                    "prompt": prompt,
                    "prompt_format": package_child_surface["prompt_format"],
                    "child_surface_projection_sha256": package_child_surface["projection_sha256"],
                    "answer_input_mode": effective_input_mode,
                    "upload_enabled": upload_enabled,
                    "stuck_enabled": True,
                    "hint": hint,
                    "continue_label": "继续下一题" if assessment_feedback else "",
                    "requires_explanation": requires_explanation,
                    "interaction_schema": child_interaction_schema,
                    "teaching_sections": teaching_sections or {},
                    "assessment_feedback": assessment_feedback or {},
                    "question_visual": question_visual,
                    "allowed_response_modes": ["continue", "stuck"] if step_type in {"worked_example", "teaching_repair"} else None,
                }),
                db.json_dump(selection_reason),
                selection_reason.get("source_next_step_decision_id"),
                packet.get("packet_id", ""),
                (answer_contract or {}).get("id"),
                (answer_contract or {}).get("contract_version"),
                (answer_contract or {}).get("contract_digest_sha256"),
                now,
                now,
            ),
        )
        return step_id

    def _question_visual_for_question(
        self,
        question: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not question_visuals.visual_required_by_policy(question):
            return None
        try:
            manifest = question_visuals.QuestionVisualManifest.load_active(
                self.conn,
                project_root=self.project_root,
            )
            requirement = question_visuals.required_binding_for_question(
                question,
                manifest=manifest,
            )
            if requirement is None:
                return None
            visual = manifest.child_visual_for_question(question)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ChildSafeRuntimeError(
                "这道题需要的题面图还没有安全准备好，请稍后再试。",
                status=503,
                child_action="稍后重试",
            ) from exc
        if visual is None:
            raise ChildSafeRuntimeError(
                "这道题需要的题面图还没有安全准备好，请稍后再试。",
                status=503,
                child_action="稍后重试",
            )
        return visual

    def _answer_photo_data_url_for_attempt(self, attempt_id: str) -> str | None:
        for attachment in db.attachments_for_attempt(self.conn, attempt_id):
            if attachment["kind"] != "answer_photo" or attachment["content_type"] not in ALLOWED_ANSWER_PHOTO_TYPES:
                continue
            filename = attachment["filename"]
            if not filename or "/" in filename or "\\" in filename or Path(filename).name != filename:
                continue
            target = (self.project_root / attachment["relative_path"]).resolve()
            upload_root = (self.project_root / ANSWER_UPLOAD_RELATIVE_PREFIX).resolve()
            if target.parent != upload_root or not target.is_file():
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

    def _record_model_agent_run(
        self,
        *,
        agent_key: str,
        session_id: str,
        phase: str,
        trigger: str,
        route: model_router.ModelRoute,
        status: str,
        confidence: float,
        input_refs: dict[str, Any],
        output: dict[str, Any],
        error_reason: str = "",
        route_meta: dict[str, Any] | None = None,
        use_v5_contract: bool = False,
    ) -> dict[str, Any]:
        role = internal_agents.INTERNAL_AGENT_ROLES[agent_key]
        contract = internal_agents.load_v5_contract_for_agent(agent_key) if use_v5_contract else internal_agents.load_contract(role["contract_key"])
        prompt_path = internal_agents.prompt_path_for_contract(contract)
        return db.record_agent_run(
            self.conn,
            agent_key=agent_key,
            engine_type="model" if route.enabled else "hybrid",
            session_id=session_id,
            phase=phase,
            trigger=trigger,
            input_refs=input_refs,
            prompt_version_id=str(contract.get("prompt_version_id") or ""),
            prompt_template_sha256=internal_agents.file_sha256(prompt_path) if prompt_path.exists() else "",
            model_provider=route.provider if route.enabled else "",
            model_name=route.model if route.enabled else "",
            model_alias=route.model_alias if route.enabled else "",
            model_params=({**route.model_params, **(route_meta or {})} if route.enabled else (route_meta or {})),
            response_schema_version=str(contract.get("response_schema_version") or ""),
            response_schema_sha256=db._digest_json(contract),
            status=status,
            confidence=confidence,
            output=output,
            error_reason=error_reason[:800],
            commit=False,
        )

    def _record_deterministic_agent_run(
        self,
        *,
        agent_key: str,
        session_id: str,
        phase: str,
        trigger: str,
        input_refs: dict[str, Any],
        output: dict[str, Any],
        status: str = "accepted",
        confidence: float = 1.0,
        use_v5_contract: bool = False,
    ) -> dict[str, Any]:
        role = internal_agents.INTERNAL_AGENT_ROLES[agent_key]
        contract = internal_agents.load_v5_contract_for_agent(agent_key) if use_v5_contract else internal_agents.load_contract(role["contract_key"])
        prompt_path = internal_agents.prompt_path_for_contract(contract)
        return db.record_agent_run(
            self.conn,
            agent_key=agent_key,
            engine_type="deterministic",
            session_id=session_id,
            phase=phase,
            trigger=trigger,
            input_refs=input_refs,
            prompt_version_id=str(contract.get("prompt_version_id") or ""),
            prompt_template_sha256=internal_agents.file_sha256(prompt_path) if prompt_path.exists() else "",
            response_schema_version=str(contract.get("response_schema_version") or ""),
            response_schema_sha256=db._digest_json(contract),
            status=status,
            confidence=confidence,
            output=output,
            commit=False,
        )

    def _record_evaluation_update(
        self,
        *,
        attempt: dict[str, Any],
        validation: evidence_gate.EvidenceValidationResult,
        provider_mode: str,
        evaluation_agent_run_id: str | None = None,
        evaluation_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        support = attempt.get("answer_analysis", {}).get("evaluation_support", {})
        evaluation_output = evaluation_output or {}
        usable = validation.predicate.usable
        if not usable:
            return {
                "applied": False,
                "status_code": "",
                "reason": "Evidence gate did not pass.",
                "validation_id": validation.validation_id,
                "report_label": validation.predicate.report_label,
            }
        recommendation = str(evaluation_output.get("mastery_recommendation") or "")
        old_status = self.conn.execute(
            "select * from learner_node_status where node_id = ?",
            (attempt["node_id"],),
        ).fetchone()
        old_attempt_ids = db.json_load(old_status["source_attempt_ids_json"], []) if old_status else []
        old_validation_ids = db.json_load(old_status["source_evidence_validation_ids_json"], []) if old_status else []
        source_attempt_ids = list(dict.fromkeys([*(str(item) for item in old_attempt_ids if item), attempt["id"]]))
        source_validation_ids = list(dict.fromkeys([*(str(item) for item in old_validation_ids if item), *([validation.validation_id] if validation.validation_id else [])]))
        if attempt.get("blocking_evidence") or recommendation == "blocked":
            status_code = "D"
            decision = "prerequisite_blocked"
            reason = str(evaluation_output.get("reason") or "孩子明确卡住或证据显示不能启动。")
        elif recommendation == "stable_for_now" and self._evidence_set_supports_stable_mastery(source_validation_ids):
            status_code = "A"
            decision = "stable_for_now"
            reason = str(evaluation_output.get("reason") or "多条不同核心证据和近迁移证据支持暂时稳定。")
        elif recommendation in {"weak"}:
            status_code = "C"
            decision = "current_node_weak"
            reason = str(evaluation_output.get("reason") or "有效证据显示当前节点仍不稳。")
        elif recommendation == "emerging":
            if old_status and old_status["status_code"] in {"A", "C"}:
                status_code = old_status["status_code"]
                decision = "preserve_accumulated_status"
                reason = str(evaluation_output.get("reason") or "单条高分证据不足以覆盖已有累积状态。")
            else:
                status_code = "B"
                decision = "basic_understanding"
                reason = str(evaluation_output.get("reason") or "本题关键得分点成立，先记为初步掌握，仍需迁移确认。")
        elif old_status and old_status["status_code"] in {"A", "C"} and recommendation == "":
            status_code = old_status["status_code"]
            decision = "preserve_accumulated_status"
            reason = str(evaluation_output.get("reason") or "单条窄证据不足以覆盖已有累积状态。")
        elif recommendation == "likely_stable":
            status_code = "B"
            decision = "likely_stable"
            reason = str(evaluation_output.get("reason") or "重复证据支持基本理解，但仍需迁移确认。")
        elif attempt.get("result") == "correct" and int(attempt.get("explanation_score") or 0) >= 2 and support.get("reasoning_soundness") == "sound":
            status_code = "B"
            decision = "basic_understanding"
            reason = str(evaluation_output.get("reason") or "本题答案和关键过程成立，但仍需变式确认稳定性。")
        elif attempt.get("result") == "partial":
            status_code = "C"
            decision = "current_node_weak"
            reason = "有部分思路，但过程、表达或检验仍不稳。"
        else:
            status_code = "C"
            decision = "current_node_weak"
            reason = "有效证据显示当前节点存在断点。"
        if recommendation in {"blocked", "weak"} and status_code == "B":
            status_code = "C"
            decision = "current_node_weak"
            reason = str(evaluation_output.get("reason") or reason)
        if evaluation_agent_run_id:
            run = {"id": evaluation_agent_run_id}
        else:
            run = self._record_deterministic_agent_run(
                agent_key="evaluation_agent",
                session_id=attempt["session_id"],
                phase="evaluation_update",
                trigger=f"v5_evaluation_update:{attempt['id']}:{validation.validation_id}",
                input_refs={
                    "attempt_id": attempt["id"],
                    "evidence_validation_id": validation.validation_id,
                    "provider_mode": provider_mode,
                },
                output={
                    "node_id": attempt["node_id"],
                    "status_code": status_code,
                    "decision": decision,
                    "reason": reason,
                    "analysis_support": support,
                    "evaluation_agent_output": evaluation_output,
                },
            )
        source_validation_hash = db._digest_json({
            "attempt_id": attempt["id"],
            "validation_id": validation.validation_id,
            "analysis_version": attempt.get("analysis_version"),
        })
        decision_id = f"MD-{uuid.uuid4().hex[:12]}"
        now = db.now_iso()
        self.conn.execute(
            """
            insert or ignore into mastery_decisions(
              id, session_id, node_id, decision, closure_result,
              evidence_attempt_ids_json, agent_run_id, applied, reason,
              decision_payload_json, graph_version, question_bank_version,
              source_attempt_ids_json, source_evidence_validation_ids_json,
              evaluation_agent_run_id, decision_version, old_status_id,
              new_status_code, dimension_scores_json, source_evidence_validation_hash,
              created_at
            ) values (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                attempt["session_id"],
                attempt["node_id"],
                decision,
                "mastered_for_now" if status_code == "A" else ("repaired_not_mastered" if status_code in {"B", "C"} else "prerequisite_blocked"),
                db.json_dump(source_attempt_ids),
                run["id"],
                reason,
                db.json_dump({"evaluation_support": support, "report_label": validation.predicate.report_label, "evaluation_agent_output": evaluation_output}),
                attempt.get("graph_version") or "",
                attempt.get("question_bank_version") or "",
                db.json_dump(source_attempt_ids),
                db.json_dump(source_validation_ids),
                run["id"],
                str(old_status["status_revision"]) if old_status else "",
                status_code,
                db.json_dump({
                    "result": attempt.get("result"),
                    "explanation_score": attempt.get("explanation_score"),
                    "weak_dimensions": support.get("dominant_gap_dimensions", []),
                }),
                source_validation_hash,
                now,
            ),
        )
        canonical = self.conn.execute(
            """
            select *
            from mastery_decisions
            where node_id = ?
              and graph_version = ?
              and source_evidence_validation_hash = ?
              and decision_version = 1
            order by created_at, id
            limit 1
            """,
            (attempt["node_id"], attempt.get("graph_version") or "", source_validation_hash),
        ).fetchone()
        if canonical:
            decision_id = canonical["id"]
            run_id_for_status = canonical["evaluation_agent_run_id"] or canonical["agent_run_id"] or run["id"]
        else:
            run_id_for_status = run["id"]
        self.conn.execute(
            """
            insert or replace into learner_node_status(
              node_id, status_code, latest_score, can_explain,
              evidence_attempt_ids_json, status_reason, graph_version,
              question_bank_version, mastery_decision_id, source_attempt_ids_json,
              source_evidence_validation_ids_json, updated_by_agent_run_id,
              status_revision, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, coalesce((select status_revision + 1 from learner_node_status where node_id = ?), 1), ?)
            """,
            (
                attempt["node_id"],
                status_code,
                float(attempt.get("score_points") or 0) / max(float(attempt.get("max_points") or 2), 1.0),
                1 if status_code in {"A", "B"} and int(attempt.get("explanation_score") or 0) >= 2 else 0,
                db.json_dump(source_attempt_ids),
                f"Evaluation Agent: {reason}",
                attempt.get("graph_version") or "",
                attempt.get("question_bank_version") or "",
                decision_id,
                db.json_dump(source_attempt_ids),
                db.json_dump(source_validation_ids),
                run_id_for_status,
                attempt["node_id"],
                now,
            ),
        )
        return {
            "applied": True,
            "status_code": status_code,
            "decision": decision,
            "reason": reason,
            "validation_id": validation.validation_id,
            "agent_run_id": run_id_for_status,
            "mastery_decision_id": decision_id,
        }

    def _evidence_set_supports_stable_mastery(self, validation_ids: list[str]) -> bool:
        ids = [str(item) for item in validation_ids if item]
        if len(ids) < 3:
            return False
        placeholders = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"""
            select ev.id, q.kind, q.variant_level, q.raw_json
            from evidence_validations ev
            left join question_items q on q.id = ev.question_id
            where ev.id in ({placeholders})
              and ev.gate_status = 'passed'
            """,
            ids,
        ).fetchall()
        cores: set[str] = set()
        has_transfer = False
        for row in rows:
            raw = db.json_load(row["raw_json"], {})
            cores.add(str(raw.get("core_stem_id") or raw.get("math_core_signature") or row["id"]))
            kind = str(row["kind"] or row["variant_level"] or "")
            if kind in {"transfer_retest", "near_transfer"}:
                has_transfer = True
        return len(cores) >= 3 and has_transfer

    def _advance_after_analysis(
        self,
        *,
        flow_id: str,
        source_step_id: str,
        attempt: dict[str, Any],
        validation: evidence_gate.EvidenceValidationResult,
        evaluation: dict[str, Any],
        provider_mode: str,
    ) -> dict[str, Any]:
        flow = dict(self._flow_by_id(flow_id))
        step_count = self.conn.execute(
            "select count(*) from flow_steps where flow_id = ?",
            (flow_id,),
        ).fetchone()[0]
        current_step = self.conn.execute("select * from flow_steps where id = ?", (source_step_id,)).fetchone()
        if current_step:
            self.conn.execute(
                "update flow_steps set status = 'completed', updated_at = ? where id = ?",
                (db.now_iso(), source_step_id),
            )

        if not validation.predicate.usable:
            decision = self._record_next_step_decision(
                flow=flow,
                action="blocked",
                report_label=validation.predicate.report_label,
                source_step_id=source_step_id,
                source_attempt_ids=[attempt["id"]],
                source_validation_ids=[validation.validation_id] if validation.validation_id else [],
                provider_mode=provider_mode,
                reason="Evidence gate rejected or kept evidence pending; no mastery-dependent step selected.",
            )
            self._block_flow(flow_id, "这一步还不能可靠判断，需要系统恢复或补充更清楚的答案。")
            return decision

        if step_count >= int(flow.get("budget_min") or 10):
            decision = self._record_next_step_decision(
                flow=flow,
                action="summary",
                report_label=validation.predicate.report_label,
                source_step_id=source_step_id,
                source_attempt_ids=[attempt["id"]],
                source_validation_ids=[validation.validation_id] if validation.validation_id else [],
                source_mastery_ids=[evaluation.get("mastery_decision_id")] if evaluation.get("mastery_decision_id") else [],
                provider_mode=provider_mode,
                reason="Reached the normal review budget; close with evidence summary.",
            )
            summary_id = self._ensure_daily_summary(
                flow,
                reason="budget_min_reached",
                target_flow_revision=int(flow.get("flow_revision") or 1) + 1,
            )
            self.conn.execute(
                """
                update daily_flows
                set status = 'completed',
                    current_step_id = null,
                    summary_id = ?,
                    flow_revision = flow_revision + 1,
                    updated_at = ?
                where id = ?
                """,
                (summary_id, db.now_iso(), flow_id),
            )
            return decision

        if attempt.get("blocking_evidence") or attempt.get("result") in {"wrong", "partial"}:
            if attempt.get("blocking_evidence") or attempt.get("result") == "wrong":
                next_selection = self._next_selection_after_attempt(flow, attempt=attempt)
                if next_selection and next_selection.get("action") == "prerequisite_probe":
                    decision = self._record_next_step_decision(
                        flow=flow,
                        action="prerequisite_probe",
                        report_label=validation.predicate.report_label,
                        source_step_id=source_step_id,
                        source_attempt_ids=[attempt["id"]],
                        source_validation_ids=[validation.validation_id] if validation.validation_id else [],
                        source_mastery_ids=[evaluation.get("mastery_decision_id")] if evaluation.get("mastery_decision_id") else [],
                        provider_mode=provider_mode,
                        reason=next_selection["reason"],
                        candidate_packet=next_selection.get("candidate_packet"),
                        target_node_id=next_selection["question"]["node_id"],
                    )
                    new_step_id = self._create_question_step(
                        flow_id=flow_id,
                        position=step_count + 1,
                        graph_version=flow["graph_version"],
                        question=next_selection["question"],
                        review_record_id=next_selection["review_record_id"],
                        selection_reason={
                            **(next_selection.get("selection_reason") or {}),
                            "source_next_step_decision_id": decision["id"],
                        },
                        candidate_packet=next_selection.get("candidate_packet") or {},
                        support_hint="先回到更前面的关键关系，用一题小检查确认断点。",
                    )
                    self.conn.execute(
                        """
                        update daily_flows
                        set status = 'reviewing',
                            current_step_id = ?,
                            flow_revision = flow_revision + 1,
                            updated_at = ?
                        where id = ?
                        """,
                        (new_step_id, db.now_iso(), flow_id),
                    )
                    return decision
            decision = self._record_next_step_decision(
                flow=flow,
                action="micro_teach",
                report_label=validation.predicate.report_label,
                source_step_id=source_step_id,
                source_attempt_ids=[attempt["id"]],
                source_validation_ids=[validation.validation_id] if validation.validation_id else [],
                source_mastery_ids=[evaluation.get("mastery_decision_id")] if evaluation.get("mastery_decision_id") else [],
                provider_mode=provider_mode,
                reason="先讲清第一个断点，再用小检查确认，而不是直接连续刷题。",
                target_node_id=attempt["node_id"],
            )
            teaching_step_id = self._create_teaching_repair_step(
                flow=flow,
                source_attempt=attempt,
                source_step_id=source_step_id,
                source_next_step_decision_id=decision["id"],
                position=step_count + 1,
            )
            self.conn.execute(
                """
                update daily_flows
                set status = 'reviewing',
                    current_step_id = ?,
                    flow_revision = flow_revision + 1,
                    updated_at = ?
                where id = ?
                """,
                (teaching_step_id, db.now_iso(), flow_id),
            )
            return decision

        next_selection = self._next_selection_after_attempt(flow, attempt=attempt)
        if not next_selection:
            decision = self._record_next_step_decision(
                flow=flow,
                action="summary",
                report_label=validation.predicate.report_label,
                source_step_id=source_step_id,
                source_attempt_ids=[attempt["id"]],
                source_validation_ids=[validation.validation_id] if validation.validation_id else [],
                source_mastery_ids=[evaluation.get("mastery_decision_id")] if evaluation.get("mastery_decision_id") else [],
                provider_mode=provider_mode,
                reason="No eligible next question found from bounded candidate packets.",
            )
            summary_id = self._ensure_daily_summary(
                flow,
                reason="no_eligible_next_question",
                target_flow_revision=int(flow.get("flow_revision") or 1) + 1,
            )
            self.conn.execute(
                """
                update daily_flows
                set status = 'completed',
                    current_step_id = null,
                    summary_id = ?,
                    flow_revision = flow_revision + 1,
                    updated_at = ?
                where id = ?
                """,
                (summary_id, db.now_iso(), flow_id),
            )
            return decision

        action = next_selection["action"]
        analysis = attempt.get("answer_analysis") or {}
        support_hint = ""
        if action in {"same_structure_retest", "prerequisite_probe"}:
            support_hint = _child_safe_text(
                f"先看刚才这一点：{analysis.get('teaching_explanation') or analysis.get('process_gap') or '把关键关系、步骤和检验写清楚。'}",
                "先把关键关系、步骤和检验写清楚。",
                limit=420,
            )
        decision = self._record_next_step_decision(
            flow=flow,
            action=action,
            report_label=validation.predicate.report_label,
            source_step_id=source_step_id,
            source_attempt_ids=[attempt["id"]],
            source_validation_ids=[validation.validation_id] if validation.validation_id else [],
            source_mastery_ids=[evaluation.get("mastery_decision_id")] if evaluation.get("mastery_decision_id") else [],
            provider_mode=provider_mode,
            reason=next_selection["reason"],
            candidate_packet=next_selection.get("candidate_packet"),
            target_node_id=next_selection["question"]["node_id"],
        )
        selection_reason = {
            **(next_selection.get("selection_reason") or {}),
            "source_next_step_decision_id": decision["id"],
        }
        new_step_id = self._create_question_step(
            flow_id=flow_id,
            position=step_count + 1,
            graph_version=flow["graph_version"],
            question=next_selection["question"],
            review_record_id=next_selection["review_record_id"],
            selection_reason=selection_reason,
            candidate_packet=next_selection.get("candidate_packet") or {},
            support_hint=support_hint,
        )
        self.conn.execute(
            """
            update daily_flows
            set status = 'reviewing',
                current_step_id = ?,
                flow_revision = flow_revision + 1,
                updated_at = ?
            where id = ?
            """,
            (new_step_id, db.now_iso(), flow_id),
        )
        return decision

    def _create_v51_assessment_feedback_step(
        self,
        *,
        flow: dict[str, Any],
        source_attempt: dict[str, Any],
        source_step_id: str,
        source_next_step_decision_id: str,
        position: int,
        assessment: dict[str, Any],
        contract: dict[str, Any],
        needs_repair: bool,
    ) -> str:
        feedback = assessment_store.assessment_feedback_projection(assessment)
        reference = contract.get("reference_solution") if isinstance(contract.get("reference_solution"), dict) else {}
        solution_steps = [
            str(item).strip()
            for item in (reference.get("solution_steps") or [])
            if str(item).strip()
        ][:5]
        teaching_explanation = _child_safe_text(
            assessment.get("teaching_explanation") or "先对照标准答案看清关键关系。",
            "先对照标准答案看清关键关系。",
            limit=520,
        )
        teaching_sections = {
            "essence": {
                "title": "为什么这样判断",
                "body": teaching_explanation,
            },
            "worked_example": {
                "title": "参考解法",
                "problem": _child_safe_text(
                    feedback.get("reference_answer") or "见标准答案",
                    "见标准答案",
                    limit=420,
                ),
                "steps": solution_steps,
                "check": _child_safe_text(
                    feedback.get("expression_judgment") or "表达按数学意图判断。",
                    "表达按数学意图判断。",
                    limit=260,
                ),
            },
            "next_micro_check": {
                "title": "下一步",
                "prompt": (
                    "先把这一处修明白，再做一道相近的小检查。"
                    if needs_repair
                    else "换一道结构相近的题，确认不是只会这一题。"
                ),
            },
        }
        question = db.get_question(self.conn, source_attempt["question_id"])
        return self._create_question_step(
            flow_id=flow["id"],
            position=position,
            graph_version=flow["graph_version"],
            question=question,
            review_record_id=source_attempt.get("review_record_id") or "",
            selection_reason={
                "reason": "v5.1_assessment_feedback",
                "source_attempt_id": source_attempt["id"],
                "source_step_id": source_step_id,
                "planned_next_step_decision_id": source_next_step_decision_id,
                "needs_repair": needs_repair,
            },
            candidate_packet={},
            support_hint=(
                "先看本题得分和差距，再把关键断点修清楚。"
                if needs_repair
                else "先看本题得分和解析，再继续下一题。"
            ),
            step_type="teaching_repair",
            answer_input_mode="none",
            teaching_sections=teaching_sections,
            assessment_feedback=feedback,
        )

    def _create_teaching_repair_step(
        self,
        *,
        flow: dict[str, Any],
        source_attempt: dict[str, Any],
        source_step_id: str,
        source_next_step_decision_id: str,
        position: int,
    ) -> str:
        if source_next_step_decision_id:
            existing = self.conn.execute(
                """
                select id
                from flow_steps
                where flow_id = ?
                  and source_next_step_decision_id = ?
                  and superseded_by_step_id is null
                order by created_at, id
                limit 1
                """,
                (flow["id"], source_next_step_decision_id),
            ).fetchone()
            if existing:
                return existing["id"]
        analysis = source_attempt.get("answer_analysis") or {}
        question = db.get_question(self.conn, source_attempt["question_id"])
        node = self.conn.execute("select name from graph_nodes where id = ?", (source_attempt["node_id"],)).fetchone()
        first_break = (
            analysis.get("process_gap")
            or analysis.get("teaching_explanation")
            or "这一步的关键关系、步骤或检验还不够稳。"
        )
        next_prompt = analysis.get("next_child_prompt") or "接下来用一道小检查确认这一步是否修住。"
        now = db.now_iso()
        step_id = f"FS-{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            insert into flow_steps(
              id, flow_id, step_handle, position, step_type, status, graph_version,
              node_id, question_bank_version, question_id, question_item_version,
              review_record_id, expected_evidence_json, prompt_package_json,
              selection_reason_json, source_next_step_decision_id, candidate_packet_id,
              step_revision, created_at, updated_at
            ) values (?, ?, ?, ?, 'teaching_repair', 'selected', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 1, ?, ?)
            """,
            (
                step_id,
                flow["id"],
                f"step-{uuid.uuid4().hex[:10]}",
                int(position),
                flow["graph_version"],
                source_attempt["node_id"],
                flow.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION,
                question["id"],
                question.get("item_version") or question_bank.QUESTION_BANK_VERSION,
                source_attempt.get("review_record_id") or "",
                db.json_dump({"teaching_only": True, "requires_followup_check": True}),
                db.json_dump({
                    "title": "先修这一处",
                    "topic_label": node["name"] if node else "先修这一处",
                    "prompt": f"刚才的关键断点：{first_break}\n\n先看这一句：{analysis.get('teaching_explanation') or first_break}\n\n下一步：{next_prompt}",
                    "answer_input_mode": "none",
                    "upload_enabled": False,
                    "stuck_enabled": True,
                    "hint": "看完后点继续，系统会给一题很小的检查；如果还是卡住，也可以直接说卡住。",
                }),
                db.json_dump({
                    "reason": "teaching_repair_after_usable_weak_evidence",
                    "source_attempt_id": source_attempt["id"],
                    "source_step_id": source_step_id,
                }),
                source_next_step_decision_id,
                now,
                now,
            ),
        )
        return step_id

    def _next_selection_after_attempt(self, flow: dict[str, Any], *, attempt: dict[str, Any]) -> dict[str, Any] | None:
        analysis = attempt.get("answer_analysis") or {}
        support = analysis.get("evaluation_support") if isinstance(analysis.get("evaluation_support"), dict) else {}
        target_error_tags = list(attempt.get("error_tags") or [])
        unstable_dimensions = list(support.get("dominant_gap_dimensions") or [])
        if attempt.get("blocking_evidence") or attempt.get("result") == "wrong":
            rollback_nodes = self.graph.rollback_candidates(attempt["node_id"])
            for node_id in rollback_nodes + [attempt["node_id"]]:
                selected = self._select_question_for_node(
                    node_id,
                    graph_version=flow["graph_version"],
                    flow_id=flow["id"],
                    flow_revision=int(flow.get("flow_revision") or 1) + 1,
                    reason={
                        "reason": "failed_current_node_prerequisite_probe",
                        "source_attempt_id": attempt["id"],
                        "source_node_id": attempt["node_id"],
                    },
                    target_error_tags=target_error_tags,
                    unstable_dimensions=unstable_dimensions,
                    selection_intent="wrong_blocking",
                )
                if selected:
                    return {
                        **selected,
                        "action": "prerequisite_probe" if node_id != attempt["node_id"] else "same_structure_retest",
                        "reason": "失败后先沿前置链或同结构小题确认断点。",
                    }
        if attempt.get("result") == "partial":
            selected = self._select_question_for_node(
                attempt["node_id"],
                graph_version=flow["graph_version"],
                flow_id=flow["id"],
                flow_revision=int(flow.get("flow_revision") or 1) + 1,
                reason={"reason": "partial_reasoning_same_structure_retest", "source_attempt_id": attempt["id"]},
                target_error_tags=target_error_tags,
                unstable_dimensions=unstable_dimensions,
                selection_intent="partial_unstable",
            )
            if selected:
                return {**selected, "action": "same_structure_retest", "reason": "思路部分成立但不稳定，换一道同结构题确认。"}
        stable_context = self._stable_ready_context(str(attempt.get("node_id") or ""))
        if attempt.get("result") == "correct" and stable_context["supported"]:
            selected = self._select_question_for_node(
                attempt["node_id"],
                graph_version=flow["graph_version"],
                flow_id=flow["id"],
                flow_revision=int(flow.get("flow_revision") or 1) + 1,
                reason={"reason": "stable_ready_extension_or_transfer", "source_attempt_id": attempt["id"]},
                preferred_kinds=["stretch_transfer", "variant", "transfer_retest", "reverse_reasoning"],
                selection_intent="stable_ready",
                next_evidence_goal="stretch_readiness",
                learner_status=stable_context["learner_status"],
                prerequisite_ready=stable_context["prerequisite_ready"],
            )
            if selected:
                action = "stretch" if self._selection_looks_like_stretch(selected) else "near_transfer_retest"
                return {
                    **selected,
                    "action": action,
                    "reason": "当前节点已有稳定且有迁移证据，可选择受控拓展；若无合适拓展则继续近迁移确认。",
                }
        selected = self._select_question_for_node(
            attempt["node_id"],
            graph_version=flow["graph_version"],
            flow_id=flow["id"],
            flow_revision=int(flow.get("flow_revision") or 1) + 1,
            reason={"reason": "correct_reasoning_near_transfer_retest", "source_attempt_id": attempt["id"]},
            preferred_kinds=["variant", "transfer_retest", "reverse_reasoning", "error_spotting"],
            selection_intent="correct_narrow",
            next_evidence_goal="near_transfer_retest",
        )
        if selected:
            return {**selected, "action": "near_transfer_retest", "reason": "本题过程成立，换近迁移题确认是否真的稳定。"}
        return None

    def _stable_ready_context(self, node_id: str) -> dict[str, Any]:
        status = self.conn.execute(
            "select * from learner_node_status where node_id = ? limit 1",
            (node_id,),
        ).fetchone()
        learner_status = str(status["status_code"] or "") if status else ""
        prerequisite_ready = self._direct_prerequisites_ready(node_id)
        supported = (
            learner_status == "A"
            and prerequisite_ready
            and self._has_varied_transfer_evidence(node_id, dict(status) if status else {})
        )
        return {
            "supported": supported,
            "learner_status": learner_status,
            "prerequisite_ready": prerequisite_ready,
        }

    def _direct_prerequisites_ready(self, node_id: str) -> bool:
        node = self.graph.get_node(node_id) or {}
        prerequisites = [str(item) for item in (node.get("prerequisites") or []) if str(item)]
        if not prerequisites:
            return True
        placeholders = ",".join("?" for _ in prerequisites)
        rows = self.conn.execute(
            f"select node_id, status_code from learner_node_status where node_id in ({placeholders})",
            prerequisites,
        ).fetchall()
        status_by_node = {str(row["node_id"]): str(row["status_code"] or "") for row in rows}
        return all(status_by_node.get(node_id) == "A" for node_id in prerequisites)

    def _has_varied_transfer_evidence(self, node_id: str, status: dict[str, Any]) -> bool:
        attempt_ids = [
            str(item)
            for item in (
                db.json_load(status.get("source_attempt_ids_json"), [])
                or db.json_load(status.get("evidence_attempt_ids_json"), [])
                or []
            )
            if str(item)
        ]
        if not attempt_ids:
            return False
        placeholders = ",".join("?" for _ in attempt_ids)
        rows = self.conn.execute(
            f"""
            select a.id, a.result, a.score_points, a.max_points, a.grading_status,
                   a.analysis_status, q.kind, q.raw_json, q.source_json
            from attempts a
            join question_items q on q.id = a.question_id
            where a.id in ({placeholders})
              and a.node_id = ?
              and a.evidence_status = 'active'
            """,
            [*attempt_ids, node_id],
        ).fetchall()
        core_ids: set[str] = set()
        has_transfer = False
        transfer_kinds = {
            "transfer_retest",
            "stretch_transfer",
            "variant",
            "two_method_compare",
            "model_selection",
        }
        transfer_roles = {
            "near_transfer",
            "integrated_transfer",
            "multi_representation",
            "alternative_method",
            "summary_transfer_check",
            "stretch_readiness_check",
        }
        for row in rows:
            try:
                ratio = float(row["score_points"] or 0) / float(row["max_points"] or 0)
            except (TypeError, ValueError, ZeroDivisionError):
                ratio = 0.0
            if row["grading_status"] != "graded" or row["analysis_status"] != "valid":
                continue
            if row["result"] != "correct" or ratio < 0.85:
                continue
            raw = db.json_load(row["raw_json"], {}) if row["raw_json"] else {}
            source = db.json_load(row["source_json"], {}) if row["source_json"] else {}
            core_ids.add(str(raw.get("core_stem_id") or source.get("core_stem_id") or row["id"]))
            slot_role = str(source.get("slot_role") or "")
            evidence_role = str(source.get("evidence_role") or source.get("evidence_goal") or "")
            if str(row["kind"] or "") in transfer_kinds or slot_role in transfer_roles or "transfer" in evidence_role:
                has_transfer = True
        return has_transfer and len(core_ids) >= 2

    def _selection_looks_like_stretch(self, selected: dict[str, Any]) -> bool:
        question = selected.get("question") if isinstance(selected.get("question"), dict) else {}
        question_id = str(question.get("id") or "")
        for candidate in (selected.get("candidate_packet") or {}).get("candidates") or []:
            if str(candidate.get("question_id") or "") != question_id:
                continue
            role_text = " ".join(
                str(candidate.get(key) or "")
                for key in ("slot_role", "evidence_role", "kind")
            ).lower()
            return bool(candidate.get("controlled_stretch")) or "stretch" in role_text
        kind = str(question.get("kind") or "").lower()
        return "stretch" in kind

    def _record_next_step_decision(
        self,
        *,
        flow: dict[str, Any],
        action: str,
        report_label: str,
        source_step_id: str,
        source_attempt_ids: list[str],
        source_validation_ids: list[str],
        provider_mode: str,
        reason: str,
        source_mastery_ids: list[str] | None = None,
        candidate_packet: dict[str, Any] | None = None,
        target_node_id: str | None = None,
        planner_agent_run_id: str | None = None,
        branch_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        packet = candidate_packet or {}
        if planner_agent_run_id:
            run = {"id": planner_agent_run_id}
        else:
            run = self._record_deterministic_agent_run(
                agent_key="planner_agent",
                session_id=flow["legacy_session_id"],
                phase="planner_decision",
                trigger=f"v5_next_step:{flow['id']}:{flow.get('flow_revision')}:{source_step_id or action}",
                input_refs={
                    "flow_id": flow["id"],
                    "source_step_id": source_step_id,
                    "source_attempt_ids": source_attempt_ids,
                    "source_evidence_validation_ids": source_validation_ids,
                    "candidate_packet_id": packet.get("packet_id", ""),
                },
                output={
                    "action": action,
                    "target_node_id": target_node_id,
                    "reason": reason,
                    "report_label": report_label,
                },
            )
        decision_id = f"NSD-{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            insert or ignore into next_step_decisions(
              id, flow_id, flow_revision, decision_version, decision_status,
              action, graph_version, question_bank_version, target_node_id,
              source_step_id, source_attempt_ids_json,
              source_evidence_validation_ids_json, source_mastery_decision_ids_json,
              candidate_packet_id, candidate_packet_hash,
              candidate_filter_summary_json, pending_evidence_ids_json,
              skipped_node_ids_json, branch_policy_json, planner_agent_run_id,
              provider_mode, fallback_reason, stale_lineage_ids_json,
              mock_source_ids_json, report_label, reason, created_at
            ) values (?, ?, ?, 1, 'accepted', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, '[]', ?, ?, ?, ?)
            """,
            (
                decision_id,
                flow["id"],
                int(flow.get("flow_revision") or 1),
                action,
                flow["graph_version"],
                flow.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION,
                target_node_id,
                source_step_id or None,
                db.json_dump(source_attempt_ids),
                db.json_dump([item for item in source_validation_ids if item]),
                db.json_dump([item for item in (source_mastery_ids or []) if item]),
                packet.get("packet_id", ""),
                packet.get("packet_hash", ""),
                db.json_dump(packet.get("filter_summary") or {}),
                db.json_dump([] if report_label == "confirmed" else source_attempt_ids),
                db.json_dump({**(branch_policy or {}), "v5_action": action, "bounded_candidate_packet": bool(packet)}),
                run["id"],
                provider_mode,
                "" if action != "summary" else reason,
                db.json_dump(source_attempt_ids if provider_mode == "mock_only" else []),
                report_label,
                reason[:1000],
                db.now_iso(),
            ),
        )
        canonical = self.conn.execute(
            """
            select *
            from next_step_decisions
            where flow_id = ?
              and flow_revision = ?
              and coalesce(source_step_id, '') = coalesce(?, '')
              and decision_version = 1
            order by created_at, id
            limit 1
            """,
            (flow["id"], int(flow.get("flow_revision") or 1), source_step_id or None),
        ).fetchone()
        if canonical:
            return {
                "id": canonical["id"],
                "action": canonical["action"],
                "planner_agent_run_id": canonical["planner_agent_run_id"] or run["id"],
                "reason": canonical["reason"] or reason,
                "target_node_id": canonical["target_node_id"] or target_node_id,
                "reused_existing": canonical["id"] != decision_id,
            }
        return {
            "id": decision_id,
            "action": action,
            "planner_agent_run_id": run["id"],
            "reason": reason,
            "target_node_id": target_node_id,
            "reused_existing": False,
        }

    def _create_clarify_step(
        self,
        *,
        flow_id: str,
        source_step_id: str,
        attempt: dict[str, Any],
        validation: evidence_gate.EvidenceValidationResult,
        provider_mode: str,
        reason: str,
    ) -> dict[str, Any]:
        flow = dict(self._flow_by_id(flow_id))
        if source_step_id:
            self.conn.execute(
                "update flow_steps set status = 'completed', updated_at = ? where id = ?",
                (db.now_iso(), source_step_id),
            )
        decision = self._record_next_step_decision(
            flow=flow,
            action="clarify_evidence",
            report_label=validation.predicate.report_label,
            source_step_id=source_step_id,
            source_attempt_ids=[attempt["id"]],
            source_validation_ids=[validation.validation_id] if validation.validation_id else [],
            provider_mode=provider_mode,
            reason=reason,
            target_node_id=attempt["node_id"],
        )
        question = db.get_question(self.conn, attempt["question_id"])
        step_id = self._create_question_step(
            flow_id=flow_id,
            position=int(self.conn.execute("select count(*) from flow_steps where flow_id = ?", (flow_id,)).fetchone()[0]) + 1,
            graph_version=flow["graph_version"],
            question=question,
            review_record_id=attempt.get("review_record_id") or "",
            selection_reason={"reason": "clarify_unclear_evidence", "source_next_step_decision_id": decision["id"]},
            candidate_packet={},
            support_hint="刚才的答案或照片不够清楚。请用文字把关键步骤和最后答案补清楚，或重新拍一张清楚的纸面过程。",
            step_type="clarify_evidence",
            answer_input_mode="clarification",
        )
        self.conn.execute(
            """
            update daily_flows
            set status = 'reviewing',
                current_step_id = ?,
                flow_revision = flow_revision + 1,
                updated_at = ?
            where id = ?
            """,
            (step_id, db.now_iso(), flow_id),
        )
        return decision

    def _try_enqueue_recovery_for_blocked_flow(self, flow: dict[str, Any]) -> bool:
        row = self.conn.execute(
            """
            select *
            from background_jobs
            where flow_id = ?
              and job_type in ('answer_analysis','evaluation_update','planner_decision','teaching_generation')
              and status in ('blocked','dead_letter')
            order by updated_at desc, created_at desc, id desc
            limit 1
            """,
            (flow["id"],),
        ).fetchone()
        if not row:
            return False
        origin = dict(row)
        route = _route_for_v5_job_type(str(origin.get("job_type") or ""))
        if _provider_mode(route) == "not_configured":
            return False
        attempt_id = str(origin.get("attempt_id") or "")
        if not attempt_id:
            return False
        try:
            attempt = db.get_attempt(self.conn, attempt_id)
        except KeyError:
            return False
        if attempt.get("evidence_status") != "active":
            return False
        payload = db.json_load(origin.get("payload_json"), {})
        if int(payload.get("recovery_generation") or 0) >= 1:
            return False
        if self.conn.execute(
            """
            select count(*)
            from background_jobs
            where attempt_id = ?
              and status = 'succeeded'
              and created_at > ?
            """,
            (attempt_id, origin.get("created_at") or ""),
        ).fetchone()[0]:
            return False
        existing_recovery = self.conn.execute(
            """
            select id
            from background_jobs
            where attempt_id = ?
              and status in ('queued','claimed','running','retry')
              and idempotency_key like ?
            order by created_at desc, id desc
            limit 1
            """,
            (attempt_id, f"v5:{origin['job_type']}:recovery:{origin['id']}:%"),
        ).fetchone()
        if existing_recovery:
            return True
        payload.update({
            "payload_schema_version": job_queue.V5_JOB_PAYLOAD_SCHEMA_VERSION,
            "job_type": origin["job_type"],
            "legacy_session_id": attempt["session_id"],
            "flow_id": flow["id"],
            "flow_revision": int(flow.get("flow_revision") or 1) + 1,
            "flow_step_id": attempt.get("flow_step_id") or origin.get("flow_step_id") or "",
            "step_revision": int(origin.get("step_revision") or 1),
            "attempt_id": attempt_id,
            "attempt_version": int(attempt.get("attempt_version") or 1),
            "analysis_version": int(attempt.get("analysis_version") or 0),
            "graph_version": attempt.get("graph_version") or flow.get("graph_version") or "",
            "question_bank_version": attempt.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION,
            "question_id": attempt.get("question_id") or origin.get("question_id") or "",
            "review_record_id": attempt.get("review_record_id") or origin.get("review_record_id") or "",
            "provider_mode": _provider_mode(route),
            "source_job_ids": sorted(set((payload.get("source_job_ids") or []) + [origin["id"]])),
            "recovery_origin_job_id": origin["id"],
            "recovery_generation": int(payload.get("recovery_generation") or 0) + 1,
            "route_meta": {"source": "blocked_recovery", "origin_job_id": origin["id"], **route.audit_metadata()},
        })
        key = f"v5:{origin['job_type']}:recovery:{origin['id']}:{payload['recovery_generation']}"
        job_queue.JobQueue(self.conn).enqueue(origin["job_type"], key, payload, commit=False)
        if attempt.get("flow_step_id"):
            self.conn.execute(
                "update flow_steps set status = 'analyzing', updated_at = ? where id = ? and status in ('selected','displayed','analyzing','blocked')",
                (db.now_iso(), attempt["flow_step_id"]),
            )
        self.conn.execute(
            """
            update daily_flows
            set status = 'reviewing',
                current_step_id = coalesce(?, current_step_id),
                blocked_reason = '',
                flow_revision = flow_revision + 1,
                updated_at = ?
            where id = ?
            """,
            (attempt.get("flow_step_id"), db.now_iso(), flow["id"]),
        )
        return True

    def _block_flow(self, flow_id: str, reason: str) -> None:
        if not flow_id:
            return
        self.conn.execute(
            """
            update daily_flows
            set status = 'blocked',
                blocked_reason = ?,
                flow_revision = flow_revision + 1,
                updated_at = ?
            where id = ?
              and status not in ('completed','superseded')
            """,
            (reason[:500], db.now_iso(), flow_id),
        )

    def _ensure_daily_summary(
        self,
        flow: dict[str, Any],
        *,
        reason: str,
        target_flow_revision: int | None = None,
    ) -> str:
        summary_revision = int(target_flow_revision if target_flow_revision is not None else (flow.get("flow_revision") or 1))
        existing = self.conn.execute(
            """
            select id
            from daily_summaries
            where flow_id = ? and flow_revision = ? and summary_version = 1
            limit 1
            """,
            (flow["id"], summary_revision),
        ).fetchone()
        if existing:
            return existing["id"]
        steps = self._rows_for_flow_ids("flow_steps", [flow["id"]])
        attempts = self._attempts_for_step_ids([step["id"] for step in steps])
        validations = self._validations_for_attempt_ids([attempt["id"] for attempt in attempts])
        decisions = self._rows_for_flow_ids("next_step_decisions", [flow["id"]])
        jobs = self._rows_for_flow_ids("background_jobs", [flow["id"]])
        mastery_rows = [dict(row) for row in self.conn.execute(
            """
            select *
            from mastery_decisions
            where session_id = ?
            order by created_at, id
            """,
            (flow.get("legacy_session_id") or "",),
        ).fetchall()]
        job_refs_by_type: dict[str, list[dict[str, Any]]] = {}
        for job in jobs:
            if job.get("job_type") not in job_queue.V5_MODEL_JOB_TYPES:
                continue
            refs = db.json_load(job.get("result_refs_json"), {})
            job_refs_by_type.setdefault(str(job.get("job_type")), []).append({
                "job_id": job.get("id"),
                "status": job.get("status"),
                "attempt_id": job.get("attempt_id"),
                "provider_mode": job.get("provider_mode"),
                "result_refs": refs,
            })
        touched_node_ids = sorted({attempt["node_id"] for attempt in attempts if attempt.get("node_id")})
        label_counts: dict[str, int] = {}
        validation_by_attempt = {item["attempt_id"]: item for item in validations}
        for attempt in attempts:
            validation = validation_by_attempt.get(attempt["id"])
            if validation:
                predicate = db.json_load(validation.get("predicate_result_json"), {})
                label = str(predicate.get("report_label") or validation.get("gate_status") or "pending")
            elif attempt.get("grading_status") == "pending_review":
                label = "pending"
            else:
                label = "missing_lineage"
            label_counts[label] = label_counts.get(label, 0) + 1
        correct_count = sum(1 for attempt in attempts if attempt.get("result") == "correct")
        weak_count = sum(1 for attempt in attempts if attempt.get("result") in {"partial", "wrong"} or attempt.get("blocking_evidence"))
        pending_count = label_counts.get("pending", 0) + label_counts.get("blocked", 0)
        confirmed_count = label_counts.get("confirmed", 0)
        blocked_count = label_counts.get("blocked", 0)
        child_summary = {
            "title": "今天先到这里",
            "what_went_well": (
                f"今天有 {confirmed_count} 条作答证据已经确认。"
                if confirmed_count
                else "今天的作答已经保存。"
            ),
            "keep_working_on": (
                f"还有 {weak_count} 处思路、步骤或表达不够稳，下次先修这里。"
                if weak_count
                else "下一次继续把关键关系、步骤和检验写清楚。"
            ),
            "pending_note": (
                f"还有 {pending_count} 条证据需要等系统恢复或补充清楚后再判断。"
                if pending_count
                else ""
            ),
            "blocked_note": "其中有步骤暂时不能安全判断。" if blocked_count else "",
            "next_action": (
                "刚才卡住的地方已经保存；今天先到这里，下次会从这一步继续修。"
                if reason == "child_still_stuck_after_teaching"
                else "休息一下；下次会从最需要巩固的地方继续。"
            ),
            "labels": label_counts,
        }
        operator_summary = {
            "reason": reason,
            "flow_id": flow["id"],
            "flow_revision": summary_revision,
            "graph_nodes_touched": touched_node_ids,
            "step_count": len(steps),
            "attempt_count": len(attempts),
            "correct_count": correct_count,
            "weak_or_wrong_count": weak_count,
            "report_labels": label_counts,
            "steps": [
                {
                    "id": step["id"],
                    "step_type": step["step_type"],
                    "status": step["status"],
                    "node_id": step["node_id"],
                    "question_id": step["question_id"],
                    "selection_reason": db.json_load(step.get("selection_reason_json"), {}),
                }
                for step in steps
            ],
            "attempts": [
                {
                    "id": attempt["id"],
                    "node_id": attempt["node_id"],
                    "question_id": attempt["question_id"],
                    "result": attempt["result"],
                    "grading_status": attempt["grading_status"],
                    "analysis_status": attempt.get("analysis_status"),
                    "review_meta": db.json_load(attempt.get("review_meta_json"), {}) if "review_meta_json" in attempt else attempt.get("review_meta", {}),
                }
                for attempt in attempts
            ],
            "phase_lineage": {
                "jobs": job_refs_by_type,
                "answer_analysis_job_id": _first_job_ref(job_refs_by_type, "answer_analysis", "job_id"),
                "answer_analysis_agent_run_id": _first_job_ref(job_refs_by_type, "answer_analysis", "answer_analysis_agent_run_id"),
                "evaluation_job_id": _first_job_ref(job_refs_by_type, "evaluation_update", "job_id"),
                "evaluation_agent_run_id": _first_job_ref(job_refs_by_type, "evaluation_update", "evaluation_agent_run_id"),
                "planner_job_id": _first_job_ref(job_refs_by_type, "planner_decision", "job_id"),
                "planner_agent_run_id": _first_job_ref(job_refs_by_type, "planner_decision", "planner_agent_run_id"),
                "teaching_job_id": _first_job_ref(job_refs_by_type, "teaching_generation", "job_id"),
                "teaching_agent_run_id": _first_job_ref(job_refs_by_type, "teaching_generation", "teaching_agent_run_id"),
                "mastery_decision_ids": [row["id"] for row in mastery_rows],
                "next_step_decision_ids": [decision["id"] for decision in decisions],
                "provider_modes": sorted({str(job.get("provider_mode") or "") for job in jobs if job.get("provider_mode")}),
            },
        }
        summary_id = f"DS-{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            insert into daily_summaries(
              id, flow_id, flow_revision, summary_version, graph_version,
              touched_node_ids_json, question_bank_version, source_step_ids_json,
              source_attempt_ids_json, source_evidence_validation_ids_json,
              source_mastery_decision_ids_json, source_next_step_decision_ids_json,
              late_evidence_included_ids_json, late_evidence_excluded_ids_json,
              report_label_json, child_summary_json, operator_summary_json, created_at
            ) values (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', ?, ?, ?, ?)
            """,
            (
                summary_id,
                flow["id"],
                summary_revision,
                flow["graph_version"],
                db.json_dump(touched_node_ids),
                flow.get("question_bank_version") or question_bank.QUESTION_BANK_VERSION,
                db.json_dump([step["id"] for step in steps]),
                db.json_dump([attempt["id"] for attempt in attempts]),
                db.json_dump([item["id"] for item in validations]),
                db.json_dump([row["id"] for row in mastery_rows]),
                db.json_dump([decision["id"] for decision in decisions]),
                db.json_dump(label_counts),
                db.json_dump(child_summary),
                db.json_dump(operator_summary),
                db.now_iso(),
            ),
        )
        return summary_id

    def _latest_summary_for_flow(self, flow_id: str | None) -> dict[str, Any]:
        if not flow_id:
            return {}
        row = self.conn.execute(
            """
            select *
            from daily_summaries
            where flow_id = ?
            order by created_at desc, id desc
            limit 1
            """,
            (flow_id,),
        ).fetchone()
        if not row:
            return {}
        data = dict(row)
        data["child_summary"] = db.json_load(data.pop("child_summary_json"), {})
        data["operator_summary"] = db.json_load(data.pop("operator_summary_json"), {})
        data["report_label"] = db.json_load(data.pop("report_label_json"), {})
        return data


def _kind_label(step_type: str | None) -> str:
    return {
        "question": "小检测",
        "teaching_repair": "讲解",
        "worked_example": "例题",
        "micro_check": "小互动",
        "standard_check": "小检测",
        "variant_check": "变式小题",
        "clarify_evidence": "确认一下",
        "summary": "总结",
        "ready_for_new_knowledge": "新知识准备",
    }.get(str(step_type or ""), "学习")


def _first_job_ref(job_refs_by_type: dict[str, list[dict[str, Any]]], job_type: str, key: str) -> str:
    for item in job_refs_by_type.get(job_type, []):
        if key == "job_id" and item.get("job_id"):
            return str(item["job_id"])
        refs = item.get("result_refs") if isinstance(item.get("result_refs"), dict) else {}
        if refs.get(key):
            return str(refs[key])
    return ""


def _child_interaction_schema_with_accessible_choices(
    schema: dict[str, Any] | None,
    prompt: str,
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    projected = dict(schema)
    choices = [
        dict(choice)
        for choice in (schema.get("choices") or [])
        if isinstance(choice, dict)
    ]
    if str(schema.get("type") or "") not in {"single_choice", "multi_choice"}:
        projected["choices"] = choices
        return projected
    lines = [line.strip() for line in str(prompt or "").splitlines() if line.strip()]
    for choice in choices:
        choice_id = str(choice.get("id") or "").strip()
        label = str(choice.get("label") or "").strip()
        if not choice_id or label not in {choice_id, f"{choice_id}.", f"{choice_id}．"}:
            continue
        prefixes = (
            f"{choice_id}.", f"{choice_id}．", f"{choice_id}、",
            f"{choice_id})", f"{choice_id}）", f"{choice_id}:", f"{choice_id}：",
        )
        for line in lines:
            prefix = next((item for item in prefixes if line.startswith(item)), "")
            if not prefix:
                continue
            full_label = line[len(prefix):].strip()
            if full_label:
                choice["label"] = full_label
                break
    projected["choices"] = choices
    return projected


def _child_prompt_without_duplicate_choice_labels(
    prompt: str,
    interaction_schema: dict[str, Any] | None,
) -> str:
    if not interaction_schema or interaction_schema.get("type") not in {"single_choice", "multi_choice"}:
        return str(prompt or "")
    labels = [
        str(choice.get("label") or "").strip()
        for choice in (interaction_schema.get("choices") or [])
        if isinstance(choice, dict) and str(choice.get("label") or "").strip()
    ]
    if not labels:
        return str(prompt or "")
    kept: list[str] = []
    for line in str(prompt or "").splitlines():
        stripped = line.strip()
        duplicate_option_line = False
        for label in labels:
            if stripped == label:
                duplicate_option_line = True
                break
            if not stripped.endswith(label):
                continue
            prefix = stripped[: -len(label)].strip().rstrip(".．、:：)）")
            if prefix and len(prefix) <= 3 and prefix.replace(" ", "").isalnum():
                duplicate_option_line = True
                break
        if not duplicate_option_line:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    cleaned = "\n".join(kept).strip()
    return cleaned or str(prompt or "")


def _allowed_response_modes_for_step(step_type: str | None, package: dict[str, Any]) -> list[str]:
    raw_modes = package.get("allowed_response_modes")
    if isinstance(raw_modes, list):
        modes = [str(item) for item in raw_modes if item]
    else:
        answer_input_mode = str(package.get("answer_input_mode") or "text")
        if answer_input_mode == "none":
            modes = ["continue"]
        elif answer_input_mode == "clarification" or step_type == "clarify_evidence":
            modes = ["text", "photo", "text_photo", "clarification"]
        elif answer_input_mode == "photo":
            modes = ["photo"]
        elif answer_input_mode == "text_photo":
            modes = ["text", "photo", "text_photo"]
        elif answer_input_mode == "interaction":
            modes = ["interaction", "text"]
        else:
            modes = ["text"]
    interaction_schema = question_bank.normalize_question_interaction_schema(package.get("interaction_schema"))
    if interaction_schema and interaction_schema.get("type") != "short_text":
        modes.append("interaction")
    if bool(package.get("stuck_enabled", True)) and step_type in {"question", "micro_check", "clarify_evidence", "worked_example", "teaching_repair"}:
        modes.append("stuck")
    if not bool(package.get("upload_enabled", True)):
        modes = [mode for mode in modes if mode not in {"photo", "text_photo"}]
    deduped: list[str] = []
    for mode in modes:
        if mode not in deduped:
            deduped.append(mode)
    return deduped


def _child_safe_teaching_sections(sections: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    ordered_keys = ["essence", "core_model", "worked_example", "why_it_works", "next_micro_check"]
    iterable = [(key, sections[key]) for key in ordered_keys if key in sections]
    iterable.extend((key, value) for key, value in sections.items() if key not in ordered_keys)
    for key, value in iterable:
        projected_key: str | _ChildSafeAliasKey = str(key)
        if key == "core_model":
            projected_key = "core_model"
        if isinstance(value, dict):
            projected_value: dict[str, Any] = {}
            for child_key, child_value in value.items():
                if isinstance(child_value, list):
                    projected_value[str(child_key)] = [
                        _child_safe_text(item, "", limit=360)
                        for item in child_value
                        if str(item or "").strip()
                    ]
                else:
                    projected_value[str(child_key)] = _child_safe_text(child_value, "", limit=700)
            safe[projected_key] = projected_value
        elif isinstance(value, list):
            safe[projected_key] = [
                _child_safe_text(item, "", limit=360)
                for item in value
                if str(item or "").strip()
            ]
        else:
            safe[projected_key] = _child_safe_text(value, "", limit=700)
    return safe


def _child_safe_interaction_schema(schema: dict[str, Any]) -> dict[str, Any]:
    interaction_type = str(schema.get("type") or "short_text").strip()
    if interaction_type not in question_bank.QUESTION_INTERACTION_TYPES:
        interaction_type = "short_text"
    safe: dict[str, Any] = {
        "type": interaction_type,
        "title": _child_safe_text(schema.get("title") or "", "", limit=80),
        "allow_explanation": bool(schema.get("allow_explanation", True)),
        "requires_explanation": bool(
            schema.get("requires_explanation", schema.get("explanation_required", False))
        ),
        "explanation_label": _child_safe_text(schema.get("explanation_label") or "补充说明", "补充说明", limit=40),
        "answer_placeholder": _child_safe_text(schema.get("answer_placeholder") or "", "", limit=100),
        "placeholder": _child_safe_text(schema.get("placeholder") or "", "", limit=100),
    }
    if interaction_type == "fill_blank":
        fields = []
        for field in schema.get("fields") or []:
            if not isinstance(field, dict):
                continue
            field_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(field.get("id") or ""))[:40]
            if not field_id:
                continue
            fields.append({
                "id": field_id,
                "label": _child_safe_text(field.get("label") or field_id, field_id, limit=60),
                "placeholder": _child_safe_text(field.get("placeholder") or "", "", limit=80),
                "prefix": _child_safe_text(field.get("prefix") or "", "", limit=30),
                "suffix": _child_safe_text(field.get("suffix") or "", "", limit=30),
            })
        safe["fields"] = fields[:8]
    if interaction_type in {"single_choice", "multi_choice"}:
        choices = []
        for choice in schema.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            choice_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(choice.get("id") or ""))[:40]
            if not choice_id:
                continue
            choices.append({
                "id": choice_id,
                "label": _child_safe_text(choice.get("label") or choice_id, choice_id, limit=160),
            })
        safe["choices"] = choices[:8]
    if interaction_type == "formula_input":
        safe["formula_label"] = _child_safe_text(schema.get("formula_label") or "算式", "算式", limit=60)
        safe["placeholder"] = _child_safe_text(schema.get("placeholder") or "", "", limit=100)
    return safe


def child_teaching_step_dto(step: dict[str, Any]) -> dict[str, Any]:
    sections = step.get("teaching_sections") if isinstance(step.get("teaching_sections"), dict) else {}
    try:
        prompt_projection = child_prompt.project_prompt_only(
            step.get("prompt") or "先看讲解，再做小检查。",
            allow_legacy=True,
            limit=2000,
        )
    except child_prompt.ChildPromptContractError as exc:
        raise ChildSafeRuntimeError("当前步骤还没有准备好，请稍后再试。") from exc
    dto = {
        "step_handle": _child_safe_text(step.get("step_handle") or "", "", limit=80),
        "position": int(step.get("position") or 0),
        "kind_label": _kind_label(step.get("step_type") or step.get("kind_label") or "teaching_repair"),
        "topic_label": _child_safe_text(step.get("topic_label") or "当前步骤", "当前步骤", limit=80),
        "prompt_format": prompt_projection["prompt_format"],
        "prompt": prompt_projection["prompt"],
        "prompt_segments": prompt_projection["prompt_segments"],
        "child_surface_projection_sha256": prompt_projection["projection_sha256"],
        "answer_input_mode": "none",
        "allowed_response_modes": [
            mode for mode in (step.get("allowed_response_modes") or ["continue", "stuck"])
            if mode in {"continue", "stuck", "cannot_provide"}
        ],
        "upload_enabled": False,
        "stuck_enabled": bool(step.get("stuck_enabled", True)),
        "state": _child_safe_text(step.get("status") or step.get("state") or "", "", limit=40),
        "support": {
            "hint": _child_safe_text((step.get("support") or {}).get("hint") if isinstance(step.get("support"), dict) else "", "", limit=180),
            "continue_label": _child_safe_text((step.get("support") or {}).get("continue_label") if isinstance(step.get("support"), dict) else "", "", limit=40),
            "stuck_label": _child_safe_text((step.get("support") or {}).get("stuck_label") if isinstance(step.get("support"), dict) else "", "", limit=40),
        },
        "teaching_sections": _child_safe_teaching_sections(sections),
    }
    feedback = step.get("assessment_feedback") if isinstance(step.get("assessment_feedback"), dict) else {}
    if feedback:
        dto["assessment_feedback"] = {
            "score_label": _child_safe_text(feedback.get("score_label") or "", "", limit=20),
            "reference_answer": _child_safe_text(feedback.get("reference_answer") or "", "", limit=700),
            "answer_gap": _child_safe_text(feedback.get("answer_gap") or "", "", limit=700),
            "improvement_direction": [
                _child_safe_text(item, "", limit=260)
                for item in (feedback.get("improvement_direction") or [])
                if str(item or "").strip()
            ][:6],
            "expression_judgment": _child_safe_text(feedback.get("expression_judgment") or "", "", limit=500),
        }
    _assert_child_safe_projection(dto)
    return dto


def normalize_new_knowledge_transition(
    *,
    previous_phase: str,
    requested_action: str,
    candidate_kind: str,
    audit: dict[str, Any] | None = None,
) -> dict[str, str]:
    audit = audit if isinstance(audit, dict) else {}
    action = str(requested_action or "")
    kind = str(candidate_kind or "")
    if previous_phase == "micro_check" and action in {"near_transfer_retest", "stretch"}:
        audit["normalization"] = "coerced_early_variant_to_standard"
        audit["requested_action"] = action
        return {
            "action": "same_structure_retest",
            "step_type": "standard_check",
            "new_knowledge_phase": "standard",
        }
    if previous_phase in {"micro_check", "standard"} and action == "same_structure_retest":
        return {
            "action": action,
            "step_type": "standard_check",
            "new_knowledge_phase": "standard",
        }
    if previous_phase == "standard" and action in {"near_transfer_retest", "stretch"}:
        return {
            "action": action,
            "step_type": "variant_check",
            "new_knowledge_phase": "variant",
        }
    if kind in {"variant", "near_transfer", "integrated_transfer"} and previous_phase != "standard":
        audit["normalization"] = "coerced_candidate_kind_to_standard"
        return {
            "action": "same_structure_retest",
            "step_type": "standard_check",
            "new_knowledge_phase": "standard",
        }
    return {
        "action": action,
        "step_type": "question",
        "new_knowledge_phase": "",
    }


def _child_safe_text(value: Any, fallback: str, *, limit: int = 600) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    for term in CHILD_FORBIDDEN_TERMS:
        text = text.replace(term, "")
    text = " ".join(text.split())
    return (text or fallback)[:limit]


def _assert_child_safe_projection(value: Any) -> None:
    lowered = str(value).lower()
    for term in CHILD_FORBIDDEN_TERMS:
        if term.lower() in lowered:
            raise ChildSafeRuntimeError("当前步骤还没有准备好，请稍后再试。")


def _provider_mode(route: model_router.ModelRoute) -> str:
    if not route.enabled:
        return "not_configured"
    if route.provider in {"recorded_model", "mock_only"}:
        return route.provider
    return "live_model"


def _route_for_v5_job_type(job_type: str) -> model_router.ModelRoute:
    if job_type == "evaluation_update":
        return model_router.evaluation_route()
    if job_type == "planner_decision":
        return model_router.planner_route()
    if job_type == "teaching_generation":
        return model_router.teaching_route()
    return model_router.answer_analysis_route()


def _question_structure_repetition_fingerprint(question: dict[str, Any]) -> str:
    metadata = question.get("metadata") if isinstance(question.get("metadata"), dict) else {}
    source = metadata.get("source") if isinstance(metadata.get("source"), dict) else {}
    node_alignment = (
        metadata.get("node_alignment")
        if isinstance(metadata.get("node_alignment"), dict)
        else {}
    )
    quality = metadata.get("quality") if isinstance(metadata.get("quality"), dict) else {}
    core_stem_id = str(
        question.get("core_stem_id")
        or source.get("core_stem_id")
        or node_alignment.get("core_stem_id")
        or quality.get("core_stem_id")
        or ""
    ).strip()
    if core_stem_id:
        return f"core_stem:{core_stem_id}"
    math_core_signature = str(
        question.get("math_core_signature")
        or source.get("math_core_signature")
        or node_alignment.get("math_core_signature")
        or quality.get("math_core_signature")
        or ""
    ).strip()
    if math_core_signature:
        return f"math_core:{math_core_signature}"
    problem_family_id = str(
        question.get("problem_family_id")
        or source.get("problem_family_id")
        or node_alignment.get("problem_family_id")
        or quality.get("problem_family_id")
        or ""
    ).strip()
    return f"problem_family:{problem_family_id}" if problem_family_id else ""


def _iso_add_seconds(value: str, seconds: int) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.fromisoformat(db.now_iso())
    return (parsed + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_answer_photo_data_url(data_url: str) -> tuple[str, bytes]:
    match = re.fullmatch(r"data:([^;,]+);base64,(.*)", data_url, flags=re.DOTALL)
    if not match:
        raise ChildSafeRuntimeError("照片格式不对，请重新上传。", status=400, child_action="重新上传")
    content_type = match.group(1).lower()
    if content_type not in ALLOWED_ANSWER_PHOTO_TYPES:
        raise ChildSafeRuntimeError("只支持常见图片格式，请重新上传。", status=400, child_action="重新上传")
    encoded = match.group(2)
    max_encoded_size = ((MAX_ANSWER_PHOTO_BYTES + 2) // 3) * 4 + 1024
    if len(encoded) > max_encoded_size:
        raise ChildSafeRuntimeError("照片太大了，请重新拍一张更清楚的小图。", status=400, child_action="重新上传")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ChildSafeRuntimeError("照片格式不对，请重新上传。", status=400, child_action="重新上传") from exc
    if not data or len(data) > MAX_ANSWER_PHOTO_BYTES or not _looks_like_allowed_image(content_type, data):
        raise ChildSafeRuntimeError("照片读取失败，请重新上传。", status=400, child_action="重新上传")
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
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "answer"
    stem = stem[:80]
    return f"{attempt_id}-{uuid.uuid4().hex[:8]}-{stem}{ALLOWED_ANSWER_PHOTO_TYPES[content_type]}"
