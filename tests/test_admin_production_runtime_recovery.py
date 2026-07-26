from __future__ import annotations

import json
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from learning_system import model_router
from learning_system.admin import production_workflow
from learning_system.admin import semantic_collision
from learning_system.admin.production_attempt_state import ProductionAttemptLedger
from learning_system.admin.semantic_collision import build_semantic_collision_board


class AdminProductionRuntimeRecoveryTests(unittest.TestCase):
    def test_workflow_report_writes_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            production_workflow.os,
            "replace",
            wraps=production_workflow.os.replace,
        ) as replace:
            root = Path(tmp)
            production_workflow.write_slot_production_workflow_report(
                {"workflow_id": "WF-atomic", "status": "WORKFLOW_STAGED", "steps": []},
                root=root,
                apply=True,
            )
            production_workflow.write_batch_production_workflow_report(
                {"batch_id": "BATCH-atomic", "status": "BATCH_COMPLETED", "slot_workflows": []},
                root=root,
                apply=True,
            )

        self.assertEqual(4, replace.call_count)

    def _collision_candidate(self, root: Path, item_id: str = "NEW") -> Path:
        path = root / f"{item_id}.candidate.json"
        path.write_text(
            json.dumps(
                {
                    "item": {
                        "id": item_id,
                        "node_id": "M-G7-NUMBER-LINE",
                        "question_type": "number_line_position_distance",
                        "prompt": f"candidate {item_id}",
                        "quality": {"structure_fingerprint": f"fp-{item_id}"},
                    }
                }
            ),
            encoding="utf-8",
        )
        return path

    def _write_collision_receipt(
        self,
        root: Path,
        candidate_path: Path,
        *,
        item_id: str,
    ) -> dict[str, object]:
        candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate_item = dict(candidate_payload["item"])
        candidate_sha = hashlib.sha256(
            json.dumps(candidate_item, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        candidate_file_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
        binding = {
            "item_id": item_id,
            "candidate_path": str(candidate_path),
            "candidate_sha256": candidate_sha,
            "candidate_file_sha256": candidate_file_sha,
        }
        candidate_set_sha = hashlib.sha256(
            json.dumps(
                [
                    {
                        "item_id": item_id,
                        "candidate_sha256": candidate_sha,
                        "candidate_file_sha256": candidate_file_sha,
                    }
                ],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        decision = {
            "candidate_item_id": item_id,
            "decision": "PASS",
            "confidence": 0.95,
            "collisions": [],
            "summary": "No semantic collision.",
            "decision_source": "live_model_board",
            "candidate_sha256": candidate_sha,
            "candidate_file_sha256": candidate_file_sha,
        }
        empty_snapshot_sha = hashlib.sha256(
            json.dumps([], ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        path = root / "collision.json"
        report = {
            "schema_version": "2026-07-25.codex-admin.semantic-collision-board.v1",
            "status": "PASS",
            "provider_mode": "live_model",
            "write_applied": True,
            "candidate_bindings": [binding],
            "candidate_set_sha256": candidate_set_sha,
            "candidate_decisions": {item_id: decision},
            "base_staged_bank_sha256": hashlib.sha256(b"").hexdigest(),
            "base_staged_snapshot_sha256": empty_snapshot_sha,
            "base_staged_item_bindings": [],
            "model_evidence": {
                "provider_mode": "live_model",
                "raw_response_sha256": "9" * 64,
                "route": {"structured_json_mode": "json_schema"},
                "transport_attempts": [],
            },
            "semantic_collision_json_path": str(path),
        }
        path.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        report["semantic_collision_json_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return report

    def _collision_result(self, decisions: list[dict]) -> model_router.StructuredJSONResult:
        value = {"decisions": decisions, "batch_summary": "bounded review"}
        return model_router.StructuredJSONResult(
            value=value,
            mode="json_schema",
            raw_response={"output_text": json.dumps(value)},
            endpoint="responses",
        )

    def test_collision_receipt_binds_candidates_set_and_base_bank_and_revalidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._collision_candidate(root)
            bank = root / "staged.json"
            bank.write_text(json.dumps({"items": []}), encoding="utf-8")
            candidate_file_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
            bank_sha256 = hashlib.sha256(bank.read_bytes()).hexdigest()
            result = self._collision_result(
                [
                    {
                        "candidate_item_id": "NEW",
                        "decision": "PASS",
                        "confidence": 0.97,
                        "collisions": [],
                        "summary": "distinct",
                    }
                ]
            )
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch.object(
                model_router, "call_structured_json", return_value=result
            ):
                report = semantic_collision.build_semantic_collision_board(
                    root=root,
                    candidate_paths=[candidate],
                    staged_bank_path=bank,
                )
            written = semantic_collision.write_semantic_collision_board(report, root=root, apply=True)
            validated = semantic_collision.validate_semantic_collision_receipt(
                root=root,
                receipt_path=root / written["semantic_collision_json_path"],
                candidate_path=candidate,
                staged_bank_path=bank,
                expected_receipt_sha256=written["semantic_collision_json_sha256"],
            )

        self.assertEqual(candidate_file_sha256, report["candidate_bindings"][0]["candidate_file_sha256"])
        self.assertRegex(report["candidate_set_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(bank_sha256, report["base_staged_bank_sha256"])
        self.assertEqual("PASS", validated["decision"]["decision"])

    def test_collision_receipt_cannot_hide_items_from_matching_base_bank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._collision_candidate(root)
            bank = root / "staged.json"
            bank.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "BASE-1",
                                "node_id": "M-G7-NUMBER-LINE",
                                "question_type": "number_line_position_distance",
                                "prompt": "base question",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = self._collision_result(
                [
                    {
                        "candidate_item_id": "NEW",
                        "decision": "PASS",
                        "confidence": 0.97,
                        "collisions": [],
                        "summary": "distinct",
                    }
                ]
            )
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch.object(
                model_router, "call_structured_json", return_value=result
            ):
                report = semantic_collision.build_semantic_collision_board(
                    root=root,
                    candidate_paths=[candidate],
                    staged_bank_path=bank,
                )
            written = semantic_collision.write_semantic_collision_board(
                report,
                root=root,
                apply=True,
            )
            receipt_path = root / written["semantic_collision_json_path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["base_staged_item_bindings"] = []
            receipt["base_staged_snapshot_sha256"] = hashlib.sha256(
                json.dumps([], ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "BASE_STAGED_BANK_BINDINGS_MISMATCH"):
                semantic_collision.validate_semantic_collision_receipt(
                    root=root,
                    receipt_path=receipt_path,
                    candidate_path=candidate,
                    staged_bank_path=bank,
                    expected_receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                )

    def test_collision_board_fails_closed_for_low_confidence_unknown_and_self_reference(self) -> None:
        cases = [
            (
                {
                    "candidate_item_id": "NEW",
                    "decision": "PASS",
                    "confidence": 0.4,
                    "collisions": [],
                    "summary": "uncertain",
                },
                "semantic_collision_low_confidence",
            ),
            (
                {
                    "candidate_item_id": "NEW",
                    "decision": "COLLISION",
                    "confidence": 0.97,
                    "collisions": [{"item_id": "UNKNOWN", "reason": "outside board"}],
                    "summary": "unknown ref",
                },
                "semantic_collision_reference_out_of_scope",
            ),
            (
                {
                    "candidate_item_id": "NEW",
                    "decision": "COLLISION",
                    "confidence": 0.97,
                    "collisions": [{"item_id": "NEW", "reason": "self"}],
                    "summary": "self ref",
                },
                "semantic_collision_self_reference",
            ),
        ]
        for decision, expected_code in cases:
            with self.subTest(expected_code=expected_code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                candidate = self._collision_candidate(root)
                bank = root / "staged.json"
                bank.write_text(json.dumps({"items": []}), encoding="utf-8")
                with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch.object(
                    model_router,
                    "call_structured_json",
                    return_value=self._collision_result([decision]),
                ):
                    report = semantic_collision.build_semantic_collision_board(
                        root=root,
                        candidate_paths=[candidate],
                        staged_bank_path=bank,
                    )

            self.assertEqual("BLOCKED", report["status"])
            self.assertIn(expected_code, {finding["code"] for finding in report["findings"]})

    def test_collision_reviewed_checkpoint_requires_receipt_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = ProductionAttemptLedger(
                root=root,
                artifact_root=root,
                staged_bank_path=root / "staged.json",
                requirement_id="REQ-1",
                slot_id="SLOT-1",
                max_content_attempts=3,
                apply=True,
            )
            with self.assertRaisesRegex(ValueError, "COLLISION_BINDING"):
                ledger.save_pending_stage_checkpoint(
                    {
                        "item_id": "NEW",
                        "candidate_path": "candidate.json",
                        "staging_decision_path": "staging.json",
                        "pending_stage": {},
                        "steps": [],
                        "collision_required": True,
                        "collision_reviewed": True,
                    }
                )

            with self.assertRaisesRegex(ValueError, "COLLISION_REQUIRED"):
                ledger.save_pending_stage_checkpoint(
                    {
                        "item_id": "NEW",
                        "candidate_path": "candidate.json",
                        "staging_decision_path": "staging.json",
                        "pending_stage": {},
                        "steps": [],
                        "collision_required": False,
                        "collision_reviewed": True,
                    }
                )

    def test_single_slot_recovery_runs_collision_board_before_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._write_attempt_plan(root)
            candidate = root / "candidate.json"
            staging_decision = root / "staging.json"
            candidate.write_text(json.dumps({"item": {"id": "CAND-1"}}), encoding="utf-8")
            staging_decision.write_text(json.dumps({"status": "STAGED_READY"}), encoding="utf-8")
            ledger = ProductionAttemptLedger(
                root=root,
                artifact_root=root,
                staged_bank_path=root / "staged.json",
                requirement_id="REQ-1",
                slot_id="SLOT-1",
                max_content_attempts=3,
                apply=True,
            )
            ledger.save_pending_stage_checkpoint(
                {
                    "item_id": "CAND-1",
                    "candidate_path": str(candidate),
                    "staging_decision_path": str(staging_decision),
                    "pending_stage": {
                        "candidate_path": str(candidate),
                        "staging_decision_path": str(staging_decision),
                    },
                    "steps": [],
                    "collision_required": True,
                    "collision_reviewed": False,
                }
            )
            collision_report = self._write_collision_receipt(
                root,
                candidate,
                item_id="CAND-1",
            )
            with mock.patch.object(
                production_workflow,
                "build_semantic_collision_board",
                return_value=dict(collision_report),
            ) as build_board, mock.patch.object(
                production_workflow,
                "write_semantic_collision_board",
                return_value=dict(collision_report),
            ), mock.patch.object(
                production_workflow,
                "build_and_write_stage_candidate_receipt",
                return_value={"status": "STAGED_WRITABLE", "item_id": "CAND-1"},
            ) as stage:
                report = production_workflow.run_slot_production_workflow(
                    root=root,
                    artifact_root=root,
                    generation_plan_path=plan,
                    staged_bank_path=root / "staged.json",
                    apply=True,
                )

        self.assertEqual("WORKFLOW_STAGED", report["status"])
        build_board.assert_called_once()
        self.assertEqual(
            root / "collision.json",
            stage.call_args.kwargs["semantic_collision_receipt_path"],
        )

    def _write_attempt_plan(self, root: Path) -> Path:
        plan = root / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "slot_id": "SLOT-1",
                    "question_requirement_id": "REQ-1",
                    "bounded_candidate_packet": {
                        "question_requirement": {
                            "slot_id": "SLOT-1",
                            "question_requirement_id": "REQ-1",
                            "node_id": "M-TEST",
                            "family_id": "test_family",
                            "difficulty": "L2",
                            "evidence_goal": "测试恢复边界",
                            "must_include": ["测试恢复边界"],
                            "must_not_include": [],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return plan

    def test_attempt_budget_survives_bank_change_and_recovers_pending_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank = root / "staged.json"
            bank.write_text(json.dumps({"items": []}), encoding="utf-8")
            first = ProductionAttemptLedger(
                root=root,
                artifact_root=root,
                staged_bank_path=bank,
                requirement_id="REQ-1",
                slot_id="SLOT-1",
                max_content_attempts=3,
                apply=True,
            )

            lease = first.begin_content_attempt()
            self.assertEqual(1, lease["content_attempt"])
            first_digest = first.snapshot()["staged_bank_digest"]

            bank.write_text(json.dumps({"items": [{"id": "OTHER"}]}), encoding="utf-8")
            resumed = ProductionAttemptLedger(
                root=root,
                artifact_root=root,
                staged_bank_path=bank,
                requirement_id="REQ-1",
                slot_id="SLOT-1",
                max_content_attempts=3,
                apply=True,
            )
            recovered = resumed.begin_content_attempt()
            self.assertEqual(lease["lease_id"], recovered["lease_id"])
            self.assertEqual(1, recovered["content_attempt"])
            self.assertEqual(1, resumed.snapshot()["crash_recovery_count"])

            resumed.record_provider_transport_attempts(
                recovered,
                stage="generate_candidate",
                attempts=[
                    {"outcome": "retryable_failure", "status_code": 502},
                    {"outcome": "response_received"},
                ],
            )
            resumed.complete_content_attempt(recovered, consumed=True, outcome="candidate_rejected")
            next_lease = resumed.begin_content_attempt()
            state = resumed.snapshot()

        self.assertEqual(2, next_lease["content_attempt"])
        self.assertEqual(1, state["content_attempts_consumed"])
        self.assertEqual(2, state["provider_transport_attempt_count"])
        self.assertEqual(1, state["provider_transport_retry_count"])
        self.assertEqual(first_digest, state["staged_bank_digest"])

    def test_successful_model_transport_evidence_is_counted_from_route_metadata(self) -> None:
        attempts = [
            {"outcome": "retryable_failure", "status_code": 502},
            {"outcome": "response_received", "status_code": 200},
        ]

        extracted = production_workflow._transport_attempts(
            {"status": "PASS", "route": {"transport_attempts": attempts}}
        )

        self.assertEqual(attempts, extracted)

    def test_expert_transport_failure_resumes_same_candidate_without_content_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._write_attempt_plan(root)
            candidate = root / "candidate.json"
            candidate.write_text(json.dumps({"item": {"id": "CAND-1"}}), encoding="utf-8")
            generated = {
                "status": "CANDIDATE_READY_FOR_EXPERT_REVIEW",
                "item_id": "CAND-1",
                "candidate_json_path": str(candidate),
                "machine_report": {"status": "SELF_CHECKED_PASS", "item_id": "CAND-1"},
                "route": {"transport_attempts": [{"outcome": "response_received"}]},
            }
            model_error = {
                "status": "BLOCKED_MODEL_ERROR",
                "item_id": "CAND-1",
                "transport_meta": {
                    "transport_attempts": [
                        {"outcome": "retryable_failure", "status_code": 502}
                    ]
                },
                "model_error": {"message": "temporary 502"},
            }
            model_pass = {
                "status": "PASS",
                "item_id": "CAND-1",
                "route": {"transport_attempts": [{"outcome": "response_received"}]},
            }
            qa_reject = {"status": "NEEDS_FIX", "item_id": "CAND-1"}

            with mock.patch.object(
                production_workflow,
                "build_generated_candidate_from_plan",
                return_value=generated,
            ) as generate, mock.patch.object(
                production_workflow,
                "write_generated_candidate_artifact",
                side_effect=lambda report, **_kwargs: dict(report),
            ), mock.patch.object(
                production_workflow,
                "write_production_report",
                side_effect=lambda report, **_kwargs: dict(report),
            ), mock.patch.object(
                production_workflow,
                "build_candidate_expert_review",
                return_value={"status": "PASS", "item_id": "CAND-1"},
            ), mock.patch.object(
                production_workflow,
                "write_expert_quality_review",
                side_effect=lambda report, **_kwargs: dict(report),
            ), mock.patch.object(
                production_workflow,
                "build_candidate_model_expert_board_review",
                side_effect=[model_error, model_pass],
            ), mock.patch.object(
                production_workflow,
                "write_model_expert_board_review",
                side_effect=lambda report, **_kwargs: dict(report),
            ), mock.patch.object(
                production_workflow,
                "build_candidate_qa_contract_check",
                return_value=qa_reject,
            ), mock.patch.object(
                production_workflow,
                "write_candidate_qa_contract_check",
                side_effect=lambda report, **_kwargs: dict(report),
            ):
                first = production_workflow.run_slot_production_workflow(
                    root=root,
                    artifact_root=root,
                    generation_plan_path=plan,
                    staged_bank_path=root / "staged.json",
                    max_attempts=1,
                    apply=True,
                )
                second = production_workflow.run_slot_production_workflow(
                    root=root,
                    artifact_root=root,
                    generation_plan_path=plan,
                    staged_bank_path=root / "staged.json",
                    max_attempts=1,
                    apply=True,
                )

        self.assertEqual("BLOCKED_MODEL_ERROR", first["status"])
        self.assertEqual("NEEDS_FIX", second["status"])
        self.assertEqual(1, generate.call_count)
        self.assertEqual(0, second["attempt_count"])
        self.assertEqual(1, second["content_attempt_state"]["content_attempts_consumed"])
        self.assertEqual(1, second["content_attempt_state"]["provider_transport_retry_count"])

    def test_expired_absolute_deadline_interrupts_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.json"
            plan.write_text(
                json.dumps({"slot_id": "SLOT-1", "question_requirement_id": "REQ-1"}),
                encoding="utf-8",
            )
            with mock.patch.object(
                production_workflow,
                "build_generated_candidate_from_plan",
                side_effect=AssertionError("generation must not start after deadline"),
            ):
                report = production_workflow.run_slot_production_workflow(
                    root=root,
                    artifact_root=root,
                    generation_plan_path=plan,
                    staged_bank_path=root / "staged.json",
                    max_attempts=3,
                    absolute_deadline_monotonic=time.monotonic() - 0.01,
                    apply=True,
                )

        self.assertEqual("INTERRUPTED_DEADLINE", report["status"])
        self.assertEqual("generate_candidate", report["interrupted_before_stage"])
        self.assertEqual(0, report["attempt_count"])

    def test_batch_checkpoint_cannot_bypass_pending_collision_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._write_attempt_plan(root)
            candidate = root / "candidate.json"
            staging = root / "staging.json"
            candidate.write_text(json.dumps({"item": {"id": "CAND-1"}}), encoding="utf-8")
            staging.write_text(json.dumps({"status": "STAGED_READY"}), encoding="utf-8")
            ledger = ProductionAttemptLedger(
                root=root,
                artifact_root=root,
                staged_bank_path=root / "staged.json",
                requirement_id="REQ-1",
                slot_id="SLOT-1",
                max_content_attempts=3,
                apply=True,
            )
            ledger.save_pending_stage_checkpoint(
                {
                    "item_id": "CAND-1",
                    "candidate_path": str(candidate),
                    "staging_decision_path": str(staging),
                    "pending_stage": {
                        "candidate_path": str(candidate),
                        "staging_decision_path": str(staging),
                    },
                    "steps": [],
                    "collision_required": True,
                    "collision_reviewed": False,
                }
            )
            with mock.patch.object(
                production_workflow,
                "build_and_write_stage_candidate_receipt",
                side_effect=AssertionError("staging must wait for collision evidence"),
            ), mock.patch.object(
                production_workflow,
                "build_generated_candidate_from_plan",
                side_effect=AssertionError("checkpoint recovery must not regenerate"),
            ):
                report = production_workflow.run_slot_production_workflow(
                    root=root,
                    artifact_root=root,
                    generation_plan_path=plan,
                    staged_bank_path=root / "staged.json",
                    max_attempts=3,
                    apply=True,
                    defer_stage=True,
                )

        self.assertEqual("WORKFLOW_READY_FOR_COLLISION_REVIEW", report["status"])
        self.assertFalse(report["staging_allowed"])

    def test_collision_approved_checkpoint_resumes_serial_stage_without_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._write_attempt_plan(root)
            candidate = root / "candidate.json"
            staging = root / "staging.json"
            candidate.write_text(json.dumps({"item": {"id": "CAND-1"}}), encoding="utf-8")
            staging.write_text(json.dumps({"status": "STAGED_READY"}), encoding="utf-8")
            collision_report = self._write_collision_receipt(
                root,
                candidate,
                item_id="CAND-1",
            )
            collision_decision = collision_report["candidate_decisions"]["CAND-1"]
            ledger = ProductionAttemptLedger(
                root=root,
                artifact_root=root,
                staged_bank_path=root / "staged.json",
                requirement_id="REQ-1",
                slot_id="SLOT-1",
                max_content_attempts=3,
                apply=True,
            )
            ledger.save_pending_stage_checkpoint(
                {
                    "item_id": "CAND-1",
                    "candidate_path": str(candidate),
                    "staging_decision_path": str(staging),
                    "pending_stage": {
                        "candidate_path": str(candidate),
                        "staging_decision_path": str(staging),
                    },
                    "steps": [],
                    "collision_required": True,
                    "collision_reviewed": True,
                    "semantic_collision_json_path": str(root / "collision.json"),
                    "semantic_collision_json_sha256": collision_report[
                        "semantic_collision_json_sha256"
                    ],
                    "candidate_set_sha256": collision_report["candidate_set_sha256"],
                    "base_staged_bank_sha256": collision_report[
                        "base_staged_bank_sha256"
                    ],
                    "base_staged_snapshot_sha256": collision_report[
                        "base_staged_snapshot_sha256"
                    ],
                    "collision_decision": collision_decision,
                }
            )
            with mock.patch.object(
                production_workflow,
                "build_generated_candidate_from_plan",
                side_effect=AssertionError("approved checkpoint must not regenerate"),
            ), mock.patch.object(
                production_workflow,
                "build_and_write_stage_candidate_receipt",
                return_value={"status": "STAGED_WRITABLE", "item_id": "CAND-1"},
            ) as stage:
                report = production_workflow.run_slot_production_workflow(
                    root=root,
                    artifact_root=root,
                    generation_plan_path=plan,
                    staged_bank_path=root / "staged.json",
                    max_attempts=3,
                    apply=True,
                )

            recovered = ledger.snapshot()

        self.assertEqual("WORKFLOW_STAGED", report["status"])
        self.assertEqual(1, stage.call_count)
        self.assertEqual(
            root / "collision.json",
            stage.call_args.kwargs["semantic_collision_receipt_path"],
        )
        self.assertEqual(
            collision_report["semantic_collision_json_sha256"],
            stage.call_args.kwargs["semantic_collision_receipt_sha256"],
        )
        self.assertIsNone(recovered["pending_stage_checkpoint"])

    def test_recovery_rejects_checkpoint_collision_snapshot_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._write_attempt_plan(root)
            candidate = root / "candidate.json"
            staging = root / "staging.json"
            candidate.write_text(json.dumps({"item": {"id": "CAND-1"}}), encoding="utf-8")
            staging.write_text(json.dumps({"status": "STAGED_READY"}), encoding="utf-8")
            collision_report = self._write_collision_receipt(
                root,
                candidate,
                item_id="CAND-1",
            )
            ledger = ProductionAttemptLedger(
                root=root,
                artifact_root=root,
                staged_bank_path=root / "staged.json",
                requirement_id="REQ-1",
                slot_id="SLOT-1",
                max_content_attempts=3,
                apply=True,
            )
            ledger.save_pending_stage_checkpoint(
                {
                    "item_id": "CAND-1",
                    "candidate_path": str(candidate),
                    "staging_decision_path": str(staging),
                    "pending_stage": {
                        "candidate_path": str(candidate),
                        "staging_decision_path": str(staging),
                    },
                    "steps": [],
                    "collision_required": True,
                    "collision_reviewed": True,
                    "semantic_collision_json_path": str(root / "collision.json"),
                    "semantic_collision_json_sha256": collision_report[
                        "semantic_collision_json_sha256"
                    ],
                    "candidate_set_sha256": collision_report["candidate_set_sha256"],
                    "base_staged_bank_sha256": collision_report[
                        "base_staged_bank_sha256"
                    ],
                    "base_staged_snapshot_sha256": "f" * 64,
                    "collision_decision": collision_report["candidate_decisions"]["CAND-1"],
                }
            )
            with mock.patch.object(
                production_workflow,
                "build_and_write_stage_candidate_receipt",
                side_effect=AssertionError("mismatched checkpoint must not reach staging"),
            ) as stage:
                report = production_workflow.run_slot_production_workflow(
                    root=root,
                    artifact_root=root,
                    generation_plan_path=plan,
                    staged_bank_path=root / "staged.json",
                    max_attempts=3,
                    apply=True,
                )

        self.assertEqual("WORKFLOW_BLOCKED_STAGE_EXCEPTION", report["status"])
        stage.assert_not_called()

    def test_recovery_stage_exception_is_normalized_to_blocked_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._write_attempt_plan(root)
            candidate = self._collision_candidate(root, "CAND-1")
            staging = root / "staging.json"
            staging.write_text(json.dumps({"status": "STAGED_READY"}), encoding="utf-8")
            ledger = ProductionAttemptLedger(
                root=root,
                artifact_root=root,
                staged_bank_path=root / "staged.json",
                requirement_id="REQ-1",
                slot_id="SLOT-1",
                max_content_attempts=3,
                apply=True,
            )
            ledger.save_pending_stage_checkpoint(
                {
                    "item_id": "CAND-1",
                    "candidate_path": str(candidate),
                    "staging_decision_path": str(staging),
                    "pending_stage": {
                        "candidate_path": str(candidate),
                        "staging_decision_path": str(staging),
                    },
                    "steps": [],
                    "collision_required": True,
                    "collision_reviewed": True,
                    "semantic_collision_json_path": "collision.json",
                    "semantic_collision_json_sha256": "1" * 64,
                    "candidate_set_sha256": "2" * 64,
                    "base_staged_bank_sha256": "3" * 64,
                    "base_staged_snapshot_sha256": "4" * 64,
                    "collision_decision": {
                        "candidate_item_id": "CAND-1",
                        "decision": "PASS",
                    },
                }
            )
            with mock.patch.object(
                production_workflow,
                "build_and_write_stage_candidate_receipt",
                side_effect=RuntimeError("disk unavailable"),
            ):
                report = production_workflow.run_slot_production_workflow(
                    root=root,
                    artifact_root=root,
                    generation_plan_path=plan,
                    staged_bank_path=root / "staged.json",
                    apply=True,
                )

        self.assertEqual("WORKFLOW_BLOCKED_STAGE_EXCEPTION", report["status"])
        self.assertEqual("BLOCKED_STAGE_EXCEPTION", report["staged_receipt"]["status"])
        self.assertTrue(report["staged_receipt"]["stage_receipt_json_path"])

    def test_one_live_board_blocks_semantic_duplicate_with_different_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = root / "candidate.json"
            candidate_path.write_text(
                json.dumps(
                    {
                        "item": {
                            "id": "NEW",
                            "node_id": "M-G7-NUMBER-LINE",
                            "question_type": "number_line_position_distance",
                            "prompt": "点A向右移动3格后到2，点A原来表示什么数？",
                            "quality": {"structure_fingerprint": "new-hash"},
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            bank = root / "staged.json"
            bank.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "OLD",
                                "node_id": "M-G7-NUMBER-LINE",
                                "question_type": "number_line_position_distance",
                                "prompt": "一个点向右走3个单位到达2，起点是多少？",
                                "quality": {"structure_fingerprint": "old-hash"},
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            model_value = {
                "decisions": [
                    {
                        "candidate_item_id": "NEW",
                        "decision": "COLLISION",
                        "confidence": 0.98,
                        "collisions": [
                            {
                                "item_id": "OLD",
                                "reason": "同一未知起点、同一右移3格、同一终点2，仅改写措辞。",
                            }
                        ],
                        "summary": "不是有意义的新诊断结构。",
                    }
                ],
                "batch_summary": "发现一项语义碰撞。",
            }
            result = model_router.StructuredJSONResult(
                value=model_value,
                mode="json_schema",
                raw_response={"output_text": json.dumps(model_value, ensure_ascii=False)},
                endpoint="responses",
            )
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch.object(
                model_router, "call_structured_json", return_value=result
            ):
                report = build_semantic_collision_board(
                    root=root,
                    candidate_paths=[candidate_path],
                    staged_bank_path=bank,
                )

        self.assertEqual("COLLISION_FOUND", report["status"])
        self.assertEqual("live_model", report["provider_mode"])
        decision = report["candidate_decisions"]["NEW"]
        self.assertEqual("COLLISION", decision["decision"])
        self.assertNotEqual(
            decision["candidate_structure_fingerprint"],
            report["comparison_items"][0]["structure_fingerprint"],
        )

    def test_parallel_batch_defers_stage_until_serial_collision_review(self) -> None:
        stage_order: list[str] = []
        board_calls: list[list[str]] = []

        def prepared(plan_path: Path) -> dict:
            item_id = plan_path.stem
            return {
                "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
                "workflow_id": f"WF-{item_id}",
                "status": "WORKFLOW_READY_FOR_COLLISION_REVIEW",
                "generation_plan_path": str(plan_path),
                "attempt_count": 1,
                "item_id": item_id,
                "elapsed_seconds": 0.01,
                "steps": [],
                "pending_stage": {
                    "candidate_path": f"{item_id}.candidate.json",
                    "staging_decision_path": f"{item_id}.staging.json",
                },
                "staging_allowed": False,
                "activation_allowed": False,
                "activation_implication": "does_not_authorize_activation",
            }

        def fake_collision_board(**kwargs):
            item_ids = [Path(path).name.split(".")[0] for path in kwargs["candidate_paths"]]
            board_calls.append(item_ids)
            return {
                "schema_version": "2026-07-25.codex-admin.semantic-collision-board.v1",
                "status": "PASS",
                "candidate_decisions": {
                    item_id: {"candidate_item_id": item_id, "decision": "PASS", "collisions": []}
                    for item_id in item_ids
                },
                "finding_counts": {},
                "findings": [],
            }

        def fake_stage(**kwargs):
            item_id = Path(kwargs["candidate_path"]).name.split(".")[0]
            stage_order.append(item_id)
            return {"status": "STAGED_WRITABLE", "item_id": item_id}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            production_workflow,
            "run_slot_production_workflow",
            side_effect=lambda **kwargs: prepared(Path(kwargs["generation_plan_path"])),
        ), mock.patch.object(
            production_workflow,
            "build_semantic_collision_board",
            side_effect=fake_collision_board,
        ), mock.patch.object(
            production_workflow,
            "write_semantic_collision_board",
            side_effect=lambda report, **_kwargs: report,
        ), mock.patch.object(
            production_workflow,
            "build_and_write_stage_candidate_receipt",
            side_effect=fake_stage,
        ), mock.patch.object(
            production_workflow,
            "write_slot_production_workflow_report",
            side_effect=lambda report, **_kwargs: report,
        ):
            root = Path(tmp)
            report = production_workflow.run_batch_production_workflow(
                root=root,
                artifact_root=root,
                generation_plan_paths=[Path("one.json"), Path("two.json")],
                staged_bank_path=root / "staged.json",
                parallel_workers=2,
                generation_batch_size=1,
                max_runtime_seconds=10,
                apply=True,
            )

        self.assertEqual([["one", "two"]], board_calls)
        self.assertEqual(["one", "two"], stage_order)
        self.assertEqual("BATCH_COMPLETED", report["status"])

    def test_batch_deadline_prevents_new_serial_stage_after_collision_board(self) -> None:
        def prepared(plan_path: Path) -> dict:
            return {
                "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
                "workflow_id": "WF-one",
                "status": "WORKFLOW_READY_FOR_COLLISION_REVIEW",
                "generation_plan_path": str(plan_path),
                "attempt_count": 1,
                "item_id": "one",
                "elapsed_seconds": 0.01,
                "steps": [],
                "pending_stage": {
                    "candidate_path": "one.candidate.json",
                    "staging_decision_path": "one.staging.json",
                },
            }

        def slow_board(**_kwargs):
            time.sleep(0.02)
            return {
                "status": "PASS",
                "candidate_decisions": {
                    "one": {"candidate_item_id": "one", "decision": "PASS", "collisions": []}
                },
                "findings": [],
                "finding_counts": {},
            }

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            production_workflow,
            "run_slot_production_workflow",
            side_effect=lambda **kwargs: prepared(Path(kwargs["generation_plan_path"])),
        ), mock.patch.object(
            production_workflow,
            "build_semantic_collision_board",
            side_effect=slow_board,
        ), mock.patch.object(
            production_workflow,
            "write_semantic_collision_board",
            side_effect=lambda report, **_kwargs: report,
        ), mock.patch.object(
            production_workflow,
            "build_and_write_stage_candidate_receipt",
            side_effect=AssertionError("stage must not start after absolute deadline"),
        ), mock.patch.object(
            production_workflow,
            "write_slot_production_workflow_report",
            side_effect=lambda report, **_kwargs: report,
        ):
            root = Path(tmp)
            report = production_workflow.run_batch_production_workflow(
                root=root,
                artifact_root=root,
                generation_plan_paths=[Path("one.json")],
                staged_bank_path=root / "staged.json",
                max_runtime_seconds=0.005,
                apply=True,
            )

        self.assertEqual("BATCH_PARTIAL_BUDGET_EXHAUSTED", report["status"])
        self.assertEqual("INTERRUPTED_DEADLINE", report["slot_workflows"][0]["status"])

    def test_collision_board_exception_preserves_candidates_for_restart(self) -> None:
        prepared = {
            "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
            "workflow_id": "WF-one",
            "status": "WORKFLOW_READY_FOR_COLLISION_REVIEW",
            "generation_plan_path": "one.json",
            "attempt_count": 1,
            "item_id": "one",
            "elapsed_seconds": 0.01,
            "steps": [],
            "pending_stage": {
                "candidate_path": "one.candidate.json",
                "staging_decision_path": "one.staging.json",
            },
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            production_workflow,
            "run_slot_production_workflow",
            return_value=prepared,
        ), mock.patch.object(
            production_workflow,
            "build_semantic_collision_board",
            side_effect=RuntimeError("board transport crashed"),
        ), mock.patch.object(
            production_workflow,
            "build_and_write_stage_candidate_receipt",
            side_effect=AssertionError("unreviewed candidate must not stage"),
        ), mock.patch.object(
            production_workflow,
            "write_slot_production_workflow_report",
            side_effect=lambda report, **_kwargs: report,
        ):
            root = Path(tmp)
            report = production_workflow.run_batch_production_workflow(
                root=root,
                artifact_root=root,
                generation_plan_paths=[Path("one.json")],
                staged_bank_path=root / "staged.json",
                apply=True,
            )

        self.assertEqual("BATCH_COMPLETED_WITH_FAILURES", report["status"])
        self.assertEqual("WORKFLOW_BLOCKED_COLLISION_REVIEW", report["slot_workflows"][0]["status"])


if __name__ == "__main__":
    unittest.main()
