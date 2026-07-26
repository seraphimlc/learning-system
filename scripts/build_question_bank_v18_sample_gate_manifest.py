#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import validate_question_bank_v18_sample  # noqa: E402

MANIFEST_PATH = ROOT / "data/question_banks/v18/sample_gate_manifest_v18.json"

INPUTS = {
    "taxonomy": ROOT / "data/question_banks/v18/question_type_taxonomy_v18.json",
    "blueprints": ROOT / "data/question_banks/v18/node_question_blueprints_v18.json",
    "sample": ROOT / "data/question_banks/v18/math_v18_sample_60.json",
    "blueprint_generator": ROOT / "scripts/build_question_bank_v18_blueprints.py",
    "sample_generator": ROOT / "scripts/generate_question_bank_v18_sample.py",
    "blueprint_validator": ROOT / "scripts/validate_question_bank_v18_blueprints.py",
    "sample_validator": ROOT / "scripts/validate_question_bank_v18_sample.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> dict[str, Any]:
    validation = validate_question_bank_v18_sample.validate()
    sample = json.loads(INPUTS["sample"].read_text(encoding="utf-8"))
    item_ids = [item["id"] for item in sample["items"]]
    return {
        "schema_version": "2026-07-22.question-bank-v18.sample-gate-manifest",
        "status": "sample_static_qa_passed_scope_limited",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample_question_bank_version": sample["question_bank_version"],
        "sample_item_count": sample["item_count"],
        "sample_node_count": sample["node_count"],
        "sample_question_ids": item_ids,
        "input_digests": {
            name: {
                "path": str(path.relative_to(ROOT)),
                "sha256": _sha256(path),
            }
            for name, path in INPUTS.items()
        },
        "validation": validation,
        "review_receipts": [
            {
                "reviewer": "education_expert",
                "status": "PASS_WITH_SCOPE",
                "scope": "semantic sample review before final fixes; fixes were subsequently applied",
            },
            {
                "reviewer": "guanzhi",
                "status": "PASS_WITH_SCOPE",
                "scope": "static sample QA and false-pass audit; no browser/model runtime proof",
            },
        ],
        "not_authorized_for": [
            "child_runtime_activation",
            "full_bank_generation_without_same_digest",
            "claiming live model assessment quality",
        ],
        "next_gate_required": [
            "v18 import/activate fail-closed gate",
            "candidate packet mapping test",
            "live model grading sample regression",
            "browser child-flow regression",
        ],
    }


def main() -> None:
    manifest = build_manifest()
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {MANIFEST_PATH}")
    print(json.dumps({"status": manifest["status"], "sample_item_count": manifest["sample_item_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
