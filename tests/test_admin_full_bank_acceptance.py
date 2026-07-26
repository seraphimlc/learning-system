from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from learning_system.admin.full_bank_acceptance import build_full_bank_acceptance
from learning_system.admin.inventory import build_question_bank_inventory
from learning_system.admin.staging import staged_content_envelope_sha256


class AdminFullBankAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.node_id = "N1"
        self.family_id = "F1"
        self._write_json("data/knowledge_graphs/math/math_knowledge_graph_v2.json", {"nodes": [{"id": self.node_id, "name": "Node"}]})
        self._write_json("data/question_banks/v18/math_v18_sample_60.json", {"items": []})
        self._write_json(
            "data/question_banks/v18/question_type_taxonomy_v18.json",
            {"clusters": [{"cluster_id": "test", "families": [{"family_id": self.family_id}]}]},
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _digest_json(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _write_json(self, relative_path: str, payload: dict[str, Any]) -> tuple[Path, str]:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_review_artifact(self, relative_path: str, report: dict[str, Any]) -> str:
        _path, raw_sha = self._write_json(relative_path, report)
        return raw_sha

    def _base_item(self, item_id: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "item_version": "v1",
            "node_id": self.node_id,
            "question_type": self.family_id,
            "difficulty": "L2",
            "prompt": "计算 1+1，并说明理由。",
            "answer_format": "结果和理由。",
            "standard_answer": "2，因为 1+1=2。",
            "accepted_alternatives": [],
            "required_evidence": ["写出 1+1=2", "说明使用加法", "检查结果符合题意"],
            "key_score_points": [
                {
                    "key": "answer",
                    "points": 4,
                    "evidence": "得到 2",
                    "mastery_dimension": "calculation",
                },
                {
                    "key": "reason",
                    "points": 4,
                    "evidence": "说明加法关系",
                    "mastery_dimension": "process",
                },
                {
                    "key": "check",
                    "points": 2,
                    "evidence": "检查结果符合题意",
                    "mastery_dimension": "check",
                },
            ],
            "solution_steps": ["1+1=2"],
            "target_error_tags": ["calculation"],
            "rollback_candidates": [],
            "child_surface_design": {
                "task_focus_count": 1,
                "primary_task": "计算并说明一个必要理由。",
                "child_deliverables": ["写出结果", "说明一条必要理由"],
                "backend_evidence_targets": ["结果正确", "理由与结果一致"],
                "student_actions": {"primary": "compute_or_solve", "supporting": ["explain_core_relation"]},
                "interaction_requirements": {"response_kind": "short_text", "actions": []},
                "writing_burden": {
                    "burden_level": "light",
                    "estimated_response_lines": 2,
                    "why_necessary": "两行足以区分答案和理由。",
                },
                "visual_support": {"mode": "not_needed", "prompt_depends_on_visual": False, "asset_ref": ""},
                "language_surface": {
                    "natural_child_facing_chinese": True,
                    "respectful_age_appropriate": True,
                    "named_characters": [],
                    "short_explanation_requests": 1,
                },
                "distractor_design": {"distractors": []},
                "difficulty_alignment": {
                    "target_difficulty": "L2",
                    "diagnostic_breakpoint": "能否给出与答案一致的理由。",
                    "difficulty_source": "mathematical_structure",
                },
            },
            "quality": {
                "activation_eligible": False,
                "canonical_structure_fingerprint": f"FP-{item_id}",
            },
        }

    def _stage_item(
        self,
        candidate_item: dict[str, Any],
        *,
        include_qa_contract: bool = True,
        include_machine_artifact: bool = True,
        semantic_scope: dict[str, Any] | None = None,
        bind_semantic_to_contract: bool = True,
    ) -> tuple[dict[str, Any], str]:
        item_id = str(candidate_item["id"])
        node_id = str(candidate_item["node_id"])
        family_id = str(candidate_item.get("question_type") or candidate_item.get("question_family_id") or "")
        candidate_sha = self._digest_json(candidate_item)
        content_envelope_sha = staged_content_envelope_sha256(candidate_item)
        candidate_rel = f"data/admin/candidates/{item_id}.json"
        _candidate_path, candidate_file_sha = self._write_json(
            candidate_rel,
            {"schema_version": "candidate-artifact.v1", "candidate_sha256": candidate_sha, "item": candidate_item},
        )

        common_report = {
            "item_id": item_id,
            "node_id": node_id,
            "family_id": family_id,
            "candidate_sha256": candidate_sha,
            "source_path": candidate_rel,
            "source_file_sha256": candidate_file_sha,
            "finding_counts": {},
            "findings": [],
            "write_applied": True,
        }
        machine_rel = f"data/admin/production/{item_id}-machine.json"
        machine_report = {
            "schema_version": "2026-07-23.codex-admin.production-candidate-check.v1",
            "status": "SELF_CHECKED_PASS",
            "item_id": item_id,
            "node_id": node_id,
            "family_id": family_id,
            "candidate_sha256": candidate_sha,
            "finding_counts": {},
            "findings": [],
            "production_json_path": machine_rel,
            "write_applied": True,
        }
        machine_digest = self._write_review_artifact(machine_rel, machine_report)

        expert_rel = f"data/admin/reviews/{item_id}.json"
        expert_report = {
            **common_report,
            "schema_version": "2026-07-23.codex-admin.candidate-expert-review.v1",
            "status": "PASS",
            "review_json_path": expert_rel,
        }
        expert_digest = self._write_review_artifact(expert_rel, expert_report)

        model_rel = f"data/admin/model_expert_reviews/{item_id}.json"
        model_report = {
            **common_report,
            "schema_version": "2026-07-23.codex-admin.model-expert-board-review.v1",
            "status": "PASS",
            "provider_mode": "live_model",
            "model_expert_review_json_path": model_rel,
        }
        model_digest = self._write_review_artifact(model_rel, model_report)

        qa_contract_rel = f"data/admin/qa_contract_checks/{item_id}.json"
        qa_contract_report = {
            **common_report,
            "schema_version": "2026-07-24.codex-admin.candidate-qa-contract-check.v1",
            "gate_type": "deterministic_contract_check",
            "semantic_authority": False,
            "status": "PASS",
            "qa_contract_check_json_path": qa_contract_rel,
        }
        qa_contract_digest = self._write_review_artifact(qa_contract_rel, qa_contract_report)

        qa_rel = f"data/admin/qa/{item_id}.json"
        scope = semantic_scope or {
            "support_only": False,
            "not_for_activation": False,
            "exclude_from_coverage": False,
            "reasons": [],
        }
        qa_report = {
            **common_report,
            "schema_version": "2026-07-23.codex-admin.candidate-qa-review.v1",
            "gate_type": "live_model_semantic_qa",
            "status": "PASS",
            "provider_mode": "live_model",
            "qa_contract_report_sha256": qa_contract_digest if bind_semantic_to_contract else "0" * 64,
            "scope": scope,
            "route": {
                "raw_response_sha256": "a" * 64,
                "structured_json_mode": "json_schema",
            },
            "prompt_meta": {
                "rendered_prompt_sha256": "b" * 64,
                "response_schema_sha256": "c" * 64,
            },
            "status_normalization": {
                "authority": "deterministic_from_profile_verdicts",
                "model_overall_status_is_advisory": True,
            },
            "qa_json_path": qa_rel,
        }
        qa_digest = self._write_review_artifact(qa_rel, qa_report)

        receipts = {
            "machine_check": {
                "role": "machine_contract_check",
                "schema_version": machine_report["schema_version"],
                "status": "SELF_CHECKED_PASS",
                "item_id": item_id,
                "node_id": node_id,
                "family_id": family_id,
                "candidate_sha256": candidate_sha,
                "content_envelope_sha256": content_envelope_sha,
                "source_path": "",
                "source_file_sha256": "",
                "report_path": machine_rel if include_machine_artifact else "",
                "report_sha256": machine_digest,
            },
            "deterministic_expert_review": {
                "role": "deterministic_expert_review",
                "schema_version": expert_report["schema_version"],
                "status": "PASS",
                "item_id": item_id,
                "node_id": node_id,
                "family_id": family_id,
                "candidate_sha256": candidate_sha,
                "content_envelope_sha256": content_envelope_sha,
                "source_path": candidate_rel,
                "source_file_sha256": candidate_file_sha,
                "report_path": expert_rel,
                "report_sha256": expert_digest,
            },
            "model_expert_board_review": {
                "role": "live_model_expert_board_review",
                "schema_version": model_report["schema_version"],
                "status": "PASS",
                "item_id": item_id,
                "node_id": node_id,
                "family_id": family_id,
                "candidate_sha256": candidate_sha,
                "content_envelope_sha256": content_envelope_sha,
                "source_path": candidate_rel,
                "source_file_sha256": candidate_file_sha,
                "report_path": model_rel,
                "report_sha256": model_digest,
            },
            "guanzhi_qa_review": {
                "role": "live_model_semantic_qa_review",
                "schema_version": qa_report["schema_version"],
                "status": "PASS",
                "item_id": item_id,
                "node_id": node_id,
                "family_id": family_id,
                "candidate_sha256": candidate_sha,
                "content_envelope_sha256": content_envelope_sha,
                "source_path": candidate_rel,
                "source_file_sha256": candidate_file_sha,
                "report_path": qa_rel,
                "report_sha256": qa_digest,
                "gate_type": "live_model_semantic_qa",
                "provider_mode": "live_model",
                "scope": scope,
            },
        }
        qa_contract_receipt = {
            "role": "deterministic_qa_contract_check",
            "schema_version": qa_contract_report["schema_version"],
            "status": "PASS",
            "item_id": item_id,
            "node_id": node_id,
            "family_id": family_id,
            "candidate_sha256": candidate_sha,
            "content_envelope_sha256": content_envelope_sha,
            "source_path": candidate_rel,
            "source_file_sha256": candidate_file_sha,
            "report_path": qa_contract_rel,
            "report_sha256": qa_contract_digest,
            "gate_type": "deterministic_contract_check",
        }
        staged_review_receipts = copy.deepcopy(receipts)
        staged_review_receipts["guanzhi_qa_review"]["role"] = "guanzhi_qa_review"
        staged_review_receipts["guanzhi_qa_review"].pop("gate_type", None)
        staged_review_receipts["guanzhi_qa_review"].pop("provider_mode", None)
        staged_review_receipts["guanzhi_qa_review"].pop("scope", None)
        decision_rel = f"data/admin/production/{item_id}.json"
        decision = {
            "schema_version": "2026-07-23.codex-admin.production-staging-decision.v1",
            "status": "STAGED_READY",
            "staging_allowed": True,
            "candidate_sha256": candidate_sha,
            "machine_report_sha256": machine_digest,
            "expert_report_sha256": expert_digest,
            "model_expert_report_sha256": model_digest,
            "qa_contract_report_sha256": qa_contract_digest,
            "qa_report_sha256": qa_digest,
            "semantic_qa_report_sha256": qa_digest,
            "review_receipts": receipts,
        }
        if include_qa_contract:
            decision["qa_contract_check"] = qa_contract_receipt
        _decision_path, decision_sha = self._write_json(decision_rel, decision)

        staged = copy.deepcopy(candidate_item)
        staged_quality = dict(staged.get("quality") or {})
        staged_quality.update(
            {
                "review_status": "staged",
                "status": "staged",
                "activation_eligible": False,
                "content_envelope_sha256": content_envelope_sha,
                "review_evidence": {
                    "content_envelope_sha256": content_envelope_sha,
                    "receipts": staged_review_receipts,
                },
                "staging_receipts": {
                    "candidate_path": candidate_rel,
                    "candidate_sha256": candidate_sha,
                    "content_envelope_sha256": content_envelope_sha,
                    "staging_decision_path": decision_rel,
                    "staging_decision_sha256": decision_sha,
                    "machine_report_sha256": machine_digest,
                    "expert_report_sha256": expert_digest,
                    "model_expert_report_sha256": model_digest,
                    "qa_contract_report_sha256": qa_contract_digest,
                    "qa_report_sha256": qa_digest,
                    "semantic_qa_report_sha256": qa_digest,
                },
            }
        )
        staged["quality"] = staged_quality
        return staged, qa_rel

    def _write_bank(self, items: list[dict[str, Any]], *, minimum: int, target: int, maximum: int) -> Path:
        previous_items: list[dict[str, Any]] = []
        for item in items:
            quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
            staging_receipts = quality.get("staging_receipts") if isinstance(quality.get("staging_receipts"), dict) else {}
            candidate_rel = str(staging_receipts.get("candidate_path") or "")
            candidate_path = self.root / candidate_rel
            candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate_item = dict(candidate_payload["item"])
            candidate_sha = self._digest_json(candidate_item)
            candidate_file_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
            binding = {
                "item_id": str(item.get("id") or ""),
                "candidate_path": candidate_rel,
                "candidate_sha256": candidate_sha,
                "candidate_file_sha256": candidate_file_sha,
            }
            candidate_set_sha = self._digest_json(
                [
                    {
                        "item_id": binding["item_id"],
                        "candidate_sha256": candidate_sha,
                        "candidate_file_sha256": candidate_file_sha,
                    }
                ]
            )
            base_bindings = [
                {
                    "item_id": str(previous.get("id") or ""),
                    "item_sha256": self._digest_json(previous),
                }
                for previous in previous_items
            ]
            collision_rel = f"data/admin/semantic_collision/{binding['item_id']}.json"
            collision = {
                "schema_version": "2026-07-25.codex-admin.semantic-collision-board.v1",
                "status": "PASS",
                "provider_mode": "live_model",
                "write_applied": True,
                "candidate_bindings": [binding],
                "candidate_set_sha256": candidate_set_sha,
                "candidate_decisions": {
                    binding["item_id"]: {
                        "candidate_item_id": binding["item_id"],
                        "decision": "PASS",
                        "confidence": 0.95,
                        "collisions": [],
                        "summary": "No semantic collision.",
                        "decision_source": "live_model_board",
                        "candidate_sha256": candidate_sha,
                        "candidate_file_sha256": candidate_file_sha,
                    }
                },
                "base_staged_bank_sha256": self._digest_json(base_bindings),
                "base_staged_snapshot_sha256": self._digest_json(base_bindings),
                "base_staged_item_bindings": base_bindings,
                "model_evidence": {
                    "provider_mode": "live_model",
                    "raw_response_sha256": "9" * 64,
                    "route": {"structured_json_mode": "json_schema"},
                    "transport_attempts": [],
                },
            }
            _collision_path, collision_sha = self._write_json(collision_rel, collision)
            staging_receipts.update(
                {
                    "semantic_collision_receipt_path": collision_rel,
                    "semantic_collision_receipt_sha256": collision_sha,
                    "semantic_collision_candidate_set_sha256": candidate_set_sha,
                    "semantic_collision_base_staged_bank_sha256": collision[
                        "base_staged_bank_sha256"
                    ],
                    "semantic_collision_base_snapshot_sha256": collision[
                        "base_staged_snapshot_sha256"
                    ],
                    "semantic_collision_decision": collision["candidate_decisions"][
                        binding["item_id"]
                    ],
                }
            )
            previous_items.append(item)
        self._write_json(
            "data/question_banks/v18/node_question_blueprints_v18.json",
            {
                "blueprints": [
                    {
                        "node_id": self.node_id,
                        "node_name": "Node",
                        "candidate_budget": {"min": minimum, "target": target, "max": maximum},
                        "family_plan": [
                            {"family_id": self.family_id, "target_count": target, "difficulty": ["L2"]}
                        ],
                    }
                ]
            },
        )
        bank_path, _sha = self._write_json(
            "data/question_banks/v18/staged_candidates_v18.json",
            {
                "schema_version": "2026-07-23.codex-admin.staged-question-bank.v1",
                "question_bank_version": "2026-07-23.bank.v18.staged",
                "status": "staged_not_active",
                "item_count": len(items),
                "items": items,
            },
        )
        return bank_path

    def test_only_contract_complete_and_revalidated_items_count_toward_budget(self) -> None:
        good, _qa_path = self._stage_item(self._base_item("Q1"))
        invalid_candidate = self._base_item("Q2")
        invalid_candidate.pop("prompt")
        invalid, _qa_path = self._stage_item(invalid_candidate)
        bank_path = self._write_bank([good, invalid], minimum=1, target=1, maximum=2)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual(2, report["raw_item_count"])
        self.assertEqual(1, report["qualified_item_count"])
        self.assertEqual(1, report["counts_by_node"][self.node_id])
        self.assertEqual(["Q2"], [item["item_id"] for item in report["disqualified_items"]])
        self.assertEqual("NEEDS_FIX", report["status"])

    def test_missing_child_surface_design_is_disqualified(self) -> None:
        candidate = self._base_item("Q1")
        candidate.pop("child_surface_design")
        staged, _qa_path = self._stage_item(candidate)
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn("missing_child_surface_design", report["disqualified_items"][0]["blocking_codes"])

    def test_decimal_score_contract_counts_as_ten_points(self) -> None:
        candidate = self._base_item("Q1")
        candidate["key_score_points"][0]["points"] = 1.5
        candidate["key_score_points"][1]["points"] = 3.5
        candidate["key_score_points"][2]["points"] = 5
        staged, _qa_path = self._stage_item(candidate)
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual("PASS", report["status"])
        self.assertEqual(1, report["qualified_item_count"])

    def test_legacy_four_receipt_item_is_pending_revalidation_and_does_not_count(self) -> None:
        legacy, _qa_path = self._stage_item(
            self._base_item("Q1"),
            include_qa_contract=False,
            include_machine_artifact=False,
        )
        bank_path = self._write_bank([legacy], minimum=1, target=1, maximum=1)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual(0, report["qualified_item_count"])
        self.assertEqual(1, report["legacy_pending_revalidation_count"])
        self.assertEqual(
            "legacy_pending_revalidation",
            report["disqualified_items"][0]["qualification_status"],
        )
        self.assertIn(
            "missing_qa_contract_check_receipt",
            report["disqualified_items"][0]["blocking_codes"],
        )

    def test_semantic_qa_scope_disqualifies_item(self) -> None:
        staged, _qa_path = self._stage_item(
            self._base_item("Q1"),
            semantic_scope={
                "support_only": True,
                "not_for_activation": True,
                "exclude_from_coverage": True,
                "reasons": ["只保留为支持材料"],
            },
        )
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn("semantic_qa_scope_not_empty", {finding["code"] for finding in report["findings"]})

    def test_semantic_qa_must_bind_current_contract_check_digest(self) -> None:
        staged, _qa_path = self._stage_item(
            self._base_item("Q1"),
            bind_semantic_to_contract=False,
        )
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn(
            "semantic_qa_contract_digest_mismatch",
            {finding["code"] for finding in report["findings"]},
        )

    def test_tampered_qa_artifact_disqualifies_item(self) -> None:
        staged, qa_rel = self._stage_item(self._base_item("Q1"))
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)
        qa_path = self.root / qa_rel
        tampered = json.loads(qa_path.read_text(encoding="utf-8"))
        tampered["tampered"] = True
        self._write_json(qa_rel, tampered)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn("semantic_qa_review_report_digest_mismatch", {finding["code"] for finding in report["findings"]})

    def test_missing_collision_receipt_disqualifies_item(self) -> None:
        staged, _qa_path = self._stage_item(self._base_item("Q1"))
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
        receipts = bank["items"][0]["quality"]["staging_receipts"]
        receipts.pop("semantic_collision_receipt_path")
        receipts.pop("semantic_collision_receipt_sha256")
        self._write_json(
            "data/question_banks/v18/staged_candidates_v18.json",
            bank,
        )

        report = build_full_bank_acceptance(
            root=self.root,
            bank_path=bank_path,
            require_target=True,
        )

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn(
            "admin_staged_item_collision_receipt_missing",
            {finding["code"] for finding in report["findings"]},
        )

    def test_staged_content_changed_after_review_is_disqualified(self) -> None:
        staged, _qa_path = self._stage_item(self._base_item("Q1"))
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
        bank["items"][0]["prompt"] = "这是一道未经原始评审的新题干。"
        self._write_json(
            "data/question_banks/v18/staged_candidates_v18.json",
            bank,
        )

        report = build_full_bank_acceptance(
            root=self.root,
            bank_path=bank_path,
            require_target=True,
        )

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn(
            "staged_content_envelope_sha256_mismatch",
            {finding["code"] for finding in report["findings"]},
        )

    def test_low_confidence_collision_receipt_disqualifies_item(self) -> None:
        staged, _qa_path = self._stage_item(self._base_item("Q1"))
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
        receipts = bank["items"][0]["quality"]["staging_receipts"]
        collision_path = self.root / receipts["semantic_collision_receipt_path"]
        collision = json.loads(collision_path.read_text(encoding="utf-8"))
        collision["candidate_decisions"]["Q1"]["confidence"] = 0.4
        _path, collision_sha = self._write_json(
            receipts["semantic_collision_receipt_path"],
            collision,
        )
        receipts["semantic_collision_receipt_sha256"] = collision_sha
        receipts["semantic_collision_decision"] = collision["candidate_decisions"]["Q1"]
        self._write_json(
            "data/question_banks/v18/staged_candidates_v18.json",
            bank,
        )

        report = build_full_bank_acceptance(
            root=self.root,
            bank_path=bank_path,
            require_target=True,
        )

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn(
            "admin_semantic_collision_decision_not_trustworthy",
            {finding["code"] for finding in report["findings"]},
        )

    def test_non_live_collision_decision_source_disqualifies_item(self) -> None:
        staged, _qa_path = self._stage_item(self._base_item("Q1"))
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
        receipts = bank["items"][0]["quality"]["staging_receipts"]
        collision_path = self.root / receipts["semantic_collision_receipt_path"]
        collision = json.loads(collision_path.read_text(encoding="utf-8"))
        collision["candidate_decisions"]["Q1"]["decision_source"] = "recorded_or_manual"
        _path, collision_sha = self._write_json(
            receipts["semantic_collision_receipt_path"],
            collision,
        )
        receipts["semantic_collision_receipt_sha256"] = collision_sha
        receipts["semantic_collision_decision"] = collision["candidate_decisions"]["Q1"]
        self._write_json(
            "data/question_banks/v18/staged_candidates_v18.json",
            bank,
        )

        report = build_full_bank_acceptance(
            root=self.root,
            bank_path=bank_path,
            require_target=True,
        )

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn(
            "admin_semantic_collision_decision_source_invalid",
            {finding["code"] for finding in report["findings"]},
        )

    def test_legacy_contract_aliases_are_explicit_but_qualify(self) -> None:
        candidate = self._base_item("Q1")
        candidate["question_family_id"] = candidate.pop("question_type")
        candidate["scoring_targets"] = candidate.pop("key_score_points")
        staged, _qa_path = self._stage_item(candidate)
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual("PASS", report["status"])
        self.assertEqual(1, report["qualified_item_count"])
        self.assertEqual(
            {
                "legacy_guanzhi_semantic_receipt_snapshot": 1,
                "legacy_question_family_id_used": 1,
                "legacy_scoring_targets_used": 1,
            },
            report["v18_item_contract"]["migration_finding_counts"],
        )

    def test_conflicting_family_alias_disqualifies_item(self) -> None:
        candidate = self._base_item("Q1")
        candidate["question_family_id"] = "OTHER"
        staged, _qa_path = self._stage_item(candidate)
        bank_path = self._write_bank([staged], minimum=1, target=1, maximum=1)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual(0, report["qualified_item_count"])
        self.assertIn("question_family_contract_conflict", {finding["code"] for finding in report["findings"]})

    def test_qualified_count_above_max_is_blocking(self) -> None:
        first, _qa_path = self._stage_item(self._base_item("Q1"))
        second, _qa_path = self._stage_item(self._base_item("Q2"))
        bank_path = self._write_bank([first, second], minimum=1, target=1, maximum=1)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=True)

        self.assertEqual(2, report["qualified_item_count"])
        self.assertEqual(1, report["over_max_gaps"][0]["over_max_by"])
        self.assertEqual("NEEDS_FIX", report["status"])

    def test_no_require_target_passes_at_minimum_and_reports_optional_shortfall(self) -> None:
        staged, _qa_path = self._stage_item(self._base_item("Q1"))
        bank_path = self._write_bank([staged], minimum=1, target=2, maximum=3)

        report = build_full_bank_acceptance(root=self.root, bank_path=bank_path, require_target=False)

        self.assertEqual("PASS", report["status"])
        self.assertEqual([], report["target_gaps"])
        self.assertEqual(1, report["target_shortfalls"][0]["missing_to_target"])

    def test_inventory_v18_uses_staged_and_sample_has_explicit_alias(self) -> None:
        staged, _qa_path = self._stage_item(self._base_item("Q1"))
        self._write_bank([staged], minimum=1, target=1, maximum=1)
        self._write_json(
            "data/question_banks/v18/math_v18_sample_60.json",
            {
                "question_bank_version": "2026-07-22.bank.v18.sample-60",
                "status": "draft_generated_not_active",
                "items": [],
            },
        )

        staged_report = build_question_bank_inventory(root=self.root, version="v18")
        sample_report = build_question_bank_inventory(root=self.root, version="v18-sample")

        self.assertEqual("data/question_banks/v18/staged_candidates_v18.json", staged_report["source_path"])
        self.assertEqual("staged_or_explicit", staged_report["inventory_scope"])
        self.assertEqual("data/question_banks/v18/math_v18_sample_60.json", sample_report["source_path"])
        self.assertEqual("sample", sample_report["inventory_scope"])


if __name__ == "__main__":
    unittest.main()
