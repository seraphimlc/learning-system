from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from . import db, question_bank


GATE_VERSION = "2026-07-10.v3.evidence-gate.skeleton"


@dataclass(frozen=True)
class EvidencePredicateResult:
    usable: bool
    projection_status: str
    failed_fields: tuple[str, ...]
    report_label: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "usable": self.usable,
            "projection_status": self.projection_status,
            "failed_fields": list(self.failed_fields),
            "report_label": self.report_label,
        }


@dataclass(frozen=True)
class EvidenceValidationResult:
    validation_id: str | None
    gate_status: str
    predicate: EvidencePredicateResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "gate_status": self.gate_status,
            "predicate": self.predicate.as_dict(),
        }


class EvidenceUsePredicate:
    """v3 fail-closed predicate shared by evaluation, planner, and reports."""

    @staticmethod
    def evaluate(
        attempt: dict[str, Any],
        *,
        gate_status: str | None = None,
        current_graph_version: str,
        current_question_bank_version: str = question_bank.QUESTION_BANK_VERSION,
        provider_mode: str = "not_configured",
        lineage: dict[str, Any] | None = None,
    ) -> EvidencePredicateResult:
        failed: list[str] = []
        lineage_provided = lineage is not None
        lineage = lineage or {}
        if attempt.get("evidence_status") != "active":
            failed.append("evidence_status")
        if attempt.get("grading_status") != "graded":
            failed.append("grading_status")
        if attempt.get("analysis_status") != "valid":
            failed.append("analysis_status")
        accepted_assessment = lineage.get("accepted_assessment_lineage") is True
        if (
            attempt.get("analysis_status") == "valid"
            and not accepted_assessment
            and not db.is_valid_answer_analysis(attempt.get("answer_analysis") or {})
        ):
            failed.append("answer_analysis")
        if lineage.get("accepted_assessment_required") and not accepted_assessment:
            failed.append("accepted_assessment_lineage")
        if lineage.get("answer_analysis_agent_run_required") and lineage.get("answer_analysis_agent_run_lineage") is False:
            failed.append("answer_analysis_agent_run_lineage")
        if provider_mode in {"mock", "mock_only", "not_configured"}:
            failed.append("provider_mode")
        if not attempt.get("flow_step_id"):
            failed.append("flow_step_id")
        if attempt.get("flow_step_id") and (not lineage_provided or lineage.get("flow_step_exists") is False):
            failed.append("flow_step_lineage")
        if attempt.get("flow_step_id") and (not lineage_provided or lineage.get("step_question_matches_attempt") is False):
            failed.append("step_question_lineage")
        if attempt.get("flow_step_id") and (not lineage_provided or lineage.get("step_review_record_matches_attempt") is False):
            failed.append("step_review_record_lineage")
        if attempt.get("flow_step_id") and (not lineage_provided or lineage.get("step_graph_version_matches_attempt") is False):
            failed.append("step_graph_version_lineage")
        if attempt.get("flow_step_id") and (not lineage_provided or lineage.get("step_question_bank_version_matches_attempt") is False):
            failed.append("step_question_bank_version_lineage")
        if attempt.get("flow_step_id") and (not lineage_provided or lineage.get("step_attempt_matches_attempt") is False):
            failed.append("step_attempt_lineage")
        if attempt.get("flow_step_id") and (not lineage_provided or lineage.get("step_question_item_version_matches_question") is False):
            failed.append("step_question_item_version_lineage")
        if not attempt.get("node_id"):
            failed.append("node_id")
        if attempt.get("node_id") and (not lineage_provided or lineage.get("node_matches_step") is False):
            failed.append("node_lineage")
        if not attempt.get("question_id"):
            failed.append("question_id")
        if attempt.get("question_id") and (not lineage_provided or lineage.get("question_exists") is False):
            failed.append("question_lineage")
        if attempt.get("question_id") and (not lineage_provided or lineage.get("question_active_use") is False):
            failed.append("question_active_use_lineage")
        if not attempt.get("review_record_id"):
            failed.append("review_record_id")
        if attempt.get("review_record_id") and (not lineage_provided or lineage.get("review_record_active") is False):
            failed.append("review_record_lineage")
        if not attempt.get("graph_version") or attempt.get("graph_version") != current_graph_version:
            failed.append("graph_version")
        if not attempt.get("question_bank_version") or attempt.get("question_bank_version") != current_question_bank_version:
            failed.append("question_bank_version")
        if gate_status != "passed":
            failed.append("gate_status")

        report_label = _report_label_for_failed_fields(failed, provider_mode=provider_mode)
        return EvidencePredicateResult(
            usable=not failed,
            projection_status="usable" if not failed else ("pending" if "grading_status" in failed or "analysis_status" in failed else "rejected"),
            failed_fields=tuple(failed),
            report_label=report_label,
        )


class EvidenceGate:
    """Records validation rows; it does not reinterpret weak evidence as mastery."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        current_graph_version: str,
        current_question_bank_version: str = question_bank.QUESTION_BANK_VERSION,
    ) -> None:
        self.conn = conn
        self.current_graph_version = current_graph_version
        self.current_question_bank_version = current_question_bank_version

    def validate_attempt(
        self,
        attempt_id: str,
        *,
        analysis_version: int | None = None,
        provider_mode: str = "not_configured",
        answer_analysis_agent_run_id: str | None = None,
        assessment_id: str | None = None,
        assessment_version: int | None = None,
        assessment_digest_sha256: str | None = None,
        commit: bool = True,
    ) -> EvidenceValidationResult:
        row = self.conn.execute("select * from attempts where id = ?", (attempt_id,)).fetchone()
        if not row:
            predicate = EvidencePredicateResult(
                usable=False,
                projection_status="blocked",
                failed_fields=("attempt_id",),
                report_label="missing_lineage",
            )
            return EvidenceValidationResult(validation_id=None, gate_status="blocked", predicate=predicate)

        attempt = db.attempt_row_to_dict(row)
        attempt_analysis_version = int(analysis_version if analysis_version is not None else attempt.get("analysis_version") or 0)
        lineage = self._lineage_for_attempt(attempt)
        lineage.update(
            self._assessment_lineage(
                attempt=attempt,
                assessment_id=assessment_id,
                assessment_version=assessment_version,
                assessment_digest_sha256=assessment_digest_sha256,
            )
        )
        effective_provider_mode = provider_mode
        if attempt.get("analysis_status") == "valid":
            run_lineage = self._answer_analysis_run_lineage(
                answer_analysis_agent_run_id=answer_analysis_agent_run_id,
                attempt=attempt,
                requested_provider_mode=provider_mode,
            )
            lineage.update(run_lineage)
            effective_provider_mode = str(run_lineage.get("effective_provider_mode") or provider_mode)
        preliminary = EvidenceUsePredicate.evaluate(
            attempt,
            gate_status="passed",
            current_graph_version=self.current_graph_version,
            current_question_bank_version=self.current_question_bank_version,
            provider_mode=effective_provider_mode,
            lineage=lineage,
        )
        gate_status = "passed" if preliminary.usable else ("pending" if preliminary.report_label == "pending" else "rejected")
        predicate = EvidenceUsePredicate.evaluate(
            attempt,
            gate_status=gate_status,
            current_graph_version=self.current_graph_version,
            current_question_bank_version=self.current_question_bank_version,
            provider_mode=effective_provider_mode,
            lineage=lineage,
        )
        validation_id = f"EV-{uuid.uuid4().hex[:12]}"
        now = db.now_iso()
        self.conn.execute(
            """
            insert or ignore into evidence_validations(
              id, attempt_id, attempt_version, analysis_version, graph_version,
              node_id, question_id, question_bank_version, gate_version,
              gate_status, failed_fields_json, predicate_result_json,
              answer_analysis_agent_run_id, provider_mode, assessment_id,
              assessment_version, assessment_digest_sha256, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validation_id,
                attempt_id,
                int(attempt.get("attempt_version") or 1),
                attempt_analysis_version,
                str(attempt.get("graph_version") or ""),
                str(attempt.get("node_id") or ""),
                str(attempt.get("question_id") or ""),
                str(attempt.get("question_bank_version") or ""),
                GATE_VERSION,
                gate_status,
                db.json_dump(predicate.failed_fields),
                db.json_dump(predicate.as_dict()),
                answer_analysis_agent_run_id,
                effective_provider_mode,
                assessment_id,
                assessment_version,
                assessment_digest_sha256,
                now,
                now,
            ),
        )
        if commit:
            self.conn.commit()
        canonical = self.conn.execute(
            """
            select id, gate_status, predicate_result_json, provider_mode,
                   answer_analysis_agent_run_id, assessment_id,
                   assessment_version, assessment_digest_sha256
            from evidence_validations
            where attempt_id = ?
              and attempt_version = ?
              and analysis_version = ?
              and gate_version = ?
            order by created_at desc, id desc
            limit 1
            """,
            (
                attempt_id,
                int(attempt.get("attempt_version") or 1),
                attempt_analysis_version,
                GATE_VERSION,
            ),
        ).fetchone()
        if canonical:
            canonical_payload_raw = db.json_load(canonical["predicate_result_json"], {})
            canonical_differs = (
                canonical["gate_status"] != gate_status
                or str(canonical["provider_mode"] or "") != effective_provider_mode
                or str(canonical["answer_analysis_agent_run_id"] or "") != str(answer_analysis_agent_run_id or "")
                or str(canonical["assessment_id"] or "") != str(assessment_id or "")
                or canonical["assessment_version"] != assessment_version
                or str(canonical["assessment_digest_sha256"] or "") != str(assessment_digest_sha256 or "")
                or canonical_payload_raw != predicate.as_dict()
            )
            if canonical_differs:
                self.conn.execute(
                    """
                    update evidence_validations
                    set gate_status = ?,
                        failed_fields_json = ?,
                        predicate_result_json = ?,
                        answer_analysis_agent_run_id = ?,
                        provider_mode = ?,
                        assessment_id = ?,
                        assessment_version = ?,
                        assessment_digest_sha256 = ?,
                        updated_at = ?
                    where id = ?
                    """,
                    (
                        gate_status,
                        db.json_dump(predicate.failed_fields),
                        db.json_dump(predicate.as_dict()),
                        answer_analysis_agent_run_id,
                        effective_provider_mode,
                        assessment_id,
                        assessment_version,
                        assessment_digest_sha256,
                        db.now_iso(),
                        canonical["id"],
                    ),
                )
                if commit:
                    self.conn.commit()
                return EvidenceValidationResult(
                    validation_id=canonical["id"],
                    gate_status=gate_status,
                    predicate=predicate,
                )
            canonical_payload = canonical_payload_raw or predicate.as_dict()
            canonical_predicate = EvidencePredicateResult(
                usable=bool(canonical_payload.get("usable")),
                projection_status=str(canonical_payload.get("projection_status") or ""),
                failed_fields=tuple(str(item) for item in canonical_payload.get("failed_fields") or []),
                report_label=str(canonical_payload.get("report_label") or canonical["gate_status"]),
            )
            return EvidenceValidationResult(
                validation_id=canonical["id"],
                gate_status=canonical["gate_status"],
                predicate=canonical_predicate,
            )
        return EvidenceValidationResult(validation_id=validation_id, gate_status=gate_status, predicate=predicate)

    def _assessment_lineage(
        self,
        *,
        attempt: dict[str, Any],
        assessment_id: str | None,
        assessment_version: int | None,
        assessment_digest_sha256: str | None,
    ) -> dict[str, Any]:
        required = any(
            value is not None
            for value in (
                assessment_id,
                assessment_version,
                assessment_digest_sha256,
            )
        )
        if not required:
            return {"accepted_assessment_required": False}
        if not (
            isinstance(assessment_id, str)
            and assessment_id
            and isinstance(assessment_version, int)
            and not isinstance(assessment_version, bool)
            and assessment_version > 0
            and isinstance(assessment_digest_sha256, str)
            and assessment_digest_sha256
        ):
            return {
                "accepted_assessment_required": True,
                "accepted_assessment_lineage": False,
            }
        row = self.conn.execute(
            "select * from attempt_assessments where id = ?",
            (assessment_id,),
        ).fetchone()
        valid = bool(
            row
            and row["status"] == "accepted"
            and row["attempt_id"] == attempt.get("id")
            and int(row["attempt_version"] or 0)
            == int(attempt.get("attempt_version") or 0)
            and int(row["assessment_version"] or 0) == assessment_version
            and row["assessment_digest_sha256"] == assessment_digest_sha256
        )
        return {
            "accepted_assessment_required": True,
            "accepted_assessment_lineage": valid,
        }

    def _answer_analysis_run_lineage(
        self,
        *,
        answer_analysis_agent_run_id: str | None,
        attempt: dict[str, Any],
        requested_provider_mode: str,
    ) -> dict[str, Any]:
        run_id = str(answer_analysis_agent_run_id or "")
        required = bool(run_id) or requested_provider_mode in {"live_model", "recorded_model"}
        if not required:
            return {
                "answer_analysis_agent_run_required": False,
                "effective_provider_mode": requested_provider_mode,
            }
        if not run_id:
            return {
                "answer_analysis_agent_run_required": True,
                "answer_analysis_agent_run_lineage": False,
                "effective_provider_mode": requested_provider_mode,
            }
        row = self.conn.execute("select * from agent_runs where id = ?", (run_id,)).fetchone()
        if not row:
            return {
                "answer_analysis_agent_run_required": True,
                "answer_analysis_agent_run_lineage": False,
                "effective_provider_mode": requested_provider_mode,
            }
        input_refs = db.json_load(row["input_refs_json"], {})
        model_params = db.json_load(row["model_params_json"], {})
        run_provider_mode = str(
            model_params.get("trust_mode")
            or model_params.get("provider_mode")
            or row["model_provider"]
            or requested_provider_mode
        )
        provider_matches = (
            requested_provider_mode in {"", "real"}
            or not run_provider_mode
            or requested_provider_mode == run_provider_mode
        )
        lineage_ok = (
            row["agent_key"] == "answer_analysis_agent"
            and row["phase"] == "answer_analysis"
            and row["status"] == "accepted"
            and str(input_refs.get("attempt_id") or "") == str(attempt.get("id") or "")
            and provider_matches
        )
        return {
            "answer_analysis_agent_run_required": True,
            "answer_analysis_agent_run_lineage": bool(lineage_ok),
            "effective_provider_mode": run_provider_mode or requested_provider_mode,
        }

    def _lineage_for_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        flow_step_id = str(attempt.get("flow_step_id") or "")
        question_id = str(attempt.get("question_id") or "")
        review_record_id = str(attempt.get("review_record_id") or "")
        node_id = str(attempt.get("node_id") or "")
        lineage: dict[str, Any] = {}
        step: sqlite3.Row | None = None

        if flow_step_id:
            step = self.conn.execute("select * from flow_steps where id = ?", (flow_step_id,)).fetchone()
            lineage["flow_step_exists"] = step is not None
            if step is not None:
                lineage["node_matches_step"] = bool(node_id and step["node_id"] == node_id)
                lineage["step_question_matches_attempt"] = bool(question_id and step["question_id"] == question_id)
                lineage["step_review_record_matches_attempt"] = bool(review_record_id and step["review_record_id"] == review_record_id)
                lineage["step_graph_version_matches_attempt"] = bool(attempt.get("graph_version") and step["graph_version"] == attempt.get("graph_version"))
                lineage["step_question_bank_version_matches_attempt"] = bool(
                    attempt.get("question_bank_version") and step["question_bank_version"] == attempt.get("question_bank_version")
                )
                lineage["step_attempt_matches_attempt"] = bool(step["attempt_id"] == attempt.get("id"))
            else:
                lineage["node_matches_step"] = False
                lineage["step_question_matches_attempt"] = False
                lineage["step_review_record_matches_attempt"] = False
                lineage["step_graph_version_matches_attempt"] = False
                lineage["step_question_bank_version_matches_attempt"] = False
                lineage["step_attempt_matches_attempt"] = False
        else:
            lineage["flow_step_exists"] = False
            lineage["node_matches_step"] = False
            lineage["step_question_matches_attempt"] = False
            lineage["step_review_record_matches_attempt"] = False
            lineage["step_graph_version_matches_attempt"] = False
            lineage["step_question_bank_version_matches_attempt"] = False
            lineage["step_attempt_matches_attempt"] = False

        question_dict: dict[str, Any] | None = None
        if question_id:
            question = self.conn.execute("select id, item_version from question_items where id = ?", (question_id,)).fetchone()
            lineage["question_exists"] = question is not None
            if question is not None:
                try:
                    question_dict = db.get_question(self.conn, question_id)
                except KeyError:
                    question_dict = None
            lineage["question_active_use"] = bool(question_dict and db.is_child_schedulable_question(self.conn, question_dict))
            if step is not None and question is not None:
                lineage["step_question_item_version_matches_question"] = bool(
                    step and step["question_item_version"] == question["item_version"]
                )
            else:
                lineage["step_question_item_version_matches_question"] = False
        else:
            lineage["question_exists"] = False
            lineage["question_active_use"] = False
            lineage["step_question_item_version_matches_question"] = False

        if review_record_id:
            lineage["review_record_active"] = bool(
                question_dict
                and db.question_review_record_allows_active_use(self.conn, question_dict, review_record_id)
            )
        else:
            lineage["review_record_active"] = False
        return lineage


def _report_label_for_failed_fields(failed_fields: list[str], *, provider_mode: str) -> str:
    if not failed_fields:
        return "confirmed"
    if "graph_version" in failed_fields or "question_bank_version" in failed_fields:
        return "stale"
    missing_lineage_fields = {
        "flow_step_id",
        "flow_step_lineage",
        "step_question_lineage",
        "step_review_record_lineage",
        "step_graph_version_lineage",
        "step_question_bank_version_lineage",
        "step_attempt_lineage",
        "step_question_item_version_lineage",
        "node_id",
        "node_lineage",
        "question_id",
        "question_lineage",
        "question_active_use_lineage",
        "review_record_id",
        "review_record_lineage",
        "answer_analysis_agent_run_lineage",
    }
    if any(field in failed_fields for field in missing_lineage_fields):
        return "missing_lineage"
    if provider_mode in {"mock", "mock_only"}:
        return "mock_only"
    if provider_mode == "not_configured":
        return "blocked"
    if "grading_status" in failed_fields or "analysis_status" in failed_fields:
        return "pending"
    return "blocked"
