from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import question_bank_v18_activation_gate
from learning_system.admin.expert_review import EXPERT_PROFILES
from learning_system.admin.qa_review import REQUIRED_HARD_BLOCKERS, REQUIRED_SEMANTIC_QA_PROFILES
from learning_system.admin.staging import (
    STAGED_BANK_SCHEMA_VERSION,
    STAGED_CONTENT_ENVELOPE_SCHEMA_VERSION,
    staged_content_envelope_sha256,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/question_banks/v18/sample_gate_manifest_v18.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class QuestionBankV18ActivationGateTests(unittest.TestCase):
    def _build_activation_bundle(self, root: Path) -> tuple[Path, dict[str, object]]:
        item = {
            "id": "CAND-ACTIVATION-001",
            "node_id": "M-G7-NUMBER-LINE",
            "question_type": "number_line_position_distance",
            "prompt": "在数轴上标出 -2 和 3，并说明它们到原点的距离。",
            "standard_answer": "距离分别为 2 和 3。",
            "key_score_points": [{"key": "answer", "points": 10}],
            "source_type": "ai_original",
            "quality": {"structure_fingerprint": "CANON-ACTIVATION-001"},
        }
        candidate_path = root / "candidate.json"
        _write_json(candidate_path, {"item": item})
        candidate_sha256 = _digest_json(item)
        candidate_file_sha256 = _sha256(candidate_path)
        common = {
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
                **common,
                "schema_version": "2026-07-23.codex-admin.production-candidate-check.v1",
                "status": "SELF_CHECKED_PASS",
                "production_json_path": str(root / "artifacts/machine.json"),
            },
            "deterministic_expert_review": {
                **common,
                "schema_version": "2026-07-23.codex-admin.candidate-expert-review.v1",
                "status": "PASS",
                "source_path": str(candidate_path),
                "source_file_sha256": candidate_file_sha256,
                "review_json_path": str(root / "artifacts/expert.json"),
                "expert_profiles": {
                    profile: {"status": "PASS", "finding_counts": {}}
                    for profile in EXPERT_PROFILES
                },
            },
            "model_expert_board_review": {
                **common,
                "schema_version": "2026-07-23.codex-admin.model-expert-board-review.v1",
                "status": "PASS",
                "source_path": str(candidate_path),
                "source_file_sha256": candidate_file_sha256,
                "model_expert_review_json_path": str(root / "artifacts/model.json"),
                "provider_mode": "live_model",
                "route": {"raw_response_sha256": "1" * 64, "structured_json_mode": "json_schema"},
                "prompt_meta": {"rendered_prompt_sha256": "2" * 64, "response_schema_sha256": "3" * 64},
                "profile_reviews": [
                    {"profile": profile, "status": "pass"}
                    for profile in EXPERT_PROFILES
                ],
            },
            "qa_contract_check": {
                **common,
                "schema_version": "2026-07-24.codex-admin.candidate-qa-contract-check.v1",
                "gate_type": "deterministic_contract_check",
                "engine_type": "deterministic_contract_validation",
                "semantic_authority": False,
                "status": "PASS",
                "source_path": str(candidate_path),
                "source_file_sha256": candidate_file_sha256,
                "qa_contract_check_json_path": str(root / "artifacts/qa-contract.json"),
            },
        }
        artifact_paths = {
            name: Path(
                artifact.get("production_json_path")
                or artifact.get("review_json_path")
                or artifact.get("model_expert_review_json_path")
                or artifact.get("qa_contract_check_json_path")
            )
            for name, artifact in artifacts.items()
        }
        for name, path in artifact_paths.items():
            _write_json(path, artifacts[name])
        contract_digest = _sha256(artifact_paths["qa_contract_check"])
        semantic_path = root / "artifacts/semantic-qa.json"
        artifacts["semantic_qa_review"] = {
            **common,
            "schema_version": "2026-07-23.codex-admin.candidate-qa-review.v1",
            "gate_type": "live_model_semantic_qa",
            "status": "PASS",
            "source_path": str(candidate_path),
            "source_file_sha256": candidate_file_sha256,
            "qa_contract_report_sha256": contract_digest,
            "qa_json_path": str(semantic_path),
            "provider_mode": "live_model",
            "route": {"raw_response_sha256": "4" * 64, "structured_json_mode": "json_schema"},
            "prompt_meta": {"rendered_prompt_sha256": "5" * 64, "response_schema_sha256": "6" * 64},
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
        artifact_paths["semantic_qa_review"] = semantic_path
        _write_json(semantic_path, artifacts["semantic_qa_review"])

        envelope_sha = staged_content_envelope_sha256(item)
        item["question_bank_version"] = "2026-07-23.bank.v18.staged"
        receipt_roles = {
            "machine_check": "machine_contract_check",
            "deterministic_expert_review": "deterministic_expert_review",
            "model_expert_board_review": "live_model_expert_board_review",
            "qa_contract_check": "deterministic_qa_contract_check",
            "semantic_qa_review": "live_model_semantic_qa_review",
        }
        review_receipts = {}
        for name, path in artifact_paths.items():
            artifact = artifacts[name]
            review_receipts[name] = {
                "role": receipt_roles[name],
                "schema_version": artifact["schema_version"],
                "status": artifact["status"],
                "gate_type": artifact.get("gate_type", ""),
                "provider_mode": artifact.get("provider_mode", ""),
                "item_id": item["id"],
                "node_id": item["node_id"],
                "family_id": item["question_type"],
                "candidate_sha256": candidate_sha256,
                "content_envelope_sha256": envelope_sha,
                "source_path": artifact.get("source_path", ""),
                "source_file_sha256": artifact.get("source_file_sha256", ""),
                "report_path": str(path),
                "report_sha256": _sha256(path),
                "qa_contract_report_sha256": artifact.get("qa_contract_report_sha256", ""),
                "finding_counts": {},
                "finding_codes": [],
            }
        collision_binding = {
            "item_id": item["id"],
            "candidate_path": str(candidate_path),
            "candidate_sha256": candidate_sha256,
            "candidate_file_sha256": candidate_file_sha256,
        }
        collision_set_sha256 = _digest_json(
            [
                {
                    "item_id": item["id"],
                    "candidate_sha256": candidate_sha256,
                    "candidate_file_sha256": candidate_file_sha256,
                }
            ]
        )
        collision_decision = {
            "candidate_item_id": item["id"],
            "decision": "PASS",
            "confidence": 0.95,
            "collisions": [],
            "summary": "No semantic collision.",
            "decision_source": "live_model_board",
            "candidate_sha256": candidate_sha256,
            "candidate_file_sha256": candidate_file_sha256,
        }
        collision_path = root / "artifacts/semantic-collision.json"
        _write_json(
            collision_path,
            {
                "schema_version": "2026-07-25.codex-admin.semantic-collision-board.v1",
                "status": "PASS",
                "provider_mode": "live_model",
                "write_applied": True,
                "candidate_bindings": [collision_binding],
                "candidate_set_sha256": collision_set_sha256,
                "candidate_decisions": {item["id"]: collision_decision},
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
        item["quality"].update(
            {
                "review_status": "staged",
                "status": "staged",
                "activation_eligible": False,
                "content_envelope_sha256": envelope_sha,
                "staging_receipts": {
                    "candidate_path": str(candidate_path),
                    "candidate_sha256": candidate_sha256,
                    "content_envelope_sha256": envelope_sha,
                    "semantic_collision_receipt_path": str(collision_path),
                    "semantic_collision_receipt_sha256": _sha256(collision_path),
                    "semantic_collision_candidate_set_sha256": collision_set_sha256,
                    "semantic_collision_base_staged_bank_sha256": hashlib.sha256(b"").hexdigest(),
                    "semantic_collision_base_snapshot_sha256": _digest_json([]),
                    "semantic_collision_decision": collision_decision,
                },
                "review_evidence": {
                    "content_envelope_sha256": envelope_sha,
                    "receipts": review_receipts,
                },
            }
        )
        bank = {
            "schema_version": STAGED_BANK_SCHEMA_VERSION,
            "question_bank_version": "2026-07-23.bank.v18.staged",
            "status": "staged_not_active",
            "item_count": 1,
            "items": [item],
        }
        bank_path = root / "staged.json"
        _write_json(bank_path, bank)
        bank_sha256 = _sha256(bank_path)
        full_bank_object_sha256 = "f" * 64
        full_bank = {
            "schema_version": question_bank_v18_activation_gate.FULL_BANK_ACCEPTANCE_SCHEMA_VERSION,
            "status": "PASS",
            "subject": "math",
            "require_target": True,
            "bank_path": str(bank_path),
            "question_bank_version": bank["question_bank_version"],
            "item_count": 1,
            "qualified_item_count": 1,
            "disqualified_item_count": 0,
            "qualified_item_ids": [item["id"]],
            "finding_counts": {},
            "counts_by_node": {item["node_id"]: 1},
            "counts_by_family": {item["question_type"]: 1},
            "source_digests": {
                "staged_bank": {"path": str(bank_path), "sha256": bank_sha256},
            },
            "full_bank_acceptance_sha256": full_bank_object_sha256,
        }
        full_bank_path = root / "full-bank.json"
        _write_json(full_bank_path, full_bank)
        identity = {
            "subject": "math",
            "question_bank_version": bank["question_bank_version"],
            "staged_bank_sha256": bank_sha256,
            "full_bank_acceptance_sha256": full_bank_object_sha256,
        }
        receipt_entries = []
        for receipt_type in sorted(question_bank_v18_activation_gate.REQUIRED_ACTIVATION_RECEIPTS):
            receipt = {
                "schema_version": question_bank_v18_activation_gate.ACTIVATION_RECEIPT_SCHEMA_VERSION,
                "receipt_type": receipt_type,
                "status": "PASS",
                "object_identity": identity,
                "evidence": {"checked": True},
            }
            receipt_path = root / "receipts" / f"{receipt_type}.json"
            _write_json(receipt_path, receipt)
            receipt_entries.append(
                {
                    "receipt_type": receipt_type,
                    "path": str(receipt_path),
                    "sha256": _sha256(receipt_path),
                    "schema_version": question_bank_v18_activation_gate.ACTIVATION_RECEIPT_SCHEMA_VERSION,
                    "status": "PASS",
                    "object_identity": identity,
                }
            )
        manifest = {
            "schema_version": question_bank_v18_activation_gate.ACTIVATION_MANIFEST_SCHEMA_VERSION,
            "status": question_bank_v18_activation_gate.ACTIVATION_READY_STATUS,
            "subject": "math",
            "question_bank": {
                "path": str(bank_path),
                "sha256": bank_sha256,
                "schema_version": STAGED_BANK_SCHEMA_VERSION,
                "status": "staged_not_active",
                "question_bank_version": bank["question_bank_version"],
                "item_count": 1,
                "content_envelope_schema_version": STAGED_CONTENT_ENVELOPE_SCHEMA_VERSION,
            },
            "full_bank_acceptance": {
                "path": str(full_bank_path),
                "sha256": _sha256(full_bank_path),
                "schema_version": question_bank_v18_activation_gate.FULL_BANK_ACCEPTANCE_SCHEMA_VERSION,
                "status": "PASS",
                "full_bank_acceptance_sha256": full_bank_object_sha256,
            },
            "review_receipts": receipt_entries,
            "not_authorized_for": [],
        }
        manifest_path = root / "activation-manifest.json"
        _write_json(manifest_path, manifest)
        return manifest_path, manifest

    @staticmethod
    def _validate_with_bound_acceptance(manifest_path: Path) -> dict[str, object]:
        full_bank_path = manifest_path.parent / "full-bank.json"

        def builder(**_kwargs):
            return json.loads(full_bank_path.read_text(encoding="utf-8"))

        return question_bank_v18_activation_gate.validate_activation_readiness(
            manifest_path,
            acceptance_builder=builder,
        )

    def test_sample_integrity_passes_but_does_not_allow_activation(self) -> None:
        report = question_bank_v18_activation_gate.validate_sample_integrity(MANIFEST_PATH)

        self.assertEqual("PASS", report["status"])
        self.assertEqual("sample_integrity", report["mode"])
        self.assertEqual("sample_static_qa_passed_scope_limited", report["manifest_status"])
        self.assertEqual(60, report["sample_item_count"])
        self.assertFalse(report["activation_allowed"])

    def test_sample_manifest_is_not_activation_ready(self) -> None:
        with self.assertRaises(question_bank_v18_activation_gate.GateError):
            question_bank_v18_activation_gate.validate_activation_readiness(MANIFEST_PATH)

    def test_manifest_digest_mismatch_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        tampered = copy.deepcopy(manifest)
        tampered["input_digests"]["sample"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample_gate_manifest_v18.json"
            path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(question_bank_v18_activation_gate.GateError, "digest mismatch"):
                question_bank_v18_activation_gate.validate_sample_integrity(path)

    def test_fixed_activation_manifest_with_bound_artifacts_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, _manifest = self._build_activation_bundle(Path(tmp))
            report = self._validate_with_bound_acceptance(manifest_path)

        self.assertEqual("PASS", report["status"])
        self.assertTrue(report["activation_allowed"])
        self.assertEqual(1, report["validated_item_count"])
        self.assertEqual(
            question_bank_v18_activation_gate.REQUIRED_ACTIVATION_RECEIPTS,
            set(report["checked_receipts"]),
        )

    def test_activation_manifest_rejects_extra_schema_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._build_activation_bundle(root)
            manifest["legacy_input_digests"] = {}
            _write_json(manifest_path, manifest)

            with self.assertRaisesRegex(question_bank_v18_activation_gate.GateError, "schema mismatch"):
                self._validate_with_bound_acceptance(manifest_path)

    def test_activation_receipt_digest_and_identity_are_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._build_activation_bundle(root)
            receipt = manifest["review_receipts"][0]
            receipt["object_identity"] = dict(receipt["object_identity"])
            receipt["object_identity"]["staged_bank_sha256"] = "0" * 64
            _write_json(manifest_path, manifest)

            with self.assertRaisesRegex(question_bank_v18_activation_gate.GateError, "object identity mismatch"):
                self._validate_with_bound_acceptance(manifest_path)

    def test_activation_receipt_artifact_tampering_fails_digest_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._build_activation_bundle(root)
            receipt_path = Path(manifest["review_receipts"][0]["path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["evidence"]["checked"] = False
            _write_json(receipt_path, receipt)

            with self.assertRaisesRegex(question_bank_v18_activation_gate.GateError, "digest mismatch"):
                self._validate_with_bound_acceptance(manifest_path)

    def test_activation_requires_full_bank_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._build_activation_bundle(root)
            manifest["full_bank_acceptance"]["status"] = "PASS_WITH_SCOPE"
            _write_json(manifest_path, manifest)

            with self.assertRaisesRegex(question_bank_v18_activation_gate.GateError, "requires full-bank acceptance PASS"):
                self._validate_with_bound_acceptance(manifest_path)

    def test_activation_recomputes_staged_content_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._build_activation_bundle(root)
            bank_path = Path(manifest["question_bank"]["path"])
            bank = json.loads(bank_path.read_text(encoding="utf-8"))
            bank["items"][0]["prompt"] += " 已被修改。"
            _write_json(bank_path, bank)
            manifest["question_bank"]["sha256"] = _sha256(bank_path)
            _write_json(manifest_path, manifest)

            with self.assertRaisesRegex(question_bank_v18_activation_gate.GateError, "content envelope validation failed"):
                self._validate_with_bound_acceptance(manifest_path)

    def test_activation_revalidates_staged_review_artifact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._build_activation_bundle(root)
            bank_path = Path(manifest["question_bank"]["path"])
            bank = json.loads(bank_path.read_text(encoding="utf-8"))
            semantic_path = Path(
                bank["items"][0]["quality"]["review_evidence"]["receipts"]["semantic_qa_review"]["report_path"]
            )
            semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
            semantic["qa_contract_report_sha256"] = "0" * 64
            _write_json(semantic_path, semantic)

            with self.assertRaisesRegex(question_bank_v18_activation_gate.GateError, "review artifact validation failed"):
                self._validate_with_bound_acceptance(manifest_path)

    def test_activation_revalidates_collision_receipt_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._build_activation_bundle(root)
            bank_path = Path(manifest["question_bank"]["path"])
            bank = json.loads(bank_path.read_text(encoding="utf-8"))
            collision_path = Path(
                bank["items"][0]["quality"]["staging_receipts"][
                    "semantic_collision_receipt_path"
                ]
            )
            collision = json.loads(collision_path.read_text(encoding="utf-8"))
            collision["candidate_decisions"]["CAND-ACTIVATION-001"]["confidence"] = 0.1
            _write_json(collision_path, collision)

            with self.assertRaisesRegex(
                question_bank_v18_activation_gate.GateError,
                "review artifact validation failed",
            ):
                self._validate_with_bound_acceptance(manifest_path)

    def test_activation_rejects_legacy_four_receipt_staged_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._build_activation_bundle(root)
            bank_path = Path(manifest["question_bank"]["path"])
            bank = json.loads(bank_path.read_text(encoding="utf-8"))
            bank["items"][0]["quality"]["review_evidence"]["receipts"].pop("qa_contract_check")
            _write_json(bank_path, bank)
            manifest["question_bank"]["sha256"] = _sha256(bank_path)
            _write_json(manifest_path, manifest)

            with self.assertRaisesRegex(question_bank_v18_activation_gate.GateError, "content envelope validation failed"):
                self._validate_with_bound_acceptance(manifest_path)

    def test_self_reported_full_bank_pass_is_rejected_by_recomputation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, _manifest = self._build_activation_bundle(Path(tmp))

            with self.assertRaisesRegex(
                question_bank_v18_activation_gate.GateError,
                "recomputed full-bank acceptance is not PASS",
            ):
                question_bank_v18_activation_gate.validate_activation_readiness(manifest_path)


if __name__ == "__main__":
    unittest.main()
