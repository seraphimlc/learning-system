#!/usr/bin/env python3
"""Audit question bank items: verify calculation answers via sympy.

Usage:
  python3 scripts/audit_question_bank_answers.py --db PATH         # sqlite question_items
  python3 scripts/audit_question_bank_answers.py --json FILE       # [{prompt, expected_answer, ...}]

Exit codes:
  0  audit completed, no mismatches
  1  audit completed, at least one mismatch
  2  operational failure (db/json path missing, db lacks question_items
     table, json unreadable / parse error / top level not a list) — the
     same code argparse uses for usage errors
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

# scripts/ 下的脚本直接运行时机 sys.path[0] 是 scripts/，需引导到仓库根（照抄现有脚本惯例）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system.answer_verification import verify_expected_answer  # noqa: E402


class AuditError(Exception):
    """操作失败（路径不存在 / 缺表 / JSON 非法），由 main 统一转为退出码 2。"""


def _read_only_connection(path: Path) -> sqlite3.Connection:
    # 照抄 generate_answer_contracts.py 的只读连接惯例：mode=ro 防止审计工具误建文件
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def _items_from_db(path: Path):
    if not path.exists():
        raise AuditError(f"数据库文件不存在: {path}")
    conn = _read_only_connection(path)
    try:
        rows = conn.execute(
            "select prompt, expected_answer from question_items"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise AuditError(f"db 缺少 question_items 表或列: {exc}") from exc
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _items_from_json(path: Path):
    if not path.exists():
        raise AuditError(f"JSON 文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuditError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, list):
        raise AuditError(f"JSON 顶层必须是 list，实际是: {type(data).__name__}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--db", type=Path)
    group.add_argument("--json", type=Path, dest="json_path")
    args = parser.parse_args(argv)
    try:
        if args.db:
            items = _items_from_db(args.db)
        else:
            items = _items_from_json(args.json_path)
    except AuditError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
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
