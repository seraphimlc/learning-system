from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from learning_system import db, question_bank
from tests.test_question_bank_v12 import (
    PROJECT_ROOT,
    _load_graph,
    _manifest,
    _runner_receipt_for_manifest,
)


SCRIPT_PATH = PROJECT_ROOT / "scripts/release_question_bank_v12.py"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_candidate(root: Path, manifest: dict, receipt: dict) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    receipt_path = root / "receipt.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    return manifest_path, receipt_path


def _database_state(path: Path) -> dict[str, object]:
    with closing(db.connect(path)) as conn:
        return {
            "active": db.get_active_question_bank_version(conn),
            "v12_questions": conn.execute(
                "select count(*) from question_items where item_version = ?",
                (question_bank.QUESTION_BANK_V12_VERSION,),
            ).fetchone()[0],
            "v12_reviews": conn.execute(
                "select count(*) from question_review_records where item_version = ?",
                (question_bank.QUESTION_BANK_V12_VERSION,),
            ).fetchone()[0],
            "ledger": [
                tuple(row)
                for row in conn.execute(
                    """
                    select question_bank_version, manifest_id, manifest_sha256,
                           node_count, item_count, status
                    from question_bank_version_ledger
                    order by question_bank_version, id
                    """
                ).fetchall()
            ],
        }


def _v12_review_lineage(path: Path) -> list[tuple[object, ...]]:
    with closing(db.connect(path)) as conn:
        return [
            tuple(row)
            for row in conn.execute(
                """
                select id, question_id, item_version, reviewed_at,
                       reviewer_run_id, candidate_sha256
                from question_review_records
                where item_version = ?
                order by question_id, id
                """,
                (question_bank.QUESTION_BANK_V12_VERSION,),
            ).fetchall()
        ]


class QuestionBankV12ReleaseCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._fixture_tmp = tempfile.TemporaryDirectory(prefix="qb12-release-full-")
        fixture_root = Path(cls._fixture_tmp.name)
        cls.full_manifest_path = fixture_root / "manifest.json"
        cls.full_receipt_path = fixture_root / "receipt.json"
        generator = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import json, sys
from pathlib import Path
from learning_system import question_bank
from tests.test_question_bank_v12 import _load_graph, _manifest, _runner_receipt_for_manifest
manifest = _manifest(tuple(node['id'] for node in _load_graph()['nodes']), provider_mode='live_model', status='draft_live_model')
receipt = _runner_receipt_for_manifest(manifest)
Path(sys.argv[1]).write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
Path(sys.argv[2]).write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
print(question_bank.v12_canonical_manifest_sha256(manifest))
""",
                str(cls.full_manifest_path),
                str(cls.full_receipt_path),
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        if generator.returncode != 0:
            raise RuntimeError(generator.stderr or generator.stdout)
        cls.full_manifest_sha256 = generator.stdout.strip()
        cls.full_manifest = json.loads(cls.full_manifest_path.read_text(encoding="utf-8"))
        cls.full_receipt = json.loads(cls.full_receipt_path.read_text(encoding="utf-8"))
        cls.seeded_database_path = fixture_root / "seeded.sqlite"
        with closing(db.connect(cls.seeded_database_path)) as conn:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            db.seed_external_question_bank_v12(
                conn,
                cls.full_manifest,
                project_root=PROJECT_ROOT,
                runner_receipt=cls.full_receipt,
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._fixture_tmp.cleanup()

    def _new_database(self, root: Path) -> Path:
        path = root / "learning.sqlite"
        with closing(db.connect(path)) as conn:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
        return path

    def _new_seeded_database(self, root: Path) -> Path:
        path = root / "learning.sqlite"
        shutil.copyfile(self.seeded_database_path, path)
        return path

    def _load_release_module(self):
        spec = importlib.util.spec_from_file_location("release_question_bank_v12", SCRIPT_PATH)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    def _run_cli(
        self,
        *,
        db_path: Path,
        manifest_path: Path,
        receipt_path: Path,
        backup_root: Path,
        mode: str = "",
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT_PATH),
            "--db",
            str(db_path),
            "--manifest",
            str(manifest_path),
            "--receipt",
            str(receipt_path),
            "--backup-root",
            str(backup_root),
            "--json",
        ]
        if mode:
            command.append(f"--{mode}")
        env = dict(os.environ)
        env["OPENAI_API_KEY"] = "must-not-appear-in-release-output"
        return subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
            env=env,
        )

    def test_default_dry_run_validates_full_contract_and_persists_nothing(self):
        with tempfile.TemporaryDirectory(prefix="qb12-release-dry-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            backup_root = root / "backups"
            before = _database_state(db_path)

            completed = self._run_cli(
                db_path=db_path,
                manifest_path=self.full_manifest_path,
                receipt_path=self.full_receipt_path,
                backup_root=backup_root,
            )

            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            payload = json.loads(completed.stdout)
            self.assertEqual("dry_run", payload["status"])
            self.assertTrue(payload["dry_run"])
            self.assertTrue(payload["activation_ready"])
            self.assertEqual(56, payload["node_count"])
            self.assertEqual(1120, payload["item_count"])
            self.assertEqual(
                self.full_manifest_sha256,
                payload["manifest_sha256"],
            )
            self.assertEqual(
                {
                    "schema_version",
                    "runner_mode",
                    "status",
                    "manifest_id",
                    "question_bank_version",
                    "graph_version",
                    "canonical_manifest_sha256",
                    "node_count",
                    "item_count",
                },
                set(payload["receipt_lineage"]),
            )
            self.assertEqual(before["active"], payload["active_before"])
            self.assertEqual(before["active"], payload["active_after"])
            self.assertIsNone(payload["backup_path"])
            self.assertEqual(before, _database_state(db_path))
            self.assertFalse(backup_root.exists())
            self.assertNotIn("must-not-appear-in-release-output", completed.stdout)

    def test_tampered_receipt_fails_closed(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        receipt = _runner_receipt_for_manifest(manifest)
        with tempfile.TemporaryDirectory(prefix="qb12-release-invalid-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            before = _database_state(db_path)
            tampered = json.loads(json.dumps(receipt))
            tampered["canonical_manifest_sha256"] = "0" * 64
            manifest_path, tampered_path = _write_candidate(root / "tampered", manifest, tampered)
            completed = self._run_cli(
                db_path=db_path,
                manifest_path=manifest_path,
                receipt_path=tampered_path,
                backup_root=root / "tampered-backups",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("manifest hash mismatch", json.loads(completed.stdout)["error"])
            self.assertEqual(before, _database_state(db_path))

    def test_tampered_manifest_fails_closed_before_backup_or_database_write(self):
        with tempfile.TemporaryDirectory(prefix="qb12-release-manifest-tamper-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            before = _database_state(db_path)
            tampered = json.loads(self.full_manifest_path.read_text(encoding="utf-8"))
            tampered["nodes"][0]["items"][0]["prompt"] += " tampered"
            manifest_path, receipt_path = _write_candidate(
                root / "tampered",
                tampered,
                self.full_receipt,
            )
            backup_root = root / "backups"

            completed = self._run_cli(
                db_path=db_path,
                manifest_path=manifest_path,
                receipt_path=receipt_path,
                backup_root=backup_root,
                mode="stage",
            )

            self.assertNotEqual(0, completed.returncode)
            self.assertIn("manifest hash mismatch", json.loads(completed.stdout)["error"])
            self.assertEqual(before, _database_state(db_path))
            self.assertFalse(backup_root.exists())

    def test_partial_manifest_is_rejected_in_every_mode_without_writes(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        receipt = _runner_receipt_for_manifest(manifest)
        with tempfile.TemporaryDirectory(prefix="qb12-release-partial-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            before = _database_state(db_path)
            valid_manifest_path, valid_receipt_path = _write_candidate(
                root / "partial",
                manifest,
                receipt,
            )
            for mode in ("", "stage", "activate"):
                with self.subTest(mode=mode or "dry_run"):
                    backup_root = root / f"{mode or 'dry-run'}-backups"
                    completed = self._run_cli(
                        db_path=db_path,
                        manifest_path=valid_manifest_path,
                        receipt_path=valid_receipt_path,
                        backup_root=backup_root,
                        mode=mode,
                    )
                    self.assertNotEqual(0, completed.returncode)
                    self.assertIn("56 nodes/1120 items", json.loads(completed.stdout)["error"])
                    self.assertEqual(before, _database_state(db_path))
                    self.assertFalse(backup_root.exists())

    def test_stage_creates_verified_backup_and_double_run_is_canonical(self):
        with tempfile.TemporaryDirectory(prefix="qb12-release-stage-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            backup_root = root / "backups"
            backup_root.mkdir(mode=0o710)
            backup_root_mode = stat.S_IMODE(backup_root.stat().st_mode)
            active_before = _database_state(db_path)["active"]

            first = self._run_cli(
                db_path=db_path,
                manifest_path=self.full_manifest_path,
                receipt_path=self.full_receipt_path,
                backup_root=backup_root,
                mode="stage",
            )
            second = self._run_cli(
                db_path=db_path,
                manifest_path=self.full_manifest_path,
                receipt_path=self.full_receipt_path,
                backup_root=backup_root,
                mode="stage",
            )

            self.assertEqual(0, first.returncode, first.stderr or first.stdout)
            self.assertEqual(0, second.returncode, second.stderr or second.stdout)
            first_payload = json.loads(first.stdout)
            second_payload = json.loads(second.stdout)
            self.assertEqual("staged", first_payload["status"])
            self.assertEqual("already_staged", second_payload["status"])
            self.assertEqual(first_payload["ledger_id"], second_payload["ledger_id"])
            self.assertEqual(active_before, first_payload["active_after"])
            self.assertEqual(active_before, second_payload["active_after"])
            self.assertEqual(1120, _database_state(db_path)["v12_questions"])
            backups = sorted(backup_root.glob("*.sqlite"))
            self.assertEqual(1, len(backups))
            self.assertEqual(backup_root_mode, stat.S_IMODE(backup_root.stat().st_mode))
            backup_path = Path(first_payload["backup_path"])
            self.assertTrue(backup_path.is_file())
            self.assertEqual("0710", first_payload["backup_root_mode"])
            self.assertEqual(0o600, stat.S_IMODE(backup_path.stat().st_mode))
            self.assertEqual(_file_sha256(backup_path), first_payload["backup_sha256"])
            with closing(sqlite3.connect(backup_path)) as backup_conn:
                self.assertEqual("ok", backup_conn.execute("pragma integrity_check").fetchone()[0])
            self.assertIsNone(second_payload["backup_path"])
            self.assertIsNone(second_payload["backup_sha256"])

    def test_full_activate_and_repeat_return_one_canonical_active_ledger(self):
        with tempfile.TemporaryDirectory(prefix="qb12-release-activate-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            backup_root = root / "backups"
            active_before = _database_state(db_path)["active"]

            first = self._run_cli(
                db_path=db_path,
                manifest_path=self.full_manifest_path,
                receipt_path=self.full_receipt_path,
                backup_root=backup_root,
                mode="activate",
            )
            second = self._run_cli(
                db_path=db_path,
                manifest_path=self.full_manifest_path,
                receipt_path=self.full_receipt_path,
                backup_root=backup_root,
                mode="activate",
            )

            self.assertEqual(0, first.returncode, first.stderr or first.stdout)
            self.assertEqual(0, second.returncode, second.stderr or second.stdout)
            first_payload = json.loads(first.stdout)
            second_payload = json.loads(second.stdout)
            self.assertEqual("activated", first_payload["status"])
            self.assertEqual("already_active", second_payload["status"])
            self.assertEqual(active_before, first_payload["active_before"])
            self.assertEqual(question_bank.QUESTION_BANK_V12_VERSION, first_payload["active_after"])
            self.assertEqual(first_payload["ledger_id"], second_payload["ledger_id"])
            self.assertIsNone(second_payload["backup_path"])
            state = _database_state(db_path)
            self.assertEqual(question_bank.QUESTION_BANK_V12_VERSION, state["active"])
            self.assertEqual(1120, state["v12_questions"])
            self.assertEqual(
                1,
                sum(
                    1
                    for version, _manifest_id, _sha, _nodes, _items, status in state["ledger"]
                    if version == question_bank.QUESTION_BANK_V12_VERSION and status == "active"
                ),
            )

    def test_unsealed_full_receipt_cannot_activate_and_preserves_old_active(self):
        with tempfile.TemporaryDirectory(prefix="qb12-release-unsealed-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            before = _database_state(db_path)
            unsealed = json.loads(self.full_receipt_path.read_text(encoding="utf-8"))
            unsealed["status"] = "running"
            candidate_root = root / "candidate"
            candidate_root.mkdir(parents=True)
            manifest_path = candidate_root / "manifest.json"
            receipt_path = candidate_root / "receipt.json"
            shutil.copyfile(self.full_manifest_path, manifest_path)
            receipt_path.write_text(json.dumps(unsealed, ensure_ascii=False), encoding="utf-8")
            del unsealed
            with self.assertRaisesRegex(ValueError, "live completed status"):
                spec = importlib.util.spec_from_file_location("release_question_bank_v12", SCRIPT_PATH)
                self.assertIsNotNone(spec)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]
                module.release_question_bank(
                    db_path=db_path,
                    manifest_path=manifest_path,
                    receipt_path=receipt_path,
                    backup_root=root / "backups",
                    mode="activate",
                )
            self.assertEqual(before, _database_state(db_path))

    def test_failure_after_seed_rolls_back_every_write_and_preserves_old_active(self):
        module = self._load_release_module()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        receipt = _runner_receipt_for_manifest(manifest)
        with tempfile.TemporaryDirectory(prefix="qb12-release-rollback-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            manifest_path, receipt_path = _write_candidate(root / "candidate", manifest, receipt)
            backup_root = root / "backups"
            before = _database_state(db_path)
            authority = module._candidate_authority(manifest_path, receipt_path)
            authority["full_coverage"] = True

            with mock.patch.object(
                module,
                "_candidate_authority",
                return_value=authority,
            ), mock.patch.object(
                module.db,
                "stage_question_bank_version",
                side_effect=RuntimeError("injected stage failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected stage failure"):
                    module.release_question_bank(
                        db_path=db_path,
                        manifest_path=manifest_path,
                        receipt_path=receipt_path,
                        backup_root=backup_root,
                        mode="stage",
                    )

            self.assertEqual(before, _database_state(db_path))
            backups = list(backup_root.glob("*.sqlite"))
            self.assertEqual(1, len(backups))
            with closing(sqlite3.connect(backups[0])) as backup_conn:
                self.assertEqual("ok", backup_conn.execute("pragma integrity_check").fetchone()[0])

    def test_canonical_retry_skips_seed_and_stage_and_preserves_review_lineage(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-canonical-retry-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            backup_root = root / "backups"
            staged = module.release_question_bank(
                db_path=db_path,
                manifest_path=self.full_manifest_path,
                receipt_path=self.full_receipt_path,
                backup_root=backup_root,
                mode="stage",
            )
            staged_lineage = _v12_review_lineage(db_path)
            self.assertEqual(1120, len(staged_lineage))
            staged_state = _database_state(db_path)
            staged_backup_count = len(list(backup_root.glob("*.sqlite")))

            with mock.patch.object(
                module.db,
                "seed_external_question_bank_v12",
                side_effect=AssertionError("canonical retry called seeder"),
            ) as seed_spy, mock.patch.object(
                module.db,
                "stage_question_bank_version",
                side_effect=AssertionError("canonical retry called stager"),
            ) as stage_spy:
                repeated_stage = module.release_question_bank(
                    db_path=db_path,
                    manifest_path=self.full_manifest_path,
                    receipt_path=self.full_receipt_path,
                    backup_root=backup_root,
                    mode="stage",
                )
            self.assertEqual("already_staged", repeated_stage["status"])
            self.assertIsNone(repeated_stage["backup_path"])
            seed_spy.assert_not_called()
            stage_spy.assert_not_called()
            self.assertEqual(staged_lineage, _v12_review_lineage(db_path))
            self.assertEqual(staged_state, _database_state(db_path))
            self.assertEqual(
                staged_backup_count,
                len(list(backup_root.glob("*.sqlite"))),
            )

            with mock.patch.object(
                module.db,
                "seed_external_question_bank_v12",
                side_effect=AssertionError("staged activation called seeder"),
            ) as seed_spy, mock.patch.object(
                module.db,
                "stage_question_bank_version",
                side_effect=AssertionError("staged activation called stager"),
            ) as stage_spy:
                activated = module.release_question_bank(
                    db_path=db_path,
                    manifest_path=self.full_manifest_path,
                    receipt_path=self.full_receipt_path,
                    backup_root=backup_root,
                    mode="activate",
                )
            self.assertEqual("activated", activated["status"])
            seed_spy.assert_not_called()
            stage_spy.assert_not_called()
            self.assertEqual(staged_lineage, _v12_review_lineage(db_path))
            activated_state = _database_state(db_path)
            self.assertEqual(question_bank.QUESTION_BANK_V12_VERSION, activated_state["active"])
            self.assertEqual(
                staged_backup_count + 1,
                len(list(backup_root.glob("*.sqlite"))),
            )
            active_backup_count = len(list(backup_root.glob("*.sqlite")))

            with mock.patch.object(
                module.db,
                "seed_external_question_bank_v12",
                side_effect=AssertionError("active retry called seeder"),
            ) as seed_spy, mock.patch.object(
                module.db,
                "stage_question_bank_version",
                side_effect=AssertionError("active retry called stager"),
            ) as stage_spy, mock.patch.object(
                module.db,
                "activate_question_bank_version",
                side_effect=AssertionError("active retry called activator"),
            ) as activate_spy:
                repeated_active = module.release_question_bank(
                    db_path=db_path,
                    manifest_path=self.full_manifest_path,
                    receipt_path=self.full_receipt_path,
                    backup_root=backup_root,
                    mode="activate",
                )
            self.assertEqual("already_active", repeated_active["status"])
            self.assertIsNone(repeated_active["backup_path"])
            seed_spy.assert_not_called()
            stage_spy.assert_not_called()
            activate_spy.assert_not_called()
            self.assertEqual(staged_lineage, _v12_review_lineage(db_path))
            self.assertEqual(activated_state, _database_state(db_path))
            self.assertEqual(
                active_backup_count,
                len(list(backup_root.glob("*.sqlite"))),
            )

            with closing(db.connect(db_path)) as conn:
                question_id = conn.execute(
                    "select id from question_items where item_version = ? order by id limit 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()[0]
                conn.execute("update question_items set raw_json = '{}' where id = ?", (question_id,))
                conn.commit()
            with mock.patch.object(
                module.db,
                "seed_external_question_bank_v12",
                side_effect=AssertionError("attestation failure called seeder"),
            ) as seed_spy:
                with self.assertRaisesRegex(
                    module.QuestionBankReleaseError,
                    "raw_json mismatch",
                ):
                    module.release_question_bank(
                        db_path=db_path,
                        manifest_path=self.full_manifest_path,
                        receipt_path=self.full_receipt_path,
                        backup_root=backup_root,
                        mode="stage",
                    )
            seed_spy.assert_not_called()
            self.assertEqual(staged_lineage, _v12_review_lineage(db_path))

    def test_post_commit_verification_failure_reports_committed_unverified(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-postcommit-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            before = _database_state(db_path)
            with mock.patch.object(
                module,
                "_verify_committed_release",
                side_effect=RuntimeError("injected post-commit verification failure"),
                create=True,
            ):
                with self.assertRaises(module.QuestionBankReleaseError) as raised:
                    module.release_question_bank(
                        db_path=db_path,
                        manifest_path=self.full_manifest_path,
                        receipt_path=self.full_receipt_path,
                        backup_root=root / "backups",
                        mode="stage",
                    )

            report = raised.exception.report
            self.assertEqual("committed_unverified", report["status"])
            self.assertEqual("committed", report["commit_state"])
            self.assertTrue(report["ledger_id"])
            self.assertTrue(Path(report["backup_path"]).is_file())
            self.assertTrue(report["recovery"]["required"])
            after = _database_state(db_path)
            self.assertEqual(before["active"], after["active"])
            self.assertEqual(1120, after["v12_questions"])
            self.assertTrue(
                any(
                    version == question_bank.QUESTION_BANK_V12_VERSION and status == "staged"
                    for version, _manifest_id, _sha, _nodes, _items, status in after["ledger"]
                )
            )

    def test_commit_exception_reports_commit_unknown_without_claiming_rollback(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-commit-unknown-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            with mock.patch.object(
                module,
                "_commit_release",
                side_effect=sqlite3.OperationalError("injected commit result unknown"),
                create=True,
            ):
                with self.assertRaises(module.QuestionBankReleaseError) as raised:
                    module.release_question_bank(
                        db_path=db_path,
                        manifest_path=self.full_manifest_path,
                        receipt_path=self.full_receipt_path,
                        backup_root=root / "backups",
                        mode="stage",
                    )

            report = raised.exception.report
            self.assertEqual("commit_unknown", report["status"])
            self.assertEqual("commit_unknown", report["commit_state"])
            self.assertEqual("unknown", report["active_after"])
            self.assertNotIn("rollback", report)
            self.assertTrue(report["recovery"]["required"])

    def test_backup_rejects_group_or_world_writable_root_before_file_creation(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-backup-root-") as tmp:
            root = Path(tmp)
            db_path = self._new_database(root)
            for unsafe_mode in (0o777, 0o730):
                with self.subTest(mode=format(unsafe_mode, "04o")):
                    backup_root = root / f"backups-{unsafe_mode:o}"
                    backup_root.mkdir()
                    os.chmod(backup_root, unsafe_mode)
                    with self.assertRaisesRegex(ValueError, "group/world writable"):
                        module._backup_database(db_path, backup_root)
                    self.assertEqual(
                        unsafe_mode,
                        stat.S_IMODE(backup_root.stat().st_mode),
                    )
                    self.assertEqual([], list(backup_root.iterdir()))
            new_root = root / "new-secure-backups"
            backup = module._backup_database(db_path, new_root)
            self.assertEqual(0o700, stat.S_IMODE(new_root.stat().st_mode))
            self.assertEqual("0700", backup["root_mode"])
            self.assertEqual(0o600, stat.S_IMODE(Path(backup["path"]).stat().st_mode))

    def test_release_input_authority_rejects_leaf_symlinks(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-symlink-") as tmp:
            root = Path(tmp)
            target = root / "authority.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "authority-link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "unsafe or missing"):
                module._regular_file(link, "manifest")
            self.assertEqual(target.resolve(), module._regular_file(target, "manifest"))

    def test_transaction_attestation_rejects_extra_v12_question(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-extra-") as tmp:
            root = Path(tmp)
            db_path = self._new_seeded_database(root)
            with closing(db.connect(db_path)) as conn:
                row = conn.execute(
                    "select * from question_items where item_version = ? order by id limit 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()
                values = dict(row)
                values["id"] = "V12-EXTRA-QUESTION"
                raw = db.json_load(values["raw_json"], {})
                raw["id"] = values["id"]
                values["raw_json"] = db.json_dump(raw)
                columns = list(values)
                conn.execute(
                    f"insert into question_items({','.join(columns)}) values ({','.join('?' for _ in columns)})",
                    tuple(values[column] for column in columns),
                )
                conn.commit()
            before = _database_state(db_path)

            with mock.patch.object(
                module.db,
                "seed_external_question_bank_v12",
                return_value={"questions_upserted": 1120},
            ):
                with self.assertRaisesRegex(module.QuestionBankReleaseError, "extra"):
                    module.release_question_bank(
                        db_path=db_path,
                        manifest_path=self.full_manifest_path,
                        receipt_path=self.full_receipt_path,
                        backup_root=root / "backups",
                        mode="stage",
                    )
            self.assertEqual(before, _database_state(db_path))

    def test_transaction_attestation_rejects_missing_v12_question(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-missing-") as tmp:
            root = Path(tmp)
            db_path = self._new_seeded_database(root)
            with closing(db.connect(db_path)) as conn:
                question_id = conn.execute(
                    "select id from question_items where item_version = ? order by id limit 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()[0]
                conn.execute("delete from question_review_records where question_id = ?", (question_id,))
                conn.execute("delete from question_items where id = ?", (question_id,))
                conn.commit()
            before = _database_state(db_path)

            with mock.patch.object(
                module.db,
                "seed_external_question_bank_v12",
                return_value={"questions_upserted": 1120},
            ):
                with self.assertRaisesRegex(module.QuestionBankReleaseError, "missing"):
                    module.release_question_bank(
                        db_path=db_path,
                        manifest_path=self.full_manifest_path,
                        receipt_path=self.full_receipt_path,
                        backup_root=root / "backups",
                        mode="stage",
                    )
            self.assertEqual(before, _database_state(db_path))

    def test_transaction_attestation_rejects_raw_json_mismatch(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-raw-") as tmp:
            root = Path(tmp)
            db_path = self._new_seeded_database(root)
            with closing(db.connect(db_path)) as conn:
                question_id = conn.execute(
                    "select id from question_items where item_version = ? order by id limit 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()[0]
                conn.execute("update question_items set raw_json = '{}' where id = ?", (question_id,))
                conn.commit()
            before = _database_state(db_path)

            with mock.patch.object(
                module.db,
                "seed_external_question_bank_v12",
                return_value={"questions_upserted": 1120},
            ):
                with self.assertRaisesRegex(module.QuestionBankReleaseError, "raw_json mismatch"):
                    module.release_question_bank(
                        db_path=db_path,
                        manifest_path=self.full_manifest_path,
                        receipt_path=self.full_receipt_path,
                        backup_root=root / "backups",
                        mode="stage",
                    )
            self.assertEqual(before, _database_state(db_path))

    def test_transaction_attestation_rejects_candidate_digest_mismatch(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-candidate-digest-") as tmp:
            root = Path(tmp)
            db_path = self._new_seeded_database(root)
            with closing(db.connect(db_path)) as conn:
                question_id = conn.execute(
                    "select id from question_items where item_version = ? order by id limit 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()[0]
                conn.execute(
                    "update question_review_records set candidate_sha256 = ? where question_id = ? and item_version = ?",
                    ("0" * 64, question_id, question_bank.QUESTION_BANK_V12_VERSION),
                )
                conn.commit()
            before = _database_state(db_path)

            with mock.patch.object(
                module.db,
                "seed_external_question_bank_v12",
                return_value={"questions_upserted": 1120},
            ):
                with self.assertRaisesRegex(module.QuestionBankReleaseError, "candidate digest mismatch"):
                    module.release_question_bank(
                        db_path=db_path,
                        manifest_path=self.full_manifest_path,
                        receipt_path=self.full_receipt_path,
                        backup_root=root / "backups",
                        mode="stage",
                    )
            self.assertEqual(before, _database_state(db_path))

    def test_attempted_immutable_question_conflict_rolls_back(self):
        module = self._load_release_module()
        with tempfile.TemporaryDirectory(prefix="qb12-release-attempt-conflict-") as tmp:
            root = Path(tmp)
            db_path = self._new_seeded_database(root)
            with closing(db.connect(db_path)) as conn:
                row = conn.execute(
                    "select id, node_id from question_items where item_version = ? order by id limit 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()
                conn.execute(
                    "insert into learning_sessions(id, title, mode, created_at) values ('S-IMMUTABLE', 'release test', 'test', ?)",
                    (db.now_iso(),),
                )
                conn.execute(
                    """
                    insert into attempts(
                      id, session_id, question_id, node_id, result, grading_status,
                      score_points, max_points, error_tags_json, answer_raw,
                      parent_note, question_bank_version, created_at
                    ) values ('A-IMMUTABLE', 'S-IMMUTABLE', ?, ?, 'correct', 'graded',
                              1, 1, '[]', 'answer', '', ?, ?)
                    """,
                    (row["id"], row["node_id"], question_bank.QUESTION_BANK_V12_VERSION, db.now_iso()),
                )
                conn.execute("update question_items set raw_json = '{}' where id = ?", (row["id"],))
                conn.commit()
            before = _database_state(db_path)

            with self.assertRaisesRegex(
                module.QuestionBankReleaseError,
                "immutable attempted v12 question conflict",
            ):
                module.release_question_bank(
                    db_path=db_path,
                    manifest_path=self.full_manifest_path,
                    receipt_path=self.full_receipt_path,
                    backup_root=root / "backups",
                    mode="stage",
                )
            self.assertEqual(before, _database_state(db_path))


if __name__ == "__main__":
    unittest.main()
