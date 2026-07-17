#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, question_visuals


DEFAULT_MANIFEST = PROJECT_ROOT / "data/question_visuals/math_question_visual_manifest_v1.json"
DEFAULT_INVENTORY = PROJECT_ROOT / "data/question_visuals/math_question_visual_inventory_v1.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_project_file(path: Path) -> tuple[Path, str]:
    candidate = path.resolve()
    root = PROJECT_ROOT.resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
        raise ValueError("question visual activation path is unsafe or missing")
    return candidate, str(candidate.relative_to(root))


def read_only_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def backup_database(db_path: Path, backup_root: Path) -> dict[str, str]:
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backup_root / f"{db_path.stem}.pre-question-visual-v1.{stamp}.sqlite"
    source_conn = sqlite3.connect(str(db_path))
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    return {"path": str(target), "sha256": file_sha256(target)}


def candidate_receipt(manifest_path: Path, inventory_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    manifest_file, manifest_relative = safe_project_file(manifest_path)
    inventory_file, inventory_relative = safe_project_file(inventory_path)
    manifest = question_visuals.QuestionVisualManifest.load_validated(
        manifest_file,
        inventory_path=inventory_file,
    )
    report = manifest.audit_report
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))
    if report["pending_inventory_slots"]:
        raise ValueError("question visual inventory still has refresh-pending required slots")
    if report["required_triple_count"] != 40 or report["manifest_entry_count"] != 40:
        raise ValueError("question visual activation requires exactly 40 required triples")
    activated_at = db.now_iso()
    receipt = {
        "receipt_schema_version": question_visuals.ACTIVE_RECEIPT_SCHEMA_VERSION,
        "manifest_version": manifest.payload["manifest_version"],
        "manifest_sha256": report["manifest_sha256"],
        "inventory_version": inventory["inventory_version"],
        "inventory_sha256": report["inventory_sha256"],
        "relative_path": manifest_relative,
        "inventory_relative_path": inventory_relative,
        "renderer_contract_version": manifest.payload["renderer_contract_version"],
        "required_triple_count": report["required_triple_count"],
        "required_triples_sha256": report["required_triples_sha256"],
        "activated_at": activated_at,
    }
    return receipt, report


def audit(db_path: Path) -> dict[str, object]:
    with read_only_connection(db_path) as conn:
        manifest = question_visuals.QuestionVisualManifest.load_active(
            conn,
            project_root=PROJECT_ROOT,
        )
    report = manifest.audit_report
    if report["pending_inventory_slots"] or report["required_triple_count"] != 40:
        raise ValueError("active question visual receipt is incomplete")
    return {
        "status": "active",
        "manifest_version": manifest.payload["manifest_version"],
        "manifest_sha256": report["manifest_sha256"],
        "inventory_sha256": report["inventory_sha256"],
        "required_triple_count": report["required_triple_count"],
        "required_triples_sha256": report["required_triples_sha256"],
        "viewbox_all_inside": report["viewbox_all_inside"],
    }


def activate(db_path: Path, manifest_path: Path, inventory_path: Path, backup_root: Path) -> dict[str, object]:
    receipt, _report = candidate_receipt(manifest_path, inventory_path)
    backup = backup_database(db_path, backup_root)
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
            (
                question_visuals.ACTIVE_RECEIPT_KEY,
                db.json_dump(receipt),
                receipt["activated_at"],
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {**audit(db_path), "status": "activated", "backup": backup}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit or activate typed question visuals")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--backup-root", type=Path, default=PROJECT_ROOT / "data/backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--activate", action="store_true")
    mode.add_argument("--audit", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if not args.db.is_file():
            raise ValueError("database path is missing")
        if args.activate:
            result = activate(args.db, args.manifest, args.inventory, args.backup_root)
        elif args.audit:
            result = audit(args.db)
        else:
            receipt, report = candidate_receipt(args.manifest, args.inventory)
            result = {
                "status": "dry_run",
                "activation_ready": True,
                "manifest_version": receipt["manifest_version"],
                "manifest_sha256": receipt["manifest_sha256"],
                "inventory_sha256": receipt["inventory_sha256"],
                "required_triple_count": receipt["required_triple_count"],
                "required_triples_sha256": receipt["required_triples_sha256"],
                "viewbox_all_inside": report["viewbox_all_inside"],
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "activation_ready": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
