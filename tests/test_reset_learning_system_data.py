from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from learning_system import daily_runtime, db, server
from scripts import reset_learning_system_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ResetLearningSystemDataTests(unittest.TestCase):
    def test_reset_clears_bad_question_bank_and_disables_legacy_autoseed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "learning.sqlite"
            backup_dir = root / "backups"
            conn = db.connect(db_path)
            try:
                db.init_schema(conn)
                db.seed_from_assets(conn, PROJECT_ROOT)
                self.assertGreater(conn.execute("select count(*) from graph_nodes").fetchone()[0], 0)
                conn.execute(
                    """
                    insert into question_items(
                      id, item_version, source_type, node_id, secondary_node_ids_json,
                      kind, question_type, variant_level, prompt, answer_format,
                      expected_answer, rubric_json, solution_steps_json, error_tags_json,
                      rollback_candidate_node_ids_json, rollback_candidate_relations_json,
                      estimated_minutes, parent_observation, source_json, raw_json
                    ) values (
                      'Q-reset-fixture', 'test-bank', 'graph_generated', 'M-PRE-NUMBER-SENSE', '[]',
                      'standard_example', 'fixture', 'L2', 'fixture prompt', 'fixture answer',
                      'fixture expected', '[]', '[]', '[]', '[]', '[]',
                      1, '', '{}', '{}'
                    )
                    """
                )
                question = conn.execute("select id, node_id from question_items order by id limit 1").fetchone()
                self.assertIsNotNone(question)
                session_id = db.create_session(conn, "reset fixture", commit=False)
                conn.execute(
                    """
                    insert into attempts(
                      id, session_id, question_id, node_id, result, grading_status,
                      score_points, max_points, error_tags_json, answer_raw,
                      parent_note, created_at
                    ) values (
                      'A-reset-fixture', ?, ?, ?, 'submitted', 'pending_review',
                      0, 10, '[]', 'fixture answer', '', ?
                    )
                    """,
                    (session_id, question["id"], question["node_id"], db.now_iso()),
                )
                conn.commit()
                self.assertEqual(1, conn.execute("select count(*) from attempts").fetchone()[0])
            finally:
                conn.close()

            result = reset_learning_system_data.reset_database(db_path, backup_dir=None)

            self.assertEqual("none", result["backup_policy"])
            self.assertEqual("", result["backup_path"])
            self.assertFalse(backup_dir.exists())
            conn = db.connect(db_path)
            try:
                self.assertEqual(0, conn.execute("select count(*) from question_items").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from question_review_records").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from answer_contracts").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from learning_sessions").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from attempts").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from daily_flows").fetchone()[0])
                self.assertGreater(conn.execute("select count(*) from graph_nodes").fetchone()[0], 0)
                self.assertTrue(server._db_seed_assets_disabled(conn))
                self.assertFalse(server._db_has_active_seed_assets(conn))
                self.assertTrue(server._db_has_graph_assets(conn))
                payload = daily_runtime.DailyLearningRuntime(
                    conn,
                    project_root=PROJECT_ROOT,
                ).load_or_create_daily_flow(local_date="2026-07-22")
                self.assertEqual("blocked", payload["child_state"])
                self.assertEqual("content_preparation", payload["message"]["blocked_kind"])
                self.assertIn("题目还没有准备好", payload["message"]["body"])
                self.assertEqual(0, conn.execute("select count(*) from learning_sessions").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from daily_flows").fetchone()[0])
            finally:
                conn.close()

    def test_clean_graph_only_database_blocks_without_fabricating_bank_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "learning.sqlite"
            conn = db.connect(db_path)
            try:
                db.init_schema(conn)
                db.seed_from_assets(conn, PROJECT_ROOT)

                self.assertEqual(56, conn.execute("select count(*) from graph_nodes").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from question_items").fetchone()[0])
                self.assertEqual(
                    0,
                    conn.execute(
                        "select count(*) from question_bank_version_ledger where status = 'active'"
                    ).fetchone()[0],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "exactly one active question-bank ledger row is required",
                ):
                    db.get_active_question_bank_version(conn)

                payload = daily_runtime.DailyLearningRuntime(
                    conn,
                    project_root=PROJECT_ROOT,
                ).load_or_create_daily_flow(local_date="2026-07-23")

                self.assertEqual("blocked", payload["child_state"])
                self.assertEqual("content_preparation", payload["message"]["blocked_kind"])
                self.assertEqual(0, conn.execute("select count(*) from learning_sessions").fetchone()[0])
                self.assertEqual(0, conn.execute("select count(*) from daily_flows").fetchone()[0])
            finally:
                conn.close()

    def test_generic_activation_rejects_empty_or_unbacked_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "learning.sqlite"
            conn = db.connect(db_path)
            try:
                db.init_schema(conn)
                db.seed_from_assets(conn, PROJECT_ROOT)
                graph_version = db.json_load(
                    conn.execute(
                        "select value from system_meta where key = 'graph_ref'"
                    ).fetchone()["value"],
                    {},
                )["lineage"]

                for version, node_count, item_count, expected_error in (
                    ("test.empty-bank", 0, 0, "positive item and node counts"),
                    ("test.unbacked-bank", 1, 1, "item_count mismatch"),
                ):
                    with self.subTest(version=version):
                        db.stage_question_bank_version(
                            conn,
                            question_bank_version=version,
                            graph_version=graph_version,
                            manifest_id=f"{version}.manifest",
                            manifest_sha256="a" * 64,
                            node_count=node_count,
                            item_count=item_count,
                            commit=False,
                        )
                        with self.assertRaisesRegex(ValueError, expected_error):
                            db.activate_question_bank_version(
                                conn,
                                question_bank_version=version,
                                expected_current_version=None,
                                reason="negative activation test",
                                commit=False,
                            )
                        self.assertEqual(
                            0,
                            conn.execute(
                                "select count(*) from question_bank_version_ledger where status = 'active'"
                            ).fetchone()[0],
                        )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
