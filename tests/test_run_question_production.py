from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts.run_question_production import execute_action


class RecordingOrchestrator:
    def __init__(self) -> None:
        self.calls = []

    def run_until(self, node_id, node, until_stage):
        self.calls.append(("run_until", node_id, node, until_stage))
        return {"status": "paused"}

    def resume(self, run_id, until_stage=None):
        self.calls.append(("resume", run_id, until_stage))
        return {"status": "paused"}

    def promote(self, **kwargs):
        self.calls.append(("promote", kwargs))
        return {"status": "staged"}

    def retry(self, run_id):
        self.calls.append(("retry", run_id))
        return {"status": "completed"}

    def recover(self, run_id):
        self.calls.append(("recover", run_id))
        return {"status": "completed"}

    def rerun(self, node_id, node, *, source_run_id=None):
        self.calls.append(("rerun", node_id, node, source_run_id))
        return {"status": "completed"}

    def revise_structure(self, node_id, node, *, source_run_id, feedback):
        self.calls.append(("revise_structure", node_id, node, source_run_id, feedback))
        return {"status": "paused"}


class RunQuestionProductionTests(unittest.TestCase):
    def test_retry_action_uses_explicit_run_retry(self):
        orchestrator = RecordingOrchestrator()

        result = execute_action(
            orchestrator,
            SimpleNamespace(
                action="retry",
                run_id="PR-test",
                node="M-G7-ABSOLUTE",
                until=None,
            ),
            node={"node_id": "M-G7-ABSOLUTE"},
        )

        self.assertEqual({"status": "completed"}, result)
        self.assertEqual([("retry", "PR-test")], orchestrator.calls)

    def test_rerun_action_uses_a_new_run_boundary(self):
        orchestrator = RecordingOrchestrator()

        result = execute_action(
            orchestrator,
            SimpleNamespace(
                action="rerun",
                run_id=None,
                node="M-G7-COMPARE",
                until=None,
                source_run_id="PR-source",
            ),
            node={"node_id": "M-G7-COMPARE"},
        )

        self.assertEqual({"status": "completed"}, result)
        self.assertEqual(
            [("rerun", "M-G7-COMPARE", {"node_id": "M-G7-COMPARE", "node": {"node_id": "M-G7-COMPARE"}}, "PR-source")],
            orchestrator.calls,
        )

    def test_resume_action_can_stop_at_a_requested_stage(self):
        orchestrator = RecordingOrchestrator()

        execute_action(
            orchestrator,
            SimpleNamespace(
                action="resume",
                run_id="PR-test",
                node="M-G7-ABSOLUTE",
                until="slot_design",
            ),
            node={"node_id": "M-G7-ABSOLUTE"},
        )

        self.assertEqual([("resume", "PR-test", "slot_design")], orchestrator.calls)

    def test_promote_action_uses_the_formal_promotion_boundary(self):
        class PromotionOrchestrator(RecordingOrchestrator):
            def __init__(self):
                super().__init__()
                self.conn = object()

        orchestrator = PromotionOrchestrator()
        from unittest.mock import patch

        result = execute_action(
            orchestrator,
            SimpleNamespace(
                action="promote",
                run_id="PR-test",
                node=None,
                until=None,
                question_bank_version="bank-test-1",
                graph_version="graph-test-1",
                manifest_id="manifest-test-1",
            ),
        )

        self.assertEqual({"status": "staged"}, result)
        self.assertEqual(
            [("promote", {"run_id": "PR-test", "question_bank_version": "bank-test-1", "graph_version": "graph-test-1", "manifest_id": "manifest-test-1"})],
            orchestrator.calls,
        )

    def test_structure_revision_action_uses_source_run_feedback(self):
        orchestrator = RecordingOrchestrator()

        result = execute_action(
            orchestrator,
            SimpleNamespace(
                action="revise_structure",
                run_id=None,
                node="N-1",
                until=None,
                source_run_id="PR-source",
                feedback=[{"message": "upstream conflict"}],
            ),
            node={"node_id": "N-1"},
        )

        self.assertEqual({"status": "paused"}, result)
        self.assertEqual(
            [("revise_structure", "N-1", {"node_id": "N-1"}, "PR-source", [{"message": "upstream conflict"}])],
            orchestrator.calls,
        )


if __name__ == "__main__":
    unittest.main()
