#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, question_bank
from learning_system.graph_runtime import GraphRuntimeService


class QuestionBankReleaseError(RuntimeError):
    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} path is unsafe or missing")
    candidate = expanded.resolve()
    if not candidate.is_file():
        raise ValueError(f"{label} path is unsafe or missing")
    return candidate


def _load_json_object(path: Path, label: str) -> tuple[Path, dict[str, Any]]:
    candidate = _regular_file(path, label)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return candidate, value


def _candidate_authority(
    manifest_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    manifest_file, manifest = _load_json_object(manifest_path, "manifest")
    receipt_file, receipt = _load_json_object(receipt_path, "receipt")
    manifest_sha256 = question_bank.v12_canonical_manifest_sha256(manifest)
    if receipt.get("canonical_manifest_sha256") != manifest_sha256:
        raise ValueError(
            "V12 active seed requires trusted live runner receipt: manifest hash mismatch"
        )
    if receipt.get("schema_version") != question_bank.V12_RUNNER_RECEIPT_SCHEMA_VERSION:
        raise ValueError(
            "V12 active seed requires trusted live runner receipt: schema_version"
        )
    if receipt.get("runner_mode") != "live" or receipt.get("status") != "completed":
        raise ValueError(
            "V12 active seed requires trusted live runner receipt: live completed status"
        )
    for key in ("manifest_id", "question_bank_version", "graph_version"):
        if receipt.get(key) != manifest.get(key):
            raise ValueError(f"V12 release receipt lineage mismatch: {key}")

    nodes = manifest.get("nodes") if isinstance(manifest.get("nodes"), list) else []
    node_ids = [str(node.get("node_id") or "") for node in nodes if isinstance(node, dict)]
    items = [
        item
        for node in nodes
        if isinstance(node, dict)
        for item in (node.get("items") if isinstance(node.get("items"), list) else [])
        if isinstance(item, dict)
    ]
    item_ids = [str(item.get("id") or "") for item in items]
    if not node_ids or any(not node_id for node_id in node_ids):
        raise ValueError("V12 release manifest has missing node identities")
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("V12 release manifest has duplicate node identities")
    if not item_ids or any(not item_id for item_id in item_ids):
        raise ValueError("V12 release manifest has missing question identities")
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("V12 release manifest has duplicate question identities")
    if int(receipt.get("node_count") or 0) != len(node_ids):
        raise ValueError("V12 release receipt lineage mismatch: node_count")
    if int(receipt.get("item_count") or 0) != len(item_ids):
        raise ValueError("V12 release receipt lineage mismatch: item_count")

    graph_snapshot = GraphRuntimeService(project_root=PROJECT_ROOT).graph_snapshot()
    graph_node_ids = set(graph_snapshot["nodes"])
    if manifest.get("graph_version") != graph_snapshot["graph_lineage"]:
        raise ValueError("V12 release manifest graph lineage is not current")
    full_coverage = (
        len(node_ids) == question_bank.V12_FULL_BANK_NODE_COUNT
        and len(item_ids) == question_bank.V12_FULL_BANK_ITEM_COUNT
        and set(node_ids) == graph_node_ids
        and len(graph_node_ids) == question_bank.V12_FULL_BANK_NODE_COUNT
    )
    receipt_lineage = {
        key: receipt.get(key)
        for key in (
            "schema_version",
            "runner_mode",
            "status",
            "manifest_id",
            "question_bank_version",
            "graph_version",
            "canonical_manifest_sha256",
            "node_count",
            "item_count",
        )
    }
    return {
        "manifest_file": manifest_file,
        "receipt_file": receipt_file,
        "manifest": manifest,
        "receipt": receipt,
        "manifest_sha256": manifest_sha256,
        "manifest_file_sha256": file_sha256(manifest_file),
        "receipt_sha256": file_sha256(receipt_file),
        "receipt_lineage": receipt_lineage,
        "node_count": len(node_ids),
        "item_count": len(item_ids),
        "full_coverage": full_coverage,
    }


def _active_ledger(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        select *
        from question_bank_version_ledger
        where status = 'active'
        order by activated_at desc, updated_at desc, id desc
        """
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("question bank release requires exactly one active ledger")
    return dict(rows[0])


def _assert_database_authority(
    conn: sqlite3.Connection,
    *,
    graph_version: str,
) -> dict[str, Any]:
    graph_row = conn.execute(
        "select value from system_meta where key = 'graph_ref'"
    ).fetchone()
    graph_ref = db.json_load(graph_row["value"], {}) if graph_row else {}
    if not isinstance(graph_ref, dict) or graph_ref.get("lineage") != graph_version:
        raise ValueError("database graph lineage does not match release manifest")
    return _active_ledger(conn)


def _backup_database(db_path: Path, backup_root: Path) -> dict[str, Any]:
    root = backup_root.expanduser().resolve()
    root_existed = root.exists()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root_existed:
        os.chmod(root, 0o700)
    root_mode = stat.S_IMODE(root.stat().st_mode)
    if root_mode & 0o022:
        raise ValueError("question bank backup root is group/world writable")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target = root / f"{db_path.stem}.pre-v12-question-bank.{stamp}.{uuid.uuid4().hex[:8]}.sqlite"
    target_fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(target_fd)
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as source_conn:
            with closing(sqlite3.connect(str(target))) as target_conn:
                source_conn.backup(target_conn)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    os.chmod(target, 0o600)
    target_mode = stat.S_IMODE(target.stat().st_mode)
    if target_mode != 0o600:
        raise ValueError("question bank backup permissions are not 0600")
    with closing(sqlite3.connect(str(target))) as verify_conn:
        integrity = str(verify_conn.execute("pragma integrity_check").fetchone()[0])
    if integrity != "ok":
        raise ValueError("question bank backup integrity check failed")
    return {
        "path": str(target),
        "sha256": file_sha256(target),
        "size_bytes": target.stat().st_size,
        "mode": format(target_mode, "04o"),
        "root_mode": format(root_mode, "04o"),
        "integrity_check": integrity,
    }


def _commit_release(conn: sqlite3.Connection) -> None:
    conn.commit()


def _expected_v12_question_authority(
    manifest: dict[str, Any],
) -> dict[str, dict[str, str]]:
    graph_path = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes_by_id = {
        str(node.get("id") or ""): node
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    expected: dict[str, dict[str, str]] = {}
    for node_entry in manifest.get("nodes") or []:
        node_id = str(node_entry.get("node_id") or "")
        node = nodes_by_id.get(node_id)
        if node is None:
            raise ValueError(f"V12 release manifest references unknown node: {node_id}")
        for external_item in node_entry.get("items") or []:
            converted = question_bank.external_v12_item_to_question_item(
                manifest,
                node,
                external_item,
            )
            question_id = str(converted.get("id") or "")
            if not question_id or question_id in expected:
                raise ValueError("V12 release manifest question authority is not unique")
            raw_json = db.json_dump(converted)
            expected[question_id] = {
                "raw_json": raw_json,
                "candidate_sha256": hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
            }
    return expected


def _attest_seeded_v12_exact(
    conn: sqlite3.Connection,
    *,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    expected = _expected_v12_question_authority(manifest)
    rows = conn.execute(
        "select id, raw_json from question_items where item_version = ? order by id",
        (question_bank.QUESTION_BANK_V12_VERSION,),
    ).fetchall()
    actual_by_id = {str(row["id"]): row for row in rows}
    expected_ids = set(expected)
    actual_ids = set(actual_by_id)
    missing = sorted(expected_ids - actual_ids)
    extra = sorted(actual_ids - expected_ids)
    if missing or extra:
        raise ValueError(
            "V12 release DB question set mismatch: "
            f"missing={missing[:5]} extra={extra[:5]}"
        )

    for question_id in sorted(expected):
        authority = expected[question_id]
        if actual_by_id[question_id]["raw_json"] != authority["raw_json"]:
            has_attempt = conn.execute(
                "select 1 from attempts where question_id = ? limit 1",
                (question_id,),
            ).fetchone()
            if has_attempt:
                raise ValueError(
                    f"immutable attempted v12 question conflict: {question_id}"
                )
            raise ValueError(f"V12 release DB raw_json mismatch: {question_id}")

        review_rows = conn.execute(
            """
            select candidate_sha256, review_status, active_eligible
            from question_review_records
            where question_id = ?
              and item_version = ?
              and source_type = 'graph_generated'
              and active_eligible = 1
            """,
            (question_id, question_bank.QUESTION_BANK_V12_VERSION),
        ).fetchall()
        if not review_rows:
            raise ValueError(
                f"V12 release DB candidate digest authority is missing: {question_id}"
            )
        if any(
            row["review_status"] != "approved"
            or row["candidate_sha256"] != authority["candidate_sha256"]
            for row in review_rows
        ):
            raise ValueError(
                f"V12 release DB candidate digest mismatch: {question_id}"
            )
    return {
        "question_count": len(actual_ids),
        "candidate_digest_count": len(expected_ids),
    }


def _assert_canonical_ledger_identity(
    ledger: sqlite3.Row | dict[str, Any],
    authority: dict[str, Any],
) -> None:
    values = dict(ledger)
    expected = {
        "question_bank_version": str(
            authority["manifest"]["question_bank_version"]
        ),
        "graph_version": str(authority["manifest"]["graph_version"]),
        "manifest_id": str(authority["manifest"]["manifest_id"]),
        "manifest_sha256": str(authority["manifest_sha256"]),
        "node_count": int(authority["node_count"]),
        "item_count": int(authority["item_count"]),
    }
    mismatches = [
        key
        for key, expected_value in expected.items()
        if values.get(key) != expected_value
    ]
    if mismatches:
        raise ValueError(
            "canonical question bank ledger identity conflict: "
            + ",".join(sorted(mismatches))
        )


def _verify_committed_release(
    *,
    database: Path,
    authority: dict[str, Any],
    ledger_id: str,
    expected_active_after: str,
    mode: str,
) -> dict[str, Any]:
    with closing(db.connect(database)) as conn:
        attestation = _attest_seeded_v12_exact(
            conn,
            manifest=authority["manifest"],
        )
        ledger = conn.execute(
            "select * from question_bank_version_ledger where id = ?",
            (ledger_id,),
        ).fetchone()
        if ledger is None:
            raise ValueError("committed question bank ledger is missing")
        expected_statuses = {"active"} if mode == "activate" else {"staged", "active"}
        if ledger["status"] not in expected_statuses:
            raise ValueError("committed question bank ledger status is not authoritative")
        active_after = str(_active_ledger(conn)["question_bank_version"])
        if active_after != expected_active_after:
            raise ValueError(
                "committed active question bank mismatch: "
                f"expected {expected_active_after}, got {active_after}"
            )
    return {
        "active_after": active_after,
        "ledger_status": str(ledger["status"]),
        "attestation": attestation,
    }


def _base_report(
    authority: dict[str, Any],
    *,
    mode: str,
    active_before: str,
) -> dict[str, Any]:
    return {
        "status": "dry_run" if mode == "dry_run" else "pending",
        "mode": mode,
        "dry_run": mode == "dry_run",
        "activation_ready": bool(authority["full_coverage"]),
        "manifest_id": authority["manifest"].get("manifest_id"),
        "question_bank_version": authority["manifest"].get("question_bank_version"),
        "graph_version": authority["manifest"].get("graph_version"),
        "manifest_sha256": authority["manifest_sha256"],
        "manifest_file_sha256": authority["manifest_file_sha256"],
        "receipt_sha256": authority["receipt_sha256"],
        "receipt_lineage": authority["receipt_lineage"],
        "node_count": authority["node_count"],
        "item_count": authority["item_count"],
        "active_before": active_before,
        "active_after": active_before,
        "backup_path": None,
        "backup_sha256": None,
        "backup_size_bytes": 0,
        "backup_mode": None,
        "backup_root_mode": None,
        "backup_integrity_check": None,
        "commit_state": "pre_commit",
        "active_after_verified_in_transaction": False,
    }


def release_question_bank(
    *,
    db_path: Path,
    manifest_path: Path,
    receipt_path: Path,
    backup_root: Path,
    mode: str = "dry_run",
) -> dict[str, Any]:
    if mode not in {"dry_run", "stage", "activate"}:
        raise ValueError("question bank release mode is invalid")
    database = _regular_file(db_path, "database")
    authority = _candidate_authority(manifest_path, receipt_path)
    if not authority["full_coverage"]:
        raise ValueError(
            "full v12 release requires sealed coverage: 56 nodes/1120 items"
        )

    with closing(db.connect(database)) as conn:
        active_before_row = _assert_database_authority(
            conn,
            graph_version=str(authority["manifest"].get("graph_version") or ""),
        )
    active_before = str(active_before_row["question_bank_version"])
    report = _base_report(authority, mode=mode, active_before=active_before)

    conn = db.connect(database)
    commit_state = "pre_commit"
    try:
        conn.execute("BEGIN IMMEDIATE")
        current_row = _assert_database_authority(
            conn,
            graph_version=str(authority["manifest"].get("graph_version") or ""),
        )
        if current_row["id"] != active_before_row["id"]:
            raise ValueError("active question bank changed after release preflight")
        existing = conn.execute(
            """
            select *
            from question_bank_version_ledger
            where question_bank_version = ?
              and status in ('staged','active')
            order by created_at desc, id desc
            limit 1
            """,
            (authority["manifest"]["question_bank_version"],),
        ).fetchone()
        seed_result: dict[str, Any]
        db_attestation: dict[str, Any]
        ledger: sqlite3.Row | dict[str, Any]
        if existing:
            _assert_canonical_ledger_identity(existing, authority)
            db_attestation = _attest_seeded_v12_exact(
                conn,
                manifest=authority["manifest"],
            )
            seed_result = {
                "questions_upserted": 0,
                "canonical_seed_skipped": True,
            }
            ledger = existing
        else:
            if mode != "dry_run":
                backup = _backup_database(database, backup_root)
                report.update({
                    "backup_path": backup["path"],
                    "backup_sha256": backup["sha256"],
                    "backup_size_bytes": backup["size_bytes"],
                    "backup_mode": backup["mode"],
                    "backup_root_mode": backup["root_mode"],
                    "backup_integrity_check": backup["integrity_check"],
                })
            seed_result = db.seed_external_question_bank_v12(
                conn,
                authority["manifest"],
                project_root=PROJECT_ROOT,
                runner_receipt=authority["receipt"],
                commit=False,
            )
            db_attestation = _attest_seeded_v12_exact(
                conn,
                manifest=authority["manifest"],
            )
            ledger = db.stage_question_bank_version(
                conn,
                question_bank_version=str(
                    authority["manifest"]["question_bank_version"]
                ),
                graph_version=str(authority["manifest"]["graph_version"]),
                manifest_id=str(authority["manifest"]["manifest_id"]),
                manifest_sha256=str(authority["manifest_sha256"]),
                node_count=int(authority["node_count"]),
                item_count=int(authority["item_count"]),
                commit=False,
            )

        canonical_noop = bool(
            existing
            and (
                mode == "stage"
                or (mode == "activate" and existing["status"] == "active")
            )
        )
        if canonical_noop:
            active_in_transaction = str(
                _active_ledger(conn)["question_bank_version"]
            )
            if active_in_transaction != active_before:
                raise ValueError("canonical no-op active ledger changed")
            report.update({
                "ledger_id": ledger["id"],
                "seed_result": seed_result,
                "db_attestation": db_attestation,
                "active_after": active_before,
                "active_after_verified_in_transaction": True,
                "commit_state": "not_committed",
                "status": (
                    "already_active"
                    if existing["status"] == "active"
                    else "already_staged"
                ),
            })
            conn.rollback()
            return report

        if existing and mode == "activate" and existing["status"] == "staged":
            backup = _backup_database(database, backup_root)
            report.update({
                "backup_path": backup["path"],
                "backup_sha256": backup["sha256"],
                "backup_size_bytes": backup["size_bytes"],
                "backup_mode": backup["mode"],
                "backup_root_mode": backup["root_mode"],
                "backup_integrity_check": backup["integrity_check"],
            })

        if mode in {"dry_run", "activate"} and ledger["status"] != "active":
            ledger = db.activate_question_bank_version(
                conn,
                question_bank_version=str(
                    authority["manifest"]["question_bank_version"]
                ),
                expected_current_version=active_before,
                reason="sealed full v12 question bank release",
                commit=False,
            )
        report.update({
            "ledger_id": ledger["id"],
            "seed_result": seed_result,
            "db_attestation": db_attestation,
        })
        active_in_transaction = str(_active_ledger(conn)["question_bank_version"])
        expected_active_after = (
            str(authority["manifest"]["question_bank_version"])
            if mode in {"dry_run", "activate"}
            else active_before
        )
        if active_in_transaction != expected_active_after:
            raise ValueError(
                "transactional active question bank mismatch: "
                f"expected {expected_active_after}, got {active_in_transaction}"
            )
        report["active_after_verified_in_transaction"] = True
        if mode == "dry_run":
            conn.rollback()
            report["status"] = "dry_run"
            report["commit_state"] = "not_committed"
            report["active_after"] = active_before
            return report

        if mode == "stage":
            success_status = "staged"
        else:
            success_status = (
                "already_active"
                if active_before == authority["manifest"]["question_bank_version"]
                else "activated"
            )
        report["active_after"] = expected_active_after
        try:
            _commit_release(conn)
        except Exception as exc:
            commit_state = "commit_unknown"
            report["commit_state"] = commit_state
            report["status"] = "commit_unknown"
            report["active_after"] = "unknown"
            report["error"] = str(exc)
            report["recovery"] = {
                "required": True,
                "action": "audit ledger and database against the verified backup before retry",
                "ledger_id": report.get("ledger_id"),
                "backup_path": report.get("backup_path"),
            }
            raise QuestionBankReleaseError(str(exc), report) from exc

        commit_state = "committed"
        report["commit_state"] = commit_state
        try:
            committed = _verify_committed_release(
                database=database,
                authority=authority,
                ledger_id=str(report["ledger_id"]),
                expected_active_after=expected_active_after,
                mode=mode,
            )
        except Exception as exc:
            report["status"] = "committed_unverified"
            report["error"] = str(exc)
            report["recovery"] = {
                "required": True,
                "action": "audit the committed ledger against the verified backup; do not retry blindly",
                "ledger_id": report.get("ledger_id"),
                "backup_path": report.get("backup_path"),
            }
            raise QuestionBankReleaseError(str(exc), report) from exc
        report["post_commit_verification"] = committed
        report["status"] = success_status
        return report
    except QuestionBankReleaseError:
        raise
    except Exception as exc:
        if commit_state == "pre_commit":
            try:
                conn.rollback()
                report["rollback"] = "completed"
            except Exception as rollback_exc:
                report["rollback"] = "failed"
                report["rollback_error"] = str(rollback_exc)
        try:
            with closing(db.connect(database)) as verify_conn:
                report["active_after"] = str(_active_ledger(verify_conn)["question_bank_version"])
        except Exception:
            report["active_after"] = "unknown"
        report["status"] = "error"
        report["commit_state"] = commit_state
        report["error"] = str(exc)
        raise QuestionBankReleaseError(str(exc), report) from exc
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run, stage, or activate a sealed full v12 question bank"
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--backup-root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stage", action="store_true")
    mode.add_argument("--activate", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = "activate" if args.activate else ("stage" if args.stage else "dry_run")
    try:
        result = release_question_bank(
            db_path=args.db,
            manifest_path=args.manifest,
            receipt_path=args.receipt,
            backup_root=args.backup_root,
            mode=mode,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
        return 0
    except QuestionBankReleaseError as exc:
        print(json.dumps(exc.report, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
        return 1
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "mode": mode,
            "dry_run": mode == "dry_run",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
