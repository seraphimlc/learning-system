from __future__ import annotations

import sqlite3
import unittest

from learning_system import db
from learning_system.question_production_persistence import (
    BriefPersistence,
    CandidatePersistence,
    QFPersistence,
    SlotPersistence,
    default_persistences,
)


class QuestionProductionPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_schema(self.conn)
        self.conn.execute(
            "insert into graph_nodes(id,name,stage,domain,priority,summer_mode,sequence_band,prerequisites_json,unlocks_json,raw_json) values (?,?,?,?,?,?,?,?,?,?)",
            ("N-1", "测试节点", "test", "math", "P0", "core", 1, "[]", "[]", "{}"),
        )
        self.conn.execute(
            "insert into production_runs(id,node_id,input_json,input_digest_sha256,status,error_reason,lease_owner,lease_expires_at,run_generation,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?)",
            ("RUN-1", "N-1", "{}", "input", "running", "", "owner", "2099-01-01", 1, "now", "now"),
        )
        self.conn.execute(
            "insert into production_stages(id,run_id,stage_name,logical_key,status,attempt_count,max_attempts,lease_owner,lease_expires_at,run_generation,input_json,input_digest_sha256,output_json,output_digest_sha256,validation_errors_json,dependency_ids_json,error_reason,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("STAGE-1", "RUN-1", "qf_design", "N-1", "running", 1, 1, "owner", "2099-01-01", 1, "{}", "input", "[]", "", "[]", "[]", "", "now", "now"),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_default_persistences_have_one_adapter_per_artifact_type(self):
        persistences = default_persistences()
        self.assertIsInstance(persistences["qf_design"], QFPersistence)
        self.assertIsInstance(persistences["slot_design"], SlotPersistence)
        self.assertIsInstance(persistences["brief_generation"], BriefPersistence)
        self.assertIsInstance(persistences["candidate_generation"], CandidatePersistence)

    def test_persistence_writes_payload_and_parent_lineage(self):
        QFPersistence().persist(
            self.conn,
            run_id="RUN-1",
            stage_id="STAGE-1",
            output=[{"qf_id": "QF-1", "node_id": "N-1"}],
            parent_artifact_ids=[],
            input_digest="input",
            output_digest="output",
            artifact_attempt=1,
        )

        row = self.conn.execute("select artifact_type,logical_key,parent_artifact_ids_json,payload_json from production_artifacts").fetchone()
        self.assertEqual("qf", row["artifact_type"])
        self.assertEqual("QF-1", row["logical_key"])
        self.assertEqual([], __import__("json").loads(row["parent_artifact_ids_json"]))
        self.assertEqual("QF-1", __import__("json").loads(row["payload_json"])["qf_id"])


if __name__ == "__main__":
    unittest.main()
