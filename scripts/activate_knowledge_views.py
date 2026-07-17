#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, knowledge_map
from learning_system.graph_runtime import GraphRuntimeService
from learning_system.knowledge_view_config import KnowledgeViewConfig


RECEIPT_SCHEMA_VERSION = "knowledge-views-activation.v1"
DEFAULT_CONFIG = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_views_v5_1.json"


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
        raise ValueError("knowledge view config path is unsafe or missing")
    return candidate, str(candidate.relative_to(root))


def read_only_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def backup_database(db_path: Path, backup_root: Path) -> dict[str, str]:
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backup_root / f"{db_path.stem}.pre-knowledge-views-v5.1.{stamp}.sqlite"
    source_conn = sqlite3.connect(str(db_path))
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    return {"path": str(target), "sha256": file_sha256(target)}


def candidate_authority(db_path: Path, config_path: Path) -> dict[str, object]:
    config_file, relative_path = safe_project_file(config_path)
    snapshot = GraphRuntimeService(project_root=PROJECT_ROOT).graph_snapshot()
    config = KnowledgeViewConfig.load_validated(config_file, snapshot)
    if not config.validation_report.get("valid"):
        raise ValueError("knowledge view config validation failed")
    with read_only_connection(db_path) as conn:
        row = conn.execute("select value from system_meta where key = 'graph_ref'").fetchone()
        graph_ref = db.json_load(row["value"], {}) if row else {}
        secret_row = conn.execute(
            "select value from system_meta where key = ?",
            (knowledge_map.HANDLE_SECRET_KEY,),
        ).fetchone()
    if graph_ref.get("lineage") != snapshot["graph_lineage"]:
        raise ValueError("database graph lineage does not match current graph")
    existing_secret = str(secret_row["value"] if secret_row else "")
    secret_valid = len(knowledge_map._secret_bytes(existing_secret)) >= 32
    receipt = {
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "config_version": config.config_version,
        "config_sha256": config.canonical_sha256(),
        "graph_lineage": snapshot["graph_lineage"],
        "relative_path": relative_path,
        "handle_policy_version": knowledge_map.HANDLE_POLICY_VERSION,
        "activated_at": db.now_iso(),
    }
    return {
        "receipt": receipt,
        "secret": existing_secret if secret_valid else secrets.token_hex(32),
        "secret_reused": secret_valid,
        "validation_report": config.validation_report,
    }


def audit(db_path: Path) -> dict[str, object]:
    with read_only_connection(db_path) as conn:
        receipt_row = conn.execute(
            "select value from system_meta where key = ?",
            (knowledge_map.VIEW_RECEIPT_KEY,),
        ).fetchone()
        secret_row = conn.execute(
            "select value from system_meta where key = ?",
            (knowledge_map.HANDLE_SECRET_KEY,),
        ).fetchone()
    if not receipt_row or not secret_row:
        raise ValueError("knowledge view activation receipt is missing")
    receipt = db.json_load(receipt_row["value"], {})
    expected_keys = {
        "receipt_schema_version",
        "config_version",
        "config_sha256",
        "graph_lineage",
        "relative_path",
        "handle_policy_version",
        "activated_at",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_keys:
        raise ValueError("knowledge view activation receipt schema is invalid")
    if (
        receipt["receipt_schema_version"] != RECEIPT_SCHEMA_VERSION
        or receipt["handle_policy_version"] != knowledge_map.HANDLE_POLICY_VERSION
        or len(knowledge_map._secret_bytes(secret_row["value"])) < 32
    ):
        raise ValueError("knowledge view activation lineage is invalid")
    config_path, relative_path = safe_project_file(PROJECT_ROOT / receipt["relative_path"])
    snapshot = GraphRuntimeService(project_root=PROJECT_ROOT).graph_snapshot()
    config = KnowledgeViewConfig.load_validated(config_path, snapshot)
    if (
        relative_path != receipt["relative_path"]
        or receipt["config_version"] != config.config_version
        or receipt["config_sha256"] != config.canonical_sha256()
        or receipt["graph_lineage"] != snapshot["graph_lineage"]
        or not config.validation_report.get("valid")
    ):
        raise ValueError("knowledge view activation receipt is stale")
    return {
        "status": "active",
        "config_version": config.config_version,
        "config_sha256": config.canonical_sha256(),
        "graph_lineage": snapshot["graph_lineage"],
        "handle_secret_present": True,
    }


def activate(db_path: Path, config_path: Path, backup_root: Path) -> dict[str, object]:
    authority = candidate_authority(db_path, config_path)
    backup = backup_database(db_path, backup_root)
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
            (
                knowledge_map.VIEW_RECEIPT_KEY,
                db.json_dump(authority["receipt"]),
                authority["receipt"]["activated_at"],
            ),
        )
        conn.execute(
            "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
            (
                knowledge_map.HANDLE_SECRET_KEY,
                authority["secret"],
                authority["receipt"]["activated_at"],
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {**audit(db_path), "status": "activated", "backup": backup, "secret_reused": authority["secret_reused"]}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit or activate the v5.1 knowledge views")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
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
            result = activate(args.db, args.config, args.backup_root)
        elif args.audit:
            result = audit(args.db)
        else:
            authority = candidate_authority(args.db, args.config)
            result = {
                "status": "dry_run",
                "activation_ready": True,
                "config_version": authority["receipt"]["config_version"],
                "config_sha256": authority["receipt"]["config_sha256"],
                "graph_lineage": authority["receipt"]["graph_lineage"],
                "handle_secret_would_be_reused": authority["secret_reused"],
                "validation_report": authority["validation_report"],
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
