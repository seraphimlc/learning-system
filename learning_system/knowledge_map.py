from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import daily_runtime, db
from .graph_runtime import GraphRuntimeService
from .knowledge_view_config import KnowledgeViewConfig


VIEW_RECEIPT_KEY = "knowledge_views_active.v1"
VIEW_RECEIPT_SCHEMA = "knowledge-views-activation.v1"
HANDLE_SECRET_KEY = "knowledge_views_handle_secret.v1"
ASSESSMENT_RECEIPT_KEY = "answer_assessment_active.v5.1"
ASSESSMENT_RECEIPT_SCHEMA = "answer-assessment-activation.v1"
HANDLE_POLICY_VERSION = "kv51-h1"
PROJECTION_SCHEMA_VERSION = "5.1-knowledge-views"
CHILD_PROJECTION_POLICY_VERSION = "child-map-only-v2"
CHILD_HIDDEN_MODULE_IDS = {"Z_LEARNING_PROCESS"}
CHILD_VISIBLE_MODULE_ORDER = [
    "A_FOUNDATION",
    "E_RATIONAL_NUMBERS",
    "B_FRACTION_RATIO",
    "C_ALGEBRA_BRIDGE",
    "F_EXPRESSIONS",
    "G_LINEAR_EQUATION",
    "D_WORD_MODELS",
    "H_GEOMETRY_INTRO",
]
ALLOWED_ACTIONS = {"diagnostic", "learn", "review", "challenge"}
NONTERMINAL_INTENT_STATUSES = {"pending", "waiting_for_safe_boundary"}
OVERVIEW_ANCHOR_PRIORITIES = {
    "M-PRE-NUMBER-SENSE": 1,
    "M-PRE-QUANTITY-RELATION": 2,
    "M-G7-RATIONAL-ADD-SUB": 3,
    "M-G7-COMBINE-LIKE": 4,
    "M-G7-EQ-SOLVE": 5,
    "M-G7-EQ-WORD": 6,
}


class KnowledgeMapError(ValueError):
    def __init__(self, message: str, *, status: int, state: str) -> None:
        super().__init__(message)
        self.status = status
        self.state = state

    def child_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "state": self.state,
            "message": str(self),
            "action_label": "返回当前学习",
        }


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _secret_bytes(value: str) -> bytes:
    raw = str(value or "").strip()
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    return raw.encode("utf-8")


def _opaque_handle(secret: bytes, *, domain: str, graph_lineage: str, canonical_id: str) -> str:
    prefixes = {"node": "kn51n", "module": "kn51m", "lane": "kn51l"}
    prefix = prefixes[domain]
    message = "\x1f".join((HANDLE_POLICY_VERSION, domain, graph_lineage, canonical_id)).encode("utf-8")
    digest = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{prefix}.{digest}"


def _row_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return dict(row) if isinstance(row, sqlite3.Row) else dict(row)


def _intent_digest(*, node_id: str, action: str) -> str:
    return _canonical_sha256({"node_id": node_id, "action": action})


def _node_module_id(node: dict[str, Any]) -> str:
    taxonomy = node.get("taxonomy") if isinstance(node.get("taxonomy"), dict) else {}
    return str(taxonomy.get("module_id") or "")


def _child_visible_module_ids(config: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    configured = [str(module_id) for module_id in config["root"]["module_order"]]
    configured_set = set(configured)
    ordered = [
        module_id
        for module_id in CHILD_VISIBLE_MODULE_ORDER
        if module_id in configured_set and module_id in snapshot["modules"]
    ]
    ordered.extend(
        module_id
        for module_id in configured
        if (
            module_id not in ordered
            and module_id not in CHILD_HIDDEN_MODULE_IDS
            and module_id in snapshot["modules"]
        )
    )
    return ordered


def _child_projection_version(config: KnowledgeViewConfig) -> str:
    return (
        f"kv51:{CHILD_PROJECTION_POLICY_VERSION}:"
        f"{config.config_version}:{config.canonical_sha256()[:16]}"
    )


def _sealed_receipt_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    claimed = str(value.get("receipt_digest_sha256") or "")
    body = {key: item for key, item in value.items() if key != "receipt_digest_sha256"}
    return len(claimed) == 64 and hmac.compare_digest(claimed, _canonical_sha256(body))


def _answer_contract_question_digest(question: dict[str, Any]) -> str:
    return _canonical_sha256(
        {
            "question_id": question.get("id"),
            "item_version": question.get("item_version"),
            "node_id": question.get("node_id"),
            "kind": question.get("kind"),
            "prompt": question.get("prompt"),
            "answer_format": question.get("answer_format"),
            "expected_answer": question.get("expected_answer"),
            "solution_steps": question.get("solution_steps") or [],
            "reference_evidence": question.get("reference_evidence"),
        }
    )


def _begin_write(conn: sqlite3.Connection, label: str) -> tuple[str, bool]:
    if conn.in_transaction:
        savepoint = f"kv51_{label}_{uuid.uuid4().hex[:10]}"
        conn.execute(f"savepoint {savepoint}")
        return savepoint, True
    conn.execute("begin immediate")
    return "", False


def _finish_write(conn: sqlite3.Connection, savepoint: str, nested: bool) -> None:
    if nested:
        conn.execute(f"release savepoint {savepoint}")
    else:
        conn.commit()


def _rollback_write(conn: sqlite3.Connection, savepoint: str, nested: bool) -> None:
    if nested:
        conn.execute(f"rollback to savepoint {savepoint}")
        conn.execute(f"release savepoint {savepoint}")
    else:
        conn.rollback()


def _with_lock_retry(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    last_error: sqlite3.OperationalError | None = None
    for attempt in range(4):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).casefold() or attempt == 3:
                raise
            last_error = exc
            time.sleep(0.03 * (attempt + 1))
    raise last_error or sqlite3.OperationalError("target-intent write failed")


def create_target_intent(
    conn: sqlite3.Connection,
    *,
    child_key: str,
    graph_version: str,
    node_id: str,
    action: str,
    client_idempotency_key: str,
    source_flow_id: str | None = None,
    source_flow_revision: int | None = None,
    source_step_id: str | None = None,
    status: str = "pending",
    reason: str = "",
) -> dict[str, Any]:
    child_key = str(child_key or "").strip()
    graph_version = str(graph_version or "").strip()
    node_id = str(node_id or "").strip()
    action = str(action or "").strip()
    key = str(client_idempotency_key or "").strip()
    if not child_key or not graph_version or not node_id or not key:
        raise ValueError("target intent requires child, graph, node, and idempotency key")
    if action not in ALLOWED_ACTIONS:
        raise ValueError("unsupported target action")
    if status not in NONTERMINAL_INTENT_STATUSES:
        raise ValueError("new target intent must be nonterminal")
    payload_digest = _intent_digest(node_id=node_id, action=action)

    def operation() -> dict[str, Any]:
        savepoint, nested = _begin_write(conn, "create_intent")
        try:
            existing = conn.execute(
                """
                select * from learning_target_intents
                where child_key = ? and graph_version = ? and client_idempotency_key = ?
                """,
                (child_key, graph_version, key),
            ).fetchone()
            if existing:
                if (
                    existing["payload_digest_sha256"] != payload_digest
                    or existing["node_id"] != node_id
                    or existing["action"] != action
                ):
                    raise ValueError("client idempotency key was reused for another target")
                _finish_write(conn, savepoint, nested)
                return dict(existing)
            if conn.execute("select 1 from graph_nodes where id = ?", (node_id,)).fetchone() is None:
                raise ValueError("target node is not in the active graph")
            intent_id = f"KTI-{uuid.uuid4().hex[:20]}"
            now = db.now_iso()
            conn.execute(
                """
                insert into learning_target_intents(
                  id, child_key, graph_version, node_id, action, status,
                  source_flow_id, source_flow_revision, source_step_id,
                  client_idempotency_key, payload_digest_sha256,
                  reason, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent_id,
                    child_key,
                    graph_version,
                    node_id,
                    action,
                    status,
                    source_flow_id,
                    source_flow_revision,
                    source_step_id,
                    key,
                    payload_digest,
                    str(reason or ""),
                    now,
                    now,
                ),
            )
            row = conn.execute("select * from learning_target_intents where id = ?", (intent_id,)).fetchone()
            _finish_write(conn, savepoint, nested)
            return dict(row)
        except Exception:
            _rollback_write(conn, savepoint, nested)
            raise

    return _with_lock_retry(operation)


def newest_pending_intent(
    conn: sqlite3.Connection,
    *,
    child_key: str,
    graph_version: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select * from learning_target_intents
        where child_key = ? and graph_version = ?
          and status in ('pending','waiting_for_safe_boundary')
        order by created_at desc, id desc
        limit 1
        """,
        (child_key, graph_version),
    ).fetchone()
    return dict(row) if row else None


def apply_intent_at_safe_boundary(
    conn: sqlite3.Connection,
    *,
    intent_id: str,
    applied_flow_id: str,
    applied_step_id: str,
) -> dict[str, Any]:
    def operation() -> dict[str, Any]:
        savepoint, nested = _begin_write(conn, "apply_intent")
        try:
            row = conn.execute(
                "select * from learning_target_intents where id = ?",
                (intent_id,),
            ).fetchone()
            if not row:
                raise LookupError("target intent does not exist")
            if row["status"] == "applied":
                if row["applied_flow_id"] != applied_flow_id or row["applied_step_id"] != applied_step_id:
                    raise ValueError("target intent is already applied at another boundary")
                _finish_write(conn, savepoint, nested)
                return dict(row)
            if row["status"] not in NONTERMINAL_INTENT_STATUSES:
                raise ValueError("target intent is not applicable")
            flow = conn.execute("select * from daily_flows where id = ?", (applied_flow_id,)).fetchone()
            step = conn.execute("select * from flow_steps where id = ?", (applied_step_id,)).fetchone()
            if not flow or not step or step["flow_id"] != applied_flow_id:
                raise ValueError("safe boundary flow or step lineage is invalid")
            if step["node_id"] != row["node_id"] or flow["graph_version"] != row["graph_version"]:
                raise ValueError("safe boundary does not match target intent lineage")
            now = db.now_iso()
            conn.execute(
                """
                update learning_target_intents
                set status = 'applied', applied_flow_id = ?, applied_step_id = ?,
                    reason = '', updated_at = ?
                where id = ? and status in ('pending','waiting_for_safe_boundary')
                """,
                (applied_flow_id, applied_step_id, now, intent_id),
            )
            applied = conn.execute(
                "select * from learning_target_intents where id = ?",
                (intent_id,),
            ).fetchone()
            _finish_write(conn, savepoint, nested)
            return dict(applied)
        except Exception:
            _rollback_write(conn, savepoint, nested)
            raise

    return _with_lock_retry(operation)


class KnowledgeMapService:
    def __init__(self, conn: sqlite3.Connection, *, project_root: Path | str | None = None) -> None:
        self.conn = conn
        self.project_root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]

    def _require_policy(self) -> None:
        if not daily_runtime.knowledge_map_home_policy_requested():
            raise KnowledgeMapError(
                "知识首页暂时没有打开，请继续当前学习。",
                status=404,
                state="unavailable",
            )
        if not daily_runtime.answer_assessment_v51_enabled():
            raise KnowledgeMapError(
                "答案评估还没有准备好，暂时不能从知识首页开始新任务。",
                status=409,
                state="assessment_unavailable",
            )

    def _assessment_authority(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        ledger_rows = self.conn.execute(
            "select * from question_bank_version_ledger where status = 'active' order by id"
        ).fetchall()
        receipt_row = self.conn.execute(
            "select value from system_meta where key = ?",
            (ASSESSMENT_RECEIPT_KEY,),
        ).fetchone()
        if len(ledger_rows) != 1 or not receipt_row:
            raise KnowledgeMapError(
                "答案评估还没有完成数据库审计，暂时不能从知识首页开始新任务。",
                status=409,
                state="assessment_unavailable",
            )
        ledger = dict(ledger_rows[0])
        receipt = db.json_load(receipt_row["value"], {})
        graph_lineage = str(snapshot["graph_lineage"])
        bank_version = str(ledger.get("question_bank_version") or "")
        if (
            not _sealed_receipt_valid(receipt)
            or receipt.get("schema_version") != ASSESSMENT_RECEIPT_SCHEMA
            or receipt.get("status") != "active"
            or receipt.get("graph_lineage") != graph_lineage
            or receipt.get("question_bank_ledger_id") != ledger.get("id")
            or receipt.get("question_bank_version") != bank_version
            or ledger.get("graph_version") != graph_lineage
            or int(ledger.get("item_count") or 0) <= 0
        ):
            raise KnowledgeMapError(
                "答案评估激活凭据已经变化，请刷新后再试。",
                status=409,
                state="assessment_unavailable",
            )
        if receipt.get("activation_mode") == "lightweight_local_contracts_v1":
            return self._lightweight_assessment_authority(
                snapshot=snapshot,
                ledger=ledger,
                receipt=receipt,
            )
        rows = self.conn.execute(
            """
            select ac.id as contract_id, ac.stable_contract_id,
                   ac.question_id, ac.item_version, ac.contract_version,
                   ac.contract_digest_sha256, ac.question_digest_sha256,
                   ac.graph_version, ac.question_bank_version,
                   ac.reference_solution_json, ac.score_points_json,
                   ac.generator_run_id, ac.review_record_id, ac.review_run_id,
                   ac.design_receipt_json, ac.design_receipt_sha256,
                   ac.review_receipt_json, ac.review_receipt_sha256,
                   qi.node_id, qi.raw_json, qi.source_type,
                   qrr.candidate_sha256, qrr.review_status,
                   qrr.active_eligible, qrr.reviewer_run_id as question_reviewer_run_id,
                   qr.agent_key as question_reviewer_agent_key,
                   qr.phase as question_reviewer_phase,
                   qr.status as question_reviewer_status,
                   qr.model_provider as question_reviewer_provider,
                   qr.model_name as question_reviewer_model,
                   qr.model_alias as question_reviewer_alias,
                   qr.input_refs_json as question_reviewer_input_refs_json,
                   qr.output_json as question_reviewer_output_json,
                   dr.agent_key as designer_agent_key,
                   dr.phase as designer_phase,
                   dr.status as designer_status,
                   dr.model_provider as designer_provider,
                   dr.model_name as designer_model,
                   dr.model_alias as designer_alias,
                   dr.output_json as designer_output_json,
                   dr.output_digest_sha256 as designer_output_digest,
                   rr.agent_key as contract_reviewer_agent_key,
                   rr.phase as contract_reviewer_phase,
                   rr.status as contract_reviewer_status,
                   rr.model_provider as contract_reviewer_provider,
                   rr.model_name as contract_reviewer_model,
                   rr.model_alias as contract_reviewer_alias,
                   rr.output_json as contract_reviewer_output_json,
                   rr.output_digest_sha256 as contract_reviewer_output_digest
            from answer_contracts ac
            join question_items qi
              on qi.id = ac.question_id and qi.item_version = ac.item_version
            join question_review_records qrr on qrr.id = ac.review_record_id
            join agent_runs qr on qr.id = qrr.reviewer_run_id
            join agent_runs dr on dr.id = ac.generator_run_id
            join agent_runs rr on rr.id = ac.review_run_id
            where ac.status = 'active'
              and ac.graph_version = ?
              and ac.question_bank_version = ?
              and qi.item_version = ?
            order by ac.question_id
            """,
            (graph_lineage, bank_version, bank_version),
        ).fetchall()
        if len(rows) != int(ledger["item_count"]):
            raise KnowledgeMapError(
                "答案评估激活集合不完整，请继续当前学习。",
                status=409,
                state="assessment_unavailable",
            )
        assets: list[dict[str, Any]] = []
        commitments: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            candidate = db.json_load(item["raw_json"], {})
            question_digest = _answer_contract_question_digest(candidate)
            candidate_digest = db._digest_json(candidate)
            question_input = db.json_load(item["question_reviewer_input_refs_json"], {})
            question_output = db.json_load(item["question_reviewer_output_json"], {})
            design_output = db.json_load(item["designer_output_json"], {})
            review_output = db.json_load(item["contract_reviewer_output_json"], {})
            design_receipt = db.json_load(item["design_receipt_json"], {})
            review_receipt = db.json_load(item["review_receipt_json"], {})
            exact_lineage = not any(
                (
                    not isinstance(candidate, dict),
                    item["item_version"] != bank_version,
                    item["graph_version"] != graph_lineage,
                    item["question_bank_version"] != bank_version,
                    item["question_digest_sha256"] != question_digest,
                    item["candidate_sha256"] != candidate_digest,
                    item["review_status"] != "approved",
                    int(item["active_eligible"] or 0) != 1,
                    item["question_reviewer_agent_key"] != "question_reviewer_agent",
                    item["question_reviewer_phase"] != "question_quality_review",
                    item["question_reviewer_status"] != "accepted",
                    item["question_reviewer_provider"] != "openai",
                    item["question_reviewer_model"] != "gpt-5.5",
                    item["question_reviewer_alias"] != "gpt-5.5",
                    question_input.get("question_id") != item["question_id"],
                    question_input.get("candidate_sha256") != candidate_digest,
                    question_output.get("review_status") != "approved",
                    question_output.get("active_eligible") is not True,
                    item["designer_agent_key"] != "answer_contract_designer_agent",
                    item["designer_phase"] != "answer_contract_design_v2",
                    item["designer_status"] != "accepted",
                    item["designer_provider"] != "openai",
                    item["designer_model"] != "gpt-5.5",
                    item["designer_alias"] != "gpt-5.5",
                    item["contract_reviewer_agent_key"]
                    != "answer_contract_reviewer_agent",
                    item["contract_reviewer_phase"] != "answer_contract_review_v2",
                    item["contract_reviewer_status"] != "accepted",
                    item["contract_reviewer_provider"] != "openai",
                    item["contract_reviewer_model"] != "gpt-5.5",
                    item["contract_reviewer_alias"] != "gpt-5.5",
                    item["designer_output_digest"] != db._digest_json(design_output),
                    item["contract_reviewer_output_digest"]
                    != db._digest_json(review_output),
                    not _sealed_receipt_valid(design_receipt),
                    not _sealed_receipt_valid(review_receipt),
                    design_receipt.get("agent_run_id") != item["generator_run_id"],
                    design_receipt.get("output_digest_sha256")
                    != item["designer_output_digest"],
                    design_receipt.get("exact_live_lineage") is not True,
                    design_receipt.get("receipt_digest_sha256")
                    != item["design_receipt_sha256"],
                    review_receipt.get("agent_run_id") != item["review_run_id"],
                    review_receipt.get("contract_digest_sha256")
                    != item["contract_digest_sha256"],
                    review_receipt.get("output_digest_sha256")
                    != item["contract_reviewer_output_digest"],
                    review_receipt.get("exact_live_lineage") is not True,
                    review_receipt.get("receipt_digest_sha256")
                    != item["review_receipt_sha256"],
                )
            )
            if not exact_lineage:
                raise KnowledgeMapError(
                    "答案评估的题目或合同审查凭据不一致，请继续当前学习。",
                    status=409,
                    state="assessment_unavailable",
                )
            commitment = {
                "question_id": item["question_id"],
                "item_version": item["item_version"],
                "node_id": item["node_id"],
                "question_digest_sha256": question_digest,
                "review_record_id": item["review_record_id"],
                "candidate_sha256": item["candidate_sha256"],
                "contract_id": item["contract_id"],
                "contract_version": int(item["contract_version"]),
                "contract_digest_sha256": item["contract_digest_sha256"],
                "generator_run_id": item["generator_run_id"],
                "review_run_id": item["review_run_id"],
                "design_receipt_sha256": item["design_receipt_sha256"],
                "review_receipt_sha256": item["review_receipt_sha256"],
            }
            commitments.append(commitment)
            question_row = self.conn.execute(
                "select * from question_items where id = ? and item_version = ?",
                (item["question_id"], item["item_version"]),
            ).fetchone()
            assets.append(
                {
                    **commitment,
                    "question": db.row_to_question(question_row),
                    "contract": {
                        "id": item["contract_id"],
                        "stable_contract_id": item["stable_contract_id"],
                        "question_id": item["question_id"],
                        "item_version": item["item_version"],
                        "contract_version": int(item["contract_version"]),
                        "contract_digest_sha256": item["contract_digest_sha256"],
                        "graph_version": item["graph_version"],
                        "question_bank_version": item["question_bank_version"],
                        "reference_solution": db.json_load(
                            item["reference_solution_json"], {}
                        ),
                        "score_points": db.json_load(item["score_points_json"], []),
                        "review_record_id": item["review_record_id"],
                        "review_run_id": item["review_run_id"],
                        "status": "active",
                    },
                }
            )
        commitment_digest = _canonical_sha256(commitments)
        if (
            int(receipt.get("active_contract_count") or 0) != len(commitments)
            or receipt.get("contract_set_digest_sha256") != commitment_digest
            or int(ledger.get("node_count") or 0)
            not in {0, len({item["node_id"] for item in commitments})}
        ):
            raise KnowledgeMapError(
                "答案评估激活集合摘要不一致，请继续当前学习。",
                status=409,
                state="assessment_unavailable",
            )
        assets_by_node: dict[str, list[dict[str, Any]]] = {}
        for asset in assets:
            assets_by_node.setdefault(str(asset["node_id"]), []).append(asset)
        return {
            "ledger": ledger,
            "receipt": receipt,
            "assets": assets,
            "assets_by_node": assets_by_node,
        }

    def _lightweight_assessment_authority(
        self,
        *,
        snapshot: dict[str, Any],
        ledger: dict[str, Any],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        graph_lineage = str(snapshot["graph_lineage"])
        bank_version = str(ledger.get("question_bank_version") or "")
        rows = self.conn.execute(
            """
            select ac.id as contract_id, ac.stable_contract_id,
                   ac.question_id, ac.item_version, ac.contract_version,
                   ac.contract_digest_sha256, ac.question_digest_sha256,
                   ac.graph_version, ac.question_bank_version,
                   ac.reference_solution_json, ac.score_points_json,
                   ac.review_record_id, qi.node_id, qi.raw_json,
                   qrr.candidate_sha256, qrr.review_status, qrr.active_eligible
            from answer_contracts ac
            join question_items qi
              on qi.id = ac.question_id and qi.item_version = ac.item_version
            join question_review_records qrr on qrr.id = ac.review_record_id
            where ac.status = 'active'
              and ac.graph_version = ?
              and ac.question_bank_version = ?
              and qi.item_version = ?
            order by ac.question_id
            """,
            (graph_lineage, bank_version, bank_version),
        ).fetchall()
        if len(rows) != int(ledger["item_count"]):
            raise KnowledgeMapError(
                "答案评估激活集合不完整，请继续当前学习。",
                status=409,
                state="assessment_unavailable",
            )
        assets: list[dict[str, Any]] = []
        commitments: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            question_row = self.conn.execute(
                "select * from question_items where id = ? and item_version = ?",
                (item["question_id"], item["item_version"]),
            ).fetchone()
            if not question_row:
                raise KnowledgeMapError(
                    "答案评估题目凭据缺失，请继续当前学习。",
                    status=409,
                    state="assessment_unavailable",
                )
            question = db.row_to_question(question_row)
            question_digest = _answer_contract_question_digest(question)
            candidate_digest = db._digest_json(db.json_load(item["raw_json"], {}))
            if (
                item["item_version"] != bank_version
                or item["graph_version"] != graph_lineage
                or item["question_bank_version"] != bank_version
                or item["question_digest_sha256"] != question_digest
                or item["candidate_sha256"] != candidate_digest
                or item["review_status"] != "approved"
                or int(item["active_eligible"] or 0) != 1
            ):
                raise KnowledgeMapError(
                    "答案评估的题目或合同凭据不一致，请继续当前学习。",
                    status=409,
                    state="assessment_unavailable",
                )
            commitment = {
                "question_id": item["question_id"],
                "item_version": item["item_version"],
                "node_id": item["node_id"],
                "question_digest_sha256": question_digest,
                "review_record_id": item["review_record_id"],
                "candidate_sha256": item["candidate_sha256"],
                "contract_id": item["contract_id"],
                "contract_version": int(item["contract_version"]),
                "contract_digest_sha256": item["contract_digest_sha256"],
            }
            commitments.append(commitment)
            assets.append(
                {
                    **commitment,
                    "question": question,
                    "contract": {
                        "id": item["contract_id"],
                        "stable_contract_id": item["stable_contract_id"],
                        "question_id": item["question_id"],
                        "item_version": item["item_version"],
                        "contract_version": int(item["contract_version"]),
                        "contract_digest_sha256": item["contract_digest_sha256"],
                        "graph_version": item["graph_version"],
                        "question_bank_version": item["question_bank_version"],
                        "reference_solution": db.json_load(
                            item["reference_solution_json"], {}
                        ),
                        "score_points": db.json_load(item["score_points_json"], []),
                        "review_record_id": item["review_record_id"],
                        "review_run_id": "",
                        "status": "active",
                    },
                }
            )
        commitment_digest = _canonical_sha256(commitments)
        if (
            int(receipt.get("active_contract_count") or 0) != len(commitments)
            or receipt.get("contract_set_digest_sha256") != commitment_digest
            or int(ledger.get("node_count") or 0)
            not in {0, len({item["node_id"] for item in commitments})}
        ):
            raise KnowledgeMapError(
                "答案评估激活集合摘要不一致，请继续当前学习。",
                status=409,
                state="assessment_unavailable",
            )
        assets_by_node: dict[str, list[dict[str, Any]]] = {}
        for asset in assets:
            assets_by_node.setdefault(str(asset["node_id"]), []).append(asset)
        return {
            "ledger": ledger,
            "receipt": receipt,
            "assets": assets,
            "assets_by_node": assets_by_node,
        }

    def _runtime_authority(self) -> dict[str, Any]:
        self._require_policy()
        snapshot = GraphRuntimeService(project_root=self.project_root).graph_snapshot()
        graph_ref_row = self.conn.execute(
            "select value from system_meta where key = 'graph_ref'"
        ).fetchone()
        graph_ref = db.json_load(graph_ref_row["value"], {}) if graph_ref_row else {}
        if not isinstance(graph_ref, dict) or graph_ref.get("lineage") != snapshot["graph_lineage"]:
            raise KnowledgeMapError(
                "知识关系刚刚更新，请刷新后再试。",
                status=409,
                state="stale",
            )
        receipt_row = self.conn.execute(
            "select value from system_meta where key = ?",
            (VIEW_RECEIPT_KEY,),
        ).fetchone()
        if not receipt_row:
            raise KnowledgeMapError(
                "知识首页还在准备中，请继续当前学习。",
                status=503,
                state="unavailable",
            )
        receipt = db.json_load(receipt_row["value"], {})
        expected_receipt_keys = {
            "receipt_schema_version",
            "config_version",
            "config_sha256",
            "graph_lineage",
            "relative_path",
            "handle_policy_version",
            "activated_at",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != expected_receipt_keys
            or receipt.get("receipt_schema_version") != VIEW_RECEIPT_SCHEMA
            or receipt.get("handle_policy_version") != HANDLE_POLICY_VERSION
        ):
            raise KnowledgeMapError(
                "知识首页配置暂时不可用，请继续当前学习。",
                status=503,
                state="unavailable",
            )
        relative_path = str(receipt.get("relative_path") or "") if isinstance(receipt, dict) else ""
        candidate = (self.project_root / relative_path).resolve()
        project_root = self.project_root.resolve()
        if (
            not relative_path
            or Path(relative_path).is_absolute()
            or not candidate.is_relative_to(project_root)
            or not candidate.is_file()
        ):
            raise KnowledgeMapError(
                "知识首页配置暂时不可用，请继续当前学习。",
                status=503,
                state="unavailable",
            )
        try:
            config = KnowledgeViewConfig.load_validated(candidate, snapshot)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise KnowledgeMapError(
                "知识首页配置暂时不可用，请继续当前学习。",
                status=503,
                state="unavailable",
            ) from exc
        if not config.validation_report.get("valid"):
            raise KnowledgeMapError(
                "知识首页配置暂时不可用，请继续当前学习。",
                status=503,
                state="unavailable",
            )
        if (
            receipt.get("config_version") != config.config_version
            or receipt.get("graph_lineage") != snapshot["graph_lineage"]
            or receipt.get("config_sha256") != config.canonical_sha256()
            or config.graph_lineage != snapshot["graph_lineage"]
        ):
            raise KnowledgeMapError(
                "知识首页版本已经变化，请刷新后再试。",
                status=409,
                state="stale",
            )
        secret_row = self.conn.execute(
            "select value from system_meta where key = ?",
            (HANDLE_SECRET_KEY,),
        ).fetchone()
        secret = _secret_bytes(secret_row["value"] if secret_row else "")
        if len(secret) < 16:
            raise KnowledgeMapError(
                "知识首页安全凭据还没有准备好。",
                status=503,
                state="unavailable",
            )
        assessment = self._assessment_authority(snapshot)
        return {
            "snapshot": snapshot,
            "config": config,
            "secret": secret,
            "assessment": assessment,
        }

    def _handles(self, authority: dict[str, Any]) -> dict[str, dict[str, str]]:
        snapshot = authority["snapshot"]
        config = authority["config"].payload
        secret = authority["secret"]
        lineage = snapshot["graph_lineage"]
        return {
            "node": {
                node_id: _opaque_handle(secret, domain="node", graph_lineage=lineage, canonical_id=node_id)
                for node_id in snapshot["nodes"]
            },
            "module": {
                module_id: _opaque_handle(secret, domain="module", graph_lineage=lineage, canonical_id=module_id)
                for module_id in snapshot["modules"]
            },
            "lane": {
                lane["id"]: _opaque_handle(secret, domain="lane", graph_lineage=lineage, canonical_id=str(lane["id"]))
                for lane in config["graph"]["lanes"]
            },
        }

    def _current_learning(self, child_key: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select f.status, f.mode, f.current_step_id,
                   s.status as step_status, s.step_type, s.prompt_package_json
            from daily_flows f
            left join flow_steps s on s.id = f.current_step_id
            where f.child_key = ?
            order by f.updated_at desc, f.created_at desc, f.id desc
            limit 1
            """,
            (child_key,),
        ).fetchone()
        if not row:
            return self._current_learning_copy("not_started", "")
        prompt_package = db.json_load(row["prompt_package_json"], {})
        topic_label = str(
            prompt_package.get("topic_label")
            if isinstance(prompt_package, dict)
            else ""
        ).strip()
        status = str(row["status"] or "")
        step_status = str(row["step_status"] or "")
        step_type = str(row["step_type"] or "")
        if row["current_step_id"]:
            if step_status == "analyzing":
                state = "analyzing_pending"
            elif step_type in {"teaching_repair", "worked_example"}:
                state = "feedback_teaching"
            elif step_type == "clarify_evidence":
                state = "clarify_evidence"
            else:
                state = "current_step"
        elif status == "new":
            state = "start_resume"
        elif status == "ready_for_new_knowledge":
            state = "ready_for_new_knowledge"
        elif status in {"reviewing", "learning_new"}:
            state = "analyzing_pending"
        elif status in {"completed", "superseded"}:
            state = "summary"
        elif status in {"blocked", "paused"}:
            state = "blocked"
        else:
            state = "start_resume"
        return self._current_learning_copy(state, topic_label)

    def _current_learning_copy(self, state: str, topic_label: str) -> dict[str, str]:
        topic = str(topic_label or "").strip()
        current_label = f"“{topic}”还可以继续。" if topic else "当前学习还可以继续。"
        teaching_label = f"“{topic}”还有下一步。" if topic else "当前学习还有下一步。"
        copy_by_state = {
            "not_started": ("可以先看看自己的数学知识。", "", ""),
            "start_resume": ("今天的学习可以开始了。", "开始今天学习", "正在打开"),
            "current_step": (current_label, "继续当前学习", "正在打开"),
            "analyzing_pending": ("刚才的答案已经保存，正在批阅。", "查看当前进度", "正在打开进度"),
            "feedback_teaching": (teaching_label, "继续当前学习", "正在打开"),
            "clarify_evidence": ("刚才的答案还需要补清楚一点。", "继续补充", "正在打开"),
            "ready_for_new_knowledge": ("旧知识复习暂时告一段落。", "学一个新知识", "正在准备"),
            "blocked": ("刚才的学习已经保存，可以查看恢复方式。", "查看恢复方式", "正在打开"),
            "summary": ("今天的学习已经完成。", "查看今天总结", "正在打开"),
        }
        canonical = state if state in copy_by_state else "not_started"
        label, action_label, pending_label = copy_by_state[canonical]
        return {
            "state": canonical,
            "topic_label": topic[:80],
            "label": label,
            "action_label": action_label,
            "pending_label": pending_label,
        }

    def _child_safe_current_learning(
        self,
        child_key: str,
        current_learning: dict[str, Any] | None,
    ) -> dict[str, str]:
        if not isinstance(current_learning, dict):
            return self._current_learning(child_key)
        state = str(current_learning.get("state") or "not_started").strip() or "not_started"
        topic_label = str(current_learning.get("topic_label") or "").strip()
        return self._current_learning_copy(state, topic_label)

    def _learner_states(self, authority: dict[str, Any]) -> dict[str, dict[str, Any]]:
        graph_version = str(authority["snapshot"]["graph_lineage"])
        bank_version = str(
            authority["assessment"]["ledger"]["question_bank_version"]
        )
        return {
            str(row["node_id"]): row
            for row in db.authoritative_learner_node_status_rows(
                self.conn,
                graph_version=graph_version,
                question_bank_version=bank_version,
            )
        }

    def _target_runtime_context(
        self,
        *,
        child_key: str,
        authority: dict[str, Any],
        learner_states: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        runtime = daily_runtime.DailyLearningRuntime(
            self.conn,
            project_root=self.project_root,
            child_key=child_key,
        )
        source_flow = runtime.current_target_flow()
        source_step = (
            self.conn.execute(
                "select * from flow_steps where id = ?",
                (source_flow["current_step_id"],),
            ).fetchone()
            if source_flow and source_flow["current_step_id"]
            else None
        )
        states = learner_states if learner_states is not None else self._learner_states(authority)
        return {
            "source_flow": source_flow,
            "source_step": source_step,
            "status_by_node": {
                node_id: str(row.get("status_code") or "")
                for node_id, row in states.items()
            },
        }

    def _allowed_actions(
        self,
        node_id: str,
        status_code: str,
        authority: dict[str, Any],
        target_context: dict[str, Any],
    ) -> list[str]:
        node = authority["snapshot"]["nodes"].get(node_id) or {}
        descriptors, _readiness = self._action_descriptors(
            node_id=node_id,
            node=node,
            status_code=status_code,
            authority=authority,
            target_context=target_context,
        )
        return [
            str(item["action"])
            for item in descriptors
            if item.get("enabled") and item.get("action") in ALLOWED_ACTIONS
        ]

    def _action_descriptors(
        self,
        *,
        node_id: str,
        node: dict[str, Any],
        status_code: str,
        authority: dict[str, Any],
        target_context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        assessment_ready = bool(authority["assessment"]["assets_by_node"].get(node_id))
        content_ready = bool(str(node.get("essence_for_child") or "").strip())
        if status_code == "D":
            readiness = {
                "code": "needs_prerequisite",
                "label": "需要先准备",
                "reason": "先补一小步准备知识，再回来学习会更顺。",
            }
        elif not content_ready:
            readiness = {
                "code": "content_unavailable",
                "label": "学习内容准备中",
                "reason": "这个知识点的学习内容还在准备，暂时不能开始。",
            }
        elif not assessment_ready:
            readiness = {
                "code": "assessment_unavailable",
                "label": "小检测准备中",
                "reason": "这个知识点的小检测还在准备。",
            }
        else:
            readiness = {"code": "ready", "label": "可以开始", "reason": ""}
        def descriptor(
            action: str,
            label: str,
            role: str,
            *,
            enabled: bool = True,
            disabled_reason: str = "",
        ) -> dict[str, Any]:
            pending_labels = {
                "diagnostic": "正在准备检测",
                "learn": "正在准备学习",
                "review": "正在准备复习",
                "challenge": "正在准备挑战",
            }
            qualification = daily_runtime.qualify_knowledge_target_action(
                self.conn,
                authority,
                node_id=node_id,
                action=action,
                status_by_node=target_context["status_by_node"],
                source_step=target_context.get("source_step"),
            )
            effective_enabled = enabled and bool(qualification["enabled"])
            effective_reason = "" if effective_enabled else str(
                qualification.get("disabled_reason") or disabled_reason
            )
            return {
                "action": action,
                "label": label,
                "role": role,
                "enabled": effective_enabled,
                "disabled_reason": effective_reason,
                "pending_label": pending_labels[action],
                "result_behavior": qualification["result_behavior"],
            }

        if readiness["code"] == "needs_prerequisite":
            items = [descriptor("learn", "先补准备知识", "primary")]
            if not items[0]["enabled"]:
                readiness["reason"] = items[0]["disabled_reason"]
            return items, readiness
        if readiness["code"] == "content_unavailable":
            preferred = "challenge" if status_code == "A" else "learn"
            label = "挑战一下" if preferred == "challenge" else (
                "针对性学习" if status_code in {"C", "D"} else "开始学习"
            )
            items = [descriptor(
                preferred,
                label,
                "primary",
                enabled=False,
                disabled_reason=readiness["reason"],
            )]
            readiness["reason"] = items[0]["disabled_reason"]
            return items, readiness
        if readiness["code"] == "assessment_unavailable":
            items = [
                descriptor(
                    "diagnostic",
                    "先检测一下",
                    "primary",
                    enabled=False,
                    disabled_reason=readiness["reason"],
                ),
                descriptor("learn", "开始学习", "secondary"),
            ]
            readiness["reason"] = items[0]["disabled_reason"]
            return items, readiness
        if status_code == "A":
            return [
                descriptor("challenge", "挑战一下", "primary"),
                descriptor("review", "复习这个点", "secondary"),
            ], readiness
        if status_code == "B":
            return [
                descriptor("learn", "继续学习", "primary"),
                descriptor("diagnostic", "再检测一次", "secondary"),
            ], readiness
        if status_code in {"C", "D"}:
            return [
                descriptor("learn", "针对性学习", "primary"),
                descriptor("diagnostic", "再检测一次", "secondary"),
            ], readiness
        return [
            descriptor("diagnostic", "先检测一下", "primary"),
            descriptor("learn", "开始学习", "secondary"),
        ], readiness

    def child_projection(
        self,
        *,
        child_key: str = "single-child",
        current_learning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        authority = self._runtime_authority()
        snapshot = authority["snapshot"]
        config_object: KnowledgeViewConfig = authority["config"]
        config = config_object.payload
        handles = self._handles(authority)
        learner_states = self._learner_states(authority)
        target_context = self._target_runtime_context(
            child_key=child_key,
            authority=authority,
            learner_states=learner_states,
        )
        current_learning_projection = self._child_safe_current_learning(
            child_key,
            current_learning,
        )
        status_labels = {
            "A": ("stable", "暂时掌握", "已经比较稳"),
            "B": ("developing", "学习中", "有学习记录，还可以再稳一点"),
            "C": ("needs_support", "待巩固", "适合再巩固关键步骤"),
            "D": ("needs_support", "待巩固", "适合先补一小步"),
        }
        visible_module_ids = _child_visible_module_ids(config, snapshot)
        visible_module_id_set = set(visible_module_ids)
        visible_node_ids = {
            node_id
            for node_id, node in snapshot["nodes"].items()
            if _node_module_id(node) in visible_module_id_set
        }
        child_module_order = {
            module_id: (index + 1) * 10
            for index, module_id in enumerate(visible_module_ids)
        }
        modules = [
            {
                "handle": handles["module"][module_id],
                "name": str(snapshot["modules"][module_id]["name"]),
                "order": child_module_order[module_id],
                "collapsed_by_default": bool(
                    config["mind_map"]["modules"][module_id]["collapsed_by_default"]
                ),
            }
            for module_id in visible_module_ids
        ]
        nodes: list[dict[str, Any]] = []
        module_order_index = {
            module_id: index
            for index, module_id in enumerate(visible_module_ids)
        }
        ordered_nodes = sorted(
            (
                (node_id, node)
                for node_id, node in snapshot["nodes"].items()
                if node_id in visible_node_ids
            ),
            key=lambda item: (
                module_order_index.get(_node_module_id(item[1]), 999),
                config["mind_map"]["nodes"][item[0]]["order"],
                str(item[1].get("name") or ""),
            ),
        )
        for node_id, node in ordered_nodes:
            taxonomy = node.get("taxonomy") if isinstance(node.get("taxonomy"), dict) else {}
            status = learner_states.get(node_id)
            status_code = str(status["status_code"] if status else "")
            band, evidence_label, summary = status_labels.get(
                status_code,
                ("untested", "未测试", "还没有留下学习记录"),
            )
            source_attempt_ids = db.json_load(
                status.get("source_attempt_ids_json") if status else None,
                [],
            )
            completed_activity = min(
                4,
                len(source_attempt_ids) if isinstance(source_attempt_ids, list) else 0,
            )
            action_descriptors, action_readiness = self._action_descriptors(
                node_id=node_id,
                node=node,
                status_code=status_code,
                authority=authority,
                target_context=target_context,
            )
            allowed_actions = [
                str(item["action"])
                for item in action_descriptors
                if item.get("enabled") and item.get("action") in ALLOWED_ACTIONS
            ]
            nodes.append({
                "handle": handles["node"][node_id],
                "name": str(node.get("name") or ""),
                "module_handle": handles["module"][str(taxonomy.get("module_id") or "")],
                "stage_label": str(node.get("stage") or ""),
                "essence": str(node.get("essence_for_child") or ""),
                "learning_state": band,
                "learning_state_label": summary,
                "evidence_state": {"code": band, "label": evidence_label},
                "activity": {
                    "completed": completed_activity,
                    "total": 4,
                    "label": f"学习历程，完成 {completed_activity}/4",
                },
                "stage_progress": {"completed": completed_activity, "total": 4},
                "mastery_band": band,
                "mastery_summary": summary,
                "action_readiness": action_readiness,
                "action_descriptors": action_descriptors,
                "allowed_actions": allowed_actions,
                "recommended": status_code in {"C", "D"},
            })
        relationships = [
            {
                "source_handle": handles["node"][edge["source"]],
                "target_handle": handles["node"][edge["target"]],
                "relation": "hard_prerequisite",
            }
            for edge in snapshot["strict_prerequisites"]
            if edge["source"] in visible_node_ids and edge["target"] in visible_node_ids
        ]
        mind_placements = []
        for node_id, placement in config["mind_map"]["nodes"].items():
            if node_id not in visible_node_ids:
                continue
            parent = placement["primary_parent"]
            if (
                (parent["type"] == "module" and parent["id"] not in visible_module_id_set)
                or (parent["type"] == "node" and parent["id"] not in visible_node_ids)
            ):
                continue
            parent_handle = (
                handles["module"][parent["id"]]
                if parent["type"] == "module"
                else handles["node"][parent["id"]]
            )
            mind_placements.append({
                "handle": handles["node"][node_id],
                "parent_handle": parent_handle,
                "parent_type": parent["type"],
                "order": placement["order"],
                "collapsed_by_default": placement["collapsed_by_default"],
            })
        cross_links = [
            {
                "source_handle": handles["node"][edge["source"]],
                "target_handle": handles["node"][edge["target"]],
            }
            for edge in config_object.mind_map_cross_links(snapshot["strict_prerequisites"])
            if edge["source"] in visible_node_ids and edge["target"] in visible_node_ids
        ]
        projection_version = _child_projection_version(config_object)
        return {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "projection_version": projection_version,
            "default_view": "mind_map",
            "modules": modules,
            "nodes": nodes,
            "relationships": relationships,
            "views": {
                "mind_map": {
                    "root_label": str(config["root"].get("label") or "我的数学知识体系"),
                    "placements": sorted(mind_placements, key=lambda item: (item["parent_handle"], item["order"])),
                    "cross_links": cross_links,
                }
            },
            "current_learning": current_learning_projection,
            "recommended_handles": [row["handle"] for row in nodes if row["recommended"]],
        }

    def select_target(self, *, child_key: str = "single-child", request: dict[str, Any]) -> dict[str, Any]:
        savepoint, nested = _begin_write(self.conn, "select_target")
        try:
            if not isinstance(request, dict):
                raise KnowledgeMapError(
                    "这个学习目标无法确认，请刷新后再试。",
                    status=409,
                    state="conflict",
                )
            expected_keys = {
                "handle",
                "projection_version",
                "action",
                "client_idempotency_key",
            }
            if set(request) != expected_keys:
                raise KnowledgeMapError(
                    "这个学习目标包含了无效信息，请刷新后再试。",
                    status=409,
                    state="conflict",
                )
            authority = self._runtime_authority()
            config: KnowledgeViewConfig = authority["config"]
            projection_version = _child_projection_version(config)
            if request.get("projection_version") != projection_version:
                raise KnowledgeMapError(
                    "知识首页已经更新，请刷新后重新选择。",
                    status=409,
                    state="conflict",
                )
            handles = self._handles(authority)
            handle = str(request.get("handle") or "")
            node_id = next(
                (
                    candidate
                    for candidate, candidate_handle in handles["node"].items()
                    if hmac.compare_digest(handle, candidate_handle)
                ),
                "",
            )
            action = str(request.get("action") or "")
            key = str(request.get("client_idempotency_key") or "").strip()
            if not node_id or action not in ALLOWED_ACTIONS or not key:
                raise KnowledgeMapError(
                    "这个学习目标无法验证，请刷新后重新选择。",
                    status=409,
                    state="conflict",
                )
            node = authority["snapshot"]["nodes"].get(node_id) or {}
            if _node_module_id(node) in CHILD_HIDDEN_MODULE_IDS:
                raise KnowledgeMapError(
                    "这个学习目标暂时不能从首页选择，请换一个知识点。",
                    status=409,
                    state="conflict",
                )
            graph_version = str(authority["snapshot"]["graph_lineage"])
            learner_states = self._learner_states(authority)
            status_code = str((learner_states.get(node_id) or {}).get("status_code") or "")
            target_context = self._target_runtime_context(
                child_key=child_key,
                authority=authority,
                learner_states=learner_states,
            )
            descriptors, _readiness = self._action_descriptors(
                node_id=node_id,
                node=node,
                status_code=status_code,
                authority=authority,
                target_context=target_context,
            )
            selected_descriptor = next(
                (item for item in descriptors if item["action"] == action),
                None,
            )
            if not selected_descriptor or not selected_descriptor["enabled"]:
                raise KnowledgeMapError(
                    str(
                        (selected_descriptor or {}).get("disabled_reason")
                        or "这部分还没有通过完整审查，请继续当前学习。"
                    ),
                    status=409,
                    state="conflict",
                )
            payload_digest = _intent_digest(node_id=node_id, action=action)
            existing = self.conn.execute(
                """
                select * from learning_target_intents
                where child_key = ? and graph_version = ?
                  and client_idempotency_key = ?
                """,
                (child_key, graph_version, key),
            ).fetchone()
            if existing and any(
                (
                    existing["node_id"] != node_id,
                    existing["action"] != action,
                    existing["payload_digest_sha256"] != payload_digest,
                )
            ):
                raise KnowledgeMapError(
                    "这个学习目标和刚才的选择不一致，请刷新后再试。",
                    status=409,
                    state="conflict",
                )
            source_flow = target_context.get("source_flow")
            source_step = target_context.get("source_step")
            if existing:
                intent = dict(existing)
            else:
                self.conn.execute(
                    """
                    update learning_target_intents
                    set status = 'cancelled', reason = 'replaced_by_newer_target', updated_at = ?
                    where child_key = ? and graph_version = ?
                      and status in ('pending','waiting_for_safe_boundary')
                    """,
                    (db.now_iso(), child_key, graph_version),
                )
                intent = create_target_intent(
                    self.conn,
                    child_key=child_key,
                    graph_version=graph_version,
                    node_id=node_id,
                    action=action,
                    client_idempotency_key=key,
                    source_flow_id=str(source_flow["id"]) if source_flow else None,
                    source_flow_revision=(
                        int(source_flow["flow_revision"] or 1) if source_flow else None
                    ),
                    source_step_id=str(source_step["id"]) if source_step else None,
                    status="pending",
                    reason="ready_for_runtime_boundary",
                )
            runtime = daily_runtime.DailyLearningRuntime(
                self.conn,
                project_root=self.project_root,
                child_key=child_key,
            )
            result = runtime._materialize_target_intent_locked(
                str(intent["id"]),
                authority,
            )
            status = str(result.get("status") or "blocked")
            expected_status = (
                "applied"
                if selected_descriptor["result_behavior"] == "enter_now"
                else "waiting_for_safe_boundary"
            )
            if status != expected_status:
                raise KnowledgeMapError(
                    str(
                        result.get("message")
                        or selected_descriptor.get("disabled_reason")
                        or "这个学习目标的状态已经变化，请刷新后重新选择。"
                    ),
                    status=409,
                    state="conflict",
                )
            _finish_write(self.conn, savepoint, nested)
        except KnowledgeMapError:
            _rollback_write(self.conn, savepoint, nested)
            raise
        except (LookupError, ValueError, sqlite3.DatabaseError) as exc:
            _rollback_write(self.conn, savepoint, nested)
            raise KnowledgeMapError(
                "这个学习目标暂时无法安全切换，请刷新后再试。",
                status=409,
                state="conflict",
            ) from exc
        status = str(result.get("status") or "blocked")
        node_name = str((authority["snapshot"]["nodes"].get(node_id) or {}).get("name") or "这个知识点")
        messages = {
            "applied": "已经切换到这个学习目标。",
            "waiting_for_safe_boundary": f"已经记住“{node_name}”，当前学习结束后会切换到这里。",
            "blocked": "这个学习目标暂时不能安全开始，请继续当前学习。",
        }
        return {
            "status": status,
            "result_behavior": selected_descriptor["result_behavior"],
            "message": messages.get(status, messages["blocked"]),
            "current_learning": self._current_learning(child_key),
            "client_idempotency_key": key,
        }
