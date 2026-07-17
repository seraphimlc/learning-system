from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from learning_system import daily_runtime, db, question_bank, server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V12_PILOT_PATH = PROJECT_ROOT / "data/question_banks/math/math_question_bank_v12_pilot_six_nodes.json"
V12_EQ_DENOM_CHECKPOINT_PATH = (
    PROJECT_ROOT
    / "data/question_banks/math/.v12_pilot_six_checkpoints/M-G7-EQ-DENOM.json"
)
V12_NUMBER_LINE_CHECKPOINT_PATH = (
    PROJECT_ROOT
    / "data/question_banks/math/.v12_pilot_six_checkpoints/M-G7-NUMBER-LINE.json"
)
V12_GEO_VIEWS_CHECKPOINT_PATH = (
    PROJECT_ROOT
    / "data/question_banks/math/.v12_pilot_six_checkpoints/M-G7-GEO-VIEWS.json"
)
INVENTORY_PATH = PROJECT_ROOT / "tests/fixtures/question_visual_inventory_v51.json"
SCENES_PATH = PROJECT_ROOT / "tests/fixtures/question_visual_typed_scenes_v1.json"
MISSING_MANIFEST_PATH = PROJECT_ROOT / "tests/fixtures/question_visual_manifest_missing_binding_v1.json"
BOUND_MANIFEST_PATH = PROJECT_ROOT / "tests/fixtures/question_visual_manifest_bound_number_line_v1.json"
BROWSER_RENDERER_FIXTURE = PROJECT_ROOT / "tests/fixtures/browser_question_visual_renderer_v51.mjs"
BROWSER_FAILURE_FIXTURE = PROJECT_ROOT / "tests/fixtures/browser_question_visual_resource_failure_v51.mjs"
BROWSER_RECOVERY_FIXTURE = PROJECT_ROOT / "tests/fixtures/browser_question_visual_recovery_v51.mjs"

PRODUCTION_MANIFEST_PATH = PROJECT_ROOT / "data/question_visuals/math_question_visual_manifest_v1.json"
PRODUCTION_RENDERER_JS = PROJECT_ROOT / "app/local_learning_system/question_visual_renderer.js"
PRODUCTION_RENDERER_CSS = PROJECT_ROOT / "app/local_learning_system/question_visual_renderer.css"
VISUAL_ACTIVATION_SCRIPT = PROJECT_ROOT / "scripts/activate_question_visuals.py"

VISUAL_RECEIPT_KEY = "question_visual_manifest_active.v1"
ALLOWED_SCENE_TYPES = {
    "number_line",
    "cube_net",
    "orthographic_view",
    "simple_geometry",
}
FORBIDDEN_SCENE_KEYS = {
    "raw_svg",
    "svg",
    "html",
    "script",
    "src",
    "href",
    "url",
    "external_url",
    "data_url",
}
EXPECTED_RENDERER_API = {"render", "clear", "supportedSceneTypes"}
CHILD_VISUAL_KEYS = {"scene_type", "alt_text", "long_description", "scene"}
CHILD_VISUAL_FORBIDDEN_KEYS = {
    "question_id",
    "item_version",
    "question_digest_sha256",
    "manifest_version",
    "manifest_sha256",
    "inventory_sha256",
    "renderer_contract_version",
    "relative_path",
    "receipt",
    "receipt_sha256",
    "entry_sha256",
}
SCENE_BUDGETS = {
    "number_line": {"ticks": 41, "points": 16},
    "cube_net": {"cells": 6},
    "orthographic_view": {"views": 3, "width": 12, "height": 12, "filled_cells": 144},
    "simple_geometry": {"points": 24, "segments": 48, "markers": 24},
}


def _canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class QuestionVisualV51TestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.scene_fixture = json.loads(SCENES_PATH.read_text(encoding="utf-8"))
        cls.v12 = json.loads(V12_PILOT_PATH.read_text(encoding="utf-8"))
        cls.eq_denom_checkpoint = json.loads(
            V12_EQ_DENOM_CHECKPOINT_PATH.read_text(encoding="utf-8")
        )
        cls.number_line_checkpoint = json.loads(
            V12_NUMBER_LINE_CHECKPOINT_PATH.read_text(encoding="utf-8")
        )
        cls.geo_checkpoint = json.loads(
            V12_GEO_VIEWS_CHECKPOINT_PATH.read_text(encoding="utf-8")
        )
        cls.number_line_group = next(
            group for group in cls.inventory["groups"] if group["node_id"] == "M-G7-NUMBER-LINE"
        )
        cls.geo_group = next(
            group for group in cls.inventory["groups"] if group["node_id"] == "M-G7-GEO-VIEWS"
        )
        cls.number_line_items = {
            str(item["id"]): item for item in cls.number_line_checkpoint["node"]["items"]
        }
        cls.geo_items = {
            str(item["id"]): item for item in cls.geo_checkpoint["node"]["items"]
        }
        cls.default_visual_item = copy.deepcopy(cls.geo_checkpoint["node"]["items"][0])
        cls.eq_denom_item = copy.deepcopy(cls.eq_denom_checkpoint["node"]["items"][0])

    def _require_file(self, path: Path, purpose: str) -> Path:
        self.assertTrue(path.is_file(), f"missing production {purpose}: {path}")
        return path

    def _require_visual_module(self):
        try:
            return importlib.import_module("learning_system.question_visuals")
        except ModuleNotFoundError as exc:
            if exc.name == "learning_system.question_visuals":
                self.fail("missing production module: learning_system.question_visuals")
            raise

    def _manifest_type(self):
        module = self._require_visual_module()
        manifest_type = getattr(module, "QuestionVisualManifest", None)
        self.assertIsNotNone(manifest_type, "QuestionVisualManifest public API is missing")
        return manifest_type

    def _load_validated_manifest(self, path: Path = PRODUCTION_MANIFEST_PATH):
        manifest_type = self._manifest_type()
        loader = getattr(manifest_type, "load_validated", None)
        self.assertIsNotNone(loader, "QuestionVisualManifest.load_validated is missing")
        loaded = loader(path, inventory_path=INVENTORY_PATH)
        if isinstance(loaded, tuple):
            self.assertEqual(2, len(loaded))
            manifest, report = loaded
        else:
            manifest = loaded
            report = getattr(manifest, "audit_report", None)
        self.assertIsInstance(report, dict, "validated manifest must expose an audit report")
        return manifest, report

    def _load_active_manifest(self, conn):
        manifest_type = self._manifest_type()
        loader = getattr(manifest_type, "load_active", None)
        self.assertIsNotNone(
            loader,
            "QuestionVisualManifest.load_active is required for receipt-bound runtime use",
        )
        loaded = loader(conn, project_root=PROJECT_ROOT)
        if isinstance(loaded, tuple):
            self.assertEqual(2, len(loaded))
            manifest, report = loaded
        else:
            manifest = loaded
            report = getattr(manifest, "audit_report", None)
        self.assertIsInstance(report, dict, "active manifest must expose a receipt audit report")
        return manifest, report

    def _validate_entry(self, entry: dict):
        return self._entry_validator()(entry)

    def _entry_validator(self):
        manifest_type = self._manifest_type()
        validator = getattr(manifest_type, "validate_entry", None)
        self.assertIsNotNone(validator, "QuestionVisualManifest.validate_entry is missing")
        return validator

    @contextmanager
    def _runtime_env(self):
        previous = os.environ.get("V3_DAILY_RUNTIME_ENABLED")
        os.environ["V3_DAILY_RUNTIME_ENABLED"] = "1"
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("V3_DAILY_RUNTIME_ENABLED", None)
            else:
                os.environ["V3_DAILY_RUNTIME_ENABLED"] = previous

    @contextmanager
    def _seeded_runtime_db(self, *, question_fixture: dict | None = None, create_flow: bool = True):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "question-visual-v51.sqlite"
            with closing(db.connect(db_path)) as conn:
                db.init_schema(conn)
                item = copy.deepcopy(
                    question_fixture
                    if question_fixture is not None
                    else self.default_visual_item
                )
                item_version = self.geo_group["item_version"]
                digest = question_bank.v12_external_candidate_sha256(item)
                item["item_version"] = item_version
                item["question_bank_version"] = item_version
                item["question_digest_sha256"] = digest
                item["source_type"] = "graph_generated_v12"
                graph = json.loads(
                    (PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json").read_text(
                        encoding="utf-8"
                    )
                )
                node = next(row for row in graph["nodes"] if row["id"] == item["node_id"])
                summer = node.get("summer_execution") or {}
                conn.execute(
                    """
                    insert into graph_nodes(
                      id, name, stage, domain, priority, summer_mode, sequence_band,
                      prerequisites_json, unlocks_json, raw_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node["id"],
                        node["name"],
                        node["stage"],
                        node["domain"],
                        node["priority"],
                        summer.get("mode") or "core",
                        int(summer.get("sequence_band") or 99),
                        db.json_dump(node.get("prerequisites") or []),
                        db.json_dump(node.get("unlocks") or []),
                        db.json_dump(node),
                    ),
                )
                conn.execute(
                    """
                    insert into question_items(
                      id, item_version, source_type, node_id, secondary_node_ids_json,
                      kind, question_type, variant_level, prompt, answer_format,
                      expected_answer, rubric_json, solution_steps_json, error_tags_json,
                      rollback_candidate_node_ids_json, rollback_candidate_relations_json,
                      estimated_minutes, parent_observation, source_json, created_by_event_id,
                      raw_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        item_version,
                        "graph_generated_v12",
                        item["node_id"],
                        "[]",
                        item["kind"],
                        item["question_type"],
                        item["variant_level"],
                        item["prompt"],
                        item["answer_format"],
                        item["expected_answer"],
                        db.json_dump({}),
                        db.json_dump(item.get("solution_steps") or []),
                        db.json_dump(item.get("target_error_tags") or []),
                        db.json_dump(item.get("rollback_candidates") or []),
                        "[]",
                        int(item.get("estimated_minutes") or 4),
                        "",
                        db.json_dump({"question_digest_sha256": digest}),
                        None,
                        db.json_dump(item),
                    ),
                )
                graph_version = str(self.v12["graph_version"])
                db.ensure_initial_active_question_bank_version(
                    conn,
                    question_bank_version=item_version,
                    graph_version=graph_version,
                    manifest_id="question-visual-v51-test-bank",
                    manifest_sha256=_canonical_sha256({"question_id": item["id"]}),
                    commit=False,
                )
                candidate_sha256 = db._digest_json(item)
                reviewer_run = db.record_agent_run(
                    conn,
                    agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
                    engine_type="deterministic",
                    session_id=None,
                    phase="test_question_quality_review",
                    trigger="question_visual_v51_fixture",
                    input_refs={
                        "question_id": item["id"],
                        "candidate_sha256": candidate_sha256,
                    },
                    prompt_version_id="question-visual-v51.test-review.v1",
                    status="accepted",
                    confidence=1.0,
                    output={"review_status": "approved", "active_eligible": True},
                    commit=False,
                )
                review_record_id = f"QRR-VISUAL-{hashlib.sha256(item['id'].encode()).hexdigest()[:12]}"
                conn.execute(
                    """
                    insert into question_review_records(
                      id, question_id, candidate_id, item_version, source_type,
                      candidate_sha256, designer_run_id, reviewer_run_id,
                      review_contract_version, review_status, rejection_reasons_json,
                      criteria_json, active_eligible, reviewed_at
                    ) values (?, ?, ?, ?, ?, ?, null, ?, ?, 'approved', '[]', '{}', 1, ?)
                    """,
                    (
                        review_record_id,
                        item["id"],
                        item["id"],
                        item_version,
                        item["source_type"],
                        candidate_sha256,
                        reviewer_run["id"],
                        "question-visual-v51.test-review.v1",
                        db.now_iso(),
                    ),
                )
                stored_question = db.get_question(conn, item["id"])
                self.assertTrue(
                    db.question_review_record_allows_active_use(
                        conn,
                        stored_question,
                        review_record_id,
                    )
                )
                now = "2026-07-15T00:00:00+08:00"
                if create_flow:
                    conn.execute(
                        """
                        insert into daily_flows(
                          id, child_key, local_date, mode, status, graph_version,
                          question_bank_version, created_at, updated_at
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "FLOW-VISUAL-V51",
                            "single-child",
                            "2026-07-15",
                            "review",
                            "active",
                            graph_version,
                            item_version,
                            now,
                            now,
                        ),
                    )
                conn.commit()
            yield db_path, item, digest, review_record_id

    def _install_manifest_receipt(
        self,
        conn,
        manifest_path: Path,
        *,
        inventory_path: Path = INVENTORY_PATH,
        receipt_patch: dict | None = None,
    ) -> dict:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        inventory_sha256 = _canonical_sha256(inventory)
        required_triples = [
            {
                "question_id": item["question_id"],
                "item_version": group["item_version"],
                "question_digest_sha256": item["question_digest_sha256"],
                "scene_type": item["scene_type"],
            }
            for group in inventory["groups"]
            if group["checkpoint_status"] == "complete"
            for item in group["items"]
        ]
        required_triples.sort(
            key=lambda item: (
                item["question_id"],
                item["item_version"],
                item["question_digest_sha256"],
            )
        )
        receipt = {
            "receipt_schema_version": "question-visual-activation.v1",
            "manifest_version": payload["manifest_version"],
            "manifest_sha256": _canonical_sha256(payload),
            "inventory_version": inventory["inventory_version"],
            "inventory_sha256": inventory_sha256,
            "relative_path": str(manifest_path.relative_to(PROJECT_ROOT)),
            "inventory_relative_path": str(inventory_path.relative_to(PROJECT_ROOT)),
            "renderer_contract_version": payload["renderer_contract_version"],
            "required_triple_count": len(required_triples),
            "required_triples_sha256": _canonical_sha256(required_triples),
            "activated_at": "2026-07-15T00:00:00+08:00",
        }
        receipt.update(receipt_patch or {})
        conn.execute(
            "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
            (VISUAL_RECEIPT_KEY, db.json_dump(receipt), receipt["activated_at"]),
        )
        conn.commit()
        return receipt

    def _structural_manifest_payload(self, *, inventory_relative_path: str | None = None) -> dict:
        payload = json.loads(PRODUCTION_MANIFEST_PATH.read_text(encoding="utf-8"))
        payload["inventory_relative_path"] = inventory_relative_path or str(
            INVENTORY_PATH.relative_to(PROJECT_ROOT)
        )
        return payload

    def _write_json(self, path: Path, payload: object) -> Path:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    @contextmanager
    def _structural_manifest_file(self):
        fixture_root = PROJECT_ROOT / "tests/fixtures"
        with tempfile.TemporaryDirectory(
            prefix="browser_question_visual_manifest_",
            dir=fixture_root,
        ) as tmpdir:
            path = Path(tmpdir) / "manifest.json"
            self._write_json(path, self._structural_manifest_payload())
            yield path

    @contextmanager
    def _complete_visual_package(self):
        fixture_root = PROJECT_ROOT / "tests/fixtures"
        with tempfile.TemporaryDirectory(prefix="question_visual_complete_", dir=fixture_root) as tmpdir:
            root = Path(tmpdir)
            inventory_path = root / "inventory.json"
            manifest_path = root / "manifest.json"
            inventory = copy.deepcopy(self.inventory)
            manifest = json.loads(PRODUCTION_MANIFEST_PATH.read_text(encoding="utf-8"))
            manifest["inventory_relative_path"] = str(inventory_path.relative_to(PROJECT_ROOT))
            self._write_json(inventory_path, inventory)
            self._write_json(manifest_path, manifest)
            yield manifest_path, inventory_path

    @contextmanager
    def _pending_visual_package(self):
        fixture_root = PROJECT_ROOT / "tests/fixtures"
        with tempfile.TemporaryDirectory(prefix="question_visual_pending_", dir=fixture_root) as tmpdir:
            root = Path(tmpdir)
            inventory_path = root / "inventory.json"
            manifest_path = root / "manifest.json"
            inventory = copy.deepcopy(self.inventory)
            number_group = next(
                group for group in inventory["groups"] if group["node_id"] == "M-G7-NUMBER-LINE"
            )
            number_group["checkpoint_status"] = "refresh_pending"
            pending_items = []
            for item in number_group["items"]:
                pending_items.append({
                    "slot": item["slot"],
                    "question_id": item["question_id"],
                    "required": True,
                    "scene_type": "number_line",
                    "binding_status": "refresh_pending",
                })
            number_group["items"] = pending_items
            manifest = json.loads(PRODUCTION_MANIFEST_PATH.read_text(encoding="utf-8"))
            manifest["inventory_relative_path"] = str(inventory_path.relative_to(PROJECT_ROOT))
            pending_ids = {item["question_id"] for item in pending_items}
            manifest["entries"] = [
                entry
                for entry in manifest["entries"]
                if entry["question_id"] not in pending_ids
            ]
            self._write_json(inventory_path, inventory)
            self._write_json(manifest_path, manifest)
            yield manifest_path, inventory_path

    def _selected_question_packet(self, question: dict, review_record_id: str) -> dict:
        return {
            "question": question,
            "review_record_id": review_record_id,
            "selection_reason": {"reason": "question_visual_v51_http_gate"},
            "candidate_packet": {},
        }

    def _request_json(self, method: str, base_url: str, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _create_question_step(self, conn, question: dict) -> str:
        runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
        return runtime._create_question_step(
            flow_id="FLOW-VISUAL-V51",
            position=1,
            graph_version=str(self.v12["graph_version"]),
            question=question,
            review_record_id="",
            selection_reason={"reason": "question_visual_v51_test"},
            answer_input_mode="text_photo",
        )


class QuestionVisualInventoryTests(QuestionVisualV51TestCase):
    def test_activation_cli_rejects_pending_production_and_is_atomic_auditable_when_complete(self):
        self._require_file(VISUAL_ACTIVATION_SCRIPT, "question visual activation CLI")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "visual-activation.sqlite"
            with closing(db.connect(db_path)) as conn:
                db.init_schema(conn)
                before_pending = "\n".join(conn.iterdump())
            with self._pending_visual_package() as (pending_manifest, pending_inventory):
                pending = subprocess.run(
                    [
                        "python3",
                        str(VISUAL_ACTIVATION_SCRIPT),
                        "--db",
                        str(db_path),
                        "--manifest",
                        str(pending_manifest),
                        "--inventory",
                        str(pending_inventory),
                        "--json",
                    ],
                    cwd=PROJECT_ROOT,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertNotEqual(0, pending.returncode, pending.stdout)
                self.assertFalse(json.loads(pending.stdout)["activation_ready"])
            with closing(db.connect(db_path)) as conn:
                self.assertEqual(before_pending, "\n".join(conn.iterdump()))

            with self._complete_visual_package() as (manifest_path, inventory_path):
                dry_run = subprocess.run(
                    [
                        "python3",
                        str(VISUAL_ACTIVATION_SCRIPT),
                        "--db",
                        str(db_path),
                        "--manifest",
                        str(manifest_path),
                        "--inventory",
                        str(inventory_path),
                        "--json",
                    ],
                    cwd=PROJECT_ROOT,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(0, dry_run.returncode, dry_run.stderr or dry_run.stdout)
                self.assertEqual(40, json.loads(dry_run.stdout)["required_triple_count"])
                activated = subprocess.run(
                    [
                        "python3",
                        str(VISUAL_ACTIVATION_SCRIPT),
                        "--db",
                        str(db_path),
                        "--manifest",
                        str(manifest_path),
                        "--inventory",
                        str(inventory_path),
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
                with closing(db.connect(db_path)) as conn:
                    before_audit = "\n".join(conn.iterdump())
                audited = subprocess.run(
                    [
                        "python3",
                        str(VISUAL_ACTIVATION_SCRIPT),
                        "--db",
                        str(db_path),
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
                with closing(db.connect(db_path)) as conn:
                    self.assertEqual(before_audit, "\n".join(conn.iterdump()))

    def test_number_line_completed_checkpoint_exactly_binds_20_required_scenes(self):
        entries = self.number_line_group["items"]
        self.assertEqual("completed", self.number_line_checkpoint["status"])
        self.assertEqual("complete", self.number_line_group["checkpoint_status"])
        self.assertEqual(20, len(entries))
        self.assertEqual(set(range(1, 21)), {entry["slot"] for entry in entries})
        self.assertEqual(20, len({entry["question_id"] for entry in entries}))
        for entry in entries:
            source = self.number_line_items[entry["question_id"]]
            self.assertTrue(entry["required"])
            self.assertEqual("number_line", entry["scene_type"])
            self.assertEqual(
                question_bank.v12_external_candidate_sha256(source),
                entry["question_digest_sha256"],
            )

    def test_geo_views_completed_checkpoint_exactly_binds_20_required_scenes(self):
        entries = self.geo_group["items"]
        self.assertEqual("completed", self.geo_checkpoint["status"])
        self.assertEqual("complete", self.geo_group["checkpoint_status"])
        self.assertEqual(20, len(entries))
        self.assertEqual(set(range(1, 21)), {entry["slot"] for entry in entries})
        for entry in entries:
            source = self.geo_items[entry["question_id"]]
            self.assertTrue(entry["required"])
            self.assertIn(entry["scene_type"], ALLOWED_SCENE_TYPES - {"number_line"})
            self.assertEqual(
                question_bank.v12_external_candidate_sha256(source),
                entry["question_digest_sha256"],
            )

    def test_production_manifest_uses_public_loader_and_exact_triple_lookup(self):
        self._require_file(PRODUCTION_MANIFEST_PATH, "question visual manifest")
        manifest, report = self._load_validated_manifest()
        self.assertEqual([], report.get("invalid_entries", []), report)
        self.assertEqual([], report.get("missing_required_entries", []), report)
        self.assertEqual([], report.get("extra_entries", []), report)
        self.assertEqual([], report.get("duplicate_bindings", []), report)
        self.assertEqual(40, report.get("manifest_entry_count"), report)
        self.assertEqual(40, report.get("bound_inventory_slots"), report)
        self.assertEqual(0, report.get("pending_inventory_slots"), report)
        self.assertEqual("", report.get("pending_inventory_node"), report)
        expected_triples = {
            (
                entry["question_id"],
                group["item_version"],
                entry["question_digest_sha256"],
            )
            for group in self.inventory["groups"]
            for entry in group["items"]
        }
        payload = json.loads(PRODUCTION_MANIFEST_PATH.read_text(encoding="utf-8"))
        actual_triples = {
            (
                entry.get("question_id"),
                entry.get("item_version"),
                entry.get("question_digest_sha256"),
            )
            for entry in payload.get("entries") or []
            if isinstance(entry, dict)
        }
        self.assertEqual(expected_triples, actual_triples)
        for group in self.inventory["groups"]:
            for entry in group["items"]:
                visual = manifest.lookup(
                    entry["question_id"],
                    group["item_version"],
                    entry["question_digest_sha256"],
                )
                self.assertIsNotNone(visual, entry)
                self.assertEqual(entry["scene_type"], visual["scene_type"])
                self.assertIsNone(
                    manifest.lookup(
                        entry["question_id"],
                        group["item_version"] + ":stale",
                        entry["question_digest_sha256"],
                    )
                )

    def test_active_receipt_binds_exact_manifest_and_inventory_files(self):
        with self._structural_manifest_file() as manifest_path, tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "receipt.sqlite")
            try:
                db.init_schema(conn)
                receipt = self._install_manifest_receipt(conn, manifest_path)
                manifest, report = self._load_active_manifest(conn)
                self.assertEqual([], report.get("invalid_entries", []), report)
                self.assertEqual([], report.get("missing_required_entries", []), report)
                self.assertEqual([], report.get("extra_entries", []), report)
                self.assertEqual(40, report.get("manifest_entry_count"), report)
                self.assertEqual(40, report.get("bound_inventory_slots"), report)
                self.assertEqual(0, report.get("pending_inventory_slots"), report)
                self.assertEqual(receipt["manifest_sha256"], report.get("manifest_sha256"), report)
                self.assertEqual(receipt["inventory_sha256"], report.get("inventory_sha256"), report)
                self.assertEqual(
                    {
                        entry["question_id"]
                        for group in self.inventory["groups"]
                        for entry in group["items"]
                    },
                    {
                        entry["question_id"]
                        for entry in self._structural_manifest_payload()["entries"]
                        if manifest.lookup(
                            entry["question_id"],
                            entry["item_version"],
                            entry["question_digest_sha256"],
                        )
                    },
                )
            finally:
                conn.close()

    def test_manifest_inventory_and_receipt_tampering_fail_closed(self):
        fixture_root = PROJECT_ROOT / "tests/fixtures"
        with tempfile.TemporaryDirectory(
            prefix="browser_question_visual_tamper_",
            dir=fixture_root,
        ) as tmpdir, tempfile.TemporaryDirectory() as db_tmp:
            root = Path(tmpdir)
            manifest_path = root / "manifest.json"
            inventory_path = root / "inventory.json"
            self._write_json(inventory_path, self.inventory)

            def install(payload: dict, *, receipt_patch: dict | None = None):
                payload = copy.deepcopy(payload)
                payload["inventory_relative_path"] = str(inventory_path.relative_to(PROJECT_ROOT))
                self._write_json(manifest_path, payload)
                conn.execute("delete from system_meta where key = ?", (VISUAL_RECEIPT_KEY,))
                self._install_manifest_receipt(
                    conn,
                    manifest_path,
                    inventory_path=inventory_path,
                    receipt_patch=receipt_patch,
                )

            conn = db.connect(Path(db_tmp) / "tamper.sqlite")
            try:
                db.init_schema(conn)
                baseline = self._structural_manifest_payload(
                    inventory_relative_path=str(inventory_path.relative_to(PROJECT_ROOT))
                )
                install(baseline)
                manifest, _report = self._load_active_manifest(conn)

                missing = copy.deepcopy(baseline)
                missing["entries"].pop()
                install(missing)
                with self.subTest(case="resigned_missing_entry"), self.assertRaises(ValueError):
                    self._load_active_manifest(conn)

                duplicate = copy.deepcopy(baseline)
                duplicate["entries"].append(copy.deepcopy(duplicate["entries"][0]))
                install(duplicate)
                with self.subTest(case="resigned_duplicate_entry"), self.assertRaises(ValueError):
                    self._load_active_manifest(conn)

                extra = copy.deepcopy(baseline)
                extra_entry = copy.deepcopy(extra["entries"][0])
                extra_entry["question_id"] = "QB12-UNINVENTORIED-VISUAL-01"
                extra["entries"].append(extra_entry)
                install(extra)
                with self.subTest(case="resigned_extra_entry"), self.assertRaises(ValueError):
                    self._load_active_manifest(conn)

                install(baseline)
                tampered_file = copy.deepcopy(baseline)
                tampered_file["entries"][0]["alt_text"] += "篡改"
                self._write_json(manifest_path, tampered_file)
                with self.subTest(case="manifest_changed_after_receipt"), self.assertRaises(ValueError):
                    self._load_active_manifest(conn)

                install(baseline, receipt_patch={"manifest_sha256": "0" * 64})
                with self.subTest(case="receipt_hash_tamper"), self.assertRaises(ValueError):
                    self._load_active_manifest(conn)

                install(baseline, receipt_patch={"activation_eligible": True})
                with self.subTest(case="receipt_unknown_field"), self.assertRaises(ValueError):
                    self._load_active_manifest(conn)

                install(baseline)
                tampered_inventory = copy.deepcopy(self.inventory)
                tampered_inventory["groups"][0]["items"][0]["required"] = False
                self._write_json(inventory_path, tampered_inventory)
                with self.subTest(case="inventory_changed_after_receipt"), self.assertRaises(ValueError):
                    self._load_active_manifest(conn)

                for case, mutation in (
                    ("resigned_empty_groups", []),
                    ("resigned_deleted_required_group", copy.deepcopy(self.inventory["groups"][1:])),
                ):
                    resigned_inventory = copy.deepcopy(self.inventory)
                    resigned_inventory["groups"] = mutation
                    self._write_json(inventory_path, resigned_inventory)
                    install(baseline)
                    with self.subTest(case=case), self.assertRaises(ValueError):
                        self._load_active_manifest(conn)
                self._write_json(inventory_path, self.inventory)
            finally:
                conn.close()
            entry = self.geo_group["items"][0]
            self.assertIsNone(
                manifest.lookup(
                    entry["question_id"],
                    self.geo_group["item_version"],
                    "0" * 64,
                )
            )


class QuestionVisualSecurityTests(QuestionVisualV51TestCase):
    def _bound_entry(self, scene: dict) -> dict:
        return {
            "question_id": "Q-VISUAL-TEST",
            "item_version": "item.v1",
            "question_digest_sha256": "a" * 64,
            "required": True,
            **copy.deepcopy(scene),
        }

    def test_scene_allowlist_accepts_only_typed_exact_schemas(self):
        validate = self._entry_validator()
        self.assertEqual(ALLOWED_SCENE_TYPES, set(self.inventory["allowed_scene_types"]))
        for scene in self.scene_fixture["scenes"]:
            self.assertEqual(self._bound_entry(scene), validate(self._bound_entry(scene)))

            unknown = self._bound_entry(scene)
            unknown["scene"]["unexpected"] = "forbidden"
            with self.assertRaises(ValueError):
                validate(unknown)

        wrong_type = self._bound_entry(self.scene_fixture["scenes"][0])
        wrong_type["scene_type"] = "model_authored_svg"
        with self.assertRaises(ValueError):
            validate(wrong_type)

    def test_raw_svg_script_and_external_resources_are_rejected_before_rendering(self):
        validate = self._entry_validator()
        base = self._bound_entry(self.scene_fixture["scenes"][0])
        attacks = [
            ("raw_svg", "<svg><script>alert(1)</script></svg>"),
            ("script", "alert(1)"),
            ("external_url", "https://example.invalid/diagram.svg"),
            ("src", "data:image/svg+xml,<svg onload=alert(1)></svg>"),
        ]
        for key, value in attacks:
            attacked = copy.deepcopy(base)
            attacked["scene"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(attacked)

        for value in (
            "<svg viewBox='0 0 10 10'></svg>",
            "<script>alert(1)</script>",
            "javascript:alert(1)",
            "https://example.invalid/a.png",
        ):
            attacked = copy.deepcopy(base)
            attacked["alt_text"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(attacked)

    def test_manifest_fixture_contains_no_forbidden_scene_keys_or_payloads(self):
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn(str(key).casefold(), FORBIDDEN_SCENE_KEYS)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, str):
                self.assertNotRegex(value, r"(?i)<\s*(?:svg|script)|javascript:|https?://|data:image/svg")

        walk(self.scene_fixture)

    def test_recursive_exact_scene_schemas_enforce_budgets_and_references(self):
        validate = self._entry_validator()
        by_type = {
            scene["scene_type"]: self._bound_entry(scene)
            for scene in self.scene_fixture["scenes"]
        }

        nested_unknown_attacks = []
        number_line = copy.deepcopy(by_type["number_line"])
        number_line["scene"]["axis"]["units"] = "model-authored"
        nested_unknown_attacks.append(("number_line_axis_unknown", number_line))
        number_line_tick = copy.deepcopy(by_type["number_line"])
        number_line_tick["scene"]["ticks"][0]["style"] = "red"
        nested_unknown_attacks.append(("number_line_tick_unknown", number_line_tick))
        number_line_point = copy.deepcopy(by_type["number_line"])
        number_line_point["scene"]["points"][0]["href"] = "https://example.invalid"
        nested_unknown_attacks.append(("number_line_point_unknown", number_line_point))

        cube = copy.deepcopy(by_type["cube_net"])
        cube["scene"]["cells"][0]["rotation"] = 90
        nested_unknown_attacks.append(("cube_cell_unknown", cube))

        orthographic = copy.deepcopy(by_type["orthographic_view"])
        orthographic["scene"]["views"][0]["camera"] = "perspective"
        nested_unknown_attacks.append(("orthographic_view_unknown", orthographic))

        geometry_point = copy.deepcopy(by_type["simple_geometry"])
        geometry_point["scene"]["points"][0]["color"] = "red"
        nested_unknown_attacks.append(("geometry_point_unknown", geometry_point))
        geometry_segment = copy.deepcopy(by_type["simple_geometry"])
        geometry_segment["scene"]["segments"][0]["onclick"] = "alert(1)"
        nested_unknown_attacks.append(("geometry_segment_unknown", geometry_segment))
        geometry_marker = copy.deepcopy(by_type["simple_geometry"])
        geometry_marker["scene"]["markers"][0]["raw_svg"] = "<svg/>"
        nested_unknown_attacks.append(("geometry_marker_unknown", geometry_marker))

        for name, attacked in nested_unknown_attacks:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(attacked)

        budget_attacks = []
        too_many_ticks = copy.deepcopy(by_type["number_line"])
        too_many_ticks["scene"]["ticks"] = [
            {"value": index, "label": str(index)}
            for index in range(SCENE_BUDGETS["number_line"]["ticks"] + 1)
        ]
        too_many_ticks["scene"]["axis"].update({"min": 0, "max": 100, "origin": 0})
        budget_attacks.append(("number_line_ticks", too_many_ticks))

        too_many_points = copy.deepcopy(by_type["number_line"])
        too_many_points["scene"]["points"] = [
            {"key": f"p{index}", "value": 0, "label": str(index)}
            for index in range(SCENE_BUDGETS["number_line"]["points"] + 1)
        ]
        budget_attacks.append(("number_line_points", too_many_points))

        cube_over_budget = copy.deepcopy(by_type["cube_net"])
        cube_over_budget["scene"]["cells"].append(
            {"key": "f7", "x": 4, "y": 1, "label": "7"}
        )
        budget_attacks.append(("cube_net_cells", cube_over_budget))

        orthographic_over_budget = copy.deepcopy(by_type["orthographic_view"])
        orthographic_over_budget["scene"]["views"][0]["width"] = (
            SCENE_BUDGETS["orthographic_view"]["width"] + 1
        )
        budget_attacks.append(("orthographic_width", orthographic_over_budget))

        geometry_over_budget = copy.deepcopy(by_type["simple_geometry"])
        geometry_over_budget["scene"]["points"] = [
            {"key": f"p{index}", "x": index, "y": index, "label": str(index)}
            for index in range(SCENE_BUDGETS["simple_geometry"]["points"] + 1)
        ]
        budget_attacks.append(("geometry_points", geometry_over_budget))

        for name, attacked in budget_attacks:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(attacked)

        reference_attacks = []
        duplicate_cube_cell = copy.deepcopy(by_type["cube_net"])
        duplicate_cube_cell["scene"]["cells"][1]["x"] = duplicate_cube_cell["scene"]["cells"][0]["x"]
        duplicate_cube_cell["scene"]["cells"][1]["y"] = duplicate_cube_cell["scene"]["cells"][0]["y"]
        reference_attacks.append(("cube_duplicate_coordinate", duplicate_cube_cell))

        orthographic_out_of_bounds = copy.deepcopy(by_type["orthographic_view"])
        orthographic_out_of_bounds["scene"]["views"][0]["filled_cells"].append([99, 99])
        reference_attacks.append(("orthographic_out_of_bounds", orthographic_out_of_bounds))

        geometry_bad_segment = copy.deepcopy(by_type["simple_geometry"])
        geometry_bad_segment["scene"]["segments"][0]["to"] = "missing-point"
        reference_attacks.append(("geometry_segment_reference", geometry_bad_segment))

        geometry_bad_marker = copy.deepcopy(by_type["simple_geometry"])
        geometry_bad_marker["scene"]["markers"][0]["arms"] = ["a", "missing-point"]
        reference_attacks.append(("geometry_marker_reference", geometry_bad_marker))

        duplicate_number_line_key = copy.deepcopy(by_type["number_line"])
        duplicate_number_line_key["scene"]["points"][1]["key"] = (
            duplicate_number_line_key["scene"]["points"][0]["key"]
        )
        reference_attacks.append(("number_line_duplicate_point_key", duplicate_number_line_key))

        for name, attacked in reference_attacks:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(attacked)

        numeric_attacks = []
        infinite_axis = copy.deepcopy(by_type["number_line"])
        infinite_axis["scene"]["axis"]["max"] = float("inf")
        numeric_attacks.append(("number_line_infinite", infinite_axis))
        oversized_span = copy.deepcopy(by_type["number_line"])
        oversized_span["scene"]["axis"]["max"] = 1_000_001
        numeric_attacks.append(("number_line_span", oversized_span))
        oversized_cube = copy.deepcopy(by_type["cube_net"])
        oversized_cube["scene"]["cells"][0]["x"] = 100
        numeric_attacks.append(("cube_coordinate_span", oversized_cube))
        nan_geometry = copy.deepcopy(by_type["simple_geometry"])
        nan_geometry["scene"]["points"][0]["x"] = float("nan")
        numeric_attacks.append(("geometry_nan", nan_geometry))
        outside_geometry = copy.deepcopy(by_type["simple_geometry"])
        outside_geometry["scene"]["points"][0]["y"] = 96
        numeric_attacks.append(("geometry_viewbox", outside_geometry))
        for name, attacked in numeric_attacks:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(attacked)

        for scene_type, entry in by_type.items():
            with self.subTest(valid_scene=scene_type):
                self.assertEqual(entry, validate(copy.deepcopy(entry)))


class QuestionVisualSchedulingTests(QuestionVisualV51TestCase):
    def test_missing_or_resigned_incomplete_receipt_never_falls_back_to_text(self):
        with self._seeded_runtime_db() as (path, _item, _digest, _review_record_id), closing(db.connect(path)) as conn:
            question = db.get_question(conn, self.default_visual_item["id"])
            before = conn.execute("select count(*) from flow_steps").fetchone()[0]
            with self.subTest(case="missing_receipt"), self.assertRaises(daily_runtime.ChildSafeRuntimeError):
                self._create_question_step(conn, question)
            self.assertEqual(before, conn.execute("select count(*) from flow_steps").fetchone()[0])

        fixture_root = PROJECT_ROOT / "tests/fixtures"
        with tempfile.TemporaryDirectory(prefix="visual_resigned_missing_group_", dir=fixture_root) as tmpdir:
            root = Path(tmpdir)
            inventory_path = root / "inventory.json"
            manifest_path = root / "manifest.json"
            inventory = copy.deepcopy(self.inventory)
            inventory["groups"] = [inventory["groups"][0]]
            manifest = json.loads(PRODUCTION_MANIFEST_PATH.read_text(encoding="utf-8"))
            manifest["inventory_relative_path"] = str(inventory_path.relative_to(PROJECT_ROOT))
            manifest["entries"] = []
            self._write_json(inventory_path, inventory)
            self._write_json(manifest_path, manifest)
            with self._seeded_runtime_db() as (path, _item, _digest, _review_record_id), closing(db.connect(path)) as conn:
                self._install_manifest_receipt(conn, manifest_path, inventory_path=inventory_path)
                question = db.get_question(conn, self.default_visual_item["id"])
                before = conn.execute("select count(*) from flow_steps").fetchone()[0]
                with self.subTest(case="resigned_deleted_group"), self.assertRaises(daily_runtime.ChildSafeRuntimeError):
                    self._create_question_step(conn, question)
                self.assertEqual(before, conn.execute("select count(*) from flow_steps").fetchone()[0])

    def test_required_visual_missing_binding_blocks_step_and_attempt_creation(self):
        with self._seeded_runtime_db() as (path, _item, _digest, _review_record_id), closing(db.connect(path)) as conn:
            self._install_manifest_receipt(conn, MISSING_MANIFEST_PATH)
            question = db.get_question(conn, self.default_visual_item["id"])
            before_steps = conn.execute("select count(*) from flow_steps").fetchone()[0]
            before_attempts = conn.execute("select count(*) from attempts").fetchone()[0]
            error = None
            try:
                self._create_question_step(conn, question)
            except (ValueError, RuntimeError) as exc:
                error = exc
            after_steps = conn.execute("select count(*) from flow_steps").fetchone()[0]
            after_attempts = conn.execute("select count(*) from attempts").fetchone()[0]
            self.assertEqual(before_steps, after_steps, "required visual failure scheduled a question step")
            self.assertEqual(before_attempts, after_attempts, "required visual failure created an attempt")
            self.assertIsNotNone(error, "missing required visual did not fail closed")
            self.assertRegex(str(error), r"(?i)visual|manifest|scene|图")

    def test_exact_bound_visual_is_projected_and_photo_answer_remains_available(self):
        with self._structural_manifest_file() as manifest_path:
            with self._seeded_runtime_db() as (path, _item, digest, _review_record_id), closing(db.connect(path)) as conn:
                self._install_manifest_receipt(conn, manifest_path)
                question = db.get_question(conn, self.default_visual_item["id"])
                step_id = self._create_question_step(conn, question)
                row = conn.execute("select * from flow_steps where id = ?", (step_id,)).fetchone()
                package = db.json_load(row["prompt_package_json"], {})
                self.assertEqual("text_photo", package["answer_input_mode"])
                self.assertTrue(package["upload_enabled"])
                self.assertIn("question_visual", package)
                visual = package["question_visual"]
                self.assertEqual(CHILD_VISUAL_KEYS, set(visual))
                self.assertEqual("cube_net", visual["scene_type"])
                self.assertTrue(visual["alt_text"])
                self.assertTrue(visual["long_description"])
                self.assertNotIn(digest, json.dumps(visual, ensure_ascii=False))

    def test_renderer_resource_failure_in_browser_creates_zero_attempts(self):
        with self._structural_manifest_file() as manifest_path:
            with self._seeded_runtime_db() as (path, _item, _digest, _review_record_id):
                with closing(db.connect(path)) as conn:
                    self._install_manifest_receipt(conn, manifest_path)
                    question = db.get_question(conn, self.default_visual_item["id"])
                    step_id = self._create_question_step(conn, question)
                    conn.execute(
                        "update daily_flows set current_step_id = ? where id = ?",
                        (step_id, "FLOW-VISUAL-V51"),
                    )
                    conn.commit()
                    before = conn.execute("select count(*) from attempts").fetchone()[0]

                with self._runtime_env():
                    httpd, base_url = server.start_test_server(path)
                    try:
                        completed = subprocess.run(
                            ["node", str(BROWSER_FAILURE_FIXTURE), "--base-url", base_url],
                            cwd=PROJECT_ROOT,
                            text=True,
                            capture_output=True,
                            timeout=60,
                            check=False,
                        )
                    finally:
                        httpd.shutdown()
                        httpd.server_close()
                with closing(db.connect(path)) as conn:
                    after = conn.execute("select count(*) from attempts").fetchone()[0]
                self.assertEqual(before, after, "renderer resource failure created an attempt")
                self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)

    def test_required_visual_gate_blocks_real_start_api_with_503_and_zero_writes(self):
        with self._seeded_runtime_db(create_flow=False) as (
            path,
            _item,
            _digest,
            review_record_id,
        ), closing(db.connect(path)) as conn:
            self._install_manifest_receipt(conn, MISSING_MANIFEST_PATH)
            question = db.get_question(conn, self.default_visual_item["id"])
            before = {
                table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                for table in ("learning_sessions", "daily_flows", "flow_steps", "attempts")
            }
            selected = self._selected_question_packet(question, review_record_id)
            with self._runtime_env(), patch.object(
                daily_runtime.DailyLearningRuntime,
                "_select_first_review_question",
                return_value=selected,
            ):
                httpd, base_url = server.start_test_server(path)
                try:
                    status, payload = self._request_json(
                        "POST",
                        base_url,
                        "/api/daily-flow/review/start",
                        {"client_day_key": "2099-07-15"},
                    )
                finally:
                    httpd.shutdown()
                    httpd.server_close()

            with closing(db.connect(path)) as after_conn:
                after = {
                    table: after_conn.execute(f"select count(*) from {table}").fetchone()[0]
                    for table in ("learning_sessions", "daily_flows", "flow_steps", "attempts")
                }
            self.assertEqual(503, status, payload)
            self.assertEqual("blocked", payload.get("child_state"), payload)
            self.assertRegex(json.dumps(payload, ensure_ascii=False), r"图|题面|视觉|资源")
            self.assertEqual(before, after, "required visual API gate left partial learning writes")

    def test_non_inventory_question_uses_text_fallback_and_creates_zero_attempts(self):
        with self._structural_manifest_file() as manifest_path, self._seeded_runtime_db(
            question_fixture=self.eq_denom_item,
            create_flow=False,
        ) as (path, item, _digest, review_record_id):
            with closing(db.connect(path)) as conn:
                self._install_manifest_receipt(conn, manifest_path)
                question = db.get_question(conn, item["id"])
            selected = self._selected_question_packet(question, review_record_id)
            with self._runtime_env(), patch.object(
                daily_runtime.DailyLearningRuntime,
                "_select_first_review_question",
                return_value=selected,
            ):
                httpd, base_url = server.start_test_server(path)
                try:
                    status, payload = self._request_json(
                        "POST",
                        base_url,
                        "/api/daily-flow/review/start",
                        {"client_day_key": "2099-07-16"},
                    )
                finally:
                    httpd.shutdown()
                    httpd.server_close()
            self.assertEqual(200, status, payload)
            self.assertEqual("current_step", payload.get("child_state"), payload)
            self.assertNotIn("question_visual", payload.get("current_step") or {})
            with closing(db.connect(path)) as conn:
                self.assertEqual(1, conn.execute("select count(*) from flow_steps").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from attempts").fetchone()[0])

    def test_child_bootstrap_visual_dto_is_exact_and_has_no_lineage_leakage(self):
        with self._structural_manifest_file() as manifest_path, self._seeded_runtime_db() as (
            path,
            _item,
            digest,
            _review_record_id,
        ):
            with closing(db.connect(path)) as conn:
                self._install_manifest_receipt(conn, manifest_path)
                question = db.get_question(conn, self.default_visual_item["id"])
                step_id = self._create_question_step(conn, question)
                conn.execute(
                    "update daily_flows set current_step_id = ?, status = 'reviewing' where id = ?",
                    (step_id, "FLOW-VISUAL-V51"),
                )
                conn.commit()
            with self._runtime_env():
                httpd, base_url = server.start_test_server(path)
                try:
                    status, payload = self._request_json("GET", base_url, "/api/child-bootstrap")
                finally:
                    httpd.shutdown()
                    httpd.server_close()
            self.assertEqual(200, status, payload)
            visual = (payload.get("current_step") or {}).get("question_visual")
            self.assertIsInstance(visual, dict, payload)
            self.assertEqual(CHILD_VISUAL_KEYS, set(visual))
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn(digest, serialized)
            self.assertNotRegex(serialized, r"tests/fixtures|data/question_visuals|[0-9a-f]{64}")

            def walk(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        self.assertNotIn(str(key), CHILD_VISUAL_FORBIDDEN_KEYS)
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)

            walk(visual)

    def test_renderer_recovery_reload_and_double_click_create_exactly_one_attempt(self):
        with self._structural_manifest_file() as manifest_path, self._seeded_runtime_db() as (
            path,
            _item,
            _digest,
            _review_record_id,
        ):
            with closing(db.connect(path)) as conn:
                self._install_manifest_receipt(conn, manifest_path)
                question = db.get_question(conn, self.default_visual_item["id"])
                step_id = self._create_question_step(conn, question)
                conn.execute(
                    "update daily_flows set current_step_id = ?, status = 'reviewing' where id = ?",
                    (step_id, "FLOW-VISUAL-V51"),
                )
                conn.commit()
            with self._runtime_env(), patch.object(
                server.LearningHandler,
                "_start_v3_flow_processing",
                autospec=True,
            ):
                httpd, base_url = server.start_test_server(path)
                try:
                    completed = subprocess.run(
                        ["node", str(BROWSER_RECOVERY_FIXTURE), "--base-url", base_url],
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
            self.assertTrue(report["visual_present_before_reload"])
            self.assertTrue(report["visual_present_after_reload"])
            self.assertEqual(1, report["submit_request_count"])
            with closing(db.connect(path)) as conn:
                attempts = conn.execute("select * from attempts order by created_at, id").fetchall()
                self.assertEqual(1, len(attempts))
                self.assertEqual("pending_review", attempts[0]["grading_status"])


class TypedQuestionVisualRendererTests(QuestionVisualV51TestCase):
    def test_renderer_public_api_has_no_raw_markup_network_or_model_svg_lane(self):
        js = self._require_file(PRODUCTION_RENDERER_JS, "typed question visual renderer").read_text(
            encoding="utf-8"
        )
        css = self._require_file(PRODUCTION_RENDERER_CSS, "typed question visual stylesheet").read_text(
            encoding="utf-8"
        )
        match = re.search(
            r"window\.QuestionVisualRenderer\s*=\s*Object\.freeze\s*\(\s*\{(?P<body>.*?)\}\s*\)",
            js,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "window.QuestionVisualRenderer public API is missing")
        names = set(
            re.findall(
                r"(?:^|,)\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*(?=[:,]|$)",
                match.group("body").strip(),
            )
        )
        self.assertEqual(EXPECTED_RENDERER_API, names)
        self.assertIn("createElementNS", js)
        self.assertNotRegex(js, r"\.innerHTML\s*=|insertAdjacentHTML|DOMParser|document\.write")
        self.assertNotRegex(js, r"\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon")
        self.assertNotRegex(js, r"\beval\s*\(|new\s+Function|javascript:")
        self.assertNotRegex(js, r"raw_svg|model[_-]?authored[_-]?svg|https?://|data:image/svg")
        self.assertNotRegex(css, r"(?i)@import|url\s*\(|https?://|data:image|javascript:")
        for scene_type in ALLOWED_SCENE_TYPES:
            self.assertIn(scene_type, js)

    def test_four_typed_scenes_render_deterministically_with_accessibility_responsive_and_print_contracts(self):
        self._require_file(PRODUCTION_RENDERER_JS, "typed question visual renderer")
        self._require_file(PRODUCTION_RENDERER_CSS, "typed question visual stylesheet")
        completed = subprocess.run(
            [
                "node",
                str(BROWSER_RENDERER_FIXTURE),
                "--renderer",
                str(PRODUCTION_RENDERER_JS),
                "--style",
                str(PRODUCTION_RENDERER_CSS),
                "--scenes",
                str(SCENES_PATH),
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertEqual(ALLOWED_SCENE_TYPES, set(report["deterministic_scene_types"]))
        self.assertTrue(report["alt_and_long_descriptions"])
        self.assertTrue(report["viewport_1280_no_overflow"])
        self.assertTrue(report["viewport_390_no_overflow"])
        self.assertTrue(report["print_monochrome"])
        self.assertTrue(report["no_forbidden_dom"])
        self.assertEqual([], report["runtime_network_calls"])
        self.assertEqual([], report["browser_network_requests"])
        self.assertEqual(ALLOWED_SCENE_TYPES, set(report["scene_reports"]))
        for scene_type, scene_report in report["scene_reports"].items():
            with self.subTest(scene_type=scene_type):
                self.assertEqual({"1280", "390"}, set(scene_report["viewports"]))
                desktop = scene_report["viewports"]["1280"]
                mobile = scene_report["viewports"]["390"]
                for viewport_report in (desktop, mobile):
                    self.assertTrue(viewport_report["valid_view_box"])
                    self.assertTrue(viewport_report["geometry_inside"])
                    self.assertTrue(viewport_report["no_overflow"])
                    self.assertEqual([], viewport_report["missing_labels"])
                    self.assertGreaterEqual(
                        viewport_report["graphic_count"],
                        viewport_report["minimum_graphics"],
                    )
                    self.assertGreater(viewport_report["root_width"], 40)
                    self.assertGreater(viewport_report["root_height"], 40)
                self.assertEqual(desktop["view_box"], mobile["view_box"])
                self.assertLessEqual(mobile["root_width"], 390)
                self.assertTrue(scene_report["print"]["monochrome"])
                self.assertTrue(scene_report["print"]["visible"])
                self.assertTrue(scene_report["print"]["no_overflow"])
                self.assertTrue(scene_report["print"]["view_box"])


if __name__ == "__main__":
    unittest.main()
