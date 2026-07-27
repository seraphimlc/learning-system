from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning_system import child_prompt, daily_runtime, db, knowledge_map, question_usage
from scripts import activate_three_node_pilot as activation
import tests.test_learning_system as learning_system_tests


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ThreeNodePilotActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "pilot.sqlite"

    def _manifest(self) -> dict:
        return json.loads(activation.DEFAULT_MANIFEST.read_text(encoding="utf-8"))

    def _write_manifest(self, value: dict, name: str = "pilot.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _seed_recent_node_history(
        self,
        conn,
        runtime: daily_runtime.DailyLearningRuntime,
        *,
        node_id: str,
        local_date: str,
    ) -> str:
        graph_version = runtime.graph.current_graph_version()
        with conn:
            flow = runtime._create_daily_flow(local_date, graph_version)
            now = db.now_iso()
            rows = conn.execute(
                """
                select q.id, q.item_version, r.id as review_record_id
                from question_items q
                join question_review_records r
                  on r.question_id = q.id
                 and r.item_version = q.item_version
                 and r.review_status = 'approved'
                 and r.active_eligible = 1
                where q.node_id = ?
                  and q.item_version = ?
                order by q.id
                """,
                (node_id, activation.PILOT_VERSION),
            ).fetchall()
            self.assertGreaterEqual(len(rows), 4)
            for index, row in enumerate(rows, start=1):
                conn.execute(
                    """
                    insert into flow_steps(
                      id, flow_id, step_handle, position, step_type, status,
                      graph_version, node_id, question_bank_version,
                      question_id, question_item_version, review_record_id,
                      expected_evidence_json, prompt_package_json,
                      selection_reason_json, step_revision, created_at, updated_at
                    ) values (?, ?, ?, ?, 'question', 'completed', ?, ?, ?, ?, ?, ?, '{}', '{}', ?, 1, ?, ?)
                    """,
                    (
                        f"FS-history-{index}",
                        flow["id"],
                        f"step-history-{index}",
                        index,
                        graph_version,
                        node_id,
                        activation.PILOT_VERSION,
                        row["id"],
                        row["item_version"],
                        row["review_record_id"],
                        db.json_dump({"reason": "recent_formal_bank_cooldown_fixture"}),
                        now,
                        now,
                    ),
                )
            conn.execute(
                """
                update daily_flows
                set mode = 'review_old_knowledge', status = 'completed',
                    current_step_id = null, updated_at = ?
                where id = ?
                """,
                (now, flow["id"]),
            )
        return flow["id"]

    def test_activates_exact_reviewed_three_node_bank_and_contracts(self) -> None:
        result = activation.activate(self.db_path)

        self.assertEqual("activated", result["status"])
        self.assertEqual(17, result["item_count"])
        self.assertEqual(18, result["manifest_item_count"])
        self.assertEqual(3, result["node_count"])
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)

        ledgers = conn.execute(
            "select * from question_bank_version_ledger order by id"
        ).fetchall()
        self.assertEqual(1, len(ledgers))
        self.assertEqual(activation.PILOT_VERSION, ledgers[0]["question_bank_version"])
        self.assertEqual("active", ledgers[0]["status"])
        self.assertEqual(17, ledgers[0]["item_count"])
        self.assertEqual(3, ledgers[0]["node_count"])

        rows = conn.execute(
            "select * from question_items order by node_id, id"
        ).fetchall()
        self.assertEqual(17, len(rows))
        self.assertEqual(
            {
                "M-PRE-INTEGER-OPS": 6,
                "M-G7-NUMBER-LINE": 5,
                "M-G7-EQ-SOLVE": 6,
            },
            dict(
                conn.execute(
                    "select node_id, count(*) from question_items group by node_id"
                ).fetchall()
            ),
        )
        questions = [db.row_to_question(row) for row in rows]
        self.assertEqual(17, len({question["problem_instance_id"] for question in questions}))
        self.assertNotIn("MATH-PILOT-V1-NL-01", {question["id"] for question in questions})
        self.assertTrue(all(question["source_type"] == "graph_generated" for question in questions))
        self.assertTrue(
            all(
                question["interaction_schema"]["schema_version"]
                == child_prompt.QUESTION_INTERACTION_SCHEMA_V2
                and question["interaction_schema"]["type"] == "short_text"
                for question in questions
            )
        )
        self.assertEqual(
            0,
            conn.execute(
                "select count(*) from question_items where item_version != ?",
                (activation.PILOT_VERSION,),
            ).fetchone()[0],
        )

        policies = conn.execute(
            "select * from question_usage_policies where status = 'active'"
        ).fetchall()
        self.assertEqual(17, len(policies))
        self.assertTrue(all(row["item_version"] == activation.PILOT_VERSION for row in policies))
        for question in questions:
            policy = db.active_question_usage_policy(
                conn, question["id"], item_version=activation.PILOT_VERSION
            )
            self.assertIsNotNone(policy)
            self.assertIn("teaching", policy["allowed_purposes"])
            self.assertEqual(
                question_usage.policy_digest(question["raw"]["usage_policy"]),
                policy["policy_digest_sha256"],
            )

        reviews = conn.execute(
            """
            select qrr.*, ar.agent_key, ar.phase, ar.status as run_status
            from question_review_records qrr
            join agent_runs ar on ar.id = qrr.reviewer_run_id
            order by qrr.question_id
            """
        ).fetchall()
        self.assertEqual(17, len(reviews))
        self.assertTrue(all(row["review_status"] == "approved" for row in reviews))
        self.assertTrue(all(row["active_eligible"] == 1 for row in reviews))
        self.assertTrue(all(row["agent_key"] == "question_reviewer_agent" for row in reviews))
        self.assertTrue(all(row["phase"] == "question_quality_review" for row in reviews))
        self.assertTrue(all(row["run_status"] == "accepted" for row in reviews))

        contracts = conn.execute(
            "select * from answer_contracts where status = 'active' order by question_id"
        ).fetchall()
        self.assertEqual(17, len(contracts))
        for contract in contracts:
            self.assertEqual(activation.PILOT_VERSION, contract["item_version"])
            self.assertEqual(activation.PILOT_VERSION, contract["question_bank_version"])
            score_points = db.json_load(contract["score_points_json"], [])
            self.assertEqual(10, sum(point["points"] for point in score_points))
            self.assertGreaterEqual(len(score_points), 2)

        receipt_row = conn.execute(
            "select value from system_meta where key = ?",
            (knowledge_map.ASSESSMENT_RECEIPT_KEY,),
        ).fetchone()
        receipt = db.json_load(receipt_row["value"], {})
        self.assertEqual("lightweight_local_contracts_v1", receipt["activation_mode"])
        self.assertEqual(17, receipt["active_contract_count"])
        self.assertEqual(activation.PILOT_VERSION, receipt["question_bank_version"])

    def test_repeated_activation_is_idempotent(self) -> None:
        first = activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        before = {
            "ledger": tuple(conn.execute(
                "select id, activated_at, updated_at from question_bank_version_ledger"
            ).fetchone()),
            "runs": conn.execute("select count(*) from agent_runs").fetchone()[0],
            "reviews": conn.execute("select count(*) from question_review_records").fetchone()[0],
            "contracts": conn.execute("select count(*) from answer_contracts").fetchone()[0],
        }
        conn.close()

        second = activation.activate(self.db_path)

        self.assertEqual("activated", first["status"])
        self.assertEqual("already_active", second["status"])
        self.assertEqual(first["ledger_id"], second["ledger_id"])
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        after = {
            "ledger": tuple(conn.execute(
                "select id, activated_at, updated_at from question_bank_version_ledger"
            ).fetchone()),
            "runs": conn.execute("select count(*) from agent_runs").fetchone()[0],
            "reviews": conn.execute("select count(*) from question_review_records").fetchone()[0],
            "contracts": conn.execute("select count(*) from answer_contracts").fetchone()[0],
        }
        self.assertEqual(before, after)

    def test_malformed_manifest_fails_before_database_creation(self) -> None:
        malformed = self._manifest()
        malformed["items"][0]["scoring_targets"][0]["points"] = 7
        manifest_path = self._write_manifest(malformed)

        with self.assertRaisesRegex(ValueError, "must total 10"):
            activation.activate(self.db_path, manifest_path=manifest_path)

        self.assertFalse(self.db_path.exists())

    def test_expert_activation_order_and_hold_are_runtime_authoritative(self) -> None:
        _manifest, items, _digest = activation.load_pilot(activation.DEFAULT_MANIFEST)
        by_id = {item["id"]: item for item in items}
        self.assertEqual("hold", by_id["MATH-PILOT-V1-NL-01"]["activation_status"])
        self.assertTrue(by_id["MATH-PILOT-V1-NL-01"]["usage_policy"]["not_for_activation"])

        authority = {"assessment": {"assets_by_node": {}}}
        for node_id in activation.PILOT_NODE_IDS:
            authority["assessment"]["assets_by_node"][node_id] = [
                {"question_id": item["id"], "question": item}
                for item in items
                if item["node_id"] == node_id and item["activation_status"] == "active"
            ]

        expected_first = {
            "M-PRE-INTEGER-OPS": "MATH-PILOT-V1-IO-03",
            "M-G7-NUMBER-LINE": "MATH-PILOT-V1-NL-02",
            "M-G7-EQ-SOLVE": "MATH-PILOT-V1-EQ-02",
        }
        for node_id, question_id in expected_first.items():
            selected = daily_runtime._authoritative_target_asset(
                authority,
                node_id=node_id,
                action="diagnostic",
            )
            self.assertEqual(question_id, selected["question_id"])

    def test_expert_activation_order_is_preserved_by_real_database_authority(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        with patch.dict(
            "os.environ",
            {
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            service = knowledge_map.KnowledgeMapService(
                conn,
                project_root=PROJECT_ROOT,
            )
            snapshot = knowledge_map.GraphRuntimeService(
                project_root=PROJECT_ROOT
            ).graph_snapshot()
            authority = {"assessment": service._assessment_authority(snapshot)}

        expected_first = {
            "M-PRE-INTEGER-OPS": "MATH-PILOT-V1-IO-03",
            "M-G7-NUMBER-LINE": "MATH-PILOT-V1-NL-02",
            "M-G7-EQ-SOLVE": "MATH-PILOT-V1-EQ-02",
        }
        for node_id, question_id in expected_first.items():
            selected = daily_runtime._authoritative_target_asset(
                authority,
                node_id=node_id,
                action="diagnostic",
            )
            self.assertEqual(question_id, selected["question_id"])

    def test_expert_scoring_revisions_do_not_over_penalize_nonessential_writing(self) -> None:
        _manifest, items, _digest = activation.load_pilot(activation.DEFAULT_MANIFEST)
        by_id = {item["id"]: item for item in items}

        def target(question_id: str, key: str) -> dict:
            return next(
                point
                for point in by_id[question_id]["scoring_targets"]
                if point["key"] == key
            )

        self.assertFalse(target("MATH-PILOT-V1-IO-02", "correct_judgment")["required_for_pass"])
        self.assertTrue(target("MATH-PILOT-V1-IO-03", "valid_regrouping")["required_for_pass"])
        self.assertFalse(target("MATH-PILOT-V1-IO-04", "correct_result")["required_for_pass"])
        self.assertFalse(target("MATH-PILOT-V1-NL-04", "direction_reason")["required_for_pass"])
        self.assertEqual(4, target("MATH-PILOT-V1-EQ-03", "equivalent_reduction")["points"])
        self.assertTrue(target("MATH-PILOT-V1-EQ-03", "equivalent_reduction")["required_for_pass"])

    def test_runtime_uses_two_item_group_and_does_not_repeat_across_flows(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        with patch.dict(
            "os.environ",
            {
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            first = runtime.start_review_mode(client_day_key="2099-07-26")
            first_flow_id = conn.execute(
                "select flow_id from flow_steps where step_handle = ?",
                (first["current_step"]["step_handle"],),
            ).fetchone()["flow_id"]
            first_step = conn.execute(
                "select question_id, selection_reason_json from flow_steps where flow_id = ? order by created_at limit 1",
                (first_flow_id,),
            ).fetchone()
            first_group = db.json_load(first_step["selection_reason_json"], {})["mini_group"]
            self.assertEqual("MATH-PILOT-V1-NL-02", first_step["question_id"])
            self.assertEqual(2, first_group["size"])
            self.assertTrue(first_group["defer_analysis_until_group_end"])

            runtime.complete_summary(first_flow_id)
            second = runtime.start_review_mode(client_day_key="2099-07-26-second-tab")
            second_flow_id = conn.execute(
                "select flow_id from flow_steps where step_handle = ?",
                (second["current_step"]["step_handle"],),
            ).fetchone()["flow_id"]
            second_question_id = conn.execute(
                "select question_id from flow_steps where flow_id = ? order by created_at limit 1",
                (second_flow_id,),
            ).fetchone()["question_id"]
            self.assertEqual("MATH-PILOT-V1-NL-04", second_question_id)
            self.assertNotEqual(first_step["question_id"], second_question_id)

    def test_group_review_keeps_planned_question_usage_eligible_after_cooldown(self) -> None:
        from learning_system import assessment_store, model_router

        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        with patch.dict(
            "os.environ",
            {
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            graph_version = runtime.graph.current_graph_version()
            with conn:
                history = runtime._create_daily_flow("2099-07-25", graph_version)
                now = db.now_iso()
                for index, question_id in enumerate(
                    ("MATH-PILOT-V1-NL-04", "MATH-PILOT-V1-NL-06"),
                    start=1,
                ):
                    question = db.get_question(conn, question_id)
                    review = conn.execute(
                        """
                        select id
                        from question_review_records
                        where question_id = ? and item_version = ?
                          and review_status = 'approved' and active_eligible = 1
                        order by reviewed_at desc, id desc
                        limit 1
                        """,
                        (question_id, question["item_version"]),
                    ).fetchone()
                    conn.execute(
                        """
                        insert into flow_steps(
                          id, flow_id, step_handle, position, step_type, status,
                          graph_version, node_id, question_bank_version,
                          question_id, question_item_version, review_record_id,
                          expected_evidence_json, prompt_package_json,
                          selection_reason_json, step_revision, created_at, updated_at
                        ) values (?, ?, ?, ?, 'question', 'completed', ?, ?, ?, ?, ?, ?,
                                  '{}', '{}', ?, 1, ?, ?)
                        """,
                        (
                            f"FS-group-history-{index}",
                            history["id"],
                            f"step-group-history-{index}",
                            index,
                            graph_version,
                            question["node_id"],
                            activation.PILOT_VERSION,
                            question_id,
                            question["item_version"],
                            review["id"],
                            db.json_dump({"reason": "diagnostic_cooldown_fixture"}),
                            now,
                            now,
                        ),
                    )
                conn.execute(
                    """
                    update daily_flows
                    set status = 'completed', current_step_id = null, updated_at = ?
                    where id = ?
                    """,
                    (now, history["id"]),
                )

            first = runtime.start_review_mode(client_day_key="2099-07-26")
            first_question_id = conn.execute(
                "select question_id from flow_steps where step_handle = ?",
                (first["current_step"]["step_handle"],),
            ).fetchone()["question_id"]
            self.assertEqual("MATH-PILOT-V1-NL-02", first_question_id)
            second = runtime.persist_child_response(
                daily_runtime.CurrentStepSubmission(
                    step_handle=first["current_step"]["step_handle"],
                    position=first["current_step"]["position"],
                    client_idempotency_key="pilot-group-purpose-first",
                    answer_text="每格是0.5，向右三格到0.5。",
                )
            )
            second_question_id = conn.execute(
                "select question_id from flow_steps where step_handle = ?",
                (second["current_step"]["step_handle"],),
            ).fetchone()["question_id"]
            self.assertEqual("MATH-PILOT-V1-NL-03", second_question_id)
            runtime.persist_child_response(
                daily_runtime.CurrentStepSubmission(
                    step_handle=second["current_step"]["step_handle"],
                    position=second["current_step"]["position"],
                    client_idempotency_key="pilot-group-purpose-second",
                    answer_text="B=0.75，C=0，所以A<C<B。",
                )
            )

            job = dict(
                conn.execute(
                    """
                    select *
                    from background_jobs
                    where job_type = 'group_answer_analysis'
                    order by created_at desc, id desc
                    limit 1
                    """
                ).fetchone()
            )
            payload = db.json_load(job["payload_json"], {})
            output_items = []
            for group_item in payload["group_items"]:
                contract = assessment_store.bound_active_contract_for_flow_step(
                    conn,
                    group_item["step_id"],
                )
                output_items.append(
                    {
                        "attempt_id": group_item["attempt_id"],
                        "criteria": [
                            {
                                "criterion_key": point["key"],
                                "status": "met",
                                "child_evidence": "答案体现了对应的数学关系和结论。",
                                "reason": "作答满足该得分点。",
                            }
                            for point in contract["score_points"]
                        ],
                        "answer_gap": "没有影响得分的数学差距。",
                        "improvement_direction": ["保持当前解题方式。"],
                        "expression_judgment": "表达能够体现正确数学意图。",
                        "teaching_explanation": "先确定数轴方向和距离，再得到位置关系。",
                        "confidence": 0.97,
                    }
                )
            structured = model_router.StructuredJSONResult(
                value={
                    "schema_version": daily_runtime.GROUP_ANSWER_REVIEW_SCHEMA_VERSION,
                    "items": output_items,
                    "confidence": 0.97,
                },
                mode="json_schema",
                raw_response={"fixture": "pilot-group-purpose"},
                endpoint="unit://structured-json",
            )
            route = model_router.ModelRoute(
                agent_key="answer_analysis_agent",
                task="answer_review",
                provider="openai",
                model="gpt-5.5",
                model_alias="gpt-5.5",
                base_url="https://unit.invalid/v1",
                api_key="test-only-key",
                timeout_seconds=120,
                model_params={"temperature": 0},
            )
            with patch.object(
                model_router,
                "answer_analysis_route",
                return_value=route,
            ), patch.object(
                model_router,
                "call_structured_json",
                return_value=structured,
            ) as model_call:
                result = runtime._handle_group_answer_analysis_job(job)

        self.assertEqual(1, model_call.call_count)
        self.assertEqual("succeeded", result["job_status"], result)
        self.assertEqual("mini_group_assessment_feedback", result["next_action"])
        planned_step = conn.execute(
            "select * from flow_steps where id = ?",
            (result["planned_step_id"],),
        ).fetchone()
        self.assertIsNotNone(planned_step)
        planned_usage = db.flow_step_usage_context(conn, planned_step["id"])
        planned_policy = db.active_question_usage_policy(
            conn,
            planned_step["question_id"],
        )
        planned_reason = db.json_load(planned_step["selection_reason_json"], {})
        self.assertIn(planned_usage["purpose"], planned_policy["allowed_purposes"])
        self.assertEqual("diagnostic", planned_usage["purpose"])
        self.assertEqual(
            planned_usage["raw"],
            planned_reason["requested_usage_context"],
            "the usage context selected before materialization must be recorded unchanged",
        )

    def test_diagnostic_sessions_skip_practice_only_items_before_selection(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        with patch.dict(
            "os.environ",
            {
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            selected_ids = []
            for index in range(4):
                state = runtime.start_review_mode(
                    client_day_key=f"2099-07-{26 + index:02d}"
                )
                self.assertEqual("current_step", state["child_state"])
                flow_id = conn.execute(
                    "select flow_id from flow_steps where step_handle = ?",
                    (state["current_step"]["step_handle"],),
                ).fetchone()["flow_id"]
                selected_ids.append(
                    conn.execute(
                        "select question_id from flow_steps where flow_id = ? order by position limit 1",
                        (flow_id,),
                    ).fetchone()["question_id"]
                )
                runtime.complete_summary(flow_id)

        self.assertEqual(
            [
                "MATH-PILOT-V1-NL-02",
                "MATH-PILOT-V1-NL-04",
                "MATH-PILOT-V1-NL-03",
                "MATH-PILOT-V1-NL-06",
            ],
            selected_ids,
        )
        self.assertNotIn("MATH-PILOT-V1-NL-05", selected_ids)

    def test_cross_session_cooldown_expires_and_reuses_oldest_formal_item(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        with patch.dict(
            "os.environ",
            {
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            old = runtime.start_review_mode(client_day_key="2000-01-01")
            old_flow_id = conn.execute(
                "select flow_id from flow_steps where step_handle = ?",
                (old["current_step"]["step_handle"],),
            ).fetchone()["flow_id"]
            runtime.complete_summary(old_flow_id)

            fresh = runtime.start_review_mode(client_day_key="2099-07-26")
            fresh_question_id = conn.execute(
                "select question_id from flow_steps where step_handle = ?",
                (fresh["current_step"]["step_handle"],),
            ).fetchone()["question_id"]

        self.assertEqual("MATH-PILOT-V1-NL-02", fresh_question_id)

    def test_formal_bank_identity_survives_supersede_and_rollback_statuses(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)

        self.assertTrue(
            db.is_ledger_managed_question_bank_version(conn, activation.PILOT_VERSION)
        )
        for status in ("superseded", "rolled_back"):
            conn.execute(
                "update question_bank_version_ledger set status = ? where question_bank_version = ?",
                (status, activation.PILOT_VERSION),
            )
            self.assertTrue(
                db.is_ledger_managed_question_bank_version(
                    conn,
                    activation.PILOT_VERSION,
                )
            )

    def test_formal_bank_relaxes_only_cross_session_cooldown_when_node_is_saturated(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        with patch.dict(
            "os.environ",
            {
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            graph_version = runtime.graph.current_graph_version()
            with conn:
                flow = runtime._create_daily_flow("2099-07-26", graph_version)
            available = daily_runtime.question_bank.QuestionBankService.candidate_packet_for_node(
                conn,
                node_id="M-G7-NUMBER-LINE",
                graph_version=graph_version,
                flow_id=flow["id"],
                flow_revision=int(flow["flow_revision"]),
                limit=8,
                exclusions={},
                question_bank_version=activation.PILOT_VERSION,
                selection_intent="initial_review",
                required_purpose="diagnostic",
            )
            saturated = {
                **available,
                "candidates": [],
                "candidate_count": 0,
                "filter_summary": {
                    **dict(available.get("filter_summary") or {}),
                    "excluded_cooldown": 1,
                },
            }
            with patch.object(
                daily_runtime.question_bank.QuestionBankService,
                "candidate_packet_for_node",
                side_effect=[saturated, available],
            ), patch.object(
                db,
                "find_question_for_node",
                side_effect=AssertionError("formal bank must not enter legacy fallback"),
            ):
                selected = runtime._select_question_for_node(
                    "M-G7-NUMBER-LINE",
                    graph_version=graph_version,
                    flow_id=flow["id"],
                    flow_revision=int(flow["flow_revision"]),
                    reason={"reason": "cooldown_saturation_test"},
                    selection_intent="initial_review",
                    required_purpose="diagnostic",
                )

        self.assertEqual("MATH-PILOT-V1-NL-02", selected["question"]["id"])
        self.assertTrue(
            selected["selection_reason"]["cross_session_cooldown_relaxed"]
        )

    def test_formal_bank_new_knowledge_sequence_stays_live_without_same_flow_instance_reuse(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        helper = learning_system_tests.LearningSystemTest(methodName="runTest")
        helper.conn = conn
        with patch.dict(
            "os.environ",
            {
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            conn.execute(
                """
                insert or replace into learner_node_status(
                  node_id, status_code, latest_score, can_explain,
                  evidence_attempt_ids_json, status_reason, updated_at
                ) values ('M-PRE-NUMBER-SENSE', 'A', 1, 1, '[]', ?, ?)
                """,
                ("formal pilot prerequisite fixture", db.now_iso()),
            )
            conn.commit()
            historical_flow_id = self._seed_recent_node_history(
                conn,
                runtime,
                node_id="M-PRE-INTEGER-OPS",
                local_date="2099-07-22",
            )
            historical_question_ids = {
                row["question_id"]
                for row in conn.execute(
                    "select question_id from flow_steps where flow_id = ?",
                    (historical_flow_id,),
                ).fetchall()
            }

            runtime, flow_id, worked = helper._start_v5_recorded_new_knowledge_flow(
                "2099-07-23"
            )
            worked_row = conn.execute(
                "select * from flow_steps where step_handle = ?",
                (worked["current_step"]["step_handle"],),
            ).fetchone()
            self.assertEqual("worked_example", worked_row["step_type"])
            self.assertIn(worked_row["question_id"], historical_question_ids)

            with patch.object(
                runtime,
                "_select_question_for_node",
                wraps=runtime._select_question_for_node,
            ) as micro_selector, patch.object(
                runtime,
                "_explicit_question_usage_context",
                wraps=runtime._explicit_question_usage_context,
            ) as usage_context_builder:
                micro = runtime.continue_current_step(
                    step_handle=worked["current_step"]["step_handle"],
                    position=worked["current_step"]["position"],
                )
            requested_usage = usage_context_builder.call_args.kwargs[
                "requested_usage"
            ]
            self.assertEqual(
                requested_usage["purpose"],
                micro_selector.call_args.kwargs["required_purpose"],
                "the micro-check purpose must be fixed before candidate selection",
            )
            micro_row = conn.execute(
                "select * from flow_steps where step_handle = ?",
                (micro["current_step"]["step_handle"],),
            ).fetchone()
            self.assertEqual("micro_check", micro_row["step_type"])
            self.assertTrue(
                db.json_load(micro_row["selection_reason_json"], {}).get(
                    "cross_session_cooldown_relaxed"
                )
            )
            worked_usage = db.flow_step_usage_context(conn, worked_row["id"])
            micro_usage = db.flow_step_usage_context(conn, micro_row["id"])
            micro_reason = db.json_load(micro_row["selection_reason_json"], {})
            self.assertEqual("teaching", worked_usage["purpose"])
            self.assertEqual("worked_example", worked_usage["purpose_role"])
            self.assertEqual("practice", micro_usage["purpose"])
            self.assertEqual(
                requested_usage,
                {
                    key: micro_usage["raw"][key]
                    for key in requested_usage
                },
                "selection and SQLite usage context must come from one request",
            )
            self.assertEqual(
                micro_usage["raw"],
                micro_reason["requested_usage_context"],
                "materialization must persist the exact preselected usage context",
            )
            runtime.persist_child_response(daily_runtime.CurrentStepSubmission(
                step_handle=micro["current_step"]["step_handle"],
                position=micro["current_step"]["position"],
                client_idempotency_key="pilot-new-micro",
                answer_text="我写出核心关系、计算步骤和检查。",
            ))
            micro_attempt = db.get_attempt(
                conn,
                conn.execute(
                    "select id from attempts where client_idempotency_key = 'pilot-new-micro'"
                ).fetchone()["id"],
            )
            standard_result = helper._drain_v5_attempt_dag(
                runtime,
                micro_attempt["id"],
                answer_review=helper._v5_recorded_correct_review(micro_attempt),
                planner_action="same_structure_retest",
            )
            standard_feedback = standard_result["projection"]
            standard = runtime.continue_current_step(
                step_handle=standard_feedback["current_step"]["step_handle"],
                position=standard_feedback["current_step"]["position"],
            )
            standard_row = conn.execute(
                "select * from flow_steps where step_handle = ?",
                (standard["current_step"]["step_handle"],),
            ).fetchone()
            self.assertEqual("standard_check", standard_row["step_type"])

            runtime.persist_child_response(daily_runtime.CurrentStepSubmission(
                step_handle=standard["current_step"]["step_handle"],
                position=standard["current_step"]["position"],
                client_idempotency_key="pilot-new-standard",
                answer_text="我独立完成标准题，并检验结果。",
            ))
            standard_attempt = db.get_attempt(
                conn,
                conn.execute(
                    "select id from attempts where client_idempotency_key = 'pilot-new-standard'"
                ).fetchone()["id"],
            )
            variant_result = helper._drain_v5_attempt_dag(
                runtime,
                standard_attempt["id"],
                answer_review=helper._v5_recorded_correct_review(standard_attempt),
                planner_action="near_transfer_retest",
            )
            variant_feedback = variant_result["projection"]
            variant = runtime.continue_current_step(
                step_handle=variant_feedback["current_step"]["step_handle"],
                position=variant_feedback["current_step"]["position"],
            )
            variant_row = conn.execute(
                "select * from flow_steps where step_handle = ?",
                (variant["current_step"]["step_handle"],),
            ).fetchone()
            self.assertEqual("variant_check", variant_row["step_type"])

            runtime.persist_child_response(daily_runtime.CurrentStepSubmission(
                step_handle=variant["current_step"]["step_handle"],
                position=variant["current_step"]["position"],
                client_idempotency_key="pilot-new-variant-gap",
                answer_text="我得到一个结果，但说不清条件变化后为什么仍能这样做。",
            ))
            variant_attempt = db.get_attempt(
                conn,
                conn.execute(
                    "select id from attempts where client_idempotency_key = 'pilot-new-variant-gap'"
                ).fetchone()["id"],
            )
            gap_review = {
                "result": "wrong",
                "score_points": 0,
                "max_points": 2,
                "error_tags": ["concept_confusion"],
                "explanation_score": 0,
                "blocking_evidence": False,
                "confidence": 0.91,
                "parent_note": "近迁移模型解释缺失，进入针对性修复。",
                "analysis": learning_system_tests.weak_reasoning_answer_analysis(
                    optimal_answer=db.get_question(
                        conn, variant_attempt["question_id"]
                    )["expected_answer"],
                    process_gap="条件改变后，核心关系为什么仍成立还没有说明。",
                ),
                "ai_review": {
                    "status": "graded",
                    "provider": "recorded_model",
                    "confidence": 0.91,
                },
            }
            repair_result = helper._drain_v5_attempt_dag(
                runtime,
                variant_attempt["id"],
                answer_review=gap_review,
                planner_action="micro_teach",
            )
            repair_feedback = repair_result["projection"]
            repair = runtime.continue_current_step(
                step_handle=repair_feedback["current_step"]["step_handle"],
                position=repair_feedback["current_step"]["position"],
            )
            repair_row = conn.execute(
                "select * from flow_steps where step_handle = ?",
                (repair["current_step"]["step_handle"],),
            ).fetchone()
            self.assertEqual("teaching_repair", repair_row["step_type"])
            self.assertEqual(
                "repair",
                db.json_load(repair_row["selection_reason_json"], {}).get(
                    "new_knowledge_phase"
                ),
            )
            variant_assessment = conn.execute(
                """
                select score_out_of_10, question_passed
                from attempt_assessments
                where attempt_id = ? and status = 'accepted'
                order by assessment_version desc
                limit 1
                """,
                (variant_attempt["id"],),
            ).fetchone()
            self.assertIsNotNone(variant_assessment)
            self.assertEqual(0, variant_assessment["question_passed"])
            self.assertLess(variant_assessment["score_out_of_10"], 8)
            summary = runtime.continue_current_step(
                step_handle=repair["current_step"]["step_handle"],
                position=repair["current_step"]["position"],
                stuck=True,
            )
            self.assertEqual("summary", summary["child_state"])
            completed_flow = conn.execute(
                "select status, summary_id from daily_flows where id = ?",
                (flow_id,),
            ).fetchone()
            self.assertEqual("completed", completed_flow["status"])
            self.assertTrue(completed_flow["summary_id"])

        phase_rows = conn.execute(
            """
            select s.step_type, q.*
            from flow_steps s
            join question_items q on q.id = s.question_id
            where s.flow_id = ?
              and s.node_id = 'M-PRE-INTEGER-OPS'
              and s.step_type in ('worked_example','micro_check','standard_check','variant_check')
            order by s.position
            """,
            (flow_id,),
        ).fetchall()
        self.assertEqual(
            ["worked_example", "micro_check", "standard_check", "variant_check"],
            [row["step_type"] for row in phase_rows],
        )
        phase_instances = [
            db.row_to_question(row)["problem_instance_id"] for row in phase_rows
        ]
        self.assertEqual(len(phase_instances), len(set(phase_instances)))

        answerable_rows = conn.execute(
            """
            select q.*
            from flow_steps s
            join question_items q on q.id = s.question_id
            where s.flow_id = ?
              and s.step_type in ('question','micro_check','standard_check','variant_check')
              and s.superseded_by_step_id is null
            order by s.position
            """,
            (flow_id,),
        ).fetchall()
        answerable_instances = [
            db.row_to_question(row)["problem_instance_id"] for row in answerable_rows
        ]
        self.assertEqual(len(answerable_instances), len(set(answerable_instances)))
        planner_cooldown_flags = [
            bool(db.json_load(row["candidate_filter_summary_json"], {}).get(
                "cross_session_cooldown_relaxed"
            ))
            for row in conn.execute(
                """
                select candidate_filter_summary_json
                from next_step_decisions
                where flow_id = ? and action in ('same_structure_retest','near_transfer_retest')
                order by created_at
                """,
                (flow_id,),
            ).fetchall()
        ]
        self.assertEqual([True, True], planner_cooldown_flags)

    def test_changed_manifest_identity_is_rejected_without_mutation(self) -> None:
        activation.activate(self.db_path)
        changed = self._manifest()
        changed["items"][0]["prompt"] += " 请复核。"
        changed_path = self._write_manifest(changed, "changed.json")
        conn = db.connect(self.db_path)
        before = conn.execute(
            "select manifest_sha256, activated_at, updated_at from question_bank_version_ledger"
        ).fetchone()
        before_questions = conn.execute("select count(*) from question_items").fetchone()[0]
        conn.close()

        with self.assertRaisesRegex(ValueError, "ledger identity mismatch"):
            activation.activate(self.db_path, manifest_path=changed_path)

        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        after = conn.execute(
            "select manifest_sha256, activated_at, updated_at from question_bank_version_ledger"
        ).fetchone()
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(
            before_questions,
            conn.execute("select count(*) from question_items").fetchone()[0],
        )

    def test_existing_legacy_bank_is_rejected_and_not_superseded(self) -> None:
        conn = db.connect(self.db_path)
        db.init_schema(conn)
        db.seed_from_assets(conn, PROJECT_ROOT)
        now = db.now_iso()
        conn.execute(
            """
            insert into question_bank_version_ledger(
              id, question_bank_version, graph_version, manifest_id,
              manifest_sha256, node_count, item_count, status,
              reason, created_at, updated_at, activated_at
            ) values ('QBL-legacy', '2026-07-12.bank.v12', 'legacy-graph',
                      'legacy-1120', 'legacy-digest', 56, 1120, 'active',
                      'legacy fixture', ?, ?, ?)
            """,
            (now, now, now),
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(ValueError, "contains another question bank"):
            activation.activate(self.db_path)

        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        ledger = conn.execute(
            "select question_bank_version, status from question_bank_version_ledger"
        ).fetchone()
        self.assertEqual(("2026-07-12.bank.v12", "active"), tuple(ledger))
        self.assertEqual(0, conn.execute("select count(*) from question_items").fetchone()[0])

    def test_cli_requires_isolated_db_and_returns_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts/activate_three_node_pilot.py"),
                "--db",
                str(self.db_path),
                "--json",
            ],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual("activated", payload["status"])
        self.assertEqual(17, payload["item_count"])
        self.assertEqual(18, payload["manifest_item_count"])


if __name__ == "__main__":
    unittest.main()
