from __future__ import annotations

import json
import http.client
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from unittest.mock import patch

from learning_system import assessment_policy, assessment_store, child_prompt, daily_runtime, db, knowledge_map, planner, question_bank, question_usage, semantic_agents, server
from scripts import activate_knowledge_views as view_activation
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

    def _activate_predecessor_bank(self, db_path: Path | None = None) -> dict:
        target_path = db_path or self.db_path
        predecessor_manifest = (
            PROJECT_ROOT
            / "data/question_banks/math/math_three_node_pilot_2026-07-28.v2.json"
        )
        raw_bytes = predecessor_manifest.read_bytes()
        manifest = json.loads(raw_bytes.decode("utf-8"))
        with patch.multiple(
            activation,
            PILOT_VERSION=activation.PILOT_PREVIOUS_VERSION,
            PILOT_MANIFEST_ID="math_three_node_pilot_2026_07_28_v2",
            DEFAULT_MANIFEST=predecessor_manifest,
        ):
            graph_nodes, _graph_sha = activation._load_graph(PROJECT_ROOT)
            items = [
                activation._build_item(
                    raw,
                    manifest=manifest,
                    manifest_sha256=activation.hashlib.sha256(raw_bytes).hexdigest(),
                    graph_nodes=graph_nodes,
                )
                for raw in manifest["items"]
            ]
            conn = db.connect(target_path)
            try:
                db.init_schema(conn)
                db.seed_from_assets(conn, PROJECT_ROOT)
                graph_ref = db.json_load(
                    conn.execute(
                        "select value from system_meta where key = 'graph_ref'"
                    ).fetchone()["value"],
                    {},
                )
                graph_version = graph_ref["lineage"]
                for item in items:
                    question_bank.apply_question_lineage(
                        item,
                        graph_version=graph_version,
                        question_bank_version=activation.PILOT_PREVIOUS_VERSION,
                    )
                with conn:
                    staged = activation._stage_items(
                        conn,
                        manifest=manifest,
                        items=items,
                        manifest_sha256=activation.hashlib.sha256(raw_bytes).hexdigest(),
                        graph_version=graph_version,
                    )
                    ledger = db.activate_question_bank_version(
                        conn,
                        question_bank_version=activation.PILOT_PREVIOUS_VERSION,
                        expected_current_version=None,
                        reason="authoritative v2 test fixture",
                        commit=False,
                    )
                    activation._write_contracts_and_receipt(
                        conn,
                        items=items,
                        ledger=ledger,
                        graph_version=graph_version,
                    )
                return {
                    "status": "activated",
                    "ledger_id": staged["id"],
                    "question_bank_version": activation.PILOT_PREVIOUS_VERSION,
                }
            finally:
                conn.close()

    def _learning_evidence_digests(self, conn) -> dict[str, str]:
        tables = (
            "learning_sessions",
            "attempts",
            "attempt_assessments",
            "evidence_validations",
            "mastery_decisions",
        )
        return {
            table: activation.canonical_sha256(
                [dict(row) for row in conn.execute(f"select * from {table} order by id")]
            )
            for table in tables
        }

    def _seed_authoritative_learning_evidence(self, conn) -> None:
        ledger = conn.execute(
            "select * from question_bank_version_ledger where status = 'active'"
        ).fetchone()
        question = conn.execute(
            "select * from question_items where item_version = ? order by id limit 1",
            (activation.PILOT_PREVIOUS_VERSION,),
        ).fetchone()
        contract = conn.execute(
            "select * from answer_contracts where question_id = ? and status = 'active'",
            (question["id"],),
        ).fetchone()
        session_id = db.create_session(
            conn,
            "v2 evidence preservation fixture",
            mode="daily_flow_v3",
            status="completed",
            commit=False,
        )
        attempt_id = db.record_attempt(
            conn,
            session_id=session_id,
            question_id=question["id"],
            node_id=question["node_id"],
            result="correct",
            score_points=2,
            max_points=2,
            error_tags=[],
            answer_raw="fixture answer",
            parent_note="",
            question_bank_version=activation.PILOT_PREVIOUS_VERSION,
            commit=False,
        )
        now = db.now_iso()
        conn.execute(
            """
            insert into attempt_assessments(
              id, attempt_id, attempt_version, assessment_version,
              assessment_digest_sha256, assessment_input_digest_sha256,
              question_id, question_item_version, answer_contract_id,
              answer_contract_version, answer_contract_digest_sha256,
              criterion_judgments_json, score_out_of_10, question_passed,
              reference_answer_json, improvement_direction_json,
              trust_label, provider_mode, evidence_gate_version, status,
              accepted_at, created_at, updated_at
            ) values (
              'AA-preserved-v2', ?, 1, 1, 'assessment-digest-v2',
              'assessment-input-v2', ?, ?, ?, ?, ?, '[]', 10, 1,
              '{}', '[]', 'trusted', 'fixture', 'v5.1', 'accepted', ?, ?, ?
            )
            """,
            (
                attempt_id,
                question["id"],
                activation.PILOT_PREVIOUS_VERSION,
                contract["id"],
                contract["contract_version"],
                contract["contract_digest_sha256"],
                now,
                now,
                now,
            ),
        )
        conn.execute(
            """
            insert into evidence_validations(
              id, attempt_id, attempt_version, analysis_version,
              graph_version, node_id, question_id, question_bank_version,
              gate_version, gate_status, failed_fields_json,
              predicate_result_json, provider_mode, created_at, updated_at,
              assessment_id, assessment_version, assessment_digest_sha256
            ) values (
              'EV-preserved-v2', ?, 1, 1, ?, ?, ?, ?, 'v5.1', 'usable',
              '[]', '{}', 'fixture', ?, ?, 'AA-preserved-v2', 1,
              'assessment-digest-v2'
            )
            """,
            (
                attempt_id,
                ledger["graph_version"],
                question["node_id"],
                question["id"],
                activation.PILOT_PREVIOUS_VERSION,
                now,
                now,
            ),
        )
        conn.execute(
            """
            insert into mastery_decisions(
              id, session_id, node_id, decision, closure_result,
              evidence_attempt_ids_json, applied, reason,
              decision_payload_json, graph_version, question_bank_version,
              source_attempt_ids_json, source_evidence_validation_ids_json,
              decision_version, new_status_code, dimension_scores_json,
              source_evidence_validation_hash, created_at
            ) values (
              'MD-preserved-v2', ?, ?, 'keep', 'continue', ?, 1,
              'fixture', '{}', ?, ?, ?, '["EV-preserved-v2"]', 1,
              'B', '{}', 'validation-hash-v2', ?
            )
            """,
            (
                session_id,
                question["node_id"],
                db.json_dump([attempt_id]),
                ledger["graph_version"],
                activation.PILOT_PREVIOUS_VERSION,
                db.json_dump([attempt_id]),
                now,
            ),
        )
        conn.commit()

    def _create_nl10_teaching_repair(
        self,
        *,
        criterion_statuses: dict[str, str],
    ) -> tuple[object, daily_runtime.DailyLearningRuntime, dict, dict, dict]:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
        state = runtime.start_review_mode(client_day_key="2099-07-28")
        current_step = conn.execute(
            "select * from flow_steps where step_handle = ?",
            (state["current_step"]["step_handle"],),
        ).fetchone()
        flow = dict(runtime._flow_by_id(current_step["flow_id"]))
        conn.execute(
            "update flow_steps set status = 'completed', updated_at = ? where id = ?",
            (db.now_iso(), current_step["id"]),
        )
        conn.execute(
            "update daily_flows set current_step_id = null, updated_at = ? where id = ?",
            (db.now_iso(), flow["id"]),
        )
        question = db.get_question(conn, "MATH-PILOT-V3-NL-10")
        review = conn.execute(
            """
            select id from question_review_records
            where question_id = ? and item_version = ?
              and review_status = 'approved' and active_eligible = 1
            order by reviewed_at desc, id desc
            limit 1
            """,
            (question["id"], question["item_version"]),
        ).fetchone()
        contract = assessment_store.active_contract_for_question(
            conn,
            question["id"],
            question["item_version"],
        )
        self.assertIsNotNone(contract)
        source_step_id = runtime._create_question_step(
            flow_id=flow["id"],
            position=int(
                conn.execute(
                    "select count(*) from flow_steps where flow_id = ?",
                    (flow["id"],),
                ).fetchone()[0]
            )
            + 1,
            graph_version=flow["graph_version"],
            question=question,
            review_record_id=review["id"],
            selection_reason={
                "reason": "nl10_support_routing_fixture",
                "requested_usage_context": runtime._explicit_question_usage_context(
                    question_id=question["id"],
                    requested_usage={
                        "purpose": "diagnostic",
                        "purpose_role": "confirmation_transfer",
                    },
                    block_id="DIAG-NL10-SUPPORT-ROUTING",
                ),
            },
            candidate_packet={},
            answer_contract=contract,
        )
        contract = {**contract, "node_id": question["node_id"]}
        attempt_id = db.record_attempt(
            conn,
            session_id=flow["legacy_session_id"],
            question_id=question["id"],
            node_id=question["node_id"],
            result="submitted",
            score_points=0,
            max_points=2,
            error_tags=[],
            answer_raw="结构化评分测试答案",
            parent_note="",
            grading_status="pending_review",
            question_bank_version=activation.PILOT_VERSION,
            commit=False,
        )
        conn.execute(
            """
            update attempts
            set flow_step_id = ?, graph_version = ?
            where id = ?
            """,
            (source_step_id, flow["graph_version"], attempt_id),
        )
        pending = assessment_store.record_pending_assessment(
            conn,
            attempt_id=attempt_id,
            attempt_version=1,
            contract=contract,
            assessment_input_digest_sha256=f"nl10-support-{attempt_id}",
            commit=False,
        )
        judgments = [
            {
                "criterion_key": point["source_target_key"],
                "status": criterion_statuses.get(
                    point["source_target_key"],
                    "met",
                ),
                "child_evidence": "结构化测试证据",
                "reason": "按 canonical criterion key 判断",
            }
            for point in contract["score_points"]
        ]
        calculated = assessment_policy.calculate_assessment(
            assessment_store.policy_contract_for_assessment(contract),
            judgments,
        )
        accepted = assessment_store.accept_assessment(
            conn,
            assessment_id=pending["id"],
            criterion_judgments=judgments,
            score_out_of_10=calculated["score_out_of_10"],
            question_passed=calculated["question_passed"],
            feedback={
                "reference_answer": question["expected_answer"],
                "answer_gap": "按结构化评分点定位缺口。",
                "improvement_direction": ["先修复对应评分点。"],
                "expression_judgment": "按数学证据判断。",
                "teaching_explanation": "用对应的结构化模型修复。",
            },
            assessment_digest_sha256=f"accepted-nl10-support-{attempt_id}",
            answer_analysis_agent_run_id=None,
            provider_mode="deterministic_test",
            commit=False,
        )
        source_attempt = db.get_attempt(conn, attempt_id)
        repair_step_id = runtime._create_teaching_repair_step(
            flow=flow,
            source_attempt=source_attempt,
            source_step_id=source_step_id,
            source_next_step_decision_id="",
            position=int(
                conn.execute(
                    "select count(*) from flow_steps where flow_id = ?",
                    (flow["id"],),
                ).fetchone()[0]
            )
            + 1,
            initial_status="planned",
        )
        repair_step = dict(
            conn.execute(
                "select * from flow_steps where id = ?",
                (repair_step_id,),
            ).fetchone()
        )
        return conn, runtime, flow, source_attempt, {
            "assessment": accepted,
            "step": repair_step,
        }

    def _complete_selected_flow(self, conn, runtime, flow_id: str) -> dict:
        conn.execute(
            "update flow_steps set status = 'completed' where flow_id = ? and status in ('selected','displayed','analyzing')",
            (flow_id,),
        )
        conn.execute(
            "update daily_flows set status = 'ready_for_new_knowledge', current_step_id = null where id = ?",
            (flow_id,),
        )
        conn.commit()
        return runtime.complete_summary(flow_id)

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

    def _install_formal_target_intent_flow(
        self,
        conn,
        *,
        used_integer_question_ids: tuple[str, ...],
    ) -> tuple[daily_runtime.DailyLearningRuntime, dict, dict]:
        runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
        graph_version = runtime.graph.current_graph_version()
        authority = knowledge_map.KnowledgeMapService(
            conn,
            project_root=PROJECT_ROOT,
        )._runtime_authority()
        assets = {
            str(asset["question_id"]): asset
            for node_assets in authority["assessment"]["assets_by_node"].values()
            for asset in node_assets
        }
        with conn:
            flow = runtime._create_daily_flow(date.today().isoformat(), graph_version)
            position = 1
            for question_id in used_integer_question_ids:
                asset = assets[question_id]
                usage = runtime._explicit_question_usage_context(
                    question_id=question_id,
                    requested_usage={
                        "purpose": "diagnostic",
                        "purpose_role": "entry_probe",
                    },
                    block_id=f"TARGET-HISTORY-{position}",
                )
                step_id = runtime._create_question_step(
                    flow_id=flow["id"],
                    position=position,
                    graph_version=graph_version,
                    question=asset["question"],
                    review_record_id=asset["review_record_id"],
                    selection_reason={
                        "reason": "formal_target_history_fixture",
                        "requested_usage_context": usage,
                    },
                    step_type="question",
                    initial_status="selected",
                    answer_contract=asset["contract"],
                )
                conn.execute(
                    "update flow_steps set status = 'completed' where id = ?",
                    (step_id,),
                )
                position += 1
            current_asset = assets["MATH-PILOT-V3-EQ-02"]
            current_usage = runtime._explicit_question_usage_context(
                question_id=current_asset["question_id"],
                requested_usage={
                    "purpose": "diagnostic",
                    "purpose_role": "entry_probe",
                },
                block_id="TARGET-CURRENT-EQ-02",
            )
            current_step_id = runtime._create_question_step(
                flow_id=flow["id"],
                position=position,
                graph_version=graph_version,
                question=current_asset["question"],
                review_record_id=current_asset["review_record_id"],
                selection_reason={
                    "reason": "formal_target_current_fixture",
                    "requested_usage_context": current_usage,
                },
                step_type="question",
                initial_status="displayed",
                answer_contract=current_asset["contract"],
            )
            conn.execute(
                """
                update daily_flows
                set mode = 'review_old_knowledge', status = 'reviewing',
                    current_step_id = ?, updated_at = ?
                where id = ?
                """,
                (current_step_id, db.now_iso(), flow["id"]),
            )
        return runtime, dict(flow), dict(
            conn.execute(
                "select * from flow_steps where id = ?",
                (current_step_id,),
            ).fetchone()
        )

    def test_activates_exact_reviewed_three_node_bank_and_contracts(self) -> None:
        result = activation.activate(self.db_path)

        self.assertEqual("activated", result["status"])
        self.assertEqual(23, result["item_count"])
        self.assertEqual(24, result["manifest_item_count"])
        self.assertEqual(3, result["node_count"])
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)

        ledgers = conn.execute(
            "select * from question_bank_version_ledger order by id"
        ).fetchall()
        self.assertEqual(1, len(ledgers))
        self.assertEqual(activation.PILOT_VERSION, ledgers[0]["question_bank_version"])
        self.assertEqual("active", ledgers[0]["status"])
        self.assertEqual(23, ledgers[0]["item_count"])
        self.assertEqual(3, ledgers[0]["node_count"])

        rows = conn.execute(
            "select * from question_items order by node_id, id"
        ).fetchall()
        self.assertEqual(23, len(rows))
        self.assertEqual(
            {
                "M-PRE-INTEGER-OPS": 6,
                "M-G7-NUMBER-LINE": 11,
                "M-G7-EQ-SOLVE": 6,
            },
            dict(
                conn.execute(
                    "select node_id, count(*) from question_items group by node_id"
                ).fetchall()
            ),
        )
        questions = [db.row_to_question(row) for row in rows]
        self.assertEqual(23, len({question["problem_instance_id"] for question in questions}))
        self.assertNotIn("MATH-PILOT-V3-NL-01", {question["id"] for question in questions})
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
        self.assertEqual(23, len(policies))
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
        self.assertEqual(23, len(reviews))
        self.assertTrue(all(row["review_status"] == "approved" for row in reviews))
        self.assertTrue(all(row["active_eligible"] == 1 for row in reviews))
        self.assertTrue(all(row["agent_key"] == "question_reviewer_agent" for row in reviews))
        self.assertTrue(all(row["phase"] == "question_quality_review" for row in reviews))
        self.assertTrue(all(row["run_status"] == "accepted" for row in reviews))

        contracts = conn.execute(
            "select * from answer_contracts where status = 'active' order by question_id"
        ).fetchall()
        self.assertEqual(23, len(contracts))
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
        self.assertEqual(23, receipt["active_contract_count"])
        self.assertEqual(activation.PILOT_VERSION, receipt["question_bank_version"])

    def test_support_usage_is_teaching_only_and_never_mastery_eligible(self) -> None:
        manifest = self._manifest()
        support_id = "MATH-PILOT-V3-NL-06"
        for item in manifest["items"]:
            if item["id"] == support_id:
                item["usage"] = "support"
                break
        manifest_path = self._write_manifest(manifest, "pilot-support.json")

        activation.activate(self.db_path, manifest_path=manifest_path)

        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        policy = db.active_question_usage_policy(
            conn,
            support_id,
            item_version=activation.PILOT_VERSION,
        )
        self.assertEqual(["teaching"], policy["allowed_purposes"])
        self.assertTrue(policy["support_only"])
        self.assertEqual(
            {
                "node_state_in": ["weak", "due", "mastered"],
                "requires_prior_item_ids": ["MATH-PILOT-V3-NL-10"],
                "prefer_after_evidence_keys": ["midpoint_reverse_location_gap"],
            },
            policy["selection_preconditions"],
        )
        self.assertEqual(
            {
                "schema_version": "2026-07-28.support-routing.v1",
                "routes": [
                    {
                        "evidence_key": "midpoint_reverse_location_gap",
                        "source_item_id": "MATH-PILOT-V3-NL-10",
                        "criterion_key": "unique_endpoints_with_midpoint",
                        "trigger_statuses": ["not_met", "contradicted"],
                    }
                ],
            },
            policy["support_routing"],
        )
        teaching_context = question_usage.context_for_step(
            policy,
            purpose="teaching",
            purpose_role=policy["teaching_roles"][0],
        )
        self.assertFalse(teaching_context["mastery_update_eligible"])
        graph_version = conn.execute(
            "select graph_version from question_bank_version_ledger where status = 'active'"
        ).fetchone()[0]
        sibling_ids = [
            row["id"]
            for row in conn.execute(
                "select id from question_items where node_id = 'M-G7-NUMBER-LINE' and id <> ?",
                (support_id,),
            )
        ]
        for purpose in ("diagnostic", "practice"):
            packet = question_bank.QuestionBankService.candidate_packet_for_node(
                conn,
                node_id="M-G7-NUMBER-LINE",
                graph_version=graph_version,
                flow_id=f"FLOW-support-{purpose}",
                exclusions={"recent_question_ids": sibling_ids},
                question_bank_version=activation.PILOT_VERSION,
                required_purpose=purpose,
            )
            self.assertNotIn(
                support_id,
                {candidate["question_id"] for candidate in packet["candidates"]},
            )
        planner_packet = question_bank.QuestionBankService.candidate_packet_for_node(
            conn,
            node_id="M-G7-NUMBER-LINE",
            graph_version=graph_version,
            flow_id="FLOW-support-production-planner",
            exclusions={"recent_question_ids": sibling_ids},
            question_bank_version=activation.PILOT_VERSION,
            required_purpose="diagnostic",
            selection_intent="stable_ready",
            learner_status="A",
            prerequisite_ready=True,
        )
        self.assertNotIn(
            support_id,
            {candidate["question_id"] for candidate in planner_packet["candidates"]},
            "support-only assets must not enter a diagnostic planner packet",
        )
        diagnostic_policy = db.active_question_usage_policy(
            conn,
            "MATH-PILOT-V3-NL-02",
            item_version=activation.PILOT_VERSION,
        )
        practice_policy = db.active_question_usage_policy(
            conn,
            "MATH-PILOT-V3-NL-05",
            item_version=activation.PILOT_VERSION,
        )
        self.assertEqual(
            ["teaching", "diagnostic", "practice"],
            diagnostic_policy["allowed_purposes"],
        )
        self.assertEqual(
            ["teaching", "practice"],
            practice_policy["allowed_purposes"],
        )
        self.assertFalse(diagnostic_policy["support_only"])
        self.assertFalse(practice_policy["support_only"])

    def test_nl10_midpoint_gap_routes_real_teaching_repair_to_support_asset(self) -> None:
        conn, _runtime, _flow, source_attempt, result = self._create_nl10_teaching_repair(
            criterion_statuses={"unique_endpoints_with_midpoint": "not_met"},
        )

        repair_step = result["step"]
        self.assertEqual("teaching_repair", repair_step["step_type"])
        self.assertEqual("MATH-PILOT-V3-NL-06", repair_step["question_id"])
        repair_prompt = db.json_load(repair_step["prompt_package_json"], {})[
            "prompt"
        ]
        self.assertIn("中点表示-1", repair_prompt)
        self.assertIn("A=-4", repair_prompt)
        selection_reason = db.json_load(repair_step["selection_reason_json"], {})
        self.assertEqual(source_attempt["id"], selection_reason["source_attempt_id"])
        self.assertEqual(
            "midpoint_reverse_location_gap",
            selection_reason["support_evidence_key"],
        )
        usage = db.flow_step_usage_context(conn, repair_step["id"])
        self.assertEqual("teaching", usage["purpose"])
        self.assertEqual("targeted_repair", usage["purpose_role"])
        self.assertFalse(usage["mastery_update_eligible"])
        self.assertEqual(
            0,
            conn.execute(
                "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
                (f'%"{source_attempt["id"]}"%',),
            ).fetchone()[0],
        )

    def test_support_routing_contract_mismatch_fails_before_activation(self) -> None:
        manifest = self._manifest()
        for item in manifest["items"]:
            if item["id"] == "MATH-PILOT-V3-NL-06":
                item["selection_preconditions"]["prefer_after_evidence_keys"] = [
                    "unrelated_gap"
                ]
                break
        manifest_path = self._write_manifest(
            manifest,
            "pilot-support-routing-mismatch.json",
        )

        with self.assertRaisesRegex(
            ValueError,
            "support_routing evidence key is not permitted",
        ):
            activation.activate(self.db_path, manifest_path=manifest_path)
        self.assertFalse(self.db_path.exists())

    def test_support_route_source_criterion_must_exist_before_database_creation(self) -> None:
        manifest = self._manifest()
        for item in manifest["items"]:
            if item["id"] != "MATH-PILOT-V3-NL-10":
                continue
            target = next(
                point
                for point in item["scoring_targets"]
                if point["key"] == "unique_endpoints_with_midpoint"
            )
            target["key"] = "renamed_midpoint_criterion"
            break
        manifest_path = self._write_manifest(
            manifest,
            "pilot-support-source-criterion-renamed.json",
        )

        with self.assertRaisesRegex(
            ValueError,
            "support route criterion does not exist",
        ):
            activation.activate(self.db_path, manifest_path=manifest_path)
        self.assertFalse(self.db_path.exists())

    def test_support_route_source_item_must_exist_before_database_creation(self) -> None:
        manifest = self._manifest()
        missing_source_id = "MATH-PILOT-V3-NL-MISSING"
        for item in manifest["items"]:
            if item["id"] == "MATH-PILOT-V3-NL-06":
                item["selection_preconditions"]["requires_prior_item_ids"] = [
                    missing_source_id
                ]
                break
        routing = json.loads(json.dumps(activation.PILOT_SUPPORT_ROUTING))
        routing["MATH-PILOT-V3-NL-06"]["routes"][0][
            "source_item_id"
        ] = missing_source_id
        manifest_path = self._write_manifest(
            manifest,
            "pilot-support-source-missing.json",
        )

        with patch.object(activation, "PILOT_SUPPORT_ROUTING", routing):
            with self.assertRaisesRegex(
                ValueError,
                "support route source item does not exist",
            ):
                activation.activate(self.db_path, manifest_path=manifest_path)
        self.assertFalse(self.db_path.exists())

    def test_support_route_cross_node_source_fails_before_database_creation(self) -> None:
        manifest = self._manifest()
        cross_node_source_id = "MATH-PILOT-V3-IO-01"
        source_criterion_key = ""
        for item in manifest["items"]:
            if item["id"] == cross_node_source_id:
                source_criterion_key = item["scoring_targets"][0]["key"]
            if item["id"] == "MATH-PILOT-V3-NL-06":
                item["selection_preconditions"]["requires_prior_item_ids"] = [
                    cross_node_source_id
                ]
        routing = json.loads(json.dumps(activation.PILOT_SUPPORT_ROUTING))
        route = routing["MATH-PILOT-V3-NL-06"]["routes"][0]
        route["source_item_id"] = cross_node_source_id
        route["criterion_key"] = source_criterion_key
        manifest_path = self._write_manifest(
            manifest,
            "pilot-support-source-cross-node.json",
        )

        with patch.object(activation, "PILOT_SUPPORT_ROUTING", routing):
            with self.assertRaisesRegex(
                ValueError,
                "support route source node is not legal",
            ):
                activation.activate(self.db_path, manifest_path=manifest_path)
        self.assertFalse(self.db_path.exists())

    def test_nl10_unrelated_gap_does_not_route_support_asset(self) -> None:
        _conn, _runtime, _flow, _source_attempt, result = self._create_nl10_teaching_repair(
            criterion_statuses={"valid_multiple_examples": "not_met"},
        )

        self.assertEqual("MATH-PILOT-V3-NL-10", result["step"]["question_id"])

    def test_nl10_without_gap_does_not_route_support_asset(self) -> None:
        _conn, _runtime, _flow, _source_attempt, result = self._create_nl10_teaching_repair(
            criterion_statuses={},
        )

        self.assertEqual("MATH-PILOT-V3-NL-10", result["step"]["question_id"])

    def test_generic_learn_excludes_support_and_forged_target_context_is_rejected(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        graph_version = conn.execute(
            "select graph_version from question_bank_version_ledger where status = 'active'"
        ).fetchone()[0]
        support_id = "MATH-PILOT-V3-NL-06"
        sibling_ids = [
            row["id"]
            for row in conn.execute(
                "select id from question_items where node_id = 'M-G7-NUMBER-LINE' and id <> ?",
                (support_id,),
            )
        ]

        generic_packet = question_bank.QuestionBankService.candidate_packet_for_node(
            conn,
            node_id="M-G7-NUMBER-LINE",
            graph_version=graph_version,
            flow_id="FLOW-generic-learn-support-exclusion",
            exclusions={"recent_question_ids": sibling_ids},
            question_bank_version=activation.PILOT_VERSION,
            selection_intent="new_knowledge_teaching",
            required_purpose="teaching",
        )
        self.assertNotIn(
            support_id,
            {candidate["question_id"] for candidate in generic_packet["candidates"]},
        )

        with self.assertRaisesRegex(ValueError, "accepted assessment routing receipt"):
            question_bank.QuestionBankService.candidate_packet_for_node(
                conn,
                node_id="M-G7-NUMBER-LINE",
                graph_version=graph_version,
                flow_id="FLOW-targeted-support-repair",
                exclusions={"recent_question_ids": sibling_ids},
                question_bank_version=activation.PILOT_VERSION,
                selection_intent="targeted_support_repair",
                required_purpose="teaching",
                support_routing_context={
                    "source_item_id": "MATH-PILOT-V3-NL-10",
                    "criterion_statuses": {
                        "unique_endpoints_with_midpoint": "not_met",
                    },
                    "node_state": "weak",
                },
            )

    def test_planner_packet_filters_support_only_by_planned_usage_purpose(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
        state = runtime.start_review_mode(client_day_key="2099-07-28")
        current_step = conn.execute(
            "select * from flow_steps where step_handle = ?",
            (state["current_step"]["step_handle"],),
        ).fetchone()
        flow = dict(runtime._flow_by_id(current_step["flow_id"]))
        support_id = "MATH-PILOT-V3-NL-06"
        rows = conn.execute(
            """
            select q.id, q.item_version, r.id as review_record_id
            from question_items q
            join question_review_records r
              on r.question_id = q.id
             and r.item_version = q.item_version
             and r.review_status = 'approved'
             and r.active_eligible = 1
            where q.node_id = 'M-G7-NUMBER-LINE'
              and q.id not in (?, ?)
            order by q.id
            """,
            (support_id, current_step["question_id"]),
        ).fetchall()
        now = db.now_iso()
        next_position = int(current_step["position"]) + 1
        for index, row in enumerate(rows):
            conn.execute(
                """
                insert into flow_steps(
                  id, flow_id, step_handle, position, step_type, status,
                  graph_version, node_id, question_bank_version,
                  question_id, question_item_version, review_record_id,
                  expected_evidence_json, prompt_package_json,
                  selection_reason_json, step_revision, created_at, updated_at
                ) values (?, ?, ?, ?, 'question', 'completed', ?,
                          'M-G7-NUMBER-LINE', ?, ?, ?, ?, '{}', '{}', '{}',
                          1, ?, ?)
                """,
                (
                    f"FS-planner-support-history-{index}",
                    flow["id"],
                    f"step-planner-support-history-{index}",
                    next_position + index,
                    flow["graph_version"],
                    activation.PILOT_VERSION,
                    row["id"],
                    row["item_version"],
                    row["review_record_id"],
                    now,
                    now,
                ),
            )
        conn.commit()
        stable_attempt = {
            "id": "A-planner-support-stable",
            "node_id": "M-G7-NUMBER-LINE",
            "result": "correct",
            "blocking_evidence": False,
            "flow_step_id": current_step["id"],
            "question_bank_version": activation.PILOT_VERSION,
        }
        with patch.object(
            runtime,
            "_stable_ready_context",
            return_value={
                "supported": True,
                "learner_status": "A",
                "prerequisite_ready": True,
            },
        ):
            diagnostic_packet = runtime._candidate_packet_for_planner(
                flow,
                stable_attempt,
            )
        self.assertEqual("diagnostic", diagnostic_packet["required_purpose"])
        self.assertNotIn(
            support_id,
            {
                candidate["question_id"]
                for candidate in diagnostic_packet["candidates"]
            },
        )
        self.assertGreaterEqual(
            int(diagnostic_packet["filter_summary"]["excluded_purpose_mismatch"]),
            1,
        )

        practice_packet = runtime._candidate_packet_for_planner(
            flow,
            {**stable_attempt, "id": "A-planner-support-partial", "result": "partial"},
        )
        self.assertEqual("practice", practice_packet["required_purpose"])
        self.assertNotIn(
            support_id,
            {candidate["question_id"] for candidate in practice_packet["candidates"]},
        )

    def test_planner_consumer_rejects_forged_support_candidate_before_writes(self) -> None:
        activation.activate(self.db_path)
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
        state = runtime.start_review_mode(client_day_key="2099-07-28")
        source_step = conn.execute(
            "select * from flow_steps where step_handle = ?",
            (state["current_step"]["step_handle"],),
        ).fetchone()
        flow = dict(runtime._flow_by_id(source_step["flow_id"]))
        source_question = db.get_question(conn, source_step["question_id"])
        attempt_id = db.record_attempt(
            conn,
            session_id=flow["legacy_session_id"],
            question_id=source_question["id"],
            node_id=source_question["node_id"],
            result="correct",
            score_points=2,
            max_points=2,
            error_tags=[],
            answer_raw="fixture",
            parent_note="",
            question_bank_version=activation.PILOT_VERSION,
            commit=False,
        )
        conn.execute(
            """
            update attempts
            set flow_step_id = ?, graph_version = ?, analysis_version = 1,
                analysis_status = 'valid'
            where id = ?
            """,
            (source_step["id"], flow["graph_version"], attempt_id),
        )
        support_id = "MATH-PILOT-V3-NL-06"
        support_question = db.get_question(conn, support_id)
        support_review = conn.execute(
            """
            select id from question_review_records
            where question_id = ? and item_version = ?
              and review_status = 'approved' and active_eligible = 1
            """,
            (support_id, activation.PILOT_VERSION),
        ).fetchone()
        packet = {
            "packet_id": "CP-forged-support",
            "packet_hash": "forged-support-hash",
            "packet_schema_version": "2026-07-11.v5.planner-candidate-packet.v1",
            "graph_version": flow["graph_version"],
            "question_bank_version": activation.PILOT_VERSION,
            "flow_id": flow["id"],
            "flow_revision": int(flow["flow_revision"]),
            "target_node_id": source_question["node_id"],
            "candidate_count": 1,
            "required_purpose": "diagnostic",
            "filter_summary": {},
            "candidates": [
                {
                    "question_id": support_id,
                    "item_version": activation.PILOT_VERSION,
                    "node_id": support_question["node_id"],
                    "kind": support_question["kind"],
                    "review_record_id": support_review["id"],
                    "allowed_purposes": ["diagnostic"],
                }
            ],
        }
        payload = {
            "payload_schema_version": "2026-07-11.v5.job-payload.v1",
            "flow_id": flow["id"],
            "flow_revision": int(flow["flow_revision"]),
            "flow_step_id": source_step["id"],
            "step_revision": int(source_step["step_revision"]),
            "attempt_id": attempt_id,
            "attempt_version": 1,
            "analysis_version": 1,
            "graph_version": flow["graph_version"],
            "question_bank_version": activation.PILOT_VERSION,
            "question_id": source_question["id"],
            "review_record_id": source_step["review_record_id"],
            "provider_mode": "recorded_model",
            "candidate_packet": packet,
            "source_evidence_validation_ids": [],
            "source_mastery_decision_ids": [],
        }
        now = db.now_iso()
        conn.execute(
            """
            insert into background_jobs(
              id, job_type, session_id, attempt_id, status, payload_json,
              idempotency_key, flow_id, flow_revision, flow_step_id,
              step_revision, attempt_version, analysis_version,
              graph_version, question_bank_version, question_id,
              review_record_id, candidate_packet_id, provider_mode,
              payload_schema_version, created_at, updated_at
            ) values (
              'BJ-forged-support', 'planner_decision', ?, ?, 'queued', ?,
              'planner-forged-support', ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?,
              'recorded_model', ?, ?, ?
            )
            """,
            (
                flow["legacy_session_id"],
                attempt_id,
                db.json_dump(payload),
                flow["id"],
                int(flow["flow_revision"]),
                source_step["id"],
                int(source_step["step_revision"]),
                flow["graph_version"],
                activation.PILOT_VERSION,
                source_question["id"],
                source_step["review_record_id"],
                packet["packet_id"],
                payload["payload_schema_version"],
                now,
                now,
            ),
        )
        conn.commit()
        before_step_count = conn.execute(
            "select count(*) from flow_steps where flow_id = ?",
            (flow["id"],),
        ).fetchone()[0]
        before_source_status = conn.execute(
            "select status from flow_steps where id = ?",
            (source_step["id"],),
        ).fetchone()[0]
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="planner_agent",
            phase="planner_decision",
            status="accepted",
            provider_mode="recorded_model",
            retryable=False,
            confidence=0.99,
            output={
                "schema_version": "2026-07-11.planner-next-step.v5.schema.v2",
                "action": "stretch",
                "target_node_id": support_question["node_id"],
                "selected_candidate_id": support_id,
                "candidate_packet_id": packet["packet_id"],
                "branch_policy": {
                    "uses_prerequisite_first": False,
                    "requires_teaching_generation": False,
                },
                "confidence": 0.99,
                "reason": "forged support-only selection",
            },
            prompt_version_id="planner-test",
            response_schema_version="planner-test",
        )

        with patch.object(
            semantic_agents,
            "call_planner_agent",
            return_value=envelope,
        ):
            result = runtime.process_next_background_job(
                worker_id="planner-support-worker",
                flow_id=flow["id"],
                job_id="BJ-forged-support",
            )

        self.assertEqual("retry", result.get("status"), result)
        self.assertEqual(
            "retry",
            conn.execute(
                "select status from background_jobs where id = 'BJ-forged-support'"
            ).fetchone()[0],
        )
        self.assertEqual(
            0,
            conn.execute(
                "select count(*) from next_step_decisions where flow_id = ?",
                (flow["id"],),
            ).fetchone()[0],
        )
        self.assertEqual(
            before_step_count,
            conn.execute(
                "select count(*) from flow_steps where flow_id = ?",
                (flow["id"],),
            ).fetchone()[0],
        )
        self.assertEqual(
            before_source_status,
            conn.execute(
                "select status from flow_steps where id = ?",
                (source_step["id"],),
            ).fetchone()[0],
        )
        self.assertNotIn(
            conn.execute(
                "select status from daily_flows where id = ?",
                (flow["id"],),
            ).fetchone()[0],
            {"blocked", "completed"},
        )
        self.assertEqual(
            0,
            conn.execute(
                "select count(*) from background_jobs where status = 'dead_letter'"
            ).fetchone()[0],
        )

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

    def test_authorized_v2_to_v3_cutover_backs_up_and_preserves_old_ledger(self) -> None:
        self._activate_predecessor_bank()
        conn = db.connect(self.db_path)
        runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
        blocking_flow = runtime._create_daily_flow(
            "2099-07-28",
            runtime.graph.current_graph_version(),
        )
        conn.commit()
        conn.close()
        backup_dir = self.root / "backups"

        with patch.object(activation, "PRODUCTION_DB", self.db_path.resolve()):
            staged = activation.activate(
                self.db_path,
                allow_production_cutover=True,
                expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                backup_dir=backup_dir,
            )

        self.assertEqual("staged_waiting_for_safe_boundary", staged["status"])
        self.assertEqual([blocking_flow["id"]], staged["blockers"]["daily_flows"])
        self.assertTrue(Path(staged["backup"]).is_file())
        self.assertEqual(64, len(staged["backup_sha256"]))
        first_backup = staged["backup"]
        conn = db.connect(self.db_path)
        self.assertEqual(
            (activation.PILOT_PREVIOUS_VERSION, "active"),
            tuple(conn.execute(
                "select question_bank_version, status from question_bank_version_ledger where status = 'active'"
            ).fetchone()),
        )
        self.assertEqual(
            "staged",
            conn.execute(
                "select status from question_bank_version_ledger where question_bank_version = ?",
                (activation.PILOT_VERSION,),
            ).fetchone()[0],
        )
        self.assertEqual(
            0,
            conn.execute(
                "select count(*) from answer_contracts where question_bank_version = ?",
                (activation.PILOT_VERSION,),
            ).fetchone()[0],
        )
        conn.execute(
            "update daily_flows set status = 'completed', current_step_id = null where id = ?",
            (blocking_flow["id"],),
        )
        conn.commit()
        conn.close()

        with patch.object(activation, "PRODUCTION_DB", self.db_path.resolve()):
            result = activation.activate(
                self.db_path,
                allow_production_cutover=True,
                expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                backup_dir=backup_dir,
            )

        self.assertEqual("activated", result["status"])
        self.assertEqual(activation.PILOT_PREVIOUS_VERSION, result["previous_question_bank_version"])
        self.assertTrue(Path(result["backup"]).is_file())
        self.assertEqual(64, len(result["backup_sha256"]))
        self.assertNotEqual(first_backup, result["backup"])
        backup_conn = db.connect(Path(result["backup"]))
        try:
            self.assertEqual("ok", backup_conn.execute("pragma quick_check").fetchone()[0])
        finally:
            backup_conn.close()
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        ledgers = {
            row["question_bank_version"]: row["status"]
            for row in conn.execute(
                "select question_bank_version, status from question_bank_version_ledger"
            )
        }
        self.assertEqual("superseded", ledgers[activation.PILOT_PREVIOUS_VERSION])
        self.assertEqual("active", ledgers[activation.PILOT_VERSION])
        self.assertEqual(
            activation.PILOT_ACTIVE_ITEM_COUNT,
            conn.execute(
                "select count(*) from question_items where item_version = ?",
                (activation.PILOT_VERSION,),
            ).fetchone()[0],
        )

    def test_stage_only_is_consistent_for_isolated_databases(self) -> None:
        staged = activation.activate(self.db_path, stage_only=True)

        self.assertEqual("staged", staged["status"])
        conn = db.connect(self.db_path)
        self.assertEqual(
            (activation.PILOT_VERSION, "staged"),
            tuple(conn.execute(
                "select question_bank_version, status from question_bank_version_ledger"
            ).fetchone()),
        )
        self.assertEqual(
            0,
            conn.execute(
                "select count(*) from answer_contracts where question_bank_version = ?",
                (activation.PILOT_VERSION,),
            ).fetchone()[0],
        )
        conn.close()

        activated = activation.activate(self.db_path)

        self.assertEqual("activated", activated["status"])
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(
            "active",
            conn.execute(
                "select status from question_bank_version_ledger where question_bank_version = ?",
                (activation.PILOT_VERSION,),
            ).fetchone()[0],
        )

    def test_production_cutover_backs_up_without_writable_schema_initialization(self) -> None:
        self._activate_predecessor_bank()

        with patch.object(activation, "PRODUCTION_DB", self.db_path.resolve()), patch.object(
            db,
            "init_schema",
            side_effect=AssertionError("production cutover must not run migrations"),
        ):
            result = activation.activate(
                self.db_path,
                allow_production_cutover=True,
                expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                backup_dir=self.root / "backups",
                stage_only=True,
            )

        self.assertEqual("staged", result["status"])
        self.assertTrue(Path(result["backup"]).is_file())
        self.assertEqual(64, len(result["backup_sha256"]))

    def test_cutover_blocks_every_canonical_active_background_job_status(self) -> None:
        self._activate_predecessor_bank()
        conn = db.connect(self.db_path)
        session_id = db.create_session(
            conn,
            "active job blocker fixture",
            mode="daily_flow_v3",
            status="active",
            commit=False,
        )
        now = db.now_iso()
        expected_ids = []
        for status in sorted(db.V3_ACTIVE_BACKGROUND_JOB_STATUSES):
            job_id = f"BJ-{status}"
            expected_ids.append(job_id)
            conn.execute(
                """
                insert into background_jobs(
                  id, job_type, session_id, status, payload_json,
                  created_at, updated_at
                ) values (?, 'answer_analysis', ?, ?, '{}', ?, ?)
                """,
                (job_id, session_id, status, now, now),
            )
        conn.commit()
        conn.close()

        with patch.object(activation, "PRODUCTION_DB", self.db_path.resolve()):
            result = activation.activate(
                self.db_path,
                allow_production_cutover=True,
                expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                backup_dir=self.root / "backups",
            )

        self.assertEqual("staged_waiting_for_safe_boundary", result["status"])
        self.assertEqual(expected_ids, result["blockers"]["background_jobs"])
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(
            activation.PILOT_PREVIOUS_VERSION,
            conn.execute(
                "select question_bank_version from question_bank_version_ledger where status = 'active'"
            ).fetchone()[0],
        )

    def test_cutover_rechecks_blockers_inside_immediate_transaction(self) -> None:
        self._activate_predecessor_bank()
        conn = db.connect(self.db_path)
        session_id = db.create_session(
            conn,
            "cutover race fixture",
            mode="daily_flow_v3",
            status="active",
        )
        conn.close()
        original_blockers = activation._runtime_cutover_blockers
        calls = 0

        def inject_job_after_first_check(conn):
            nonlocal calls
            calls += 1
            if calls == 1:
                other = db.connect(self.db_path)
                try:
                    now = db.now_iso()
                    other.execute(
                        """
                        insert into background_jobs(
                          id, job_type, session_id, status, payload_json,
                          created_at, updated_at
                        ) values (
                          'BJ-cutover-race', 'answer_analysis', ?, 'running',
                          '{}', ?, ?
                        )
                        """,
                        (session_id, now, now),
                    )
                    other.commit()
                finally:
                    other.close()
                return {
                    "daily_flows": [],
                    "background_jobs": [],
                    "learning_target_intents": [],
                }
            return original_blockers(conn)

        with patch.object(activation, "PRODUCTION_DB", self.db_path.resolve()), patch.object(
            activation,
            "_runtime_cutover_blockers",
            side_effect=inject_job_after_first_check,
        ):
            result = activation.activate(
                self.db_path,
                allow_production_cutover=True,
                expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                backup_dir=self.root / "backups",
            )

        self.assertEqual(2, calls)
        self.assertEqual("staged_waiting_for_safe_boundary", result["status"])
        self.assertEqual(
            ["BJ-cutover-race"],
            result["blockers"]["background_jobs"],
        )
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(
            activation.PILOT_PREVIOUS_VERSION,
            conn.execute(
                "select question_bank_version from question_bank_version_ledger where status = 'active'"
            ).fetchone()[0],
        )

    def test_predecessor_ledger_receipt_and_instance_identity_fail_closed(self) -> None:
        cases = ("ledger", "receipt", "problem_instance")
        for case in cases:
            with self.subTest(case=case):
                db_path = self.root / f"predecessor-{case}.sqlite"
                self._activate_predecessor_bank(db_path)
                conn = db.connect(db_path)
                if case == "ledger":
                    conn.execute(
                        "update question_bank_version_ledger set manifest_sha256 = 'tampered' where status = 'active'"
                    )
                elif case == "receipt":
                    row = conn.execute(
                        "select value from system_meta where key = ?",
                        (knowledge_map.ASSESSMENT_RECEIPT_KEY,),
                    ).fetchone()
                    receipt = db.json_load(row["value"], {})
                    receipt["question_bank_ledger_id"] = "QBL-tampered"
                    conn.execute(
                        "update system_meta set value = ? where key = ?",
                        (
                            db.json_dump(receipt),
                            knowledge_map.ASSESSMENT_RECEIPT_KEY,
                        ),
                    )
                else:
                    row = conn.execute(
                        "select id, raw_json from question_items where item_version = ? order by id limit 1",
                        (activation.PILOT_PREVIOUS_VERSION,),
                    ).fetchone()
                    raw = db.json_load(row["raw_json"], {})
                    raw["problem_instance_id"] = "PI-tampered"
                    conn.execute(
                        "update question_items set raw_json = ? where id = ?",
                        (db.json_dump(raw), row["id"]),
                    )
                conn.commit()
                conn.close()

                with patch.object(activation, "PRODUCTION_DB", db_path.resolve()):
                    with self.assertRaisesRegex(ValueError, "predecessor authority"):
                        activation.activate(
                            db_path,
                            allow_production_cutover=True,
                            expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                            backup_dir=self.root / f"backups-{case}",
                        )

                conn = db.connect(db_path)
                self.assertEqual(
                    0,
                    conn.execute(
                        "select count(*) from question_bank_version_ledger where question_bank_version = ?",
                        (activation.PILOT_VERSION,),
                    ).fetchone()[0],
                )
                conn.close()

    def test_stage_and_activate_preserve_learning_evidence_row_digests(self) -> None:
        self._activate_predecessor_bank()
        conn = db.connect(self.db_path)
        self._seed_authoritative_learning_evidence(conn)
        before = self._learning_evidence_digests(conn)
        conn.close()

        with patch.object(activation, "PRODUCTION_DB", self.db_path.resolve()):
            staged = activation.activate(
                self.db_path,
                allow_production_cutover=True,
                expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                backup_dir=self.root / "backups",
                stage_only=True,
            )
        self.assertEqual("staged", staged["status"])
        conn = db.connect(self.db_path)
        self.assertEqual(before, self._learning_evidence_digests(conn))
        conn.close()

        with patch.object(activation, "PRODUCTION_DB", self.db_path.resolve()):
            activated = activation.activate(
                self.db_path,
                allow_production_cutover=True,
                expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                backup_dir=self.root / "backups",
            )
        self.assertEqual("activated", activated["status"])
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(before, self._learning_evidence_digests(conn))

    def test_malformed_manifest_fails_before_database_creation(self) -> None:
        malformed = self._manifest()
        malformed["items"][0]["scoring_targets"][0]["points"] = 7
        manifest_path = self._write_manifest(malformed)

        with self.assertRaisesRegex(ValueError, "must total 10"):
            activation.activate(self.db_path, manifest_path=manifest_path)

        self.assertFalse(self.db_path.exists())

    def test_formal_pilot_scoring_targets_declare_explicit_contract_semantics(self) -> None:
        manifest, items, _digest = activation.load_pilot(activation.DEFAULT_MANIFEST)
        self.assertEqual(24, len(items))
        self.assertEqual(24, len(manifest["items"]))
        self.assertEqual(
            23,
            len([item for item in items if item["activation_status"] == "active"]),
        )
        for item in items:
            for target in item["scoring_targets"]:
                with self.subTest(item_id=item["id"], target=target["key"]):
                    self.assertIn(
                        target["dimension"],
                        assessment_policy.ALLOWED_MASTERY_DIMENSIONS,
                    )
                    self.assertIsInstance(target["required_for_pass"], bool)
                    assessment_policy.validate_authoritative_scoring_targets(item)

    def test_formal_pilot_reference_components_resolve_to_exact_answer_components(self) -> None:
        _manifest, items, _digest = activation.load_pilot(activation.DEFAULT_MANIFEST)

        for item in items:
            with self.subTest(item_id=item["id"]):
                validated = assessment_policy.validate_authoritative_scoring_targets(
                    item
                )
                self.assertEqual(len(item["scoring_targets"]), len(validated))

    def test_formal_pilot_rejects_malformed_or_out_of_range_reference_component(self) -> None:
        for reference_component in (
            "solution_steps",
            "solution_steps[-1]",
            "solution_steps[99]",
            "solution_steps[abc]",
            "unknown_reference",
        ):
            with self.subTest(reference_component=reference_component):
                malformed = self._manifest()
                malformed["items"][0]["scoring_targets"][0][
                    "reference_component"
                ] = reference_component
                manifest_path = self._write_manifest(
                    malformed,
                    name="pilot-invalid-reference-component.json",
                )
                with self.assertRaisesRegex(ValueError, "reference_component"):
                    activation.activate(self.db_path, manifest_path=manifest_path)
                self.assertFalse(self.db_path.exists())

    def test_formal_pilot_missing_dimension_or_evidence_source_fails_closed(self) -> None:
        for field in ("dimension", "reference_component"):
            with self.subTest(field=field):
                malformed = self._manifest()
                malformed["items"][0]["scoring_targets"][0].pop(field, None)
                manifest_path = self._write_manifest(
                    malformed,
                    name=f"pilot-missing-{field}.json",
                )
                with self.assertRaisesRegex(ValueError, field):
                    activation.activate(self.db_path, manifest_path=manifest_path)
                self.assertFalse(self.db_path.exists())

    def test_each_active_formal_item_missing_explicit_scoring_field_fails_closed(self) -> None:
        manifest = self._manifest()
        _loaded_manifest, loaded_items, _digest = activation.load_pilot(
            activation.DEFAULT_MANIFEST
        )
        active_ids = {
            item["id"]
            for item in loaded_items
            if item["activation_status"] == "active"
        }
        active_indexes = [
            index
            for index, item in enumerate(manifest["items"])
            if item["id"] in active_ids
        ]
        self.assertEqual(23, len(active_indexes))
        for item_index in active_indexes:
            item_id = manifest["items"][item_index]["id"]
            for field in (
                "scoring_targets",
                "key",
                "criterion",
                "points",
                "dimension",
                "required_for_pass",
                "reference_component",
            ):
                with self.subTest(item_id=item_id, field=field):
                    malformed = self._manifest()
                    if field == "scoring_targets":
                        malformed["items"][item_index].pop(field, None)
                    else:
                        malformed["items"][item_index]["scoring_targets"][0].pop(
                            field,
                            None,
                        )
                    manifest_path = self._write_manifest(
                        malformed,
                        name=f"pilot-{item_id}-{field}.json",
                    )
                    with self.assertRaises(ValueError):
                        activation.activate(self.db_path, manifest_path=manifest_path)
                    self.assertFalse(self.db_path.exists())

    def test_expert_activation_order_and_hold_are_runtime_authoritative(self) -> None:
        _manifest, items, _digest = activation.load_pilot(activation.DEFAULT_MANIFEST)
        by_id = {item["id"]: item for item in items}
        self.assertEqual("hold", by_id["MATH-PILOT-V3-NL-01"]["activation_status"])
        self.assertTrue(by_id["MATH-PILOT-V3-NL-01"]["usage_policy"]["not_for_activation"])

        authority = {"assessment": {"assets_by_node": {}}}
        for node_id in activation.PILOT_NODE_IDS:
            authority["assessment"]["assets_by_node"][node_id] = [
                {"question_id": item["id"], "question": item}
                for item in items
                if item["node_id"] == node_id and item["activation_status"] == "active"
            ]

        expected_first = {
            "M-PRE-INTEGER-OPS": "MATH-PILOT-V3-IO-03",
            "M-G7-NUMBER-LINE": "MATH-PILOT-V3-NL-02",
            "M-G7-EQ-SOLVE": "MATH-PILOT-V3-EQ-02",
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
            "M-PRE-INTEGER-OPS": "MATH-PILOT-V3-IO-03",
            "M-G7-NUMBER-LINE": "MATH-PILOT-V3-NL-02",
            "M-G7-EQ-SOLVE": "MATH-PILOT-V3-EQ-02",
        }
        for node_id, question_id in expected_first.items():
            selected = daily_runtime._authoritative_target_asset(
                authority,
                node_id=node_id,
                action="diagnostic",
            )
            self.assertEqual(question_id, selected["question_id"])

        support_asset = next(
            asset
            for asset in authority["assessment"]["assets_by_node"][
                "M-G7-NUMBER-LINE"
            ]
            if asset["question_id"] == "MATH-PILOT-V3-NL-06"
        )
        self.assertTrue(support_asset["support_only"])

    def test_generic_learn_target_materialization_cannot_fall_back_to_support(self) -> None:
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
            authority = {
                "snapshot": snapshot,
                "assessment": service._assessment_authority(snapshot),
            }
            runtime = daily_runtime.DailyLearningRuntime(
                conn,
                project_root=PROJECT_ROOT,
            )
            flow = dict(
                runtime._create_daily_flow(
                    "2099-07-28-support-learn-bypass",
                    authority["snapshot"]["graph_lineage"],
                )
            )
            number_line_assets = authority["assessment"]["assets_by_node"][
                "M-G7-NUMBER-LINE"
            ]
            regular_assets = [
                asset
                for asset in number_line_assets
                if asset["question_id"] != "MATH-PILOT-V3-NL-06"
            ]
            now = db.now_iso()
            for position, asset in enumerate(regular_assets, start=1):
                question = asset["question"]
                conn.execute(
                    """
                    insert into flow_steps(
                      id, flow_id, step_handle, position, step_type, status,
                      graph_version, node_id, question_bank_version,
                      question_id, question_item_version, review_record_id,
                      expected_evidence_json, prompt_package_json,
                      selection_reason_json, step_revision, created_at, updated_at
                    ) values (?, ?, ?, ?, 'worked_example', 'completed', ?, ?, ?,
                              ?, ?, ?, '{}', '{}', '{}', 1, ?, ?)
                    """,
                    (
                        f"FS-support-learn-history-{position}",
                        flow["id"],
                        f"step-support-learn-history-{position}",
                        position,
                        flow["graph_version"],
                        question["node_id"],
                        flow["question_bank_version"],
                        question["id"],
                        question["item_version"],
                        asset["review_record_id"],
                        now,
                        now,
                    ),
                )
            intent = knowledge_map.create_target_intent(
                conn,
                child_key="single-child",
                graph_version=authority["snapshot"]["graph_lineage"],
                node_id="M-G7-NUMBER-LINE",
                action="learn",
                client_idempotency_key="generic-learn-must-not-use-support",
                source_flow_id=flow["id"],
                source_flow_revision=int(flow["flow_revision"]),
            )

            qualification = daily_runtime.qualify_knowledge_target_action(
                conn,
                authority,
                node_id="M-G7-NUMBER-LINE",
                action="learn",
                excluded_problem_instance_ids=runtime._reserved_problem_instance_ids_for_flow(
                    flow["id"]
                ),
            )
            self.assertFalse(qualification["enabled"])
            self.assertEqual(
                "target_teaching_instance_exhausted",
                qualification["reason_code"],
            )

            result = runtime._materialize_target_intent_locked(
                intent["id"],
                authority,
                local_date="2099-07-28-support-learn-bypass",
            )

        self.assertEqual("blocked", result["status"])
        self.assertEqual("target_teaching_instance_exhausted", result["reason"])
        stored_intent = conn.execute(
            "select status, reason from learning_target_intents where id = ?",
            (intent["id"],),
        ).fetchone()
        self.assertEqual("blocked", stored_intent["status"])
        self.assertEqual("target_teaching_instance_exhausted", stored_intent["reason"])
        self.assertEqual(
            0,
            conn.execute(
                """
                select count(*) from flow_steps
                where flow_id = ? and question_id = 'MATH-PILOT-V3-NL-06'
                """,
                (flow["id"],),
            ).fetchone()[0],
        )

    def test_expert_scoring_revisions_do_not_over_penalize_nonessential_writing(self) -> None:
        _manifest, items, _digest = activation.load_pilot(activation.DEFAULT_MANIFEST)
        by_id = {item["id"]: item for item in items}

        def target(question_id: str, key: str) -> dict:
            return next(
                point
                for point in by_id[question_id]["scoring_targets"]
                if point["key"] == key
            )

        self.assertFalse(target("MATH-PILOT-V3-IO-02", "correct_judgment")["required_for_pass"])
        self.assertTrue(target("MATH-PILOT-V3-IO-03", "valid_regrouping")["required_for_pass"])
        self.assertFalse(target("MATH-PILOT-V3-IO-04", "correct_result")["required_for_pass"])
        self.assertFalse(target("MATH-PILOT-V3-NL-04", "direction_reason")["required_for_pass"])
        self.assertEqual(4, target("MATH-PILOT-V3-EQ-03", "equivalent_reduction")["points"])
        self.assertTrue(target("MATH-PILOT-V3-EQ-03", "equivalent_reduction")["required_for_pass"])

    def test_number_line_v3_has_balanced_families_and_real_depth(self) -> None:
        manifest, items, _digest = activation.load_pilot(activation.DEFAULT_MANIFEST)
        number_line = [
            item for item in items if item["node_id"] == "M-G7-NUMBER-LINE"
        ]
        self.assertEqual(12, len(number_line))
        self.assertEqual(
            activation.NUMBER_LINE_FAMILY_COUNTS,
            Counter(
                item["source"]["problem_family_basis"]["question_family_id"]
                for item in number_line
            ),
        )
        active = [
            item for item in number_line if item["activation_status"] == "active"
        ]
        self.assertEqual(11, len(active))
        self.assertGreaterEqual(
            sum(item["variant_level"] == "L4" for item in active),
            4,
        )
        self.assertEqual(12, len({item["prompt"] for item in number_line}))
        self.assertEqual(
            {
                "MATH-PILOT-V3-NL-07",
                "MATH-PILOT-V3-NL-08",
                "MATH-PILOT-V3-NL-09",
                "MATH-PILOT-V3-NL-10",
                "MATH-PILOT-V3-NL-11",
                "MATH-PILOT-V3-NL-12",
            },
            {
                item["id"]
                for item in number_line
                if item["id"].split("-")[-1] in {
                    "07", "08", "09", "10", "11", "12"
                }
            },
        )
        self.assertEqual(
            set(manifest["question_family_assignments"]),
            {item["id"] for item in number_line},
        )
        self.assertEqual(
            24,
            len(manifest["predecessor_question_ids"]),
        )
        for item in items:
            predecessor_id = manifest["predecessor_question_ids"].get(item["id"])
            instance_key = item["source"]["problem_instance_basis"]["instance_key"]
            expected_instance_id = "PI-" + activation.canonical_sha256(
                {
                    "manifest_id": (
                        activation.predecessor_manifest_id(predecessor_id)
                        if predecessor_id
                        else activation.PILOT_MANIFEST_ID
                    ),
                    "question_id": predecessor_id or item["id"],
                    "problem_instance_key": instance_key,
                }
            )[:20]
            self.assertEqual(expected_instance_id, item["problem_instance_id"])

    def test_number_line_v3_scoring_requires_each_questions_diagnostic_evidence(self) -> None:
        _manifest, items, _digest = activation.load_pilot(activation.DEFAULT_MANIFEST)
        by_id = {item["id"]: item for item in items}
        expected_required_points = {
            "MATH-PILOT-V3-NL-07": 10,
            "MATH-PILOT-V3-NL-08": 10,
            "MATH-PILOT-V3-NL-09": 10,
            "MATH-PILOT-V3-NL-10": 10,
            "MATH-PILOT-V3-NL-11": 10,
            "MATH-PILOT-V3-NL-12": 10,
        }
        for question_id, expected_points in expected_required_points.items():
            with self.subTest(question_id=question_id):
                item = by_id[question_id]
                self.assertEqual(
                    expected_points,
                    sum(
                        point["points"]
                        for point in item["scoring_targets"]
                        if point["required_for_pass"]
                    ),
                )
                self.assertEqual(
                    10,
                    sum(point["points"] for point in item["scoring_targets"]),
                )

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
            self.assertEqual("MATH-PILOT-V3-NL-02", first_step["question_id"])
            self.assertEqual(2, first_group["size"])
            self.assertTrue(first_group["defer_analysis_until_group_end"])

            self._complete_selected_flow(conn, runtime, first_flow_id)
            second = runtime.start_review_mode(client_day_key="2099-07-26-second-tab")
            second_flow_id = conn.execute(
                "select flow_id from flow_steps where step_handle = ?",
                (second["current_step"]["step_handle"],),
            ).fetchone()["flow_id"]
            second_question_id = conn.execute(
                "select question_id from flow_steps where flow_id = ? order by created_at limit 1",
                (second_flow_id,),
            ).fetchone()["question_id"]
            self.assertEqual("MATH-PILOT-V3-NL-04", second_question_id)
            self.assertNotEqual(first_step["question_id"], second_question_id)

    def test_group_review_does_not_start_singleton_followup_when_bank_has_one_candidate(self) -> None:
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
                blocked_ids = [
                    item["id"]
                    for item in activation.load_pilot(activation.DEFAULT_MANIFEST)[1]
                    if item["node_id"] == "M-G7-NUMBER-LINE"
                    and item["activation_status"] == "active"
                    and item["id"] not in {
                        "MATH-PILOT-V3-NL-02",
                        "MATH-PILOT-V3-NL-04",
                    }
                ]
                for index, question_id in enumerate(blocked_ids, start=1):
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
            self.assertEqual("MATH-PILOT-V3-NL-02", first_question_id)
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
            self.assertEqual("MATH-PILOT-V3-NL-04", second_question_id)
            runtime.persist_child_response(
                daily_runtime.CurrentStepSubmission(
                    step_handle=second["current_step"]["step_handle"],
                    position=second["current_step"]["position"],
                    client_idempotency_key="pilot-group-purpose-second",
                    answer_text="不正确。箭头向右时数值应增大，应改为-1、0、1、2。",
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
        decision = conn.execute(
            "select action from next_step_decisions where id = ?",
            (result["next_step_decision_id"],),
        ).fetchone()
        planned_rows = conn.execute(
            """
            select selection_reason_json
            from flow_steps
            where flow_id = ? and status = 'planned'
              and step_type in ('question','micro_check','standard_check','variant_check')
            order by position
            """,
            (job["flow_id"],),
        ).fetchall()
        if result["planned_step_id"]:
            self.assertNotEqual("summary", decision["action"])
            self.assertEqual(1, len(planned_rows))
            followup_group = db.json_load(
                planned_rows[0]["selection_reason_json"], {}
            ).get("mini_group", {})
            self.assertGreaterEqual(int(followup_group.get("size") or 0), 2)
            self.assertTrue(followup_group.get("defer_analysis_until_group_end"))
        else:
            self.assertEqual("summary", decision["action"])
            self.assertEqual([], planned_rows)

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
                self._complete_selected_flow(conn, runtime, flow_id)

        self.assertEqual(
            [
                "MATH-PILOT-V3-NL-02",
                "MATH-PILOT-V3-NL-04",
                "MATH-PILOT-V3-NL-07",
                "MATH-PILOT-V3-NL-08",
            ],
            selected_ids,
        )
        self.assertNotIn("MATH-PILOT-V3-NL-05", selected_ids)

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
            self._complete_selected_flow(conn, runtime, old_flow_id)

            fresh = runtime.start_review_mode(client_day_key="2099-07-26")
            fresh_question_id = conn.execute(
                "select question_id from flow_steps where step_handle = ?",
                (fresh["current_step"]["step_handle"],),
            ).fetchone()["question_id"]

        self.assertEqual("MATH-PILOT-V3-NL-02", fresh_question_id)

    def test_cross_version_cooldown_excludes_completed_problem_instance_after_cutover(self) -> None:
        self._activate_predecessor_bank()
        conn = db.connect(self.db_path)
        with patch.dict(
            "os.environ",
            {
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
            old = runtime.start_review_mode(client_day_key="2099-07-27")
            old_step = conn.execute(
                """
                select s.flow_id, s.question_id, q.raw_json
                from flow_steps s
                join question_items q on q.id = s.question_id
                where s.step_handle = ?
                """,
                (old["current_step"]["step_handle"],),
            ).fetchone()
            old_problem_instance_id = db.json_load(old_step["raw_json"], {})[
                "problem_instance_id"
            ]
            self._complete_selected_flow(conn, runtime, old_step["flow_id"])
        conn.close()

        with patch.object(activation, "PRODUCTION_DB", self.db_path.resolve()):
            cutover = activation.activate(
                self.db_path,
                allow_production_cutover=True,
                expected_current_version=activation.PILOT_PREVIOUS_VERSION,
                backup_dir=self.root / "backups",
            )
        self.assertEqual("activated", cutover["status"])

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
            fresh = runtime.start_review_mode(client_day_key="2099-07-28")
        fresh_row = conn.execute(
            """
            select q.id, q.raw_json
            from flow_steps s
            join question_items q on q.id = s.question_id
            where s.step_handle = ?
            """,
            (fresh["current_step"]["step_handle"],),
        ).fetchone()
        fresh_problem_instance_id = db.json_load(fresh_row["raw_json"], {})[
            "problem_instance_id"
        ]
        self.assertNotEqual(old_problem_instance_id, fresh_problem_instance_id)

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

        self.assertEqual("MATH-PILOT-V3-NL-02", selected["question"]["id"])
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
        self.assertEqual(23, payload["item_count"])
        self.assertEqual(24, payload["manifest_item_count"])

    def test_authorized_bootstrap_on_formal_pilot_uses_v5_projection_not_legacy_planner(self) -> None:
        activation.activate(self.db_path)
        with patch.dict("os.environ", {"V3_DAILY_RUNTIME_ENABLED": "1"}), patch.object(
            planner,
            "latest_or_create_plan",
            side_effect=AssertionError("v5 operator bootstrap must not create a legacy plan"),
        ):
            httpd, base_url = server.start_test_server(self.db_path)
            try:
                host, port = base_url.removeprefix("http://").split(":")
                client = http.client.HTTPConnection(host, int(port), timeout=5)
                try:
                    client.request(
                        "GET",
                        "/api/bootstrap",
                        headers={"Authorization": "Bearer test-operator-token"},
                    )
                    response = client.getresponse()
                    body = response.read().decode("utf-8")
                finally:
                    client.close()
                self.assertEqual(200, response.status, body)
                payload = json.loads(body)
                self.assertEqual("v5_operator", payload["runtime_mode"])
                self.assertIn("daily_flow", payload)
                self.assertNotIn("today_plan", payload)
                self.assertNotIn("planner_blocked", payload)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_child_learning_session_start_on_formal_pilot_uses_v5_projection_not_legacy_planner(self) -> None:
        activation.activate(self.db_path)
        with patch.dict("os.environ", {"V3_DAILY_RUNTIME_ENABLED": "1"}), patch.object(
            planner,
            "latest_or_create_plan",
            side_effect=AssertionError("v5 child session start must not create a legacy plan"),
        ):
            httpd, base_url = server.start_test_server(self.db_path)
            try:
                host, port = base_url.removeprefix("http://").split(":")
                client = http.client.HTTPConnection(host, int(port), timeout=5)
                try:
                    client.request(
                        "POST",
                        "/api/learning-sessions",
                        body=json.dumps({"client_day_key": "2099-07-27"}),
                        headers={"Content-Type": "application/json"},
                    )
                    response = client.getresponse()
                    body = response.read().decode("utf-8")
                finally:
                    client.close()
                self.assertEqual(200, response.status, body)
                payload = json.loads(body)
                self.assertEqual("current_step", payload["child_state"])
                self.assertIn(payload["current_step"]["kind_label"], {"题目", "小检测"})
                self.assertTrue(payload["current_step"]["step_handle"])
                self.assertTrue(payload["current_step"]["prompt"])

                def projected_keys(value):
                    if isinstance(value, dict):
                        for key, child in value.items():
                            yield str(key).lower()
                            yield from projected_keys(child)
                    elif isinstance(value, list):
                        for child in value:
                            yield from projected_keys(child)

                exposed_keys = set(projected_keys(payload))
                for forbidden in (
                    "node_id",
                    "question_id",
                    "attempt_id",
                    "flow_id",
                    "graph_version",
                    "provider",
                    "model",
                    "planner_agent",
                ):
                    self.assertNotIn(forbidden, exposed_keys)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_formal_target_intent_recovery_uses_unseen_instance_and_bootstraps_cleanly(self) -> None:
        activation.activate(self.db_path)
        view_activation.activate(
            self.db_path,
            view_activation.DEFAULT_CONFIG,
            self.root / "knowledge-view-backups",
        )
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        with patch.dict(
            "os.environ",
            {
                "V3_DAILY_RUNTIME_ENABLED": "1",
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime, flow, current_step = self._install_formal_target_intent_flow(
                conn,
                used_integer_question_ids=("MATH-PILOT-V3-IO-03",),
            )
            service = knowledge_map.KnowledgeMapService(
                conn,
                project_root=PROJECT_ROOT,
            )
            projection = service.child_projection(child_key="single-child")
            integer_name = conn.execute(
                "select name from graph_nodes where id = 'M-PRE-INTEGER-OPS'"
            ).fetchone()["name"]
            target = next(
                node for node in projection["nodes"] if node["name"] == integer_name
            )
            descriptor = next(
                item
                for item in target["action_descriptors"]
                if item["action"] == "diagnostic"
            )
            self.assertTrue(descriptor["enabled"], descriptor)
            self.assertEqual("wait_for_safe_boundary", descriptor["result_behavior"])
            request = {
                "handle": target["handle"],
                "projection_version": projection["projection_version"],
                "action": "diagnostic",
                "client_idempotency_key": "formal-target-after-safe-boundary",
            }
            waiting = service.select_target(
                child_key="single-child",
                request=request,
            )
            replay_waiting = service.select_target(
                child_key="single-child",
                request=request,
            )
            self.assertEqual("waiting_for_safe_boundary", waiting["status"])
            self.assertEqual(waiting, replay_waiting)
            conn.execute(
                "update flow_steps set status = 'completed' where id = ?",
                (current_step["id"],),
            )
            conn.execute(
                "update daily_flows set status = 'ready_for_new_knowledge' where id = ?",
                (flow["id"],),
            )
            conn.commit()

            httpd, base_url = server.start_test_server(self.db_path)
            try:
                host, port = base_url.removeprefix("http://").split(":")
                child_client = http.client.HTTPConnection(host, int(port), timeout=5)
                try:
                    child_client.request("GET", "/api/child-bootstrap")
                    child_response = child_client.getresponse()
                    child_body = child_response.read().decode("utf-8")
                finally:
                    child_client.close()
                self.assertEqual(200, child_response.status, child_body)
                child_payload = json.loads(child_body)
                self.assertEqual("current_step", child_payload["child_state"])

                operator_client = http.client.HTTPConnection(host, int(port), timeout=5)
                try:
                    operator_client.request(
                        "GET",
                        "/api/bootstrap",
                        headers={"Authorization": "Bearer test-operator-token"},
                    )
                    operator_response = operator_client.getresponse()
                    operator_body = operator_response.read().decode("utf-8")
                finally:
                    operator_client.close()
                self.assertEqual(200, operator_response.status, operator_body)
                self.assertEqual("v5_operator", json.loads(operator_body)["runtime_mode"])
            finally:
                httpd.shutdown()
                httpd.server_close()

            intent = conn.execute(
                "select * from learning_target_intents where client_idempotency_key = ?",
                ("formal-target-after-safe-boundary",),
            ).fetchone()
            self.assertEqual("applied", intent["status"])
            applied_step = conn.execute(
                "select * from flow_steps where id = ?",
                (intent["applied_step_id"],),
            ).fetchone()
            self.assertEqual("M-PRE-INTEGER-OPS", applied_step["node_id"])
            self.assertEqual("MATH-PILOT-V3-IO-02", applied_step["question_id"])
            self.assertNotEqual("MATH-PILOT-V3-IO-03", applied_step["question_id"])
            self.assertEqual(1, conn.execute(
                "select count(*) from flow_steps where id = ?",
                (intent["applied_step_id"],),
            ).fetchone()[0])
            self.assertEqual(0, conn.execute(
                """
                select count(*)
                from attempts a
                join flow_steps s on s.id = a.flow_step_id
                where s.flow_id = ?
                """,
                (flow["id"],),
            ).fetchone()[0])

    def test_formal_target_intent_exhaustion_becomes_blocked_and_bootstraps_cleanly(self) -> None:
        activation.activate(self.db_path)
        view_activation.activate(
            self.db_path,
            view_activation.DEFAULT_CONFIG,
            self.root / "knowledge-view-backups",
        )
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        with patch.dict(
            "os.environ",
            {
                "V3_DAILY_RUNTIME_ENABLED": "1",
                "ANSWER_ASSESSMENT_POLICY": "v5.1",
                "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
            },
        ):
            runtime, flow, current_step = self._install_formal_target_intent_flow(
                conn,
                used_integer_question_ids=(
                    "MATH-PILOT-V3-IO-03",
                    "MATH-PILOT-V3-IO-02",
                    "MATH-PILOT-V3-IO-04",
                    "MATH-PILOT-V3-IO-06",
                    "MATH-PILOT-V3-IO-01",
                ),
            )
            authority = knowledge_map.KnowledgeMapService(
                conn,
                project_root=PROJECT_ROOT,
            )._runtime_authority()
            intent = knowledge_map.create_target_intent(
                conn,
                child_key="single-child",
                graph_version=authority["snapshot"]["graph_lineage"],
                node_id="M-PRE-INTEGER-OPS",
                action="diagnostic",
                client_idempotency_key="formal-target-exhausted-after-boundary",
                source_flow_id=flow["id"],
                source_flow_revision=int(flow["flow_revision"]),
                source_step_id=current_step["id"],
                status="waiting_for_safe_boundary",
                reason="current_assessment_must_finish",
            )
            conn.execute(
                "update flow_steps set status = 'completed' where id = ?",
                (current_step["id"],),
            )
            conn.execute(
                "update daily_flows set status = 'ready_for_new_knowledge' where id = ?",
                (flow["id"],),
            )
            conn.commit()

            httpd, base_url = server.start_test_server(self.db_path)
            try:
                host, port = base_url.removeprefix("http://").split(":")
                child_client = http.client.HTTPConnection(host, int(port), timeout=5)
                try:
                    child_client.request("GET", "/api/child-bootstrap")
                    child_response = child_client.getresponse()
                    child_body = child_response.read().decode("utf-8")
                finally:
                    child_client.close()
                self.assertEqual(200, child_response.status, child_body)
                child_payload = json.loads(child_body)
                self.assertIn("child_state", child_payload)

                operator_client = http.client.HTTPConnection(host, int(port), timeout=5)
                try:
                    operator_client.request(
                        "GET",
                        "/api/bootstrap",
                        headers={"Authorization": "Bearer test-operator-token"},
                    )
                    operator_response = operator_client.getresponse()
                    operator_body = operator_response.read().decode("utf-8")
                finally:
                    operator_client.close()
                self.assertEqual(200, operator_response.status, operator_body)
                self.assertEqual("v5_operator", json.loads(operator_body)["runtime_mode"])
            finally:
                httpd.shutdown()
                httpd.server_close()

            stored_intent = conn.execute(
                "select * from learning_target_intents where id = ?",
                (intent["id"],),
            ).fetchone()
            self.assertEqual("blocked", stored_intent["status"])
            self.assertEqual("target_problem_instance_exhausted", stored_intent["reason"])
            self.assertIsNone(stored_intent["applied_step_id"])
            self.assertEqual(0, conn.execute(
                """
                select count(*)
                from attempts a
                join flow_steps s on s.id = a.flow_step_id
                where s.flow_id = ?
                """,
                (flow["id"],),
            ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
