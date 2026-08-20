#!/usr/bin/env python3
"""Audit question bank items: verify calculation answers via sympy.

Usage:
  python3 scripts/audit_question_bank_answers.py --db PATH         # sqlite question_items
  python3 scripts/audit_question_bank_answers.py --json FILE       # [{prompt, expected_answer, ...}]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# scripts/ 下的脚本直接运行时机 sys.path[0] 是 scripts/，需引导到仓库根（照抄现有脚本惯例）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system.answer_verification import verify_expected_answer  # noqa: E402


def _items_from_db(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select prompt, expected_answer from question_items"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise SystemExit(f"db 缺少 question_items 表或列: {exc}") from exc
    finally:
        conn.close()
    return [dict(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--db", type=Path)
    group.add_argument("--json", type=Path, dest="json_path")
    args = parser.parse_args()
    items = _items_from_db(args.db) if args.db else json.loads(args.json_path.read_text(encoding="utf-8"))
    verified = mismatch = unverifiable = 0
    mismatches = []
    for item in items:
        expected = item.get("expected_answer")
        if expected is None or str(expected).strip() == "":
            unverifiable += 1
            continue
        result = verify_expected_answer(str(item.get("prompt", "")), str(expected))
        if result["verdict"] == "verified":
            verified += 1
        elif result["verdict"] == "mismatch":
            mismatch += 1
            mismatches.append((item.get("prompt", "")[:40], result["expected"]))
        else:
            unverifiable += 1
    print(json.dumps({
        "total": len(items), "verified": verified,
        "mismatch": mismatch, "unverifiable": unverifiable,
        "mismatch_samples": mismatches[:20],
    }, ensure_ascii=False, indent=2))
    return 0 if mismatch == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
