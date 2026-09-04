from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system import db
from scripts import activate_three_node_pilot
from scripts import guanzhi_browser_regression as browser_regression


class GuanzhiBrowserRegressionScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "browser-regression.sqlite"
        activate_three_node_pilot.activate(self.db_path)
        self.conn = browser_regression._open_conn(self.db_path)
        self.addCleanup(self.conn.close)
        self.assets = browser_regression._active_question_assets(self.conn)

    def _stored_usage(self, step_id: str) -> tuple[dict, dict]:
        step = self.conn.execute(
            "select selection_reason_json from flow_steps where id = ?",
            (step_id,),
        ).fetchone()
        self.assertIsNotNone(step)
        selection_reason = db.json_load(step["selection_reason_json"], {})
        usage = db.flow_step_usage_context(self.conn, step_id)
        self.assertEqual(usage["raw"], selection_reason["requested_usage_context"])
        return selection_reason, usage

    def test_number_line_group_asset_prefers_practice_only_question(self) -> None:
        selected = browser_regression._number_line_practice_asset(self.assets)

        self.assertIsNotNone(selected)
        self.assertEqual("M-G7-NUMBER-LINE", selected["node_id"])
        self.assertIn("practice", selected["usage_policy"]["allowed_purposes"])
        self.assertNotIn("diagnostic", selected["usage_policy"]["allowed_purposes"])

    def test_group_end_oracle_uses_public_child_state_not_internal_ui_alias(self) -> None:
        self.assertIn(
            "analyzing_pending",
            browser_regression.GROUP_END_CHILD_STATES,
        )
        self.assertNotIn("analyzing", browser_regression.GROUP_END_CHILD_STATES)

    def test_materialize_uses_canonical_policy_bound_usage_for_diagnostic_and_practice(self) -> None:
        diagnostic_asset = next(
            asset
            for asset in self.assets
            if "diagnostic" in set(asset["usage_policy"]["allowed_purposes"])
        )
        diagnostic = browser_regression._materialize_question_as_current_step(
            self.conn,
            diagnostic_asset,
            position=1,
        )
        diagnostic_reason, diagnostic_usage = self._stored_usage(diagnostic["step_id"])

        self.assertEqual("diagnostic", diagnostic_reason["target_action"])
        self.assertEqual("diagnostic", diagnostic_usage["purpose"])
        self.assertIn(
            diagnostic_usage["purpose_role"],
            diagnostic_asset["usage_policy"]["diagnostic_roles"],
        )
        self.assertEqual(
            diagnostic_asset["usage_policy"]["policy_digest_sha256"],
            diagnostic_usage["raw"]["question_usage_policy_digest_sha256"],
        )

        practice_asset = next(
            asset
            for asset in self.assets
            if "practice" in set(asset["usage_policy"]["allowed_purposes"])
        )
        practice = browser_regression._materialize_question_as_current_step(
            self.conn,
            practice_asset,
            position=2,
            mini_group=True,
        )
        practice_reason, practice_usage = self._stored_usage(practice["step_id"])

        self.assertEqual("review", practice_reason["target_action"])
        self.assertEqual("practice", practice_usage["purpose"])
        self.assertEqual("consolidation", practice_usage["purpose_role"])
        self.assertEqual(
            practice_asset["usage_policy"]["default_practice_family"],
            practice_usage["practice_family"],
        )
        self.assertIn(
            practice_usage["practice_role"],
            practice_asset["usage_policy"]["allowed_practice_roles"],
        )
        self.assertEqual(
            practice_usage["raw"],
            practice_reason["mini_group"]["usage_context"],
        )
        self.assertEqual(
            practice_asset["usage_policy"]["policy_digest_sha256"],
            practice_usage["raw"]["question_usage_policy_digest_sha256"],
        )

    def test_support_only_question_materializes_as_teaching_not_review(self) -> None:
        support_asset = next(
            asset
            for asset in self.assets
            if asset["usage_policy"]["support_only"]
        )

        materialized = browser_regression._materialize_question_as_current_step(
            self.conn,
            support_asset,
            position=3,
        )
        selection_reason, usage = self._stored_usage(materialized["step_id"])

        self.assertEqual("teaching", selection_reason["target_action"])
        self.assertEqual("teaching", usage["purpose"])
        self.assertNotIn("diagnostic", support_asset["usage_policy"]["allowed_purposes"])
        self.assertNotIn("practice", support_asset["usage_policy"]["allowed_purposes"])

    def test_knowledge_home_unavailable_returns_needs_fix_instead_of_crashing(self) -> None:
        class FakeLocator:
            def click(self) -> None:
                return None

        class FakePage:
            def __init__(self) -> None:
                self.screenshots: list[str] = []

            def reload(self, **_kwargs) -> None:
                return None

            def wait_for_selector(self, _selector: str, **_kwargs) -> None:
                return None

            def locator(self, _selector: str) -> FakeLocator:
                return FakeLocator()

            def screenshot(self, *, path: str, **_kwargs) -> None:
                self.screenshots.append(path)

        page = FakePage()
        output_dir = Path(self.temp_dir.name) / "artifacts"
        output_dir.mkdir()
        with mock.patch.object(
            browser_regression,
            "_request_json",
            return_value={
                "status": 503,
                "payload": {
                    "state": "unavailable",
                    "message": "知识首页还在准备中。",
                },
            },
        ):
            result = browser_regression._knowledge_home_browser_audit(
                page,
                output_dir=output_dir,
            )

        self.assertEqual("NEEDS_FIX", result["status"])
        self.assertEqual(1, result["issue_count"])
        self.assertEqual(["knowledge-map status=503"], result["issues"])
        self.assertTrue(page.screenshots[0].endswith("knowledge-home-unavailable.png"))


if __name__ == "__main__":
    unittest.main()
