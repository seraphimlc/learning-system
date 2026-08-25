from __future__ import annotations

import sqlite3
import unittest

from learning_system import db, job_queue


class Task2TransactionDigestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_schema(self.conn)
        self.conn.execute("pragma foreign_keys = off")
        self.addCleanup(self.conn.close)

    @staticmethod
    def _v3_payload(session_id: str, digest: str | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "legacy_session_id": session_id,
            "payload_schema_version": "v3.test",
            "flow_id": "FLOW-task2",
            "flow_step_id": "STEP-task2",
            "attempt_id": "ATT-task2",
            "graph_version": "graph-v2",
            "question_bank_version": "bank-v2",
        }
        if digest is not None:
            payload["contract_digest_sha256"] = digest
        return payload

    def test_legacy_enqueue_does_not_commit_callers_transaction(self) -> None:
        self.conn.execute("create table transaction_probe (id integer primary key, value text not null)")
        self.conn.execute("insert into transaction_probe(id, value) values (1, 'before')")
        self.conn.commit()

        self.conn.execute("begin")
        self.conn.execute("update transaction_probe set value = 'outer-change' where id = 1")
        db.enqueue_background_job(
            self.conn,
            job_type="answer_review",
            session_id="SESSION-task2-legacy",
            payload={},
            commit=True,
        )

        self.conn.rollback()
        self.assertEqual("before", self.conn.execute("select value from transaction_probe where id = 1").fetchone()[0])
        self.assertEqual(0, self.conn.execute("select count(*) from background_jobs").fetchone()[0])

    def test_v3_enqueue_does_not_commit_callers_transaction(self) -> None:
        self.conn.execute("create table transaction_probe (id integer primary key, value text not null)")
        self.conn.execute("insert into transaction_probe(id, value) values (1, 'before')")
        self.conn.commit()

        self.conn.execute("begin")
        self.conn.execute("update transaction_probe set value = 'outer-change' where id = 1")
        job_queue.JobQueue(self.conn).enqueue(
            "answer_analysis",
            "v3:task2:transaction",
            self._v3_payload("SESSION-task2-v3"),
            commit=True,
        )

        self.conn.rollback()
        self.assertEqual("before", self.conn.execute("select value from transaction_probe where id = 1").fetchone()[0])
        self.assertEqual(0, self.conn.execute("select count(*) from background_jobs").fetchone()[0])

    def test_enqueue_own_transaction_rolls_back_after_insert_error(self) -> None:
        self.conn.execute(
            """
            create trigger fail_background_job_insert
            after insert on background_jobs
            begin
              select raise(abort, 'forced enqueue failure');
            end
            """
        )

        for enqueue in (
            lambda: db.enqueue_background_job(
                self.conn,
                job_type="answer_review",
                session_id="SESSION-task2-error-legacy",
                payload={},
            ),
            lambda: job_queue.JobQueue(self.conn).enqueue(
                "answer_analysis",
                "v3:task2:error",
                self._v3_payload("SESSION-task2-error-v3"),
            ),
        ):
            with self.subTest(enqueue=enqueue):
                with self.assertRaises(sqlite3.IntegrityError):
                    enqueue()
                self.assertFalse(self.conn.in_transaction)
                self.assertEqual(0, self.conn.execute("select count(*) from background_jobs").fetchone()[0])

    def test_job_digests_are_lowercase_and_uppercase_replay_is_idempotent(self) -> None:
        digest = "ab" * 32
        upper = digest.upper()

        legacy = db.enqueue_background_job(
            self.conn,
            job_type="answer_review",
            session_id="SESSION-task2-digest-legacy",
            payload={"contract_digest_sha256": upper},
        )
        legacy_replay = db.enqueue_background_job(
            self.conn,
            job_type="answer_review",
            session_id="SESSION-task2-digest-legacy",
            payload={"contract_digest_sha256": digest},
        )
        self.assertEqual(legacy["id"], legacy_replay["id"])
        self.assertEqual(digest, legacy["contract_digest_sha256"])
        self.assertEqual(digest, self.conn.execute("select contract_digest_sha256 from background_jobs where id = ?", (legacy["id"],)).fetchone()[0])

        v3 = job_queue.JobQueue(self.conn).enqueue(
            "answer_analysis",
            "v3:task2:digest",
            self._v3_payload("SESSION-task2-digest-v3", upper),
        )
        self.assertEqual(digest, self.conn.execute("select contract_digest_sha256 from background_jobs where id = ?", (v3.job_id,)).fetchone()[0])
        v3_replay = job_queue.JobQueue(self.conn).enqueue(
            "answer_analysis",
            "v3:task2:digest",
            self._v3_payload("SESSION-task2-digest-v3", digest),
        )
        self.assertTrue(v3_replay.reused_existing)
        self.assertEqual(v3.job_id, v3_replay.job_id)

    def test_fixed_effect_digest_is_strict_normalized_and_replay_is_case_insensitive(self) -> None:
        digest = "cd" * 32
        first = db.record_fixed_assessment_effect(
            self.conn,
            attempt_id="ATT-task2-effect",
            attempt_version=1,
            contract_digest_sha256=digest.upper(),
            result={"score": 1},
            profile={"supports": ["answer_correctness"]},
            ceiling="B",
        )
        replay = db.record_fixed_assessment_effect(
            self.conn,
            attempt_id="ATT-task2-effect",
            attempt_version=1,
            contract_digest_sha256=digest,
            result={"score": 0},
            profile={},
            ceiling="D",
        )

        self.assertEqual(digest, first["contract_digest_sha256"])
        self.assertEqual(digest, first["effect_key"].rsplit(":", 1)[-1])
        self.assertEqual(first["effect_key"], replay["effect_key"])
        self.assertEqual({"score": 1}, replay["result"])
        self.assertEqual(digest, self.conn.execute("select contract_digest_sha256 from fixed_assessment_effects").fetchone()[0])

        for invalid in (None, "", "a" * 63, "g" * 64, 123):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    db.fixed_assessment_effect_key("ATT-task2-invalid", 1, invalid)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
