from __future__ import annotations

import json
import sqlite3
import unittest

from learning_system import db
from learning_system.question_production_promotion import promote_run


def _candidate_content(mode: str = "fill_blank", *, with_rubric: bool = True) -> dict:
    content = {
        "schema_version": "question-content.v1",
        "task_type": "calculation" if mode == "fill_blank" else "reasoning",
        "response_mode": mode,
        "prompt": "计算：1 + 2 = ____。" if mode == "fill_blank" else "请说明你的解题理由。",
        "choices": [],
        "answer": ["3"] if mode == "fill_blank" else ["答案应说明关键关系。"],
    }
    if mode == "short_answer" and with_rubric:
        content["rubric"] = ["指出关键关系", "结论与理由一致"]
        content["solution_steps"] = ["识别题目中的关键关系", "说明理由并得出结论"]
    return content


class QuestionProductionPromotionTests(unittest.TestCase):
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
            ("RUN-1", "N-1", "{}", "input", "completed", "", "", None, 1, "now", "now"),
        )
        self.conn.execute(
            "insert into production_stages(id,run_id,stage_name,logical_key,status,attempt_count,max_attempts,lease_owner,lease_expires_at,run_generation,input_json,input_digest_sha256,output_json,output_digest_sha256,validation_errors_json,validation_result_json,dependency_ids_json,error_reason,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "STAGE-CANDIDATE", "RUN-1", "candidate_generation", "BRIEF-1", "completed", 1, 1,
                "", None, 1, "{}", "input", "[]", "output", "[]",
                json.dumps({"semantic_review": {"decision": "accepted", "score": 9, "issues": [], "repair_instructions": []}}),
                json.dumps(["PA-BRIEF"]), "", "now", "now",
            ),
        )
        self.conn.execute(
            "insert into production_artifacts(id,run_id,stage_id,artifact_type,logical_key,parent_artifact_ids_json,payload_json,input_digest_sha256,output_digest_sha256,artifact_attempt,created_at) values (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "PA-BRIEF", "RUN-1", "STAGE-CANDIDATE", "brief", "BRIEF-1", "[]",
                json.dumps({"brief_id": "BRIEF-1", "qf_id": "QF-1", "slot_id": "SLOT-1", "node_id": "N-1"}),
                "input", "output", 1, "now",
            ),
        )
        self.conn.execute(
            "insert into production_artifacts(id,run_id,stage_id,artifact_type,logical_key,parent_artifact_ids_json,payload_json,input_digest_sha256,output_digest_sha256,artifact_attempt,created_at) values (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "PA-CANDIDATE", "RUN-1", "STAGE-CANDIDATE", "candidate", "CANDIDATE-1", json.dumps(["PA-BRIEF"]),
                json.dumps({
                    "candidate_id": "CANDIDATE-1", "brief_id": "BRIEF-1", "node_id": "N-1",
                    "content": _candidate_content(),
                }, ensure_ascii=False), "input", "output", 1, "now",
            ),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_promotes_reviewed_fixed_answer_candidate_to_staged_question_item(self):
        result = promote_run(
            self.conn,
            run_id="RUN-1",
            question_bank_version="bank-test-1",
            graph_version="graph-test-1",
            manifest_id="manifest-test-1",
        )

        self.assertEqual(1, result["promoted_count"])
        self.assertEqual(1, self.conn.execute("select count(*) from question_items").fetchone()[0])
        item = self.conn.execute("select * from question_items").fetchone()
        self.assertEqual("graph_generated", item["source_type"])
        self.assertEqual("fill_blank", json.loads(item["raw_json"])["interaction_schema"]["type"])
        self.assertEqual("staged", self.conn.execute("select status from question_bank_version_ledger").fetchone()[0])
        review = self.conn.execute(
            "select candidate_id, item_version, review_status, reviewer_run_id, active_eligible from question_review_records"
        ).fetchone()
        self.assertIsNotNone(review)
        self.assertEqual("CANDIDATE-1", review["candidate_id"])
        self.assertEqual("bank-test-1", review["item_version"])
        self.assertEqual("approved", review["review_status"])
        self.assertTrue(review["reviewer_run_id"])
        self.assertEqual(1, review["active_eligible"])
        reviewer = self.conn.execute(
            "select agent_key, phase, status from agent_runs where id = ?",
            (review["reviewer_run_id"],),
        ).fetchone()
        self.assertEqual(("question_reviewer_agent", "question_quality_review", "accepted"), tuple(reviewer))
        audit = self.conn.execute(
            "select event_type,status,input_json,output_json from production_audit_events where stage_name='promotion'"
        ).fetchone()
        self.assertEqual(("promotion", "completed"), (audit["event_type"], audit["status"]))
        self.assertTrue(json.loads(audit["input_json"]))
        self.assertTrue(json.loads(audit["output_json"]))

    def test_short_answer_requires_rubric_and_solution_steps(self):
        self.conn.execute("delete from production_artifacts where artifact_type='candidate'")
        self.conn.execute(
            "insert into production_artifacts(id,run_id,stage_id,artifact_type,logical_key,parent_artifact_ids_json,payload_json,input_digest_sha256,output_digest_sha256,artifact_attempt,created_at) values (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "PA-CANDIDATE-2", "RUN-1", "STAGE-CANDIDATE", "candidate", "CANDIDATE-2", json.dumps(["PA-BRIEF"]),
                json.dumps({"candidate_id": "CANDIDATE-2", "brief_id": "BRIEF-1", "node_id": "N-1", "content": _candidate_content("short_answer", with_rubric=False)}, ensure_ascii=False),
                "input", "output", 1, "now",
            ),
        )
        self.conn.commit()

        with self.assertRaisesRegex(ValueError, "rubric"):
            promote_run(self.conn, run_id="RUN-1", question_bank_version="bank-test-1", graph_version="graph-test-1", manifest_id="manifest-test-1")
        self.assertEqual(0, self.conn.execute("select count(*) from question_items").fetchone()[0])

    def test_semantic_rejection_cannot_be_promoted(self):
        self.conn.execute(
            "update production_stages set validation_result_json=? where id='STAGE-CANDIDATE'",
            (json.dumps({"semantic_review": {"decision": "rejected", "score": 2, "issues": ["too mechanical"], "repair_instructions": ["redesign"]}}),),
        )
        self.conn.commit()

        with self.assertRaisesRegex(ValueError, "not semantically accepted"):
            promote_run(self.conn, run_id="RUN-1", question_bank_version="bank-test-1", graph_version="graph-test-1", manifest_id="manifest-test-1")
        self.assertEqual(0, self.conn.execute("select count(*) from question_items").fetchone()[0])

    def test_promotion_is_idempotent_for_same_run_and_version(self):
        first = promote_run(self.conn, run_id="RUN-1", question_bank_version="bank-test-1", graph_version="graph-test-1", manifest_id="manifest-test-1")
        second = promote_run(self.conn, run_id="RUN-1", question_bank_version="bank-test-1", graph_version="graph-test-1", manifest_id="manifest-test-1")

        self.assertEqual(1, first["promoted_count"])
        self.assertEqual(0, second["promoted_count"])
        self.assertEqual(1, self.conn.execute("select count(*) from question_items").fetchone()[0])
        self.assertEqual(1, self.conn.execute("select count(*) from question_bank_version_ledger").fetchone()[0])

    def test_promotion_binds_question_identity_to_bank_version(self):
        first = promote_run(
            self.conn,
            run_id="RUN-1",
            question_bank_version="bank-test-1",
            graph_version="graph-test-1",
            manifest_id="manifest-test-1",
        )
        second = promote_run(
            self.conn,
            run_id="RUN-1",
            question_bank_version="bank-test-2",
            graph_version="graph-test-1",
            manifest_id="manifest-test-2",
        )

        self.assertEqual(1, first["promoted_count"])
        self.assertEqual(1, second["promoted_count"])
        self.assertEqual(2, self.conn.execute("select count(*) from question_items").fetchone()[0])
        ids = [row[0] for row in self.conn.execute("select id from question_items order by id")]
        self.assertNotEqual(ids[0], ids[1])


if __name__ == "__main__":
    unittest.main()
