"""Persistence adapters for validated question-production artifacts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Persistence(Protocol):
    artifact_type: str

    def persist(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        stage_id: str,
        output: list[dict[str, Any]],
        parent_artifact_ids: list[str],
        input_digest: str,
        output_digest: str,
        artifact_attempt: int,
    ) -> None: ...


class SQLiteArtifactPersistence:
    artifact_type: str

    def persist(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        stage_id: str,
        output: list[dict[str, Any]],
        parent_artifact_ids: list[str],
        input_digest: str,
        output_digest: str,
        artifact_attempt: int,
    ) -> None:
        for item in output:
            key = str(item.get(f"{self.artifact_type}_id") or "").strip()
            if not key:
                raise ValueError(f"{self.artifact_type} persistence requires its entity id")
            conn.execute(
                """
                insert into production_artifacts(
                  id,run_id,stage_id,artifact_type,logical_key,
                  parent_artifact_ids_json,payload_json,input_digest_sha256,
                  output_digest_sha256,artifact_attempt,created_at
                ) values (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"PA-{uuid.uuid4().hex[:12]}",
                    run_id,
                    stage_id,
                    self.artifact_type,
                    key,
                    json.dumps(parent_artifact_ids, ensure_ascii=False),
                    json.dumps(item, ensure_ascii=False, sort_keys=True),
                    input_digest,
                    output_digest,
                    artifact_attempt,
                    _now(),
                ),
            )


class QFPersistence(SQLiteArtifactPersistence):
    artifact_type = "qf"


class SlotPersistence(SQLiteArtifactPersistence):
    artifact_type = "slot"


class BriefPersistence(SQLiteArtifactPersistence):
    artifact_type = "brief"


class CandidatePersistence(SQLiteArtifactPersistence):
    artifact_type = "candidate"


def default_persistences() -> dict[str, Persistence]:
    return {
        "qf_design": QFPersistence(),
        "slot_design": SlotPersistence(),
        "brief_generation": BriefPersistence(),
        "candidate_generation": CandidatePersistence(),
    }
