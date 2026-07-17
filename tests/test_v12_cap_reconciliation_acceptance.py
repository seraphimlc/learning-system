import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_CHECKPOINT_DIR = (
    PROJECT_ROOT / "data/question_banks/math/.v12_pilot_six_checkpoints"
)
EXPECTED_RECONCILED_NODES = {
    "M-BRIDGE-MOTION-CHASE",
    "M-G7-EQ-DENOM",
    "M-G7-GEO-VIEWS",
    "M-G7-RATIONAL-ADD-SUB",
    "M-PRE-UNIT-CONVERSION",
}


def _load_v12_build_module():
    script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
    spec = importlib.util.spec_from_file_location(
        "build_math_question_bank_v12_cap_reconciliation_acceptance",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the v12 question-bank build module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _file_hash_manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
    }


def _manifest_sha256(manifest: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class V12CapReconciliationAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_v12_build_module()
        cls.production_hashes_before = _file_hash_manifest(PRODUCTION_CHECKPOINT_DIR)
        cls.production_manifest_sha256_before = _manifest_sha256(
            cls.production_hashes_before
        )

    @classmethod
    def tearDownClass(cls):
        hashes_after = _file_hash_manifest(PRODUCTION_CHECKPOINT_DIR)
        if hashes_after != cls.production_hashes_before:
            before_paths = set(cls.production_hashes_before)
            after_paths = set(hashes_after)
            changed = sorted(
                path
                for path in before_paths & after_paths
                if cls.production_hashes_before[path] != hashes_after[path]
            )
            raise AssertionError(
                "production checkpoint directory changed during QA: "
                f"added={sorted(after_paths - before_paths)}, "
                f"removed={sorted(before_paths - after_paths)}, changed={changed}"
            )

    def _temporary_checkpoint_copy(self, parent: Path) -> Path:
        destination = parent / "v12_pilot_six_checkpoints"
        shutil.copytree(PRODUCTION_CHECKPOINT_DIR, destination)
        return destination

    def _completed_node_ids(self, checkpoint_dir: Path) -> list[str]:
        completed = []
        for checkpoint_path in sorted(checkpoint_dir.glob("*.json")):
            checkpoint = _read_json(checkpoint_path)
            if checkpoint.get("status") == "completed":
                completed.append(str(checkpoint["node_id"]))
        return completed

    def _tracker_node_ids(self, checkpoint_dir: Path) -> list[str]:
        suffix = ".model-budget.json"
        return sorted(
            path.name.removesuffix(suffix)
            for path in (checkpoint_dir / ".run-state").glob(f"*{suffix}")
        )

    def _reconciled_node_ids(self, checkpoint_dir: Path) -> set[str]:
        reconciled = set()
        for node_id in self._tracker_node_ids(checkpoint_dir):
            state = _read_json(
                checkpoint_dir / ".run-state" / f"{node_id}.model-budget.json"
            )
            if any(
                migration.get("migration_reason")
                == "legacy_state_cap_pollution_reconciled_to_sealed_checkpoint"
                for migration in state.get("migrations", [])
            ):
                reconciled.add(node_id)
        return reconciled

    def _cap_divergence_nodes(self, checkpoint_dir: Path) -> set[str]:
        divergent = set()
        for node_id in self._completed_node_ids(checkpoint_dir):
            checkpoint = _read_json(checkpoint_dir / f"{node_id}.json")
            state = _read_json(
                checkpoint_dir / ".run-state" / f"{node_id}.model-budget.json"
            )
            checkpoint_caps = (
                checkpoint["model_budget"]["max_semantic_calls"],
                checkpoint["model_budget"]["max_provider_attempts"],
            )
            state_caps = (
                state["max_semantic_calls"],
                state["max_provider_attempts"],
            )
            if checkpoint_caps != state_caps:
                divergent.add(node_id)
        return divergent

    def _initialize_tracker(self, checkpoint_dir: Path, node_id: str, run_id: str):
        return self.module._ModelBudgetTracker(
            checkpoint_dir=checkpoint_dir,
            node_id=node_id,
            run_id=run_id,
            max_semantic_calls=512,
            max_provider_attempts=1536,
        )

    def test_01_all_existing_trackers_initialize_on_real_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = self._temporary_checkpoint_copy(Path(tmp))
            tracker_node_ids = self._tracker_node_ids(checkpoint_dir)
            completed_node_ids = self._completed_node_ids(checkpoint_dir)
            divergence_nodes = self._cap_divergence_nodes(checkpoint_dir)
            reconciled_node_ids = self._reconciled_node_ids(checkpoint_dir)
            checkpoint_paths = sorted(checkpoint_dir.glob("*.json"))
            checkpoint_statuses = {
                path.stem: str(_read_json(path).get("status") or "")
                for path in checkpoint_paths
            }

            self.assertEqual(56, len(tracker_node_ids))
            self.assertTrue(
                set(checkpoint_statuses).issubset(set(tracker_node_ids)),
                "every existing checkpoint must have a tracker authority",
            )
            self.assertEqual(set(), divergence_nodes)
            self.assertEqual(EXPECTED_RECONCILED_NODES, reconciled_node_ids)

            initialized = []
            failures = {}
            verified_reconciliations = set()
            for index, node_id in enumerate(tracker_node_ids, start=1):
                state_before = _read_json(
                    checkpoint_dir / ".run-state" / f"{node_id}.model-budget.json"
                )
                try:
                    tracker = self.module._ModelBudgetTracker(
                        checkpoint_dir=checkpoint_dir,
                        node_id=node_id,
                        run_id=f"QA-ALL-TRACKERS-{index:02d}",
                        max_semantic_calls=512,
                        max_provider_attempts=1536,
                        persist_on_init=False,
                    )
                    snapshot = tracker.snapshot()
                    initialized.append(node_id)
                except Exception as exc:  # The evidence must retain every failed node.
                    failures[node_id] = f"{type(exc).__name__}: {exc}"
                    continue

                self.assertEqual(
                    state_before["semantic_calls"], snapshot["semantic_calls"]
                )
                self.assertEqual(
                    state_before["provider_attempts"], snapshot["provider_attempts"]
                )
                self.assertEqual(
                    state_before["max_semantic_calls"],
                    snapshot["max_semantic_calls"],
                )
                self.assertEqual(
                    state_before["max_provider_attempts"],
                    snapshot["max_provider_attempts"],
                )

                reconciliation = next(
                    (
                        migration
                        for migration in snapshot.get("migrations", [])
                        if migration.get("migration_reason")
                        == "legacy_state_cap_pollution_reconciled_to_sealed_checkpoint"
                    ),
                    None,
                )
                if node_id in reconciled_node_ids:
                    self.assertIsNotNone(reconciliation)
                    self.assertEqual(
                        reconciliation,
                        _read_json(tracker.marker_path)["legacy_cap_reconciliation"],
                    )
                    verified_reconciliations.add(node_id)

            print(json.dumps({
                "case": "all_existing_tracker_initialization",
                "checkpoint_count": len(checkpoint_paths),
                "completed_checkpoint_count": len(completed_node_ids),
                "incomplete_checkpoint_nodes": sorted(
                    node_id
                    for node_id, status in checkpoint_statuses.items()
                    if status != "completed"
                ),
                "tracker_count": len(tracker_node_ids),
                "initialized": len(initialized),
                "failed_nodes": failures,
                "cap_divergence_nodes": sorted(divergence_nodes),
                "reconciled_nodes": sorted(verified_reconciliations),
            }, ensure_ascii=False, sort_keys=True))
            self.assertEqual({}, failures)
            self.assertEqual(len(tracker_node_ids), len(initialized))
            self.assertEqual(EXPECTED_RECONCILED_NODES, verified_reconciliations)

    def test_02_state_count_plus_one_fails_closed(self):
        node_id = "M-G7-EQ-DENOM"
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = self._temporary_checkpoint_copy(Path(tmp))
            state_path = (
                checkpoint_dir / ".run-state" / f"{node_id}.model-budget.json"
            )
            state = _read_json(state_path)
            state["semantic_calls"] += 1
            _write_json(state_path, state)

            with self.assertRaisesRegex(
                self.module.model_router.ModelCallError,
                r"budget.*(count|reconcil|diverg|integrity)",
            ) as raised:
                self._initialize_tracker(
                    checkpoint_dir,
                    node_id,
                    "QA-CAP-COUNT-PLUS-ONE",
                )
            print(json.dumps({
                "case": "state_count_plus_one",
                "node_id": node_id,
                "result": "rejected",
                "error": str(raised.exception),
            }, ensure_ascii=False, sort_keys=True))

    def test_03_checkpoint_seal_tamper_fails_closed(self):
        node_id = "M-G7-GEO-VIEWS"
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = self._temporary_checkpoint_copy(Path(tmp))
            checkpoint_path = checkpoint_dir / f"{node_id}.json"
            checkpoint = _read_json(checkpoint_path)
            checkpoint.setdefault("stage_counters", {})["qa_seal_tamper"] = 1
            _write_json(checkpoint_path, checkpoint)

            with self.assertRaisesRegex(
                self.module.model_router.ModelCallError,
                r"checkpoint.*(seal|integrity)",
            ) as raised:
                self._initialize_tracker(
                    checkpoint_dir,
                    node_id,
                    "QA-CAP-CHECKPOINT-SEAL-TAMPER",
                )
            print(json.dumps({
                "case": "checkpoint_seal_tamper",
                "node_id": node_id,
                "result": "rejected",
                "error": str(raised.exception),
            }, ensure_ascii=False, sort_keys=True))

    def test_04_resigned_migration_marker_tamper_fails_closed(self):
        node_id = "M-G7-RATIONAL-ADD-SUB"
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = self._temporary_checkpoint_copy(Path(tmp))
            tracker = self._initialize_tracker(
                checkpoint_dir,
                node_id,
                "QA-CAP-MARKER-CREATE",
            )
            marker = _read_json(tracker.marker_path)
            marker["legacy_cap_reconciliation"]["equal_counts"][
                "semantic_calls"
            ] += 1
            marker["integrity_sha256"] = (
                self.module._model_budget_marker_integrity_sha256(marker)
            )
            _write_json(tracker.marker_path, marker)

            with self.assertRaisesRegex(
                self.module.model_router.ModelCallError,
                r"budget.*marker.*reconciliation.*(commitment|count)",
            ) as raised:
                self._initialize_tracker(
                    checkpoint_dir,
                    node_id,
                    "QA-CAP-MARKER-TAMPER-RESUME",
                )
            print(json.dumps({
                "case": "resigned_migration_marker_tamper",
                "node_id": node_id,
                "outer_marker_integrity": "recomputed",
                "result": "rejected",
                "error": str(raised.exception),
            }, ensure_ascii=False, sort_keys=True))

    def test_05_migrated_motion_chase_advances_and_resumes_on_copy(self):
        node_id = "M-BRIDGE-MOTION-CHASE"
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = self._temporary_checkpoint_copy(Path(tmp))
            tracker = self._initialize_tracker(
                checkpoint_dir,
                node_id,
                "QA-MOTION-CHASE-ADVANCE",
            )
            before = tracker.snapshot()
            reconciliation = next(
                migration
                for migration in before["migrations"]
                if migration.get("migration_reason")
                == "legacy_state_cap_pollution_reconciled_to_sealed_checkpoint"
            )
            self.assertEqual(
                {"semantic_calls": 64, "provider_attempts": 75},
                reconciliation["equal_counts"],
            )
            self.assertGreater(
                before["semantic_calls"],
                reconciliation["equal_counts"]["semantic_calls"],
            )
            self.assertGreater(
                before["provider_attempts"],
                reconciliation["equal_counts"]["provider_attempts"],
            )

            tracker.reserve_semantic_call("qa_motion_chase_post_completion_semantic")
            tracker.reserve_provider_attempt("qa_motion_chase_post_completion_provider")
            tracker.mark_completed()
            advanced = tracker.snapshot()

            checkpoint_path = checkpoint_dir / f"{node_id}.json"
            checkpoint = _read_json(checkpoint_path)
            checkpoint["model_budget"] = advanced
            checkpoint["completed_node_receipt"] = (
                self.module._completed_checkpoint_node_receipt(
                    node_entry=checkpoint["node"],
                    graph_version=checkpoint["graph_version"],
                    repair_chain_hash=checkpoint["repair_chain_hash"],
                    model_budget_commitment=(
                        self.module._model_budget_receipt_commitment(advanced)
                    ),
                )
            )
            checkpoint["checkpoint_integrity_sha256"] = (
                self.module._checkpoint_integrity_sha256(checkpoint)
            )
            _write_json(checkpoint_path, checkpoint)

            resumed = self.module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-MOTION-CHASE-RESUME",
                max_semantic_calls=512,
                max_provider_attempts=1536,
                persist_on_init=False,
            ).snapshot()
            self.assertEqual(before["semantic_calls"] + 1, resumed["semantic_calls"])
            self.assertEqual(
                before["provider_attempts"] + 1,
                resumed["provider_attempts"],
            )
            self.assertEqual(120, resumed["max_semantic_calls"])
            self.assertEqual(300, resumed["max_provider_attempts"])
            print(json.dumps({
                "case": "migrated_motion_chase_advance_resume",
                "node_id": node_id,
                "migration_baseline": reconciliation["equal_counts"],
                "before": {
                    "semantic_calls": before["semantic_calls"],
                    "provider_attempts": before["provider_attempts"],
                },
                "resumed": {
                    "semantic_calls": resumed["semantic_calls"],
                    "provider_attempts": resumed["provider_attempts"],
                },
                "caps": {
                    "max_semantic_calls": resumed["max_semantic_calls"],
                    "max_provider_attempts": resumed["max_provider_attempts"],
                },
            }, ensure_ascii=False, sort_keys=True))

    def test_06_motion_chase_migration_baseline_tamper_fails_closed(self):
        node_id = "M-BRIDGE-MOTION-CHASE"
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = self._temporary_checkpoint_copy(Path(tmp))
            state_path = (
                checkpoint_dir / ".run-state" / f"{node_id}.model-budget.json"
            )
            marker_path = (
                checkpoint_dir
                / ".run-state"
                / f"{node_id}.model-budget-upgrade.json"
            )
            state = _read_json(state_path)
            baseline = state["counter_events"][0]
            self.assertEqual("legacy_baseline_import", baseline["event_type"])
            baseline["semantic_calls"] += 1
            baseline["event_sha256"] = self.module._model_budget_event_sha256(
                baseline
            )
            state["integrity_sha256"] = self.module._model_budget_integrity_sha256(
                state
            )
            marker = _read_json(marker_path)
            marker["budget_integrity_sha256"] = state["integrity_sha256"]
            marker["integrity_sha256"] = (
                self.module._model_budget_marker_integrity_sha256(marker)
            )
            _write_json(state_path, state)
            _write_json(marker_path, marker)

            with self.assertRaisesRegex(
                self.module.model_router.ModelCallError,
                r"budget.*(baseline|counter|chain|lineage|integrity|commitment)",
            ) as raised:
                self._initialize_tracker(
                    checkpoint_dir,
                    node_id,
                    "QA-MOTION-CHASE-BASELINE-TAMPER",
                )
            print(json.dumps({
                "case": "motion_chase_migration_baseline_tamper",
                "node_id": node_id,
                "outer_integrities": "recomputed",
                "result": "rejected",
                "error": str(raised.exception),
            }, ensure_ascii=False, sort_keys=True))

    def test_07_motion_chase_resigned_count_rollback_fails_closed(self):
        node_id = "M-BRIDGE-MOTION-CHASE"
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = self._temporary_checkpoint_copy(Path(tmp))
            state_path = (
                checkpoint_dir / ".run-state" / f"{node_id}.model-budget.json"
            )
            marker_path = (
                checkpoint_dir
                / ".run-state"
                / f"{node_id}.model-budget-upgrade.json"
            )
            state = _read_json(state_path)
            state["semantic_calls"] -= 1
            state["integrity_sha256"] = self.module._model_budget_integrity_sha256(
                state
            )
            marker = _read_json(marker_path)
            marker["budget_integrity_sha256"] = state["integrity_sha256"]
            marker["integrity_sha256"] = (
                self.module._model_budget_marker_integrity_sha256(marker)
            )
            _write_json(state_path, state)
            _write_json(marker_path, marker)

            with self.assertRaisesRegex(
                self.module.model_router.ModelCallError,
                r"budget.*(count|counter|rollback|lineage|integrity|commitment)",
            ) as raised:
                self._initialize_tracker(
                    checkpoint_dir,
                    node_id,
                    "QA-MOTION-CHASE-COUNT-ROLLBACK",
                )
            print(json.dumps({
                "case": "motion_chase_resigned_count_rollback",
                "node_id": node_id,
                "outer_integrities": "recomputed",
                "result": "rejected",
                "error": str(raised.exception),
            }, ensure_ascii=False, sort_keys=True))

    def test_99_production_checkpoint_file_hashes_are_unchanged(self):
        hashes_after = _file_hash_manifest(PRODUCTION_CHECKPOINT_DIR)
        self.assertEqual(self.production_hashes_before, hashes_after)
        print(json.dumps({
            "case": "production_checkpoint_zero_write",
            "file_count": len(hashes_after),
            "before_sha256": self.production_manifest_sha256_before,
            "after_sha256": _manifest_sha256(hashes_after),
            "result": "unchanged",
        }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
