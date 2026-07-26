from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from learning_system.admin.staged_cleanup import StagedCleanupError, remove_staged_items


class StagedCleanupTests(unittest.TestCase):
    def _write_fixture(self, root: Path) -> tuple[Path, Path]:
        bank_path = root / "data/question_banks/v18/staged.json"
        bank_path.parent.mkdir(parents=True)
        bank = {
            "schema_version": "test",
            "status": "staged_not_active",
            "item_count": 2,
            "items": [{"id": "Q1"}, {"id": "Q2"}],
        }
        bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        digest = hashlib.sha256(bank_path.read_bytes()).hexdigest()
        decision_path = root / "data/admin/removal_decisions/remove.json"
        decision_path.parent.mkdir(parents=True)
        decision = {
            "schema_version": "2026-07-24.codex-admin.staged-removal-decision.v1",
            "decision_id": "REMOVE-TEST",
            "source_bank_path": "data/question_banks/v18/staged.json",
            "source_bank_sha256": digest,
            "source_item_count": 2,
            "decision": "remove_from_staged_bank_and_regenerate",
            "items": [{"item_id": "Q2", "reason_code": "review_rejected"}],
        }
        decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return bank_path, decision_path

    def test_dry_run_does_not_modify_bank(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank_path, decision_path = self._write_fixture(root)
            before = bank_path.read_bytes()
            receipt = remove_staged_items(root=root, bank_path=bank_path, decision_path=decision_path)
            self.assertEqual("DRY_RUN", receipt["status"])
            self.assertEqual(before, bank_path.read_bytes())

    def test_apply_removes_only_reviewed_item_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank_path, decision_path = self._write_fixture(root)
            receipt = remove_staged_items(
                root=root,
                bank_path=bank_path,
                decision_path=decision_path,
                apply=True,
            )
            bank = json.loads(bank_path.read_text(encoding="utf-8"))
            self.assertEqual("APPLIED", receipt["status"])
            self.assertEqual(1, bank["item_count"])
            self.assertEqual(["Q1"], [item["id"] for item in bank["items"]])
            stored = json.loads(
                (root / "data/admin/removal_receipts/REMOVE-TEST.json").read_text(encoding="utf-8")
            )
            self.assertEqual("APPLIED", stored["status"])
            self.assertEqual(receipt["after_sha256"], hashlib.sha256(bank_path.read_bytes()).hexdigest())

    def test_digest_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank_path, decision_path = self._write_fixture(root)
            bank_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(StagedCleanupError, "SOURCE_DIGEST_MISMATCH"):
                remove_staged_items(root=root, bank_path=bank_path, decision_path=decision_path, apply=True)


if __name__ == "__main__":
    unittest.main()
