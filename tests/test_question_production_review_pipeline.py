from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import patch

from learning_system import db
from learning_system.question_production_orchestrator import ProductionOrchestrator
from learning_system.question_production_skills import ValidationResult


class ReviewedSkill:
    def __init__(self, stage: str, *, review_decision: str = "accepted") -> None:
        self.stage = stage
        self.review_decision = review_decision
        self.generator_payloads: list[dict] = []
        self.review_payloads: list[dict] = []

    def run(self, payload: dict) -> list[dict]:
        self.generator_payloads.append(payload)
        if self.stage == "qf_design":
            return [{"qf_id": "qf-1", "node_id": payload["node_id"]}]
        if self.stage == "slot_design":
            return [{"slot_id": "slot-1", "qf_id": payload["qf_id"], "node_id": payload["node_id"]}]
        if self.stage == "brief_generation":
            return [{"brief_id": "brief-1", "slot_id": payload["slot_id"], "qf_id": payload["qf_id"], "node_id": payload["node_id"]}]
        return [{"candidate_id": "candidate-1", "brief_id": payload["brief_id"], "node_id": payload["node_id"]}]

    def validate(self, payload: dict, output: dict) -> list[str]:
        return []

    def review(self, payload: dict, output: list[dict]) -> dict:
        self.review_payloads.append({"payload": payload, "output": output})
        entity_id = output[0][{
            "qf_design": "qf_id",
            "slot_design": "slot_id",
            "brief_generation": "brief_id",
            "candidate_generation": "candidate_id",
        }[self.stage]]
        return {
            "decision": self.review_decision,
            "score": 2 if self.review_decision == "rejected" else 9,
            "issues": ["semantic_issue"] if self.review_decision == "rejected" else [],
            "repair_instructions": ["repair_generation"] if self.review_decision == "rejected" else [],
            "root_cause_stage": self.stage if self.review_decision == "rejected" else "none",
            "recovery_action": "retry_current_stage" if self.review_decision == "rejected" else "none",
            "recovery_stage": self.stage if self.review_decision == "rejected" else "none",
            "confidence": 0.9,
        }

    def validate_review(self, payload: dict, output: list[dict], review: dict) -> ValidationResult:
        if self.review_decision == "rejected":
            return ValidationResult.rejected(
                [{"code": "semantic_review_rejected", "message": "semantic_issue", "severity": "error"}],
                target_stage=self.stage,
            )
        return ValidationResult.passed()


class AcceptOnSecondReviewSkill(ReviewedSkill):
    def review(self, payload: dict, output: list[dict]) -> dict:
        self.review_payloads.append({"payload": payload, "output": output})
        accepted = len(self.review_payloads) > 1
        return {
            "decision": "accepted" if accepted else "rejected",
            "score": 9 if accepted else 3,
            "issues": [] if accepted else ["semantic_issue"],
            "repair_instructions": [] if accepted else ["repair_generation"],
            "root_cause_stage": "none" if accepted else self.stage,
            "recovery_action": "none" if accepted else "retry_current_stage",
            "recovery_stage": "none" if accepted else self.stage,
            "confidence": 0.9,
        }

    def validate_review(self, payload: dict, output: list[dict], review: dict) -> ValidationResult:
        if review["decision"] == "rejected":
            return ValidationResult.rejected(
                [{"code": "semantic_review_rejected", "message": "semantic_issue", "severity": "error"}],
                target_stage=self.stage,
            )
        return ValidationResult.passed()


class RecoverCandidateSkill(ReviewedSkill):
    def __init__(self) -> None:
        super().__init__("candidate_generation")

    def review(self, payload: dict, output: list[dict]) -> dict:
        self.review_payloads.append({"payload": payload, "output": output})
        if len(self.review_payloads) == 1:
            return {
                "decision": "rejected",
                "score": 3,
                "issues": ["Brief 与 Candidate 合同冲突"],
                "repair_instructions": ["重新生成 Brief"],
                "root_cause_stage": "brief_generation",
                "recovery_action": "regenerate_from_stage",
                "recovery_stage": "brief_generation",
                "confidence": 0.95,
            }
        return {
            "decision": "accepted",
            "score": 9,
            "issues": [],
            "repair_instructions": [],
            "root_cause_stage": "none",
            "recovery_action": "none",
            "recovery_stage": "none",
            "confidence": 0.95,
        }

    def validate_review(self, payload: dict, output: list[dict], review: dict) -> ValidationResult:
        if review["decision"] == "rejected":
            return ValidationResult.rejected(
                [{"code": "semantic_review_rejected", "message": "Brief 与 Candidate 合同冲突", "severity": "error"}],
                target_stage=review["recovery_stage"],
            )
        return ValidationResult.passed()


class QuestionProductionReviewPipelineTests(unittest.TestCase):
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

    def _skills(self, qf_decision: str = "accepted"):
        return {
            stage: ReviewedSkill(stage, review_decision=qf_decision if stage == "qf_design" else "accepted")
            for stage in ("qf_design", "slot_design", "brief_generation", "candidate_generation")
        }

    def test_semantic_rejection_blocks_persistence_and_downstream(self):
        skills = self._skills(qf_decision="rejected")
        orchestrator = ProductionOrchestrator(self.conn, skills=skills)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("failed", result["status"])
        self.assertEqual("rejected", result["stages"][0]["status"])
        self.assertEqual(3, len(skills["qf_design"].review_payloads))
        self.assertEqual(0, self.conn.execute("select count(*) from production_artifacts").fetchone()[0])
        self.assertTrue(all(stage["status"] == "blocked" for stage in result["stages"][1:]))

    def test_missing_semantic_reviewer_is_rejected_by_default(self):
        skills = self._skills()
        for skill in skills.values():
            skill.review = None
        orchestrator = ProductionOrchestrator(self.conn, skills=skills)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("failed", result["status"])
        self.assertIn("semantic_reviewer_missing", result["stages"][0]["validation_errors"][0]["code"])

    def test_semantic_acceptance_is_required_before_each_artifact_persistence(self):
        skills = self._skills()
        orchestrator = ProductionOrchestrator(self.conn, skills=skills)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("completed", result["status"])
        self.assertEqual(4, self.conn.execute("select count(*) from production_artifacts").fetchone()[0])
        self.assertEqual(1, len(skills["qf_design"].review_payloads))
        self.assertEqual(1, len(skills["slot_design"].review_payloads))
        self.assertEqual(1, len(skills["brief_generation"].review_payloads))
        self.assertEqual(1, len(skills["candidate_generation"].review_payloads))
        stored = self.conn.execute("select validation_result_json from production_stages where stage_name='qf_design'").fetchone()[0]
        self.assertEqual("accepted", json.loads(stored)["semantic_review"]["decision"])

    def test_orchestrator_exposes_promotion_as_an_explicit_boundary(self):
        skills = self._skills()
        orchestrator = ProductionOrchestrator(self.conn, skills=skills)

        with patch("learning_system.question_production_orchestrator.promote_run", return_value={"status": "staged"}) as promotion:
            result = orchestrator.promote(
                "RUN-1",
                question_bank_version="bank-test-1",
                graph_version="graph-test-1",
                manifest_id="manifest-test-1",
            )

        self.assertEqual({"status": "staged"}, result)
        promotion.assert_called_once_with(
            self.conn,
            run_id="RUN-1",
            question_bank_version="bank-test-1",
            graph_version="graph-test-1",
            manifest_id="manifest-test-1",
        )

    def test_each_action_retries_inside_orchestrator_with_reviewer_feedback(self):
        skills = {
            "qf_design": AcceptOnSecondReviewSkill("qf_design"),
            "slot_design": ReviewedSkill("slot_design"),
            "brief_generation": ReviewedSkill("brief_generation"),
            "candidate_generation": ReviewedSkill("candidate_generation"),
        }
        orchestrator = ProductionOrchestrator(self.conn, skills=skills, max_attempts=2)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("completed", result["status"])
        self.assertEqual(2, len(skills["qf_design"].review_payloads))
        self.assertEqual(2, self.conn.execute("select attempt_count from production_stages where stage_name='qf_design'").fetchone()[0])
        self.assertEqual(1, self.conn.execute("select count(*) from production_artifacts where artifact_type='qf'").fetchone()[0])
        retry_input = skills["qf_design"].review_payloads[1]["payload"]
        self.assertEqual("semantic_issue", retry_input["previous_validation_errors"][0]["message"])

    def test_candidate_review_records_upstream_suggestion_and_stops_without_rollback(self):
        calls = []
        candidate = RecoverCandidateSkill()
        skills = {
            "qf_design": ReviewedSkill("qf_design"),
            "slot_design": ReviewedSkill("slot_design"),
            "brief_generation": ReviewedSkill("brief_generation"),
            "candidate_generation": candidate,
        }
        orchestrator = ProductionOrchestrator(self.conn, skills=skills)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("failed", result["status"])
        self.assertEqual(1, len(skills["brief_generation"].generator_payloads))
        self.assertEqual(1, len(candidate.review_payloads))
        recovery_events = self.conn.execute(
            "select count(*) from production_audit_events where run_id=? and event_type='recovery'",
            (result["run_id"],),
        ).fetchone()[0]
        self.assertEqual(0, recovery_events)
        stored_review = json.loads(
            self.conn.execute(
                "select validation_result_json from production_stages where run_id=? and stage_name='candidate_generation'",
                (result["run_id"],),
            ).fetchone()[0]
        )["semantic_review"]
        self.assertEqual("brief_generation", stored_review["root_cause_stage"])
        self.assertEqual("regenerate_from_stage", stored_review["recovery_action"])


if __name__ == "__main__":
    unittest.main()
