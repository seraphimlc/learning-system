from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from learning_system.admin.expert_ideation import build_expert_design_ideas
from learning_system.admin.production_loop import (
    build_question_requirement_plan,
    decide_staging_from_receipts,
)
from learning_system.admin.question_generation import _normalize_model_item
from learning_system.admin.qa_review import REQUIRED_SEMANTIC_QA_PROFILES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXECUTION_SCOPE_FIELDS = (
    "support_only",
    "not_for_activation",
    "exclude_from_coverage",
    "secondary_nodes",
)


def _write_brief(tmp_path: Path, brief: dict, name: str = "brief.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    return path


def _requirement_plan(brief: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        brief_path = _write_brief(Path(tmp), brief)
        return build_question_requirement_plan(
            root=PROJECT_ROOT,
            node_id=str(brief["node_id"]),
            version="v18",
            design_brief_path=brief_path,
        )


def _scope(*, support_only: bool = False) -> dict[str, object]:
    return {
        "support_only": support_only,
        "not_for_activation": support_only,
        "exclude_from_coverage": support_only,
        "reasons": ["Canonical requirement is support-only."] if support_only else [],
    }


def _hard_blockers() -> dict[str, dict[str, object]]:
    return {
        key: {"detected": False, "evidence": []}
        for key in (
            "mathematical_ambiguity",
            "prompt_answer_conflict",
            "node_or_family_mismatch",
            "age_inappropriate",
            "meaningless_formal_requirement",
        )
    }


def _clean_receipts(source_path: Path, *, requirement_scope: dict[str, object]) -> dict[str, dict[str, object]]:
    item = {
        "id": "CAND-SUPPORT-SCOPE",
        "node_id": "M-BRIDGE-SOLUTION-HABIT",
        "question_type": "solution_trace_repair",
    }
    candidate_sha = hashlib.sha256(
        json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    identity = {
        "item_id": item["id"],
        "node_id": item["node_id"],
        "family_id": item["question_type"],
        "candidate_sha256": candidate_sha,
        "source_file_sha256": source_sha,
        "source_path": str(source_path),
        "requirement_scope": copy.deepcopy(requirement_scope),
    }
    machine = {
        "schema_version": "2026-07-23.codex-admin.production-candidate-check.v1",
        "status": "SELF_CHECKED_PASS",
        **identity,
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
        "status": "PASS",
        "provider_mode": "live_model",
        "route": {"raw_response_sha256": "raw", "structured_json_mode": "json_schema"},
        "prompt_meta": {"rendered_prompt_sha256": "prompt", "response_schema_sha256": "schema"},
        "profile_reviews": [
            {"profile": profile, "status": "pass"}
            for profile in REQUIRED_SEMANTIC_QA_PROFILES
        ],
        "hard_blockers": _hard_blockers(),
        "scope": _scope(),
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


class RequirementScopeTrustTests(unittest.TestCase):
    def test_requirement_plan_rejects_each_missing_execution_scope_field(self) -> None:
        canonical = build_expert_design_ideas(
            root=PROJECT_ROOT,
            node_id="M-G7-NUMBER-LINE",
            version="v18",
        )
        expected_code = {
            field: f"requirement_missing_{field}"
            for field in EXECUTION_SCOPE_FIELDS
        }

        for field in EXECUTION_SCOPE_FIELDS:
            with self.subTest(field=field):
                brief = copy.deepcopy(canonical)
                brief["question_requirements"][0].pop(field)

                plan = _requirement_plan(brief)
                codes = {finding["code"] for finding in plan["findings"]}

                self.assertEqual("BLOCKED", plan["status"])
                self.assertIn(expected_code[field], codes)

    def test_requirement_plan_rejects_execution_scope_tampering(self) -> None:
        canonical = build_expert_design_ideas(
            root=PROJECT_ROOT,
            node_id="M-G7-NUMBER-LINE",
            version="v18",
        )
        tampered_values = {
            "support_only": True,
            "not_for_activation": True,
            "exclude_from_coverage": True,
            "secondary_nodes": ["M-G7-POS-NEG"],
        }

        for field, value in tampered_values.items():
            with self.subTest(field=field):
                brief = copy.deepcopy(canonical)
                brief["question_requirements"][0][field] = value

                plan = _requirement_plan(brief)
                codes = {finding["code"] for finding in plan["findings"]}

                self.assertEqual("BLOCKED", plan["status"])
                self.assertIn(f"requirement_{field}_mismatch", codes)

    def test_support_only_requirement_cannot_be_promoted_to_coverage(self) -> None:
        brief = build_expert_design_ideas(
            root=PROJECT_ROOT,
            node_id="M-BRIDGE-SOLUTION-HABIT",
            version="v18",
        )
        requirement = brief["question_requirements"][0]
        self.assertTrue(requirement["support_only"])
        requirement.update(
            {
                "coverage_role": "entry_probe",
                "support_only": False,
                "not_for_activation": False,
                "exclude_from_coverage": False,
            }
        )

        plan = _requirement_plan(brief)
        codes = {finding["code"] for finding in plan["findings"]}

        self.assertEqual("BLOCKED", plan["status"])
        self.assertIn("requirement_support_role_mismatch", codes)
        self.assertIn("requirement_support_only_mismatch", codes)
        self.assertIn("requirement_not_for_activation_mismatch", codes)
        self.assertIn("requirement_exclude_from_coverage_mismatch", codes)

    def test_nonempty_secondary_nodes_propagate_to_trusted_candidate_identity(self) -> None:
        secondary_nodes = ["M-G7-POS-NEG", "M-PRE-NUMBER-SENSE"]
        requirement = {
            "question_requirement_id": "REQ-secondary-node-test",
            "slot_id": "M-G7-NUMBER-LINE:number_line_reference_frame:01",
            "node_id": "M-G7-NUMBER-LINE",
            "family_id": "number_line_reference_frame",
            "difficulty": "L2",
            "evidence_goal": "识别数轴参照系",
            "must_include": ["原点", "正方向", "单位长度"],
            "support_only": False,
            "not_for_activation": False,
            "exclude_from_coverage": False,
            "secondary_nodes": secondary_nodes,
        }
        plan = {
            "design_brief_id": "BRIEF-secondary-node-test",
            "node_id": "M-G7-NUMBER-LINE",
            "family_id": "number_line_reference_frame",
            "bounded_candidate_packet": {
                "family_plan_entry": {"required_evidence": ["数轴三要素"]},
            },
        }
        output = {
            "item": {
                "prompt": "在给出的数轴上填写指定点表示的数。",
                "design_rationale": "同时保留正负数与估算前置证据。",
            }
        }

        candidate = _normalize_model_item(
            output,
            plan=plan,
            requirement=requirement,
            generation_attempt=1,
            previous_rejection_codes=[],
        )

        self.assertEqual(secondary_nodes, candidate["secondary_node_ids"])

    def test_model_clean_pass_cannot_override_canonical_support_scope(self) -> None:
        requirement_scope = {
            "coverage_role": "support_only",
            "support_only": True,
            "not_for_activation": True,
            "exclude_from_coverage": True,
            "secondary_nodes": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "candidate.json"
            source.write_text("{}", encoding="utf-8")
            decision = decide_staging_from_receipts(
                root=Path(tmp),
                **_clean_receipts(source, requirement_scope=requirement_scope),
            )

        self.assertNotEqual("STAGED_READY", decision["status"])
        self.assertFalse(decision["staging_allowed"])
        self.assertFalse(decision["coverage_eligible"])
        self.assertTrue(decision["staging_scope"]["support_only"])
        self.assertTrue(decision["staging_scope"]["not_for_activation"])
        self.assertTrue(decision["staging_scope"]["exclude_from_coverage"])


if __name__ == "__main__":
    unittest.main()
