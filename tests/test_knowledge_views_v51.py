from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from unittest import mock
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path

from learning_system import db, question_bank, question_visuals, server
from learning_system.graph_runtime import GraphRuntimeService
from learning_system.knowledge_map import KnowledgeMapError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
VIEW_CONFIG_PATH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_views_v5_1.json"
KNOWLEDGE_VIEW_JS = PROJECT_ROOT / "app/local_learning_system/knowledge_views.js"
KNOWLEDGE_VIEW_CSS = PROJECT_ROOT / "app/local_learning_system/knowledge_views.css"
CHILD_INDEX = PROJECT_ROOT / "app/local_learning_system/index.html"
BROWSER_FIXTURE = PROJECT_ROOT / "tests/fixtures/browser_knowledge_views_v51.mjs"
POLICY_OFF_BROWSER_FIXTURE = PROJECT_ROOT / "tests/fixtures/browser_knowledge_views_policy_off_v51.mjs"
KNOWLEDGE_ACTIVATION_SCRIPT = PROJECT_ROOT / "scripts/activate_knowledge_views.py"
QUESTION_VISUAL_ACTIVATION_SCRIPT = PROJECT_ROOT / "scripts/activate_question_visuals.py"
QUESTION_VISUAL_MANIFEST_PATH = PROJECT_ROOT / "data/question_visuals/math_question_visual_manifest_v1.json"
QUESTION_VISUAL_INVENTORY_PATH = PROJECT_ROOT / "data/question_visuals/math_question_visual_inventory_v1.json"
INVALID_CONFIG_FIXTURE = PROJECT_ROOT / "tests/fixtures/knowledge_views_v51_invalid_config.json"

VIEW_RECEIPT_KEY = "knowledge_views_active.v1"
HANDLE_SECRET_KEY = "knowledge_views_handle_secret.v1"
ASSESSMENT_RECEIPT_KEY = "answer_assessment_active.v5.1"
HANDLE_SECRET_ONE = "11" * 32
HANDLE_SECRET_TWO = "22" * 32
TEST_BANK_VERSION = "2026-07-15.kv51-authority-test"
MUTATING_ACTIONS = {"diagnostic", "learn", "review", "challenge"}
CHILD_HIDDEN_MODULE_IDS = {"Z_LEARNING_PROCESS"}
EXPECTED_CHILD_MODULE_ORDER = [
    "底层计算与数感",
    "有理数概念与运算",
    "分数百分数与比例",
    "算术到代数桥梁",
    "代数式与整式",
    "一元一次方程",
    "应用题模型",
    "几何图形初步",
]
EXPECTED_PROJECTION_KEYS = {
    "schema_version",
    "projection_version",
    "default_view",
    "modules",
    "nodes",
    "relationships",
    "views",
    "current_learning",
    "recommended_handles",
}
EXPECTED_CONTROLLER_API = {
    "initialize",
    "setProjection",
    "show",
    "hide",
    "focusNode",
    "currentView",
    "destroy",
}
CHILD_FORBIDDEN_KEYS = {
    "node_id",
    "node_ids",
    "canonical_node_id",
    "graph_version",
    "graph_lineage",
    "config_version",
    "config_sha256",
    "config_path",
    "question_id",
    "attempt_id",
    "assessment_id",
    "flow_id",
    "step_id",
    "packet_id",
    "lineage_id",
    "provider",
    "provider_mode",
    "model",
    "agent",
    "agent_key",
    "prompt",
    "rubric",
    "threshold",
    "confidence",
    "queue",
    "job",
    "job_id",
    "reducer",
    "idempotency_key",
}


def _canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sealed_receipt(payload: dict) -> dict:
    body = dict(payload)
    body["receipt_digest_sha256"] = _canonical_sha256(body)
    return body


def _edge_set(items) -> set[tuple[str, str]]:
    edges = set()
    for item in items:
        if isinstance(item, dict):
            source = item.get("source") or item.get("from") or item.get("source_handle")
            target = item.get("target") or item.get("to") or item.get("target_handle")
        else:
            source, target = item
        edges.add((str(source), str(target)))
    return edges


def _row_id(row) -> str:
    if isinstance(row, sqlite3.Row):
        return str(row["id"])
    if isinstance(row, dict):
        return str(row.get("id") or row.get("intent_id") or "")
    return str(getattr(row, "id", "") or "")


class KnowledgeViewsV51TestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        cls.nodes = {str(node["id"]): node for node in cls.graph["nodes"]}
        cls.node_ids = set(cls.nodes)
        cls.module_names = {}
        for node in cls.nodes.values():
            taxonomy = node["taxonomy"]
            module_id = str(taxonomy["module_id"])
            module_name = str(taxonomy["module_name"])
            prior = cls.module_names.setdefault(module_id, module_name)
            if prior != module_name:
                raise AssertionError(f"module name drift for {module_id}")
        cls.module_ids = set(cls.module_names)
        cls.child_visible_node_ids = {
            node_id
            for node_id, node in cls.nodes.items()
            if str(node["taxonomy"]["module_id"]) not in CHILD_HIDDEN_MODULE_IDS
        }
        cls.child_visible_module_ids = cls.module_ids - CHILD_HIDDEN_MODULE_IDS
        cls.strict_edges = {
            (str(prerequisite), node_id)
            for node_id, node in cls.nodes.items()
            for prerequisite in node.get("prerequisites", [])
        }
        cls.unlock_edges = {
            (node_id, str(unlocked))
            for node_id, node in cls.nodes.items()
            for unlocked in node.get("unlocks", [])
        }
        cls.unlock_only_edges = cls.unlock_edges - cls.strict_edges
        cls.graph_lineage = GraphRuntimeService(project_root=PROJECT_ROOT).current_graph_version()

    def _require_file(self, path: Path, purpose: str) -> Path:
        self.assertTrue(path.is_file(), f"missing production {purpose}: {path}")
        return path

    def _require_module(self, module_name: str):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                self.fail(f"missing production module: {module_name}")
            raise

    def _load_view_config_json(self) -> dict:
        path = self._require_file(VIEW_CONFIG_PATH, "v5.1 knowledge-view config")
        return json.loads(path.read_text(encoding="utf-8"))

    @contextmanager
    def _policy_env(self, *, map_policy: str, assessment_policy: str):
        updates = {
            "KNOWLEDGE_MAP_HOME_POLICY": map_policy,
            "ANSWER_ASSESSMENT_POLICY": assessment_policy,
            "V3_DAILY_RUNTIME_ENABLED": "1",
        }
        previous = {key: os.environ.get(key) for key in updates}
        os.environ.update(updates)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    @contextmanager
    def _temp_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "knowledge-views-v51.sqlite"
            with closing(db.connect(path)) as conn:
                db.init_schema(conn)
                self._seed_graph_only(conn)
            yield path

    def _seed_graph_only(self, conn: sqlite3.Connection) -> None:
        with conn:
            for node_id, node in self.nodes.items():
                summer = node.get("summer_execution") or {}
                conn.execute(
                    """
                    insert into graph_nodes(
                      id, name, stage, domain, priority, summer_mode,
                      sequence_band, prerequisites_json, unlocks_json, raw_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node_id,
                        str(node.get("name") or ""),
                        str(node.get("stage") or ""),
                        str(node.get("domain") or ""),
                        str(node.get("priority") or ""),
                        str(summer.get("mode") or "diagnose_only"),
                        int(summer.get("sequence_band") or 99),
                        db.json_dump(node.get("prerequisites") or []),
                        db.json_dump(node.get("unlocks") or []),
                        db.json_dump(node),
                    ),
                )
            for source, target in sorted(self.strict_edges):
                conn.execute(
                    "insert into graph_edges(from_node_id, to_node_id, relation) values (?, ?, 'prerequisite')",
                    (source, target),
                )
            conn.execute(
                "insert into system_meta(key, value, updated_at) values (?, ?, ?)",
                (
                    "graph_ref",
                    db.json_dump({"lineage": self.graph_lineage}),
                    "2026-07-15T00:00:00+08:00",
                ),
            )

    def _install_view_activation(
        self,
        conn: sqlite3.Connection,
        *,
        config_payload: dict,
        relative_path: str = "data/knowledge_graphs/math/math_knowledge_views_v5_1.json",
        secret: str = HANDLE_SECRET_ONE,
        assessment_active: bool = True,
        assessment_node_ids: list[str] | None = None,
    ) -> list[dict]:
        receipt = {
            "receipt_schema_version": "knowledge-views-activation.v1",
            "config_version": str(config_payload.get("config_version") or "2026-07-14.v5.1"),
            "config_sha256": _canonical_sha256(config_payload),
            "graph_lineage": self.graph_lineage,
            "relative_path": relative_path,
            "handle_policy_version": "kv51-h1",
            "activated_at": "2026-07-15T00:00:00+08:00",
        }
        with conn:
            conn.execute(
                "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
                (VIEW_RECEIPT_KEY, db.json_dump(receipt), "2026-07-15T00:00:00+08:00"),
            )
            conn.execute(
                "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
                (HANDLE_SECRET_KEY, secret, "2026-07-15T00:00:00+08:00"),
            )
        return (
            self._install_assessment_activation(conn, node_ids=assessment_node_ids)
            if assessment_active
            else []
        )

    def _install_visual_activation(self, conn: sqlite3.Connection) -> None:
        manifest = question_visuals.QuestionVisualManifest.load_validated(
            QUESTION_VISUAL_MANIFEST_PATH,
            inventory_path=QUESTION_VISUAL_INVENTORY_PATH,
        )
        report = manifest.audit_report
        inventory = json.loads(QUESTION_VISUAL_INVENTORY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(40, report["manifest_entry_count"], report)
        self.assertEqual(40, report["required_triple_count"], report)
        self.assertEqual(0, report["pending_inventory_slots"], report)
        activated_at = "2026-07-15T00:00:00+08:00"
        receipt = {
            "receipt_schema_version": question_visuals.ACTIVE_RECEIPT_SCHEMA_VERSION,
            "manifest_version": manifest.payload["manifest_version"],
            "manifest_sha256": report["manifest_sha256"],
            "inventory_version": inventory["inventory_version"],
            "inventory_sha256": report["inventory_sha256"],
            "relative_path": str(QUESTION_VISUAL_MANIFEST_PATH.relative_to(PROJECT_ROOT)),
            "inventory_relative_path": str(QUESTION_VISUAL_INVENTORY_PATH.relative_to(PROJECT_ROOT)),
            "renderer_contract_version": manifest.payload["renderer_contract_version"],
            "required_triple_count": report["required_triple_count"],
            "required_triples_sha256": report["required_triples_sha256"],
            "activated_at": activated_at,
        }
        conn.execute(
            "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
            (question_visuals.ACTIVE_RECEIPT_KEY, db.json_dump(receipt), activated_at),
        )
        conn.commit()

    def _install_assessment_activation(
        self,
        conn: sqlite3.Connection,
        *,
        node_ids: list[str] | None = None,
    ) -> list[dict]:
        default_nodes = [
            node_id
            for node_id in sorted(self.node_ids)
            if node_id in self.child_visible_node_ids and not self.nodes[node_id].get("prerequisites")
        ]
        default_nodes.extend(
            node_id
            for node_id in sorted(self.child_visible_node_ids)
            if node_id not in default_nodes
        )
        default_nodes = default_nodes[:2]
        selected_node_ids = list(node_ids or default_nodes)
        assets = []
        with conn:
            conn.execute("delete from question_bank_version_ledger where status = 'active'")
            now = "2026-07-15T00:00:00+08:00"
            ledger_id = "QBL-kv51-authority"
            conn.execute(
                """
                insert or replace into question_bank_version_ledger(
                  id, question_bank_version, graph_version, manifest_id,
                  manifest_sha256, node_count, item_count, status,
                  activated_at, reason, created_at, updated_at
                ) values (?, ?, ?, 'kv51-authority-manifest', ?, ?, ?, 'active',
                          ?, 'isolated knowledge-view authority fixture', ?, ?)
                """,
                (
                    ledger_id,
                    TEST_BANK_VERSION,
                    self.graph_lineage,
                    "a" * 64,
                    len(set(selected_node_ids)),
                    len(selected_node_ids),
                    now,
                    now,
                    now,
                ),
            )
            node_occurrences: dict[str, int] = {}
            for index, node_id in enumerate(selected_node_ids, 1):
                node_occurrences[node_id] = node_occurrences.get(node_id, 0) + 1
                variant_context = (
                    f"这是同一知识点的第 {node_occurrences[node_id]} 个不同情境。"
                    if selected_node_ids.count(node_id) > 1
                    else ""
                )
                question_id = f"KV51-Q-{index:02d}"
                review_record_id = f"KV51-QRR-{index:02d}"
                contract_id = f"KV51-AC-{index:02d}"
                node = dict(self.nodes[node_id])
                node_name = str(node.get("name") or "这个知识点")
                essence = str(
                    node.get("teaching_contract", {}).get("one_sentence_essence")
                    or node.get("essence_for_child")
                    or f"{node_name} 的核心关系"
                )
                question_type = str(
                    (node.get("question_generation", {}).get("seed_question_types") or ["诊断辨析"])[0]
                )
                candidate = {
                    "id": question_id,
                    "item_version": TEST_BANK_VERSION,
                    "source_type": "graph_generated",
                    "node_id": node_id,
                    "kind": "wrong_solution_repair",
                    "question_type": question_type,
                    "variant_level": "L3",
                    "prompt": (
                        f"围绕「{node_name}」判断这段说法："
                        f"“{essence}，所以遇到同类题只要写最后答案就能证明会了。”"
                        "请指出这句话哪一部分可用、哪一部分不够，并用一个小例子或检验说明理由。"
                        f"{variant_context}"
                    ),
                    "answer_format": "可用部分 + 不够部分 + 例子或检验",
                    "expected_answer": (
                        f"可用部分：{essence}。不够部分：只写最后答案不能证明掌握，"
                        "还要给出关键关系、必要过程或检验。例子可以展示规则如何使用，"
                        "并说明为什么不是只靠答案。"
                    ),
                    "rubric": {
                        "requires_process": True,
                        "score_points": [
                            {"key": "rule", "points": 4, "criterion": "能说出本节点核心规则或关系"},
                            {"key": "gap", "points": 3, "criterion": "能指出只写答案不足以证明掌握"},
                            {"key": "evidence", "points": 3, "criterion": "能给出例子、过程或检验作为证据"},
                        ],
                    },
                    "solution_steps": [
                        f"先确认本节点核心关系：{essence}",
                        "再说明“只写最后答案”缺少过程证据或检验证据。",
                        "最后给出一个小例子、过程片段或检验，证明规则真的能用。",
                    ],
                    "target_error_tags": ["concept_confusion"],
                    "rollback_candidate_node_ids": [],
                    "rollback_candidate_relations": [],
                    "estimated_minutes": 4,
                    "parent_observation": "",
                    "source": {
                        "type": "graph_generated",
                        "fixture": "kv51-authority",
                        "curated_manifest_id": question_bank.GRAPH_SEED_REVIEW_MANIFEST_ID,
                    },
                }
                question_bank._attach_question_identity_contract(candidate, node, question_type)
                question_bank.apply_question_lineage(
                    candidate,
                    graph_version=self.graph_lineage,
                    question_bank_version=TEST_BANK_VERSION,
                )
                candidate["source"]["reviewer_evidence"] = (
                    question_bank.curated_seed_reviewer_evidence(candidate)
                )
                quality = question_bank.review_item_quality(candidate)
                self.assertEqual("approved", quality["review_status"], quality)
                candidate["quality"] = quality
                candidate["cognitive_level"] = quality["cognitive_level"]
                candidate["item_purpose"] = quality["item_purpose"]
                candidate["requires_reasoning"] = quality["requires_reasoning"]
                candidate["review_agent_check"] = {
                    "reviewer_agent": question_bank.QUESTION_REVIEWER_AGENT_KEY,
                    "status": quality["review_status"],
                    "rejection_reasons": quality["rejection_reasons"],
                }
                candidate["challenge_profile"] = {
                    "picture_level": False,
                    "labels": [],
                }
                candidate_digest = db._digest_json(candidate)
                question_digest = _canonical_sha256({
                    "question_id": candidate["id"],
                    "item_version": candidate["item_version"],
                    "node_id": candidate["node_id"],
                    "kind": candidate["kind"],
                    "prompt": candidate["prompt"],
                    "answer_format": candidate["answer_format"],
                    "expected_answer": candidate["expected_answer"],
                    "solution_steps": candidate["solution_steps"],
                    "reference_evidence": None,
                })
                conn.execute(
                    """
                    insert or replace into question_items(
                      id, item_version, source_type, node_id, secondary_node_ids_json,
                      kind, question_type, variant_level, prompt, answer_format,
                      expected_answer, rubric_json, solution_steps_json, error_tags_json,
                      rollback_candidate_node_ids_json, rollback_candidate_relations_json,
                      estimated_minutes, parent_observation, source_json, raw_json
                    ) values (?, ?, 'graph_generated', ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              '[]', '[]', 2, '', ?, ?)
                    """,
                    (
                        question_id,
                        TEST_BANK_VERSION,
                        node_id,
                        candidate["kind"],
                        candidate["question_type"],
                        candidate["variant_level"],
                        candidate["prompt"],
                        candidate["answer_format"],
                        candidate["expected_answer"],
                        db.json_dump(candidate["rubric"]),
                        db.json_dump(candidate["solution_steps"]),
                        db.json_dump(candidate["target_error_tags"]),
                        db.json_dump(candidate["source"]),
                        db.json_dump(candidate),
                    ),
                )
                db.upsert_question_usage_policy(conn, candidate, commit=False)
                question_run = db.record_agent_run(
                    conn,
                    agent_key="question_reviewer_agent",
                    engine_type="model",
                    session_id=None,
                    phase="question_quality_review",
                    trigger=f"kv51-question-review:{question_id}",
                    input_refs={"question_id": question_id, "candidate_sha256": candidate_digest},
                    status="accepted",
                    confidence=0.99,
                    output={"review_status": "approved", "active_eligible": True},
                    model_provider="openai",
                    model_name="gpt-5.5",
                    model_alias="gpt-5.5",
                    commit=False,
                )
                conn.execute(
                    """
                    insert or replace into question_review_records(
                      id, question_id, candidate_id, item_version, source_type,
                      candidate_sha256, reviewer_run_id, review_contract_version,
                      review_status, rejection_reasons_json, criteria_json,
                      active_eligible, reviewed_at
                    ) values (?, ?, ?, ?, 'graph_generated', ?, ?, 'question-review.v1',
                              'approved', '[]', '{}', 1, ?)
                    """,
                    (
                        review_record_id,
                        question_id,
                        question_id,
                        TEST_BANK_VERSION,
                        candidate_digest,
                        question_run["id"],
                        now,
                    ),
                )
                designer_output = {"schema_version": "answer-contract-design.v2", "items": [{"item_handle": f"item-{index}"}]}
                designer_run = db.record_agent_run(
                    conn,
                    agent_key="answer_contract_designer_agent",
                    engine_type="model",
                    session_id=None,
                    phase="answer_contract_design_v2",
                    trigger=f"kv51-contract-design:{question_id}",
                    input_refs={"question_id": question_id, "item_version": TEST_BANK_VERSION},
                    status="accepted",
                    confidence=0.95,
                    output=designer_output,
                    model_provider="openai",
                    model_name="gpt-5.5",
                    model_alias="gpt-5.5",
                    commit=False,
                )
                contract_digest = _canonical_sha256(
                    {"question_id": question_id, "item_version": TEST_BANK_VERSION, "contract_version": 1}
                )
                reviewer_output = {"schema_version": "answer-contract-review.v2", "items": [{"approved": True, "issues": []}]}
                reviewer_run = db.record_agent_run(
                    conn,
                    agent_key="answer_contract_reviewer_agent",
                    engine_type="model",
                    session_id=None,
                    phase="answer_contract_review_v2",
                    trigger=f"kv51-contract-review:{question_id}",
                    input_refs={
                        "question_id": question_id,
                        "item_version": TEST_BANK_VERSION,
                        "contract_digest_sha256": contract_digest,
                    },
                    status="accepted",
                    confidence=0.95,
                    output=reviewer_output,
                    model_provider="openai",
                    model_name="gpt-5.5",
                    model_alias="gpt-5.5",
                    commit=False,
                )
                design_receipt = _sealed_receipt({
                    "schema_version": "answer-contract-design-receipt.v2",
                    "agent_run_id": designer_run["id"],
                    "output_digest_sha256": db._digest_json(designer_output),
                    "exact_live_lineage": True,
                })
                review_receipt = _sealed_receipt({
                    "schema_version": "answer-contract-review-receipt.v2",
                    "agent_run_id": reviewer_run["id"],
                    "contract_digest_sha256": contract_digest,
                    "output_digest_sha256": db._digest_json(reviewer_output),
                    "exact_live_lineage": True,
                })
                conn.execute(
                    """
                    insert or replace into answer_contracts(
                      id, stable_contract_id, question_id, item_version, contract_version,
                      contract_digest_sha256, question_digest_sha256, graph_version,
                      question_bank_version, reference_solution_json, score_points_json,
                      generator_version, generation_input_digest_sha256, generator_run_id,
                      design_contract_schema_version, review_contract_schema_version,
                      design_receipt_json, design_receipt_sha256,
                      review_record_id, review_run_id, review_receipt_json,
                      review_receipt_sha256, status, approved_at, activated_at,
                      created_at, updated_at
                    ) values (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'answer-contract-v2', ?, ?,
                              'answer-contract-design.v2', 'answer-contract-review.v2', ?, ?,
                              ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (
                        contract_id,
                        contract_id,
                        question_id,
                        TEST_BANK_VERSION,
                        contract_digest,
                        question_digest,
                        self.graph_lineage,
                        TEST_BANK_VERSION,
                        db.json_dump({"solution_steps": candidate["solution_steps"], "components": []}),
                        db.json_dump([
                            {"key": "relation", "criterion": "写出关键关系", "dimension": "concept", "points": 6, "required_for_pass": True, "source_target_key": "relation"},
                            {"key": "explain", "criterion": "说明关系含义", "dimension": "reasoning", "points": 4, "required_for_pass": False, "source_target_key": "explain"},
                        ]),
                        _canonical_sha256({"question_id": question_id, "generation": 1}),
                        designer_run["id"],
                        db.json_dump(design_receipt),
                        design_receipt["receipt_digest_sha256"],
                        review_record_id,
                        reviewer_run["id"],
                        db.json_dump(review_receipt),
                        review_receipt["receipt_digest_sha256"],
                        now,
                        now,
                        now,
                        now,
                    ),
                )
                assets.append({
                    "question_id": question_id,
                    "item_version": TEST_BANK_VERSION,
                    "node_id": node_id,
                    "question_digest_sha256": question_digest,
                    "review_record_id": review_record_id,
                    "candidate_sha256": candidate_digest,
                    "contract_id": contract_id,
                    "contract_version": 1,
                    "contract_digest_sha256": contract_digest,
                    "generator_run_id": designer_run["id"],
                    "review_run_id": reviewer_run["id"],
                    "design_receipt_sha256": design_receipt["receipt_digest_sha256"],
                    "review_receipt_sha256": review_receipt["receipt_digest_sha256"],
                })
            activation = _sealed_receipt({
                "schema_version": "answer-assessment-activation.v1",
                "status": "active",
                "graph_lineage": self.graph_lineage,
                "question_bank_ledger_id": ledger_id,
                "question_bank_version": TEST_BANK_VERSION,
                "active_contract_count": len(assets),
                "contract_set_digest_sha256": _canonical_sha256(sorted(assets, key=lambda item: item["question_id"])),
                "audited_at": now,
            })
            conn.execute(
                "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
                (ASSESSMENT_RECEIPT_KEY, db.json_dump(activation), now),
            )
        return assets

    def _install_authoritative_mastery(
        self,
        conn: sqlite3.Connection,
        asset: dict,
        *,
        status_code: str = "B",
        answer_model_provider: str = "openai",
    ) -> dict:
        now = "2026-07-15T00:05:00+08:00"
        session_id = f"LS-{asset['question_id']}"
        flow_id = f"DF-{asset['question_id']}"
        step_id = f"FS-{asset['question_id']}"
        attempt_id = f"AT-{asset['question_id']}"
        assessment_id = f"AS-{asset['question_id']}"
        validation_id = f"EV-{asset['question_id']}"
        mastery_id = f"MD-{asset['question_id']}"
        assessment_digest = _canonical_sha256({"assessment_id": assessment_id, "accepted": True})
        answer_run = db.record_agent_run(
            conn,
            agent_key="answer_analysis_agent",
            engine_type="model",
            session_id=session_id,
            phase="answer_analysis",
            trigger=f"kv51-answer-analysis:{attempt_id}",
            input_refs={"attempt_id": attempt_id, "assessment_id": assessment_id},
            status="accepted",
            confidence=0.95,
            output={"schema_version": "answer-review.v3", "criteria": []},
            model_provider=answer_model_provider,
            model_name="gpt-5.5",
            model_alias="gpt-5.5",
            commit=False,
        )
        evaluation_run = db.record_agent_run(
            conn,
            agent_key="evaluation_agent",
            engine_type="deterministic",
            session_id=session_id,
            phase="evaluation_update",
            trigger=f"kv51-mastery:{attempt_id}",
            input_refs={"attempt_id": attempt_id, "evidence_validation_id": validation_id},
            status="accepted",
            confidence=1.0,
            output={"node_id": asset["node_id"], "status_code": status_code},
            commit=False,
        )
        with conn:
            conn.execute(
                "insert into learning_sessions(id, title, mode, status, created_at) values (?, 'kv51', 'daily_flow_v3', 'active', ?)",
                (session_id, now),
            )
            conn.execute(
                """
                insert into daily_flows(
                  id, child_key, local_date, mode, status, current_step_id,
                  graph_version, question_bank_version, legacy_session_id,
                  assessment_policy_version, created_at, updated_at
                ) values (?, 'single-child', '2026-07-15', 'review_old_knowledge',
                          'reviewing', ?, ?, ?, ?, 'v5.1', ?, ?)
                """,
                (flow_id, step_id, self.graph_lineage, TEST_BANK_VERSION, session_id, now, now),
            )
            conn.execute(
                """
                insert into flow_steps(
                  id, flow_id, step_handle, position, step_type, status,
                  graph_version, node_id, question_bank_version, question_id,
                  question_item_version, review_record_id, answer_contract_id,
                  answer_contract_version, answer_contract_digest_sha256,
                  created_at, updated_at
                ) values (?, ?, ?, 1, 'question', 'completed', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    step_id,
                    flow_id,
                    f"step-{asset['question_id']}",
                    self.graph_lineage,
                    asset["node_id"],
                    TEST_BANK_VERSION,
                    asset["question_id"],
                    asset["item_version"],
                    asset["review_record_id"],
                    asset["contract_id"],
                    asset["contract_digest_sha256"],
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                insert into attempts(
                  id, session_id, question_id, node_id, result, grading_status,
                  evidence_status, score_points, max_points, error_tags_json,
                  answer_raw, parent_note, answer_analysis_json, review_meta_json,
                  flow_step_id, graph_version, question_bank_version,
                  attempt_version, analysis_version, analysis_status,
                  client_idempotency_key, answer_source, evidence_digest_sha256,
                  review_record_id, created_at
                ) values (?, ?, ?, ?, 'partial', 'graded', 'active', 1.6, 2,
                          '[]', '过程答案', '', '{}', '{}', ?, ?, ?, 1, 1,
                          'valid', ?, 'v3_text', ?, ?, ?)
                """,
                (
                    attempt_id,
                    session_id,
                    asset["question_id"],
                    asset["node_id"],
                    step_id,
                    self.graph_lineage,
                    TEST_BANK_VERSION,
                    f"attempt-key-{asset['question_id']}",
                    _canonical_sha256({"attempt_id": attempt_id}),
                    asset["review_record_id"],
                    now,
                ),
            )
            conn.execute("update flow_steps set attempt_id = ? where id = ?", (attempt_id, step_id))
            conn.execute(
                """
                insert into attempt_assessments(
                  id, attempt_id, attempt_version, assessment_version,
                  assessment_digest_sha256, assessment_input_digest_sha256,
                  question_id, question_item_version, answer_contract_id,
                  answer_contract_version, answer_contract_digest_sha256,
                  criterion_judgments_json, score_out_of_10, question_passed,
                  reference_answer_json, improvement_direction_json,
                  trust_label, provider_mode, answer_analysis_agent_run_id,
                  status, accepted_at, created_at, updated_at
                ) values (?, ?, 1, 1, ?, ?, ?, ?, ?, 1, ?, '[]', 8, 1,
                          '{}', '[]', 'accepted', 'live_model', ?, 'accepted', ?, ?, ?)
                """,
                (
                    assessment_id,
                    attempt_id,
                    assessment_digest,
                    _canonical_sha256({"attempt_id": attempt_id, "input": True}),
                    asset["question_id"],
                    asset["item_version"],
                    asset["contract_id"],
                    asset["contract_digest_sha256"],
                    answer_run["id"],
                    now,
                    now,
                    now,
                ),
            )
            predicate = {"usable": True, "projection_status": "usable", "failed_fields": [], "report_label": "confirmed"}
            conn.execute(
                """
                insert into evidence_validations(
                  id, attempt_id, attempt_version, analysis_version,
                  graph_version, node_id, question_id, question_bank_version,
                  gate_version, gate_status, failed_fields_json,
                  predicate_result_json, answer_analysis_agent_run_id,
                  provider_mode, assessment_id, assessment_version,
                  assessment_digest_sha256, created_at, updated_at
                ) values (?, ?, 1, 1, ?, ?, ?, ?, 'kv51-test-gate', 'passed',
                          '[]', ?, ?, 'live_model', ?, 1, ?, ?, ?)
                """,
                (
                    validation_id,
                    attempt_id,
                    self.graph_lineage,
                    asset["node_id"],
                    asset["question_id"],
                    TEST_BANK_VERSION,
                    db.json_dump(predicate),
                    answer_run["id"],
                    assessment_id,
                    assessment_digest,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                insert into mastery_decisions(
                  id, session_id, node_id, decision, closure_result,
                  evidence_attempt_ids_json, agent_run_id, applied, reason,
                  decision_payload_json, graph_version, question_bank_version,
                  source_attempt_ids_json, source_evidence_validation_ids_json,
                  evaluation_agent_run_id, decision_version, new_status_code,
                  dimension_scores_json, source_evidence_validation_hash,
                  created_at
                ) values (?, ?, ?, 'basic_understanding', 'repaired_not_mastered',
                          ?, ?, 1, 'accepted assessment evidence', '{}', ?, ?, ?, ?, ?, 1, ?, '{}', ?, ?)
                """,
                (
                    mastery_id,
                    session_id,
                    asset["node_id"],
                    db.json_dump([attempt_id]),
                    evaluation_run["id"],
                    self.graph_lineage,
                    TEST_BANK_VERSION,
                    db.json_dump([attempt_id]),
                    db.json_dump([validation_id]),
                    evaluation_run["id"],
                    status_code,
                    _canonical_sha256({"validation_id": validation_id}),
                    now,
                ),
            )
            conn.execute(
                """
                insert or replace into learner_node_status(
                  node_id, status_code, latest_score, can_explain,
                  evidence_attempt_ids_json, status_reason, graph_version,
                  question_bank_version, mastery_decision_id,
                  source_attempt_ids_json, source_evidence_validation_ids_json,
                  updated_by_agent_run_id, status_revision, updated_at
                ) values (?, ?, 0.8, 1, ?, 'authoritative mastery', ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    asset["node_id"],
                    status_code,
                    db.json_dump([attempt_id]),
                    self.graph_lineage,
                    TEST_BANK_VERSION,
                    mastery_id,
                    db.json_dump([attempt_id]),
                    db.json_dump([validation_id]),
                    evaluation_run["id"],
                    now,
                ),
            )
        return {
            "attempt_id": attempt_id,
            "assessment_id": assessment_id,
            "validation_id": validation_id,
            "mastery_id": mastery_id,
            "flow_id": flow_id,
            "step_id": step_id,
        }

    def _load_validated_config(self):
        module = self._require_module("learning_system.knowledge_view_config")
        config_type = getattr(module, "KnowledgeViewConfig", None)
        self.assertIsNotNone(config_type, "KnowledgeViewConfig production API is missing")
        loader = getattr(config_type, "load_validated", None)
        self.assertIsNotNone(loader, "KnowledgeViewConfig.load_validated public API is missing")
        snapshot_method = getattr(GraphRuntimeService(project_root=PROJECT_ROOT), "graph_snapshot", None)
        self.assertIsNotNone(snapshot_method, "GraphRuntimeService.graph_snapshot is missing")
        snapshot = snapshot_method()
        loaded = loader(VIEW_CONFIG_PATH, snapshot)
        if isinstance(loaded, tuple):
            self.assertEqual(2, len(loaded), "load_validated tuple must be (config, report)")
            config, report = loaded
        else:
            config = loaded
            report = getattr(config, "validation_report", None)
        self.assertIsInstance(report, dict, "validated loader must expose an audit report")
        return config, report, snapshot

    def _service(self, conn: sqlite3.Connection):
        module = self._require_module("learning_system.knowledge_map")
        service_type = getattr(module, "KnowledgeMapService", None)
        self.assertIsNotNone(service_type, "KnowledgeMapService production API is missing")
        parameters = inspect.signature(service_type).parameters
        kwargs = {}
        positional = []
        if "conn" in parameters:
            kwargs["conn"] = conn
        else:
            positional.append(conn)
        if "project_root" in parameters:
            kwargs["project_root"] = PROJECT_ROOT
        unexpected_test_authority = {
            "answer_assessment_active",
            "assessment_active",
            "policy_enabled",
            "activation_ready",
        } & set(parameters)
        self.assertFalse(
            unexpected_test_authority,
            f"caller-controlled activation authority is forbidden: {sorted(unexpected_test_authority)}",
        )
        try:
            return service_type(*positional, **kwargs)
        except TypeError as exc:
            self.fail(f"KnowledgeMapService constructor does not match the public contract: {exc}")

    def _projection_for_conn(self, conn: sqlite3.Connection) -> dict:
        service = self._service(conn)
        method = getattr(service, "child_projection", None)
        self.assertIsNotNone(method, "KnowledgeMapService.child_projection is missing")
        parameters = inspect.signature(method).parameters
        forbidden = {
            "answer_assessment_active",
            "assessment_active",
            "policy_enabled",
            "activation_ready",
        } & set(parameters)
        self.assertFalse(forbidden, f"child projection accepts caller authorization: {sorted(forbidden)}")
        kwargs = {}
        if "child_key" in parameters:
            kwargs["child_key"] = "single-child"
        if "current_learning" in parameters:
            kwargs["current_learning"] = {}
        try:
            return method(**kwargs)
        except TypeError as exc:
            self.fail(f"child_projection does not match the public contract: {exc}")

    def _database_snapshot(self, path: Path) -> dict:
        with closing(db.connect(path)) as conn:
            tables = [
                row["name"]
                for row in conn.execute(
                    "select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name"
                ).fetchall()
            ]
            return {
                "counts": {
                    table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                    for table in tables
                },
                "system_meta": [
                    tuple(row)
                    for row in conn.execute(
                        "select key, value, updated_at from system_meta order by key"
                    ).fetchall()
                ],
            }

    def _request_json(self, base_url: str, path: str) -> tuple[int, dict]:
        request = urllib.request.Request(base_url + path, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _assert_child_safe_keys(self, value, path="$"):
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).casefold()
                self.assertNotIn(lowered, CHILD_FORBIDDEN_KEYS, f"internal key leaked at {path}.{key}")
                self.assertFalse(
                    lowered.endswith("_id") or lowered.endswith("_ids"),
                    f"raw identifier-shaped key leaked at {path}.{key}",
                )
                self._assert_child_safe_keys(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self._assert_child_safe_keys(item, f"{path}[{index}]")

    def _assert_projection_matches_config(self, payload: dict, config: dict) -> None:
        self.assertEqual(EXPECTED_PROJECTION_KEYS, set(payload))
        self.assertEqual("5.1-knowledge-views", payload["schema_version"])
        self.assertEqual("mind_map", payload["default_view"])
        self.assertEqual({"mind_map"}, set(payload["views"]))
        self.assertEqual(55, len(payload["nodes"]))
        self.assertEqual(8, len(payload["modules"]))
        self.assertEqual(95, len(payload["relationships"]))

        node_names = [str(node["name"]) for node in payload["nodes"]]
        self.assertEqual(len(node_names), len(set(node_names)), "node names must identify exact projection rows")
        expected_node_names = {
            str(self.nodes[node_id]["name"])
            for node_id in self.child_visible_node_ids
        }
        self.assertEqual(expected_node_names, set(node_names))
        node_handle_by_id = {
            node_id: next(row["handle"] for row in payload["nodes"] if row["name"] == node["name"])
            for node_id, node in self.nodes.items()
            if node_id in self.child_visible_node_ids
        }

        module_names = [str(module["name"]) for module in payload["modules"]]
        self.assertEqual(len(module_names), len(set(module_names)))
        self.assertEqual(EXPECTED_CHILD_MODULE_ORDER, module_names)
        self.assertEqual(
            {self.module_names[module_id] for module_id in self.child_visible_module_ids},
            set(module_names),
        )
        module_handle_by_id = {
            module_id: next(
                row["handle"] for row in payload["modules"] if row["name"] == module_name
            )
            for module_id, module_name in self.module_names.items()
            if module_id in self.child_visible_module_ids
        }

        expected_relationships = {
            (node_handle_by_id[source], node_handle_by_id[target], "hard_prerequisite")
            for source, target in self.strict_edges
            if source in self.child_visible_node_ids and target in self.child_visible_node_ids
        }
        actual_relationships = {
            (row["source_handle"], row["target_handle"], row["relation"])
            for row in payload["relationships"]
        }
        self.assertEqual(expected_relationships, actual_relationships)

        mind_rows = {row["handle"]: row for row in payload["views"]["mind_map"]["placements"]}
        self.assertEqual(set(node_handle_by_id.values()), set(mind_rows))
        represented_edges = set()
        for node_id, placement in config["mind_map"]["nodes"].items():
            if node_id not in self.child_visible_node_ids:
                continue
            row = mind_rows[node_handle_by_id[node_id]]
            parent = placement["primary_parent"]
            expected_parent_handle = (
                module_handle_by_id[parent["id"]]
                if parent["type"] == "module"
                else node_handle_by_id[parent["id"]]
            )
            self.assertEqual(expected_parent_handle, row["parent_handle"])
            self.assertEqual(parent["type"], row["parent_type"])
            self.assertEqual(placement["order"], row["order"])
            self.assertEqual(placement["collapsed_by_default"], row["collapsed_by_default"])
            if parent["type"] == "node":
                represented_edges.add((parent["id"], node_id))

        expected_cross_links = {
            (node_handle_by_id[source], node_handle_by_id[target])
            for source, target in self.strict_edges - represented_edges
            if source in self.child_visible_node_ids and target in self.child_visible_node_ids
        }
        actual_cross_links = _edge_set(payload["views"]["mind_map"]["cross_links"])
        self.assertEqual(expected_cross_links, actual_cross_links)


class KnowledgeViewConfigTests(KnowledgeViewsV51TestCase):
    def test_authoritative_graph_oracle_is_56_nodes_9_modules_95_strict_edges(self):
        self.assertEqual(56, len(self.node_ids))
        self.assertEqual(9, len(self.module_ids))
        self.assertEqual(95, len(self.strict_edges))
        self.assertEqual(35, len(self.unlock_only_edges))

    def test_public_validated_loader_and_config_match_every_authoritative_set(self):
        config_json = self._load_view_config_json()
        module_order = config_json["root"]["module_order"]
        edge_keys = {f"{source}->{target}" for source, target in self.strict_edges}
        self.assertEqual(9, len(module_order))
        self.assertEqual(9, len(set(module_order)), "module_order contains duplicates")
        self.assertEqual(self.module_ids, set(module_order))
        self.assertEqual("knowledge-views.v1", config_json["schema_version"])
        self.assertEqual("2026-07-14.v5.1", config_json["config_version"])
        self.assertEqual(self.graph_lineage, config_json["graph_lineage"])
        self.assertEqual(self.module_ids, set(config_json["mind_map"]["modules"]))
        self.assertEqual(self.node_ids, set(config_json["mind_map"]["nodes"]))
        self.assertEqual(self.node_ids, set(config_json["graph"]["nodes"]))
        self.assertEqual(edge_keys, set(config_json["graph"]["overview_edge_visibility"]))

        config, report, _snapshot = self._load_validated_config()
        self.assertTrue(report.get("valid"), report)
        self.assertEqual([], report.get("errors", []), report)
        self.assertEqual(56, report.get("node_count"), report)
        self.assertEqual(9, report.get("module_count"), report)
        self.assertEqual(95, report.get("strict_edge_count"), report)
        self.assertEqual(95, report.get("graph_visibility_count"), report)
        self.assertEqual(_canonical_sha256(config_json), config.canonical_sha256())

    def test_mind_map_compares_every_primary_placement_and_cross_link(self):
        config = self._load_view_config_json()
        placements = config["mind_map"]["nodes"]
        represented_edges = set()
        sibling_orders = defaultdict(set)
        for node_id in sorted(self.node_ids):
            placement = placements[node_id]
            parent = placement["primary_parent"]
            parent_type = parent["type"]
            parent_id = str(parent["id"])
            self.assertIn(parent_type, {"module", "node"})
            self.assertIsInstance(placement["order"], int)
            self.assertIsInstance(placement["collapsed_by_default"], bool)
            sibling_key = (parent_type, parent_id)
            self.assertNotIn(placement["order"], sibling_orders[sibling_key])
            sibling_orders[sibling_key].add(placement["order"])
            if parent_type == "module":
                self.assertEqual(self.nodes[node_id]["taxonomy"]["module_id"], parent_id)
            else:
                self.assertIn((parent_id, node_id), self.strict_edges)
                represented_edges.add((parent_id, node_id))

        for start in sorted(self.node_ids):
            current = start
            seen = set()
            while True:
                self.assertNotIn(current, seen, f"mind-map parent cycle from {start}")
                seen.add(current)
                parent = placements[current]["primary_parent"]
                if parent["type"] == "module":
                    self.assertIn(parent["id"], self.module_ids)
                    break
                current = parent["id"]
                self.assertIn(current, placements)

        config_object, report, _snapshot = self._load_validated_config()
        raw_cross_links = config_object.mind_map_cross_links(self.strict_edges)
        cross_links = _edge_set(raw_cross_links)
        self.assertEqual(len(raw_cross_links), len(cross_links), "cross-links must be unique")
        self.assertEqual(self.strict_edges - represented_edges, cross_links)
        self.assertEqual(self.strict_edges, represented_edges | cross_links)
        self.assertFalse(represented_edges & cross_links)
        self.assertEqual(len(cross_links), report.get("mind_map_cross_link_count"), report)

    def test_graph_compares_every_rank_lane_order_and_strict_edge_direction(self):
        config = self._load_view_config_json()
        lane_ids = [str(lane["id"]) for lane in config["graph"]["lanes"]]
        self.assertEqual(len(lane_ids), len(set(lane_ids)))
        placements = config["graph"]["nodes"]
        bucket_orders = defaultdict(set)
        for node_id in sorted(self.node_ids):
            placement = placements[node_id]
            self.assertIsInstance(placement["rank"], int)
            self.assertIn(placement["lane"], lane_ids)
            self.assertIsInstance(placement["order"], int)
            bucket = (placement["lane"], placement["rank"])
            self.assertNotIn(placement["order"], bucket_orders[bucket])
            bucket_orders[bucket].add(placement["order"])

        visibility = config["graph"]["overview_edge_visibility"]
        for source, target in sorted(self.strict_edges):
            self.assertLess(
                placements[source]["rank"],
                placements[target]["rank"],
                f"strict prerequisite must point from lower to higher rank: {source}->{target}",
            )
            self.assertIsInstance(visibility[f"{source}->{target}"], bool)
        for source, target in sorted(self.unlock_only_edges):
            self.assertNotIn(f"{source}->{target}", visibility)

    def test_graph_runtime_snapshot_matches_every_internal_edge(self):
        service = GraphRuntimeService(project_root=PROJECT_ROOT)
        method = getattr(service, "graph_snapshot", None)
        self.assertIsNotNone(method, "GraphRuntimeService.graph_snapshot is missing")
        snapshot = method()
        self.assertEqual(self.graph_lineage, snapshot["graph_lineage"])
        self.assertEqual(self.module_ids, set(snapshot["modules"]))
        self.assertEqual(self.node_ids, set(snapshot["nodes"]))
        self.assertEqual(self.strict_edges, _edge_set(snapshot["strict_prerequisites"]))
        self.assertEqual(self.unlock_only_edges, _edge_set(snapshot["unlock_only_candidates"]))


class KnowledgeMapProjectionTests(KnowledgeViewsV51TestCase):
    def test_projection_matches_every_config_placement_edge_and_opaque_handle(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                self._install_view_activation(conn, config_payload=config)
                payload = self._projection_for_conn(conn)
            self._assert_projection_matches_config(payload, config)
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            self.assertLessEqual(len(serialized.encode("utf-8")), 250 * 1024)
            for node_id in self.node_ids:
                self.assertNotIn(node_id, serialized, f"canonical node id leaked: {node_id}")
            self.assertNotIn(HANDLE_SECRET_ONE, serialized)
            self._assert_child_safe_keys(payload)

    def test_hmac_handles_are_secret_backed_stable_domain_separated_and_installation_scoped(self):
        config = self._load_view_config_json()
        with self._temp_database() as first_path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(first_path)) as conn:
                self._install_view_activation(conn, config_payload=config, secret=HANDLE_SECRET_ONE)
                first = self._projection_for_conn(conn)
            with closing(db.connect(first_path)) as restarted:
                second = self._projection_for_conn(restarted)
                stored_secret = restarted.execute(
                    "select value from system_meta where key = ?", (HANDLE_SECRET_KEY,)
                ).fetchone()["value"]
            self.assertEqual(HANDLE_SECRET_ONE, stored_secret)

        with self._temp_database() as other_path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(other_path)) as conn:
                self._install_view_activation(conn, config_payload=config, secret=HANDLE_SECRET_TWO)
                other = self._projection_for_conn(conn)

        first_nodes = {row["handle"] for row in first["nodes"]}
        second_nodes = {row["handle"] for row in second["nodes"]}
        other_nodes = {row["handle"] for row in other["nodes"]}
        module_handles = {row["handle"] for row in first["modules"]}
        self.assertEqual(first_nodes, second_nodes, "same receipt and secret must survive restart")
        self.assertTrue(first_nodes.isdisjoint(other_nodes), "different installations reused node handles")
        self.assertTrue(first_nodes.isdisjoint(module_handles))
        prefixes = {
            "node": {handle.split(".", 1)[0] for handle in first_nodes},
            "module": {handle.split(".", 1)[0] for handle in module_handles},
        }
        self.assertTrue(prefixes["node"].isdisjoint(prefixes["module"]))
        serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(HANDLE_SECRET_ONE, serialized)
        self.assertNotIn(HANDLE_SECRET_TWO, serialized)

    def test_mastery_projection_requires_current_accepted_assessment_and_authoritative_decision(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                assets = self._install_view_activation(conn, config_payload=config)
                lineage = self._install_authoritative_mastery(conn, assets[0])
                payload = self._projection_for_conn(conn)
                row = next(item for item in payload["nodes"] if item["name"] == self.nodes[assets[0]["node_id"]]["name"])
                self.assertEqual("developing", row["mastery_band"])

                conn.execute(
                    "update attempt_assessments set status = 'superseded' where id = ?",
                    (lineage["assessment_id"],),
                )
                conn.commit()
                stale = self._projection_for_conn(conn)
                stale_row = next(item for item in stale["nodes"] if item["name"] == row["name"])
                self.assertEqual("untested", stale_row["mastery_band"])
                self.assertEqual("还没有留下学习记录", stale_row["mastery_summary"])

    def test_mastery_projection_does_not_depend_on_a_hard_coded_live_provider_label(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                assets = self._install_view_activation(conn, config_payload=config)
                self._install_authoritative_mastery(
                    conn,
                    assets[0],
                    answer_model_provider="gpt",
                )
                payload = self._projection_for_conn(conn)

        row = next(
            item
            for item in payload["nodes"]
            if item["name"] == self.nodes[assets[0]["node_id"]]["name"]
        )
        self.assertEqual("developing", row["mastery_band"])
        self.assertNotEqual("还没有留下学习记录", row["mastery_summary"])

    def test_projection_exposes_child_evidence_actions_and_learning_path_order(self):
        config = self._load_view_config_json()
        selected_node_ids = sorted(self.child_visible_node_ids)[:2]
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                assets = self._install_view_activation(
                    conn,
                    config_payload=config,
                    assessment_node_ids=selected_node_ids,
                )
                stable_lineage = self._install_authoritative_mastery(
                    conn, assets[0], status_code="A"
                )
                conn.execute(
                    "update daily_flows set local_date = '2026-07-14' where id = ?",
                    (stable_lineage["flow_id"],),
                )
                conn.commit()
                self._install_authoritative_mastery(conn, assets[1], status_code="D")
                payload = self._projection_for_conn(conn)

        for node in payload["nodes"]:
            self.assertIn(node["evidence_state"]["code"], {
                "untested", "developing", "needs_support", "stable"
            })
            self.assertEqual(4, node["activity"]["total"])
            self.assertIn(node["activity"]["completed"], range(5))
            self.assertIn(
                f'{node["activity"]["completed"]}/4',
                node["activity"]["label"],
            )
            self.assertTrue(node["mastery_summary"])
            self.assertIn(node["action_readiness"]["code"], {
                "ready", "needs_prerequisite", "content_unavailable",
                "assessment_unavailable", "wait_for_current",
            })
            self.assertTrue(node["action_descriptors"])
            self.assertLessEqual(
                sum(item["role"] == "primary" for item in node["action_descriptors"]),
                1,
            )
            self.assertLessEqual(
                sum(
                    item["role"] == "secondary" and item["enabled"]
                    for item in node["action_descriptors"]
                ),
                1,
            )
            for descriptor in node["action_descriptors"]:
                self.assertTrue(descriptor["label"])
                self.assertTrue(descriptor["pending_label"])
                self.assertIn(
                    descriptor["result_behavior"],
                    {"enter_now", "wait_for_safe_boundary", "preview"},
                )
                if not descriptor["enabled"]:
                    self.assertTrue(descriptor["disabled_reason"])
            self.assertEqual(
                [item["action"] for item in node["action_descriptors"] if item["enabled"]],
                node["allowed_actions"],
            )

        stable = next(
            node for node in payload["nodes"]
            if node["name"] == self.nodes[assets[0]["node_id"]]["name"]
        )
        self.assertEqual({"code": "stable", "label": "暂时掌握"}, stable["evidence_state"])
        self.assertEqual(["挑战一下", "复习这个点"], [
            item["label"] for item in stable["action_descriptors"]
        ])

        prerequisite = next(
            node for node in payload["nodes"]
            if node["name"] == self.nodes[assets[1]["node_id"]]["name"]
        )
        self.assertEqual("needs_support", prerequisite["evidence_state"]["code"])
        self.assertEqual("needs_prerequisite", prerequisite["action_readiness"]["code"])
        self.assertEqual("先补准备知识", prerequisite["action_descriptors"][0]["label"])

        self.assertEqual(
            EXPECTED_CHILD_MODULE_ORDER,
            [module["name"] for module in payload["modules"]],
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("学习流程与错因", serialized)
        self.assertNotIn("解题步骤与检验习惯", serialized)
        self.assertNotIn("graph", payload["views"])

    def test_projection_exposes_child_safe_learning_card_summary_for_active_card_nodes(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                self._install_view_activation(conn, config_payload=config)
                payload = self._projection_for_conn(conn)

        number_line = next(node for node in payload["nodes"] if node["name"] == "数轴")
        card = number_line["learning_card"]
        self.assertIsInstance(card, dict)
        self.assertTrue(card["available"])
        self.assertEqual("数轴", card["title"])
        self.assertIn("数轴把数变成位置", card["one_sentence"])
        self.assertIn("数轴演示", card["forms"])
        self.assertTrue(card["has_interaction"])
        self._assert_child_safe_keys(card)

    def test_tampered_contract_review_lineage_blocks_db_audited_activation(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                assets = self._install_view_activation(conn, config_payload=config)
                ready = self._projection_for_conn(conn)
                asset_node = next(item for item in ready["nodes"] if item["name"] == self.nodes[assets[0]["node_id"]]["name"])
                self.assertTrue(asset_node["allowed_actions"])
                conn.execute(
                    "update agent_runs set status = 'rejected' where id = ?",
                    (assets[0]["review_run_id"],),
                )
                conn.commit()
                with self.assertRaisesRegex(ValueError, "评估|assessment|激活|凭据|准备") as raised:
                    self._projection_for_conn(conn)
                self.assertEqual(409, getattr(raised.exception, "status", None))


class KnowledgeMapServerGateTests(KnowledgeViewsV51TestCase):
    def _server_gate(self, path: Path, *, map_policy: str, assessment_policy: str):
        before = self._database_snapshot(path)
        with self._policy_env(map_policy=map_policy, assessment_policy=assessment_policy):
            httpd, base_url = server.start_test_server(path)
            try:
                status, payload = self._request_json(base_url, "/api/knowledge-map")
            finally:
                httpd.shutdown()
                httpd.server_close()
        after = self._database_snapshot(path)
        self.assertEqual(before, after, "knowledge-map gate GET mutated isolated DB state")
        self._assert_child_safe_keys(payload)
        return status, payload

    def test_server_policy_off_returns_map_specific_404_with_zero_writes(self):
        with self._temp_database() as path:
            status, payload = self._server_gate(
                path, map_policy="off", assessment_policy="off"
            )
        self.assertEqual(404, status)
        self.assertNotEqual({"error": "Not found"}, payload, "route is missing rather than policy-gated")
        self.assertNotIn("allowed_actions", json.dumps(payload, ensure_ascii=False))

    def test_server_assessment_not_activated_returns_409_and_no_learning_actions_or_writes(self):
        with self._temp_database() as path:
            status, payload = self._server_gate(
                path, map_policy="v5.1", assessment_policy="off"
            )
        self.assertEqual(409, status)
        serialized = json.dumps(payload, ensure_ascii=False)
        for action in MUTATING_ACTIONS:
            self.assertNotIn(action, serialized)

    def test_server_flag_on_without_db_audited_assessment_returns_409(self):
        config = self._load_view_config_json()
        with self._temp_database() as path:
            with closing(db.connect(path)) as conn:
                self._install_view_activation(
                    conn,
                    config_payload=config,
                    assessment_active=False,
                )
            status, payload = self._server_gate(
                path, map_policy="v5.1", assessment_policy="v5.1"
            )
        self.assertEqual(409, status)
        self.assertEqual("assessment_unavailable", payload.get("state"))

    def test_server_invalid_activated_config_returns_503_with_zero_writes(self):
        invalid_config = json.loads(INVALID_CONFIG_FIXTURE.read_text(encoding="utf-8"))
        with self._temp_database() as path:
            with closing(db.connect(path)) as conn:
                self._install_view_activation(
                    conn,
                    config_payload=invalid_config,
                    relative_path="tests/fixtures/knowledge_views_v51_invalid_config.json",
                )
            status, _payload = self._server_gate(
                path, map_policy="v5.1", assessment_policy="v5.1"
            )
        self.assertEqual(503, status)


class TargetIntentTests(KnowledgeViewsV51TestCase):
    def _knowledge_map_module(self):
        return self._require_module("learning_system.knowledge_map")

    def _create_kwargs(self, *, key: str, node_id: str | None = None, action: str = "diagnostic"):
        return {
            "child_key": "single-child",
            "graph_version": self.graph_lineage,
            "node_id": node_id or sorted(self.node_ids)[0],
            "action": action,
            "client_idempotency_key": key,
        }

    def test_target_intent_schema_enforces_db_authority_and_excludes_presentation_state(self):
        with self._temp_database() as path, closing(db.connect(path)) as conn:
            table_names = {
                row["name"]
                for row in conn.execute("select name from sqlite_master where type = 'table'").fetchall()
            }
            self.assertIn("learning_target_intents", table_names)
            columns = {
                row["name"]
                for row in conn.execute("pragma table_info(learning_target_intents)").fetchall()
            }
            required = {
                "id",
                "child_key",
                "graph_version",
                "node_id",
                "action",
                "status",
                "source_flow_id",
                "source_flow_revision",
                "source_step_id",
                "client_idempotency_key",
                "payload_digest_sha256",
                "applied_flow_id",
                "applied_step_id",
                "reason",
                "created_at",
                "updated_at",
            }
            self.assertTrue(required.issubset(columns))
            self.assertFalse(
                columns
                & {
                    "view",
                    "active_view",
                    "viewport",
                    "collapse_state",
                    "rank",
                    "lane",
                    "display_parent",
                    "handle",
                }
            )

            index_rows = conn.execute("pragma index_list(learning_target_intents)").fetchall()
            unique_shapes = []
            for index in index_rows:
                if not index["unique"]:
                    continue
                name = index["name"]
                cols = [
                    row["name"] for row in conn.execute(f"pragma index_info('{name}')").fetchall()
                ]
                sql_row = conn.execute(
                    "select sql from sqlite_master where type = 'index' and name = ?", (name,)
                ).fetchone()
                unique_shapes.append((cols, str(sql_row["sql"] or "").casefold() if sql_row else ""))
            self.assertTrue(
                any(
                    cols == ["child_key", "graph_version", "client_idempotency_key"]
                    for cols, _sql in unique_shapes
                ),
                "DB idempotency uniqueness is missing",
            )
            self.assertTrue(
                any(
                    cols == ["child_key", "graph_version"]
                    and "pending" in sql
                    and "waiting_for_safe_boundary" in sql
                    for cols, sql in unique_shapes
                ),
                "DB one-nonterminal-intent authority is missing",
            )

    def test_two_connections_compete_on_one_idempotency_key_and_return_one_canonical_row(self):
        module = self._knowledge_map_module()
        create = getattr(module, "create_target_intent", None)
        self.assertIsNotNone(create, "create_target_intent production API is missing")
        kwargs = self._create_kwargs(key="race-key")
        with self._temp_database() as path:
            barrier = threading.Barrier(2)

            def worker():
                conn = db.connect(path)
                try:
                    barrier.wait(timeout=3)
                    return ("ok", _row_id(create(conn, **kwargs)))
                except Exception as exc:  # captured so the assertion reports the concurrency defect
                    return ("error", f"{type(exc).__name__}:{exc}")
                finally:
                    conn.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result(timeout=8) for future in [pool.submit(worker), pool.submit(worker)]]
            errors = [value for status, value in results if status == "error"]
            self.assertEqual([], errors, f"concurrent retry leaked lock/unique errors: {errors}")
            ids = [value for status, value in results if status == "ok"]
            self.assertEqual(1, len(set(ids)), results)
            with closing(db.connect(path)) as conn:
                rows = conn.execute("select * from learning_target_intents").fetchall()
                self.assertEqual(1, len(rows))
                self.assertEqual(ids[0], rows[0]["id"])
                expected_digest = hashlib.sha256(
                    json.dumps(
                        {"node_id": kwargs["node_id"], "action": kwargs["action"]},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                self.assertEqual(expected_digest, rows[0]["payload_digest_sha256"])

    def test_pending_intent_survives_restart_and_conflicting_key_reuse_is_rejected(self):
        module = self._knowledge_map_module()
        create = getattr(module, "create_target_intent", None)
        newest = getattr(module, "newest_pending_intent", None)
        self.assertIsNotNone(create, "create_target_intent production API is missing")
        self.assertIsNotNone(newest, "newest_pending_intent production API is missing")
        kwargs = self._create_kwargs(key="restart-key")
        with self._temp_database() as path:
            with closing(db.connect(path)) as first_conn:
                created = create(first_conn, **kwargs)
                created_id = _row_id(created)
            with closing(db.connect(path)) as restarted_conn:
                recovered = newest(
                    restarted_conn,
                    child_key=kwargs["child_key"],
                    graph_version=kwargs["graph_version"],
                )
                self.assertEqual(created_id, _row_id(recovered))
                with self.assertRaises((ValueError, sqlite3.IntegrityError)):
                    create(restarted_conn, **{**kwargs, "action": "learn"})
                self.assertEqual(
                    1,
                    restarted_conn.execute("select count(*) from learning_target_intents").fetchone()[0],
                )

    def test_tampered_handle_and_stale_projection_or_receipt_fail_before_db_intent(self):
        module = self._knowledge_map_module()
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                self._install_view_activation(conn, config_payload=config)
                service = self._service(conn)
                payload = self._projection_for_conn(conn)
                select = getattr(service, "select_target", None)
                self.assertIsNotNone(select, "KnowledgeMapService.select_target is missing")
                valid_handle = payload["nodes"][0]["handle"]
                tampered_handle = valid_handle[:-1] + ("0" if valid_handle[-1] != "0" else "1")

                def reject(request):
                    try:
                        parameters = inspect.signature(select).parameters
                        if "request" in parameters:
                            result = select(child_key="single-child", request=request)
                        else:
                            result = select(child_key="single-child", **request)
                    except (ValueError, LookupError, sqlite3.IntegrityError):
                        return
                    self.assertIsInstance(result, dict)
                    self.assertIn(result.get("status"), {"blocked", "stale"})

                base = {
                    "handle": valid_handle,
                    "projection_version": payload["projection_version"],
                    "action": "diagnostic",
                    "client_idempotency_key": "invalid-handle-key",
                }
                reject({**base, "handle": tampered_handle})
                reject({**base, "projection_version": base["projection_version"] + ":stale"})
                conn.execute(
                    "update system_meta set value = ? where key = ?",
                    (db.json_dump({"lineage": self.graph_lineage + ":changed"}), "graph_ref"),
                )
                conn.commit()
                reject({**base, "client_idempotency_key": "stale-receipt-key"})
                self.assertEqual(
                    0,
                    conn.execute("select count(*) from learning_target_intents").fetchone()[0],
                )

    def test_prerequisite_not_ready_never_directly_applies_the_selected_target(self):
        self._knowledge_map_module()
        config = self._load_view_config_json()
        target = max(self.nodes, key=lambda node_id: len(self.nodes[node_id].get("prerequisites", [])))
        self.assertGreaterEqual(len(self.nodes[target]["prerequisites"]), 1)
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                self._install_view_activation(
                    conn,
                    config_payload=config,
                    assessment_node_ids=[target],
                )
                service = self._service(conn)
                payload = self._projection_for_conn(conn)
                target_row = next(
                    row for row in payload["nodes"]
                    if row["name"] == self.nodes[target]["name"]
                )
                target_handle = target_row["handle"]
                learn_descriptor = next(
                    item for item in target_row["action_descriptors"]
                    if item["action"] == "learn"
                )
                self.assertFalse(learn_descriptor["enabled"])
                self.assertTrue(learn_descriptor["disabled_reason"])
                select = getattr(service, "select_target", None)
                self.assertIsNotNone(select, "KnowledgeMapService.select_target is missing")
                request = {
                    "handle": target_handle,
                    "projection_version": payload["projection_version"],
                    "action": "learn",
                    "client_idempotency_key": "prerequisite-boundary-key",
                }
                with self.assertRaises(KnowledgeMapError) as raised:
                    parameters = inspect.signature(select).parameters
                    if "request" in parameters:
                        select(child_key="single-child", request=request)
                    else:
                        select(child_key="single-child", **request)
                self.assertEqual(409, raised.exception.status)
                row = conn.execute(
                    "select * from learning_target_intents where client_idempotency_key = ?",
                    (request["client_idempotency_key"],),
                ).fetchone()
                self.assertIsNone(row)

    def test_safe_boundary_reducer_application_is_restart_safe_and_exactly_once(self):
        module = self._knowledge_map_module()
        create = getattr(module, "create_target_intent", None)
        apply_at_boundary = getattr(module, "apply_intent_at_safe_boundary", None)
        self.assertIsNotNone(create, "create_target_intent production API is missing")
        self.assertIsNotNone(apply_at_boundary, "apply_intent_at_safe_boundary production API is missing")
        target = next(
            node_id
            for node_id in sorted(self.node_ids)
            if not self.nodes[node_id].get("prerequisites")
        )
        kwargs = self._create_kwargs(key="reducer-key", node_id=target, action="learn")
        with self._temp_database() as path:
            with closing(db.connect(path)) as conn:
                intent = create(conn, **kwargs)
                conn.execute(
                    """
                    insert into daily_flows(
                      id, child_key, local_date, mode, status, graph_version,
                      created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "FLOW-KV51",
                        "single-child",
                        "2026-07-15",
                        "new_knowledge",
                        "active",
                        self.graph_lineage,
                        "2026-07-15T00:00:00+08:00",
                        "2026-07-15T00:00:00+08:00",
                    ),
                )
                conn.execute(
                    """
                    insert into flow_steps(
                      id, flow_id, step_handle, position, step_type, status,
                      graph_version, node_id, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "STEP-KV51",
                        "FLOW-KV51",
                        "step-kv51",
                        1,
                        "new_knowledge",
                        "selected",
                        self.graph_lineage,
                        target,
                        "2026-07-15T00:00:00+08:00",
                        "2026-07-15T00:00:00+08:00",
                    ),
                )
                conn.commit()
                first = apply_at_boundary(
                    conn,
                    intent_id=_row_id(intent),
                    applied_flow_id="FLOW-KV51",
                    applied_step_id="STEP-KV51",
                )
            with closing(db.connect(path)) as restarted_conn:
                retry = apply_at_boundary(
                    restarted_conn,
                    intent_id=_row_id(intent),
                    applied_flow_id="FLOW-KV51",
                    applied_step_id="STEP-KV51",
                )
                row = restarted_conn.execute(
                    "select * from learning_target_intents where id = ?", (_row_id(intent),)
                ).fetchone()
                self.assertEqual("applied", row["status"])
                self.assertEqual("FLOW-KV51", row["applied_flow_id"])
                self.assertEqual("STEP-KV51", row["applied_step_id"])
                self.assertEqual(_row_id(first), _row_id(retry))
                self.assertEqual(
                    1,
                    restarted_conn.execute(
                        "select count(*) from learning_target_intents where status = 'applied'"
                    ).fetchone()[0],
                )
                self.assertEqual(
                    1,
                    restarted_conn.execute("select count(*) from flow_steps where id = 'STEP-KV51'").fetchone()[0],
                )


class KnowledgeTargetRuntimeIntegrationTests(KnowledgeViewsV51TestCase):
    def _request_for_asset(self, payload: dict, asset: dict, *, key: str, action: str = "diagnostic") -> dict:
        handle = next(
            row["handle"]
            for row in payload["nodes"]
            if row["name"] == self.nodes[asset["node_id"]]["name"]
        )
        return {
            "handle": handle,
            "projection_version": payload["projection_version"],
            "action": action,
            "client_idempotency_key": key,
        }

    def test_new_target_cancels_unconsumed_applied_plan_and_old_key_cannot_retake_control(self):
        from learning_system import daily_runtime

        config = self._load_view_config_json()
        node_ids = sorted(self.child_visible_node_ids)[:3]
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ), closing(db.connect(path)) as conn:
            assets = self._install_view_activation(
                conn,
                config_payload=config,
                assessment_node_ids=node_ids,
            )
            self._install_visual_activation(conn)
            service = self._service(conn)
            projection = self._projection_for_conn(conn)

            first_request = self._request_for_asset(
                projection,
                assets[0],
                key="target-replace-source",
            )
            self.assertEqual(
                "applied",
                service.select_target(child_key="single-child", request=first_request)["status"],
            )
            flow = conn.execute(
                "select * from daily_flows where local_date = ? order by created_at desc limit 1",
                (date.today().isoformat(),),
            ).fetchone()
            source_step_id = flow["current_step_id"]
            conn.execute(
                "update flow_steps set status = 'analyzing' where id = ?",
                (source_step_id,),
            )
            conn.commit()

            reserved_request = self._request_for_asset(
                projection,
                assets[1],
                key="target-replace-reserved",
            )
            self.assertEqual(
                "waiting_for_safe_boundary",
                service.select_target(child_key="single-child", request=reserved_request)["status"],
            )
            reserved_intent = conn.execute(
                "select * from learning_target_intents where client_idempotency_key = ?",
                (reserved_request["client_idempotency_key"],),
            ).fetchone()
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            planned = runtime._materialize_target_intent_locked(
                reserved_intent["id"],
                service._runtime_authority(),
                planned_position=2,
                preserve_current_step=True,
            )
            self.assertEqual("applied", planned["status"])
            planned_step_id = planned["step_id"]
            self.assertEqual(
                "planned",
                conn.execute(
                    "select status from flow_steps where id = ?",
                    (planned_step_id,),
                ).fetchone()["status"],
            )
            conn.execute(
                "update flow_steps set status = 'selected' where id = ?",
                (source_step_id,),
            )
            conn.commit()

            replacement_request = self._request_for_asset(
                projection,
                assets[2],
                key="target-replace-current",
            )
            replacement = service.select_target(
                child_key="single-child",
                request=replacement_request,
            )
            self.assertEqual("waiting_for_safe_boundary", replacement["status"])
            self.assertEqual(
                "cancelled",
                conn.execute(
                    "select status from learning_target_intents where id = ?",
                    (reserved_intent["id"],),
                ).fetchone()["status"],
            )
            self.assertEqual(
                "superseded",
                conn.execute(
                    "select status from flow_steps where id = ?",
                    (planned_step_id,),
                ).fetchone()["status"],
            )
            current_before_replay = conn.execute(
                "select current_step_id from daily_flows where id = ?",
                (flow["id"],),
            ).fetchone()["current_step_id"]
            self.assertEqual(source_step_id, current_before_replay)
            self.assertEqual(
                "selected",
                conn.execute(
                    "select status from flow_steps where id = ?",
                    (source_step_id,),
                ).fetchone()["status"],
            )
            with self.assertRaises(KnowledgeMapError) as replay_error:
                service.select_target(
                    child_key="single-child",
                    request=reserved_request,
                )
            self.assertEqual(409, replay_error.exception.status)
            self.assertEqual(
                current_before_replay,
                conn.execute(
                    "select current_step_id from daily_flows where id = ?",
                    (flow["id"],),
                ).fetchone()["current_step_id"],
            )

    def test_select_revalidates_inside_immediate_transaction_and_materializes_exactly_once(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ), closing(db.connect(path)) as conn:
            assets = self._install_view_activation(conn, config_payload=config)
            self._install_visual_activation(conn)
            service = self._service(conn)
            projection = self._projection_for_conn(conn)
            request = self._request_for_asset(projection, assets[0], key="materialize-once")
            original = service._runtime_authority

            def asserted_authority():
                self.assertTrue(conn.in_transaction, "selection authority was read before BEGIN IMMEDIATE")
                return original()

            with mock.patch.object(service, "_runtime_authority", side_effect=asserted_authority):
                first = service.select_target(child_key="single-child", request=request)
            self.assertEqual("applied", first["status"])
            intent = conn.execute(
                "select * from learning_target_intents where client_idempotency_key = ?",
                (request["client_idempotency_key"],),
            ).fetchone()
            self.assertEqual("applied", intent["status"])
            self.assertTrue(intent["applied_flow_id"])
            self.assertTrue(intent["applied_step_id"])
            step = conn.execute("select * from flow_steps where id = ?", (intent["applied_step_id"],)).fetchone()
            self.assertEqual(assets[0]["contract_id"], step["answer_contract_id"])
            self.assertEqual(assets[0]["contract_digest_sha256"], step["answer_contract_digest_sha256"])
            selection_reason = db.json_load(step["selection_reason_json"], {})
            mini_group = selection_reason.get("mini_group")
            self.assertIsInstance(mini_group, dict)
            self.assertEqual("review_short_set", mini_group["role"])
            self.assertEqual(1, mini_group["index"])
            self.assertGreater(mini_group["size"], 1)
            self.assertTrue(mini_group["defer_analysis_until_group_end"])
            before = {
                "flows": conn.execute("select count(*) from daily_flows").fetchone()[0],
                "steps": conn.execute("select count(*) from flow_steps").fetchone()[0],
                "intents": conn.execute("select count(*) from learning_target_intents").fetchone()[0],
            }
            retried = service.select_target(child_key="single-child", request=request)
            after = {
                "flows": conn.execute("select count(*) from daily_flows").fetchone()[0],
                "steps": conn.execute("select count(*) from flow_steps").fetchone()[0],
                "intents": conn.execute("select count(*) from learning_target_intents").fetchone()[0],
            }
            self.assertEqual("applied", retried["status"])
            self.assertEqual(before, after)

    def test_same_target_with_new_idempotency_key_reuses_current_unanswered_step(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ), closing(db.connect(path)) as conn:
            assets = self._install_view_activation(conn, config_payload=config)
            self._install_visual_activation(conn)
            service = self._service(conn)

            first_projection = self._projection_for_conn(conn)
            first_request = self._request_for_asset(
                first_projection,
                assets[0],
                key="same-target-first-click",
            )
            first = service.select_target(child_key="single-child", request=first_request)
            self.assertEqual("applied", first["status"])

            second_projection = self._projection_for_conn(conn)
            second_request = self._request_for_asset(
                second_projection,
                assets[0],
                key="same-target-second-click",
            )
            second = service.select_target(child_key="single-child", request=second_request)
            self.assertEqual("applied", second["status"])

            rows = conn.execute(
                """
                select * from learning_target_intents
                where client_idempotency_key in (?, ?)
                order by client_idempotency_key
                """,
                (
                    first_request["client_idempotency_key"],
                    second_request["client_idempotency_key"],
                ),
            ).fetchall()
            self.assertEqual(2, len(rows))
            self.assertTrue(all(row["status"] == "applied" for row in rows))
            self.assertEqual(1, len({row["applied_flow_id"] for row in rows}))
            self.assertEqual(1, len({row["applied_step_id"] for row in rows}))
            self.assertEqual(
                1,
                conn.execute("select count(*) from daily_flows").fetchone()[0],
            )
            self.assertEqual(
                1,
                conn.execute("select count(*) from flow_steps").fetchone()[0],
            )

    def test_selecting_from_home_after_summary_starts_a_new_same_day_flow(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ), closing(db.connect(path)) as conn:
            assets = self._install_view_activation(conn, config_payload=config)
            self._install_visual_activation(conn)
            service = self._service(conn)

            first_projection = self._projection_for_conn(conn)
            first_request = self._request_for_asset(
                first_projection,
                assets[0],
                key="before-summary-selection",
            )
            first = service.select_target(child_key="single-child", request=first_request)
            self.assertEqual("applied", first["status"])
            first_intent = conn.execute(
                "select * from learning_target_intents where client_idempotency_key = ?",
                (first_request["client_idempotency_key"],),
            ).fetchone()
            conn.execute(
                "update flow_steps set status = 'completed' where id = ?",
                (first_intent["applied_step_id"],),
            )
            conn.execute(
                """
                update daily_flows
                set status = 'completed', current_step_id = null, updated_at = ?
                where id = ?
                """,
                (db.now_iso(), first_intent["applied_flow_id"]),
            )
            conn.commit()

            summary_projection = service.child_projection(child_key="single-child")
            self.assertEqual("summary", summary_projection["current_learning"]["state"])
            second_request = self._request_for_asset(
                summary_projection,
                assets[1],
                key="after-summary-selection",
            )
            second = service.select_target(child_key="single-child", request=second_request)
            self.assertEqual("applied", second["status"])

            second_intent = conn.execute(
                "select * from learning_target_intents where client_idempotency_key = ?",
                (second_request["client_idempotency_key"],),
            ).fetchone()
            self.assertNotEqual(first_intent["applied_flow_id"], second_intent["applied_flow_id"])
            self.assertNotEqual(first_intent["applied_step_id"], second_intent["applied_step_id"])
            current = service.child_projection(child_key="single-child")["current_learning"]
            self.assertEqual("current_step", current["state"])
            self.assertEqual(self.nodes[assets[1]["node_id"]]["name"], current["topic_label"])

    def test_enabled_descriptors_share_runtime_eligibility_and_fulfill_result_behavior(self):
        config = self._load_view_config_json()
        foundation = next(
            node_id for node_id in sorted(self.child_visible_node_ids)
            if not self.nodes[node_id].get("prerequisites")
        )
        blocked_target = max(
            self.child_visible_node_ids,
            key=lambda node_id: len(self.nodes[node_id].get("prerequisites", [])),
        )
        missing_asset = next(
            node_id for node_id in sorted(self.child_visible_node_ids)
            if node_id not in {foundation, blocked_target}
        )
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ), closing(db.connect(path)) as conn:
            assets = self._install_view_activation(
                conn,
                config_payload=config,
                assessment_node_ids=[foundation, foundation, blocked_target],
            )
            self._install_visual_activation(conn)
            asset_by_node = {asset["node_id"]: asset for asset in assets}
            service = self._service(conn)
            projection = self._projection_for_conn(conn)
            rows_by_name = {row["name"]: row for row in projection["nodes"]}

            blocked_row = rows_by_name[self.nodes[blocked_target]["name"]]
            blocked_learn = next(
                item for item in blocked_row["action_descriptors"]
                if item["action"] == "learn"
            )
            self.assertFalse(blocked_learn["enabled"])
            self.assertTrue(blocked_learn["disabled_reason"])
            blocked_request = self._request_for_asset(
                projection,
                asset_by_node[blocked_target],
                key="shared-eligibility-prerequisite",
                action="learn",
            )
            with self.assertRaises(KnowledgeMapError) as blocked_error:
                service.select_target(child_key="single-child", request=blocked_request)
            self.assertEqual(409, blocked_error.exception.status)

            missing_row = rows_by_name[self.nodes[missing_asset]["name"]]
            self.assertTrue(missing_row["action_descriptors"])
            self.assertTrue(all(
                not item["enabled"] and item["disabled_reason"]
                for item in missing_row["action_descriptors"]
            ))
            missing_request = {
                "handle": missing_row["handle"],
                "projection_version": projection["projection_version"],
                "action": missing_row["action_descriptors"][0]["action"],
                "client_idempotency_key": "shared-eligibility-missing-asset",
            }
            with self.assertRaises(KnowledgeMapError) as missing_error:
                service.select_target(child_key="single-child", request=missing_request)
            self.assertEqual(409, missing_error.exception.status)

            foundation_row = rows_by_name[self.nodes[foundation]["name"]]
            immediate = next(
                item for item in foundation_row["action_descriptors"]
                if item["enabled"]
            )
            self.assertEqual("enter_now", immediate["result_behavior"])
            immediate_request = self._request_for_asset(
                projection,
                asset_by_node[foundation],
                key="shared-eligibility-enter-now",
                action=immediate["action"],
            )
            immediate_result = service.select_target(
                child_key="single-child",
                request=immediate_request,
            )
            self.assertEqual("applied", immediate_result["status"])
            self.assertEqual("enter_now", immediate_result["result_behavior"])

            flow = conn.execute(
                "select * from daily_flows order by created_at desc, id desc limit 1"
            ).fetchone()
            conn.execute(
                "update flow_steps set status = 'analyzing' where id = ?",
                (flow["current_step_id"],),
            )
            conn.commit()
            waiting_projection = self._projection_for_conn(conn)
            waiting_row = next(
                row for row in waiting_projection["nodes"]
                if row["name"] == self.nodes[foundation]["name"]
            )
            waiting_descriptor = next(
                item for item in waiting_row["action_descriptors"]
                if item["enabled"]
            )
            self.assertEqual("wait_for_safe_boundary", waiting_descriptor["result_behavior"])
            waiting_request = self._request_for_asset(
                waiting_projection,
                asset_by_node[foundation],
                key="shared-eligibility-wait",
                action=waiting_descriptor["action"],
            )
            waiting_result = service.select_target(
                child_key="single-child",
                request=waiting_request,
            )
            self.assertEqual("waiting_for_safe_boundary", waiting_result["status"])
            self.assertEqual("wait_for_safe_boundary", waiting_result["result_behavior"])
            self.assertEqual(
                2,
                conn.execute("select count(*) from learning_target_intents").fetchone()[0],
            )

    def test_home_actions_exclude_contract_assets_that_fail_current_child_active_gate(self):
        config = self._load_view_config_json()
        foundation = next(
            node_id for node_id in sorted(self.child_visible_node_ids)
            if not self.nodes[node_id].get("prerequisites")
        )
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ), closing(db.connect(path)) as conn:
            assets = self._install_view_activation(
                conn,
                config_payload=config,
                assessment_node_ids=[foundation],
            )
            asset = assets[0]
            original_gate = db.is_child_schedulable_question

            def current_gate(conn_arg, question, **kwargs):
                if question.get("id") == asset["question_id"]:
                    return False
                return original_gate(conn_arg, question, **kwargs)

            service = self._service(conn)
            with mock.patch.object(db, "is_child_schedulable_question", side_effect=current_gate):
                projection = self._projection_for_conn(conn)
                row = next(
                    item for item in projection["nodes"]
                    if item["name"] == self.nodes[foundation]["name"]
                )
                self.assertTrue(row["action_descriptors"])
                self.assertTrue(all(
                    not item["enabled"] and item["disabled_reason"]
                    for item in row["action_descriptors"]
                ))
                request = {
                    "handle": row["handle"],
                    "projection_version": projection["projection_version"],
                    "action": "diagnostic",
                    "client_idempotency_key": "active-use-gate-filtered",
                }
                with self.assertRaises(KnowledgeMapError) as error:
                    service.select_target(child_key="single-child", request=request)
                self.assertEqual(409, error.exception.status)
                self.assertNotIn("暂时无法安全切换", str(error.exception))
                self.assertEqual(
                    0,
                    conn.execute("select count(*) from learning_target_intents").fetchone()[0],
                )

    def test_applied_target_stays_bound_from_active_flow_through_bootstrap(self):
        from learning_system import daily_runtime

        config = self._load_view_config_json()
        target_node_id = next(
            node_id for node_id, node in self.nodes.items()
            if node_id in self.child_visible_node_ids and node["name"] == "数感与估算"
        )
        source_node_id = next(
            node_id for node_id in sorted(self.child_visible_node_ids)
            if node_id != target_node_id
        )
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ), closing(db.connect(path)) as conn:
            assets = self._install_view_activation(
                conn,
                config_payload=config,
                assessment_node_ids=[source_node_id, target_node_id],
            )
            self._install_visual_activation(conn)
            asset_by_node = {asset["node_id"]: asset for asset in assets}
            stale_lineage = self._install_authoritative_mastery(
                conn,
                asset_by_node[target_node_id],
                status_code="A",
            )
            conn.execute(
                "update daily_flows set local_date = '2026-07-14' where id = ?",
                (stale_lineage["flow_id"],),
            )

            source_asset = asset_by_node[source_node_id]
            active_flow_id = "DF-kv51-target-continuity-active"
            active_step_id = "FS-kv51-target-continuity-active"
            active_session_id = "LS-kv51-target-continuity-active"
            now = db.now_iso()
            source_prompt = {
                "topic_label": self.nodes[source_node_id]["name"],
                "prompt": "当前 active flow 的原题。",
                "answer_input_mode": "text",
                "allowed_response_modes": ["text"],
            }
            conn.execute(
                "insert into learning_sessions(id, title, mode, status, created_at) "
                "values (?, 'target continuity', 'daily_flow_v3', 'active', ?)",
                (active_session_id, now),
            )
            conn.execute(
                """
                insert into daily_flows(
                  id, child_key, local_date, mode, status, current_step_id,
                  graph_version, question_bank_version, legacy_session_id,
                  assessment_policy_version, created_at, updated_at
                ) values (?, 'single-child', ?, 'review_old_knowledge', 'active', ?,
                          ?, ?, ?, 'v5.1', ?, ?)
                """,
                (
                    active_flow_id,
                    date.today().isoformat(),
                    active_step_id,
                    self.graph_lineage,
                    TEST_BANK_VERSION,
                    active_session_id,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                insert into flow_steps(
                  id, flow_id, step_handle, position, step_type, status,
                  graph_version, node_id, question_bank_version, question_id,
                  question_item_version, review_record_id, answer_contract_id,
                  answer_contract_version, answer_contract_digest_sha256,
                  prompt_package_json, created_at, updated_at
                ) values (?, ?, 'target-continuity-source', 1, 'question', 'selected',
                          ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    active_step_id,
                    active_flow_id,
                    self.graph_lineage,
                    source_node_id,
                    TEST_BANK_VERSION,
                    source_asset["question_id"],
                    source_asset["item_version"],
                    source_asset["review_record_id"],
                    source_asset["contract_id"],
                    source_asset["contract_digest_sha256"],
                    db.json_dump(source_prompt),
                    now,
                    now,
                ),
            )
            conn.commit()

            service = self._service(conn)
            projection = self._projection_for_conn(conn)
            target_row = next(
                row for row in projection["nodes"]
                if row["name"] == self.nodes[target_node_id]["name"]
            )
            descriptor = next(
                item for item in target_row["action_descriptors"]
                if item["enabled"]
            )
            request = {
                "handle": target_row["handle"],
                "projection_version": projection["projection_version"],
                "action": descriptor["action"],
                "client_idempotency_key": "target-continuity-applied",
            }
            result = service.select_target(child_key="single-child", request=request)
            self.assertEqual("waiting_for_safe_boundary", result["status"])

            intent = conn.execute(
                "select * from learning_target_intents where client_idempotency_key = ?",
                (request["client_idempotency_key"],),
            ).fetchone()
            self.assertEqual(active_flow_id, intent["source_flow_id"])
            self.assertIsNone(intent["applied_flow_id"])
            conn.execute(
                "update flow_steps set status = 'completed', updated_at = ? where id = ?",
                (db.now_iso(), active_step_id),
            )
            conn.commit()
            recovered = daily_runtime.DailyLearningRuntime(
                conn,
                project_root=PROJECT_ROOT,
            ).recover_target_intents()
            self.assertEqual("applied", recovered["status"], recovered)
            intent = conn.execute(
                "select * from learning_target_intents where id = ?",
                (intent["id"],),
            ).fetchone()
            self.assertEqual(active_flow_id, intent["applied_flow_id"])
            materialized_flow = conn.execute(
                "select * from daily_flows where id = ?",
                (intent["applied_flow_id"],),
            ).fetchone()
            materialized_step = conn.execute(
                "select * from flow_steps where id = ?",
                (materialized_flow["current_step_id"],),
            ).fetchone()
            self.assertEqual(intent["applied_step_id"], materialized_step["id"])
            self.assertEqual(target_node_id, materialized_step["node_id"])

            bootstrap = daily_runtime.DailyLearningRuntime(
                conn,
                project_root=PROJECT_ROOT,
            ).load_or_create_daily_flow()
            self.assertEqual("current_step", bootstrap["child_state"])
            self.assertEqual(
                self.nodes[target_node_id]["name"],
                bootstrap["current_step"]["topic_label"],
            )

    def test_waiting_intent_is_applied_once_at_safe_boundary_and_reused_after_restart(self):
        from learning_system import daily_runtime, knowledge_map

        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                assets = self._install_view_activation(conn, config_payload=config)
                self._install_visual_activation(conn)
                service = self._service(conn)
                projection = self._projection_for_conn(conn)
                first_request = self._request_for_asset(projection, assets[0], key="safe-boundary-first")
                self.assertEqual("applied", service.select_target(child_key="single-child", request=first_request)["status"])
                flow = conn.execute("select * from daily_flows order by created_at desc limit 1").fetchone()
                current_step = conn.execute("select * from flow_steps where id = ?", (flow["current_step_id"],)).fetchone()
                conn.execute("update flow_steps set status = 'analyzing' where id = ?", (current_step["id"],))
                conn.commit()
                second_request = self._request_for_asset(projection, assets[1], key="safe-boundary-second")
                waiting = service.select_target(child_key="single-child", request=second_request)
                self.assertEqual("waiting_for_safe_boundary", waiting["status"])
                pending = conn.execute(
                    "select * from learning_target_intents where client_idempotency_key = ?",
                    (second_request["client_idempotency_key"],),
                ).fetchone()
                self.assertEqual("waiting_for_safe_boundary", pending["status"])
                conn.execute("update flow_steps set status = 'completed' where id = ?", (current_step["id"],))
                conn.commit()

            with closing(db.connect(path)) as restarted:
                runtime = daily_runtime.DailyLearningRuntime(restarted, project_root=PROJECT_ROOT)
                recovery = getattr(runtime, "recover_target_intents", None)
                self.assertIsNotNone(recovery, "DailyLearningRuntime.recover_target_intents is missing")
                recovered = recovery()
                self.assertEqual("applied", recovered["status"])
                canonical = knowledge_map.newest_pending_intent(
                    restarted,
                    child_key="single-child",
                    graph_version=self.graph_lineage,
                )
                self.assertIsNone(canonical)
                applied = restarted.execute(
                    "select * from learning_target_intents where client_idempotency_key = ?",
                    (second_request["client_idempotency_key"],),
                ).fetchone()
                self.assertEqual("applied", applied["status"])
                counts = (
                    restarted.execute("select count(*) from daily_flows").fetchone()[0],
                    restarted.execute("select count(*) from flow_steps").fetchone()[0],
                )
                replay = recovery()
                self.assertIn(replay["status"], {"applied", "none"})
                self.assertEqual(
                    counts,
                    (
                        restarted.execute("select count(*) from daily_flows").fetchone()[0],
                        restarted.execute("select count(*) from flow_steps").fetchone()[0],
                    ),
                )

    def test_startup_recovery_materializes_pending_intent_without_duplicate_flow_or_step(self):
        from learning_system import daily_runtime, knowledge_map

        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                assets = self._install_view_activation(conn, config_payload=config)
                self._install_visual_activation(conn)
                knowledge_map.create_target_intent(
                    conn,
                    child_key="single-child",
                    graph_version=self.graph_lineage,
                    node_id=assets[0]["node_id"],
                    action="diagnostic",
                    client_idempotency_key="startup-recovery",
                )
            with closing(db.connect(path)) as restarted:
                runtime = daily_runtime.DailyLearningRuntime(restarted, project_root=PROJECT_ROOT)
                runtime.load_or_create_daily_flow(local_date="2026-07-15")
                intent = restarted.execute(
                    "select * from learning_target_intents where client_idempotency_key = 'startup-recovery'"
                ).fetchone()
                self.assertEqual("applied", intent["status"])
                counts = (
                    restarted.execute("select count(*) from daily_flows").fetchone()[0],
                    restarted.execute("select count(*) from flow_steps").fetchone()[0],
                )
                runtime.load_or_create_daily_flow(local_date="2026-07-15")
                self.assertEqual(
                    counts,
                    (
                        restarted.execute("select count(*) from daily_flows").fetchone()[0],
                        restarted.execute("select count(*) from flow_steps").fetchone()[0],
                    ),
                )

    def test_stale_tampered_and_idempotency_conflict_are_child_safe_409_with_zero_writes(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ), closing(db.connect(path)) as conn:
            assets = self._install_view_activation(conn, config_payload=config)
            self._install_visual_activation(conn)
            service = self._service(conn)
            projection = self._projection_for_conn(conn)
            valid = self._request_for_asset(projection, assets[0], key="conflict-key")
            self.assertEqual("applied", service.select_target(child_key="single-child", request=valid)["status"])

            cases = [
                {**valid, "projection_version": valid["projection_version"] + ":stale", "client_idempotency_key": "stale-key"},
                {**valid, "handle": valid["handle"][:-1] + ("0" if valid["handle"][-1] != "0" else "1"), "client_idempotency_key": "tampered-key"},
                {**valid, "action": "learn"},
            ]
            for request in cases:
                with self.subTest(request=request):
                    before = "\n".join(conn.iterdump())
                    with self.assertRaises(ValueError) as raised:
                        service.select_target(child_key="single-child", request=request)
                    self.assertEqual(409, getattr(raised.exception, "status", None))
                    self.assertEqual("conflict", getattr(raised.exception, "state", None))
                    self.assertEqual(before, "\n".join(conn.iterdump()))


class DualViewStaticContractTests(KnowledgeViewsV51TestCase):
    def test_controller_public_boundary_has_no_transport_force_simulation_or_learning_writer(self):
        js = self._require_file(KNOWLEDGE_VIEW_JS, "dual-view controller").read_text(encoding="utf-8")
        match = re.search(r"window\.KnowledgeViews\s*=\s*Object\.freeze\s*\(\s*\{(?P<body>.*?)\}\s*\)", js, re.DOTALL)
        self.assertIsNotNone(match, "window.KnowledgeViews public controller is missing")
        public_names = set(
            re.findall(
                r"(?:^|,)\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*(?=[:,]|$)",
                match.group("body").strip(),
            )
        )
        self.assertEqual(EXPECTED_CONTROLLER_API, public_names)

        self.assertNotRegex(js, r"\bfetch\s*\(")
        self.assertNotIn("XMLHttpRequest", js)
        self.assertNotIn("WebSocket", js)
        self.assertNotIn("sendBeacon", js)
        self.assertNotRegex(js, r"/(?:api|operator)/")
        self.assertNotRegex(js, r"\bforceSimulation\b|\bd3\.force|force-directed|physics-engine")

        for match in re.finditer(r"localStorage\.setItem\s*\((?P<call>.*?)\)", js, re.DOTALL):
            call = match.group("call").casefold()
            self.assertNotRegex(
                call,
                r"attempt|assessment|answer|score|mastery|evidence|flow|step|question|target[_-]?intent|lineage",
                "controller may persist presentation state only",
            )

    def test_activation_cli_is_dry_by_default_atomic_and_auditable(self):
        self._require_file(KNOWLEDGE_ACTIVATION_SCRIPT, "knowledge-view activation CLI")
        with self._temp_database() as path, tempfile.TemporaryDirectory() as tmpdir:
            with closing(db.connect(path)) as conn:
                before = "\n".join(conn.iterdump())
            dry_run = subprocess.run(
                [
                    "python3",
                    str(KNOWLEDGE_ACTIVATION_SCRIPT),
                    "--db",
                    str(path),
                    "--json",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(0, dry_run.returncode, dry_run.stderr or dry_run.stdout)
            dry_payload = json.loads(dry_run.stdout)
            self.assertTrue(dry_payload["activation_ready"])
            with closing(db.connect(path)) as conn:
                self.assertEqual(before, "\n".join(conn.iterdump()))

            activated = subprocess.run(
                [
                    "python3",
                    str(KNOWLEDGE_ACTIVATION_SCRIPT),
                    "--db",
                    str(path),
                    "--activate",
                    "--backup-root",
                    tmpdir,
                    "--json",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(0, activated.returncode, activated.stderr or activated.stdout)
            activated_payload = json.loads(activated.stdout)
            self.assertEqual("activated", activated_payload["status"])
            self.assertTrue(Path(activated_payload["backup"]["path"]).is_file())
            self.assertNotIn("secret", activated_payload)

            with closing(db.connect(path)) as conn:
                before_audit = "\n".join(conn.iterdump())
            audited = subprocess.run(
                [
                    "python3",
                    str(KNOWLEDGE_ACTIVATION_SCRIPT),
                    "--db",
                    str(path),
                    "--audit",
                    "--json",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(0, audited.returncode, audited.stderr or audited.stdout)
            self.assertEqual("active", json.loads(audited.stdout)["status"])
            with closing(db.connect(path)) as conn:
                self.assertEqual(before_audit, "\n".join(conn.iterdump()))


class DualViewBrowserContractTests(KnowledgeViewsV51TestCase):
    def test_policy_off_hides_map_entry_and_keeps_focused_learning_surface(self):
        self._require_file(POLICY_OFF_BROWSER_FIXTURE, "policy-off knowledge-view browser fixture")
        with self._temp_database() as path, self._policy_env(
            map_policy="off",
            assessment_policy="v5.1",
        ):
            httpd, base_url = server.start_test_server(path)
            try:
                completed = subprocess.run(
                    ["node", str(POLICY_OFF_BROWSER_FIXTURE), "--base-url", base_url],
                    cwd=PROJECT_ROOT,
                    text=True,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
            finally:
                httpd.shutdown()
                httpd.server_close()
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)

    def test_browser_default_view_independent_viewports_shared_selection_and_390_child_safety(self):
        self._require_file(VIEW_CONFIG_PATH, "v5.1 knowledge-view config")
        self._require_file(KNOWLEDGE_VIEW_JS, "dual-view controller")
        self._require_file(KNOWLEDGE_VIEW_CSS, "dual-view stylesheet")
        self._require_file(CHILD_INDEX, "child application shell")
        self._require_file(BROWSER_FIXTURE, "dual-view Playwright fixture")
        config = self._load_view_config_json()

        with self._temp_database() as path, tempfile.TemporaryDirectory() as backup_root:
            with closing(db.connect(path)) as conn:
                self._install_view_activation(conn, config_payload=config)
            visual_activation = subprocess.run(
                [
                    "python3",
                    str(QUESTION_VISUAL_ACTIVATION_SCRIPT),
                    "--db",
                    str(path),
                    "--activate",
                    "--backup-root",
                    backup_root,
                    "--json",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                0,
                visual_activation.returncode,
                visual_activation.stderr or visual_activation.stdout,
            )
            with self._policy_env(map_policy="v5.1", assessment_policy="v5.1"):
                httpd, base_url = server.start_test_server(path)
                try:
                    completed = subprocess.run(
                        ["node", str(BROWSER_FIXTURE), "--base-url", base_url],
                        cwd=PROJECT_ROOT,
                        text=True,
                        capture_output=True,
                        timeout=90,
                        check=False,
                    )
                finally:
                    httpd.shutdown()
                    httpd.server_close()
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual(
            {
                "knowledge_projection_sets_connection_ready",
                "child_projection_hides_internal_process",
                "child_projection_learning_path_order",
                "not_started_hides_resume_learning",
                "child_home_defaults_to_simple_start",
                "first_visit_mind_map",
                "desktop_1280_no_horizontal_scroll",
                "flat_directory_shows_eight_modules_with_visible_nodes",
                "directory_uses_masonry_columns",
                "mind_module_order_matches_learning_path",
                "child_dom_has_no_graph_surface",
                "internal_process_module_hidden_in_dom",
                "node_selection_opens_child_safe_detail",
                "collapsed_directory_closes_detail_and_removes_extra_space",
                "search_results_max_six",
                "search_clear_preserves_child_surface",
                "child_safe_dom",
                "mobile_390_no_horizontal_scroll",
                "mobile_directory_stays_single_column",
                "mobile_controls_44px",
                "screenshots_written",
            },
            {key for key, value in report.items() if value is True},
            report,
        )
        self.assertEqual(
            {
                "knowledge-v51-child-map-desktop.png",
                "knowledge-v51-child-map-mobile.png",
            },
            set(report.get("screenshots") or {}),
        )
        for screenshot_path in report["screenshots"].values():
            self.assertGreater(Path(screenshot_path).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
