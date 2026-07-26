from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from learning_system.admin.source_receipts import SourceCandidate, write_source_receipt


class AdminConsoleSourceReceiptTests(unittest.TestCase):
    def test_commercial_source_defaults_to_no_capture_structure_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = write_source_receipt(
                SourceCandidate(
                    name="某商业教辅公开样章",
                    source_type="commercial_reference",
                    url_or_file="https://example.com/sample",
                ),
                root=root,
                apply=True,
            )

            self.assertTrue(result["write_applied"])
            self.assertEqual("structure_reference_only", result["usage_mode"])
            self.assertEqual("no_capture", result["capture_policy"])
            markdown = (root / result["receipt_markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("Content not to capture: 题干、答案、解析、图片、图形、表格、版式", markdown)
            sidecar = json.loads((root / result["receipt_json_path"]).read_text(encoding="utf-8"))
            self.assertEqual("no_capture", sidecar["capture_policy"])

    def test_open_license_without_explicit_flags_stays_scope_reference_only(self) -> None:
        result = write_source_receipt(
            SourceCandidate(
                name="Open candidate",
                source_type="open_license",
                url_or_file="https://example.com/open",
                license_observation="CC-like but unverified",
            ),
            root=Path("/tmp/non-writing-root"),
            apply=False,
        )

        self.assertFalse(result["write_applied"])
        self.assertEqual("scope_reference_only", result["usage_mode"])
        self.assertEqual("metadata_only", result["capture_policy"])
        self.assertIn("receipt_markdown_preview", result)


if __name__ == "__main__":
    unittest.main()
