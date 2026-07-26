from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from learning_system.admin.expert_ideation import FAMILY_DESIGN_KERNELS
from learning_system.admin.inventory import (
    AdminPaths,
    _blueprints_by_node,
    _load_assets,
    canonical_structure_fingerprint_for_item,
    build_node_inventory,
    build_question_bank_inventory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AdminConsoleInventoryTests(unittest.TestCase):
    def test_v18_sample_inventory_is_readable_but_not_activation_ready(self) -> None:
        report = build_question_bank_inventory(root=PROJECT_ROOT, version="v18-sample", subject="math")

        self.assertEqual("2026-07-23.codex-admin.inventory.v1", report["schema_version"])
        self.assertEqual(60, report["item_count"])
        self.assertEqual(56, report["graph_node_count"])
        self.assertEqual("draft_generated_not_active", report["question_bank_status"])
        self.assertTrue(report["activation"]["sample_only"])
        self.assertFalse(report["activation"]["activation_allowed_by_inventory"])
        self.assertIn("sample_only_do_not_activate", report["recommended_actions"])

    def test_node_inventory_reports_budget_gap_and_family_coverage(self) -> None:
        report = build_node_inventory(root=PROJECT_ROOT, node_id="M-PRE-DECIMAL-OPS", version="v18-sample")

        self.assertEqual("M-PRE-DECIMAL-OPS", report["node_id"])
        self.assertEqual(6, report["item_count"])
        self.assertGreater(report["candidate_budget"]["missing_to_target"], 0)
        self.assertTrue(report["counts_by_family"])
        self.assertIn("fill_candidate_budget_gap", report["recommended_actions"])

    def test_cli_question_bank_json_output(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/admin_console.py",
                "inventory",
                "question-bank",
                "--version",
                "v18-sample",
                "--format",
                "json",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        report = json.loads(proc.stdout)
        self.assertEqual(60, report["item_count"])
        self.assertTrue(report["activation"]["sample_only"])

    def test_v18_inventory_points_to_staged_bank(self) -> None:
        staged_path = PROJECT_ROOT / "data/question_banks/v18/staged_candidates_v18.json"
        staged = json.loads(staged_path.read_text(encoding="utf-8"))

        report = build_question_bank_inventory(root=PROJECT_ROOT, version="v18", subject="math")

        self.assertEqual("data/question_banks/v18/staged_candidates_v18.json", report["source_path"])
        self.assertEqual(staged["question_bank_version"], report["question_bank_version"])
        self.assertEqual(staged["status"], report["question_bank_status"])
        self.assertEqual(len(staged["items"]), report["item_count"])
        self.assertEqual("staged_or_explicit", report["inventory_scope"])
        self.assertFalse(report["activation"]["sample_only"])
        self.assertFalse(report["activation"]["activation_allowed_by_inventory"])

    def test_canonical_fingerprint_ignores_model_supplied_fingerprint(self) -> None:
        item = {
            "node_id": "M-G7-NUMBER-LINE",
            "question_type": "number_line_position_distance",
            "difficulty": "L3",
            "prompt": "点 A 在 -2，向右 3 个单位到 B。写出 B 并说明依据。",
            "answer_format": "数值和一句依据。",
            "solution_steps": ["B=-2+3=1。", "数轴向右数值增大。"],
            "key_score_points": [{"key": "result"}, {"key": "relation"}],
            "target_error_tags": ["direction"],
            "quality": {"model_structure_fingerprint": "MODEL-A"},
        }
        changed = json.loads(json.dumps(item, ensure_ascii=False))
        changed["quality"]["model_structure_fingerprint"] = "MODEL-B"

        self.assertEqual(
            canonical_structure_fingerprint_for_item(item),
            canonical_structure_fingerprint_for_item(changed),
        )

    def test_current_staged_bank_requires_four_review_receipts(self) -> None:
        staged_path = PROJECT_ROOT / "data/question_banks/v18/staged_candidates_v18.json"
        payload = json.loads(staged_path.read_text(encoding="utf-8"))
        required = {
            "machine_report_sha256",
            "expert_report_sha256",
            "model_expert_report_sha256",
            "qa_report_sha256",
        }
        for item in payload.get("items") or []:
            quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
            receipts = quality.get("staging_receipts") if isinstance(quality.get("staging_receipts"), dict) else {}
            missing = sorted(required - set(receipts))
            self.assertFalse(missing, f"{item.get('id')} missing staged receipt hashes: {missing}")

    def test_current_staged_bank_items_carry_review_logic_evidence(self) -> None:
        staged_path = PROJECT_ROOT / "data/question_banks/v18/staged_candidates_v18.json"
        payload = json.loads(staged_path.read_text(encoding="utf-8"))
        for item in payload.get("items") or []:
            review_evidence = item.get("quality", {}).get("review_evidence") or {}
            self.assertEqual("2026-07-23.codex-admin.item-review-evidence.v1", review_evidence.get("schema_version"), item.get("id"))
            review_logic = review_evidence.get("review_logic") or {}
            self.assertIn("frontline_math_teacher", review_logic.get("deterministic_expert_review", {}).get("profiles", {}), item.get("id"))
            self.assertEqual("live_model", review_logic.get("model_expert_board_review", {}).get("required_provider_mode"), item.get("id"))
            qa_logic = review_logic.get("guanzhi_qa_review") or review_logic.get("semantic_qa_review") or {}
            expected_checks = qa_logic.get("quality_checks") or (
                ["child_surface_has_no_internal_leaks"]
                if qa_logic.get("gate_type") == "live_model_semantic_qa"
                else []
            )
            self.assertIn(
                "child_surface_has_no_internal_leaks",
                expected_checks,
                item.get("id"),
            )
            receipts = review_evidence.get("receipts") or {}
            self.assertIn(receipts.get("deterministic_expert_review", {}).get("status"), {"PASS", "PASS_WITH_SCOPE"}, item.get("id"))
            semantic_receipt = receipts.get("guanzhi_qa_review") or receipts.get("semantic_qa_review") or {}
            self.assertIn(semantic_receipt.get("status"), {"PASS", "PASS_WITH_SCOPE"}, item.get("id"))

    def test_all_blueprint_families_have_expert_design_kernels(self) -> None:
        paths = AdminPaths(root=PROJECT_ROOT)
        _graph, _sample, blueprints_json, _taxonomy = _load_assets(paths)
        blueprints = _blueprints_by_node(blueprints_json)
        used_families = {
            str(entry.get("family_id") or "")
            for blueprint in blueprints.values()
            for entry in blueprint.get("family_plan") or []
            if entry.get("family_id")
        }
        self.assertFalse(sorted(used_families - set(FAMILY_DESIGN_KERNELS)))


if __name__ == "__main__":
    unittest.main()
