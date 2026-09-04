from __future__ import annotations

import json
import sqlite3
import threading
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta, timezone

from learning_system import db
from learning_system.question_production_orchestrator import (
    ProductionOrchestrator,
    Skill,
    create_question_production_orchestrator,
)


class RecordingSkill(Skill):
    def __init__(self, stage: str, calls: list[tuple[str, str]], *, delay: float = 0, fail: bool = False):
        self.stage = stage
        self.calls = calls
        self.payloads: list[dict] = []
        self.delay = delay
        self.fail = fail

    def run(self, payload: dict) -> list[dict]:
        self.payloads.append(payload)
        self.calls.append((self.stage, str(payload.get("key") or payload.get("node_id") or "")))
        if self.delay:
            threading.Event().wait(self.delay)
        if self.fail:
            raise RuntimeError(f"{self.stage} failed")
        if self.stage == "qf_design":
            return [{"qf_id": "qf-1", "node_id": payload["node_id"], "key": "qf-1"}]
        if self.stage == "slot_design":
            return [{"slot_id": f"slot-{payload['key']}", "qf_id": payload["qf_id"], "node_id": payload["node_id"], "key": f"slot-{payload['key']}"}]
        if self.stage == "brief_generation":
            return [{"brief_id": f"brief-{payload['key']}", "slot_id": payload["slot_id"], "node_id": payload["node_id"], "key": f"brief-{payload['key']}"}]
        return [{"candidate_id": f"candidate-{payload['key']}", "brief_id": payload["brief_id"], "node_id": payload["node_id"], "key": f"candidate-{payload['key']}"}]

    def validate(self, payload: dict, output: dict) -> list[str]:
        return []


class FailingValidationSkill(RecordingSkill):
    def validate(self, payload: dict, output: dict) -> list[str]:
        return ["invalid_output"]


class DuplicateOutputSkill(RecordingSkill):
    def run(self, payload: dict) -> list[dict]:
        return [
            {"qf_id": "qf-1", "node_id": payload["node_id"], "key": "first"},
            {"qf_id": "qf-1", "node_id": payload["node_id"], "key": "second"},
        ]


class SelectiveBriefSkill(RecordingSkill):
    def __init__(self, calls, failed_keys: set[str]):
        super().__init__("brief_generation", calls)
        self.failed_keys = failed_keys

    def validate(self, payload: dict, output: dict) -> list[str]:
        return ["brief_invalid"] if payload["slot_id"] in self.failed_keys else []


class MissingParentSkill(RecordingSkill):
    def run(self, payload: dict) -> list[dict]:
        if self.stage == "qf_design":
            self.calls.append((self.stage, str(payload.get("node_id") or "")))
            return [{"node_id": payload["node_id"], "key": "not-an-id"}]
        return super().run(payload)


class QuestionProductionOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_schema(self.conn)
        now = db.now_iso()
        self.conn.execute(
            "insert into graph_nodes(id,name,stage,domain,priority,summer_mode,sequence_band,prerequisites_json,unlocks_json,raw_json) values (?,?,?,?,?,?,?,?,?,?)",
            ("N-1", "测试节点", "test", "math", "P0", "core", 1, "[]", "[]", "{}"),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def _orchestrator(self, skills, *, max_workers=4, max_attempts=3):
        return ProductionOrchestrator(self.conn, skills=skills, require_semantic_review=False, max_workers=max_workers, max_attempts=max_attempts)

    def test_pipeline_runs_in_dependency_order_and_persists_artifacts(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })

        result = orchestrator.run("N-1", {"node_id": "N-1", "name": "测试节点"})

        self.assertEqual("completed", result["status"])
        self.assertEqual(
            ["qf_design", "slot_design", "brief_generation", "candidate_generation"],
            [stage for stage, _ in calls],
        )
        self.assertEqual(4, self.conn.execute("select count(*) from production_artifacts").fetchone()[0])
        self.assertEqual(4, self.conn.execute("select count(*) from production_stages where status='completed'").fetchone()[0])

    def test_factory_integrates_four_concrete_skills(self):
        def qf(payload):
            return [{"qf_id": "qf-1", "node_id": payload["node_id"], "name": "测试 QF", "task_type": "reasoning", "measurement_intent": "测量", "independent_reason": "独立", "allowed_response_modes": ["single_choice"], "scope": {}, "required_evidence": ["answer"], "reject_if": ["机械"]}]
        def slot(payload):
            return [{"slot_id": "slot-1", "qf_id": payload["qf_id"], "node_id": payload["node_id"], "task_type": "reasoning", "response_mode": "single_choice", "structure": "test", "measurement_target": "测量", "conditions": ["条件"], "error_targets": ["错因"], "minimum_quality": ["非机械"], "reject_if": ["简单"]}]
        def brief(payload):
            return [{"brief_id": "brief-1", "slot_id": payload["slot_id"], "qf_id": payload["qf_id"], "node_id": payload["node_id"], "task": {"task_type": "reasoning", "response_mode": "single_choice"}, "content_blueprint": {"target_concept": "测量能力", "mechanism_type": "comparison", "problem_mechanism": "通过比较完成测量", "student_actions": ["比较"], "misconception_mechanism": "混淆比较对象", "parameter_pattern": {"vary": ["数值"], "must_hold": ["答案唯一"], "avoid": ["一眼可见"], "generation_steps": ["先选参数"]}, "answer_derivation": "按定义推导", "good_instance_pattern": "需要比较后作答", "bad_instance_pattern": "直接可见答案"}, "candidate_contract": {"response_mode": "single_choice", "answer_encoding": "choice_text", "field_mapping": {"prompt": "题干", "choices": "选项", "answer": "答案", "rubric": "评分", "solution_steps": "过程"}, "response_field_count": 1, "reference_answer_count": 1, "answer_requirements": ["引用正确选项文本"], "choice_requirements": ["选项互斥"], "prompt_requirements": ["题干完整"]}, "construction": {}, "answer_contract": {}, "difficulty_contract": {}, "self_check": ["ok"]}]
        def candidate(payload):
            return {"schema_version": "question-content.v1", "task_type": "reasoning", "response_mode": "single_choice", "prompt": "选择正确答案。", "choices": ["A", "B"], "answer": ["A"]}

        orchestrator = create_question_production_orchestrator(self.conn, generators={"qf_design": qf, "slot_design": slot, "brief_generation": brief, "candidate_generation": candidate}, require_semantic_review=False)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("completed", result["status"], result)
        self.assertEqual(["qf", "slot", "brief", "candidate"], [artifact["artifact_type"] for stage in result["stages"] for artifact in stage["artifacts"]])

    def test_run_until_pauses_after_requested_stage_without_starting_downstream(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })

        result = orchestrator.run_until("N-1", {"node_id": "N-1"}, "qf_design")

        self.assertEqual("paused", result["status"])
        self.assertEqual(["qf_design"], [stage for stage, _ in calls])
        self.assertEqual(["qf_design"], [stage["stage_name"] for stage in result["stages"]])

    def test_rerun_creates_a_new_full_run_without_mutating_source_run(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })

        source = orchestrator.run("N-1", {"node_id": "N-1", "name": "测试节点"})
        rerun = orchestrator.rerun(
            "N-1",
            {"node_id": "N-1", "name": "测试节点"},
            source_run_id=source["run_id"],
        )

        self.assertNotEqual(source["run_id"], rerun["run_id"])
        self.assertEqual("completed", rerun["status"])
        self.assertEqual(2, self.conn.execute("select count(*) from production_runs where node_id='N-1'").fetchone()[0])
        self.assertEqual("completed", self.conn.execute("select status from production_runs where id=?", (source["run_id"],)).fetchone()[0])
        rerun_input = json.loads(self.conn.execute("select input_json from production_runs where id=?", (rerun["run_id"],)).fetchone()[0])
        self.assertEqual(source["run_id"], rerun_input["rerun_context"]["source_run_id"])
        self.assertEqual(8, len(calls))

    def test_structure_revision_runs_only_qf_and_slot_with_feedback(self):
        calls = []
        skills = {
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        }
        orchestrator = self._orchestrator(skills)

        result = orchestrator.revise_structure(
            "N-1",
            {"node_id": "N-1", "name": "测试节点"},
            source_run_id="PR-SOURCE",
            feedback=[{"message": "QF 与 Slot 答案形式冲突", "severity": "error"}],
        )

        self.assertEqual("paused", result["status"])
        self.assertEqual(["qf_design", "slot_design"], [stage for stage, _ in calls])
        self.assertEqual(0, [stage for stage, _ in calls].count("brief_generation"))
        self.assertEqual(0, [stage for stage, _ in calls].count("candidate_generation"))
        self.assertEqual(2, self.conn.execute("select count(*) from production_artifacts where run_id=?", (result["run_id"],)).fetchone()[0])
        self.assertEqual("PR-SOURCE", skills["slot_design"].payloads[0]["revision_context"]["source_run_id"])
        stored_input = json.loads(self.conn.execute("select input_json from production_runs where id=?", (result["run_id"],)).fetchone()[0])
        self.assertEqual("PR-SOURCE", stored_input["revision_context"]["source_run_id"])
        self.assertEqual("QF 与 Slot 答案形式冲突", stored_input["revision_context"]["feedback"][0]["message"])

    def test_upstream_failure_blocks_downstream_and_does_not_retry(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls, fail=True),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("failed", result["status"])
        self.assertEqual(["qf_design"], [stage for stage, _ in calls])
        self.assertEqual(1, self.conn.execute("select count(*) from production_stages where status='blocked'").fetchone()[0])
        self.assertEqual(1, self.conn.execute("select count(*) from production_stages where stage_name='qf_design'").fetchone()[0])
        self.assertEqual("blocked", result["stages"][0]["status"])

    def test_same_input_is_idempotent_and_does_not_call_skills_again(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })
        first = orchestrator.run("N-1", {"node_id": "N-1", "name": "测试节点"})
        second = orchestrator.run("N-1", {"node_id": "N-1", "name": "测试节点"})

        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(4, len(calls))
        self.assertEqual(1, self.conn.execute("select count(*) from production_runs").fetchone()[0])

    def test_validation_failure_is_rejected_and_requires_explicit_retry(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": FailingValidationSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })
        first = orchestrator.run("N-1", {"node_id": "N-1"})
        self.assertEqual("failed", first["status"])
        self.assertEqual("rejected", first["stages"][0]["status"])
        self.assertEqual(["qf_design"], [stage for stage, _ in calls])

        with self.assertRaisesRegex(ValueError, "explicit retry"):
            orchestrator.run("N-1", {"node_id": "N-1"})

    def test_independent_briefs_run_in_parallel(self):
        calls = []
        class TwoSlotSkill(RecordingSkill):
            def run(self, payload):
                super().run(payload)
                if self.stage == "slot_design":
                    return [
                        {"slot_id": "slot-a", "qf_id": payload["qf_id"], "node_id": payload["node_id"], "key": "slot-a"},
                        {"slot_id": "slot-b", "qf_id": payload["qf_id"], "node_id": payload["node_id"], "key": "slot-b"},
                    ]
                return super().run(payload)

        class ParallelBriefSkill(RecordingSkill):
            barrier = threading.Barrier(2)

            def run(self, payload):
                self.calls.append((self.stage, str(payload.get("key") or "")))
                self.barrier.wait(timeout=2)
                return [{"brief_id": f"brief-{payload['key']}", "slot_id": payload["slot_id"], "node_id": payload["node_id"], "key": f"brief-{payload['key']}"}]

        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": TwoSlotSkill("slot_design", calls),
            "brief_generation": ParallelBriefSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        }, max_workers=2)

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("completed", result["status"])
        self.assertEqual(2, self.conn.execute("select count(*) from production_artifacts where artifact_type='brief'").fetchone()[0])

    def test_explicit_retry_reprocesses_only_failed_stage(self):
        calls = []
        failing = FailingValidationSkill("qf_design", calls)
        orchestrator = self._orchestrator({
            "qf_design": failing,
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })
        first = orchestrator.run("N-1", {"node_id": "N-1"})
        self.assertEqual("failed", first["status"])
        orchestrator.skills["qf_design"] = RecordingSkill("qf_design", calls)

        result = orchestrator.retry(first["run_id"])

        self.assertEqual("completed", result["status"])
        self.assertEqual(2, [stage for stage, _ in calls].count("qf_design"))
        self.assertFalse(any(stage["status"] == "blocked" for stage in result["stages"]))

    def test_fanout_retry_only_reprocesses_failed_child(self):
        calls = []
        selective = SelectiveBriefSkill(calls, {"slot-b"})
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": selective,
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })
        # Replace the normal slot output with two independent children.
        class TwoSlot(RecordingSkill):
            def run(self, payload):
                return [
                    {"slot_id": "slot-a", "qf_id": payload["qf_id"], "node_id": payload["node_id"]},
                    {"slot_id": "slot-b", "qf_id": payload["qf_id"], "node_id": payload["node_id"]},
                ]
        orchestrator.skills["slot_design"] = TwoSlot("slot_design", calls)
        first = orchestrator.run("N-1", {"node_id": "N-1"})
        self.assertEqual("failed", first["status"])
        selective.failed_keys.clear()

        result = orchestrator.retry(first["run_id"])

        self.assertEqual("completed", result["status"])
        self.assertEqual(1, [key for stage, key in calls if stage == "brief_generation"].count("slot-a"))
        self.assertEqual(2, [key for stage, key in calls if stage == "brief_generation"].count("slot-b"))

    def test_missing_parent_entity_id_blocks_before_downstream_skill(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": MissingParentSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("failed", result["status"])
        self.assertEqual(["qf_design"], [stage for stage, _ in calls])

    def test_concurrent_same_input_creates_one_run_and_one_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "production.sqlite"
            first_conn = sqlite3.connect(path, check_same_thread=False)
            first_conn.row_factory = sqlite3.Row
            db.init_schema(first_conn)
            first_conn.execute(
                "insert into graph_nodes(id,name,stage,domain,priority,summer_mode,sequence_band,prerequisites_json,unlocks_json,raw_json) values (?,?,?,?,?,?,?,?,?,?)",
                ("N-1", "测试节点", "test", "math", "P0", "core", 1, "[]", "[]", "{}"),
            )
            first_conn.commit()
            second_conn = sqlite3.connect(path, check_same_thread=False)
            second_conn.row_factory = sqlite3.Row
            calls = []
            started = threading.Event()
            release = threading.Event()
            class GatedQfSkill(RecordingSkill):
                def run(self, payload):
                    self.calls.append((self.stage, str(payload.get("key") or "")))
                    started.set()
                    release.wait(timeout=2)
                    return [{"qf_id": "qf-1", "node_id": payload["node_id"], "key": "qf-1"}]
            skills = {
                "qf_design": GatedQfSkill("qf_design", calls),
                "slot_design": RecordingSkill("slot_design", calls),
                "brief_generation": RecordingSkill("brief_generation", calls),
                "candidate_generation": RecordingSkill("candidate_generation", calls),
            }
            first = ProductionOrchestrator(first_conn, skills=skills, require_semantic_review=False)
            second = ProductionOrchestrator(second_conn, skills=skills, require_semantic_review=False)

            def invoke(orchestrator):
                try:
                    return ("result", orchestrator.run("N-1", {"node_id": "N-1"}))
                except ValueError as exc:
                    return ("error", str(exc))

            with ThreadPoolExecutor(max_workers=2) as executor:
                first_future = executor.submit(invoke, first)
                self.assertTrue(started.wait(timeout=2))
                second_future = executor.submit(invoke, second)
                second_outcome = second_future.result(timeout=2)
                release.set()
                outcomes = [first_future.result(timeout=2), second_outcome]
            result = next(value for kind, value in outcomes if kind == "result")
            error = next(value for kind, value in outcomes if kind == "error")

            self.assertEqual("completed", result["status"])
            self.assertIn("already running", error)
            self.assertEqual(1, first_conn.execute("select count(*) from production_runs").fetchone()[0])
            self.assertEqual(4, len(calls))
            first_conn.close()
            second_conn.close()

    def test_duplicate_artifact_keys_block_stage_without_partial_persistence(self):
        orchestrator = self._orchestrator({
            "qf_design": DuplicateOutputSkill("qf_design", []),
            "slot_design": RecordingSkill("slot_design", []),
            "brief_generation": RecordingSkill("brief_generation", []),
            "candidate_generation": RecordingSkill("candidate_generation", []),
        })

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("failed", result["status"])
        self.assertEqual("blocked", result["stages"][0]["status"])
        self.assertEqual(0, self.conn.execute("select count(*) from production_artifacts").fetchone()[0])

    def test_retry_limit_is_enforced_by_the_orchestrator(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": FailingValidationSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })
        first = orchestrator.run("N-1", {"node_id": "N-1"})
        orchestrator.max_attempts = 1
        self.conn.execute("update production_stages set max_attempts=1 where run_id=?", (first["run_id"],))
        self.conn.commit()

        result = orchestrator.retry(first["run_id"])

        self.assertEqual("failed", result["status"])
        self.assertIn("retry limit reached", result["error_reason"])

    def test_stale_running_run_can_be_explicitly_recovered(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })
        run = orchestrator.run("N-1", {"node_id": "N-1"})
        self.conn.execute(
            "update production_runs set status='running',lease_expires_at=?,error_reason=? where id=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), "simulated crash", run["run_id"]),
        )
        self.conn.execute(
            "update production_stages set status='running',lease_expires_at=? where run_id=? and stage_name='qf_design'",
            ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), run["run_id"]),
        )
        self.conn.commit()

        recovered = orchestrator.recover(run["run_id"])

        self.assertEqual("completed", recovered["status"])
        self.assertEqual(8, len(calls))

    def test_long_action_renews_run_and_stage_leases_before_persistence(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls, delay=1.5),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        }, max_workers=1)
        orchestrator.lease_seconds = 1

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("completed", result["status"])
        self.assertEqual(4, self.conn.execute("select count(*) from production_artifacts").fetchone()[0])

    def test_requeue_invalid_completed_candidates_for_schema_repair(self):
        calls = []
        class RevalidatingCandidate(RecordingSkill):
            invalid = False
            repaired = False

            def validate(self, payload, output):
                return ["candidate_invalid"] if self.invalid and not self.repaired else []

            def run(self, payload):
                if self.invalid:
                    self.repaired = True
                return super().run(payload)

        candidate = RevalidatingCandidate("candidate_generation", calls)
        orchestrator = self._orchestrator({
            "qf_design": RecordingSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": candidate,
        })
        first = orchestrator.run("N-1", {"node_id": "N-1"})
        candidate.invalid = True

        result = orchestrator.requeue_invalid_candidates(first["run_id"])

        self.assertEqual("completed", result["status"])
        self.assertEqual("completed", result["stages"][-1]["status"])
        self.assertGreaterEqual(self.conn.execute("select count(*) from production_audit_events where event_type='schema_validator' and status='rejected'").fetchone()[0], 1)

    def test_max_attempts_is_read_from_persisted_stage_record(self):
        calls = []
        orchestrator = self._orchestrator({
            "qf_design": FailingValidationSkill("qf_design", calls),
            "slot_design": RecordingSkill("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        }, max_attempts=3)
        first = orchestrator.run("N-1", {"node_id": "N-1"})
        self.conn.execute("update production_stages set max_attempts=1 where run_id=?", (first["run_id"],))
        self.conn.commit()
        orchestrator.skills["qf_design"] = RecordingSkill("qf_design", calls)

        result = orchestrator.retry(first["run_id"])

        self.assertEqual("failed", result["status"])
        self.assertIn("retry limit reached", result["error_reason"])

    def test_prepare_failure_does_not_leave_earlier_fanout_stage_running(self):
        calls = []
        class BrokenFanout(RecordingSkill):
            def run(self, payload):
                if self.stage == "qf_design":
                    return [
                        {"qf_id": "qf-a", "node_id": payload["node_id"]},
                        {"qf_id": "qf-b", "node_id": payload["node_id"]},
                    ]
                if self.stage == "slot_design":
                    return [{"slot_id": "slot-a", "qf_id": payload["qf_id"], "node_id": payload["node_id"]}]
                return super().run(payload)
        class BadSlot(RecordingSkill):
            def run(self, payload):
                if payload["qf_id"] == "qf-b":
                    return [{"node_id": payload["node_id"]}]
                return super().run(payload)
        orchestrator = self._orchestrator({
            "qf_design": BrokenFanout("qf_design", calls),
            "slot_design": BadSlot("slot_design", calls),
            "brief_generation": RecordingSkill("brief_generation", calls),
            "candidate_generation": RecordingSkill("candidate_generation", calls),
        })

        result = orchestrator.run("N-1", {"node_id": "N-1"})

        self.assertEqual("failed", result["status"])
        self.assertEqual(0, self.conn.execute("select count(*) from production_stages where status='running'").fetchone()[0])

    def test_concurrent_retry_allows_one_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "retry.sqlite"
            first_conn = sqlite3.connect(path, check_same_thread=False)
            first_conn.row_factory = sqlite3.Row
            db.init_schema(first_conn)
            first_conn.execute(
                "insert into graph_nodes(id,name,stage,domain,priority,summer_mode,sequence_band,prerequisites_json,unlocks_json,raw_json) values (?,?,?,?,?,?,?,?,?,?)",
                ("N-1", "测试节点", "test", "math", "P0", "core", 1, "[]", "[]", "{}"),
            )
            first_conn.commit()
            second_conn = sqlite3.connect(path, check_same_thread=False)
            second_conn.row_factory = sqlite3.Row
            calls = []
            initial = ProductionOrchestrator(first_conn, skills={
                "qf_design": FailingValidationSkill("qf_design", calls),
                "slot_design": RecordingSkill("slot_design", calls),
                "brief_generation": RecordingSkill("brief_generation", calls),
                "candidate_generation": RecordingSkill("candidate_generation", calls),
            }, require_semantic_review=False)
            failed = initial.run("N-1", {"node_id": "N-1"})
            started = threading.Event()
            release = threading.Event()

            class GatedQf(RecordingSkill):
                def run(self, payload):
                    self.calls.append((self.stage, str(payload.get("key") or "")))
                    started.set()
                    release.wait(timeout=2)
                    return [{"qf_id": "qf-1", "node_id": payload["node_id"]}]

            shared = {
                "qf_design": GatedQf("qf_design", calls),
                "slot_design": RecordingSkill("slot_design", calls),
                "brief_generation": RecordingSkill("brief_generation", calls),
                "candidate_generation": RecordingSkill("candidate_generation", calls),
            }
            one = ProductionOrchestrator(first_conn, skills=shared, require_semantic_review=False)
            two = ProductionOrchestrator(second_conn, skills=shared, require_semantic_review=False)

            def invoke(orchestrator):
                try:
                    return ("result", orchestrator.retry(failed["run_id"]))
                except ValueError as exc:
                    return ("error", str(exc))

            with ThreadPoolExecutor(max_workers=2) as executor:
                winner = executor.submit(invoke, one)
                self.assertTrue(started.wait(timeout=2))
                loser = executor.submit(invoke, two)
                loser_result = loser.result(timeout=2)
                release.set()
                winner_result = winner.result(timeout=2)

            self.assertEqual("result", winner_result[0])
            self.assertEqual("completed", winner_result[1]["status"])
            self.assertEqual("error", loser_result[0])
            self.assertIn("only failed runs can be claimed", loser_result[1])
            self.assertEqual(2, [stage for stage, _ in calls if stage == "qf_design"].count("qf_design"))
            first_conn.close()
            second_conn.close()


if __name__ == "__main__":
    unittest.main()
