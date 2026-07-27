from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from learning_system import daily_runtime, db, server
from tests.test_knowledge_views_v51 import (
    PROJECT_ROOT,
    QUESTION_VISUAL_ACTIVATION_SCRIPT,
    KnowledgeViewsV51TestCase,
)


BROWSER_REGRESSION_FIXTURE = (
    PROJECT_ROOT / "tests/fixtures/browser_knowledge_views_v51_regressions.mjs"
)
BROWSER_ACTION_CONTINUITY_FIXTURE = (
    PROJECT_ROOT
    / "tests/fixtures/browser_knowledge_views_v51_action_continuity.mjs"
)


class DualViewBrowserRegressionTests(KnowledgeViewsV51TestCase):
    def _post_json(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _install_descriptor_action_fixture(self, conn, config: dict) -> list[str]:
        selected_node_ids = sorted(self.child_visible_node_ids)[:3]
        assets = self._install_view_activation(
            conn,
            config_payload=config,
            assessment_node_ids=selected_node_ids,
        )
        stable_lineage = self._install_authoritative_mastery(
            conn,
            assets[0],
            status_code="A",
        )
        conn.execute(
            "update daily_flows set local_date = '2026-07-14' where id = ?",
            (stable_lineage["flow_id"],),
        )
        conn.commit()
        self._install_authoritative_mastery(conn, assets[1], status_code="D")
        self._install_resumable_question_step(conn, assets[2])
        return [self.nodes[asset["node_id"]]["name"] for asset in assets]

    def test_current_learning_uses_today_flow_instead_of_latest_cross_day_write(self):
        config = self._load_view_config_json()
        node_ids = sorted(self.child_visible_node_ids)[:2]
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1", assessment_policy="v5.1"
        ):
            with closing(db.connect(path)) as conn:
                assets = self._install_view_activation(
                    conn,
                    config_payload=config,
                    assessment_node_ids=node_ids,
                )
                stale = self._install_authoritative_mastery(conn, assets[0])
                conn.execute(
                    """
                    update daily_flows
                    set local_date = ?, updated_at = '2099-12-31T23:59:59+00:00'
                    where id = ?
                    """,
                    ((date.today() - timedelta(days=1)).isoformat(), stale["flow_id"]),
                )
                self._install_resumable_question_step(conn, assets[1])
                conn.commit()
                payload = self._service(conn).child_projection(child_key="single-child")

        self.assertEqual(
            self.nodes[assets[1]["node_id"]]["name"],
            payload["current_learning"]["topic_label"],
        )
        self.assertEqual("current_step", payload["current_learning"]["state"])

    def _install_enabled_descriptor_post_fixture(
        self,
        conn,
        config: dict,
        *,
        include_alternate_teaching_asset: bool = True,
    ) -> list[str]:
        target_node_ids = [
            "M-PRE-NUMBER-SENSE",
            "M-BRIDGE-MOTION-BASIC",
            "M-PRE-ORDER-OPS",
        ]
        prerequisite_node_ids = [
            "M-PRE-QUANTITY-RELATION",
            "M-PRE-UNIT-CONVERSION",
        ]
        selected_node_ids = [*target_node_ids]
        if include_alternate_teaching_asset:
            selected_node_ids.append(target_node_ids[2])
        selected_node_ids.extend(prerequisite_node_ids)
        assets = self._install_view_activation(
            conn,
            config_payload=config,
            assessment_node_ids=selected_node_ids,
        )
        assets_by_node = {}
        for asset in assets:
            assets_by_node.setdefault(asset["node_id"], asset)
        for index, node_id in enumerate(prerequisite_node_ids, start=1):
            lineage = self._install_authoritative_mastery(
                conn,
                assets_by_node[node_id],
                status_code="A",
            )
            conn.execute(
                "update daily_flows set local_date = ? where id = ?",
                (f"2026-06-{index:02d}", lineage["flow_id"]),
            )
            conn.commit()
        stable_lineage = self._install_authoritative_mastery(
            conn,
            assets_by_node[target_node_ids[0]],
            status_code="A",
        )
        conn.execute(
            "update daily_flows set local_date = '2026-07-14' where id = ?",
            (stable_lineage["flow_id"],),
        )
        conn.commit()
        prerequisite_target = self._install_authoritative_mastery(
            conn,
            assets_by_node[target_node_ids[1]],
            status_code="D",
        )
        conn.execute(
            "update daily_flows set local_date = '2026-07-13' where id = ?",
            (prerequisite_target["flow_id"],),
        )
        conn.commit()
        self._install_resumable_question_step(
            conn,
            assets_by_node[target_node_ids[2]],
        )
        return [self.nodes[node_id]["name"] for node_id in target_node_ids]

    def test_learn_descriptor_is_disabled_without_unused_teaching_instance(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1",
            assessment_policy="v5.1",
        ):
            with closing(db.connect(path)) as conn:
                node_names = self._install_enabled_descriptor_post_fixture(
                    conn,
                    config,
                    include_alternate_teaching_asset=False,
                )
            httpd, base_url = server.start_test_server(path)
            try:
                get_status, projection = self._request_json(
                    base_url,
                    "/api/knowledge-map",
                )
                self.assertEqual(200, get_status, projection)
                node = next(
                    item for item in projection["nodes"] if item["name"] == node_names[2]
                )
                descriptor = next(
                    item
                    for item in node["action_descriptors"]
                    if item["action"] == "learn"
                )
                post_status, post_result = self._post_json(
                    base_url,
                    "/api/knowledge-map/select",
                    {
                        "handle": node["handle"],
                        "projection_version": projection["projection_version"],
                        "action": "learn",
                        "client_idempotency_key": "qa-no-unused-teaching-instance",
                    },
                )
            finally:
                httpd.shutdown()
                httpd.server_close()
            with closing(db.connect(path)) as conn:
                intent_count = conn.execute(
                    "select count(*) from learning_target_intents where client_idempotency_key = ?",
                    ("qa-no-unused-teaching-instance",),
                ).fetchone()[0]
        self.assertFalse(descriptor["enabled"], descriptor)
        self.assertEqual("wait_for_safe_boundary", descriptor["result_behavior"])
        self.assertIn("没有新的例题", descriptor["disabled_reason"])
        self.assertEqual(409, post_status, post_result)
        self.assertEqual("conflict", post_result.get("state"), post_result)
        self.assertNotIn(post_result.get("status"), {"applied", "waiting_for_safe_boundary"})
        self.assertEqual(0, intent_count)

    def test_displayed_question_learn_waits_then_uses_a_different_teaching_instance(self):
        config = self._load_view_config_json()
        with self._temp_database() as path, self._policy_env(
            map_policy="v5.1",
            assessment_policy="v5.1",
        ), closing(db.connect(path)) as conn:
            node_names = self._install_enabled_descriptor_post_fixture(conn, config)
            conn.execute(
                "update flow_steps set status = 'displayed' where id = 'FS-kv51-resume-oracle'"
            )
            conn.commit()
            service = self._service(conn)
            projection = service.child_projection(child_key="single-child")
            node = next(
                item for item in projection["nodes"] if item["name"] == node_names[2]
            )
            descriptor = next(
                item
                for item in node["action_descriptors"]
                if item["action"] == "learn"
            )
            source_step = conn.execute(
                "select * from flow_steps where id = 'FS-kv51-resume-oracle'"
            ).fetchone()
            source_question = db.get_question(conn, source_step["question_id"])

            self.assertTrue(descriptor["enabled"], descriptor)
            self.assertEqual("wait_for_safe_boundary", descriptor["result_behavior"])
            waiting = service.select_target(
                child_key="single-child",
                request={
                    "handle": node["handle"],
                    "projection_version": projection["projection_version"],
                    "action": "learn",
                    "client_idempotency_key": "qa-learn-after-displayed-question",
                },
            )
            self.assertEqual("waiting_for_safe_boundary", waiting["status"])
            self.assertEqual("wait_for_safe_boundary", waiting["result_behavior"])
            self.assertEqual(
                0,
                conn.execute(
                    "select count(*) from flow_steps where flow_id = ? and step_type = 'worked_example'",
                    (source_step["flow_id"],),
                ).fetchone()[0],
            )

            conn.execute(
                "update flow_steps set status = 'completed' where id = ?",
                (source_step["id"],),
            )
            conn.commit()
            recovered = daily_runtime.DailyLearningRuntime(
                conn,
                project_root=PROJECT_ROOT,
            ).recover_target_intents()

            self.assertEqual("applied", recovered["status"], recovered)
            teaching_step = conn.execute(
                "select * from flow_steps where id = ?",
                (recovered["step_id"],),
            ).fetchone()
            teaching_question = db.get_question(conn, teaching_step["question_id"])
            self.assertEqual(source_step["flow_id"], teaching_step["flow_id"])
            self.assertEqual("worked_example", teaching_step["step_type"])
            self.assertEqual("selected", teaching_step["status"])
            self.assertEqual(source_step["node_id"], teaching_step["node_id"])
            self.assertNotEqual(source_step["question_id"], teaching_step["question_id"])
            self.assertNotEqual(
                source_question["problem_instance_id"],
                teaching_question["problem_instance_id"],
            )
            self.assertEqual(
                1,
                conn.execute(
                    "select count(*) from flow_steps where flow_id = ? and step_type = 'worked_example'",
                    (source_step["flow_id"],),
                ).fetchone()[0],
            )

    def _install_resumable_question_step(self, conn, asset: dict) -> None:
        now = f"{date.today().isoformat()}T08:00:00+08:00"
        session_id = "LS-kv51-resume-oracle"
        flow_id = "DF-kv51-resume-oracle"
        step_id = "FS-kv51-resume-oracle"
        prompt = "请写出这个知识点的一条关键关系，并说明理由。"
        prompt_package = {
            "topic_label": self.nodes[asset["node_id"]]["name"],
            "prompt": prompt,
            "answer_input_mode": "text",
            "allowed_response_modes": ["text", "stuck"],
            "upload_enabled": False,
            "stuck_enabled": True,
        }
        with conn:
            conn.execute(
                "insert into learning_sessions(id, title, mode, status, created_at) "
                "values (?, 'kv51 resume oracle', 'daily_flow_v3', 'active', ?)",
                (session_id, now),
            )
            conn.execute(
                """
                insert into daily_flows(
                  id, child_key, local_date, mode, status, current_step_id,
                  graph_version, question_bank_version, legacy_session_id,
                  assessment_policy_version, created_at, updated_at
                ) values (?, 'single-child', ?, 'review_old_knowledge', 'active', ?,
                          ?, ?, ?, 'v5.1', ?, ?)
                """,
                (
                    flow_id,
                    date.today().isoformat(),
                    step_id,
                    self.graph_lineage,
                    asset["item_version"],
                    session_id,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                insert into flow_steps(
                  id, flow_id, step_handle, position, step_type, status,
                  graph_version, node_id, question_bank_version, question_id,
                  question_item_version, review_record_id, answer_contract_id,
                  answer_contract_version, answer_contract_digest_sha256,
                  prompt_package_json, created_at, updated_at
                ) values (?, ?, 'resume-current-step', 1, 'question', 'selected',
                          ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    flow_id,
                    self.graph_lineage,
                    asset["node_id"],
                    asset["item_version"],
                    asset["question_id"],
                    asset["item_version"],
                    asset["review_record_id"],
                    asset["contract_id"],
                    asset["contract_digest_sha256"],
                    db.json_dump(prompt_package),
                    now,
                    now,
                ),
            )

    def test_review_regressions_have_independent_browser_oracles(self):
        self._require_file(BROWSER_REGRESSION_FIXTURE, "child map regression browser fixture")
        config = self._load_view_config_json()

        with (
            self._temp_database() as path,
            tempfile.TemporaryDirectory(prefix="kv51-regression-backup-") as backup_root,
            tempfile.TemporaryDirectory(prefix="kv51-regression-evidence-") as evidence_dir,
        ):
            with closing(db.connect(path)) as conn:
                stable_node_name, prerequisite_node_name, current_node_name = (
                    self._install_enabled_descriptor_post_fixture(conn, config)
                )
            visual_activation = subprocess.run(
                [
                    "python3",
                    str(QUESTION_VISUAL_ACTIVATION_SCRIPT),
                    "--db",
                    str(path),
                    "--activate",
                    "--backup-root",
                    backup_root,
                    "--json",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                0,
                visual_activation.returncode,
                visual_activation.stderr or visual_activation.stdout,
            )
            with self._policy_env(map_policy="v5.1", assessment_policy="v5.1"):
                httpd, base_url = server.start_test_server(path)
                try:
                    completed = subprocess.run(
                        [
                            "node",
                            str(BROWSER_REGRESSION_FIXTURE),
                            "--base-url",
                            base_url,
                            "--evidence-dir",
                            evidence_dir,
                            "--stable-node-name",
                            stable_node_name,
                            "--prerequisite-node-name",
                            prerequisite_node_name,
                            "--current-node-name",
                            current_node_name,
                        ],
                        cwd=PROJECT_ROOT,
                        text=True,
                        capture_output=True,
                        timeout=90,
                        check=False,
                    )
                finally:
                    httpd.shutdown()
                    httpd.server_close()

            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            payload = json.loads(completed.stdout)
            report = payload.get("report") or {}
            expected = {
                "child_map_only_projection",
                "mobile_sheet_modal_cleanup",
                "graph_preference_is_ignored",
                "hide_show_preserves_child_surface",
                "search_selection_restores_context",
                "resume_requires_fresh_bootstrap_current_step",
                "state_appropriate_action_descriptors",
            }
            self.assertEqual(expected, set(report), payload)
            self.assertEqual(
                {
                    "knowledge-v51-regression-mobile-sheet-cleanup.png",
                    "knowledge-v51-regression-graph-cache-ignored.png",
                    "knowledge-v51-regression-search-selection-restore.png",
                    "knowledge-v51-regression-hide-show-child-surface.png",
                },
                set(payload.get("screenshots") or {}),
                payload,
            )
            for screenshot_path in (payload.get("screenshots") or {}).values():
                self.assertGreater(Path(screenshot_path).stat().st_size, 0)
            for case_name in sorted(expected):
                with self.subTest(case=case_name):
                    self.assertTrue(report[case_name].get("pass"), report[case_name])

    def test_enabled_descriptor_post_result_matches_result_behavior(self):
        config = self._load_view_config_json()
        target_actions = [
            (0, "challenge"),
            (0, "review"),
            (1, "learn"),
            (2, "diagnostic"),
            (2, "learn"),
        ]
        expected_status_by_behavior = {
            "enter_now": "applied",
            "wait_for_safe_boundary": "waiting_for_safe_boundary",
            "preview": "preview",
        }
        observed = []
        for node_index, action in target_actions:
            with self.subTest(node_index=node_index, action=action):
                with self._temp_database() as path, self._policy_env(
                    map_policy="v5.1",
                    assessment_policy="v5.1",
                ):
                    with closing(db.connect(path)) as conn:
                        node_names = self._install_enabled_descriptor_post_fixture(conn, config)
                    httpd, base_url = server.start_test_server(path)
                    try:
                        get_status, projection = self._request_json(base_url, "/api/knowledge-map")
                        self.assertEqual(200, get_status, projection)
                        node = next(
                            item
                            for item in projection["nodes"]
                            if item["name"] == node_names[node_index]
                        )
                        descriptor = next(
                            item
                            for item in node["action_descriptors"]
                            if item["action"] == action
                        )
                        self.assertTrue(descriptor["enabled"], descriptor)
                        self.assertIn(
                            descriptor["result_behavior"],
                            expected_status_by_behavior,
                        )
                        if node_index == 2 and action == "learn":
                            self.assertEqual(
                                "wait_for_safe_boundary",
                                descriptor["result_behavior"],
                                descriptor,
                            )
                        post_status, result = self._post_json(
                            base_url,
                            "/api/knowledge-map/select",
                            {
                                "handle": node["handle"],
                                "projection_version": projection["projection_version"],
                                "action": action,
                                "client_idempotency_key": (
                                    f"qa-descriptor-result-{node_index}-{action}"
                                ),
                            },
                        )
                    finally:
                        httpd.shutdown()
                        httpd.server_close()
                    expected_result = expected_status_by_behavior[
                        descriptor["result_behavior"]
                    ]
                    observed.append({
                        "node": node["name"],
                        "action": action,
                        "result_behavior": descriptor["result_behavior"],
                        "expected_status": expected_result,
                        "actual_status": result.get("status"),
                    })
                    self.assertEqual(200, post_status, result)
                    self.assertEqual(expected_result, result.get("status"), observed)
                    if node_index == 2 and action == "learn":
                        self.assertEqual("waiting_for_safe_boundary", result.get("status"))
                        self.assertEqual(
                            "wait_for_safe_boundary",
                            result.get("result_behavior"),
                        )

    def test_action_target_continuity_from_clicked_label_to_learning_heading(self):
        self._require_file(
            BROWSER_ACTION_CONTINUITY_FIXTURE,
            "knowledge-view action target continuity browser fixture",
        )
        config = self._load_view_config_json()
        for target_action in ("challenge", "review"):
            with self.subTest(target_action=target_action):
                with (
                    self._temp_database() as path,
                    tempfile.TemporaryDirectory(
                        prefix="kv51-continuity-backup-"
                    ) as backup_root,
                    tempfile.TemporaryDirectory(
                        prefix="kv51-continuity-evidence-"
                    ) as evidence_dir,
                ):
                    with closing(db.connect(path)) as conn:
                        target_node_name = self._install_enabled_descriptor_post_fixture(
                            conn,
                            config,
                        )[0]
                    visual_activation = subprocess.run(
                        [
                            "python3",
                            str(QUESTION_VISUAL_ACTIVATION_SCRIPT),
                            "--db",
                            str(path),
                            "--activate",
                            "--backup-root",
                            backup_root,
                            "--json",
                        ],
                        cwd=PROJECT_ROOT,
                        text=True,
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(
                        0,
                        visual_activation.returncode,
                        visual_activation.stderr or visual_activation.stdout,
                    )
                    with self._policy_env(
                        map_policy="v5.1",
                        assessment_policy="v5.1",
                    ):
                        httpd, base_url = server.start_test_server(path)
                        try:
                            completed = subprocess.run(
                                [
                                    "node",
                                    str(BROWSER_ACTION_CONTINUITY_FIXTURE),
                                    "--base-url",
                                    base_url,
                                    "--target-node-name",
                                    target_node_name,
                                    "--target-action",
                                    target_action,
                                    "--evidence-dir",
                                    evidence_dir,
                                ],
                                cwd=PROJECT_ROOT,
                                text=True,
                                capture_output=True,
                                timeout=60,
                                check=False,
                            )
                        finally:
                            httpd.shutdown()
                            httpd.server_close()

                    self.assertEqual(
                        0,
                        completed.returncode,
                        completed.stderr or completed.stdout,
                    )
                    payload = json.loads(completed.stdout)
                    screenshot = Path(payload["screenshot"])
                    self.assertGreater(screenshot.stat().st_size, 0, payload)
                    self.assertTrue(
                        payload.get("report", {}).get("pass"),
                        json.dumps(payload, ensure_ascii=False, indent=2),
                    )


if __name__ == "__main__":
    unittest.main()
