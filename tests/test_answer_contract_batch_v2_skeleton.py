from __future__ import annotations

import inspect
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system import (
    answer_contract_batch_v2 as batch,
    answer_contract_generation_v2 as generation_v2,
    db,
    internal_agents,
    model_router,
    semantic_agents,
)


class _Observer:
    def __init__(self) -> None:
        self.started = []
        self.finished = []

    def provider_attempt_started(self, context) -> None:
        self.started.append(context)

    def provider_attempt_finished(self, context, outcome) -> None:
        self.finished.append((context, outcome))


class AnswerContractBatchV2SkeletonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "batch.sqlite"
        self.conn = db.connect(self.db_path)
        db.init_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def _seed_question_authority(self) -> None:
        self.conn.execute(
            """
            insert into graph_nodes(
              id, name, stage, domain, priority, summer_mode, sequence_band,
              prerequisites_json, unlocks_json, raw_json
            ) values ('NODE-1','Node','bridge','math','high','core',1,'[]','[]','{}')
            """
        )
        self.conn.execute(
            """
            insert into question_items(
              id, item_version, source_type, node_id, secondary_node_ids_json,
              kind, question_type, variant_level, prompt, answer_format,
              expected_answer, rubric_json, solution_steps_json, error_tags_json,
              rollback_candidate_node_ids_json, rollback_candidate_relations_json,
              estimated_minutes, parent_observation, source_json, raw_json
            ) values (
              'Q-1','v1','test','NODE-1','[]','standard_example','text','base',
              'Prompt','text','Answer','{}','[]','[]','[]','[]',1,'','{}','{}'
            )
            """
        )
        self.conn.execute(
            """
            insert into question_review_records(
              id, question_id, candidate_id, item_version, source_type,
              candidate_sha256, designer_run_id, reviewer_run_id,
              review_contract_version, review_status, rejection_reasons_json,
              criteria_json, active_eligible, reviewed_at
            ) values (
              'QRR-1','Q-1','candidate','v1','test','candidate-digest',null,null,
              'v1','approved','[]','{}',1,'2026-07-15T00:00:00+00:00'
            )
            """
        )
        self.conn.commit()

    def _insert_run(self, *, run_id="ACGR-1", parent=None, kind="canary40") -> None:
        self.conn.execute(
            """
            insert into answer_contract_generation_runs(
              id, run_schema_version, run_kind, run_identity_digest_sha256,
              parent_canary_run_id, bank_version, manifest_sha256, graph_version,
              plan_digest_sha256, effective_evidence_role_policy_version,
              effective_evidence_role_policy_digest_sha256,
              generator_policy_digest_sha256,
              designer_prompt_digest_sha256, designer_schema_digest_sha256,
              designer_route_digest_sha256, reviewer_prompt_digest_sha256,
              reviewer_schema_digest_sha256, reviewer_route_digest_sha256,
              expected_item_count, new_item_count, model_call_cap,
              provider_attempt_cap, item_wall_seconds,
              heartbeat_interval_seconds, stale_after_seconds,
              operation_generation, claim_token, claim_owner_pid,
              claim_invocation_id, claimed_at, heartbeat_at,
              preflight_status, status, created_at, updated_at
            ) values (
              ?, ?, ?, ?, ?, 'bank-v1','manifest','graph-v1','plan',
              ?, ?, 'generator-policy','dp','ds','dr','rp','rs','rr',
              40,40,240,840,180,15,300,1,'claim-secret',123,'INV-1',
              '2026-07-15T00:00:00+00:00','2026-07-15T00:00:00+00:00',
              'passed','running','2026-07-15T00:00:00+00:00',
              '2026-07-15T00:00:00+00:00'
            )
            """,
            (
                run_id,
                batch.RUN_SCHEMA_VERSION,
                kind,
                f"identity-{run_id}",
                parent,
                batch.EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION,
                batch.EFFECTIVE_EVIDENCE_ROLE_POLICY_DIGEST_SHA256,
            ),
        )

    def _seed_attempt(self, *, status="reserved") -> batch.RunClaim:
        self._seed_question_authority()
        self._insert_run()
        self.conn.execute(
            """
            insert into answer_contract_generation_run_items(
              id, run_id, ordinal, question_id, item_version,
              question_digest_sha256, node_id, kind, effective_evidence_role,
              effective_evidence_role_policy_version, review_record_id,
              status, created_at, updated_at
            ) values (
              'ITEM-1','ACGR-1',0,'Q-1','v1','question-digest','NODE-1',
              'standard_example','direct',?,'QRR-1','running',
              '2026-07-15T00:00:00+00:00','2026-07-15T00:00:00+00:00'
            )
            """,
            (batch.EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION,),
        )
        self.conn.execute(
            """
            insert into answer_contract_generation_attempts(
              id, run_id, run_item_id, claim_generation,
              claim_token_digest_sha256, role, contract_version_index,
              semantic_attempt_index, request_json, request_digest_sha256,
              prompt_digest_sha256, schema_digest_sha256, route_digest_sha256,
              status, reserved_at, provider_calling_at
            ) values (
              'ACBA-1','ACGR-1','ITEM-1',1,?,'designer',0,1,'{}',
              'request','prompt','schema','route',?,
              '2026-07-15T00:00:00+00:00',
              case when ? = 'provider_calling' then '2026-07-15T00:00:01+00:00' end
            )
            """,
            (batch.claim_token_digest("claim-secret"), status, status),
        )
        self.conn.commit()
        return batch.RunClaim(
            run_id="ACGR-1",
            operation_generation=1,
            claim_token="claim-secret",
            owner_pid=123,
            invocation_id="INV-1",
            claimed_at="2026-07-15T00:00:00+00:00",
            heartbeat_at="2026-07-15T00:00:00+00:00",
        )

    def test_batch_request_api_has_no_naked_trusted_lineage_parameters(self):
        for function in (
            generation_v2.semantic_design_request_v2,
            generation_v2.semantic_review_request_v2,
        ):
            parameters = inspect.signature(function).parameters
            self.assertNotIn("batch_attempt_id", parameters)
            self.assertNotIn("effective_evidence_role", parameters)
            self.assertNotIn("effective_evidence_role_policy_version", parameters)
            self.assertIn("batch_context", parameters)
        router_parameters = inspect.signature(
            model_router.call_structured_json
        ).parameters
        self.assertNotIn("batch_attempt_id", router_parameters)
        self.assertNotIn("lifecycle_observer", router_parameters)

    def test_context_is_opaque_and_load_requires_committed_current_claim(self):
        with self.assertRaises(TypeError):
            batch.BatchAttemptContext()
        claim = self._seed_attempt()
        context = batch.load_batch_attempt_context(
            self.conn,
            batch_attempt_id="ACBA-1",
            claim=claim,
            expected_role="designer",
        )
        self.assertEqual("ACBA-1", context.batch_attempt_id)
        self.assertEqual("direct", context.effective_evidence_role)
        database_path, database_identity = batch._database_authority_identity(
            self.conn
        )
        forged = batch.BatchAttemptContext(
            _seal=batch._BATCH_ATTEMPT_CONTEXT_SEAL,
            database_path=database_path,
            database_identity_digest_sha256=database_identity,
            claim_token="claim-secret",
            batch_attempt_id="ACBA-1",
            run_id="ACGR-1",
            run_item_id="ITEM-1",
            role="designer",
            contract_version_index=0,
            semantic_attempt_index=1,
            effective_evidence_role="direct",
            effective_evidence_role_policy_version=(
                batch.EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION
            ),
            operation_generation=1,
        )
        with self.assertRaises(TypeError):
            batch.validate_batch_attempt_context(
                forged,
                expected_role="designer",
                stage="request",
            )
        self.conn.execute(
            "update answer_contract_generation_runs set claim_token='different' where id='ACGR-1'"
        )
        self.conn.commit()
        with self.assertRaises(ValueError):
            batch.validate_batch_attempt_context(
                context,
                expected_role="designer",
                stage="request",
            )

    def test_request_and_router_binding_revalidate_current_db_claim(self):
        claim = self._seed_attempt(status="provider_calling")
        context = batch.load_batch_attempt_context(
            self.conn,
            batch_attempt_id="ACBA-1",
            claim=claim,
            expected_role="designer",
        )
        packet = {
            "item_handle": "item-1",
            "question_kind": "standard_example",
            "repair_iteration": 0,
            "designer_attempt": 0,
            "question": {"prompt": "Prompt"},
            "reviewer_issues": [],
            "local_compiler_issues": [],
            "generation_input_digest_sha256": "generation",
            "local_compiler_issue_digest_sha256": "",
            "skeleton": {
                "profile_version": "profile-v1",
                "allowed_slot_catalog": [],
                "reference_anchors": {},
            },
        }
        request = generation_v2.semantic_design_request_v2(
            packet,
            batch_context=context,
        )
        self.assertEqual("ACBA-1", request.trusted_context["batch_attempt_id"])
        self.assertEqual("ACBA-1", request.source_refs["batch_attempt_id"])
        with batch.bind_batch_attempt_transport(context, _Observer()):
            pass
        self.conn.execute(
            "update answer_contract_generation_runs set operation_generation=2 where id='ACGR-1'"
        )
        self.conn.commit()
        with self.assertRaises(ValueError):
            generation_v2.semantic_design_request_v2(packet, batch_context=context)
        with self.assertRaises(ValueError):
            with batch.bind_batch_attempt_transport(context, _Observer()):
                pass

    def test_agent_and_contract_persistence_reject_non_authoritative_contexts_first(self):
        with self.assertRaises(TypeError):
            generation_v2._persist_exact_live_run(
                self.conn,
                {},
                mock.Mock(),
                mock.Mock(),
                role="designer",
                batch_context=object(),
            )
        with self.assertRaises(TypeError):
            generation_v2._persist_contract_version(
                self.conn,
                {},
                {},
                {},
                {},
                {},
                {},
                {},
                design_batch_context=object(),
                review_batch_context=object(),
            )

    def test_write_authority_rejects_stale_database_copy_before_persistence(self):
        claim = self._seed_attempt(status="provider_calling")
        context = batch.load_batch_attempt_context(
            self.conn,
            batch_attempt_id="ACBA-1",
            claim=claim,
            expected_role="designer",
        )
        copy_path = Path(self.tmpdir.name) / "stale-copy.sqlite"
        copy_conn = db.connect(copy_path)
        try:
            self.conn.backup(copy_conn)
            packet = {
                "item_handle": "design-v2-test",
                "question_id": "Q-1",
                "item_version": "v1",
                "node_id": "NODE-1",
                "question_kind": "standard_example",
                "question_digest_sha256": "question-digest",
                "profile_digest_sha256": "profile-digest",
                "generation_input_digest_sha256": "generation-digest",
                "parent_contract_digest_sha256": "",
                "review_issue_digest_sha256": "",
                "local_compiler_issue_digest_sha256": "",
                "repair_iteration": 0,
                "designer_attempt": 0,
                "question": {"prompt": "Prompt", "expected_answer": "Answer"},
                "reviewer_issues": [],
                "local_compiler_issues": [],
                "skeleton": {
                    "item_handle": "design-v2-test",
                    "profile_version": "profile-v1",
                    "allowed_slot_catalog": [],
                    "reference_anchors": {},
                },
            }
            request = generation_v2.semantic_design_request_v2(
                packet, batch_context=context
            )
            contract = internal_agents.load_contract_for_agent_version(
                generation_v2.DESIGNER_AGENT_KEY, "v2"
            )
            envelope = semantic_agents.accepted_envelope(
                agent_key=generation_v2.DESIGNER_AGENT_KEY,
                phase=generation_v2.DESIGNER_PHASE,
                output={
                    "schema_version": contract["response_schema_version"],
                    "items": [],
                },
                provider_mode="live_model",
                confidence=0.95,
                route_meta={
                    "prompt_template_sha256": internal_agents.file_sha256(
                        internal_agents.prompt_path_for_contract(contract)
                    ),
                    "rendered_prompt_sha256": (
                        semantic_agents.rendered_prompt_sha256_for_request(request)
                    ),
                    "response_schema_sha256": (
                        internal_agents.canonical_json_sha256(
                            contract["response_schema"]
                        )
                    ),
                    "structured_json_endpoint": "responses",
                    "structured_json_mode": "json_schema",
                },
                contract_version_suffix="v2",
            )
            with self.assertRaisesRegex(
                ValueError, "actual write database identity"
            ):
                generation_v2._persist_exact_live_run(
                    copy_conn,
                    packet,
                    request,
                    envelope,
                    role="designer",
                    batch_context=context,
                )
            self.assertEqual(
                0,
                copy_conn.execute("select count(*) from agent_runs").fetchone()[0],
            )
            copy_conn.execute(
                "update answer_contract_generation_runs set operation_generation=2 where id='ACGR-1'"
            )
            copy_conn.commit()
            with self.assertRaisesRegex(
                ValueError, "actual write connection does not hold current CAS claim"
            ):
                generation_v2._persist_exact_live_run(
                    copy_conn,
                    packet,
                    request,
                    envelope,
                    role="designer",
                    batch_context=context,
                )
            self.assertEqual(
                0,
                copy_conn.execute("select count(*) from agent_runs").fetchone()[0],
            )
        finally:
            copy_conn.close()

    def test_contract_write_rejects_stale_database_copy_before_persistence(self):
        claim = self._seed_attempt(status="provider_calling")
        self.conn.execute(
            """
            insert into answer_contract_generation_attempts(
              id, run_id, run_item_id, claim_generation,
              claim_token_digest_sha256, role, contract_version_index,
              semantic_attempt_index, request_json, request_digest_sha256,
              prompt_digest_sha256, schema_digest_sha256, route_digest_sha256,
              status, reserved_at, provider_calling_at
            ) values (
              'ACBA-2','ACGR-1','ITEM-1',1,?,'reviewer',0,1,'{}',
              'request-review','prompt-review','schema-review','route-review',
              'provider_calling','2026-07-15T00:00:00+00:00',
              '2026-07-15T00:00:01+00:00'
            )
            """,
            (batch.claim_token_digest("claim-secret"),),
        )
        self.conn.commit()
        designer_context = batch.load_batch_attempt_context(
            self.conn,
            batch_attempt_id="ACBA-1",
            claim=claim,
            expected_role="designer",
        )
        reviewer_context = batch.load_batch_attempt_context(
            self.conn,
            batch_attempt_id="ACBA-2",
            claim=claim,
            expected_role="reviewer",
        )
        self.conn.execute(
            "update answer_contract_generation_attempts set status='accepted' "
            "where id in ('ACBA-1', 'ACBA-2')"
        )
        self.conn.commit()

        copy_path = Path(self.tmpdir.name) / "stale-contract-copy.sqlite"
        copy_conn = db.connect(copy_path)
        try:
            self.conn.backup(copy_conn)
            with self.assertRaisesRegex(
                ValueError, "actual write database identity"
            ):
                generation_v2._persist_contract_version(
                    copy_conn,
                    {
                        "question_id": "Q-1",
                        "generation_input_digest_sha256": "generation-digest",
                    },
                    {},
                    {},
                    {},
                    {},
                    {},
                    {},
                    design_batch_context=designer_context,
                    review_batch_context=reviewer_context,
                )
            self.assertEqual(
                0,
                copy_conn.execute("select count(*) from answer_contracts").fetchone()[0],
            )
        finally:
            copy_conn.close()

    def test_write_authority_accepts_second_connection_to_same_current_database(self):
        claim = self._seed_attempt(status="provider_calling")
        context = batch.load_batch_attempt_context(
            self.conn,
            batch_attempt_id="ACBA-1",
            claim=claim,
            expected_role="designer",
        )
        second = db.connect(self.db_path)
        try:
            with batch.batch_authority_write_scope(
                second,
                contexts=(("designer", context),),
                stage="agent_run_persistence",
            ) as scope:
                self.assertIs(second, scope.connection)
                self.assertEqual("agent_run_persistence", scope.stage)
        finally:
            second.close()

    def test_write_authority_uses_savepoint_inside_existing_transaction(self):
        claim = self._seed_attempt(status="provider_calling")
        context = batch.load_batch_attempt_context(
            self.conn,
            batch_attempt_id="ACBA-1",
            claim=claim,
            expected_role="designer",
        )
        self.conn.execute("begin immediate")
        try:
            with batch.batch_authority_write_scope(
                self.conn,
                contexts=(("designer", context),),
                stage="agent_run_persistence",
            ):
                self.assertTrue(self.conn.in_transaction)
            self.assertTrue(self.conn.in_transaction)
        finally:
            self.conn.rollback()

    def test_new_schema_has_authority_foreign_keys_and_rejects_invalid_refs(self):
        expected = {
            "answer_contract_generation_runs": {
                ("parent_canary_run_id", "answer_contract_generation_runs", "id")
            },
            "answer_contract_generation_run_items": {
                ("designer_batch_attempt_id", "answer_contract_generation_attempts", "id"),
                ("reviewer_batch_attempt_id", "answer_contract_generation_attempts", "id"),
            },
            "agent_runs": {
                ("batch_attempt_id", "answer_contract_generation_attempts", "id")
            },
            "answer_contracts": {
                ("generator_batch_attempt_id", "answer_contract_generation_attempts", "id"),
                ("review_batch_attempt_id", "answer_contract_generation_attempts", "id"),
            },
        }
        for table, required in expected.items():
            actual = {
                (row[3], row[2], row[4])
                for row in self.conn.execute(f"pragma foreign_key_list({table})")
            }
            self.assertTrue(required <= actual, (table, required - actual))

        self._seed_question_authority()
        self._insert_run()
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_run(
                run_id="ACGR-FULL",
                parent="ACGR-MISSING",
                kind="full1120",
            )
            self.conn.commit()
        self.conn.rollback()
        self.conn.execute(
            """
            insert into answer_contract_generation_run_items(
              id, run_id, ordinal, question_id, item_version,
              question_digest_sha256, node_id, kind, effective_evidence_role,
              effective_evidence_role_policy_version, review_record_id,
              created_at, updated_at
            ) values (
              'ITEM-FK','ACGR-1',0,'Q-1','v1','digest','NODE-1',
              'standard_example','direct',?,'QRR-1',
              '2026-07-15T00:00:00+00:00','2026-07-15T00:00:00+00:00'
            )
            """,
            (batch.EFFECTIVE_EVIDENCE_ROLE_POLICY_VERSION,),
        )
        self.conn.commit()
        for column in (
            "designer_batch_attempt_id",
            "reviewer_batch_attempt_id",
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(
                    f"update answer_contract_generation_run_items set {column}='ACBA-MISSING' where id='ITEM-FK'"
                )
            self.conn.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                insert into agent_runs(
                  id, batch_attempt_id, agent_key, engine_type, phase,
                  trigger, status, created_at
                ) values (
                  'AR-FK','ACBA-MISSING','agent','internal_learning_agent',
                  'phase','trigger','rejected','2026-07-15T00:00:00+00:00'
                )
                """
            )
        self.conn.rollback()
        for column, row_id in (
            ("generator_batch_attempt_id", "AC-FK-G"),
            ("review_batch_attempt_id", "AC-FK-R"),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(
                    f"""
                    insert into answer_contracts(
                      id, stable_contract_id, question_id, item_version,
                      contract_digest_sha256, {column}, created_at, updated_at
                    ) values (
                      ?, 'AC-Q-1','Q-1','v1','contract-digest','ACBA-MISSING',
                      '2026-07-15T00:00:00+00:00','2026-07-15T00:00:00+00:00'
                    )
                    """,
                    (row_id,),
                )
            self.conn.rollback()

    def test_schema_authority_report_marks_legacy_missing_fk_as_migration_required(self):
        conn = sqlite3.connect(":memory:")
        try:
            for table in (
                "answer_contract_generation_runs",
                "answer_contract_generation_run_items",
                "answer_contract_generation_attempts",
                "agent_runs",
                "answer_contracts",
            ):
                conn.execute(f"create table {table}(id text primary key)")
            report = batch.batch_schema_authority_report(conn)
            self.assertEqual("migration_required", report["status"])
            self.assertTrue(report["missing_foreign_keys"])
        finally:
            conn.close()

    def test_router_observer_absent_is_behaviorally_identical(self):
        route, schema = self._route_and_schema()
        with mock.patch.object(
            model_router,
            "call_responses",
            return_value={"output_text": '{"ok":true}'},
        ) as call:
            result = model_router.call_structured_json(
                route, {"input": []}, schema=schema
            )
        self.assertEqual({"ok": True}, result.value)
        self.assertEqual(1, call.call_count)

    def test_router_observer_records_started_finished_and_fallback_count(self):
        claim = self._seed_attempt(status="provider_calling")
        context = batch.load_batch_attempt_context(
            self.conn,
            batch_attempt_id="ACBA-1",
            claim=claim,
            expected_role="designer",
        )
        route, schema = self._route_and_schema(provider="deepseek")
        observer = _Observer()
        calls = []

        def fake_call(_route, _payload):
            calls.append(1)
            if len(calls) == 1:
                raise model_router.ModelCallError(
                    "response_format.type json_object is not supported"
                )
            return {"output_text": '{"ok":true}'}

        with mock.patch.object(model_router, "call_responses", side_effect=fake_call):
            with batch.bind_batch_attempt_transport(context, observer):
                result = model_router.call_structured_json(
                    route, {"input": []}, schema=schema
                )
        self.assertEqual({"ok": True}, result.value)
        self.assertEqual([0, 1], [value.candidate_ordinal for value in observer.started])
        self.assertEqual(2, len(observer.finished))
        self.assertEqual(
            ["retryable_failure", "response_received"],
            [value.outcome for _context, value in observer.finished],
        )

    @staticmethod
    def _route_and_schema(provider="openai"):
        route = model_router.ModelRoute(
            agent_key="test_agent",
            task="test_task",
            provider=provider,
            model="gpt-5.5" if provider == "openai" else "deepseek-test",
            model_alias="gpt-5.5" if provider == "openai" else "deepseek-test",
            base_url="https://example.invalid/v1",
            api_key="test-key",
            timeout_seconds=10,
            model_params={},
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        return route, schema


if __name__ == "__main__":
    unittest.main()
