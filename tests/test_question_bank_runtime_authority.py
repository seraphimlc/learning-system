from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from learning_system import daily_runtime, db, question_bank, test_support


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QuestionBankRuntimeAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "authority.sqlite"
        self.conn = db.connect(self.db_path)
        self.addCleanup(self.conn.close)
        db.init_schema(self.conn)
        db.seed_from_assets(self.conn, PROJECT_ROOT)
        test_support.seed_runtime_test_question_bank(self.conn, PROJECT_ROOT)
        self.runtime = daily_runtime.DailyLearningRuntime(
            self.conn,
            project_root=PROJECT_ROOT,
        )
        self.graph_version = self.runtime.graph.current_graph_version()

    def _active_authority(self) -> dict:
        return db.get_active_question_bank_authority(self.conn)

    def test_new_flow_fails_closed_without_active_ledger(self) -> None:
        self.conn.execute("delete from question_bank_version_ledger")
        self.conn.commit()

        with self.assertRaisesRegex(
            ValueError,
            "exactly one active question-bank ledger row",
        ):
            self.runtime._create_daily_flow("2099-08-01", self.graph_version)

        self.assertEqual(
            0,
            self.conn.execute("select count(*) from daily_flows").fetchone()[0],
        )

    def test_new_flow_fails_closed_with_multiple_active_ledgers(self) -> None:
        authority = self._active_authority()
        self.conn.execute("drop index idx_question_bank_version_ledger_active")
        now = db.now_iso()
        self.conn.execute(
            """
            insert into question_bank_version_ledger(
              id, question_bank_version, graph_version, manifest_id,
              manifest_sha256, node_count, item_count, status,
              reason, created_at, updated_at
            ) values (?, ?, ?, ?, ?, 1, 1, 'active', ?, ?, ?)
            """,
            (
                "QBL-second-active",
                "2099.bank.second-active",
                authority["graph_version"],
                "second-active-manifest",
                "b" * 64,
                "authority ambiguity fixture",
                now,
                now,
            ),
        )
        self.conn.commit()

        with self.assertRaisesRegex(
            ValueError,
            "exactly one active question-bank ledger row",
        ):
            self.runtime._create_daily_flow("2099-08-02", self.graph_version)

    def test_candidate_packet_rejects_unknown_bank_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "known question-bank ledger row"):
            question_bank.QuestionBankService.candidate_packet_for_node(
                self.conn,
                node_id="M-G7-POS-NEG",
                graph_version=self.graph_version,
                question_bank_version="unknown-bank-version",
                required_purpose="diagnostic",
            )

    def test_candidate_packet_rejects_missing_required_purpose(self) -> None:
        authority = self._active_authority()
        with self.assertRaisesRegex(ValueError, "requires purpose"):
            question_bank.QuestionBankService.candidate_packet_for_node(
                self.conn,
                node_id="M-G7-POS-NEG",
                graph_version=self.graph_version,
                question_bank_version=authority["question_bank_version"],
                required_purpose="",
            )

    def test_support_only_item_is_isolated_from_diagnostic_packet(self) -> None:
        authority = self._active_authority()
        question = db.find_question_for_node(
            self.conn,
            "M-G7-POS-NEG",
            question_bank_version=authority["question_bank_version"],
        )
        policy = db.active_question_usage_policy(
            self.conn,
            question["id"],
            item_version=question["item_version"],
        )
        self.assertIsNotNone(policy)
        self.conn.execute(
            """
            update question_usage_policies
            set support_only = 1,
                allowed_purposes_json = '["teaching"]',
                updated_at = ?
            where id = ?
            """,
            (db.now_iso(), policy["id"]),
        )
        self.conn.commit()

        packet = question_bank.QuestionBankService.candidate_packet_for_node(
            self.conn,
            node_id=question["node_id"],
            graph_version=self.graph_version,
            question_bank_version=authority["question_bank_version"],
            required_purpose="diagnostic",
            flow_id="DF-support-isolation",
        )

        self.assertNotIn(
            question["id"],
            {candidate["question_id"] for candidate in packet["candidates"]},
        )
        self.assertGreater(packet["filter_summary"]["excluded_purpose_mismatch"], 0)

    def test_existing_flow_keeps_frozen_bank_after_new_activation(self) -> None:
        old_authority = self._active_authority()
        flow = self.runtime._create_daily_flow("2099-08-03", self.graph_version)
        now = db.now_iso()
        self.conn.execute(
            """
            update question_bank_version_ledger
            set status = 'superseded', superseded_at = ?, updated_at = ?
            where id = ?
            """,
            (now, now, old_authority["id"]),
        )
        self.conn.execute(
            """
            insert into question_bank_version_ledger(
              id, question_bank_version, graph_version, manifest_id,
              manifest_sha256, node_count, item_count, status,
              activated_at, reason, created_at, updated_at
            ) values (?, ?, ?, ?, ?, 1, 1, 'active', ?, ?, ?, ?)
            """,
            (
                "QBL-new-active",
                "2099.bank.new-active",
                old_authority["graph_version"],
                "new-active-manifest",
                "c" * 64,
                now,
                "new bank activation fixture",
                now,
                now,
            ),
        )
        self.conn.commit()

        self.assertEqual(
            old_authority["question_bank_version"],
            self.runtime._question_bank_version_for_flow(flow["id"]),
        )
        stored_flow = dict(
            self.conn.execute(
                "select * from daily_flows where id = ?",
                (flow["id"],),
            ).fetchone()
        )
        self.assertEqual(old_authority["id"], stored_flow["question_bank_ledger_id"])
        self.assertEqual(
            old_authority["manifest_sha256"],
            stored_flow["question_bank_manifest_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
