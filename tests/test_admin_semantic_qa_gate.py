from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system import model_router
from learning_system.admin.production_loop import decide_staging_from_receipts
from learning_system.admin.production_workflow import run_slot_production_workflow
from learning_system.admin.qa_review import (
    REQUIRED_SEMANTIC_QA_PROFILES,
    build_candidate_semantic_qa_review,
    normalize_semantic_qa_result,
)
from tests.test_admin_console_production_loop import (
    _is_semantic_collision_board_payload,
    _model_expert_pass_output,
    _number_line_brief,
    _semantic_collision_pass_output,
    _slot_generation_plan,
    _wrapped_model_candidate_for_slot,
)


def _scope(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "support_only": False,
        "not_for_activation": False,
        "exclude_from_coverage": False,
        "reasons": [],
    }
    value.update(overrides)
    return value


def _hard_blockers(**detected: bool) -> dict[str, dict[str, object]]:
    return {
        blocker: {
            "detected": bool(detected.get(blocker, False)),
            "evidence": [f"structured evidence for {blocker}"] if detected.get(blocker, False) else [],
        }
        for blocker in (
            "mathematical_ambiguity",
            "prompt_answer_conflict",
            "node_or_family_mismatch",
            "age_inappropriate",
            "meaningless_formal_requirement",
        )
    }


def _model_value(
    *,
    profile_statuses: dict[str, str] | None = None,
    overall_status: str = "pass",
    scope: dict[str, object] | None = None,
    hard_blockers: dict[str, dict[str, object]] | None = None,
    findings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    statuses = profile_statuses or {}
    return {
        "schema_version": "2026-07-24.admin-question-qa-review.schema.v1",
        "overall_status": overall_status,
        "confidence": 0.94,
        "profile_reviews": [
            {
                "profile": profile,
                "status": statuses.get(profile, "pass"),
                "reasons": ["independent structured review"],
                "repair_suggestions": [],
            }
            for profile in REQUIRED_SEMANTIC_QA_PROFILES
        ],
        "hard_blockers": hard_blockers or _hard_blockers(),
        "scope": scope or _scope(),
        "findings": findings or [],
        "activation_implication": "does_not_authorize_activation",
        "next_actions": ["staging_decision"],
    }


class SemanticQANormalizationTests(unittest.TestCase):
    def test_profile_verdict_overrides_model_overall_pass(self) -> None:
        value = _model_value(
            overall_status="pass",
            profile_statuses={"mathematical_validity": "needs_revision"},
            hard_blockers=_hard_blockers(mathematical_ambiguity=True),
        )

        normalized = normalize_semantic_qa_result(value, item_id="CAND-1", minimum_confidence=0.86)

        self.assertEqual("NEEDS_FIX", normalized["status"])
        self.assertEqual("pass", normalized["model_reported_overall_status"])
        self.assertTrue(normalized["hard_blockers"]["mathematical_ambiguity"]["detected"])

    def test_each_required_semantic_issue_is_blocking_without_text_matching(self) -> None:
        profile_by_blocker = {
            "mathematical_ambiguity": "mathematical_validity",
            "prompt_answer_conflict": "answer_contract_alignment",
            "node_or_family_mismatch": "graph_family_alignment",
            "age_inappropriate": "child_appropriateness",
            "meaningless_formal_requirement": "diagnostic_meaningfulness",
        }
        for blocker, profile in profile_by_blocker.items():
            with self.subTest(blocker=blocker):
                normalized = normalize_semantic_qa_result(
                    _model_value(
                        profile_statuses={profile: "needs_revision"},
                        hard_blockers=_hard_blockers(**{blocker: True}),
                    ),
                    item_id="CAND-2",
                    minimum_confidence=0.86,
                )
                self.assertEqual("NEEDS_FIX", normalized["status"])

    def test_hard_issue_finding_cannot_be_downgraded_to_p2_scope(self) -> None:
        finding = {
            "severity": "P2",
            "profile": "mathematical_validity",
            "item_id": "CAND-2B",
            "issue_type": "mathematical_ambiguity",
            "code": "ambiguous_interpretation",
            "message": "Two interpretations produce different results.",
        }
        normalized = normalize_semantic_qa_result(
            _model_value(
                profile_statuses={"mathematical_validity": "pass_with_scope"},
                scope=_scope(
                    support_only=True,
                    not_for_activation=True,
                    exclude_from_coverage=True,
                    reasons=["Model attempted to scope a hard issue."],
                ),
                findings=[finding],
            ),
            item_id="CAND-2B",
            minimum_confidence=0.86,
        )

        self.assertEqual("NEEDS_FIX", normalized["status"])
        self.assertIn("semantic_qa_hard_issue_finding_blocks", {entry["code"] for entry in normalized["findings"]})

    def test_missing_or_duplicate_profiles_fail_closed(self) -> None:
        missing = _model_value()
        missing["profile_reviews"] = list(missing["profile_reviews"])[1:]
        duplicate = _model_value()
        duplicate["profile_reviews"] = list(duplicate["profile_reviews"]) + [list(duplicate["profile_reviews"])[0]]

        missing_result = normalize_semantic_qa_result(missing, item_id="CAND-3", minimum_confidence=0.86)
        duplicate_result = normalize_semantic_qa_result(duplicate, item_id="CAND-4", minimum_confidence=0.86)

        self.assertEqual("NEEDS_FIX", missing_result["status"])
        self.assertEqual("NEEDS_FIX", duplicate_result["status"])
        self.assertIn("semantic_qa_profile_coverage_invalid", {finding["code"] for finding in missing_result["findings"]})
        self.assertIn("semantic_qa_profile_coverage_invalid", {finding["code"] for finding in duplicate_result["findings"]})

    def test_pass_with_scope_requires_complete_structured_restrictions(self) -> None:
        malformed = _model_value(
            profile_statuses={"diagnostic_meaningfulness": "pass_with_scope"},
            overall_status="pass_with_scope",
            scope={"support_only": True},
        )

        normalized = normalize_semantic_qa_result(malformed, item_id="CAND-5", minimum_confidence=0.86)

        self.assertEqual("NEEDS_FIX", normalized["status"])
        self.assertIn("semantic_qa_scope_invalid", {finding["code"] for finding in normalized["findings"]})

    def test_clean_pass_also_requires_explicit_empty_scope_contract(self) -> None:
        malformed = _model_value()
        malformed.pop("scope")

        normalized = normalize_semantic_qa_result(malformed, item_id="CAND-5B", minimum_confidence=0.86)

        self.assertEqual("NEEDS_FIX", normalized["status"])
        self.assertIn("semantic_qa_scope_invalid", {finding["code"] for finding in normalized["findings"]})

    def test_valid_pass_with_scope_keeps_all_restrictions(self) -> None:
        restrictions = _scope(
            support_only=True,
            not_for_activation=True,
            exclude_from_coverage=True,
            reasons=["Useful only as reviewer support evidence."],
        )
        value = _model_value(
            profile_statuses={"diagnostic_meaningfulness": "pass_with_scope"},
            overall_status="pass",
            scope=restrictions,
        )

        normalized = normalize_semantic_qa_result(value, item_id="CAND-6", minimum_confidence=0.86)

        self.assertEqual("PASS_WITH_SCOPE", normalized["status"])
        self.assertEqual(restrictions, normalized["scope"])

    def test_clean_profiles_normalize_to_pass_even_if_overall_claim_disagrees(self) -> None:
        normalized = normalize_semantic_qa_result(
            _model_value(overall_status="reject"),
            item_id="CAND-7",
            minimum_confidence=0.86,
        )

        self.assertEqual("PASS", normalized["status"])
        self.assertEqual("reject", normalized["model_reported_overall_status"])


class SemanticQAStagingTests(unittest.TestCase):
    def _receipts(self, source_path: Path, *, semantic_status: str = "PASS", scope: dict[str, object] | None = None) -> dict[str, dict[str, object]]:
        item = {
            "id": "CAND-STAGING",
            "node_id": "M-G7-NUMBER-LINE",
            "question_type": "number_line_position_distance",
        }
        candidate_sha = hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        identity = {
            "item_id": item["id"],
            "node_id": item["node_id"],
            "family_id": item["question_type"],
            "candidate_sha256": candidate_sha,
            "source_file_sha256": source_sha,
            "source_path": str(source_path),
        }
        machine = {
            "schema_version": "2026-07-23.codex-admin.production-candidate-check.v1",
            "status": "SELF_CHECKED_PASS",
            "requirement_scope": {
                "support_only": False,
                "not_for_activation": False,
                "exclude_from_coverage": False,
                "secondary_nodes": [],
            },
            **{key: identity[key] for key in ("item_id", "node_id", "family_id", "candidate_sha256")},
        }
        expert = {
            "schema_version": "2026-07-23.codex-admin.candidate-expert-review.v1",
            "status": "PASS",
            "finding_counts": {},
            "findings": [],
            **identity,
        }
        model_expert = {
            "schema_version": "2026-07-23.codex-admin.model-expert-board-review.v1",
            "status": "PASS",
            "provider_mode": "live_model",
            "route": {"raw_response_sha256": "raw", "structured_json_mode": "json_schema"},
            "prompt_meta": {"rendered_prompt_sha256": "prompt", "response_schema_sha256": "schema"},
            "model_expert_review_json_path": "model-expert.json",
            "finding_counts": {},
            "findings": [],
            **identity,
        }
        contract = {
            "schema_version": "2026-07-24.codex-admin.candidate-qa-contract-check.v1",
            "gate_type": "deterministic_contract_check",
            "status": "PASS",
            "qa_contract_check_json_path": "qa-contract.json",
            "finding_counts": {},
            "findings": [],
            **identity,
        }
        contract_digest = hashlib.sha256(
            json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        semantic = {
            "schema_version": "2026-07-23.codex-admin.candidate-qa-review.v1",
            "gate_type": "live_model_semantic_qa",
            "status": semantic_status,
            "provider_mode": "live_model",
            "route": {"raw_response_sha256": "raw", "structured_json_mode": "json_schema"},
            "prompt_meta": {"rendered_prompt_sha256": "prompt", "response_schema_sha256": "schema"},
            "profile_reviews": [
                {"profile": profile, "status": "pass" if semantic_status == "PASS" else "pass_with_scope"}
                for profile in REQUIRED_SEMANTIC_QA_PROFILES
            ],
            "hard_blockers": _hard_blockers(),
            "scope": scope or _scope(),
            "qa_contract_report_sha256": contract_digest,
            "status_normalization": {
                "authority": "deterministic_from_profile_verdicts",
                "model_overall_status_is_advisory": True,
            },
            "qa_json_path": "semantic-qa.json",
            "finding_counts": {},
            "findings": [],
            **identity,
        }
        return {
            "machine_report": machine,
            "expert_report": expert,
            "model_expert_report": model_expert,
            "qa_contract_report": contract,
            "semantic_qa_report": semantic,
        }

    def test_scoped_semantic_result_is_not_staged_or_counted_for_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "candidate.json"
            source.write_text("{}", encoding="utf-8")
            receipts = self._receipts(
                source,
                semantic_status="PASS_WITH_SCOPE",
                scope=_scope(
                    support_only=True,
                    not_for_activation=True,
                    exclude_from_coverage=True,
                    reasons=["Support evidence only."],
                ),
            )

            decision = decide_staging_from_receipts(root=Path(tmp), **receipts)

        self.assertEqual("SCOPED_NOT_STAGED", decision["status"])
        self.assertFalse(decision["staging_allowed"])
        self.assertFalse(decision["coverage_eligible"])
        self.assertTrue(decision["staging_scope"]["exclude_from_coverage"])

    def test_clean_live_semantic_pass_allows_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "candidate.json"
            source.write_text("{}", encoding="utf-8")
            receipts = self._receipts(source)

            decision = decide_staging_from_receipts(root=Path(tmp), **receipts)

        self.assertEqual("STAGED_READY", decision["status"])
        self.assertTrue(decision["staging_allowed"])
        self.assertTrue(decision["coverage_eligible"])

    def test_model_scope_is_union_preserved_when_semantic_qa_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "candidate.json"
            source.write_text("{}", encoding="utf-8")
            receipts = self._receipts(source)
            receipts["model_expert_report"]["status"] = "PASS_WITH_SCOPE"
            receipts["model_expert_report"]["overall_status"] = "pass_with_scope"
            receipts["model_expert_report"]["scope"] = _scope(
                support_only=True,
                not_for_activation=True,
                exclude_from_coverage=True,
                reasons=["Model expert requires restricted use."],
            )

            decision = decide_staging_from_receipts(root=Path(tmp), **receipts)

        self.assertEqual("NEEDS_REGENERATION", decision["status"])
        self.assertFalse(decision["staging_allowed"])
        self.assertTrue(decision["staging_scope"]["support_only"])
        self.assertTrue(decision["staging_scope"]["exclude_from_coverage"])
        self.assertIn("Model expert requires restricted use.", decision["staging_scope"]["reasons"])

    def test_non_live_semantic_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "candidate.json"
            source.write_text("{}", encoding="utf-8")
            receipts = self._receipts(source)
            receipts["semantic_qa_report"]["provider_mode"] = "not_configured"
            receipts["semantic_qa_report"]["status"] = "BLOCKED_MODEL_NOT_CONFIGURED"

            decision = decide_staging_from_receipts(root=Path(tmp), **receipts)

        self.assertEqual("NEEDS_REGENERATION", decision["status"])
        self.assertFalse(decision["staging_allowed"])
        self.assertIn("semantic_qa_not_live_model", {finding["code"] for finding in decision["findings"]})


class SemanticQAModelCallTests(unittest.TestCase):
    def test_semantic_gate_calls_question_reviewer_with_structured_contract(self) -> None:
        captured: dict[str, object] = {}

        def fake_call(route, payload, *, schema, **kwargs):
            captured["route"] = route
            captured["payload"] = payload
            captured["schema"] = schema
            value = _model_value()
            return model_router.StructuredJSONResult(
                value=value,
                mode="json_schema",
                raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                endpoint="responses",
            )

        candidate = {
            "id": "CAND-LIVE-SEMANTIC",
            "node_id": "M-G7-NUMBER-LINE",
            "question_type": "number_line_position_distance",
            "prompt": "A candidate prompt whose meaning is reviewed by the model.",
        }
        contract_check = {
            "schema_version": "2026-07-24.codex-admin.candidate-qa-contract-check.v1",
            "status": "PASS",
            "finding_counts": {},
            "findings": [],
        }
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = Path(tmp) / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "test-key",
                    "AI_QUESTION_REVIEW_MODEL": "test-review-model",
                    "OPENAI_BASE_URL": "https://example.invalid/v1",
                },
                clear=True,
            ), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
                report = build_candidate_semantic_qa_review(
                    root=project_root,
                    candidate_path=candidate_path,
                    contract_check=contract_check,
                )

        self.assertEqual("PASS", report["status"])
        self.assertEqual("live_model", report["provider_mode"])
        self.assertEqual("question_reviewer_agent", captured["route"].agent_key)
        self.assertEqual(
            "2026-07-24.admin-question-qa-review.schema.v1",
            captured["schema"]["properties"]["schema_version"]["const"],
        )
        self.assertIn("hard_blockers", captured["schema"]["properties"])

    def test_slot_workflow_requires_and_persists_both_qa_gates_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief = _number_line_brief()
            _plan, slot, plan_path, _brief_path = _slot_generation_plan(tmp_path)

            def fake_call(route, payload, *, schema, **kwargs):
                if route.agent_key == "admin_question_expert_review_agent":
                    value = _model_expert_pass_output()
                elif route.agent_key == "question_reviewer_agent":
                    value = (
                        _semantic_collision_pass_output(payload)
                        if _is_semantic_collision_board_payload(payload)
                        else _model_value()
                    )
                else:
                    value = _wrapped_model_candidate_for_slot(brief, slot)
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )

            staged_bank = tmp_path / "staged.json"
            with mock.patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "test-key",
                    "AI_QUESTION_MODEL": "test-generation-model",
                    "AI_QUESTION_REVIEW_MODEL": "test-review-model",
                    "OPENAI_BASE_URL": "https://example.invalid/v1",
                },
                clear=True,
            ), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
                report = run_slot_production_workflow(
                    root=Path(__file__).resolve().parents[1],
                    artifact_root=tmp_path,
                    generation_plan_path=plan_path,
                    staged_bank_path=staged_bank,
                    apply=True,
                )

            step_names = [step["step"] for step in report["steps"]]
            staged = json.loads(staged_bank.read_text(encoding="utf-8")) if staged_bank.exists() else {}

        self.assertEqual("WORKFLOW_STAGED", report["status"], report)
        self.assertIn("machine_contract_check", step_names)
        self.assertIn("qa_contract_check", step_names)
        self.assertIn("semantic_qa_review", step_names)
        self.assertLess(step_names.index("qa_contract_check"), step_names.index("semantic_qa_review"))
        self.assertLess(step_names.index("semantic_qa_review"), step_names.index("staging_decision"))
        self.assertEqual(1, staged["item_count"])


if __name__ == "__main__":
    unittest.main()
