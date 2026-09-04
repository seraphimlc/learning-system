from __future__ import annotations

import json
import sqlite3
import unittest

from learning_system import db
from learning_system.question_production_orchestrator import ProductionOrchestrator
from tests.test_question_production_review_pipeline import ReviewedSkill


class QuestionProductionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_schema(self.conn)
        self.conn.execute(
            "insert into graph_nodes(id,name,stage,domain,priority,summer_mode,sequence_band,prerequisites_json,unlocks_json,raw_json) values (?,?,?,?,?,?,?,?,?,?)",
            ("N-1", "测试节点", "test", "math", "P0", "core", 1, "[]", "[]", "{}"),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_each_stage_records_generator_validation_reviewer_and_persistence_io(self):
        skills = {
            stage: ReviewedSkill(stage)
            for stage in ("qf_design", "slot_design", "brief_generation", "candidate_generation")
        }
        orchestrator = ProductionOrchestrator(self.conn, skills=skills)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("completed", result["status"])
        events = [dict(row) for row in self.conn.execute("select * from production_audit_events order by created_at, rowid")]
        self.assertEqual(20, len(events))
        self.assertEqual(
            {"generator", "schema_validator", "semantic_reviewer", "reviewer_validator", "persistence"},
            {event["event_type"] for event in events},
        )
        for event in events:
            self.assertEqual("completed", event["status"])
            self.assertTrue(json.loads(event["input_json"]))
            self.assertTrue(json.loads(event["output_json"]))
            self.assertTrue(event["input_digest_sha256"])
            self.assertTrue(event["output_digest_sha256"])

    def test_failed_schema_validation_is_audited_without_persisting_artifact(self):
        skills = {
            stage: ReviewedSkill(stage)
            for stage in ("qf_design", "slot_design", "brief_generation", "candidate_generation")
        }
        skills["qf_design"].run = lambda payload: [{"node_id": payload["node_id"]}]
        skills["qf_design"].validate = lambda payload, output: ["invalid_schema"]
        orchestrator = ProductionOrchestrator(self.conn, skills=skills)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("failed", result["status"])
        events = [dict(row) for row in self.conn.execute("select * from production_audit_events order by created_at, rowid")]
        self.assertEqual(
            ["generator", "schema_validator", "persistence"] * 3,
            [event["event_type"] for event in events],
        )
        self.assertEqual(["rejected", "skipped"] * 3, [events[index]["status"] for index in (1, 2, 4, 5, 7, 8)])
        self.assertEqual(0, self.conn.execute("select count(*) from production_artifacts").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
