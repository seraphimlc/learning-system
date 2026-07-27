import base64
import copy
import hashlib
import http.client
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system import (
    assessment_store,
    daily_runtime,
    db,
    evidence_gate,
    internal_agents,
    job_queue,
    model_router,
    multimodal_evidence,
    question_usage,
    semantic_agents,
    server,
    test_support,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PracticeMultimodalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "practice-multimodal-seed.sqlite"
        conn = db.connect(cls._seed_path)
        try:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
            conn.close()
            from scripts import activate_lightweight_answer_contracts

            activate_lightweight_answer_contracts.activate(
                cls._seed_path,
                project_root=PROJECT_ROOT,
            )
        finally:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "practice-multimodal.sqlite"
        shutil.copy2(self._seed_path, self.db_path)
        self.conn = db.connect(self.db_path)
        self.runtime = daily_runtime.DailyLearningRuntime(
            self.conn,
            project_root=PROJECT_ROOT,
        )
        self.started = self.runtime.start_review_mode(
            client_day_key=f"2099-08-01-practice-multimodal-{id(self)}"
        )
        self.step = self.started["current_step"]

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _step_row(self, state=None):
        step = (state or self.started)["current_step"]
        row = self.conn.execute(
            "select * from flow_steps where step_handle = ? and position = ?",
            (step["step_handle"], step["position"]),
        ).fetchone()
        self.assertIsNotNone(row)
        return dict(row)

    def _set_practice_context(self, step_row, *, size=3, index=1, block_id="PB-FOCUSED"):
        self._bind_active_contract(step_row)
        policy = db.active_question_usage_policy(self.conn, step_row["question_id"])
        self.assertIsNotNone(policy)
        context = question_usage.context_for_step(
            policy,
            purpose="practice",
            purpose_role="consolidation",
            block_id=block_id,
            block_index=index,
            practice_family=policy["default_practice_family"],
            practice_role=policy["allowed_practice_roles"][0],
        )
        self.conn.execute(
            """
            update flow_step_usage_contexts
            set purpose = ?, purpose_role = ?, practice_family = ?, practice_role = ?,
                hint_policy = ?, mastery_evidence_weight = ?, instability_signal_weight = ?,
                mastery_update_eligible = ?, mastery_state_ceiling = ?,
                requires_diagnostic_confirmation = ?, block_id = ?, block_index = ?,
                structure_fingerprint = ?, context_digest_sha256 = ?, raw_json = ?
            where flow_step_id = ?
            """,
            (
                context["purpose"],
                context["purpose_role"],
                context["practice_family"],
                context["practice_role"],
                context["hint_policy"],
                context["mastery_evidence_weight"],
                context["instability_signal_weight"],
                1 if context["mastery_update_eligible"] else 0,
                context["mastery_state_ceiling"],
                1 if context["requires_diagnostic_confirmation"] else 0,
                context["block_id"],
                context["block_index"],
                context["structure_fingerprint"],
                question_usage.context_digest(context),
                db.json_dump(context),
                step_row["id"],
            ),
        )
        reason = db.json_load(step_row.get("selection_reason_json"), {})
        mini_group = dict(reason.get("mini_group") or {})
        mini_group.update(
            {
                "schema_version": daily_runtime.MINI_GROUP_METADATA_VERSION,
                "id": block_id,
                "role": "practice_adaptive_block",
                "index": index,
                "size": size,
                "defer_analysis_until_group_end": True,
                "usage_context": context,
            }
        )
        reason["mini_group"] = mini_group
        self.conn.execute(
            "update flow_steps set selection_reason_json = ? where id = ?",
            (db.json_dump(reason), step_row["id"]),
        )
        self.conn.execute(
            "update daily_flows set assessment_policy_version = 'v5.1' where id = ?",
            (step_row["flow_id"],),
        )
        self.conn.commit()
        return context

    def _bind_active_contract(self, step_row):
        question = db.get_question(self.conn, step_row["question_id"])
        contract = assessment_store.active_contract_for_question(
            self.conn,
            question["id"],
            question["item_version"],
        )
        self.assertIsNotNone(contract)
        assessment_store.bind_contract_to_flow_step(self.conn, step_row["id"], contract)
        return contract

    def _record_practice_attempt(self, step_row, *, result, answer):
        flow = dict(self.runtime._flow_by_id(step_row["flow_id"]))
        attempt_id = db.record_attempt(
            self.conn,
            session_id=flow["legacy_session_id"],
            question_id=step_row["question_id"],
            node_id=step_row["node_id"],
            result="submitted",
            score_points=0,
            max_points=2,
            error_tags=[],
            answer_raw=answer,
            parent_note="focused practice usage fixture",
            grading_status="pending_review",
            question_bank_version=step_row["question_bank_version"],
            commit=False,
        )
        self.conn.execute(
            """
            update attempts
            set flow_step_id = ?, graph_version = ?, attempt_version = 1,
                analysis_version = 1, analysis_status = 'valid',
                client_idempotency_key = ?, answer_source = 'v3_text'
            where id = ?
            """,
            (
                step_row["id"],
                step_row["graph_version"],
                f"practice-fixture-{attempt_id}",
                attempt_id,
            ),
        )
        db.record_attempt_usage_context_snapshot(
            self.conn,
            attempt_id=attempt_id,
            flow_step_id=step_row["id"],
            commit=False,
        )
        self.conn.commit()
        return self._mark_attempt_graded(attempt_id, result=result)

    def _typed_payload(self, state, *, key, answer="先写关系，再计算并检查。"):
        step = state["current_step"]
        return {
            "step_handle": step["step_handle"],
            "position": step["position"],
            "client_idempotency_key": key,
            "answer_text": answer,
        }

    def _submit_payload(self, payload):
        command = daily_runtime.CurrentStepSubmission.from_payload(payload)
        return self.runtime.persist_child_response(command)

    def _attempt_for_key(self, key):
        row = self.conn.execute(
            "select * from attempts where client_idempotency_key = ?",
            (key,),
        ).fetchone()
        self.assertIsNotNone(row)
        return db.attempt_row_to_dict(row)

    def _usable_validation(self, attempt_id):
        return evidence_gate.EvidenceValidationResult(
            validation_id=f"EV-{attempt_id}",
            gate_status="passed",
            predicate=evidence_gate.EvidencePredicateResult(
                usable=True,
                projection_status="usable",
                failed_fields=(),
                report_label="confirmed",
            ),
        )

    def _mark_attempt_graded(self, attempt_id, *, result):
        self.conn.execute(
            """
            update attempts
            set result = ?, grading_status = 'graded', analysis_status = 'valid',
                analysis_version = 1, explanation_score = ?, answer_analysis_json = ?
            where id = ?
            """,
            (
                result,
                2 if result == "correct" else 0,
                db.json_dump(
                    {
                        "evaluation_support": {
                            "reasoning_soundness": "sound" if result == "correct" else "unsound",
                            "dominant_gap_dimensions": [] if result == "correct" else ["symbols_units"],
                        }
                    }
                ),
                attempt_id,
            ),
        )
        self.conn.commit()
        return db.get_attempt(self.conn, attempt_id)

    def _confirmed_handwriting_payload(
        self,
        *,
        key,
        answer="-3",
        recognition_step_revision=None,
        recognition_media_bytes=None,
        critical_token_uncertainties=None,
    ):
        self.runtime.project_root = Path(self.tmpdir.name)
        image_bytes = b"\x89PNG\r\n\x1a\nhandwriting-focused"
        actual_sha = hashlib.sha256(image_bytes).hexdigest()
        recognition_bytes = recognition_media_bytes or image_bytes
        step_row = self._step_row()
        run = db.record_media_recognition_run(
            self.conn,
            flow_step_id=step_row["id"],
            step_revision=(
                int(step_row.get("step_revision") or 1)
                if recognition_step_revision is None
                else int(recognition_step_revision)
            ),
            question_id=step_row["question_id"],
            input_mode="handwriting",
            media_sha256=hashlib.sha256(recognition_bytes).hexdigest(),
            media_byte_size=len(recognition_bytes),
            media_version=multimodal_evidence.MEDIA_VERSION,
            content_type="image/png",
            recognizer_version=multimodal_evidence.HANDWRITING_RECOGNIZER_VERSION,
            recognition_status="usable",
            provider_mode="recorded_model",
            recognition_source="recorded_ocr_fixture",
            route_digest_sha256="r" * 64,
            recognized_text=answer,
            critical_token_uncertainties=critical_token_uncertainties or [],
            recognition_confidence=0.96,
            commit=True,
        )
        payload = self._typed_payload(self.started, key=key, answer=answer)
        payload.update(
            {
                "handwriting_image_data_url": self._data_url("image/png", image_bytes),
                "handwriting_image_name": "answer.png",
                "input_evidence": {
                    "schema_version": multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION,
                    "input_mode": "handwriting",
                    "recognition_status": "confirmed",
                    "recognition_handle": run["id"],
                    "recognized_text": answer,
                    "recognition_confidence": 0.96,
                    "critical_token_uncertainties": critical_token_uncertainties or [],
                    "media_version": multimodal_evidence.MEDIA_VERSION,
                    "child_confirmed": True,
                    "child_confirmed_text": answer,
                    "client_corrections": [],
                },
            }
        )
        return payload, actual_sha, run

    def _confirmed_browser_voice_payload(
        self,
        *,
        state=None,
        key,
        answer="负三",
    ):
        self.runtime.project_root = Path(self.tmpdir.name)
        audio = b"\x1aE\xdf\xa3browser-transcript-" + key.encode("utf-8")
        step_row = self._step_row(state)
        run = db.record_media_recognition_run(
            self.conn,
            flow_step_id=step_row["id"],
            step_revision=int(step_row["step_revision"] or 1),
            question_id=step_row["question_id"],
            input_mode="voice",
            media_sha256=hashlib.sha256(audio).hexdigest(),
            media_byte_size=len(audio),
            media_version=multimodal_evidence.MEDIA_VERSION,
            content_type="audio/webm",
            recognizer_version=multimodal_evidence.VOICE_RECOGNIZER_VERSION,
            recognition_status="usable",
            provider_mode="recorded_browser_recognition",
            recognition_source="browser_speech_recognition",
            route_digest_sha256="r" * 64,
            recognized_text=answer,
            recognition_confidence=0.88,
            commit=True,
        )
        payload = self._typed_payload(state or self.started, key=key, answer=answer)
        payload.update(
            {
                "voice_audio_data_url": self._data_url("audio/webm", audio),
                "voice_audio_name": "answer.webm",
                "input_evidence": {
                    "schema_version": multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION,
                    "input_mode": "voice",
                    "recognition_status": "confirmed",
                    "recognition_handle": run["id"],
                    "recognized_text": answer,
                    "recognition_confidence": 0.88,
                    "media_version": multimodal_evidence.MEDIA_VERSION,
                    "child_confirmed": True,
                    "child_confirmed_text": answer,
                },
            }
        )
        return payload, run

    def _configured_answer_route(self):
        return model_router.ModelRoute(
            agent_key="answer_analysis_agent",
            task="answer_review",
            provider="openai",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://unit.invalid/v1",
            api_key="test-only",
            timeout_seconds=30,
            model_params={"temperature": 0},
        )

    def _assert_separate_writer_available(self):
        probe = db.connect(self.db_path)
        try:
            probe.execute("pragma busy_timeout = 50")
            probe.execute("begin immediate")
            probe.rollback()
        finally:
            probe.close()

    def _structured_group_result(self, job):
        payload = db.json_load(job["payload_json"], {})
        output_items = []
        for group_item in payload["group_items"]:
            contract = assessment_store.bound_active_contract_for_flow_step(
                self.conn,
                group_item["step_id"],
            )
            output_items.append(
                {
                    "attempt_id": group_item["attempt_id"],
                    "criteria": [
                        {
                            "criterion_key": point["key"],
                            "status": "met",
                            "child_evidence": "结构化测试证据。",
                            "reason": "关键得分点成立。",
                        }
                        for point in contract["score_points"]
                    ],
                    "answer_gap": "没有关键差距。",
                    "improvement_direction": ["继续检查符号和关系。"],
                    "expression_judgment": "按数学意图判断。",
                    "teaching_explanation": "先确认关系，再检查符号。",
                    "confidence": 0.95,
                }
            )
        return model_router.StructuredJSONResult(
            value={
                "schema_version": daily_runtime.GROUP_ANSWER_REVIEW_SCHEMA_VERSION,
                "items": output_items,
                "confidence": 0.95,
            },
            mode="json_schema",
            raw_response={"fixture": "p1-group-lineage"},
            endpoint="unit://structured-json",
        )

    def _enqueue_single_item_group_job(self, *, key="group-lineage", answer="-3"):
        step_row = self._step_row()
        self._set_practice_context(step_row, size=2)
        state = self._submit_payload(self._typed_payload(self.started, key=key, answer=answer))
        if state["child_state"] == "current_step":
            self._submit_payload(
                self._typed_payload(state, key=f"{key}-group-peer", answer="同组补充答案")
            )
        attempt = self._attempt_for_key(key)
        job = self.conn.execute(
            """
            select * from background_jobs
            where flow_id = ? and job_type = 'group_answer_analysis'
            order by created_at desc, id desc limit 1
            """,
            (step_row["flow_id"],),
        ).fetchone()
        self.assertIsNotNone(job)
        return step_row, attempt, dict(job)

    def _enqueue_single_answer_job(self, *, key="single-lineage", answer="-3"):
        step_row = self._step_row()
        contract = self._bind_active_contract(step_row)
        selection_reason = db.json_load(step_row.get("selection_reason_json"), {})
        selection_reason.pop("mini_group", None)
        self.conn.execute(
            "update flow_steps set selection_reason_json = ? where id = ?",
            (db.json_dump(selection_reason), step_row["id"]),
        )
        self.conn.execute(
            "update daily_flows set assessment_policy_version = 'v5.1' where id = ?",
            (step_row["flow_id"],),
        )
        self.conn.commit()
        self._submit_payload(self._typed_payload(self.started, key=key, answer=answer))
        attempt = self._attempt_for_key(key)
        job = self.conn.execute(
            """
            select * from background_jobs
            where flow_id = ? and job_type = 'answer_analysis'
            order by created_at desc, id desc limit 1
            """,
            (step_row["flow_id"],),
        ).fetchone()
        self.assertIsNotNone(job)
        return step_row, attempt, contract, dict(job)

    def _accepted_single_answer_envelope(self, contract):
        expected = internal_agents.load_v5_contract_for_agent("answer_analysis_agent")
        return semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.95,
            output={
                "schema_version": expected["response_schema_version"],
                "criteria": [
                    {
                        "criterion_key": point["key"],
                        "status": "met",
                        "child_evidence": "结构化测试证据。",
                        "reason": "关键得分点成立。",
                    }
                    for point in contract["score_points"]
                ],
                "answer_gap": "没有关键差距。",
                "improvement_direction": ["继续检查符号和关系。"],
                "expression_judgment": "按数学意图判断。",
                "teaching_explanation": "先确认关系，再检查符号。",
                "confidence": 0.95,
            },
            validation_errors=(),
            error_reason="",
            route_meta={"fixture": "single-answer-fence"},
            prompt_version_id=expected["prompt_version_id"],
            response_schema_version=expected["response_schema_version"],
        )

    def _reclaim_job_during_model_call(self, job_id, result):
        self.conn.execute(
            """
            update background_jobs
            set claim_generation = claim_generation + 1,
                claim_token = 'replacement-claim-token',
                lease_expires_at = '2099-12-31T23:59:59.000000',
                status = 'running'
            where id = ?
            """,
            (job_id,),
        )
        self.conn.commit()
        return result

    def _enqueue_photo_single_answer_job(self, *, key):
        self.runtime.project_root = Path(self.tmpdir.name)
        step_row = self._step_row()
        self._set_practice_context(step_row, size=2)
        package = db.json_load(step_row.get("prompt_package_json"), {})
        package.update(
            {
                "answer_input_mode": "photo",
                "allowed_response_modes": ["photo", "stuck"],
                "upload_enabled": True,
            }
        )
        self.conn.execute(
            "update flow_steps set prompt_package_json = ? where id = ?",
            (db.json_dump(package), step_row["id"]),
        )
        self.conn.commit()
        photo_bytes = b"\x89PNG\r\n\x1a\nphoto-answer-focused"
        payload = self._typed_payload(self.started, key=key, answer="")
        payload.update(
            {
                "answer_photo_data_url": self._data_url("image/png", photo_bytes),
                "answer_photo_name": "paper.png",
            }
        )
        state = self._submit_payload(payload)
        self.assertEqual("analyzing", state["child_state"])
        attempt = self._attempt_for_key(key)
        job = self.conn.execute(
            """
            select * from background_jobs
            where flow_id = ? and job_type = 'answer_analysis'
            order by created_at desc, id desc limit 1
            """,
            (step_row["flow_id"],),
        ).fetchone()
        self.assertIsNotNone(job)
        group_job_count = self.conn.execute(
            "select count(*) from background_jobs where flow_id = ? and job_type = 'group_answer_analysis'",
            (step_row["flow_id"],),
        ).fetchone()[0]
        self.assertEqual(0, group_job_count)
        return step_row, attempt, self._bind_active_contract(step_row), dict(job)

    def _assert_group_rejected_before_model(self, job, *, expected_reason):
        route = self._configured_answer_route()
        with mock.patch.object(model_router, "answer_analysis_route", return_value=route), mock.patch.object(
            model_router,
            "call_structured_json",
        ) as model_call:
            result = self.runtime._handle_group_answer_analysis_job(job)
        model_call.assert_not_called()
        self.assertEqual("blocked", result["job_status"], result)
        self.assertEqual(expected_reason, result["reason"], result)

    def test_schema_has_real_attempt_evidence_revision_backfill(self):
        self.assertTrue(
            callable(getattr(db, "_backfill_attempt_evidence_revisions", None)),
            "db.init_schema must not call an undefined evidence-revision migration hook",
        )

    def test_clean_database_init_and_usage_policy_backfill_have_valid_insert_arity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "clean-init.sqlite"
            conn = db.connect(path)
            try:
                db.init_schema(conn)
                db.seed_from_assets(conn, PROJECT_ROOT)
                test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
                question_count = conn.execute("select count(*) from question_items").fetchone()[0]
                self.assertGreater(question_count, 0)
                conn.execute("delete from question_usage_policies")
                conn.commit()

                db.init_schema(conn)

                policy_count = conn.execute("select count(*) from question_usage_policies").fetchone()[0]
                self.assertEqual(question_count, policy_count)
            finally:
                conn.close()

    def test_submission_persists_canonical_attempt_evidence_revision(self):
        self._submit_payload(self._typed_payload(self.started, key="canonical-evidence-revision"))
        attempt = self._attempt_for_key("canonical-evidence-revision")
        revisions = self.conn.execute(
            "select * from attempt_evidence_revisions where attempt_id = ? order by revision_number",
            (attempt["id"],),
        ).fetchall()
        self.assertEqual(1, len(revisions))
        self.assertEqual(1, revisions[0]["revision_number"])
        self.assertEqual("submission", revisions[0]["revision_kind"])

    def test_direct_typed_submission_normalizes_missing_input_evidence(self):
        command = daily_runtime.CurrentStepSubmission(
            step_handle=self.step["step_handle"],
            position=self.step["position"],
            client_idempotency_key="direct-empty-input-evidence",
            answer_text="先写关系，再计算。",
            input_evidence={},
        )

        self.runtime.persist_child_response(command)

        attempt = self._attempt_for_key("direct-empty-input-evidence")
        revision = db.latest_attempt_evidence_revision(self.conn, attempt["id"])
        self.assertEqual("typed", revision["input_mode"])
        self.assertEqual(
            multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION,
            revision["schema_version"],
        )

    def test_direct_voice_submission_without_lineage_still_fails_closed(self):
        command = daily_runtime.CurrentStepSubmission(
            step_handle=self.step["step_handle"],
            position=self.step["position"],
            client_idempotency_key="direct-voice-missing-lineage",
            answer_text="负三",
            voice_audio_data_url=self._data_url("audio/webm", b"missing-lineage"),
            input_evidence={},
        )

        with self.assertRaises(daily_runtime.ChildSafeRuntimeError):
            self.runtime.persist_child_response(command)

        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempts where client_idempotency_key = ?",
            ("direct-voice-missing-lineage",),
        ).fetchone()[0])

    def test_question_allowed_purposes_and_actual_usage_are_frozen_on_step_and_attempt(self):
        step_row = self._step_row()
        policy = db.active_question_usage_policy(self.conn, step_row["question_id"])
        step_context = db.flow_step_usage_context(self.conn, step_row["id"])
        self.assertIn(step_context["purpose"], policy["allowed_purposes"])
        self.assertEqual(
            policy["policy_digest_sha256"],
            step_context["raw"]["question_usage_policy_digest_sha256"],
        )

        self._submit_payload(self._typed_payload(self.started, key="usage-freeze"))
        attempt = self._attempt_for_key("usage-freeze")
        snapshot_count = self.conn.execute(
            "select count(*) from attempt_usage_contexts where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0]
        self.assertEqual(1, snapshot_count, "submission must freeze actual usage on the attempt")
        snapshot = db.attempt_usage_context(self.conn, attempt["id"])
        self.assertEqual(step_context["context_digest_sha256"], snapshot["context_digest_sha256"])
        for key, value in step_context["raw"].items():
            self.assertEqual(value, snapshot["snapshot"][key])
        self.assertEqual(step_row["question_item_version"], snapshot["snapshot"]["question_item_version"])
        self.assertIn("actual_hint_exposed", snapshot["snapshot"])

        alternate = question_usage.context_for_step(
            policy,
            purpose="practice",
            purpose_role="consolidation",
            block_id="PB-TAMPER",
            block_index=1,
            practice_family=policy["default_practice_family"],
            practice_role=policy["allowed_practice_roles"][0],
        )
        with self.assertRaisesRegex(ValueError, "immutable"):
            db.record_flow_step_usage_context(
                self.conn,
                flow_step_id=step_row["id"],
                question_id=step_row["question_id"],
                context=alternate,
                item_version=step_row["question_item_version"],
            )

    def test_step_usage_policy_binds_exact_question_item_version(self):
        step_row = self._step_row()
        bound = self.conn.execute(
            """
            select qup.item_version
            from flow_step_usage_contexts suc
            join question_usage_policies qup on qup.id = suc.question_usage_policy_id
            where suc.flow_step_id = ?
            """,
            (step_row["id"],),
        ).fetchone()
        self.assertIsNotNone(bound)
        self.assertEqual(step_row["question_item_version"], bound["item_version"])
        context = db.flow_step_usage_context(self.conn, step_row["id"])["raw"]
        with self.assertRaisesRegex(ValueError, "exact item version"):
            db.record_flow_step_usage_context(
                self.conn,
                flow_step_id=step_row["id"],
                question_id=step_row["question_id"],
                context=context,
                item_version="tampered-item-version",
            )

    def test_missing_attempt_usage_snapshot_fails_closed_before_mastery(self):
        self._submit_payload(self._typed_payload(self.started, key="missing-usage-snapshot"))
        attempt = self._attempt_for_key("missing-usage-snapshot")
        graded = self._mark_attempt_graded(attempt["id"], result="wrong")
        self.conn.execute("delete from attempt_usage_contexts where attempt_id = ?", (attempt["id"],))
        self.conn.commit()
        before = self.conn.execute("select count(*) from mastery_decisions").fetchone()[0]

        result = self.runtime._record_evaluation_update(
            attempt=graded,
            validation=self._usable_validation(graded["id"]),
            provider_mode="deterministic_runtime",
            evaluation_output={"mastery_recommendation": "weak"},
        )

        self.assertFalse(result["applied"], result)
        self.assertEqual(before, self.conn.execute("select count(*) from mastery_decisions").fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from learner_node_status where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])

    def test_correct_practice_attempt_does_not_write_mastery(self):
        step_row = self._step_row()
        self._set_practice_context(step_row)
        graded = self._record_practice_attempt(
            step_row,
            result="correct",
            answer="先写关系，再计算并检查。",
        )
        before = self.conn.execute("select count(*) from mastery_decisions").fetchone()[0]

        result = self.runtime._record_evaluation_update(
            attempt=graded,
            validation=self._usable_validation(graded["id"]),
            provider_mode="deterministic_runtime",
            evaluation_output={"mastery_recommendation": "likely_stable"},
        )

        self.assertFalse(result["applied"])
        self.assertTrue(result["non_mastery_evidence"])
        self.assertNotIn("diagnostic_reconfirmation_signal", result)
        self.assertEqual(before, self.conn.execute("select count(*) from mastery_decisions").fetchone()[0])

    def test_wrong_practice_attempt_only_emits_structured_diagnostic_reconfirmation(self):
        step_row = self._step_row()
        self._set_practice_context(step_row)
        graded = self._record_practice_attempt(step_row, result="wrong", answer="3")

        result = self.runtime._record_evaluation_update(
            attempt=graded,
            validation=self._usable_validation(graded["id"]),
            provider_mode="deterministic_runtime",
            evaluation_output={"mastery_recommendation": "weak"},
        )

        self.assertFalse(result["applied"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
            (f"%{graded['id']}%",),
        ).fetchone()[0])
        signal = result["diagnostic_reconfirmation_signal"]
        self.assertEqual(
            {
                "required": True,
                "source_attempt_id": graded["id"],
                "node_id": graded["node_id"],
            },
            signal,
        )

    def test_adaptive_practice_block_freezes_minimum_target_and_maximum(self):
        step_row = self._step_row()
        context = self._set_practice_context(step_row)
        flow = dict(self.runtime._flow_by_id(step_row["flow_id"]))
        reason = self.runtime._mini_group_selection_reason(
            {},
            flow=flow,
            step_type="question",
            group_role="practice_adaptive_block",
            target_node_id=step_row["node_id"],
            question_id=step_row["question_id"],
            requested_usage=context,
        )

        self.assertIn("adaptive_block", reason["mini_group"])
        adaptive = reason["mini_group"]["adaptive_block"]
        self.assertEqual(2, adaptive["minimum_size"])
        self.assertEqual(3, adaptive["target_size"])
        self.assertEqual(5, adaptive["maximum_size"])

    def test_adaptive_practice_block_runs_first_group_analysis_after_two_answers(self):
        first_row = self._step_row()
        self._set_practice_context(first_row, size=3)
        second_state = self._submit_payload(
            self._typed_payload(self.started, key="adaptive-first", answer="第一题答案")
        )
        self.assertEqual(
            "current_step",
            second_state["child_state"],
            "practice block must not analyze after only one answer",
        )
        self._submit_payload(
            self._typed_payload(second_state, key="adaptive-second", answer="第二题答案")
        )

        jobs = self.conn.execute(
            "select * from background_jobs where flow_id = ? and job_type = 'group_answer_analysis'",
            (first_row["flow_id"],),
        ).fetchall()
        self.assertEqual(1, len(jobs))
        payload = db.json_load(jobs[0]["payload_json"], {})
        self.assertEqual(2, payload["mini_group_size"])
        self.assertEqual(2, len(payload["group_items"]))
        unanswered = self.conn.execute(
            """
            select count(*) from flow_steps
            where flow_id = ? and step_type = 'question'
              and status in ('selected','displayed','planned')
            """,
            (first_row["flow_id"],),
        ).fetchone()[0]
        self.assertEqual(0, unanswered, "第三题必须等两题组分析后再决定是否追加")

    def test_mixed_two_item_group_adds_at_most_one_unique_question(self):
        first_row = self._step_row()
        self._set_practice_context(first_row, size=2)
        second_state = self._submit_payload(
            self._typed_payload(self.started, key="mixed-first", answer="第一题答案")
        )
        self.assertEqual(
            "current_step",
            second_state["child_state"],
            "mixed outcome requires two answered questions before group analysis",
        )
        self._submit_payload(
            self._typed_payload(second_state, key="mixed-second", answer="第二题答案")
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where flow_id = ? and job_type = 'group_answer_analysis'",
            (first_row["flow_id"],),
        ).fetchone())
        payload = db.json_load(job["payload_json"], {})
        output_items = []
        for item_index, group_item in enumerate(payload["group_items"]):
            contract = assessment_store.bound_active_contract_for_flow_step(
                self.conn,
                group_item["step_id"],
            )
            output_items.append(
                {
                    "attempt_id": group_item["attempt_id"],
                    "criteria": [
                        {
                            "criterion_key": point["key"],
                            "status": "met" if item_index == 0 else "not_met",
                            "child_evidence": "结构化测试证据。",
                            "reason": "第一题通过，第二题需要确认。",
                        }
                        for point in contract["score_points"]
                    ],
                    "answer_gap": "第二题存在待确认差距。" if item_index else "没有关键差距。",
                    "improvement_direction": ["再用一道近迁移题确认。"],
                    "expression_judgment": "按数学意图判断。",
                    "teaching_explanation": "先确认关系，再检查符号。",
                    "confidence": 0.95,
                }
            )
        structured = model_router.StructuredJSONResult(
            value={
                "schema_version": daily_runtime.GROUP_ANSWER_REVIEW_SCHEMA_VERSION,
                "items": output_items,
                "confidence": 0.95,
            },
            mode="json_schema",
            raw_response={"fixture": "practice-mixed-two-item"},
            endpoint="unit://structured-json",
        )
        route = model_router.ModelRoute(
            agent_key="answer_analysis_agent",
            task="answer_review",
            provider="openai",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://unit.invalid/v1",
            api_key="test-only",
            timeout_seconds=30,
            model_params={"temperature": 0},
        )

        with mock.patch.object(model_router, "answer_analysis_route", return_value=route), mock.patch.object(
            model_router,
            "call_structured_json",
            return_value=structured,
        ):
            result = self.runtime._handle_group_answer_analysis_job(job)

        self.assertEqual("succeeded", result["job_status"], result)
        state = self.runtime.project_child_state(self.runtime._flow_by_id(first_row["flow_id"]))
        if state["child_state"] == "current_step":
            third_row = self._step_row(state)
            third_meta = self.runtime._mini_group_meta(third_row)
            self.assertEqual("PB-FOCUSED", third_meta["id"])
            self.assertEqual(3, third_meta["index"])
        else:
            self.assertEqual(
                "assessment_feedback",
                state["child_state"],
                "when no unused mathematical instance remains, the group must stop instead of repeating a question",
            )
        question_rows = self.conn.execute(
            """
            select question_id
            from flow_steps
            where flow_id = ? and step_type = 'question'
            order by position
            """,
            (first_row["flow_id"],),
        ).fetchall()
        problem_instance_ids = [
            str(db.get_question(self.conn, row["question_id"]).get("problem_instance_id") or "")
            for row in question_rows
        ]
        self.assertIn(len(problem_instance_ids), {2, 3})
        self.assertTrue(all(problem_instance_ids))
        self.assertEqual(
            len(problem_instance_ids),
            len(set(problem_instance_ids)),
            "adaptive evidence must use three distinct mathematical problem instances",
        )
        self.assertEqual(1 if len(problem_instance_ids) == 3 else 0, self.conn.execute(
            """
            select count(*) from flow_steps
            where flow_id = ? and step_type = 'question'
              and status in ('selected','displayed','planned')
            """,
            (first_row["flow_id"],),
        ).fetchone()[0])

    def test_mixed_group_with_no_unused_problem_instance_finishes_without_duplicate_or_orphan(self):
        first_row = self._step_row()
        self._set_practice_context(first_row, size=2)
        second_state = self._submit_payload(
            self._typed_payload(self.started, key="saturated-first", answer="第一题答案")
        )
        self._submit_payload(
            self._typed_payload(second_state, key="saturated-second", answer="第二题答案")
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where flow_id = ? and job_type = 'group_answer_analysis'",
            (first_row["flow_id"],),
        ).fetchone())
        payload = db.json_load(job["payload_json"], {})
        output_items = []
        for item_index, group_item in enumerate(payload["group_items"]):
            contract = assessment_store.bound_active_contract_for_flow_step(
                self.conn,
                group_item["step_id"],
            )
            output_items.append(
                {
                    "attempt_id": group_item["attempt_id"],
                    "criteria": [
                        {
                            "criterion_key": point["key"],
                            "status": "met" if item_index == 0 else "not_met",
                            "child_evidence": "结构化测试证据。",
                            "reason": "第一题通过，第二题需要确认。",
                        }
                        for point in contract["score_points"]
                    ],
                    "answer_gap": "第二题存在待确认差距。" if item_index else "没有关键差距。",
                    "improvement_direction": ["再用一道近迁移题确认。"],
                    "expression_judgment": "按数学意图判断。",
                    "teaching_explanation": "先确认关系，再检查符号。",
                    "confidence": 0.95,
                }
            )
        structured = model_router.StructuredJSONResult(
            value={
                "schema_version": daily_runtime.GROUP_ANSWER_REVIEW_SCHEMA_VERSION,
                "items": output_items,
                "confidence": 0.95,
            },
            mode="json_schema",
            raw_response={"fixture": "practice-saturated-two-item"},
            endpoint="unit://structured-json",
        )
        route = model_router.ModelRoute(
            agent_key="answer_analysis_agent",
            task="answer_review",
            provider="openai",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://unit.invalid/v1",
            api_key="test-only",
            timeout_seconds=30,
            model_params={"temperature": 0},
        )

        with mock.patch.object(model_router, "answer_analysis_route", return_value=route), mock.patch.object(
            model_router,
            "call_structured_json",
            return_value=structured,
        ), mock.patch.object(
            self.runtime,
            "_select_question_for_node",
            return_value=None,
        ), mock.patch.object(
            self.runtime,
            "_next_selection_after_attempt",
            return_value=None,
        ):
            result = self.runtime.process_next_background_job(
                worker_id="saturated-group-worker",
                flow_id=first_row["flow_id"],
            )

        self.assertEqual("succeeded", result["job_status"], result)
        question_rows = self.conn.execute(
            """
            select question_id
            from flow_steps
            where flow_id = ? and step_type = 'question'
            order by position
            """,
            (first_row["flow_id"],),
        ).fetchall()
        problem_instance_ids = [
            str(db.get_question(self.conn, row["question_id"]).get("problem_instance_id") or "")
            for row in question_rows
        ]
        self.assertEqual(2, len(problem_instance_ids))
        self.assertEqual(2, len(set(problem_instance_ids)))
        current_step = self.conn.execute(
            """
            select s.step_type, s.status
            from daily_flows f
            join flow_steps s on s.id = f.current_step_id
            where f.id = ?
            """,
            (first_row["flow_id"],),
        ).fetchone()
        self.assertEqual("assessment_feedback", current_step["step_type"])
        self.assertNotEqual("analyzing", current_step["status"])
        stored_job = self.conn.execute(
            "select status from background_jobs where id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual("succeeded", stored_job["status"])

    def test_group_with_unverified_voice_only_requests_same_node_diagnostic_confirmation(self):
        first_row = self._step_row()
        self._set_practice_context(first_row, size=2)
        voice_payload, _ = self._confirmed_browser_voice_payload(
            key="group-browser-voice-first",
            answer="负三",
        )
        second_state = self._submit_payload(voice_payload)
        self._submit_payload(
            self._typed_payload(
                second_state,
                key="group-browser-voice-second",
                answer="第二题答案",
            )
        )
        job = dict(self.conn.execute(
            "select * from background_jobs where flow_id = ? and job_type = 'group_answer_analysis'",
            (first_row["flow_id"],),
        ).fetchone())
        payload = db.json_load(job["payload_json"], {})
        output_items = []
        for item_index, group_item in enumerate(payload["group_items"]):
            contract = assessment_store.bound_active_contract_for_flow_step(
                self.conn,
                group_item["step_id"],
            )
            output_items.append(
                {
                    "attempt_id": group_item["attempt_id"],
                    "criteria": [
                        {
                            "criterion_key": point["key"],
                            "status": "not_met" if item_index == 0 else "met",
                            "child_evidence": "结构化测试证据。",
                            "reason": "语音题需要可信复核。" if item_index == 0 else "关键得分点成立。",
                        }
                        for point in contract["score_points"]
                    ],
                    "answer_gap": "语音证据需要复核。" if item_index == 0 else "没有关键差距。",
                    "improvement_direction": ["用可信输入再确认一次。"],
                    "expression_judgment": "按数学意图判断。",
                    "teaching_explanation": "先确认关系，再检查符号。",
                    "confidence": 0.95,
                }
            )
        structured = model_router.StructuredJSONResult(
            value={
                "schema_version": daily_runtime.GROUP_ANSWER_REVIEW_SCHEMA_VERSION,
                "items": output_items,
                "confidence": 0.95,
            },
            mode="json_schema",
            raw_response={"fixture": "group-unverified-voice-planning"},
            endpoint="unit://structured-json",
        )

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            model_router,
            "call_structured_json",
            return_value=structured,
        ), mock.patch.object(
            self.runtime,
            "_select_question_for_node",
            return_value=None,
        ) as select_question, mock.patch.object(
            self.runtime.graph,
            "rollback_candidates",
            return_value=["M-PRE-OTHER-NODE"],
        ):
            result = self.runtime._handle_group_answer_analysis_job(job)

        self.assertEqual("succeeded", result["job_status"], result)
        self.assertEqual(1, select_question.call_count)
        args, kwargs = select_question.call_args
        self.assertEqual(first_row["node_id"], args[0])
        self.assertEqual("diagnostic", kwargs["required_purpose"])
        self.assertEqual("untrusted_evidence_reconfirmation", kwargs["selection_intent"])

    def test_stuck_interrupts_practice_block_immediately(self):
        first_row = self._step_row()
        self._set_practice_context(first_row, size=3)
        payload = self._typed_payload(self.started, key="practice-stuck", answer="我卡住了")
        payload["stuck"] = True
        state = self._submit_payload(payload)

        self.assertEqual("analyzing", state["child_state"])
        self.assertEqual("正在准备讲解", state["message"]["title"])
        self.assertIn("不需要等待模型判断", state["message"]["body"])
        attempt = self._attempt_for_key("practice-stuck")
        self.assertEqual("v3_stuck", attempt["answer_source"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempts where id = ? and grading_status = 'pending_review'",
            (attempt["id"],),
        ).fetchone()[0], "stuck interruption must not leave an orphan pending_review attempt")
        self.assertEqual(0, self.conn.execute(
            "select count(*) from background_jobs where flow_id = ? and job_type = 'group_answer_analysis'",
            (first_row["flow_id"],),
        ).fetchone()[0])

    def test_explicit_stuck_teaching_uses_the_current_question_first_step(self):
        first_row = self._step_row()
        question = db.get_question(self.conn, first_row["question_id"])
        payload = self._typed_payload(self.started, key="stuck-concrete-teaching", answer="")
        payload["stuck"] = True
        self._submit_payload(payload)

        with mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=AssertionError("explicit stuck must stay on the deterministic zero-model path"),
        ):
            result = self.runtime.process_next_background_job(
                worker_id="stuck-concrete-worker",
                flow_id=first_row["flow_id"],
            )

        self.assertEqual("succeeded", result["job_status"], result)
        state = self.runtime.project_child_state(self.runtime._flow_by_id(first_row["flow_id"]))
        self.assertEqual("teaching", state["child_state"])
        prompt = state["current_step"]["prompt"]
        first_step = str((question.get("solution_steps") or [""])[0]).strip()
        self.assertTrue(first_step)
        self.assertIn(first_step, prompt)
        self.assertNotIn("这一步的关键关系、步骤或检验还不够稳", prompt)

    def test_first_check_after_explicit_stuck_stays_on_the_same_node(self):
        first_row = self._step_row()
        payload = self._typed_payload(self.started, key="stuck-same-node-check", answer="")
        payload["stuck"] = True
        self._submit_payload(payload)
        self.runtime.process_next_background_job(
            worker_id="stuck-same-node-worker",
            flow_id=first_row["flow_id"],
        )
        teaching_state = self.runtime.project_child_state(
            self.runtime._flow_by_id(first_row["flow_id"])
        )
        teaching_step = teaching_state["current_step"]
        source_question = db.get_question(self.conn, first_row["question_id"])
        replacement = None
        for row in self.conn.execute(
            """
            select q.id as question_id, r.id as review_record_id
            from question_items q
            join question_review_records r on r.question_id = q.id
             and r.item_version = q.item_version and r.active_eligible = 1
            where q.node_id = ?
              and q.id <> ?
            order by q.id
            """,
            (
                first_row["node_id"],
                first_row["question_id"],
            ),
        ).fetchall():
            candidate = db.get_question(self.conn, row["question_id"])
            if candidate["problem_instance_id"] != source_question["problem_instance_id"]:
                replacement = row
                break
        self.assertIsNotNone(replacement)
        selected = {
            "action": "same_structure_retest",
            "reason": "教学后在同一知识点做一次不同结构的小检查。",
            "question": db.get_question(self.conn, replacement["question_id"]),
            "review_record_id": replacement["review_record_id"],
            "selection_reason": {"reason": "same_node_after_explicit_stuck"},
            "candidate_packet": {},
        }

        with mock.patch.object(
            self.runtime,
            "_next_selection_after_attempt",
            side_effect=AssertionError("explicit stuck has no semantic evidence for a prerequisite jump"),
        ), mock.patch.object(
            self.runtime,
            "_select_question_for_node",
            return_value=selected,
        ) as select_same_node:
            next_state = self.runtime.continue_current_step(
                step_handle=teaching_step["step_handle"],
                position=teaching_step["position"],
            )

        self.assertEqual(first_row["node_id"], select_same_node.call_args.args[0])
        self.assertEqual("current_step", next_state["child_state"])
        next_row = self._step_row(next_state)
        self.assertEqual(first_row["node_id"], next_row["node_id"])

    def test_stuck_on_second_practice_question_closes_prior_deferred_attempt(self):
        first_row = self._step_row()
        self._set_practice_context(first_row, size=3)
        second_state = self._submit_payload(
            self._typed_payload(self.started, key="practice-before-stuck", answer="第一题答案")
        )
        first_attempt = self._attempt_for_key("practice-before-stuck")

        stuck = self._typed_payload(second_state, key="practice-stuck-second", answer="我卡住了")
        stuck["stuck"] = True
        self._submit_payload(stuck)

        prior = db.get_attempt(self.conn, first_attempt["id"])
        self.assertNotEqual("pending_review", prior["grading_status"])
        self.assertEqual("invalidated", prior["evidence_status"])
        self.assertEqual("interrupted", prior["result"])
        self.assertEqual(0, self.conn.execute(
            """
            select count(*) from attempts a
            join flow_steps s on s.id = a.flow_step_id
            where s.flow_id = ? and a.grading_status = 'pending_review'
              and a.evidence_status = 'active'
            """,
            (first_row["flow_id"],),
        ).fetchone()[0])

    def test_unconfirmed_handwriting_and_voice_are_rejected_before_attempt_creation(self):
        for mode in ("handwriting", "voice"):
            with self.subTest(mode=mode):
                payload = self._typed_payload(self.started, key=f"unconfirmed-{mode}", answer="-3")
                payload["input_evidence"] = {
                    "schema_version": multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION,
                    "input_mode": mode,
                    "recognition": {
                        "status": "recognized",
                        "source": "recorded_test",
                        "text": "-3",
                        "confidence": 0.99,
                    },
                    "child_confirmed": False,
                    "child_confirmed_text": "",
                }
                with self.assertRaises(daily_runtime.ChildSafeRuntimeError):
                    daily_runtime.CurrentStepSubmission.from_payload(payload)
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempts where client_idempotency_key like 'unconfirmed-%'"
        ).fetchone()[0])

    def test_stale_recognition_handle_is_rejected_before_scoring(self):
        step_row = self._step_row()
        payload, _, _ = self._confirmed_handwriting_payload(
            key="stale-recognition-handle",
            recognition_step_revision=int(step_row.get("step_revision") or 1) + 1,
        )
        with self.assertRaises(daily_runtime.ChildSafeRuntimeError) as raised:
            self._submit_payload(payload)
        self.assertEqual(409, raised.exception.status)
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempts where client_idempotency_key = 'stale-recognition-handle'"
        ).fetchone()[0])

    def test_media_sha_mismatch_is_rejected_before_scoring(self):
        payload, actual_sha, run = self._confirmed_handwriting_payload(
            key="media-sha-mismatch",
            recognition_media_bytes=b"\x89PNG\r\n\x1a\ndifferent-media",
        )
        self.assertNotEqual(actual_sha, run["media_sha256"])
        with self.assertRaises(daily_runtime.ChildSafeRuntimeError) as raised:
            self._submit_payload(payload)
        self.assertEqual(409, raised.exception.status)
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempts where client_idempotency_key = 'media-sha-mismatch'"
        ).fetchone()[0])

    def test_critical_symbol_ambiguity_is_rejected_even_when_child_confirmed(self):
        uncertainties = [
            {"token": "-", "location": "答案开头", "reason": "可能是负号，也可能是划痕"}
        ]
        payload, _, _ = self._confirmed_handwriting_payload(
            key="critical-symbol-ambiguous",
            critical_token_uncertainties=uncertainties,
        )
        with self.assertRaises(daily_runtime.ChildSafeRuntimeError):
            self._submit_payload(payload)
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempts where client_idempotency_key = 'critical-symbol-ambiguous'"
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute("select count(*) from mastery_decisions").fetchone()[0])

    def test_idempotency_key_reuses_same_digest_without_mutation(self):
        first_payload = self._typed_payload(self.started, key="digest-idempotency", answer="-3")
        first_state = self._submit_payload(first_payload)
        first_attempt = self._attempt_for_key("digest-idempotency")
        first_digest = first_attempt["evidence_digest_sha256"]

        replay_state = self._submit_payload(copy.deepcopy(first_payload))
        self.assertEqual(first_state["child_state"], replay_state["child_state"])
        self.assertEqual(1, self.conn.execute(
            "select count(*) from attempts where client_idempotency_key = 'digest-idempotency'"
        ).fetchone()[0])
        self.assertEqual(first_digest, self._attempt_for_key("digest-idempotency")["evidence_digest_sha256"])

    def test_idempotency_key_rejects_different_digest_with_409(self):
        first_payload = self._typed_payload(self.started, key="digest-conflict", answer="-3")
        self._submit_payload(first_payload)
        attempt = self._attempt_for_key("digest-conflict")
        self.conn.execute(
            "update flow_steps set status = 'completed' where id = ?",
            (attempt["flow_step_id"],),
        )
        self.conn.commit()

        changed = copy.deepcopy(first_payload)
        changed["answer_text"] = "3"
        with self.assertRaises(daily_runtime.ChildSafeRuntimeError) as raised:
            self._submit_payload(changed)
        self.assertEqual(409, raised.exception.status)
        self.assertEqual(1, self.conn.execute(
            "select count(*) from attempts where client_idempotency_key = 'digest-conflict'"
        ).fetchone()[0])

    def test_completed_flow_http_replay_requires_same_submission_digest_without_db_mutation(self):
        payload = self._typed_payload(
            self.started,
            key="completed-flow-http-replay",
            answer="-3",
        )
        flow_id = self._step_row()["flow_id"]
        self._submit_payload(payload)
        self._attempt_for_key("completed-flow-http-replay")
        summary = self.runtime.complete_summary(flow_id)
        self.assertEqual("summary", summary["child_state"])

        def snapshot():
            flow = dict(self.runtime._flow_by_id(flow_id))
            steps = [
                tuple(row)
                for row in self.conn.execute(
                    """
                    select id, status, attempt_id, step_revision, updated_at
                    from flow_steps where flow_id = ? order by position, id
                    """,
                    (flow_id,),
                ).fetchall()
            ]
            counts = tuple(
                self.conn.execute(f"select count(*) from {table}").fetchone()[0]
                for table in (
                    "attempts",
                    "attempt_evidence_revisions",
                    "attempt_assessments",
                    "background_jobs",
                    "next_step_decisions",
                    "daily_summaries",
                )
            )
            return (
                flow["status"],
                flow["summary_id"],
                flow["current_step_id"],
                flow["flow_revision"],
                steps,
                counts,
            )

        before = snapshot()
        httpd, base_url = server.start_test_server(self.db_path)
        try:
            with mock.patch.object(server.LearningHandler, "_start_v3_flow_processing"):
                replay = self._request(
                    "POST",
                    base_url,
                    "/api/current-step/submit",
                    copy.deepcopy(payload),
                )
                self.assertEqual(200, replay["status"], replay["body"])
                self.assertEqual("summary", json.loads(replay["body"])["child_state"])

                changed = copy.deepcopy(payload)
                changed["answer_text"] = "3"
                conflict = self._request(
                    "POST",
                    base_url,
                    "/api/current-step/submit",
                    changed,
                )
                self.assertEqual(409, conflict["status"], conflict["body"])
                self._assert_child_safe(conflict["body"])
        finally:
            httpd.shutdown()
            httpd.server_close()

        self.assertEqual(before, snapshot())

    def test_correction_creates_new_immutable_input_evidence_revision(self):
        payload, _, _ = self._confirmed_handwriting_payload(key="correction-revision", answer="3")
        self._submit_payload(payload)
        attempt = self._attempt_for_key("correction-revision")
        original = db.get_attempt_input_evidence(self.conn, attempt["id"])
        before = db.attempt_evidence_revisions(self.conn, attempt["id"])

        try:
            corrected = db.record_attempt_input_evidence(
                self.conn,
                attempt_id=attempt["id"],
                schema_version=multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION,
                input_mode="handwriting",
                recognition_status="confirmed",
                recognition_source="live_ocr",
                recognized_text="3",
                recognition_confidence=0.96,
                critical_token_uncertainties=[],
                child_confirmed=True,
                child_confirmed_text="-3",
                attachment_ids=original["attachment_ids"],
                raw={
                    "recognition_handle": "RH-current",
                    "client_corrections": [{"from": "3", "to": "-3", "reason": "补回负号"}],
                    "supersedes_evidence_id": original["id"],
                },
                commit=True,
            )
        except sqlite3.IntegrityError as exc:
            self.fail(f"correction must append an immutable revision, not overwrite/reject the prior row: {exc}")

        self.assertNotEqual(original["id"], corrected["id"])
        rows = db.attempt_evidence_revisions(self.conn, attempt["id"])
        self.assertEqual(len(before) + 1, len(rows))
        self.assertEqual(original["id"], rows[-2]["id"])
        self.assertEqual("3", rows[-2]["child_confirmed_text"])
        self.assertEqual("-3", rows[-1]["child_confirmed_text"])
        self.assertNotEqual(rows[-2]["evidence_digest_sha256"], rows[-1]["evidence_digest_sha256"])
        self.assertEqual(
            [row["evidence_digest_sha256"] for row in before],
            [row["evidence_digest_sha256"] for row in rows[:-1]],
            "correction must append without rewriting prior immutable revisions",
        )

    def test_diagnostic_actual_hint_exposure_blocks_A(self):
        rows = self._stable_mastery_lineage_rows()
        rows[0].update(
            {
                "actual_hint_exposed": True,
                "child_hint_exposed": True,
                "presented_hint": "先看绝对值表示到 0 的距离。",
            }
        )
        self.assertFalse(
            self._stable_mastery_result_for_rows(rows),
            "stored no_hint policy cannot override a hint that the child actually saw",
        )

    def test_A_requires_active_accepted_current_passed_assessments(self):
        mutations = {
            "inactive_attempt_evidence": {
                "evidence_status": "invalidated",
                "attempt_evidence_status": "invalidated",
            },
            "nonaccepted_assessment": {
                "assessment_status": "pending",
                "accepted_assessment_status": "pending",
            },
            "question_not_passed": {
                "question_passed": False,
                "assessment_question_passed": False,
            },
            "stale_graph_version": {
                "graph_version": "graph-stale",
                "attempt_graph_version": "graph-stale",
                "graph_version_is_current": False,
            },
            "stale_question_bank_version": {
                "question_bank_version": "bank-stale",
                "attempt_question_bank_version": "bank-stale",
                "question_bank_version_is_current": False,
            },
            "stale_question_item_version": {
                "question_item_version": "item-stale",
                "assessment_question_item_version": "item-stale",
                "question_item_version_is_current": False,
            },
        }
        self.assertTrue(
            self._stable_mastery_result_for_rows(self._stable_mastery_lineage_rows()),
            "the positive oracle must retain three valid diagnostic assessments",
        )
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                rows = self._stable_mastery_lineage_rows()
                rows[0].update(mutation)
                self.assertFalse(
                    self._stable_mastery_result_for_rows(rows),
                    f"A must reject {label}",
                )

    def test_raw_photo_in_deferred_group_uses_single_ocr_analysis_before_next_question(self):
        _, attempt, _, job = self._enqueue_photo_single_answer_job(key="photo-placeholder")
        self.assertEqual("已上传纸面答案。", attempt["answer_raw"])
        self.assertEqual("answer_analysis", job["job_type"])
        self.assertEqual("queued", attempt["review_meta"]["status"])
        self.assertEqual(1, self.conn.execute(
            "select count(*) from flow_steps where flow_id = ?",
            (job["flow_id"],),
        ).fetchone()[0])

    def test_usable_photo_assessment_creates_next_group_question_after_analysis(self):
        step_row, attempt, contract, job = self._enqueue_photo_single_answer_job(
            key="photo-usable-next"
        )
        route = self._configured_answer_route()
        photo_ocr = {
            "status": "usable",
            "confidence": 0.96,
            "transcript": "孩子写出了正确关系和答案。",
            "math_objects": ["正确关系"],
            "notes": "字迹清楚。",
            "route": {"provider": "doubao", "model": "vision-test", "model_alias": "vision-test"},
        }
        with mock.patch.object(model_router, "answer_analysis_route", return_value=route), mock.patch(
            "learning_system.daily_runtime.auto_review._review_answer_photo",
            return_value=photo_ocr,
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=self._accepted_single_answer_envelope(contract),
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual("succeeded", result["job_status"], result)
        self.assertEqual("mini_group_accumulating", result["next_action"], result)
        state = self.runtime.project_child_state(self.runtime._flow_by_id(step_row["flow_id"]))
        self.assertEqual("current_step", state["child_state"], state)
        next_step = self._step_row(state)
        next_meta = self.runtime._mini_group_meta(next_step)
        self.assertEqual(2, next_meta["index"])
        self.assertNotEqual(step_row["question_id"], next_step["question_id"])
        self.assertEqual("graded", db.get_attempt(self.conn, attempt["id"])["grading_status"])
        recognition = self.conn.execute(
            "select * from media_recognition_runs where flow_step_id = ?",
            (step_row["id"],),
        ).fetchone()
        self.assertIsNotNone(recognition)
        self.assertEqual("photo", recognition["input_mode"])
        self.assertEqual("usable", recognition["recognition_status"])
        answer_run = self.conn.execute(
            "select input_refs_json from agent_runs where id = ?",
            (result["answer_analysis_agent_run_id"],),
        ).fetchone()
        input_refs = db.json_load(answer_run["input_refs_json"], {})
        self.assertEqual(recognition["id"], input_refs["photo_recognition_run_id"])
        self.assertEqual(
            recognition["output_digest_sha256"],
            input_refs["photo_recognition_output_digest_sha256"],
        )

    def test_photo_ocr_artifact_tamper_is_rejected_before_assessment_commit(self):
        _, attempt, contract, job = self._enqueue_photo_single_answer_job(
            key="photo-ocr-artifact-tamper"
        )
        route = self._configured_answer_route()

        def tamper_after_ocr(_request):
            row = self.conn.execute(
                "select id from media_recognition_runs where flow_step_id = ?",
                (attempt["flow_step_id"],),
            ).fetchone()
            self.assertIsNotNone(row)
            self.conn.execute(
                "update media_recognition_runs set recognized_text = '被篡改的识别结果' where id = ?",
                (row["id"],),
            )
            self.conn.commit()
            return self._accepted_single_answer_envelope(contract)

        with mock.patch.object(model_router, "answer_analysis_route", return_value=route), mock.patch(
            "learning_system.daily_runtime.auto_review._review_answer_photo",
            return_value={
                "status": "usable",
                "confidence": 0.96,
                "transcript": "原始清楚的识别结果。",
                "math_objects": ["正确关系"],
                "notes": "清楚",
                "route": {"provider": "doubao", "model": "vision-test", "model_alias": "vision-test"},
            },
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=tamper_after_ocr,
        ):
            with self.assertRaisesRegex(ValueError, "recognition output digest mismatch"):
                self.runtime._handle_answer_analysis_job(job)

        latest = db.get_attempt(self.conn, attempt["id"])
        self.assertEqual("pending_review", latest["grading_status"])
        self.assertIsNone(
            assessment_store.accepted_assessment_for_attempt(
                self.conn,
                attempt["id"],
                int(attempt.get("attempt_version") or 1),
            )
        )

    def test_typed_then_photo_group_finishes_as_sequential_single_assessments(self):
        first_step = self._step_row()
        self._set_practice_context(first_step, size=2)
        second_state = self._submit_payload(
            self._typed_payload(self.started, key="typed-before-photo", answer="第一题文字答案")
        )
        self.assertEqual("current_step", second_state["child_state"])
        second_step = self._step_row(second_state)
        package = db.json_load(second_step.get("prompt_package_json"), {})
        package.update(
            {
                "answer_input_mode": "photo",
                "allowed_response_modes": ["photo", "stuck"],
                "upload_enabled": True,
            }
        )
        self.conn.execute(
            "update flow_steps set prompt_package_json = ? where id = ?",
            (db.json_dump(package), second_step["id"]),
        )
        self.conn.commit()
        photo_payload = self._typed_payload(second_state, key="photo-after-typed", answer="")
        photo_payload.update(
            {
                "answer_photo_data_url": self._data_url(
                    "image/png", b"\x89PNG\r\n\x1a\nphoto-after-typed"
                ),
                "answer_photo_name": "paper.png",
            }
        )
        submitted = self._submit_payload(photo_payload)
        self.assertEqual("analyzing", submitted["child_state"])
        photo_attempt = self._attempt_for_key("photo-after-typed")
        photo_job = dict(
            self.conn.execute(
                "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
                (photo_attempt["id"],),
            ).fetchone()
        )
        photo_contract = assessment_store.bound_active_contract_for_flow_step(
            self.conn, second_step["id"]
        )
        route = self._configured_answer_route()
        with mock.patch.object(model_router, "answer_analysis_route", return_value=route), mock.patch(
            "learning_system.daily_runtime.auto_review._review_answer_photo",
            return_value={
                "status": "usable",
                "confidence": 0.96,
                "transcript": "第二题照片答案正确。",
                "math_objects": ["正确答案"],
                "notes": "清楚",
                "route": {"provider": "doubao", "model": "vision-test", "model_alias": "vision-test"},
            },
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=self._accepted_single_answer_envelope(photo_contract),
        ):
            photo_result = self.runtime._handle_answer_analysis_job(photo_job)
        self.assertEqual("mini_group_sequential_analysis", photo_result["next_action"], photo_result)

        typed_attempt = self._attempt_for_key("typed-before-photo")
        typed_job = dict(
            self.conn.execute(
                "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
                (typed_attempt["id"],),
            ).fetchone()
        )
        self.assertEqual(photo_job["id"], typed_job["depends_on_job_id"])
        typed_contract = assessment_store.bound_active_contract_for_flow_step(
            self.conn, first_step["id"]
        )
        with mock.patch.object(model_router, "answer_analysis_route", return_value=route), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=self._accepted_single_answer_envelope(typed_contract),
        ):
            typed_result = self.runtime._handle_answer_analysis_job(typed_job)
        self.assertEqual("mini_group_assessment_feedback", typed_result["next_action"], typed_result)
        self.assertEqual(0, self.conn.execute(
            "select count(*) from background_jobs where flow_id = ? and job_type = 'group_answer_analysis'",
            (first_step["flow_id"],),
        ).fetchone()[0])

    def test_unclear_photo_invalidates_prior_deferred_group_evidence(self):
        first_step = self._step_row()
        self._set_practice_context(first_step, size=2)
        second_state = self._submit_payload(
            self._typed_payload(self.started, key="typed-before-unclear-photo", answer="第一题文字答案")
        )
        second_step = self._step_row(second_state)
        package = db.json_load(second_step.get("prompt_package_json"), {})
        package.update(
            {
                "answer_input_mode": "photo",
                "allowed_response_modes": ["photo", "stuck"],
                "upload_enabled": True,
            }
        )
        self.conn.execute(
            "update flow_steps set prompt_package_json = ? where id = ?",
            (db.json_dump(package), second_step["id"]),
        )
        self.conn.commit()
        payload = self._typed_payload(second_state, key="unclear-photo-after-typed", answer="")
        payload.update(
            {
                "answer_photo_data_url": self._data_url(
                    "image/png", b"\x89PNG\r\n\x1a\nunclear-photo-after-typed"
                ),
                "answer_photo_name": "unclear.png",
            }
        )
        self._submit_payload(payload)
        photo_attempt = self._attempt_for_key("unclear-photo-after-typed")
        photo_job = dict(
            self.conn.execute(
                "select * from background_jobs where attempt_id = ? and job_type = 'answer_analysis'",
                (photo_attempt["id"],),
            ).fetchone()
        )
        contract = assessment_store.bound_active_contract_for_flow_step(
            self.conn, second_step["id"]
        )
        expected = internal_agents.load_v5_contract_for_agent("answer_analysis_agent")
        criteria = []
        for index, point in enumerate(contract["score_points"]):
            criteria.append(
                {
                    "criterion_key": point["key"],
                    "status": "unclear" if index == 0 else "met",
                    "child_evidence": "照片中的关键符号看不清。" if index == 0 else "其余部分可见。",
                    "reason": "关键证据不足。" if index == 0 else "可见部分成立。",
                }
            )
        envelope = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="accepted",
            provider_mode="live_model",
            retryable=False,
            confidence=0.2,
            output={
                "schema_version": expected["response_schema_version"],
                "criteria": criteria,
                "answer_gap": "照片中的关键符号看不清，暂时不能判断。",
                "improvement_direction": ["请补拍清楚关键算式。"],
                "expression_judgment": "当前证据不足，不评价表达。",
                "teaching_explanation": "先把关键算式拍清楚。",
                "confidence": 0.2,
            },
            route_meta={"fixture": "unclear-photo-group-interruption"},
            prompt_version_id=expected["prompt_version_id"],
            response_schema_version=expected["response_schema_version"],
        )
        route = self._configured_answer_route()
        with mock.patch.object(model_router, "answer_analysis_route", return_value=route), mock.patch(
            "learning_system.daily_runtime.auto_review._review_answer_photo",
            return_value={
                "status": "unclear",
                "confidence": 0.2,
                "transcript": "",
                "math_objects": [],
                "notes": "关键符号模糊",
                "route": {"provider": "doubao", "model": "vision-test", "model_alias": "vision-test"},
            },
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ):
            result = self.runtime._handle_answer_analysis_job(photo_job)

        self.assertEqual("clarify_evidence", result["next_action"], result)
        typed_attempt = db.get_attempt(
            self.conn, self._attempt_for_key("typed-before-unclear-photo")["id"]
        )
        self.assertEqual("blocked", typed_attempt["grading_status"])
        self.assertEqual("invalidated", typed_attempt["evidence_status"])
        self.assertEqual(
            "group_interrupted_by_clarification",
            typed_attempt["review_meta"]["status"],
        )
        self.assertEqual(0, self.conn.execute(
            """
            select count(*) from attempts
            where flow_step_id in (select id from flow_steps where flow_id = ?)
              and grading_status = 'pending_review' and evidence_status = 'active'
            """,
            (first_step["flow_id"],),
        ).fetchone()[0])

    def test_group_handler_rejects_stale_evidence_revision_digest(self):
        _, attempt, job = self._enqueue_single_item_group_job(key="stale-group-evidence")
        latest = db.get_attempt_input_evidence(self.conn, attempt["id"])
        db.record_attempt_evidence_revision(
            self.conn,
            attempt_id=attempt["id"],
            revision_kind="correction",
            schema_version=multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION,
            input_mode="typed",
            recognition_status="not_required",
            effective_text="mutated after enqueue",
            submission_request_digest_sha256=attempt["submission_request_digest_sha256"],
            parent_revision_id=latest["id"],
            raw={"test_mutation": "stale_group_evidence"},
            commit=True,
        )
        self._assert_group_rejected_before_model(
            job,
            expected_reason="group_evidence_digest_mismatch",
        )

    def test_group_handler_rejects_stale_usage_context_digest(self):
        _, attempt, job = self._enqueue_single_item_group_job(key="stale-group-usage")
        snapshot = db.attempt_usage_context(self.conn, attempt["id"])["snapshot"]
        snapshot["block_id"] = "tampered-after-enqueue"
        self.conn.execute(
            "update attempt_usage_contexts set snapshot_json = ? where attempt_id = ?",
            (db.json_dump(snapshot), attempt["id"]),
        )
        self.conn.commit()
        self._assert_group_rejected_before_model(
            job,
            expected_reason="group_usage_context_digest_mismatch",
        )

    def test_single_photo_handler_rejects_stale_media_digest_before_ocr(self):
        _, attempt, _, job = self._enqueue_photo_single_answer_job(key="stale-group-media")
        attachment = db.attachments_for_attempt(self.conn, attempt["id"])[0]
        media_path = (self.runtime.project_root / attachment["relative_path"]).resolve()
        media_path.write_bytes(b"\x89PNG\r\n\x1a\nmutated-after-enqueue")
        with mock.patch(
            "learning_system.daily_runtime.auto_review._review_answer_photo"
        ) as photo_ocr, mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
        ) as answer_model:
            result = self.runtime._handle_answer_analysis_job(job)
        photo_ocr.assert_not_called()
        answer_model.assert_not_called()
        self.assertEqual("blocked", result["job_status"], result)
        self.assertIn("media", result["reason"], result)

    def test_group_handler_revalidates_complete_snapshot_after_model_call(self):
        _, attempt, job = self._enqueue_single_item_group_job(key="post-model-stale-group")
        structured = self._structured_group_result(job)

        def mutate_after_prompt(*_args, **_kwargs):
            latest = db.latest_attempt_evidence_revision(self.conn, attempt["id"])
            db.record_attempt_evidence_revision(
                self.conn,
                attempt_id=attempt["id"],
                revision_kind="correction",
                schema_version=multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION,
                input_mode="typed",
                recognition_status="not_required",
                effective_text="changed while model was running",
                submission_request_digest_sha256=attempt["submission_request_digest_sha256"],
                parent_revision_id=latest["id"],
                raw={"test_mutation": "post_model_group_snapshot"},
                commit=True,
            )
            return structured

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            model_router,
            "call_structured_json",
            side_effect=mutate_after_prompt,
        ):
            result = self.runtime._handle_group_answer_analysis_job(job)

        self.assertEqual("blocked", result["job_status"], result)
        self.assertEqual("group_evidence_digest_mismatch", result["reason"], result)
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempt_assessments where status = 'accepted'",
        ).fetchone()[0])

    def test_group_model_call_does_not_hold_sqlite_write_lock(self):
        _, _, job = self._enqueue_single_item_group_job(key="group-model-no-db-lock")
        structured = self._structured_group_result(job)

        def model_call_with_concurrent_writer(*_args, **_kwargs):
            self._assert_separate_writer_available()
            return structured

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            model_router,
            "call_structured_json",
            side_effect=model_call_with_concurrent_writer,
        ):
            result = self.runtime._handle_group_answer_analysis_job(job)

        self.assertEqual("succeeded", result["job_status"], result)

    def test_group_feedback_exposes_each_questions_actual_reference_answer(self):
        step_row, _, job = self._enqueue_single_item_group_job(
            key="group-feedback-reference-answers"
        )
        payload = db.json_load(job["payload_json"], {})
        expected_answers = []
        for group_item in payload["group_items"]:
            contract = assessment_store.bound_active_contract_for_flow_step(
                self.conn,
                group_item["step_id"],
            )
            expected_answers.append(self.runtime._assessment_reference_answer(contract))
        structured = self._structured_group_result(job)

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            model_router,
            "call_structured_json",
            return_value=structured,
        ):
            result = self.runtime._handle_group_answer_analysis_job(job)

        self.assertEqual("succeeded", result["job_status"], result)
        state = self.runtime.project_child_state(self.runtime._flow_by_id(step_row["flow_id"]))
        self.assertEqual("assessment_feedback", state["child_state"])
        feedback = state["current_step"]["assessment_feedback"]
        self.assertEqual("mini_group", feedback["scope"])
        self.assertEqual(2, len(feedback["items"]))
        self.assertEqual(
            expected_answers,
            [item["reference_answer"] for item in feedback["items"]],
        )

    def test_low_confidence_group_review_never_turns_uncertainty_into_zero_scores(self):
        step_row, _, job = self._enqueue_single_item_group_job(
            key="group-low-confidence"
        )
        structured = self._structured_group_result(job)
        for item in structured.value["items"]:
            item["confidence"] = 0.1
            item["answer_gap"] = "这份答案暂时看不清，不能安全判断。"
            for criterion in item["criteria"]:
                criterion["status"] = "not_met"
                criterion["child_evidence"] = ""
                criterion["reason"] = "低置信时不能把看不清当成做错。"
        structured.value["confidence"] = 0.1

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            model_router,
            "call_structured_json",
            return_value=structured,
        ):
            result = self.runtime._handle_group_answer_analysis_job(job)

        self.assertEqual("succeeded", result["job_status"], result)
        self.assertEqual("clarify_evidence", result["next_action"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempt_assessments where status = 'accepted'",
        ).fetchone()[0])
        group_attempts = self.conn.execute(
            """
            select a.*
            from attempts a
            join flow_steps s on s.id = a.flow_step_id
            where s.flow_id = ?
            """,
            (step_row["flow_id"],),
        ).fetchall()
        self.assertTrue(group_attempts)
        self.assertTrue(all(row["evidence_status"] == "invalidated" for row in group_attempts))
        self.assertTrue(all(row["grading_status"] != "pending_review" for row in group_attempts))
        state = self.runtime.project_child_state(self.runtime._flow_by_id(step_row["flow_id"]))
        self.assertEqual("clarify_evidence", state["child_state"])

    def test_single_model_call_does_not_hold_sqlite_write_lock(self):
        _, _, contract, job = self._enqueue_single_answer_job(
            key="single-model-no-db-lock"
        )
        envelope = self._accepted_single_answer_envelope(contract)

        def model_call_with_concurrent_writer(*_args, **_kwargs):
            self._assert_separate_writer_available()
            return envelope

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=model_call_with_concurrent_writer,
        ):
            result = self.runtime._handle_answer_analysis_job(job)

        self.assertEqual("succeeded", result["job_status"], result)

    def test_browser_voice_is_client_unverified_and_cannot_update_mastery(self):
        payload, run = self._confirmed_browser_voice_payload(
            key="browser-voice-diagnostic"
        )
        self._submit_payload(payload)
        attempt = self._attempt_for_key("browser-voice-diagnostic")
        graded = self._mark_attempt_graded(attempt["id"], result="correct")

        result = self.runtime._record_evaluation_update(
            attempt=graded,
            validation=self._usable_validation(graded["id"]),
            provider_mode="deterministic_runtime",
            evaluation_output={"mastery_recommendation": "likely_stable"},
        )

        persisted_run = db.get_media_recognition_run(self.conn, run["id"])
        self.assertEqual("client_unverified", persisted_run["trust_classification"])
        self.assertFalse(result["applied"], result)
        self.assertTrue(result["non_mastery_evidence"], result)
        self.assertEqual("client_unverified_voice_transcript", result["reason_code"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])

    def test_unverified_voice_next_selection_requires_same_node_diagnostic_confirmation(self):
        payload, _ = self._confirmed_browser_voice_payload(
            key="browser-voice-planning-guard"
        )
        self._submit_payload(payload)
        attempt = self._attempt_for_key("browser-voice-planning-guard")
        graded = self._mark_attempt_graded(attempt["id"], result="wrong")
        flow = dict(self.runtime._flow_by_id(self._step_row()["flow_id"]))
        selected = {
            "question": {"id": "Q-SAME-NODE", "node_id": graded["node_id"]},
            "review_record_id": "RR-SAME-NODE",
            "candidate_packet": {},
            "selection_reason": {},
        }

        with mock.patch.object(
            self.runtime,
            "_select_question_for_node",
            return_value=selected,
        ) as select_question, mock.patch.object(
            self.runtime.graph,
            "rollback_candidates",
            return_value=["M-PRE-OTHER-NODE"],
        ):
            result = self.runtime._next_selection_after_attempt(flow, attempt=graded)

        self.assertEqual("same_node_trusted_reconfirmation", result["action"])
        select_question.assert_called_once()
        args, kwargs = select_question.call_args
        self.assertEqual(graded["node_id"], args[0])
        self.assertEqual("diagnostic", kwargs["required_purpose"])
        self.assertEqual("untrusted_evidence_reconfirmation", kwargs["selection_intent"])

    def test_unverified_voice_single_assessment_skips_pending_target_planning(self):
        step_row = self._step_row()
        contract = self._bind_active_contract(step_row)
        selection_reason = db.json_load(step_row.get("selection_reason_json"), {})
        selection_reason.pop("mini_group", None)
        self.conn.execute(
            "update flow_steps set selection_reason_json = ? where id = ?",
            (db.json_dump(selection_reason), step_row["id"]),
        )
        self.conn.execute(
            "update daily_flows set assessment_policy_version = 'v5.1' where id = ?",
            (step_row["flow_id"],),
        )
        self.conn.commit()
        payload, _ = self._confirmed_browser_voice_payload(
            key="browser-voice-single-planning"
        )
        self._submit_payload(payload)
        envelope = self._accepted_single_answer_envelope(contract)

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            return_value=envelope,
        ), mock.patch.object(
            self.runtime,
            "_plan_pending_target_after_assessment_locked",
            side_effect=AssertionError("unverified voice must not apply a pending target"),
        ) as pending_target:
            result = self.runtime.process_next_background_job(
                worker_id="browser-voice-single-worker",
                flow_id=step_row["flow_id"],
            )

        self.assertEqual("succeeded", result["job_status"], result)
        pending_target.assert_not_called()

    def test_reclaimed_job_fences_old_worker_group_assessment_commit(self):
        step_row, _, job = self._enqueue_single_item_group_job(key="lease-fenced-group")
        structured = self._structured_group_result(job)
        group_payload = db.json_load(job["payload_json"], {})
        attempt_ids = [item["attempt_id"] for item in group_payload["group_items"]]
        placeholders = ",".join("?" for _ in attempt_ids)
        initial_attempts = [
            tuple(row)
            for row in self.conn.execute(
                f"""
                select id, result, grading_status, analysis_status, analysis_version,
                       evidence_status, review_meta_json, answer_analysis_json
                from attempts where id in ({placeholders}) order by id
                """,
                attempt_ids,
            ).fetchall()
        ]
        initial_flow = tuple(self.conn.execute(
            """
            select status, current_step_id, flow_revision, summary_id, updated_at
            from daily_flows where id = ?
            """,
            (step_row["flow_id"],),
        ).fetchone())
        initial_steps = [
            tuple(row)
            for row in self.conn.execute(
                """
                select id, status, attempt_id, source_next_step_decision_id, step_revision,
                       step_type, updated_at
                from flow_steps where flow_id = ? order by position, id
                """,
                (step_row["flow_id"],),
            ).fetchall()
        ]
        initial_counts = {
            table: self.conn.execute(f"select count(*) from {table}").fetchone()[0]
            for table in (
                "attempt_assessments",
                "agent_runs",
                "evidence_validations",
                "mastery_decisions",
                "next_step_decisions",
            )
        }

        def reclaim_while_model_runs(*_args, **_kwargs):
            self.conn.execute(
                """
                update background_jobs
                set lease_owner = 'expired-worker',
                    claim_generation = claim_generation + 1,
                    claim_token = 'replacement-claim-token',
                    lease_expires_at = '2099-12-31T23:59:59.000000',
                    status = 'running'
                where id = ?
                """,
                (job["id"],),
            )
            self.conn.commit()
            return structured

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            model_router,
            "call_structured_json",
            side_effect=reclaim_while_model_runs,
        ):
            result = self.runtime.process_next_background_job(
                worker_id="expired-worker",
                flow_id=step_row["flow_id"],
            )

        self.assertEqual("claim_lost", result["status"], result)
        self.assertEqual(0, self.conn.execute(
            f"select count(*) from attempt_assessments where attempt_id in ({placeholders})",
            attempt_ids,
        ).fetchone()[0], "reclaimed group worker must not leave pending or accepted assessments")
        self.assertEqual(0, self.conn.execute(
            f"select count(*) from attempt_assessments where attempt_id in ({placeholders}) and semantic_checkpointed_at is not null",
            attempt_ids,
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            f"select count(*) from agent_runs where input_refs_json like ?",
            (f"%{attempt_ids[0]}%",),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            f"select count(*) from evidence_validations where attempt_id in ({placeholders})",
            attempt_ids,
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from mastery_decisions where source_attempt_ids_json like ?",
            (f"%{attempt_ids[0]}%",),
        ).fetchone()[0])
        current_attempts = [
            tuple(row)
            for row in self.conn.execute(
                f"""
                select id, result, grading_status, analysis_status, analysis_version,
                       evidence_status, review_meta_json, answer_analysis_json
                from attempts where id in ({placeholders}) order by id
                """,
                attempt_ids,
            ).fetchall()
        ]
        current_flow = tuple(self.conn.execute(
            """
            select status, current_step_id, flow_revision, summary_id, updated_at
            from daily_flows where id = ?
            """,
            (step_row["flow_id"],),
        ).fetchone())
        current_steps = [
            tuple(row)
            for row in self.conn.execute(
                """
                select id, status, attempt_id, source_next_step_decision_id, step_revision,
                       step_type, updated_at
                from flow_steps where flow_id = ? order by position, id
                """,
                (step_row["flow_id"],),
            ).fetchall()
        ]
        current_counts = {
            table: self.conn.execute(f"select count(*) from {table}").fetchone()[0]
            for table in initial_counts
        }
        self.assertEqual(initial_attempts, current_attempts)
        self.assertEqual(initial_flow, current_flow)
        self.assertEqual(initial_steps, current_steps)
        self.assertEqual(initial_counts, current_counts)
        row = self.conn.execute(
            "select lease_owner, claim_token, status from background_jobs where id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual("expired-worker", row["lease_owner"])
        self.assertEqual("replacement-claim-token", row["claim_token"])
        self.assertEqual("running", row["status"])

    def test_single_answer_rejects_model_output_after_evidence_revision_race(self):
        step_row, attempt, contract, job = self._enqueue_single_answer_job(
            key="single-evidence-race"
        )
        envelope = self._accepted_single_answer_envelope(contract)

        def revise_evidence_while_model_runs(_request):
            latest = db.latest_attempt_evidence_revision(self.conn, attempt["id"])
            db.record_attempt_evidence_revision(
                self.conn,
                attempt_id=attempt["id"],
                revision_kind="correction",
                schema_version=latest["schema_version"],
                input_mode=latest["input_mode"],
                recognition_status=latest["recognition_status"],
                effective_text="并发修正后的答案",
                attachment_ids=latest["attachment_ids"],
                submission_request_digest_sha256=attempt[
                    "submission_request_digest_sha256"
                ],
                parent_revision_id=latest["id"],
                raw={"fixture": "post-enqueue-evidence-race"},
                commit=True,
            )
            return envelope

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=revise_evidence_while_model_runs,
        ):
            result = self.runtime.process_next_background_job(
                worker_id="single-evidence-worker",
                flow_id=step_row["flow_id"],
            )

        self.assertEqual("dead_letter", result["job_status"], result)
        current = db.get_attempt(self.conn, attempt["id"])
        self.assertEqual("pending_review", current["grading_status"])
        self.assertEqual(0, current["analysis_version"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempt_assessments where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from agent_runs where input_refs_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from evidence_validations where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0])

    def test_reclaimed_single_answer_job_leaves_no_semantic_checkpoint_or_business_state(self):
        step_row, attempt, contract, job = self._enqueue_single_answer_job(
            key="single-checkpoint-reclaim"
        )
        envelope = self._accepted_single_answer_envelope(contract)
        initial_flow = dict(self.runtime._flow_by_id(step_row["flow_id"]))
        initial_step = dict(self.conn.execute(
            "select * from flow_steps where id = ?", (step_row["id"],)
        ).fetchone())

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=lambda _request: self._reclaim_job_during_model_call(
                job["id"], envelope
            ),
        ):
            result = self.runtime.process_next_background_job(
                worker_id="single-reclaimed-worker",
                flow_id=step_row["flow_id"],
            )

        self.assertEqual("claim_lost", result["status"], result)
        current = db.get_attempt(self.conn, attempt["id"])
        self.assertEqual("pending_review", current["grading_status"])
        self.assertEqual(0, current["analysis_version"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempt_assessments where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from agent_runs where input_refs_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from evidence_validations where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0])
        current_flow = dict(self.runtime._flow_by_id(step_row["flow_id"]))
        current_step = dict(self.conn.execute(
            "select * from flow_steps where id = ?", (step_row["id"],)
        ).fetchone())
        self.assertEqual(initial_flow["status"], current_flow["status"])
        self.assertEqual(initial_flow["current_step_id"], current_flow["current_step_id"])
        self.assertEqual(initial_flow["flow_revision"], current_flow["flow_revision"])
        self.assertEqual(initial_step["status"], current_step["status"])

    def test_expired_lease_second_worker_reuses_checkpoint_with_one_provider_call(self):
        step_row, attempt, contract, job = self._enqueue_single_answer_job(
            key="single-expired-lease-checkpoint-reuse"
        )
        envelope = self._accepted_single_answer_envelope(contract)

        def expire_lease_after_provider_returns(_request):
            self.conn.execute(
                """
                update background_jobs
                set lease_expires_at = '2000-01-01T00:00:00.000000'
                where id = ?
                """,
                (job["id"],),
            )
            self.conn.commit()
            return envelope

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=expire_lease_after_provider_returns,
        ) as provider_call:
            first = self.runtime.process_next_background_job(
                worker_id="expired-provider-worker",
                flow_id=step_row["flow_id"],
            )
            second = self.runtime.process_next_background_job(
                worker_id="replacement-provider-worker",
                flow_id=step_row["flow_id"],
            )

        self.assertEqual("claim_lost", first["status"], first)
        self.assertEqual("succeeded", second["job_status"], second)
        self.assertEqual(1, provider_call.call_count)
        self.assertEqual(1, self.conn.execute(
            """
            select count(*) from model_response_checkpoints
            where checkpoint_kind = 'answer_analysis' and source_job_id = ?
            """,
            (job["id"],),
        ).fetchone()[0])
        self.assertEqual(1, self.conn.execute(
            "select count(*) from attempt_assessments where attempt_id = ? and status = 'accepted'",
            (attempt["id"],),
        ).fetchone()[0])
        stored_job = self.conn.execute(
            "select status, claim_generation from background_jobs where id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual("succeeded", stored_job["status"])
        self.assertGreaterEqual(int(stored_job["claim_generation"]), 2)

    def test_reclaimed_pending_answer_job_leaves_no_pending_business_state(self):
        step_row, attempt, _, job = self._enqueue_single_answer_job(
            key="single-pending-reclaim"
        )
        initial_review_meta = copy.deepcopy(attempt["review_meta"])
        initial_flow = dict(self.runtime._flow_by_id(step_row["flow_id"]))
        initial_step = dict(self.conn.execute(
            "select * from flow_steps where id = ?", (step_row["id"],)
        ).fetchone())
        expected = internal_agents.load_v5_contract_for_agent("answer_analysis_agent")
        pending = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="pending",
            provider_mode="live_model",
            retryable=True,
            confidence=0.0,
            output={},
            validation_errors=(),
            error_reason="provider temporarily unavailable",
            route_meta={"fixture": "pending-reclaim"},
            prompt_version_id=expected["prompt_version_id"],
            response_schema_version=expected["response_schema_version"],
        )

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=lambda _request: self._reclaim_job_during_model_call(
                job["id"], pending
            ),
        ):
            result = self.runtime.process_next_background_job(
                worker_id="single-pending-worker",
                flow_id=step_row["flow_id"],
            )

        self.assertEqual("claim_lost", result["status"], result)
        current = db.get_attempt(self.conn, attempt["id"])
        self.assertEqual("pending_review", current["grading_status"])
        self.assertEqual(0, current["analysis_version"])
        self.assertEqual(initial_review_meta, current["review_meta"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from agent_runs where input_refs_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from evidence_validations where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempt_assessments where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0])
        current_flow = dict(self.runtime._flow_by_id(step_row["flow_id"]))
        current_step = dict(self.conn.execute(
            "select * from flow_steps where id = ?", (step_row["id"],)
        ).fetchone())
        self.assertEqual(initial_flow["status"], current_flow["status"])
        self.assertEqual(initial_flow["current_step_id"], current_flow["current_step_id"])
        self.assertEqual(initial_flow["flow_revision"], current_flow["flow_revision"])
        self.assertEqual(initial_step["status"], current_step["status"])

    def test_reclaimed_error_answer_job_leaves_no_error_business_state(self):
        step_row, attempt, _, job = self._enqueue_single_answer_job(
            key="single-error-reclaim"
        )
        initial_review_meta = copy.deepcopy(attempt["review_meta"])
        initial_flow = dict(self.runtime._flow_by_id(step_row["flow_id"]))
        initial_step = dict(self.conn.execute(
            "select * from flow_steps where id = ?", (step_row["id"],)
        ).fetchone())
        expected = internal_agents.load_v5_contract_for_agent("answer_analysis_agent")
        error = semantic_agents.SemanticAgentEnvelope(
            agent_key="answer_analysis_agent",
            phase="answer_analysis",
            status="error",
            provider_mode="live_model",
            retryable=False,
            confidence=0.0,
            output={},
            validation_errors=(),
            error_reason="non-retryable provider response",
            route_meta={"fixture": "error-reclaim"},
            prompt_version_id=expected["prompt_version_id"],
            response_schema_version=expected["response_schema_version"],
        )

        with mock.patch.object(
            model_router,
            "answer_analysis_route",
            return_value=self._configured_answer_route(),
        ), mock.patch.object(
            semantic_agents,
            "call_answer_analysis_agent",
            side_effect=lambda _request: self._reclaim_job_during_model_call(
                job["id"], error
            ),
        ):
            result = self.runtime.process_next_background_job(
                worker_id="single-error-worker",
                flow_id=step_row["flow_id"],
            )

        self.assertEqual("claim_lost", result["status"], result)
        current = db.get_attempt(self.conn, attempt["id"])
        self.assertEqual("pending_review", current["grading_status"])
        self.assertEqual(0, current["analysis_version"])
        self.assertEqual(initial_review_meta, current["review_meta"])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from agent_runs where input_refs_json like ?",
            (f"%{attempt['id']}%",),
        ).fetchone()[0])
        self.assertEqual(0, self.conn.execute(
            "select count(*) from attempt_assessments where attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0])
        current_flow = dict(self.runtime._flow_by_id(step_row["flow_id"]))
        current_step = dict(self.conn.execute(
            "select * from flow_steps where id = ?", (step_row["id"],)
        ).fetchone())
        self.assertEqual(initial_flow["status"], current_flow["status"])
        self.assertEqual(initial_flow["current_step_id"], current_flow["current_step_id"])
        self.assertEqual(initial_flow["flow_revision"], current_flow["flow_revision"])
        self.assertEqual(initial_step["status"], current_step["status"])

    def test_unique_conflict_recovery_requires_same_key_and_submission_digest(self):
        original_payload = self._typed_payload(
            self.started,
            key="unique-race-original",
            answer="-3",
        )
        self._submit_payload(original_payload)
        existing = self._attempt_for_key("unique-race-original")
        real_active_attempt = self.runtime._active_attempt_for_step

        def submit_through_integrity_recovery(payload):
            calls = 0

            def hide_existing_until_recovery(flow_step_id, *, client_idempotency_key=None):
                nonlocal calls
                calls += 1
                if calls <= 2:
                    return None
                return real_active_attempt(
                    flow_step_id,
                    client_idempotency_key=client_idempotency_key,
                )

            with mock.patch.object(
                self.runtime,
                "_active_attempt_for_step",
                side_effect=hide_existing_until_recovery,
            ):
                return self._submit_payload(payload)

        replay = submit_through_integrity_recovery(copy.deepcopy(original_payload))
        self.assertIn(replay["child_state"], {"analyzing", "current_step"})
        self.assertEqual(existing["id"], self._attempt_for_key("unique-race-original")["id"])

        different_key = copy.deepcopy(original_payload)
        different_key["client_idempotency_key"] = "unique-race-other-key"
        with self.assertRaises(daily_runtime.SubmissionIdempotencyConflict):
            submit_through_integrity_recovery(different_key)

        different_digest = copy.deepcopy(original_payload)
        different_digest["answer_text"] = "3"
        with self.assertRaises(daily_runtime.SubmissionIdempotencyConflict):
            submit_through_integrity_recovery(different_digest)

        self.assertEqual(1, self.conn.execute(
            "select count(*) from attempts where flow_step_id = ? and evidence_status = 'active'",
            (existing["flow_step_id"],),
        ).fetchone()[0])

    def test_deferred_group_integrity_recovery_never_enqueues_single_answer_job(self):
        first_row = self._step_row()
        self._set_practice_context(first_row, size=2)
        original_payload = self._typed_payload(
            self.started,
            key="deferred-group-race",
            answer="第一题答案",
        )
        self._submit_payload(original_payload)
        existing = self._attempt_for_key("deferred-group-race")
        self.conn.execute(
            """
            update flow_steps set status = 'planned'
            where flow_id = ? and id <> ? and status in ('selected','displayed')
            """,
            (first_row["flow_id"], first_row["id"]),
        )
        self.conn.execute(
            "update flow_steps set status = 'displayed' where id = ?",
            (first_row["id"],),
        )
        self.conn.execute(
            "update daily_flows set current_step_id = ? where id = ?",
            (first_row["id"], first_row["flow_id"]),
        )
        self.conn.commit()
        real_active_attempt = self.runtime._active_attempt_for_step
        calls = 0

        def hide_existing_until_integrity_recovery(flow_step_id, *, client_idempotency_key=None):
            nonlocal calls
            calls += 1
            if calls <= 2:
                return None
            return real_active_attempt(
                flow_step_id,
                client_idempotency_key=client_idempotency_key,
            )

        with mock.patch.object(
            self.runtime,
            "_active_attempt_for_step",
            side_effect=hide_existing_until_integrity_recovery,
        ):
            self._submit_payload(copy.deepcopy(original_payload))

        self.assertEqual(existing["id"], self._attempt_for_key("deferred-group-race")["id"])
        self.assertEqual(0, self.conn.execute(
            """
            select count(*) from background_jobs
            where attempt_id = ? and job_type = 'answer_analysis'
            """,
            (existing["id"],),
        ).fetchone()[0])

    def test_child_api_bootstrap_and_stale_submit_are_child_safe(self):
        httpd, base_url = server.start_test_server(self.db_path)
        try:
            bootstrap = self._request("GET", base_url, "/api/child-bootstrap")
            self.assertEqual(200, bootstrap["status"], bootstrap["body"])
            self._assert_child_safe(bootstrap["body"])

            stale = self._request(
                "POST",
                base_url,
                "/api/current-step/submit",
                {
                    "step_handle": "expired-step-handle",
                    "position": 999,
                    "client_idempotency_key": "stale-api-focused",
                    "answer_text": "-3",
                },
            )
            self.assertEqual(409, stale["status"], stale["body"])
            self._assert_child_safe(stale["body"])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def _stable_mastery_lineage_rows(self):
        base = {
            "purpose": "diagnostic",
            "hint_policy": "no_hint",
            "mastery_update_eligible": 1,
            "actual_hint_exposed": False,
            "child_hint_exposed": False,
            "presented_hint": "",
            "evidence_status": "active",
            "attempt_evidence_status": "active",
            "assessment_status": "accepted",
            "accepted_assessment_status": "accepted",
            "question_passed": True,
            "assessment_question_passed": True,
            "graph_version": "graph-current",
            "attempt_graph_version": "graph-current",
            "current_graph_version": "graph-current",
            "graph_version_is_current": True,
            "question_bank_version": "bank-current",
            "attempt_question_bank_version": "bank-current",
            "current_question_bank_version": "bank-current",
            "question_bank_version_is_current": True,
            "question_item_version": "item-current",
            "assessment_question_item_version": "item-current",
            "current_question_item_version": "item-current",
            "question_item_version_is_current": True,
            "question_status": "active",
            "review_status": "approved",
        }
        roles = ("confirmation_core", "confirmation_transfer", "confirmation_core")
        return [
            {
                **base,
                "id": f"EV-stable-{index}",
                "purpose_role": role,
                "structure_fingerprint": f"structure-{index}",
            }
            for index, role in enumerate(roles, start=1)
        ]

    def _stable_mastery_result_for_rows(self, rows):
        class ResultRows:
            def __init__(self, values):
                self.values = values

            def fetchall(self):
                return self.values

        class FocusedConnection:
            def __init__(self, values):
                self.values = values

            def execute(self, _query, _params=()):
                return ResultRows(self.values)

        original = self.runtime.conn
        self.runtime.conn = FocusedConnection(rows)
        try:
            return self.runtime._evidence_set_supports_stable_mastery(
                [row["id"] for row in rows]
            )
        finally:
            self.runtime.conn = original

    def _request(self, method, base_url, path, payload=None):
        host, port = base_url.replace("http://", "").split(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
        try:
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            with mock.patch.dict(
                os.environ,
                {
                    "V3_DAILY_RUNTIME_ENABLED": "1",
                    "ANSWER_ASSESSMENT_POLICY": "v5.1",
                    "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
                },
            ):
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                return {"status": response.status, "body": response.read().decode("utf-8")}
        finally:
            conn.close()

    def _assert_child_safe(self, serialized):
        lowered = serialized.lower()
        for forbidden in (
            "provider",
            "model_alias",
            "model_name",
            "job_id",
            "attempt_id",
            "question_id",
            "flow_id",
            "agent_run_id",
        ):
            self.assertNotIn(forbidden, lowered)

    @staticmethod
    def _data_url(content_type, data):
        return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


if __name__ == "__main__":
    unittest.main()
