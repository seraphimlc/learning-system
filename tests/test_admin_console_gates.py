from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from learning_system.admin.expert_review import build_expert_quality_review, write_expert_quality_review
from learning_system.admin.gates import validate_admin_readiness


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AdminConsoleGateTests(unittest.TestCase):
    def test_sample_integrity_passes_with_scope_when_expert_review_has_no_blockers(self) -> None:
        expert = build_expert_quality_review(root=PROJECT_ROOT, version="v18")
        with tempfile.TemporaryDirectory() as tmp:
            expert_receipt = write_expert_quality_review(expert, root=Path(tmp), apply=True)
            report = validate_admin_readiness(
                root=PROJECT_ROOT,
                mode="sample-integrity",
                expert_report_path=Path(tmp) / expert_receipt["review_json_path"],
            )

        self.assertEqual("PASS_WITH_SCOPE", report["status"])
        self.assertFalse(report["activation_allowed"])
        self.assertFalse(report["expert_gate"]["blocking"])

    def test_activation_readiness_fails_closed_for_sample_manifest(self) -> None:
        report = validate_admin_readiness(root=PROJECT_ROOT, mode="activation-readiness")

        self.assertEqual("FAIL_CLOSED", report["status"])
        self.assertFalse(report["activation_allowed"])
        self.assertIn("not activation-ready", report["reason"])

    def test_expert_blocker_fails_closed_even_when_base_sample_integrity_passes(self) -> None:
        expert = build_expert_quality_review(root=PROJECT_ROOT, version="v18")
        expert["status"] = "NEEDS_FIX"
        expert["finding_counts"] = {"P1": 1}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "expert.json"
            path.write_text(json.dumps(expert, ensure_ascii=False), encoding="utf-8")
            report = validate_admin_readiness(root=PROJECT_ROOT, mode="sample-integrity", expert_report_path=path)

        self.assertEqual("FAIL_CLOSED", report["status"])
        self.assertFalse(report["activation_allowed"])
        self.assertEqual("expert_quality_review_has_blocking_findings", report["reason"])


if __name__ == "__main__":
    unittest.main()
