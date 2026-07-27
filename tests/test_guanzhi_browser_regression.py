from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
