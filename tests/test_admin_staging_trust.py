from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system.admin.expert_review import EXPERT_PROFILES
from learning_system.admin.qa_review import REQUIRED_HARD_BLOCKERS, REQUIRED_SEMANTIC_QA_PROFILES
from learning_system.admin import staging
from learning_system.admin.staging import (
    build_and_write_stage_candidate_receipt,
    validate_staged_bank_content_envelopes,
)


def _digest_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class AdminStagingTrustTests(unittest.TestCase):
    def test_stage_requires_collision_receipt_even_for_single_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)

            with self.assertRaisesRegex(Exception, "COLLISION_RECEIPT_REQUIRED"):
                build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=root,
                    candidate_path=bundle["candidate"],
                    staging_decision_path=bundle["decision"],
                    staged_bank_path=bundle["staged_bank"],
                    apply=True,
                )

    def _build_bundle(self, root: Path) -> dict[str, Path]:
        item = {
            "id": "CAND-TRUST-001",
            "item_version": "draft.admin-production.v1.attempt-1",
            "node_id": "M-G7-NUMBER-LINE",
            "question_type": "number_line_position_distance",
            "difficulty": "L2",
            "prompt": "在数轴上标出 -2 和 3，并说明它们到原点的距离。",
            "answer_format": "写出位置、距离和理由。",
            "standard_answer": "-2 到原点距离为 2，3 到原点距离为 3。",
            "accepted_alternatives": [],
            "required_evidence": ["位置", "距离", "理由"],
            "key_score_points": [
                {"key": "left", "points": 3},
                {"key": "right", "points": 3},
                {"key": "reason", "points": 4},
            ],
            "solution_steps": ["标点", "读距离", "说明"],
            "target_error_tags": ["concept_confusion"],
            "rollback_candidates": [],
            "source_type": "ai_original",
            "quality": {
                "review_status": "draft_generated",
                "canonical_structure_fingerprint": "CANON-TRUST-001",
                "structure_fingerprint": "CANON-TRUST-001",
            },
            "math_core_signature": "CANON-TRUST-001",
        }
        candidate_path = root / "candidate.json"
        _write_json(candidate_path, {"item": item})
        candidate_sha256 = _digest_json(item)
        candidate_file_sha256 = _sha256(candidate_path)
        candidate_binding = {
            "item_id": item["id"],
            "candidate_path": "candidate.json",
            "candidate_sha256": candidate_sha256,
            "candidate_file_sha256": candidate_file_sha256,
        }
        candidate_set_sha256 = _digest_json(
            [
                {
                    "item_id": item["id"],
                    "candidate_sha256": candidate_sha256,
                    "candidate_file_sha256": candidate_file_sha256,
                }
            ]
        )
        collision_path = root / "collision.json"
        _write_json(
            collision_path,
            {
                "schema_version": "2026-07-25.codex-admin.semantic-collision-board.v1",
                "status": "PASS",
                "provider_mode": "live_model",
                "write_applied": True,
                "candidate_bindings": [candidate_binding],
                "candidate_set_sha256": candidate_set_sha256,
                "candidate_decisions": {
                    item["id"]: {
                        "candidate_item_id": item["id"],
                        "decision": "PASS",
                        "confidence": 0.95,
                        "collisions": [],
                        "summary": "No semantic collision.",
                        "decision_source": "live_model_board",
                        "candidate_sha256": candidate_sha256,
                        "candidate_file_sha256": candidate_file_sha256,
                    }
                },
                "base_staged_bank_sha256": hashlib.sha256(b"").hexdigest(),
                "base_staged_snapshot_sha256": _digest_json([]),
                "base_staged_item_bindings": [],
                "model_evidence": {
                    "provider_mode": "live_model",
                    "raw_response_sha256": "9" * 64,
                    "route": {"structured_json_mode": "json_schema"},
                    "transport_attempts": [],
                },
            },
        )
        identity = {
            "item_id": item["id"],
            "node_id": item["node_id"],
            "family_id": item["question_type"],
            "candidate_sha256": candidate_sha256,
            "finding_counts": {},
            "findings": [],
            "write_applied": True,
        }
        artifacts = {
            "machine_check": {
                **identity,
                "schema_version": "2026-07-23.codex-admin.production-candidate-check.v1",
                "status": "SELF_CHECKED_PASS",
                "production_json_path": "artifacts/machine.json",
            },
            "deterministic_expert_review": {
                **identity,
                "schema_version": "2026-07-23.codex-admin.candidate-expert-review.v1",
                "status": "PASS",
                "source_path": "candidate.json",
                "source_file_sha256": candidate_file_sha256,
                "review_json_path": "artifacts/expert.json",
                "expert_profiles": {
                    profile: {"status": "PASS", "finding_counts": {}}
                    for profile in EXPERT_PROFILES
                },
            },
            "model_expert_board_review": {
                **identity,
                "schema_version": "2026-07-23.codex-admin.model-expert-board-review.v1",
                "status": "PASS",
                "overall_status": "pass",
                "source_path": "candidate.json",
                "source_file_sha256": candidate_file_sha256,
                "model_expert_review_json_path": "artifacts/model.json",
                "provider_mode": "live_model",
                "route": {
                    "raw_response_sha256": "1" * 64,
                    "structured_json_mode": "json_schema",
                },
                "prompt_meta": {
                    "rendered_prompt_sha256": "2" * 64,
                    "response_schema_sha256": "3" * 64,
                },
                "profile_reviews": [
                    {
                        "profile": profile,
                        "status": "pass",
                        "reasons": [],
                        "blocking_item_ids": [],
                        "repair_suggestions": [],
                    }
                    for profile in EXPERT_PROFILES
                ],
            },
            "qa_contract_check": {
                **identity,
                "schema_version": "2026-07-24.codex-admin.candidate-qa-contract-check.v1",
                "gate_type": "deterministic_contract_check",
                "engine_type": "deterministic_contract_validation",
                "semantic_authority": False,
                "status": "PASS",
                "source_path": "candidate.json",
                "source_file_sha256": candidate_file_sha256,
                "qa_contract_check_json_path": "artifacts/qa-contract.json",
            },
        }
        artifact_paths = {
            "machine_check": root / "artifacts/machine.json",
            "deterministic_expert_review": root / "artifacts/expert.json",
            "model_expert_board_review": root / "artifacts/model.json",
            "qa_contract_check": root / "artifacts/qa-contract.json",
            "semantic_qa_review": root / "artifacts/semantic-qa.json",
        }
        for name in ("machine_check", "deterministic_expert_review", "model_expert_board_review", "qa_contract_check"):
            path = artifact_paths[name]
            _write_json(path, artifacts[name])
        contract_digest = _sha256(artifact_paths["qa_contract_check"])
        artifacts["semantic_qa_review"] = {
            **identity,
            "schema_version": "2026-07-23.codex-admin.candidate-qa-review.v1",
            "gate_type": "live_model_semantic_qa",
            "status": "PASS",
            "source_path": "candidate.json",
            "source_file_sha256": candidate_file_sha256,
            "qa_contract_report_sha256": contract_digest,
            "qa_json_path": "artifacts/semantic-qa.json",
            "provider_mode": "live_model",
            "route": {
                "raw_response_sha256": "4" * 64,
                "structured_json_mode": "json_schema",
            },
            "prompt_meta": {
                "rendered_prompt_sha256": "5" * 64,
                "response_schema_sha256": "6" * 64,
            },
            "profile_reviews": [
                {"profile": profile, "status": "pass"}
                for profile in REQUIRED_SEMANTIC_QA_PROFILES
            ],
            "profile_verdicts": {
                profile: "pass" for profile in REQUIRED_SEMANTIC_QA_PROFILES
            },
            "hard_blockers": {
                blocker: {"detected": False, "evidence": []}
                for blocker in REQUIRED_HARD_BLOCKERS
            },
            "scope": {
                "support_only": False,
                "not_for_activation": False,
                "exclude_from_coverage": False,
                "reasons": [],
            },
            "status_normalization": {
                "authority": "deterministic_from_profile_verdicts",
                "model_overall_status_is_advisory": True,
            },
        }
        _write_json(artifact_paths["semantic_qa_review"], artifacts["semantic_qa_review"])
        digest_keys = {
            "machine_check": "machine_report_sha256",
            "deterministic_expert_review": "expert_report_sha256",
            "model_expert_board_review": "model_expert_report_sha256",
            "qa_contract_check": "qa_contract_report_sha256",
            "semantic_qa_review": "semantic_qa_report_sha256",
        }
        decision = {
            "schema_version": "2026-07-23.codex-admin.production-staging-decision.v1",
            "status": "STAGED_READY",
            "staging_allowed": True,
            "item_id": item["id"],
            "node_id": item["node_id"],
            "family_id": item["question_type"],
            "candidate_sha256": candidate_sha256,
            "finding_counts": {},
            "findings": [],
            "review_receipts": {},
            "write_applied": True,
            "production_json_path": "decision.json",
        }
        for name, path in artifact_paths.items():
            digest = _sha256(path)
            decision[digest_keys[name]] = digest
            summary = {
                "role": {
                    "machine_check": "machine_contract_check",
                    "deterministic_expert_review": "deterministic_expert_review",
                    "model_expert_board_review": "live_model_expert_board_review",
                    "qa_contract_check": "deterministic_qa_contract_check",
                    "semantic_qa_review": "live_model_semantic_qa_review",
                }[name],
                "schema_version": artifacts[name]["schema_version"],
                "status": artifacts[name]["status"],
                "item_id": item["id"],
                "node_id": item["node_id"],
                "family_id": item["question_type"],
                "candidate_sha256": candidate_sha256,
                "source_path": artifacts[name].get("source_path", ""),
                "source_file_sha256": artifacts[name].get("source_file_sha256", ""),
                "report_path": str(path.relative_to(root)),
                "report_sha256": digest,
                "gate_type": artifacts[name].get("gate_type", ""),
                "provider_mode": artifacts[name].get("provider_mode", ""),
                "finding_counts": {},
                "finding_codes": [],
            }
            if name == "qa_contract_check":
                decision["qa_contract_check"] = summary
            elif name == "semantic_qa_review":
                decision["qa_report_sha256"] = digest
                decision["review_receipts"]["guanzhi_qa_review"] = summary
            else:
                decision["review_receipts"][name] = summary
        decision_path = root / "decision.json"
        _write_json(decision_path, decision)
        return {
            "candidate": candidate_path,
            "decision": decision_path,
            "staged_bank": root / "staged.json",
            "collision": collision_path,
            "qa_artifact": artifact_paths["semantic_qa_review"],
            "qa_contract_artifact": artifact_paths["qa_contract_check"],
        }

    def test_stage_revalidates_raw_artifacts_and_binds_content_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            report = build_and_write_stage_candidate_receipt(
                root=root,
                artifact_root=root,
                candidate_path=bundle["candidate"],
                staging_decision_path=bundle["decision"],
                staged_bank_path=bundle["staged_bank"],
                semantic_collision_receipt_path=bundle["collision"],
                semantic_collision_receipt_sha256=_sha256(bundle["collision"]),
                apply=True,
            )
            bank = json.loads(bundle["staged_bank"].read_text(encoding="utf-8"))
            validation = validate_staged_bank_content_envelopes(bank)
            receipts = bank["items"][0]["quality"]["review_evidence"]["receipts"]
            receipt_source_paths = {
                str((root / receipt["source_path"]).resolve())
                if not Path(receipt["source_path"]).is_absolute()
                else str(Path(receipt["source_path"]).resolve())
                for receipt in receipts.values()
            }
            receipt_source_digests = {receipt["source_file_sha256"] for receipt in receipts.values()}
            receipt_artifact_paths = {str((root / receipt["report_path"]).resolve()) for receipt in receipts.values()}
            expected_candidate_path = str(bundle["candidate"].resolve())
            expected_candidate_file_sha256 = _sha256(bundle["candidate"])

        self.assertEqual("STAGED_WRITABLE", report["status"])
        self.assertEqual(1, validation["validated_item_count"])
        item = bank["items"][0]
        envelope_sha = item["quality"]["content_envelope_sha256"]
        self.assertEqual(envelope_sha, item["quality"]["staging_receipts"]["content_envelope_sha256"])
        self.assertEqual(
            {
                "machine_check",
                "deterministic_expert_review",
                "model_expert_board_review",
                "qa_contract_check",
                "semantic_qa_review",
            },
            set(item["quality"]["review_evidence"]["receipts"]),
        )
        self.assertEqual({expected_candidate_path}, receipt_source_paths)
        self.assertEqual({expected_candidate_file_sha256}, receipt_source_digests)
        self.assertEqual(5, len(receipt_artifact_paths))
        for receipt in item["quality"]["review_evidence"]["receipts"].values():
            self.assertEqual(envelope_sha, receipt["content_envelope_sha256"])

    def test_stage_revalidates_collision_receipt_and_persists_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            collision_path = root / "collision.json"
            collision_path.write_text("{}", encoding="utf-8")
            validation = {
                "receipt_path": str(collision_path),
                "receipt_sha256": "a" * 64,
                "candidate_set_sha256": "b" * 64,
                "base_staged_bank_sha256": "c" * 64,
                "base_staged_snapshot_sha256": "d" * 64,
                "decision": {"candidate_item_id": "CAND-TRUST-001", "decision": "PASS"},
            }
            with mock.patch.object(
                staging,
                "validate_semantic_collision_receipt",
                return_value=validation,
                create=True,
            ) as validate:
                report = build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=root,
                    candidate_path=bundle["candidate"],
                    staging_decision_path=bundle["decision"],
                    staged_bank_path=bundle["staged_bank"],
                    semantic_collision_receipt_path=collision_path,
                    semantic_collision_receipt_sha256="a" * 64,
                    apply=True,
                )
            bank = json.loads(bundle["staged_bank"].read_text(encoding="utf-8"))

        validate.assert_called_once()
        self.assertEqual("b" * 64, report["semantic_collision_candidate_set_sha256"])
        self.assertEqual(
            "b" * 64,
            bank["items"][0]["quality"]["staging_receipts"]["semantic_collision_candidate_set_sha256"],
        )

    def test_handwritten_staged_ready_without_raw_artifacts_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            decision = json.loads(bundle["decision"].read_text(encoding="utf-8"))
            decision["review_receipts"]["machine_check"]["report_path"] = "missing.json"
            _write_json(bundle["decision"], decision)

            with self.assertRaisesRegex(Exception, "REVIEW_ARTIFACT_MISSING"):
                build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=root,
                    candidate_path=bundle["candidate"],
                    staging_decision_path=bundle["decision"],
                    staged_bank_path=bundle["staged_bank"],
                    semantic_collision_receipt_path=bundle["collision"],
                    semantic_collision_receipt_sha256=_sha256(bundle["collision"]),
                    apply=True,
                )

    def test_review_artifact_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            qa = json.loads(bundle["qa_artifact"].read_text(encoding="utf-8"))
            qa["status"] = "NEEDS_FIX"
            _write_json(bundle["qa_artifact"], qa)

            with self.assertRaisesRegex(Exception, "ARTIFACT_DIGEST_MISMATCH"):
                build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=root,
                    candidate_path=bundle["candidate"],
                    staging_decision_path=bundle["decision"],
                    staged_bank_path=bundle["staged_bank"],
                    semantic_collision_receipt_path=bundle["collision"],
                    semantic_collision_receipt_sha256=_sha256(bundle["collision"]),
                    apply=True,
                )

    def test_review_artifact_non_pass_status_fails_even_with_fresh_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            qa = json.loads(bundle["qa_artifact"].read_text(encoding="utf-8"))
            qa["status"] = "NEEDS_FIX"
            _write_json(bundle["qa_artifact"], qa)
            fresh_digest = _sha256(bundle["qa_artifact"])
            decision = json.loads(bundle["decision"].read_text(encoding="utf-8"))
            decision["qa_report_sha256"] = fresh_digest
            decision["semantic_qa_report_sha256"] = fresh_digest
            decision["review_receipts"]["guanzhi_qa_review"]["status"] = "NEEDS_FIX"
            decision["review_receipts"]["guanzhi_qa_review"]["report_sha256"] = fresh_digest
            _write_json(bundle["decision"], decision)

            with self.assertRaisesRegex(Exception, "ARTIFACT_NOT_PASSED"):
                build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=root,
                    candidate_path=bundle["candidate"],
                    staging_decision_path=bundle["decision"],
                    staged_bank_path=bundle["staged_bank"],
                    semantic_collision_receipt_path=bundle["collision"],
                    semantic_collision_receipt_sha256=_sha256(bundle["collision"]),
                    apply=True,
                )

    def test_missing_separate_qa_contract_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            decision = json.loads(bundle["decision"].read_text(encoding="utf-8"))
            decision.pop("qa_contract_check")
            decision.pop("qa_contract_report_sha256")
            _write_json(bundle["decision"], decision)

            with self.assertRaisesRegex(Exception, "QA_CONTRACT_RECEIPT_MISSING"):
                build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=root,
                    candidate_path=bundle["candidate"],
                    staging_decision_path=bundle["decision"],
                    staged_bank_path=bundle["staged_bank"],
                    semantic_collision_receipt_path=bundle["collision"],
                    semantic_collision_receipt_sha256=_sha256(bundle["collision"]),
                    apply=True,
                )

    def test_semantic_receipt_must_bind_verified_contract_artifact_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            semantic = json.loads(bundle["qa_artifact"].read_text(encoding="utf-8"))
            semantic["qa_contract_report_sha256"] = "0" * 64
            _write_json(bundle["qa_artifact"], semantic)
            fresh_digest = _sha256(bundle["qa_artifact"])
            decision = json.loads(bundle["decision"].read_text(encoding="utf-8"))
            decision["qa_report_sha256"] = fresh_digest
            decision["semantic_qa_report_sha256"] = fresh_digest
            decision["review_receipts"]["guanzhi_qa_review"]["report_sha256"] = fresh_digest
            _write_json(bundle["decision"], decision)

            with self.assertRaisesRegex(Exception, "SEMANTIC_QA_CONTRACT_DIGEST_MISMATCH"):
                build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=root,
                    candidate_path=bundle["candidate"],
                    staging_decision_path=bundle["decision"],
                    staged_bank_path=bundle["staged_bank"],
                    semantic_collision_receipt_path=bundle["collision"],
                    semantic_collision_receipt_sha256=_sha256(bundle["collision"]),
                    apply=True,
                )

    def test_old_single_qa_receipt_shape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            decision = json.loads(bundle["decision"].read_text(encoding="utf-8"))
            decision.pop("qa_contract_check")
            decision.pop("qa_contract_report_sha256")
            decision.pop("semantic_qa_report_sha256")
            _write_json(bundle["decision"], decision)

            with self.assertRaisesRegex(Exception, "QA_CONTRACT_RECEIPT_MISSING"):
                build_and_write_stage_candidate_receipt(
                    root=root,
                    artifact_root=root,
                    candidate_path=bundle["candidate"],
                    staging_decision_path=bundle["decision"],
                    staged_bank_path=bundle["staged_bank"],
                    semantic_collision_receipt_path=bundle["collision"],
                    semantic_collision_receipt_sha256=_sha256(bundle["collision"]),
                    apply=True,
                )

    def test_staged_content_tampering_fails_envelope_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._build_bundle(root)
            build_and_write_stage_candidate_receipt(
                root=root,
                artifact_root=root,
                candidate_path=bundle["candidate"],
                staging_decision_path=bundle["decision"],
                staged_bank_path=bundle["staged_bank"],
                semantic_collision_receipt_path=bundle["collision"],
                semantic_collision_receipt_sha256=_sha256(bundle["collision"]),
                apply=True,
            )
            bank = json.loads(bundle["staged_bank"].read_text(encoding="utf-8"))
            tampered = copy.deepcopy(bank)
            tampered["items"][0]["prompt"] += " 已被修改。"

            with self.assertRaisesRegex(Exception, "CONTENT_ENVELOPE_MISMATCH"):
                validate_staged_bank_content_envelopes(tampered)


if __name__ == "__main__":
    unittest.main()
