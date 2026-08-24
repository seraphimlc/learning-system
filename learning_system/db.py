from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import internal_agents, multimodal_evidence, question_bank, question_usage


ANALYSIS_DIMENSIONS = {"final_answer", "model_or_relation", "steps", "symbols_units", "check_or_explanation", "other"}
REQUIRED_ANALYSIS_DIMENSIONS = {"final_answer", "model_or_relation", "steps", "symbols_units", "check_or_explanation"}
ANALYSIS_STATUSES = {"matched", "missing", "incorrect", "unclear", "alternative_valid"}
WEAK_ANALYSIS_STATUSES = {"missing", "incorrect", "unclear"}
ANALYSIS_EVIDENCE_STRENGTHS = {"strong", "medium", "weak", "insufficient"}
ANALYSIS_REASONING_SOUNDNESS = {"sound", "incomplete", "unsound", "unclear"}
ANALYSIS_NEXT_EVIDENCE_NEEDS = {
    "none",
    "same_structure_confirmation",
    "near_transfer_confirmation",
    "prerequisite_probe",
    "clearer_solution_evidence",
    "targeted_reteach",
}

SESSION_CLOSURE_STATUSES = ("not_started", "waiting_ai", "blocked", "evolving", "planned", "closed")
REPORT_CLAIM_LABELS = ("confirmed", "pending", "inferred", "stale", "blocked", "missing")
V3_REPORT_CLAIM_LABELS = (
    "confirmed",
    "pending",
    "blocked",
    "inferred",
    "stale",
    "mock_only",
    "missing_lineage",
)
V3_RUNTIME_VERSION = "2026-07-10.v3.skeleton"
V3_DEFAULT_CHILD_KEY = "single-child"
MIN_REVIEW_CONFIDENCE_FOR_DOWNSTREAM_EVIDENCE = 0.68
LOW_CONFIDENCE_NO_EVIDENCE_POLICY = "accepted_low_confidence_no_evidence_wrong"


class EvidenceUsePolicy:
    """v2 shared evidence gate; consumers should call this instead of re-filtering."""

    name = "active_graded_valid_analysis_current_question_high_confidence"
    required_terms = (
        "active",
        "graded",
        "valid_answer_analysis",
        "current_child_schedulable_question",
        "not_low_confidence_no_evidence",
    )
    consumers = ("evaluation", "planner", "self_evolution", "reports")

    @classmethod
    def explain(cls) -> dict[str, Any]:
        return {
            "name": cls.name,
            "required_terms": list(cls.required_terms),
            "consumers": list(cls.consumers),
        }

    @classmethod
    def is_usable_attempt(cls, conn: sqlite3.Connection, attempt: dict[str, Any]) -> bool:
        return is_current_usable_attempt_evidence(conn, attempt)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_load(value: str | None, fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    return json.loads(value)


def is_valid_answer_analysis(value: Any) -> bool:
    try:
        validate_answer_analysis(value)
        return True
    except ValueError:
        return False


def answer_analysis_statuses_by_dimension(value: dict[str, Any]) -> dict[str, str]:
    comparison = value.get("comparison")
    if not isinstance(comparison, list):
        return {}
    statuses: dict[str, str] = {}
    for item in comparison:
        if not isinstance(item, dict):
            continue
        dimension = item.get("dimension")
        status = item.get("status")
        if dimension in REQUIRED_ANALYSIS_DIMENSIONS and status in ANALYSIS_STATUSES:
            statuses[str(dimension)] = str(status)
    return statuses


def derive_answer_evaluation_support(value: dict[str, Any]) -> dict[str, Any]:
    statuses = answer_analysis_statuses_by_dimension(value)
    required_present = REQUIRED_ANALYSIS_DIMENSIONS <= set(statuses)
    weak_dimensions = sorted(
        dimension for dimension, status in statuses.items()
        if status in WEAK_ANALYSIS_STATUSES
    )
    has_unclear = any(status == "unclear" for status in statuses.values())

    reasoning_dimensions = ("model_or_relation", "steps", "check_or_explanation")
    reasoning_statuses = [statuses.get(dimension, "unclear") for dimension in reasoning_dimensions]
    if not required_present or any(status == "unclear" for status in reasoning_statuses):
        reasoning_soundness = "unclear"
    elif any(status == "incorrect" for status in reasoning_statuses):
        reasoning_soundness = "unsound"
    elif any(status == "missing" for status in reasoning_statuses):
        reasoning_soundness = "incomplete"
    else:
        reasoning_soundness = "sound"

    if not required_present:
        evidence_strength = "insufficient"
    elif not weak_dimensions:
        evidence_strength = "strong"
    elif (
        statuses.get("model_or_relation") in {"matched", "alternative_valid"}
        and statuses.get("steps") in {"matched", "alternative_valid"}
        and statuses.get("final_answer") in {"matched", "alternative_valid"}
    ):
        evidence_strength = "medium"
    elif (
        statuses.get("final_answer") in {"missing", "unclear"}
        and statuses.get("model_or_relation") in {"missing", "unclear"}
        and statuses.get("steps") in {"missing", "unclear"}
    ):
        evidence_strength = "insufficient"
    else:
        evidence_strength = "weak"

    if not required_present or has_unclear:
        next_evidence_need = "clearer_solution_evidence"
    elif not weak_dimensions:
        next_evidence_need = "none"
    elif statuses.get("model_or_relation") in {"missing", "incorrect"}:
        next_evidence_need = "prerequisite_probe" if statuses.get("steps") in {"missing", "incorrect"} else "targeted_reteach"
    elif statuses.get("steps") in WEAK_ANALYSIS_STATUSES or statuses.get("check_or_explanation") in WEAK_ANALYSIS_STATUSES:
        next_evidence_need = "same_structure_confirmation"
    elif statuses.get("final_answer") in WEAK_ANALYSIS_STATUSES or statuses.get("symbols_units") in WEAK_ANALYSIS_STATUSES:
        next_evidence_need = "same_structure_confirmation"
    else:
        next_evidence_need = "targeted_reteach"

    return {
        "usable_for_evaluation": required_present,
        "evidence_strength": evidence_strength,
        "reasoning_soundness": reasoning_soundness,
        "dominant_gap_dimensions": weak_dimensions,
        "needs_clearer_evidence": (not required_present) or has_unclear,
        "next_evidence_need": next_evidence_need,
    }


def validate_answer_analysis(value: Any) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError("answer_analysis must be a non-empty object")
    required_strings = [
        "agent_key",
        "optimal_answer",
        "child_answer_summary",
        "process_gap",
        "teaching_explanation",
        "next_child_prompt",
    ]
    for key in required_strings:
        if key not in value or not isinstance(value[key], str):
            raise ValueError(f"answer_analysis.{key} must be a string")
    if value["agent_key"] != "answer_analysis_agent":
        raise ValueError("answer_analysis.agent_key must be answer_analysis_agent")
    if not value["optimal_answer"].strip():
        raise ValueError("answer_analysis.optimal_answer is required")
    if not value["child_answer_summary"].strip():
        raise ValueError("answer_analysis.child_answer_summary is required")
    if not value["teaching_explanation"].strip():
        raise ValueError("answer_analysis.teaching_explanation is required")
    if not value["next_child_prompt"].strip():
        raise ValueError("answer_analysis.next_child_prompt is required")
    no_gap_observed = value.get("no_gap_observed", False)
    if not isinstance(no_gap_observed, bool):
        raise ValueError("answer_analysis.no_gap_observed must be a boolean when provided")
    steps = value.get("optimal_solution_steps")
    if not isinstance(steps, list) or not steps or not all(isinstance(step, str) and step.strip() for step in steps):
        raise ValueError("answer_analysis.optimal_solution_steps must be a non-empty string list")
    alternatives = value.get("alternative_solutions")
    if not isinstance(alternatives, list) or not all(isinstance(item, str) for item in alternatives):
        raise ValueError("answer_analysis.alternative_solutions must be a string list")
    comparison = value.get("comparison")
    if not isinstance(comparison, list) or not comparison:
        raise ValueError("answer_analysis.comparison must be a non-empty list")
    covered_dimensions: set[str] = set()
    weak_dimensions: set[str] = set()
    for item in comparison:
        if not isinstance(item, dict):
            raise ValueError("answer_analysis.comparison items must be objects")
        dimension = item.get("dimension")
        status = item.get("status")
        if dimension not in ANALYSIS_DIMENSIONS:
            raise ValueError("answer_analysis.comparison dimension is invalid")
        if status not in ANALYSIS_STATUSES:
            raise ValueError("answer_analysis.comparison status is invalid")
        if not isinstance(item.get("detail"), str) or not item["detail"].strip():
            raise ValueError("answer_analysis.comparison detail is required")
        if dimension in REQUIRED_ANALYSIS_DIMENSIONS:
            covered_dimensions.add(str(dimension))
            if status in WEAK_ANALYSIS_STATUSES:
                weak_dimensions.add(str(dimension))
    missing_dimensions = sorted(REQUIRED_ANALYSIS_DIMENSIONS - covered_dimensions)
    if missing_dimensions:
        raise ValueError(f"answer_analysis.comparison missing required dimensions: {', '.join(missing_dimensions)}")
    if weak_dimensions and not value["process_gap"].strip():
        raise ValueError("answer_analysis.process_gap is required when comparison shows a gap")
    if weak_dimensions and no_gap_observed:
        raise ValueError("answer_analysis.no_gap_observed cannot be true when comparison shows a gap")
    if not weak_dimensions and value["process_gap"].strip():
        raise ValueError("answer_analysis.process_gap requires at least one weak comparison dimension")
    if not weak_dimensions and not value["process_gap"].strip() and not no_gap_observed:
        raise ValueError("answer_analysis.no_gap_observed is required when there is no process gap")
    support = value.get("evaluation_support")
    if not isinstance(support, dict):
        raise ValueError("answer_analysis.evaluation_support must be an object")
    expected_support = derive_answer_evaluation_support(value)
    if support != expected_support:
        raise ValueError("answer_analysis.evaluation_support must match comparison-derived evidence")


def _validate_attempt_values(
    *,
    result: str,
    grading_status: str,
    score_points: float,
    max_points: float,
    error_tags: list[str],
    explanation_score: int | None,
    blocking_evidence: bool = False,
) -> None:
    if grading_status not in {"pending_review", "graded", "blocked"}:
        raise ValueError(f"Invalid grading status: {grading_status}")
    if result not in {"submitted", "correct", "partial", "wrong"}:
        raise ValueError(f"Invalid attempt result: {result}")
    if max_points <= 0:
        raise ValueError("max_points must be positive")
    if score_points < 0 or score_points > max_points:
        raise ValueError("score_points must be between 0 and max_points")
    if explanation_score is not None and explanation_score not in {0, 1, 2}:
        raise ValueError("explanation_score must be 0, 1, 2, or null")
    unknown_tags = [tag for tag in error_tags if tag not in question_bank.CANONICAL_ERROR_TAGS]
    if unknown_tags:
        raise ValueError(f"Unknown error tags: {', '.join(unknown_tags)}")
    if grading_status == "pending_review":
        if result != "submitted" or score_points != 0 or error_tags or blocking_evidence:
            raise ValueError("pending_review attempts must be submitted with no score, error tags, or blocking evidence")
        return
    if grading_status == "blocked":
        if result != "submitted" or score_points != 0 or error_tags or blocking_evidence:
            raise ValueError("blocked attempts must be submitted with no score, error tags, or blocking evidence")
        return
    if result == "submitted":
        raise ValueError("submitted result is only valid for pending_review or blocked attempts")
    if result == "correct" and score_points != max_points:
        raise ValueError("correct attempts must receive full score")
    if result == "partial" and not (0 < score_points < max_points):
        raise ValueError("partial attempts must receive partial score")
    if result == "wrong" and score_points != 0:
        raise ValueError("wrong attempts must receive zero score")
    if blocking_evidence and result != "wrong":
        raise ValueError("blocking_evidence is only valid for wrong attempts")


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("pragma foreign_keys = on")
    conn.executescript(
        """
        create table if not exists system_meta (
          key text primary key,
          value text not null,
          updated_at text not null
        );

        create table if not exists graph_nodes (
          id text primary key,
          name text not null,
          stage text not null,
          domain text not null,
          priority text not null,
          summer_mode text not null,
          sequence_band integer not null default 99,
          prerequisites_json text not null,
          unlocks_json text not null,
          raw_json text not null
        );

        create table if not exists graph_edges (
          id integer primary key autoincrement,
          from_node_id text not null,
          to_node_id text not null,
          relation text not null,
          unique(from_node_id, to_node_id, relation)
        );

        create table if not exists question_items (
          id text primary key,
          item_version text not null,
          source_type text not null,
          node_id text not null references graph_nodes(id),
          secondary_node_ids_json text not null,
          kind text not null,
          question_type text not null,
          variant_level text not null,
          production_category text not null default '',
          difficulty text not null default 'medium',
          purpose_role text not null default 'core',
          answer_verification text not null default 'pending',
          design_rationale_json text not null default '{}',
          prompt text not null,
          answer_format text not null,
          expected_answer text not null,
          rubric_json text not null,
          solution_steps_json text not null,
          error_tags_json text not null,
          rollback_candidate_node_ids_json text not null,
          rollback_candidate_relations_json text not null,
          estimated_minutes integer not null,
          parent_observation text not null,
          source_json text not null,
          created_by_event_id text,
          raw_json text not null
        );

        create table if not exists question_usage_policies (
          id text primary key,
          question_id text not null references question_items(id) on delete cascade,
          item_version text not null,
          policy_version text not null,
          status text not null default 'active',
          allowed_purposes_json text not null,
          default_practice_family text not null,
          allowed_practice_roles_json text not null,
          diagnostic_roles_json text not null,
          teaching_roles_json text not null,
          primary_node_id text not null references graph_nodes(id),
          secondary_node_ids_json text not null default '[]',
          structure_fingerprint text not null,
          support_only integer not null default 0,
          not_for_activation integer not null default 0,
          policy_digest_sha256 text not null,
          source_json text not null default '{}',
          created_at text not null,
          updated_at text not null
        );

        create table if not exists flow_step_usage_contexts (
          id text primary key,
          flow_step_id text not null unique references flow_steps(id) on delete cascade,
          question_usage_policy_id text not null references question_usage_policies(id),
          context_version text not null,
          purpose text not null,
          purpose_role text not null,
          practice_family text not null default '',
          practice_role text not null default '',
          hint_policy text not null,
          mastery_evidence_weight real not null,
          instability_signal_weight real not null,
          mastery_update_eligible integer not null,
          mastery_state_ceiling text not null,
          requires_diagnostic_confirmation integer not null,
          block_id text not null default '',
          block_index integer not null default 1,
          structure_fingerprint text not null,
          context_digest_sha256 text not null,
          raw_json text not null default '{}',
          created_at text not null
        );

        create table if not exists attempt_usage_contexts (
          id text primary key,
          attempt_id text not null unique references attempts(id) on delete cascade,
          flow_step_usage_context_id text not null references flow_step_usage_contexts(id),
          context_digest_sha256 text not null,
          snapshot_json text not null,
          created_at text not null
        );

        create table if not exists learning_sessions (
          id text primary key,
          title text not null,
          mode text not null,
          plan_id text,
          expected_question_ids_json text not null default '[]',
          question_snapshot_hashes_json text not null default '{}',
          status text not null default 'active',
          closure_status text not null default 'not_started',
          closure_result_json text not null default '{}',
          next_plan_id text,
          closed_at text,
          created_at text not null
        );

        create table if not exists attempts (
          id text primary key,
          session_id text not null references learning_sessions(id),
          question_id text not null references question_items(id),
          node_id text not null references graph_nodes(id),
          result text not null,
          grading_status text not null,
          evidence_status text not null default 'active',
          score_points real not null,
          max_points real not null,
          error_tags_json text not null,
          answer_raw text not null,
          parent_note text not null,
          evidence_note text not null default '',
          answer_analysis_json text not null default '{}',
          review_meta_json text not null default '{}',
          cause_analysis_json text not null default '{}',
          interaction_response_json text not null default '{}',
          explanation_score integer,
          blocking_evidence integer not null default 0,
          processed_evolution_event_id text,
          flow_step_id text,
          graph_version text not null default '',
          question_bank_version text not null default '',
          attempt_version integer not null default 1,
          analysis_version integer not null default 0,
          analysis_status text not null default 'missing',
          client_idempotency_key text not null default '',
          answer_source text not null default 'legacy',
          submission_request_digest_sha256 text not null default '',
          evidence_digest_sha256 text not null default '',
          attachment_ids_json text not null default '[]',
          review_record_id text not null default '',
          created_at text not null
        );

        create table if not exists attempt_attachments (
          id text primary key,
          attempt_id text not null references attempts(id) on delete cascade,
          kind text not null,
          original_filename text not null default '',
          filename text not null,
          content_type text not null,
          byte_size integer not null default 0,
          sha256 text not null default '',
          source text not null default 'answer_photo_data_url',
          relative_path text not null,
          created_at text not null
        );

        create table if not exists media_recognition_runs (
          id text primary key,
          flow_step_id text not null references flow_steps(id) on delete cascade,
          step_revision integer not null,
          question_id text not null references question_items(id),
          input_mode text not null,
          media_sha256 text not null,
          media_byte_size integer not null,
          media_version integer not null default 1,
          content_type text not null,
          recognizer_version text not null,
          recognition_status text not null,
          provider_mode text not null default 'not_configured',
          recognition_source text not null default '',
          trust_classification text not null default 'unknown',
          route_digest_sha256 text not null default '',
          recognized_text text not null default '',
          math_objects_json text not null default '[]',
          critical_token_uncertainties_json text not null default '[]',
          recognition_confidence real,
          output_digest_sha256 text not null,
          created_at text not null,
          unique(
            flow_step_id, step_revision, input_mode, media_sha256,
            media_byte_size, media_version, recognizer_version
          )
        );

        create table if not exists evidence_confirmations (
          id text primary key,
          attempt_id text not null references attempts(id) on delete cascade,
          recognition_run_id text not null references media_recognition_runs(id),
          confirmation_version integer not null,
          action text not null,
          confirmed_text text not null,
          client_corrections_json text not null default '[]',
          confirmation_digest_sha256 text not null,
          created_at text not null,
          unique(attempt_id, confirmation_version)
        );

        create table if not exists attempt_evidence_revisions (
          id text primary key,
          attempt_id text not null references attempts(id) on delete cascade,
          revision_number integer not null,
          parent_revision_id text references attempt_evidence_revisions(id),
          revision_kind text not null,
          schema_version text not null,
          input_mode text not null,
          recognition_status text not null,
          recognition_run_id text references media_recognition_runs(id),
          confirmation_id text references evidence_confirmations(id),
          recognition_source text not null default '',
          recognized_text text not null default '',
          effective_text text not null default '',
          recognition_confidence real,
          critical_token_uncertainties_json text not null default '[]',
          attachment_ids_json text not null default '[]',
          submission_request_digest_sha256 text not null default '',
          evidence_digest_sha256 text not null,
          raw_json text not null default '{}',
          created_at text not null,
          unique(attempt_id, revision_number),
          unique(attempt_id, evidence_digest_sha256)
        );

        create table if not exists learner_node_status (
          node_id text primary key references graph_nodes(id),
          status_code text not null,
          latest_score real not null,
          can_explain integer not null,
          evidence_attempt_ids_json text not null,
          status_reason text not null,
          graph_version text not null default '',
          question_bank_version text not null default '',
          mastery_decision_id text,
          source_attempt_ids_json text not null default '[]',
          source_evidence_validation_ids_json text not null default '[]',
          updated_by_agent_run_id text,
          status_revision integer not null default 1,
          updated_at text not null
        );

        create table if not exists agent_profiles (
          agent_key text primary key,
          display_name text not null,
          revision integer not null,
          profile_json text not null,
          updated_at text not null
        );

        create table if not exists evolution_events (
          id text primary key,
          trigger text not null,
          status text not null,
          event_type text not null,
          node_id text,
          evidence_attempt_ids_json text not null,
          before_json text not null,
          after_json text not null,
          created_question_ids_json text not null,
          created_at text not null
        );

        create table if not exists generated_plans (
          id text primary key,
          title text not null,
          tasks_json text not null,
          planner_policy_version text not null default '',
          plan_meta_json text not null default '{}',
          created_at text not null
        );

        create table if not exists agent_runs (
          id text primary key,
          batch_attempt_id text references answer_contract_generation_attempts(id),
          agent_key text not null,
          engine_type text not null,
          session_id text,
          phase text not null,
          trigger text not null,
          input_refs_json text not null default '{}',
          input_digest_sha256 text not null default '',
          provider_mode text not null default '',
          route_digest_sha256 text not null default '',
          semantic_request_digest_sha256 text not null default '',
          request_source_refs_digest_sha256 text not null default '',
          provider_chain_digest_sha256 text not null default '',
          agent_lineage_digest_sha256 text not null default '',
          prompt_version_id text not null default '',
          prompt_template_sha256 text not null default '',
          rendered_prompt_sha256 text not null default '',
          model_provider text not null default '',
          model_name text not null default '',
          model_alias text not null default '',
          model_params_json text not null default '{}',
          response_schema_version text not null default '',
          response_schema_sha256 text not null default '',
          status text not null,
          confidence real not null default 0,
          output_json text not null default '{}',
          output_digest_sha256 text not null default '',
          validation_errors_json text not null default '[]',
          error_reason text not null default '',
          created_at text not null
        );

        create table if not exists agent_handoffs (
          id text primary key,
          agent_run_id text references agent_runs(id),
          agent_key text not null,
          session_id text,
          phase text not null,
          target_node_ids_json text not null default '[]',
          question_ids_json text not null default '[]',
          attempt_ids_json text not null default '[]',
          next_action text not null default '',
          mastery_decision text not null default '',
          child_message_json text not null default '{}',
          audit_reason text not null default '',
          accepted integer not null default 0,
          created_at text not null
        );

        create table if not exists session_steps (
          id text primary key,
          session_id text not null,
          agent_run_id text references agent_runs(id),
          phase text not null,
          step_type text not null,
          payload_json text not null default '{}',
          status text not null default 'active',
          created_at text not null
        );

        create table if not exists mastery_decisions (
          id text primary key,
          session_id text not null,
          node_id text not null references graph_nodes(id),
          decision text not null,
          closure_result text not null,
          evidence_attempt_ids_json text not null default '[]',
          agent_run_id text references agent_runs(id),
          applied integer not null default 0,
          reason text not null default '',
          decision_payload_json text not null default '{}',
          graph_version text not null default '',
          question_bank_version text not null default '',
          source_attempt_ids_json text not null default '[]',
          source_evidence_validation_ids_json text not null default '[]',
          evaluation_agent_run_id text,
          decision_version integer not null default 1,
          old_status_id text,
          new_status_code text not null default '',
          dimension_scores_json text not null default '{}',
          source_evidence_validation_hash text not null default '',
          created_at text not null
        );

        create table if not exists question_review_records (
          id text primary key,
          question_id text,
          candidate_id text not null default '',
          item_version text not null default '',
          source_type text not null default '',
          candidate_sha256 text not null default '',
          designer_run_id text,
          reviewer_run_id text,
          review_contract_version text not null default '',
          review_status text not null,
          rejection_reasons_json text not null default '[]',
          criteria_json text not null default '{}',
          active_eligible integer not null default 0,
          reviewed_at text not null
        );

        create table if not exists evolution_audits (
          id text primary key,
          evolution_event_id text,
          session_id text,
          trigger text not null,
          evidence_attempt_ids_json text not null default '[]',
          before_json text not null default '{}',
          after_json text not null default '{}',
          created_question_ids_json text not null default '[]',
          question_review_record_ids_json text not null default '[]',
          no_action_reason text not null default '',
          created_at text not null
        );

        create table if not exists background_jobs (
          id text primary key,
          job_type text not null,
          session_id text not null references learning_sessions(id),
          attempt_id text references attempts(id),
          status text not null,
          run_count integer not null default 0,
          payload_json text not null default '{}',
          last_error text not null default '',
          idempotency_key text not null default '',
          flow_id text,
          flow_revision integer not null default 0,
          flow_step_id text,
          step_revision integer not null default 0,
          attempt_version integer not null default 0,
          analysis_version integer not null default 0,
          graph_version text not null default '',
          question_bank_version text not null default '',
          question_id text,
          review_record_id text not null default '',
          candidate_packet_id text not null default '',
          depends_on_json text not null default '[]',
          depends_on_job_id text,
          provider_mode text not null default 'not_configured',
          payload_schema_version text not null default '',
          available_at text,
          lease_owner text not null default '',
          claim_generation integer not null default 0,
          claim_token text not null default '',
          locked_at text,
          lease_expires_at text,
          retry_after text,
          result_refs_json text not null default '{}',
          blocked_reason text not null default '',
          dead_letter_reason text not null default '',
          route_meta_json text not null default '{}',
          created_at text not null,
          updated_at text not null,
          started_at text,
          finished_at text
        );

        create table if not exists answer_contracts (
          id text primary key,
          stable_contract_id text not null,
          question_id text not null references question_items(id),
          item_version text not null,
          contract_version integer not null default 1,
          contract_digest_sha256 text not null,
          question_digest_sha256 text not null default '',
          graph_version text not null default '',
          question_bank_version text not null default '',
          reference_solution_json text not null default '{}',
          score_points_json text not null default '[]',
          generator_version text not null default '',
          generation_input_digest_sha256 text not null default '',
          generator_run_id text references agent_runs(id),
          generator_batch_attempt_id text references answer_contract_generation_attempts(id),
          generator_provider_chain_digest_sha256 text not null default '',
          parent_contract_id text references answer_contracts(id),
          parent_contract_version integer,
          design_contract_schema_version text not null default '',
          review_contract_schema_version text not null default '',
          design_receipt_json text not null default '{}',
          design_receipt_sha256 text not null default '',
          repair_iteration integer not null default 0,
          repair_issue_digest_sha256 text not null default '',
          review_record_id text references question_review_records(id),
          review_run_id text references agent_runs(id),
          review_batch_attempt_id text references answer_contract_generation_attempts(id),
          review_provider_chain_digest_sha256 text not null default '',
          review_receipt_json text not null default '{}',
          review_receipt_sha256 text not null default '',
          fingerprint_policy_version text not null default '',
          prompt_instance_fingerprint text not null default '',
          core_structure_fingerprint text not null default '',
          status text not null default 'draft'
            check(status in ('draft','review_pending','approved','active','rejected','retired','superseded')),
          rejection_reason_json text not null default '{}',
          approved_at text,
          activated_at text,
          superseded_at text,
          created_at text not null,
          updated_at text not null
        );

        create table if not exists answer_contract_generation_runs (
          id text primary key,
          run_schema_version text not null,
          run_kind text not null check(run_kind in ('canary40','full1120')),
          run_identity_digest_sha256 text not null,
          parent_canary_run_id text references answer_contract_generation_runs(id),
          parent_canary_receipt_sha256 text not null default '',
          ledger_id text not null default '',
          bank_version text not null,
          manifest_sha256 text not null,
          graph_version text not null,
          plan_digest_sha256 text not null,
          selection_policy_version text not null default '',
          selection_source_digest_sha256 text not null default '',
          effective_evidence_role_policy_version text not null,
          effective_evidence_role_policy_digest_sha256 text not null,
          generator_policy_digest_sha256 text not null,
          designer_prompt_digest_sha256 text not null,
          designer_schema_digest_sha256 text not null,
          designer_route_digest_sha256 text not null,
          reviewer_prompt_digest_sha256 text not null,
          reviewer_schema_digest_sha256 text not null,
          reviewer_route_digest_sha256 text not null,
          expected_item_count integer not null,
          new_item_count integer not null,
          model_call_cap integer not null,
          provider_attempt_cap integer not null,
          item_wall_seconds real not null,
          heartbeat_interval_seconds real not null,
          stale_after_seconds real not null,
          operation_generation integer not null default 0,
          claim_token text,
          claim_owner_pid integer,
          claim_invocation_id text,
          claimed_at text,
          heartbeat_at text,
          preflight_status text not null default 'pending'
            check(preflight_status in ('pending','passed','blocked','not_applicable')),
          preflight_payload_json text not null default '{}',
          preflight_digest_sha256 text not null default '',
          status text not null default 'planned'
            check(status in (
              'planned','preflight_running','running','completed_passed',
              'completed_blocked','interrupted','blocked_integrity',
              'cap_exhausted','commit_unknown','committed_unverified'
            )),
          model_calls integer not null default 0,
          provider_attempts integer not null default 0,
          terminal_count integer not null default 0,
          last_error_class text not null default '',
          last_error text not null default '',
          created_at text not null,
          started_at text,
          updated_at text not null,
          interrupted_at text,
          completed_at text
        );

        create table if not exists answer_contract_generation_run_items (
          id text primary key,
          run_id text not null references answer_contract_generation_runs(id),
          ordinal integer not null,
          question_id text not null references question_items(id),
          item_version text not null,
          question_digest_sha256 text not null,
          node_id text not null,
          kind text not null,
          effective_evidence_role text not null,
          effective_evidence_role_policy_version text not null,
          review_record_id text not null references question_review_records(id),
          status text not null default 'pending'
            check(status in (
              'pending','running','approved','routed','terminal_failure',
              'interrupted','blocked_integrity','reused_approved'
            )),
          contract_id text references answer_contracts(id),
          contract_version integer,
          contract_digest_sha256 text not null default '',
          designer_run_id text references agent_runs(id),
          reviewer_run_id text references agent_runs(id),
          designer_batch_attempt_id text references answer_contract_generation_attempts(id),
          reviewer_batch_attempt_id text references answer_contract_generation_attempts(id),
          checkpoint_digest_sha256 text not null default '',
          checkpoint_projection_json text not null default '[]',
          model_calls integer not null default 0,
          provider_attempts integer not null default 0,
          terminal_class text not null default '',
          terminal_reason_code text not null default '',
          created_at text not null,
          started_at text,
          updated_at text not null,
          terminal_at text
        );

        create table if not exists answer_contract_generation_attempts (
          id text primary key,
          run_id text not null references answer_contract_generation_runs(id),
          run_item_id text not null references answer_contract_generation_run_items(id),
          claim_generation integer not null,
          claim_token_digest_sha256 text not null,
          role text not null check(role in ('designer','reviewer')),
          contract_version_index integer not null check(contract_version_index between 0 and 2),
          semantic_attempt_index integer not null check(semantic_attempt_index between 1 and 3),
          request_json text not null,
          request_digest_sha256 text not null,
          request_source_refs_digest_sha256 text not null default '',
          agent_input_refs_digest_sha256 text not null default '',
          agent_lineage_payload_json text not null default '{}',
          agent_lineage_digest_sha256 text not null default '',
          prompt_digest_sha256 text not null,
          schema_digest_sha256 text not null,
          route_digest_sha256 text not null,
          provider_chain_payload_json text not null default '{}',
          provider_chain_digest_sha256 text not null default '',
          status text not null default 'reserved'
            check(status in (
              'reserved','provider_calling','accepted','semantic_rejected',
              'transport_failed','interrupted','provider_result_unknown',
              'commit_unknown','committed_unverified'
            )),
          agent_run_id text references agent_runs(id),
          output_digest_sha256 text not null default '',
          local_verdict text not null default 'none'
            check(local_verdict in (
              'none','accepted','compiler_rejected','review_rejected','malformed'
            )),
          error_class text not null default '',
          reason_code text not null default '',
          reserved_at text not null,
          provider_calling_at text,
          result_at text,
          finished_at text
        );

        create table if not exists answer_contract_generation_provider_attempts (
          id text primary key,
          batch_attempt_id text not null references answer_contract_generation_attempts(id),
          candidate_ordinal integer not null,
          endpoint text not null,
          structured_json_mode text not null,
          request_digest_sha256 text not null,
          status text not null default 'reserved'
            check(status in (
              'reserved','calling','response_received','retryable_failure',
              'terminal_failure','provider_result_unknown','interrupted'
            )),
          http_status integer,
          retry_after_seconds real,
          response_digest_sha256 text not null default '',
          error_class text not null default '',
          error_message text not null default '',
          reserved_at text not null,
          call_started_at text,
          response_at text,
          finished_at text
        );

        create table if not exists answer_contract_generation_receipts (
          id text primary key,
          run_id text not null references answer_contract_generation_runs(id),
          receipt_schema_version text not null,
          receipt_kind text not null check(receipt_kind in ('canary40','full1120')),
          receipt_digest_sha256 text not null,
          payload_json text not null,
          completed_at text not null,
          status text not null default 'sealed' check(status = 'sealed')
        );

        create table if not exists attempt_assessments (
          id text primary key,
          attempt_id text not null references attempts(id) on delete cascade,
          attempt_version integer not null default 1,
          assessment_version integer not null default 1,
          assessment_digest_sha256 text not null,
          assessment_input_digest_sha256 text not null default '',
          question_id text not null references question_items(id),
          question_item_version text not null default '',
          answer_contract_id text not null references answer_contracts(id),
          answer_contract_version integer not null default 1,
          answer_contract_digest_sha256 text not null default '',
          criterion_judgments_json text not null default '[]',
          score_out_of_10 real,
          question_passed integer not null default 0 check(question_passed in (0, 1)),
          reference_answer_json text not null default '{}',
          answer_gap text not null default '',
          improvement_direction_json text not null default '[]',
          expression_judgment text not null default '',
          teaching_explanation text not null default '',
          semantic_output_json text not null default '{}',
          semantic_output_digest_sha256 text not null default '',
          semantic_envelope_json text not null default '{}',
          semantic_checkpointed_at text,
          trust_label text not null default 'pending',
          provider_mode text not null default 'not_configured',
          answer_analysis_agent_run_id text references agent_runs(id),
          evidence_gate_version text not null default '',
          status text not null default 'pending'
            check(status in ('pending','accepted','rejected','superseded')),
          supersedes_assessment_id text references attempt_assessments(id),
          rejection_reason text not null default '',
          accepted_at text,
          superseded_at text,
          created_at text not null,
          updated_at text not null
        );

        create table if not exists model_response_checkpoints (
          id text primary key,
          checkpoint_kind text not null,
          immutable_input_digest_sha256 text not null,
          source_job_id text not null default '',
          output_json text not null,
          output_digest_sha256 text not null,
          envelope_json text not null,
          envelope_digest_sha256 text not null,
          created_at text not null,
          unique(checkpoint_kind, immutable_input_digest_sha256)
        );

        create table if not exists model_response_inflight (
          checkpoint_kind text not null,
          immutable_input_digest_sha256 text not null,
          owner_token text not null,
          lease_expires_at text not null,
          created_at text not null,
          updated_at text not null,
          primary key(checkpoint_kind, immutable_input_digest_sha256)
        );

        create table if not exists daily_flows (
          id text primary key,
          child_key text not null default 'single-child',
          local_date text not null,
          mode text not null default 'not_selected',
          status text not null default 'new',
          budget_min integer not null default 10,
          budget_max integer not null default 20,
          current_step_id text,
          graph_version text not null,
          planned_graph_node_ids_json text not null default '[]',
          question_bank_version text not null default '',
          question_bank_ledger_id text not null default '',
          question_bank_manifest_sha256 text not null default '',
          legacy_session_id text references learning_sessions(id),
          flow_revision integer not null default 1,
          created_by_runtime_version text not null default '2026-07-10.v3.skeleton',
          source_plan_id text,
          blocked_reason text not null default '',
          summary_id text,
          created_at text not null,
          updated_at text not null
        );

        create table if not exists flow_steps (
          id text primary key,
          flow_id text not null references daily_flows(id) on delete cascade,
          step_handle text not null,
          position integer not null,
          step_type text not null,
          status text not null default 'selected',
          graph_version text not null,
          node_id text not null default '',
          question_bank_version text not null default '',
          question_id text,
          question_item_version text not null default '',
          review_record_id text not null default '',
          expected_evidence_json text not null default '{}',
          prompt_package_json text not null default '{}',
          selection_reason_json text not null default '{}',
          source_review_target_id text,
          source_next_step_decision_id text,
          candidate_packet_id text,
          attempt_id text,
          step_revision integer not null default 1,
          projection_hash text not null default '',
          superseded_by_step_id text,
          created_at text not null,
          updated_at text not null
        );

        create table if not exists learning_target_intents (
          id text primary key,
          child_key text not null,
          graph_version text not null,
          node_id text not null references graph_nodes(id),
          action text not null check(action in ('diagnostic','learn','review','challenge')),
          status text not null default 'pending'
            check(status in ('pending','waiting_for_safe_boundary','applied','blocked','cancelled')),
          source_flow_id text references daily_flows(id),
          source_flow_revision integer,
          source_step_id text references flow_steps(id),
          client_idempotency_key text not null,
          payload_digest_sha256 text not null,
          applied_flow_id text references daily_flows(id),
          applied_step_id text references flow_steps(id),
          reason text not null default '',
          created_at text not null,
          updated_at text not null
        );

        create table if not exists teaching_step_events (
          id text primary key,
          flow_id text not null,
          flow_step_id text not null,
          event_type text not null,
          event_payload_json text not null default '{}',
          evidence_status text not null default 'recorded',
          source_agent_run_id text not null default '',
          created_at text not null
        );

        create table if not exists review_targets (
          id text primary key,
          flow_id text not null references daily_flows(id) on delete cascade,
          graph_version text not null,
          node_id text not null,
          prerequisite_node_ids_json text not null default '[]',
          question_bank_version text not null default '',
          source_status_id text,
          source_mastery_decision_id text,
          source_attempt_ids_json text not null default '[]',
          priority integer not null default 0,
          reason_json text not null default '{}',
          status text not null default 'candidate',
          missing_lineage integer not null default 0,
          created_at text not null,
          updated_at text not null
        );

        create table if not exists evidence_validations (
          id text primary key,
          attempt_id text not null references attempts(id) on delete cascade,
          attempt_version integer not null default 1,
          analysis_version integer not null default 0,
          graph_version text not null,
          node_id text not null default '',
          question_id text not null default '',
          question_bank_version text not null default '',
          gate_version text not null,
          gate_status text not null,
          failed_fields_json text not null default '[]',
          predicate_result_json text not null default '{}',
          answer_analysis_agent_run_id text,
          provider_mode text not null default 'not_configured',
          created_at text not null,
          updated_at text not null
        );

        create table if not exists next_step_decisions (
          id text primary key,
          flow_id text not null references daily_flows(id) on delete cascade,
          flow_revision integer not null,
          decision_version integer not null default 1,
          decision_status text not null,
          action text not null,
          graph_version text not null,
          question_bank_version text not null default '',
          target_node_id text,
          source_step_id text,
          source_attempt_ids_json text not null default '[]',
          source_evidence_validation_ids_json text not null default '[]',
          source_mastery_decision_ids_json text not null default '[]',
          review_target_id text,
          candidate_packet_id text,
          candidate_packet_hash text not null default '',
          candidate_filter_summary_json text not null default '{}',
          pending_evidence_ids_json text not null default '[]',
          skipped_node_ids_json text not null default '[]',
          branch_policy_json text not null default '{}',
          planner_agent_run_id text,
          provider_mode text not null default 'not_configured',
          fallback_reason text,
          stale_lineage_ids_json text not null default '[]',
          mock_source_ids_json text not null default '[]',
          report_label text not null,
          reason text not null default '',
          created_at text not null
        );

        create table if not exists late_evidence_reconciliations (
          id text primary key,
          flow_id text not null references daily_flows(id) on delete cascade,
          graph_version text not null,
          node_id text not null default '',
          question_bank_version text not null default '',
          late_attempt_id text references attempts(id),
          late_analysis_version integer not null default 0,
          late_validation_id text,
          visible_step_id_at_arrival text,
          safe_transition_step_id text,
          applied_mastery_decision_id text,
          planner_reconsideration_decision_id text,
          included_in_summary integer not null default 0,
          reconciliation_status text not null default 'pending_safe_transition',
          created_at text not null,
          updated_at text not null
        );

        create table if not exists daily_summaries (
          id text primary key,
          flow_id text not null references daily_flows(id) on delete cascade,
          flow_revision integer not null,
          summary_version integer not null default 1,
          graph_version text not null,
          touched_node_ids_json text not null default '[]',
          question_bank_version text not null default '',
          source_step_ids_json text not null default '[]',
          source_attempt_ids_json text not null default '[]',
          source_evidence_validation_ids_json text not null default '[]',
          source_mastery_decision_ids_json text not null default '[]',
          source_next_step_decision_ids_json text not null default '[]',
          late_evidence_included_ids_json text not null default '[]',
          late_evidence_excluded_ids_json text not null default '[]',
          report_label_json text not null default '{}',
          child_summary_json text not null default '{}',
          operator_summary_json text not null default '{}',
          created_at text not null
        );

        create table if not exists question_bank_version_ledger (
          id text primary key,
          question_bank_version text not null,
          graph_version text not null default '',
          manifest_id text not null default '',
          manifest_sha256 text not null default '',
          node_count integer not null default 0,
          item_count integer not null default 0,
          status text not null,
          activated_at text,
          superseded_at text,
          rolled_back_at text,
          reason text not null default '',
          created_at text not null,
          updated_at text not null
        );

        -- M4-1 semester-mode tables (audit record 核对项 3 新增表 + 核对项 4 FK 方案③ 侧表)
        create table if not exists manual_error_entries (
          id text primary key,
          node_id text not null references graph_nodes(id),
          error_tag text not null,
          prompt_ctx text,
          source text not null default 'child_self_report',
          trust_status text not null default 'pending_parent',
          mode text not null default 'M0',
          retest_triggered_at text,
          recheck_count integer not null default 0,
          recheck_triggered_at text,
          parent_confirmed_at text,
          created_at text not null
        );

        create table if not exists error_cause_log (
          id text primary key,
          attempt_id text references attempts(id),
          manual_entry_id text references manual_error_entries(id),
          node_id text not null references graph_nodes(id),
          error_tag text not null,
          source text not null,
          confidence real,
          trust_status text not null default 'pending_parent',
          parent_confirmed_at text,
          graph_version text not null default '',
          created_at text not null
        );

        create table if not exists weekly_summary (
          id text primary key,
          iso_week text not null,
          status text not null default 'unacknowledged',
          node_status_snapshot_json text not null default '{}',
          coverage_json text not null default '{}',
          error_distribution_json text not null default '{}',
          evidence_scope text not null default 'system_only',
          narrative_json text not null default '{}',
          generated_at text not null,
          acknowledged_at text
        );

        create table if not exists daily_all_correct_confirmations (
          id text primary key,
          confirm_date text not null,
          confirmed_by text not null default 'child',
          evidence_scope_mark text not null default '',
          source_refs_json text,
          created_at text not null
        );
        -- mastery 判定不得读取本表：仅作每日全对证据范围标注，不进判定样本（设计稿 §3.1 / 审计核对项 3）；只 insert，confirm_date 每日唯一。

        -- M5 动机层 ② 自选目标（设计稿 §6.3.2）：每周让孩子从 2 个策展候选里自选
        -- 下周目标（有护栏的自主）。iso_week 周唯一，一周一次选择；周内改选走
        -- UPSERT（created_at 保留首次选择时间，updated_at 置位），与 weekly_summary
        -- 的 iso_week 唯一模式对齐（本表是记录载体，允许原地更新）。
        create table if not exists weekly_goal_choices (
          id text primary key,
          iso_week text not null,
          node_ids_json text not null,
          chosen_by text not null default 'child',
          created_at text not null,
          updated_at text
        );

        create index if not exists idx_questions_node on question_items(node_id);
        create index if not exists idx_questions_source on question_items(source_type);
        create unique index if not exists idx_question_usage_policies_one_active
          on question_usage_policies(question_id, item_version)
          where status = 'active';
        create index if not exists idx_question_usage_policies_node
          on question_usage_policies(primary_node_id, status);
        create index if not exists idx_question_usage_policies_fingerprint
          on question_usage_policies(structure_fingerprint, status);
        create index if not exists idx_flow_step_usage_contexts_block
          on flow_step_usage_contexts(block_id, block_index);
        create index if not exists idx_attempts_node on attempts(node_id);
        create index if not exists idx_attempts_processed on attempts(processed_evolution_event_id);
        create index if not exists idx_attempt_attachments_attempt on attempt_attachments(attempt_id);
        create index if not exists idx_media_recognition_runs_step_media
          on media_recognition_runs(flow_step_id, media_sha256, media_version);
        create index if not exists idx_attempt_evidence_revisions_latest
          on attempt_evidence_revisions(attempt_id, revision_number desc);
        create index if not exists idx_evidence_confirmations_attempt
          on evidence_confirmations(attempt_id, confirmation_version);
        create index if not exists idx_agent_runs_session on agent_runs(session_id);
        create index if not exists idx_teaching_step_events_flow on teaching_step_events(flow_id, created_at);
        create index if not exists idx_teaching_step_events_step on teaching_step_events(flow_step_id, created_at);
        create index if not exists idx_mastery_decisions_session on mastery_decisions(session_id);
        create index if not exists idx_background_jobs_session_status on background_jobs(session_id, status);
        create index if not exists idx_background_jobs_attempt on background_jobs(attempt_id);
        create unique index if not exists idx_agent_runs_unique_session_phase_trigger
          on agent_runs(agent_key, session_id, phase, trigger);
        create unique index if not exists idx_question_review_records_unique_question
          on question_review_records(question_id, item_version, candidate_sha256);
        create unique index if not exists idx_question_bank_version_ledger_active
          on question_bank_version_ledger(status)
          where status = 'active';
        create index if not exists idx_question_bank_version_ledger_version
          on question_bank_version_ledger(question_bank_version, status);
        create unique index if not exists idx_ac_generation_runs_identity
          on answer_contract_generation_runs(run_identity_digest_sha256);
        create unique index if not exists idx_ac_generation_run_items_ordinal
          on answer_contract_generation_run_items(run_id, ordinal);
        create unique index if not exists idx_ac_generation_run_items_question
          on answer_contract_generation_run_items(run_id, question_id, item_version);
        create index if not exists idx_ac_generation_run_items_status
          on answer_contract_generation_run_items(run_id, status, ordinal);
        create unique index if not exists idx_ac_generation_attempt_position
          on answer_contract_generation_attempts(
            run_item_id, role, contract_version_index, semantic_attempt_index
          );
        create index if not exists idx_ac_generation_attempt_run_status
          on answer_contract_generation_attempts(run_id, status);
        create unique index if not exists idx_ac_generation_provider_position
          on answer_contract_generation_provider_attempts(batch_attempt_id, candidate_ordinal);
        create unique index if not exists idx_ac_generation_receipts_run
          on answer_contract_generation_receipts(run_id);
        create unique index if not exists idx_ac_generation_receipts_digest
          on answer_contract_generation_receipts(receipt_digest_sha256);
        create index if not exists idx_manual_error_entries_node_created
          on manual_error_entries(node_id, created_at);
        create unique index if not exists idx_error_cause_log_system_idempotency
          on error_cause_log(attempt_id, error_tag)
          where attempt_id is not null;
        create unique index if not exists idx_error_cause_log_manual_idempotency
          on error_cause_log(manual_entry_id, error_tag)
          where manual_entry_id is not null;
        create index if not exists idx_error_cause_log_tag_created
          on error_cause_log(error_tag, created_at);
        create unique index if not exists idx_weekly_summary_iso_week
          on weekly_summary(iso_week);
        create unique index if not exists idx_daily_all_correct_confirmations_date
          on daily_all_correct_confirmations(confirm_date);
        create unique index if not exists idx_weekly_goal_choices_iso_week
          on weekly_goal_choices(iso_week);

        """
    )
    _ensure_column(
        conn,
        "question_items",
        "production_category",
        "text not null default ''",
    )
    _ensure_column(
        conn,
        "question_items",
        "difficulty",
        "text not null default 'medium'",
    )
    _ensure_column(
        conn,
        "question_items",
        "purpose_role",
        "text not null default 'core'",
    )
    _ensure_column(
        conn,
        "question_items",
        "answer_verification",
        "text not null default 'pending'",
    )
    _ensure_column(
        conn,
        "question_items",
        "design_rationale_json",
        "text not null default '{}'",
    )
    conn.execute(
        "create index if not exists idx_questions_production_category "
        "on question_items(production_category, item_version)"
    )
    _ensure_column(conn, "attempt_attachments", "original_filename", "text not null default ''")
    _ensure_column(conn, "attempt_attachments", "byte_size", "integer not null default 0")
    _ensure_column(conn, "attempt_attachments", "sha256", "text not null default ''")
    _ensure_column(conn, "attempt_attachments", "source", "text not null default 'answer_photo_data_url'")
    _ensure_column(conn, "attempts", "answer_analysis_json", "text not null default '{}'")
    _ensure_column(conn, "attempts", "review_meta_json", "text not null default '{}'")
    _ensure_column(conn, "attempts", "cause_analysis_json", "text not null default '{}'")
    _ensure_column(conn, "attempts", "interaction_response_json", "text not null default '{}'")
    _ensure_column(conn, "attempts", "evidence_status", "text not null default 'active'")
    _ensure_column(conn, "attempts", "evidence_note", "text not null default ''")
    _ensure_column(conn, "attempts", "flow_step_id", "text")
    _ensure_column(conn, "attempts", "graph_version", "text not null default ''")
    _ensure_column(conn, "attempts", "question_bank_version", "text not null default ''")
    _ensure_column(conn, "attempts", "attempt_version", "integer not null default 1")
    _ensure_column(conn, "attempts", "analysis_version", "integer not null default 0")
    _ensure_column(conn, "attempts", "analysis_status", "text not null default 'missing'")
    _ensure_column(conn, "attempts", "client_idempotency_key", "text not null default ''")
    _ensure_column(conn, "attempts", "answer_source", "text not null default 'legacy'")
    _ensure_column(conn, "attempts", "submission_request_digest_sha256", "text not null default ''")
    _ensure_column(conn, "attempts", "evidence_digest_sha256", "text not null default ''")
    _ensure_column(conn, "attempts", "attachment_ids_json", "text not null default '[]'")
    _ensure_column(conn, "attempts", "review_record_id", "text not null default ''")
    _ensure_column(conn, "attempts", "clarifies_attempt_id", "text references attempts(id)")
    _ensure_column(conn, "attempts", "attempt_role", "text not null default 'primary'")
    _ensure_column(conn, "daily_flows", "assessment_policy_version", "text not null default 'legacy'")
    _ensure_column(conn, "daily_flows", "question_bank_ledger_id", "text not null default ''")
    _ensure_column(conn, "daily_flows", "question_bank_manifest_sha256", "text not null default ''")
    conn.execute(
        "create unique index if not exists idx_question_bank_version_ledger_unique_version "
        "on question_bank_version_ledger(question_bank_version)"
    )
    _ensure_column(conn, "answer_contracts", "generation_input_digest_sha256", "text not null default ''")
    _ensure_column(conn, "answer_contracts", "parent_contract_id", "text references answer_contracts(id)")
    _ensure_column(conn, "answer_contracts", "parent_contract_version", "integer")
    _ensure_column(conn, "answer_contracts", "design_contract_schema_version", "text not null default ''")
    _ensure_column(conn, "answer_contracts", "review_contract_schema_version", "text not null default ''")
    _ensure_column(conn, "answer_contracts", "design_receipt_json", "text not null default '{}'")
    _ensure_column(conn, "answer_contracts", "design_receipt_sha256", "text not null default ''")
    _ensure_column(conn, "answer_contracts", "repair_iteration", "integer not null default 0")
    _ensure_column(conn, "answer_contracts", "repair_issue_digest_sha256", "text not null default ''")
    _ensure_column(
        conn,
        "agent_runs",
        "batch_attempt_id",
        "text references answer_contract_generation_attempts(id)",
    )
    _ensure_column(
        conn,
        "answer_contracts",
        "generator_batch_attempt_id",
        "text references answer_contract_generation_attempts(id)",
    )
    _ensure_column(
        conn,
        "answer_contracts",
        "review_batch_attempt_id",
        "text references answer_contract_generation_attempts(id)",
    )
    _ensure_column(
        conn,
        "answer_contract_generation_runs",
        "preflight_payload_json",
        "text not null default '{}'",
    )
    for column, declaration in (
        ("request_source_refs_digest_sha256", "text not null default ''"),
        ("agent_input_refs_digest_sha256", "text not null default ''"),
        ("agent_lineage_payload_json", "text not null default '{}'"),
        ("agent_lineage_digest_sha256", "text not null default ''"),
        ("provider_chain_payload_json", "text not null default '{}'"),
        ("provider_chain_digest_sha256", "text not null default ''"),
    ):
        _ensure_column(
            conn,
            "answer_contract_generation_attempts",
            column,
            declaration,
        )
    _ensure_column(
        conn,
        "answer_contract_generation_run_items",
        "checkpoint_projection_json",
        "text not null default '[]'",
    )
    for column in (
        "provider_mode",
        "route_digest_sha256",
        "semantic_request_digest_sha256",
        "request_source_refs_digest_sha256",
        "provider_chain_digest_sha256",
        "agent_lineage_digest_sha256",
    ):
        _ensure_column(conn, "agent_runs", column, "text not null default ''")
    _ensure_column(
        conn,
        "answer_contracts",
        "generator_provider_chain_digest_sha256",
        "text not null default ''",
    )
    _ensure_column(
        conn,
        "answer_contracts",
        "review_provider_chain_digest_sha256",
        "text not null default ''",
    )
    _ensure_column(conn, "flow_steps", "answer_contract_id", "text references answer_contracts(id)")
    _ensure_column(conn, "flow_steps", "answer_contract_version", "integer")
    _ensure_column(conn, "flow_steps", "answer_contract_digest_sha256", "text")
    _ensure_column(conn, "attempt_assessments", "semantic_output_json", "text not null default '{}'")
    _ensure_column(conn, "attempt_assessments", "semantic_output_digest_sha256", "text not null default ''")
    _ensure_column(conn, "attempt_assessments", "semantic_envelope_json", "text not null default '{}'")
    _ensure_column(conn, "attempt_assessments", "semantic_checkpointed_at", "text")
    _ensure_column(conn, "evidence_validations", "assessment_id", "text references attempt_assessments(id)")
    _ensure_column(conn, "evidence_validations", "assessment_version", "integer")
    _ensure_column(conn, "evidence_validations", "assessment_digest_sha256", "text")
    _ensure_column(conn, "learning_sessions", "plan_id", "text")
    _ensure_column(conn, "learning_sessions", "expected_question_ids_json", "text not null default '[]'")
    _ensure_column(conn, "learning_sessions", "question_snapshot_hashes_json", "text not null default '{}'")
    _ensure_column(conn, "learning_sessions", "status", "text not null default 'active'")
    _ensure_column(conn, "learning_sessions", "closure_status", "text not null default 'not_started'")
    _ensure_column(conn, "learning_sessions", "closure_result_json", "text not null default '{}'")
    _ensure_column(conn, "learning_sessions", "next_plan_id", "text")
    _ensure_column(conn, "learning_sessions", "closed_at", "text")
    _ensure_column(conn, "mastery_decisions", "decision_payload_json", "text not null default '{}'")
    _ensure_column(conn, "mastery_decisions", "graph_version", "text not null default ''")
    _ensure_column(conn, "mastery_decisions", "question_bank_version", "text not null default ''")
    _ensure_column(conn, "mastery_decisions", "source_attempt_ids_json", "text not null default '[]'")
    _ensure_column(conn, "mastery_decisions", "source_evidence_validation_ids_json", "text not null default '[]'")
    _ensure_column(conn, "mastery_decisions", "evaluation_agent_run_id", "text")
    _ensure_column(conn, "mastery_decisions", "decision_version", "integer not null default 1")
    _ensure_column(conn, "mastery_decisions", "old_status_id", "text")
    _ensure_column(conn, "mastery_decisions", "new_status_code", "text not null default ''")
    _ensure_column(conn, "mastery_decisions", "dimension_scores_json", "text not null default '{}'")
    _ensure_column(conn, "mastery_decisions", "source_evidence_validation_hash", "text not null default ''")
    _ensure_column(conn, "learner_node_status", "graph_version", "text not null default ''")
    _ensure_column(conn, "learner_node_status", "question_bank_version", "text not null default ''")
    _ensure_column(conn, "learner_node_status", "mastery_decision_id", "text")
    _ensure_column(conn, "learner_node_status", "source_attempt_ids_json", "text not null default '[]'")
    _ensure_column(conn, "learner_node_status", "source_evidence_validation_ids_json", "text not null default '[]'")
    _ensure_column(conn, "learner_node_status", "updated_by_agent_run_id", "text")
    _ensure_column(conn, "learner_node_status", "status_revision", "integer not null default 1")
    _ensure_column(conn, "background_jobs", "idempotency_key", "text not null default ''")
    _ensure_column(conn, "background_jobs", "flow_id", "text")
    _ensure_column(conn, "background_jobs", "flow_revision", "integer not null default 0")
    _ensure_column(conn, "background_jobs", "flow_step_id", "text")
    _ensure_column(conn, "background_jobs", "step_revision", "integer not null default 0")
    _ensure_column(conn, "background_jobs", "attempt_version", "integer not null default 0")
    _ensure_column(conn, "background_jobs", "analysis_version", "integer not null default 0")
    _ensure_column(conn, "background_jobs", "graph_version", "text not null default ''")
    _ensure_column(conn, "background_jobs", "question_bank_version", "text not null default ''")
    _ensure_column(conn, "background_jobs", "question_id", "text")
    _ensure_column(conn, "background_jobs", "review_record_id", "text not null default ''")
    _ensure_column(conn, "background_jobs", "candidate_packet_id", "text not null default ''")
    _ensure_column(conn, "background_jobs", "depends_on_json", "text not null default '[]'")
    _ensure_column(conn, "background_jobs", "depends_on_job_id", "text")
    _ensure_column(conn, "background_jobs", "provider_mode", "text not null default 'not_configured'")
    _ensure_column(conn, "background_jobs", "payload_schema_version", "text not null default ''")
    _ensure_column(conn, "background_jobs", "available_at", "text")
    _ensure_column(conn, "background_jobs", "lease_owner", "text not null default ''")
    _ensure_column(conn, "background_jobs", "claim_generation", "integer not null default 0")
    _ensure_column(conn, "background_jobs", "claim_token", "text not null default ''")
    _ensure_column(conn, "background_jobs", "locked_at", "text")
    _ensure_column(conn, "background_jobs", "lease_expires_at", "text")
    _ensure_column(conn, "background_jobs", "retry_after", "text")
    _ensure_column(conn, "background_jobs", "result_refs_json", "text not null default '{}'")
    _ensure_column(conn, "background_jobs", "blocked_reason", "text not null default ''")
    _ensure_column(conn, "background_jobs", "dead_letter_reason", "text not null default ''")
    _ensure_column(conn, "background_jobs", "route_meta_json", "text not null default '{}'")
    _ensure_column(conn, "media_recognition_runs", "trust_classification", "text not null default 'unknown'")
    _ensure_column(conn, "generated_plans", "planner_policy_version", "text not null default ''")
    _ensure_column(conn, "generated_plans", "plan_meta_json", "text not null default '{}'")
    conn.executescript(
        """
        create unique index if not exists idx_v3_daily_flows_one_active_per_child_day
          on daily_flows(child_key, local_date)
          where status in ('new','reviewing','ready_for_new_knowledge','learning_new','paused','blocked');
        create index if not exists idx_v3_daily_flows_local_date_status
          on daily_flows(local_date, status);
        create unique index if not exists idx_v3_flow_steps_unique_handle
          on flow_steps(step_handle);
        create unique index if not exists idx_v3_flow_steps_one_current_per_flow
          on flow_steps(flow_id)
          where status in ('selected','displayed','analyzing') and superseded_by_step_id is null;
        create index if not exists idx_v3_flow_steps_flow_status_position
          on flow_steps(flow_id, status, position);
        create index if not exists idx_v3_review_targets_flow_status_priority
          on review_targets(flow_id, status, priority);
        create unique index if not exists idx_v3_attempts_one_active_per_step
          on attempts(flow_step_id)
          where flow_step_id is not null and evidence_status = 'active';
        create unique index if not exists idx_v3_attempts_submit_idempotency
          on attempts(flow_step_id, client_idempotency_key)
          where flow_step_id is not null and client_idempotency_key <> '';
        create unique index if not exists idx_v3_background_jobs_active_idempotency
          on background_jobs(idempotency_key)
          where idempotency_key <> '' and status in ('queued','claimed','running','waiting','retry');
        create index if not exists idx_v3_background_jobs_flow_status
          on background_jobs(flow_id, status);
        create unique index if not exists idx_v3_evidence_validations_attempt_analysis_gate
          on evidence_validations(attempt_id, attempt_version, analysis_version, gate_version);
        create index if not exists idx_v3_evidence_validations_attempt_created
          on evidence_validations(attempt_id, created_at);
        create unique index if not exists idx_v3_mastery_decisions_evidence_package
          on mastery_decisions(node_id, graph_version, source_evidence_validation_hash, decision_version)
          where graph_version <> '' and source_evidence_validation_hash <> '';
        create unique index if not exists idx_v3_next_step_decisions_flow_revision_source
          on next_step_decisions(flow_id, flow_revision, coalesce(source_step_id, ''), decision_version);
        create unique index if not exists idx_v3_daily_summaries_flow_revision
          on daily_summaries(flow_id, flow_revision, summary_version);
        create unique index if not exists idx_answer_contracts_one_active_per_question_version
          on answer_contracts(question_id, item_version)
          where status = 'active';
        create index if not exists idx_answer_contracts_question_status
          on answer_contracts(question_id, item_version, status);
        create unique index if not exists idx_answer_contracts_stable_version
          on answer_contracts(stable_contract_id, contract_version);
        create unique index if not exists idx_answer_contracts_question_item_contract_version
          on answer_contracts(question_id, item_version, contract_version);
        create unique index if not exists idx_answer_contracts_generation_input
          on answer_contracts(question_id, item_version, generation_input_digest_sha256)
          where generation_input_digest_sha256 <> '';
        create index if not exists idx_answer_contracts_parent_lineage
          on answer_contracts(parent_contract_id, parent_contract_version, repair_iteration);
        create unique index if not exists idx_agent_runs_batch_attempt
          on agent_runs(batch_attempt_id)
          where batch_attempt_id is not null and batch_attempt_id <> '';
        create index if not exists idx_answer_contracts_batch_attempt_lineage
          on answer_contracts(generator_batch_attempt_id, review_batch_attempt_id);
        create unique index if not exists idx_attempt_assessments_one_accepted_per_attempt_version
          on attempt_assessments(attempt_id, attempt_version)
          where status = 'accepted';
        create unique index if not exists idx_attempt_assessments_input_idempotency
          on attempt_assessments(
            attempt_id, attempt_version, answer_contract_id,
            assessment_input_digest_sha256
          );
        create index if not exists idx_attempt_assessments_attempt_status
          on attempt_assessments(attempt_id, attempt_version, status, assessment_version);
        create index if not exists idx_model_response_checkpoints_source_job
          on model_response_checkpoints(source_job_id, checkpoint_kind);
        create index if not exists idx_model_response_inflight_lease
          on model_response_inflight(lease_expires_at);
        create unique index if not exists idx_learning_target_intents_idempotency
          on learning_target_intents(child_key, graph_version, client_idempotency_key);
        create unique index if not exists idx_learning_target_intents_one_nonterminal
          on learning_target_intents(child_key, graph_version)
          where status in ('pending','waiting_for_safe_boundary');
        create index if not exists idx_learning_target_intents_status_created
          on learning_target_intents(child_key, graph_version, status, created_at);
        drop index if exists idx_learning_target_intents_applied_step;
        create index idx_learning_target_intents_applied_step
          on learning_target_intents(applied_step_id)
          where status = 'applied' and applied_step_id is not null;
        """
    )
    _backfill_question_usage_policies(conn)
    _backfill_teaching_flow_step_usage_contexts(conn)
    _backfill_attempt_evidence_revisions(conn)
    conn.commit()


def _digest_json(value: Any) -> str:
    return hashlib.sha256(json_dump(value).encode("utf-8")).hexdigest()


def _canonical_digest_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


BACKGROUND_JOB_TYPES = {
    "answer_review",
    "answer_analysis",
    "evidence_validation",
    "evaluation_update",
    "planner_decision",
    "teaching_generation",
}
BACKGROUND_JOB_STATUSES = {
    "queued",
    "claimed",
    "running",
    "succeeded",
    "waiting",
    "retry",
    "blocked",
    "dead_letter",
    "error",
}
ACTIVE_BACKGROUND_JOB_STATUSES = {"queued", "running"}
V3_ACTIVE_BACKGROUND_JOB_STATUSES = {"queued", "claimed", "running", "waiting", "retry"}


def _background_job_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "session_id": row["session_id"],
        "attempt_id": row["attempt_id"],
        "status": row["status"],
        "run_count": int(row["run_count"]),
        "payload": json_load(row["payload_json"], {}),
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def enqueue_background_job(
    conn: sqlite3.Connection,
    *,
    job_type: str,
    session_id: str,
    attempt_id: str | None = None,
    payload: dict[str, Any] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    if job_type not in BACKGROUND_JOB_TYPES:
        raise ValueError(f"Invalid background job type: {job_type}")
    existing = conn.execute(
        """
        select *
        from background_jobs
        where job_type = ?
          and session_id = ?
          and coalesce(attempt_id, '') = coalesce(?, '')
          and status in ('queued', 'running', 'waiting', 'error')
        order by created_at desc, id desc
        limit 1
        """,
        (job_type, session_id, attempt_id),
    ).fetchone()
    if existing:
        return _background_job_from_row(existing)
    now = now_iso()
    job_id = f"BJ-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into background_jobs(
          id, job_type, session_id, attempt_id, status, run_count,
          payload_json, last_error, created_at, updated_at, started_at, finished_at
        ) values (?, ?, ?, ?, 'queued', 0, ?, '', ?, ?, null, null)
        """,
        (job_id, job_type, session_id, attempt_id, json_dump(payload or {}), now, now),
    )
    if commit:
        conn.commit()
    return {
        "id": job_id,
        "job_type": job_type,
        "session_id": session_id,
        "attempt_id": attempt_id,
        "status": "queued",
        "run_count": 0,
        "payload": payload or {},
        "last_error": "",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }


def mark_background_job_running(
    conn: sqlite3.Connection,
    *,
    job_type: str,
    session_id: str,
    attempt_id: str | None = None,
    commit: bool = True,
) -> None:
    now = now_iso()
    conn.execute(
        """
        update background_jobs
        set status = 'running',
            run_count = run_count + 1,
            updated_at = ?,
            started_at = coalesce(started_at, ?),
            finished_at = null,
            last_error = ''
        where job_type = ?
          and session_id = ?
          and coalesce(attempt_id, '') = coalesce(?, '')
          and status in ('queued', 'running', 'waiting', 'error')
        """,
        (now, now, job_type, session_id, attempt_id),
    )
    if commit:
        conn.commit()


def finish_background_job(
    conn: sqlite3.Connection,
    *,
    job_type: str,
    session_id: str,
    attempt_id: str | None = None,
    status: str,
    last_error: str = "",
    commit: bool = True,
) -> None:
    if status not in BACKGROUND_JOB_STATUSES - ACTIVE_BACKGROUND_JOB_STATUSES:
        raise ValueError(f"Invalid terminal background job status: {status}")
    now = now_iso()
    conn.execute(
        """
        update background_jobs
        set status = ?,
            updated_at = ?,
            finished_at = ?,
            last_error = ?
        where job_type = ?
          and session_id = ?
          and coalesce(attempt_id, '') = coalesce(?, '')
        """,
        (status, now, now, last_error[:800], job_type, session_id, attempt_id),
    )
    if commit:
        conn.commit()


def background_jobs_for_session(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select *
        from background_jobs
        where session_id = ?
        order by created_at, id
        """,
        (session_id,),
    ).fetchall()
    return [_background_job_from_row(row) for row in rows]


def pending_background_session_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        select distinct session_id
        from background_jobs
        where status in ('queued', 'running')
        union
        select distinct a.session_id
        from attempts a
        join learning_sessions s on s.id = a.session_id
        where a.grading_status = 'pending_review'
          and a.evidence_status = 'active'
          and s.mode = 'child_learning_group'
          and s.status != 'closed'
        order by session_id
        """
    ).fetchall()
    return [row["session_id"] for row in rows]


def record_agent_run(
    conn: sqlite3.Connection,
    *,
    agent_key: str,
    engine_type: str,
    session_id: str | None,
    phase: str,
    trigger: str,
    input_refs: dict[str, Any] | None = None,
    prompt_version_id: str = "",
    status: str,
    confidence: float = 0.0,
    output: dict[str, Any] | None = None,
    validation_errors: list[str] | None = None,
    error_reason: str = "",
    prompt_template_sha256: str = "",
    rendered_prompt_sha256: str = "",
    model_provider: str = "",
    model_name: str = "",
    model_alias: str = "",
    model_params: dict[str, Any] | None = None,
    response_schema_version: str = "",
    response_schema_sha256: str = "",
    commit: bool = True,
) -> dict[str, Any]:
    if engine_type not in {"model", "deterministic", "hybrid", "manual_maintenance"}:
        raise ValueError(f"Invalid agent engine type: {engine_type}")
    if status not in {"accepted", "rejected", "pending", "error"}:
        raise ValueError(f"Invalid agent run status: {status}")
    input_refs = input_refs or {}
    output = output or {}
    model_params = model_params or {}
    validation_errors = validation_errors or []
    run_id = f"AR-{uuid.uuid4().hex[:12]}"
    created_at = now_iso()
    conn.execute(
        """
        insert or ignore into agent_runs(
          id, agent_key, engine_type, session_id, phase, trigger,
          input_refs_json, input_digest_sha256, prompt_version_id,
          prompt_template_sha256, rendered_prompt_sha256, model_provider,
          model_name, model_alias, model_params_json, response_schema_version,
          response_schema_sha256, status, confidence, output_json,
          output_digest_sha256, validation_errors_json, error_reason, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            agent_key,
            engine_type,
            session_id,
            phase,
            trigger,
            json_dump(input_refs),
            _digest_json(input_refs),
            prompt_version_id,
            prompt_template_sha256,
            rendered_prompt_sha256,
            model_provider,
            model_name,
            model_alias,
            json_dump(model_params),
            response_schema_version,
            response_schema_sha256,
            status,
            float(confidence),
            json_dump(output),
            _digest_json(output),
            json_dump(validation_errors),
            error_reason,
            created_at,
        ),
    )
    existing = conn.execute(
        """
        select *
        from agent_runs
        where agent_key = ?
          and coalesce(session_id, '') = coalesce(?, '')
          and phase = ?
          and trigger = ?
        order by created_at, id
        limit 1
        """,
        (agent_key, session_id, phase, trigger),
    ).fetchone()
    if commit:
        conn.commit()
    if existing and existing["id"] != run_id:
        return {
            "id": existing["id"],
            "agent_key": existing["agent_key"],
            "engine_type": existing["engine_type"],
            "session_id": existing["session_id"],
            "phase": existing["phase"],
            "trigger": existing["trigger"],
            "status": existing["status"],
            "confidence": float(existing["confidence"]),
            "output": json_load(existing["output_json"], {}),
            "created_at": existing["created_at"],
        }
    return {
        "id": run_id,
        "agent_key": agent_key,
        "engine_type": engine_type,
        "session_id": session_id,
        "phase": phase,
        "trigger": trigger,
        "status": status,
        "confidence": float(confidence),
        "output": output,
        "created_at": created_at,
    }


def _agent_run_record_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "agent_key": row["agent_key"],
        "engine_type": row["engine_type"],
        "session_id": row["session_id"],
        "phase": row["phase"],
        "trigger": row["trigger"],
        "status": row["status"],
        "confidence": float(row["confidence"]),
        "output": json_load(row["output_json"], {}),
        "created_at": row["created_at"],
    }


def _find_agent_run_by_trigger(
    conn: sqlite3.Connection,
    *,
    agent_key: str,
    phase: str,
    trigger: str,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select *
        from agent_runs
        where agent_key = ?
          and coalesce(session_id, '') = coalesce(?, '')
          and phase = ?
          and trigger = ?
        order by created_at, id
        limit 1
        """,
        (agent_key, session_id, phase, trigger),
    ).fetchone()
    return _agent_run_record_from_row(row)


def record_mastery_decision(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    node_id: str,
    decision: str,
    closure_result: str,
    evidence_attempt_ids: list[str],
    agent_run_id: str | None,
    applied: bool,
    reason: str,
    decision_payload: dict[str, Any] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    decision_id = f"MD-{uuid.uuid4().hex[:12]}"
    created_at = now_iso()
    conn.execute(
        """
        insert into mastery_decisions(
          id, session_id, node_id, decision, closure_result,
          evidence_attempt_ids_json, agent_run_id, applied, reason,
          decision_payload_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            session_id,
            node_id,
            decision,
            closure_result,
            json_dump(evidence_attempt_ids),
            agent_run_id,
            1 if applied else 0,
            reason,
            json_dump(decision_payload or {}),
            created_at,
        ),
    )
    if commit:
        conn.commit()
    return {
        "id": decision_id,
        "session_id": session_id,
        "node_id": node_id,
        "decision": decision,
        "closure_result": closure_result,
        "evidence_attempt_ids": evidence_attempt_ids,
        "agent_run_id": agent_run_id,
        "applied": applied,
        "reason": reason,
        "decision_payload": decision_payload or {},
        "created_at": created_at,
    }


def record_teaching_step_event(
    conn: sqlite3.Connection,
    *,
    flow_id: str,
    flow_step_id: str,
    event_type: str,
    event_payload: dict[str, Any] | None = None,
    evidence_status: str = "recorded",
    source_agent_run_id: str = "",
    commit: bool = True,
) -> dict[str, Any]:
    event_id = f"TSE-{uuid.uuid4().hex[:12]}"
    created_at = now_iso()
    payload = event_payload or {}
    conn.execute(
        """
        insert into teaching_step_events(
          id, flow_id, flow_step_id, event_type, event_payload_json,
          evidence_status, source_agent_run_id, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            flow_id,
            flow_step_id,
            event_type,
            json_dump(payload),
            evidence_status,
            source_agent_run_id,
            created_at,
        ),
    )
    if commit:
        conn.commit()
    return {
        "id": event_id,
        "flow_id": flow_id,
        "flow_step_id": flow_step_id,
        "event_type": event_type,
        "event_payload": payload,
        "evidence_status": evidence_status,
        "source_agent_run_id": source_agent_run_id,
        "created_at": created_at,
    }


def teaching_step_events_for_flow(conn: sqlite3.Connection, flow_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select *
        from teaching_step_events
        where flow_id = ?
        order by created_at, id
        """,
        (flow_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "flow_id": row["flow_id"],
            "flow_step_id": row["flow_step_id"],
            "event_type": row["event_type"],
            "event_payload": json_load(row["event_payload_json"], {}),
            "evidence_status": row["evidence_status"],
            "source_agent_run_id": row["source_agent_run_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _reviewer_run_authorizes_question_review(
    conn: sqlite3.Connection,
    reviewer_run_id: str | None,
    candidate: dict[str, Any],
    source_type: str,
) -> bool:
    if not reviewer_run_id:
        return False
    run = conn.execute(
        """
        select agent_key, phase, status, input_refs_json, output_json
        from agent_runs
        where id = ?
        limit 1
        """,
        (reviewer_run_id,),
    ).fetchone()
    if not run:
        return False
    if run["agent_key"] != question_bank.QUESTION_REVIEWER_AGENT_KEY or run["status"] != "accepted":
        return False

    input_refs = json_load(run["input_refs_json"], {})
    output = json_load(run["output_json"], {})
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    candidate_sha256s = {
        _digest_json(candidate),
        _canonical_digest_json(candidate),
    }

    if run["phase"] == "curated_seed_question_review":
        return (
            source_type == "graph_generated"
            and candidate.get("item_version") == question_bank.QUESTION_BANK_VERSION
            and source.get("curated_manifest_id") == question_bank.GRAPH_SEED_REVIEW_MANIFEST_ID
            and input_refs.get("curated_manifest_id") == question_bank.GRAPH_SEED_REVIEW_MANIFEST_ID
            and input_refs.get("question_bank_version") == question_bank.QUESTION_BANK_VERSION
        )

    if run["phase"] in {"question_quality_review", "test_question_quality_review"}:
        question_id = str(candidate.get("id") or "")
        if run["phase"] == "question_quality_review" and input_refs.get("candidate_sha256") not in candidate_sha256s:
            return False
        if run["phase"] == "test_question_quality_review" and input_refs.get("candidate_sha256") not in {None, "", *candidate_sha256s}:
            return False
        return (
            input_refs.get("question_id") == question_id
            and (
                output.get("review_status") == "approved"
                or output.get("active_eligible") is True
            )
        )

    if run["phase"] == "formal_question_quality_review_import":
        formal_review = (
            source.get("formal_review")
            if isinstance(source.get("formal_review"), dict)
            else {}
        )
        canonical_sha256 = str(
            candidate.get("canonical_activation_payload_sha256")
            or formal_review.get("reviewed_content_sha256")
            or ""
        )
        return (
            source_type == "graph_generated"
            and source.get("formal_production_source")
            == question_bank.FORMAL_ADMIN_PRODUCTION_SOURCE
            and input_refs.get("question_id") == str(candidate.get("id") or "")
            and input_refs.get("canonical_activation_payload_sha256")
            == canonical_sha256
            and formal_review.get("reviewed_content_sha256") == canonical_sha256
            and output.get("review_status") == "approved"
            and output.get("active_eligible") is True
            and output.get("receipt_status") == "PASS"
            and output.get("provider_mode") == "live_model"
            and output.get("review_authority_current") is True
        )

    return False


def record_question_review_record(
    conn: sqlite3.Connection,
    *,
    question_id: str | None,
    candidate_id: str,
    item_version: str,
    source_type: str,
    candidate: dict[str, Any],
    designer_run_id: str | None = None,
    reviewer_run_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    quality = question_bank.review_item_quality_for_active_use(candidate)
    candidate_sha256 = _digest_json(candidate)
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    is_formal_admin_question = (
        source.get("formal_production_source")
        == question_bank.FORMAL_ADMIN_PRODUCTION_SOURCE
    )
    active_eligible = (
        quality.get("review_status") == "approved"
        and quality.get("age_floor") == question_bank.INCOMING_GRADE_7_AGE_FLOOR
        and (
            is_formal_admin_question
            or (
                quality.get("requires_reasoning") is True
                and quality.get("no_mechanical_drill") is True
            )
        )
        and _reviewer_run_authorizes_question_review(conn, reviewer_run_id, candidate, source_type)
    )
    if question_id:
        conn.execute(
            """
            update question_review_records
            set active_eligible = 0
            where question_id = ?
              and item_version = ?
              and source_type = ?
              and candidate_sha256 <> ?
            """,
            (question_id, item_version, source_type, candidate_sha256),
        )
    reviewed_at = now_iso()
    contract_version = quality.get(
        "contract_version", question_bank.QUESTION_PRODUCTION_CONTRACT_VERSION
    )
    review_status = quality.get("review_status", "rejected")
    rejection_reasons = json_dump(quality.get("rejection_reasons", []))
    criteria = json_dump({
        "criteria": quality.get("criteria", []),
        "requires_reasoning": quality.get("requires_reasoning"),
        "has_high_signal_structure": quality.get("has_high_signal_structure"),
        "no_mechanical_drill": quality.get("no_mechanical_drill"),
        "requires_process_evidence": quality.get("requires_process_evidence", []),
        "problem_family_id": quality.get("problem_family_id", ""),
        "core_stem_id": quality.get("core_stem_id", ""),
        "problem_instance_id": quality.get("problem_instance_id", ""),
        "node_alignment": quality.get("node_alignment", {}),
        "identity_basis": quality.get("identity_basis", {}),
        "formal_review_evidence": (
            source.get("formal_review", {}).get("review_evidence", {})
            if isinstance(source.get("formal_review"), dict)
            else {}
        ),
    })
    existing = (
        conn.execute(
            """
            select id
            from question_review_records
            where question_id = ?
              and item_version = ?
              and candidate_sha256 = ?
            limit 1
            """,
            (question_id, item_version, candidate_sha256),
        ).fetchone()
        if question_id
        else None
    )
    if existing:
        record_id = existing["id"]
        conn.execute(
            """
            update question_review_records
            set candidate_id = ?,
                source_type = ?,
                designer_run_id = ?,
                reviewer_run_id = ?,
                review_contract_version = ?,
                review_status = ?,
                rejection_reasons_json = ?,
                criteria_json = ?,
                active_eligible = ?,
                reviewed_at = ?
            where id = ?
            """,
            (
                candidate_id,
                source_type,
                designer_run_id,
                reviewer_run_id,
                contract_version,
                review_status,
                rejection_reasons,
                criteria,
                1 if active_eligible else 0,
                reviewed_at,
                record_id,
            ),
        )
    else:
        record_id = f"QRR-{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            insert into question_review_records(
              id, question_id, candidate_id, item_version, source_type,
              candidate_sha256, designer_run_id, reviewer_run_id,
              review_contract_version, review_status, rejection_reasons_json,
              criteria_json, active_eligible, reviewed_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                question_id,
                candidate_id,
                item_version,
                source_type,
                candidate_sha256,
                designer_run_id,
                reviewer_run_id,
                contract_version,
                review_status,
                rejection_reasons,
                criteria,
                1 if active_eligible else 0,
                reviewed_at,
            ),
        )
    if commit:
        conn.commit()
    return {
        "id": record_id,
        "question_id": question_id,
        "candidate_id": candidate_id,
        "item_version": item_version,
        "source_type": source_type,
        "candidate_sha256": candidate_sha256,
        "review_status": quality.get("review_status", "rejected"),
        "rejection_reasons": quality.get("rejection_reasons", []),
        "active_eligible": active_eligible,
        "reviewed_at": reviewed_at,
    }


def question_review_record_ids_for_questions(conn: sqlite3.Connection, question_ids: list[str]) -> list[str]:
    if not question_ids:
        return []
    placeholders = ",".join("?" for _ in question_ids)
    rows = conn.execute(
        f"""
        select id
        from question_review_records
        where question_id in ({placeholders})
        order by reviewed_at, id
        """,
        question_ids,
    ).fetchall()
    return [row["id"] for row in rows]


def _status_from_attempts_for_repair(rows: list[dict[str, Any]]) -> tuple[str, float, bool, str]:
    max_points = sum(float(row["max_points"]) for row in rows)
    score = sum(float(row["score_points"]) for row in rows)
    ratio = score / max_points if max_points else 0.0
    can_explain = any((row.get("explanation_score") or 0) >= 2 and not _has_high_score_reasoning_gap(row) for row in rows)
    has_blocking = any(row.get("blocking_evidence") for row in rows)
    if has_blocking:
        return "D", round(ratio, 2), can_explain, "Explicit skip/cannot-start evidence."
    if any(_has_high_score_reasoning_gap(row) for row in rows):
        return (
            "C",
            round(ratio, 2),
            False,
            "Final answer or score looked strong, but answer analysis says reasoning/model/steps/check evidence is incomplete or unsound.",
        )
    if ratio >= 0.85 and can_explain and len(rows) >= 2:
        return "A", round(ratio, 2), can_explain, "Repeated direct graded evidence meets mastery threshold."
    if ratio >= 0.85 and can_explain:
        return "B", round(ratio, 2), can_explain, "Single direct graded evidence is strong but not enough for mastery."
    if ratio >= 0.60:
        return "B", round(ratio, 2), can_explain, "Direct graded evidence is unstable but usable."
    return "C", round(ratio, 2), can_explain, "Direct graded evidence is weak; remediate or roll back."


def _has_high_score_reasoning_gap(attempt: dict[str, Any]) -> bool:
    try:
        ratio = float(attempt.get("score_points") or 0) / float(attempt.get("max_points") or 0)
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 0.0
    if attempt.get("result") != "correct" and ratio < 0.85:
        return False
    analysis = attempt.get("answer_analysis") if isinstance(attempt.get("answer_analysis"), dict) else {}
    support = analysis.get("evaluation_support") if isinstance(analysis.get("evaluation_support"), dict) else {}
    return (
        support.get("reasoning_soundness") in {"incomplete", "unsound", "unclear"}
        or support.get("evidence_strength") in {"weak", "insufficient"}
        or support.get("next_evidence_need") not in {None, "", "none"}
    )


def _valid_status_attempts_for_ids(conn: sqlite3.Connection, attempt_ids: list[str]) -> list[dict[str, Any]]:
    if not attempt_ids:
        return []
    placeholders = ",".join("?" for _ in attempt_ids)
    rows = conn.execute(
        f"""
        select a.*
        from attempts a
        join question_items q on q.id = a.question_id
        where a.id in ({placeholders})
          and a.evidence_status = 'active'
          and a.grading_status = 'graded'
          and a.answer_analysis_json <> '{{}}'
          and not (
            q.source_type = 'graph_generated'
            and q.item_version != ?
          )
          and not (
            q.source_type = 'evolved'
            and q.item_version != ?
          )
          and not (
            q.source_type = 'evolved'
            and coalesce(json_extract(q.source_json, '$.evidence_status'), '') = 'invalidated'
          )
        order by a.created_at, a.id
        """,
        [*attempt_ids, question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION],
    ).fetchall()
    return [
        attempt for attempt in (attempt_row_to_dict(row) for row in rows)
        if is_current_usable_attempt_evidence(conn, attempt)
    ]


def _retire_question_review_records_for_invalidated_sources(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select r.id as review_record_id, r.question_id, r.rejection_reasons_json
        from question_review_records r
        join question_items q on q.id = r.question_id
        where q.source_type = 'evolved'
          and (
            json_extract(q.source_json, '$.evidence_status') = 'invalidated'
            or json_extract(q.raw_json, '$.source.evidence_status') = 'invalidated'
          )
          and (r.review_status != 'rejected' or r.active_eligible != 0)
        order by r.question_id, r.id
        """
    ).fetchall()
    repaired = []
    for row in rows:
        reasons = json_load(row["rejection_reasons_json"], [])
        if not isinstance(reasons, list):
            reasons = []
        reasons = sorted(set([*reasons, "invalidated_or_incomplete_source_evidence"]))
        conn.execute(
            """
            update question_review_records
            set review_status = 'rejected',
                active_eligible = 0,
                rejection_reasons_json = ?
            where id = ?
            """,
            (json_dump(reasons), row["review_record_id"]),
        )
        repaired.append({
            "review_record_id": row["review_record_id"],
            "question_id": row["question_id"],
        })
    return repaired


def _superseded_active_question_review_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        with ranked as (
          select
            id,
            question_id,
            item_version,
            source_type,
            candidate_sha256,
            row_number() over (
              partition by question_id, item_version, source_type
              order by reviewed_at desc, id desc
            ) as active_rank,
            count(*) over (
              partition by question_id, item_version, source_type
            ) as active_count
          from question_review_records
          where active_eligible = 1
            and question_id is not null
            and question_id <> ''
        )
        select id, question_id, item_version, source_type, candidate_sha256, active_count
        from ranked
        where active_count > 1
          and active_rank > 1
        order by question_id, item_version, source_type, active_rank
        """
    ).fetchall()
    return [
        {
            "review_record_id": row["id"],
            "question_id": row["question_id"],
            "item_version": row["item_version"],
            "source_type": row["source_type"],
            "candidate_sha256": row["candidate_sha256"],
            "active_count": row["active_count"],
        }
        for row in rows
    ]


def _retire_superseded_question_review_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    superseded = _superseded_active_question_review_records(conn)
    for item in superseded:
        conn.execute(
            "update question_review_records set active_eligible = 0 where id = ?",
            (item["review_record_id"],),
        )
    return superseded


def _active_attempts_on_superseded_bank_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select
          a.id as attempt_id,
          q.id as question_id,
          q.source_type,
          q.item_version
        from attempts a
        join question_items q on q.id = a.question_id
        where a.evidence_status = 'active'
          and (
            (
              q.source_type = 'graph_generated'
              and q.item_version != ?
              and not exists (
                select 1
                from question_bank_version_ledger l
                where l.question_bank_version = q.item_version
              )
            )
            or (q.source_type = 'evolved' and q.item_version != ?)
          )
        order by q.source_type, q.item_version, a.id
        """,
        (question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION),
    ).fetchall()
    return [
        {
            "attempt_id": row["attempt_id"],
            "question_id": row["question_id"],
            "source_type": row["source_type"],
            "item_version": row["item_version"],
        }
        for row in rows
    ]


def _active_attempt_question_node_mismatches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select
          a.id as attempt_id,
          a.question_id,
          a.node_id as attempt_node_id,
          q.node_id as question_node_id
        from attempts a
        join question_items q on q.id = a.question_id
        where a.evidence_status = 'active'
          and a.node_id != q.node_id
        order by a.id
        """
    ).fetchall()
    return [
        {
            "attempt_id": row["attempt_id"],
            "question_id": row["question_id"],
            "attempt_node_id": row["attempt_node_id"],
            "question_node_id": row["question_node_id"],
        }
        for row in rows
    ]


def _invalidate_attempts_with_question_node_mismatch(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _active_attempt_question_node_mismatches(conn)
    invalidated = []
    for row in rows:
        note = (
            f"Attempt {row['attempt_id']} was invalidated because its node_id "
            f"{row['attempt_node_id']} does not match question {row['question_id']} node_id "
            f"{row['question_node_id']}."
        )
        conn.execute(
            """
            update attempts
            set evidence_status = 'invalidated',
                evidence_note = ?
            where id = ?
              and evidence_status = 'active'
            """,
            (note[:500], row["attempt_id"]),
        )
        _invalidate_questions_from_source_attempt(conn, attempt_id=row["attempt_id"], note=note)
        invalidated.append(row)
    return invalidated


def _invalidate_attempts_on_superseded_bank_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _active_attempts_on_superseded_bank_questions(conn)
    invalidated = []
    for row in rows:
        note = (
            f"Question {row['question_id']} was retired because {row['source_type']} "
            f"item_version {row['item_version']} was superseded by the current question bank."
        )
        conn.execute(
            """
            update attempts
            set evidence_status = 'invalidated',
                evidence_note = ?
            where id = ?
              and evidence_status = 'active'
            """,
            (note[:500], row["attempt_id"]),
        )
        _invalidate_questions_from_source_attempt(conn, attempt_id=row["attempt_id"], note=note)
        invalidated.append(row)
    return invalidated


def _question_review_records_for_superseded_bank_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select
          r.id as review_record_id,
          r.question_id,
          q.source_type,
          q.item_version,
          r.review_status,
          r.active_eligible,
          r.rejection_reasons_json
        from question_review_records r
        join question_items q on q.id = r.question_id
        where (
            (
              q.source_type = 'graph_generated'
              and q.item_version != ?
              and not exists (
                select 1
                from question_bank_version_ledger l
                where l.question_bank_version = q.item_version
              )
            )
            or (q.source_type = 'evolved' and q.item_version != ?)
          )
          and (r.review_status != 'rejected' or r.active_eligible != 0)
        order by q.source_type, q.item_version, r.question_id, r.id
        """,
        (question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION),
    ).fetchall()
    return [
        {
            "review_record_id": row["review_record_id"],
            "question_id": row["question_id"],
            "source_type": row["source_type"],
            "item_version": row["item_version"],
            "review_status": row["review_status"],
            "active_eligible": int(row["active_eligible"]),
            "rejection_reasons_json": row["rejection_reasons_json"],
        }
        for row in rows
    ]


def _retire_question_review_records_for_superseded_bank_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _question_review_records_for_superseded_bank_questions(conn)
    retired = []
    for row in rows:
        reasons = json_load(row["rejection_reasons_json"], [])
        if not isinstance(reasons, list):
            reasons = []
        reasons = sorted(set([*reasons, "superseded_question_bank_version"]))
        conn.execute(
            """
            update question_review_records
            set review_status = 'rejected',
                active_eligible = 0,
                rejection_reasons_json = ?
            where id = ?
            """,
            (json_dump(reasons), row["review_record_id"]),
        )
        retired.append({
            "review_record_id": row["review_record_id"],
            "question_id": row["question_id"],
            "source_type": row["source_type"],
            "item_version": row["item_version"],
        })
    return retired


def _normalize_evolved_source_evidence_status(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select q.id, q.source_json, q.raw_json,
               a.id as source_attempt_id,
               a.evidence_status as source_attempt_evidence_status,
               a.grading_status as source_attempt_grading_status,
               a.answer_analysis_json as source_attempt_answer_analysis_json
        from question_items q
        left join attempts a on a.id = json_extract(q.source_json, '$.attempt_id')
        where q.source_type = 'evolved'
        order by q.id
        """
    ).fetchall()
    normalized = []
    for row in rows:
        source = json_load(row["source_json"], {})
        raw = json_load(row["raw_json"], {})
        raw_source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        source_status = source.get("evidence_status")
        raw_source_status = raw_source.get("evidence_status")
        source_valid = _evolved_question_source_attempt_issue(
            conn,
            {
                "id": row["id"],
                "source_type": "evolved",
                "source": source,
                "raw": {"source": raw_source},
            },
        ) is None
        if source_valid:
            if source_status == "invalidated" or raw_source_status == "invalidated":
                continue
            if source_status == "active" and raw_source_status == "active":
                continue
            status = "active"
        else:
            if source_status == "invalidated" and raw_source_status == "invalidated":
                continue
            status = "invalidated"
        source["evidence_status"] = status
        if status == "invalidated":
            source["invalidation_note"] = "Source evidence is missing, inactive, ungraded, or lacks answer analysis."
        raw_source.update(source)
        raw["source"] = raw_source
        if status == "invalidated":
            quality = raw.get("quality") if isinstance(raw.get("quality"), dict) else {}
            quality.update({
                "review_status": "rejected",
                "age_floor": quality.get("age_floor", "incoming_grade_7"),
                "requires_reasoning": quality.get("requires_reasoning", True),
                "no_mechanical_drill": quality.get("no_mechanical_drill", True),
                "rejection_reasons": sorted(set((quality.get("rejection_reasons") or []) + ["invalidated_or_incomplete_source_evidence"])),
            })
            raw["quality"] = quality
            review_check = raw.get("review_agent_check") if isinstance(raw.get("review_agent_check"), dict) else {}
            review_check.update({
                "status": "rejected",
                "rejection_reasons": sorted(set((review_check.get("rejection_reasons") or []) + ["invalidated_or_incomplete_source_evidence"])),
            })
            raw["review_agent_check"] = review_check
        conn.execute(
            "update question_items set source_json = ?, raw_json = ? where id = ?",
            (json_dump(source), json_dump(raw), row["id"]),
        )
        normalized.append({
            "question_id": row["id"],
            "source_attempt_id": row["source_attempt_id"],
            "evidence_status": status,
        })
    return normalized


def _invalidate_attempts_on_invalidated_source_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select a.id as attempt_id, q.id as question_id
        from attempts a
        join question_items q on q.id = a.question_id
        where a.evidence_status = 'active'
          and q.source_type = 'evolved'
          and (
            json_extract(q.source_json, '$.evidence_status') = 'invalidated'
            or json_extract(q.raw_json, '$.source.evidence_status') = 'invalidated'
          )
        order by a.id
        """
    ).fetchall()
    invalidated = []
    for row in rows:
        conn.execute(
            """
            update attempts
            set evidence_status = 'invalidated',
                evidence_note = ?
            where id = ?
            """,
            (
                f"Question {row['question_id']} was retired because its source evidence was invalidated.",
                row["attempt_id"],
            ),
        )
        invalidated.append({
            "attempt_id": row["attempt_id"],
            "question_id": row["question_id"],
        })
    return invalidated


def _repair_learner_node_status_invalid_refs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select node_id, evidence_attempt_ids_json, status_reason,
               mastery_decision_id, graph_version, question_bank_version
        from learner_node_status
        order by node_id
        """
    ).fetchall()
    repaired = []
    for row in rows:
        if row["mastery_decision_id"]:
            authoritative = authoritative_learner_node_status_rows(
                conn,
                graph_version=str(row["graph_version"] or ""),
                question_bank_version=str(row["question_bank_version"] or ""),
            )
            authoritative_row = next(
                (
                    item
                    for item in authoritative
                    if item.get("node_id") == row["node_id"]
                    and item.get("mastery_decision_id") == row["mastery_decision_id"]
                ),
                None,
            )
            if authoritative_row is None:
                conn.execute(
                    "delete from learner_node_status where node_id = ?",
                    (row["node_id"],),
                )
                repaired.append({
                    "node_id": row["node_id"],
                    "action": "deleted_non_authoritative_mastery_status",
                    "mastery_decision_id": row["mastery_decision_id"],
                })
                continue
        evidence_ids_invalid = False
        try:
            original_ids = json_load(row["evidence_attempt_ids_json"], [])
        except (TypeError, ValueError):
            original_ids = []
            evidence_ids_invalid = True
        if not isinstance(original_ids, list):
            original_ids = []
            evidence_ids_invalid = True
        original_ids = [str(item) for item in original_ids if item]
        if evidence_ids_invalid:
            conn.execute(
                "delete from learner_node_status where node_id = ?",
                (row["node_id"],),
            )
            repaired.append({
                "node_id": row["node_id"],
                "action": "deleted_status_invalid_evidence_refs",
                "removed_attempt_ids": [],
            })
            continue
        valid_attempts = [
            attempt for attempt in _valid_status_attempts_for_ids(conn, original_ids)
            if attempt.get("node_id") == row["node_id"]
        ]
        valid_ids = [attempt["id"] for attempt in valid_attempts]
        if valid_ids == original_ids:
            continue
        if not valid_attempts:
            conn.execute("delete from learner_node_status where node_id = ?", (row["node_id"],))
            repaired.append({
                "node_id": row["node_id"],
                "action": "deleted_status",
                "removed_attempt_ids": [attempt_id for attempt_id in original_ids if attempt_id not in valid_ids],
            })
            continue
        removed_ids = [attempt_id for attempt_id in original_ids if attempt_id not in valid_ids]
        conn.execute("delete from learner_node_status where node_id = ?", (row["node_id"],))
        repaired.append({
            "node_id": row["node_id"],
            "action": "deleted_status_partial_invalid_refs",
            "removed_attempt_ids": removed_ids,
        })
    return repaired


def current_learner_node_status_rows(
    conn: sqlite3.Connection,
    *,
    status_codes: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select s.*, n.sequence_band
        from learner_node_status s
        join graph_nodes n on n.id = s.node_id
        order by n.sequence_band, s.updated_at desc, s.node_id
        """
    ).fetchall()
    allowed = set(status_codes or [])
    current_rows: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        original_ids = json_load(data.get("evidence_attempt_ids_json"), [])
        if not isinstance(original_ids, list):
            original_ids = []
        original_ids = [str(item) for item in original_ids if item]
        valid_attempts = [
            attempt for attempt in _valid_status_attempts_for_ids(conn, original_ids)
            if attempt.get("node_id") == row["node_id"]
        ]
        if not valid_attempts:
            continue
        status_code = str(data.get("status_code") or "")
        valid_ids = [attempt["id"] for attempt in valid_attempts]
        if valid_ids != original_ids:
            continue
        if allowed and status_code not in allowed:
            continue
        valid_id_set = set(valid_ids)
        data.update({
            "status_code": status_code,
            "evidence_attempt_ids": valid_ids,
            "evidence_attempt_ids_json": json_dump(valid_ids),
            "is_recomputed_from_current_evidence": False,
            "is_filtered_to_current_evidence": False,
            "invalid_evidence_attempt_ids": [
                attempt_id
                for attempt_id in original_ids
                if attempt_id not in valid_id_set
            ],
        })
        current_rows.append(data)
    return current_rows


def authoritative_learner_node_status_rows(
    conn: sqlite3.Connection,
    *,
    graph_version: str,
    question_bank_version: str,
) -> list[dict[str, Any]]:
    """Return only mastery rows backed by current accepted v5.1 evidence."""
    rows = conn.execute(
        """
        select s.*, md.applied as mastery_applied,
               md.node_id as mastery_node_id,
               md.graph_version as mastery_graph_version,
               md.question_bank_version as mastery_bank_version,
               md.new_status_code as mastery_status_code,
               md.source_attempt_ids_json as mastery_attempt_ids_json,
               md.source_evidence_validation_ids_json as mastery_validation_ids_json,
               md.evaluation_agent_run_id as mastery_evaluation_run_id,
               ar.agent_key as evaluation_agent_key,
               ar.phase as evaluation_phase,
               ar.status as evaluation_run_status
        from learner_node_status s
        join mastery_decisions md on md.id = s.mastery_decision_id
        join agent_runs ar on ar.id = md.evaluation_agent_run_id
        where s.graph_version = ?
          and s.question_bank_version = ?
          and md.graph_version = ?
          and md.question_bank_version = ?
          and md.applied = 1
        order by s.node_id
        """,
        (graph_version, question_bank_version, graph_version, question_bank_version),
    ).fetchall()
    authoritative: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        if any(
            (
                data.get("mastery_node_id") != data.get("node_id"),
                data.get("mastery_status_code") != data.get("status_code"),
                data.get("evaluation_agent_key") != "evaluation_agent",
                data.get("evaluation_phase") != "evaluation_update",
                data.get("evaluation_run_status") != "accepted",
                data.get("updated_by_agent_run_id")
                != data.get("mastery_evaluation_run_id"),
            )
        ):
            continue
        try:
            status_attempt_ids = json_load(data.get("source_attempt_ids_json"), [])
            status_validation_ids = json_load(
                data.get("source_evidence_validation_ids_json"), []
            )
            mastery_attempt_ids = json_load(data.get("mastery_attempt_ids_json"), [])
            mastery_validation_ids = json_load(
                data.get("mastery_validation_ids_json"), []
            )
            legacy_attempt_ids = json_load(data.get("evidence_attempt_ids_json"), [])
        except (TypeError, ValueError):
            continue
        if not all(
            isinstance(value, list)
            for value in (
                status_attempt_ids,
                status_validation_ids,
                mastery_attempt_ids,
                mastery_validation_ids,
                legacy_attempt_ids,
            )
        ):
            continue
        attempt_ids = [str(value) for value in status_attempt_ids if str(value)]
        validation_ids = [str(value) for value in status_validation_ids if str(value)]
        if (
            not attempt_ids
            or not validation_ids
            or attempt_ids != [str(value) for value in mastery_attempt_ids if str(value)]
            or attempt_ids != [str(value) for value in legacy_attempt_ids if str(value)]
            or validation_ids
            != [str(value) for value in mastery_validation_ids if str(value)]
        ):
            continue
        placeholders = ",".join("?" for _ in validation_ids)
        evidence_rows = conn.execute(
            f"""
            select ev.*, a.evidence_status, a.grading_status, a.analysis_status,
                   a.node_id as attempt_node_id,
                   a.question_id as attempt_question_id,
                   a.graph_version as attempt_graph_version,
                   a.question_bank_version as attempt_bank_version,
                   a.flow_step_id,
                   aa.status as assessment_status,
                   aa.attempt_id as assessment_attempt_id,
                   aa.attempt_version as accepted_attempt_version,
                   aa.assessment_version as accepted_assessment_version,
                   aa.assessment_digest_sha256 as accepted_assessment_digest,
                   aa.answer_contract_id, aa.answer_contract_version,
                   aa.answer_contract_digest_sha256,
                   aa.provider_mode as assessment_provider_mode,
                   fs.question_id as step_question_id,
                   fs.node_id as step_node_id,
                   fs.graph_version as step_graph_version,
                   fs.question_bank_version as step_bank_version,
                   fs.answer_contract_id as step_contract_id,
                   fs.answer_contract_version as step_contract_version,
                   fs.answer_contract_digest_sha256 as step_contract_digest,
                   ac.status as contract_status,
                   ac.question_id as contract_question_id,
                   ac.item_version as contract_item_version,
                   ac.graph_version as contract_graph_version,
                   ac.question_bank_version as contract_bank_version,
                   run.agent_key as answer_run_agent_key,
                   run.phase as answer_run_phase,
                   run.status as answer_run_status,
                   run.model_provider as answer_run_provider,
                   run.model_name as answer_run_model,
                   run.model_alias as answer_run_alias
            from evidence_validations ev
            join attempts a on a.id = ev.attempt_id
                           and a.attempt_version = ev.attempt_version
            join attempt_assessments aa on aa.id = ev.assessment_id
            join flow_steps fs on fs.id = a.flow_step_id
            join answer_contracts ac on ac.id = aa.answer_contract_id
            join agent_runs run on run.id = ev.answer_analysis_agent_run_id
            where ev.id in ({placeholders})
            order by ev.id
            """,
            validation_ids,
        ).fetchall()
        if len(evidence_rows) != len(validation_ids):
            continue
        valid_attempt_ids: list[str] = []
        evidence_valid = True
        for evidence in evidence_rows:
            try:
                predicate = json_load(evidence["predicate_result_json"], {})
            except (TypeError, ValueError):
                evidence_valid = False
                break
            if any(
                (
                    evidence["gate_status"] != "passed",
                    not isinstance(predicate, dict) or predicate.get("usable") is not True,
                    evidence["provider_mode"] != "live_model",
                    evidence["assessment_provider_mode"] != "live_model",
                    evidence["evidence_status"] != "active",
                    evidence["grading_status"] != "graded",
                    evidence["analysis_status"] != "valid",
                    evidence["node_id"] != data["node_id"],
                    evidence["attempt_node_id"] != data["node_id"],
                    evidence["step_node_id"] != data["node_id"],
                    evidence["graph_version"] != graph_version,
                    evidence["attempt_graph_version"] != graph_version,
                    evidence["step_graph_version"] != graph_version,
                    evidence["contract_graph_version"] != graph_version,
                    evidence["question_bank_version"] != question_bank_version,
                    evidence["attempt_bank_version"] != question_bank_version,
                    evidence["step_bank_version"] != question_bank_version,
                    evidence["contract_bank_version"] != question_bank_version,
                    evidence["assessment_status"] != "accepted",
                    evidence["assessment_attempt_id"] != evidence["attempt_id"],
                    int(evidence["accepted_attempt_version"] or 0)
                    != int(evidence["attempt_version"] or 0),
                    int(evidence["accepted_assessment_version"] or 0)
                    != int(evidence["assessment_version"] or 0),
                    evidence["accepted_assessment_digest"]
                    != evidence["assessment_digest_sha256"],
                    evidence["step_contract_id"] != evidence["answer_contract_id"],
                    int(evidence["step_contract_version"] or 0)
                    != int(evidence["answer_contract_version"] or 0),
                    evidence["step_contract_digest"]
                    != evidence["answer_contract_digest_sha256"],
                    evidence["contract_status"] != "active",
                    evidence["contract_question_id"] != evidence["question_id"],
                    evidence["contract_question_id"] != evidence["attempt_question_id"],
                    evidence["contract_question_id"] != evidence["step_question_id"],
                    evidence["contract_item_version"] != question_bank_version,
                    evidence["answer_run_agent_key"] != "answer_analysis_agent",
                    evidence["answer_run_phase"] != "answer_analysis",
                    evidence["answer_run_status"] != "accepted",
                )
            ):
                evidence_valid = False
                break
            valid_attempt_ids.append(str(evidence["attempt_id"]))
        if not evidence_valid or sorted(valid_attempt_ids) != sorted(attempt_ids):
            continue
        data["evidence_attempt_ids"] = attempt_ids
        authoritative.append(data)
    return authoritative


def current_learner_node_status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in current_learner_node_status_rows(conn):
        status_code = str(row.get("status_code") or "")
        counts[status_code] = counts.get(status_code, 0) + 1
    return counts


def lineage_integrity_audit(conn: sqlite3.Connection) -> dict[str, Any]:
    learner_status_invalid_refs = []
    for row in conn.execute(
        """
        select node_id, evidence_attempt_ids_json, mastery_decision_id,
               graph_version, question_bank_version
        from learner_node_status
        order by node_id
        """
    ).fetchall():
        evidence_refs_invalid = False
        try:
            evidence_ids = json_load(row["evidence_attempt_ids_json"], [])
        except (TypeError, ValueError):
            evidence_ids = []
            evidence_refs_invalid = True
        if not isinstance(evidence_ids, list):
            evidence_ids = []
            evidence_refs_invalid = True
        evidence_ids = [str(item) for item in evidence_ids if item]
        if evidence_refs_invalid:
            learner_status_invalid_refs.append({
                "node_id": row["node_id"],
                "mastery_decision_id": row["mastery_decision_id"],
                "reason": "invalid_evidence_attempt_ids_json",
                "invalid_attempt_ids": [],
            })
            continue
        if row["mastery_decision_id"]:
            authoritative = authoritative_learner_node_status_rows(
                conn,
                graph_version=str(row["graph_version"] or ""),
                question_bank_version=str(row["question_bank_version"] or ""),
            )
            authoritative_row = next(
                (
                    item
                    for item in authoritative
                    if item.get("node_id") == row["node_id"]
                    and item.get("mastery_decision_id") == row["mastery_decision_id"]
                ),
                None,
            )
            valid_ids = set(
                authoritative_row.get("evidence_attempt_ids") or []
            ) if authoritative_row else set()
            if authoritative_row is None:
                learner_status_invalid_refs.append({
                    "node_id": row["node_id"],
                    "mastery_decision_id": row["mastery_decision_id"],
                    "reason": "mastery_decision_not_authoritative",
                    "invalid_attempt_ids": evidence_ids,
                })
                continue
        else:
            valid_ids = {
                attempt["id"]
                for attempt in _valid_status_attempts_for_ids(conn, evidence_ids)
            }
        invalid_ids = [attempt_id for attempt_id in evidence_ids if attempt_id not in valid_ids]
        if invalid_ids:
            learner_status_invalid_refs.append({
                "node_id": row["node_id"],
                "invalid_attempt_ids": invalid_ids,
            })

    stale_review_rows = conn.execute(
        """
        select r.id as review_record_id, r.question_id
        from question_review_records r
        join question_items q on q.id = r.question_id
        where q.source_type = 'evolved'
          and (
            json_extract(q.source_json, '$.evidence_status') = 'invalidated'
            or json_extract(q.raw_json, '$.source.evidence_status') = 'invalidated'
          )
          and (r.review_status = 'approved' or r.active_eligible = 1)
        order by r.question_id, r.id
        """
    ).fetchall()
    stale_review_records = [
        {"review_record_id": row["review_record_id"], "question_id": row["question_id"]}
        for row in stale_review_rows
    ]

    active_attempt_rows = conn.execute(
        """
        select a.id as attempt_id, q.id as question_id
        from attempts a
        join question_items q on q.id = a.question_id
        where a.evidence_status = 'active'
          and q.source_type = 'evolved'
          and (
            json_extract(q.source_json, '$.evidence_status') = 'invalidated'
            or json_extract(q.raw_json, '$.source.evidence_status') = 'invalidated'
          )
        order by a.id
        """
    ).fetchall()
    active_attempts_on_invalidated_source_questions = [
        {"attempt_id": row["attempt_id"], "question_id": row["question_id"]}
        for row in active_attempt_rows
    ]
    active_attempt_question_node_mismatches = _active_attempt_question_node_mismatches(conn)
    invalid_evolved_source_attempts = []
    evolved_rows = conn.execute(
        """
        select *
        from question_items
        where source_type = 'evolved'
          and item_version = ?
        order by id
        """,
        (question_bank.EVOLVED_ITEM_VERSION,),
    ).fetchall()
    for row in evolved_rows:
        question = row_to_question(row)
        if not _has_active_question_review_record(conn, question):
            continue
        if _evolved_question_source_invalidated(question):
            continue
        issue = _evolved_question_source_attempt_issue(conn, question)
        if issue:
            invalid_evolved_source_attempts.append(issue)
    superseded_review_records = _superseded_active_question_review_records(conn)
    active_attempts_on_superseded_bank_questions = _active_attempts_on_superseded_bank_questions(conn)
    superseded_bank_review_records = _question_review_records_for_superseded_bank_questions(conn)
    issue_count = (
        len(learner_status_invalid_refs)
        + len(stale_review_records)
        + len(active_attempts_on_invalidated_source_questions)
        + len(active_attempt_question_node_mismatches)
        + len(invalid_evolved_source_attempts)
        + len(superseded_review_records)
        + len(active_attempts_on_superseded_bank_questions)
        + len(superseded_bank_review_records)
    )
    return {
        "issue_count": issue_count,
        "learner_status_invalid_refs": learner_status_invalid_refs,
        "stale_review_records": stale_review_records,
        "active_attempts_on_invalidated_source_questions": active_attempts_on_invalidated_source_questions,
        "active_attempt_question_node_mismatches": active_attempt_question_node_mismatches,
        "invalid_evolved_source_attempts": invalid_evolved_source_attempts,
        "superseded_review_records": superseded_review_records,
        "active_attempts_on_superseded_bank_questions": active_attempts_on_superseded_bank_questions,
        "superseded_bank_review_records": superseded_bank_review_records,
    }


def repair_invalidated_lineage(conn: sqlite3.Connection, *, commit: bool = True) -> dict[str, Any]:
    invalidated_superseded_bank_attempts = _invalidate_attempts_on_superseded_bank_questions(conn)
    invalidated_node_mismatches = _invalidate_attempts_with_question_node_mismatch(conn)
    normalized_sources = _normalize_evolved_source_evidence_status(conn)
    invalidated_attempts = _invalidate_attempts_on_invalidated_source_questions(conn)
    repaired_statuses = _repair_learner_node_status_invalid_refs(conn)
    repaired_review_records = _retire_question_review_records_for_invalidated_sources(conn)
    repaired_superseded_review_records = _retire_superseded_question_review_records(conn)
    repaired_superseded_bank_review_records = _retire_question_review_records_for_superseded_bank_questions(conn)
    if commit:
        conn.commit()
    return {
        "normalized_evolved_source_evidence_status": normalized_sources,
        "invalidated_attempts_on_retired_questions": invalidated_attempts,
        "invalidated_attempts_on_superseded_bank_questions": invalidated_superseded_bank_attempts,
        "invalidated_attempts_with_question_node_mismatch": invalidated_node_mismatches,
        "repaired_statuses": repaired_statuses,
        "repaired_review_records": repaired_review_records,
        "repaired_superseded_review_records": repaired_superseded_review_records,
        "repaired_superseded_bank_review_records": repaired_superseded_bank_review_records,
        "remaining_issues": lineage_integrity_audit(conn),
    }


def record_evolution_audit(
    conn: sqlite3.Connection,
    *,
    evolution_event_id: str | None,
    session_id: str | None,
    trigger: str,
    evidence_attempt_ids: list[str],
    before: dict[str, Any],
    after: dict[str, Any],
    created_question_ids: list[str],
    question_review_record_ids: list[str] | None = None,
    no_action_reason: str = "",
    commit: bool = True,
) -> dict[str, Any]:
    audit_id = f"EA-{uuid.uuid4().hex[:12]}"
    created_at = now_iso()
    conn.execute(
        """
        insert into evolution_audits(
          id, evolution_event_id, session_id, trigger, evidence_attempt_ids_json,
          before_json, after_json, created_question_ids_json,
          question_review_record_ids_json, no_action_reason, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            evolution_event_id,
            session_id,
            trigger,
            json_dump(evidence_attempt_ids),
            json_dump(before),
            json_dump(after),
            json_dump(created_question_ids),
            json_dump(question_review_record_ids or []),
            no_action_reason,
            created_at,
        ),
    )
    if commit:
        conn.commit()
    return {
        "id": audit_id,
        "evolution_event_id": evolution_event_id,
        "session_id": session_id,
        "trigger": trigger,
        "evidence_attempt_ids": evidence_attempt_ids,
        "created_question_ids": created_question_ids,
        "question_review_record_ids": question_review_record_ids or [],
        "no_action_reason": no_action_reason,
        "created_at": created_at,
    }


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {declaration}")


def seed_from_assets(conn: sqlite3.Connection, project_root: Path) -> None:
    graph_path = project_root / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_hash = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    graph_version = _graph_lineage_from_seed(graph, graph_hash)
    now = now_iso()

    with conn:
        conn.execute(
            "insert or replace into system_meta(key, value, updated_at) values (?, ?, ?)",
            ("graph_ref", json_dump({
                "path": str(graph_path),
                "version": graph["metadata"]["version"],
                "sha256": graph_hash,
                "lineage": graph_version,
            }), now),
        )
        for node in graph["nodes"]:
            summer = node.get("summer_execution", {})
            if _node_has_attempts(conn, node["id"]):
                conn.execute(
                    """
                    insert or ignore into graph_nodes(
                      id, name, stage, domain, priority, summer_mode, sequence_band,
                      prerequisites_json, unlocks_json, raw_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _node_values(node, summer),
                )
            else:
                conn.execute(
                    """
                    insert or replace into graph_nodes(
                      id, name, stage, domain, priority, summer_mode, sequence_band,
                      prerequisites_json, unlocks_json, raw_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _node_values(node, summer),
                )
        for edge in graph.get("edges", []):
            conn.execute(
                "insert or ignore into graph_edges(from_node_id, to_node_id, relation) values (?, ?, ?)",
                (edge["from"], edge["to"], edge.get("type", "related")),
            )
        for edge in graph.get("prerequisite_edges", []):
            conn.execute(
                "insert or ignore into graph_edges(from_node_id, to_node_id, relation) values (?, ?, ?)",
                (edge["from"], edge["to"], "prerequisite"),
            )

        retire_stale_child_learning_sessions(conn, commit=False)
        repair_invalidated_lineage(conn, commit=False)
        seed_agent_profiles(conn)


def get_active_question_bank_version(conn: sqlite3.Connection) -> str:
    return str(get_active_question_bank_authority(conn)["question_bank_version"])


def get_active_question_bank_authority(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        select *
        from question_bank_version_ledger
        where status = 'active'
        order by activated_at desc, updated_at desc, id desc
        """
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("exactly one active question-bank ledger row is required")
    authority = dict(rows[0])
    required = (
        "id",
        "question_bank_version",
        "graph_version",
        "manifest_id",
        "manifest_sha256",
    )
    missing = [key for key in required if not str(authority.get(key) or "").strip()]
    if missing:
        raise ValueError(
            "active question-bank authority is incomplete: " + ",".join(missing)
        )
    return authority


def is_ledger_managed_question_bank_version(
    conn: sqlite3.Connection,
    question_bank_version: str,
) -> bool:
    """Return whether a bank version has ever entered the formal ledger."""
    version = str(question_bank_version or "").strip()
    if not version:
        return False
    return bool(
        conn.execute(
            """
            select 1
            from question_bank_version_ledger
            where question_bank_version = ?
            limit 1
            """,
            (version,),
        ).fetchone()
    )


def stage_question_bank_version(
    conn: sqlite3.Connection,
    *,
    question_bank_version: str,
    graph_version: str,
    manifest_id: str,
    manifest_sha256: str,
    node_count: int,
    item_count: int,
    commit: bool = True,
) -> dict[str, Any]:
    existing = conn.execute(
        """
        select *
        from question_bank_version_ledger
        where question_bank_version = ?
        order by created_at desc, id desc
        limit 1
        """,
        (question_bank_version,),
    ).fetchone()
    if existing:
        expected_identity = {
            "graph_version": graph_version,
            "manifest_id": manifest_id,
            "manifest_sha256": manifest_sha256,
            "node_count": int(node_count or 0),
            "item_count": int(item_count or 0),
        }
        mismatches = [
            key
            for key, expected in expected_identity.items()
            if existing[key] != expected
        ]
        if mismatches:
            raise ValueError(
                "staged question bank identity conflict: "
                + ",".join(sorted(mismatches))
            )
        if str(existing["status"] or "") not in {"staged", "active"}:
            raise ValueError(
                "question bank version cannot be reused after leaving staged/active status"
            )
        if commit:
            conn.commit()
        return dict(existing)
    now = now_iso()
    ledger_id = f"QBL-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into question_bank_version_ledger(
          id, question_bank_version, graph_version, manifest_id, manifest_sha256,
          node_count, item_count, status, reason, created_at, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, 'staged', ?, ?, ?)
        """,
        (
            ledger_id,
            question_bank_version,
            graph_version,
            manifest_id,
            manifest_sha256,
            int(node_count or 0),
            int(item_count or 0),
            "staged for future active-bank cutover",
            now,
            now,
        ),
    )
    if commit:
        conn.commit()
    return dict(conn.execute("select * from question_bank_version_ledger where id = ?", (ledger_id,)).fetchone())


def activate_question_bank_version(
    conn: sqlite3.Connection,
    *,
    question_bank_version: str,
    expected_current_version: str | None,
    reason: str,
    commit: bool = True,
) -> dict[str, Any]:
    active_rows = conn.execute(
        """
        select question_bank_version
        from question_bank_version_ledger
        where status = 'active'
        order by activated_at desc, updated_at desc, id desc
        """
    ).fetchall()
    if len(active_rows) > 1:
        raise ValueError("multiple active question-bank ledger rows are not allowed")
    current = str(active_rows[0]["question_bank_version"]) if active_rows else None
    if current != expected_current_version:
        raise ValueError(f"active question bank mismatch: expected {expected_current_version}, got {current}")
    staged = conn.execute(
        """
        select *
        from question_bank_version_ledger
        where question_bank_version = ?
          and status in ('staged','active')
        order by created_at desc, id desc
        limit 1
        """,
        (question_bank_version,),
    ).fetchone()
    if not staged:
        raise ValueError(f"question bank version is not staged: {question_bank_version}")
    expected_item_count = int(staged["item_count"] or 0)
    expected_node_count = int(staged["node_count"] or 0)
    if expected_item_count <= 0 or expected_node_count <= 0:
        raise ValueError("question bank activation requires positive item and node counts")
    question_rows = conn.execute(
        """
        select *
        from question_items
        where source_type = 'graph_generated'
          and item_version = ?
        order by node_id, id
        """,
        (question_bank_version,),
    ).fetchall()
    if len(question_rows) != expected_item_count:
        raise ValueError(
            "question bank activation item_count mismatch: "
            f"ledger={expected_item_count}, database={len(question_rows)}"
        )
    actual_node_count = len({str(row["node_id"] or "") for row in question_rows if row["node_id"]})
    if actual_node_count != expected_node_count:
        raise ValueError(
            "question bank activation node_count mismatch: "
            f"ledger={expected_node_count}, database={actual_node_count}"
        )
    qualified_count = sum(
        1
        for row in question_rows
        if is_child_schedulable_question(
            conn,
            row_to_question(row),
            question_bank_version=question_bank_version,
        )
    )
    if qualified_count != expected_item_count:
        raise ValueError(
            "question bank activation requires every item to be reviewed and schedulable: "
            f"qualified={qualified_count}, expected={expected_item_count}"
        )
    if (
        question_bank_version == question_bank.QUESTION_BANK_V12_VERSION
        and (
            int(staged["node_count"] or 0) != question_bank.V12_FULL_BANK_NODE_COUNT
            or int(staged["item_count"] or 0) != question_bank.V12_FULL_BANK_ITEM_COUNT
        )
    ):
        raise ValueError(
            "v12 activation requires full-bank coverage: "
            f"expected {question_bank.V12_FULL_BANK_NODE_COUNT} nodes/"
            f"{question_bank.V12_FULL_BANK_ITEM_COUNT} items, got "
            f"{int(staged['node_count'] or 0)} nodes/{int(staged['item_count'] or 0)} items"
        )
    now = now_iso()
    if staged["status"] != "active":
        conn.execute(
            """
            update question_bank_version_ledger
            set status = 'superseded',
                superseded_at = ?,
                updated_at = ?
            where status = 'active'
            """,
            (now, now),
        )
        conn.execute(
            """
            update question_bank_version_ledger
            set status = 'active',
                activated_at = ?,
                reason = ?,
                updated_at = ?
            where id = ?
            """,
            (now, reason, now, staged["id"]),
        )
    if commit:
        conn.commit()
    return dict(conn.execute("select * from question_bank_version_ledger where question_bank_version = ? and status = 'active'", (question_bank_version,)).fetchone())


def rollback_question_bank_version(
    conn: sqlite3.Connection,
    *,
    to_question_bank_version: str,
    expected_current_version: str,
    reason: str,
    commit: bool = True,
) -> dict[str, Any]:
    current = get_active_question_bank_version(conn)
    if current != expected_current_version:
        raise ValueError(f"active question bank mismatch: expected {expected_current_version}, got {current}")
    target = conn.execute(
        """
        select *
        from question_bank_version_ledger
        where question_bank_version = ?
        order by created_at desc, id desc
        limit 1
        """,
        (to_question_bank_version,),
    ).fetchone()
    if not target:
        raise ValueError(f"rollback target question bank version is unknown: {to_question_bank_version}")
    now = now_iso()
    conn.execute(
        """
        update question_bank_version_ledger
        set status = 'rolled_back',
            rolled_back_at = ?,
            updated_at = ?
        where status = 'active'
        """,
        (now, now),
    )
    conn.execute(
        """
        update question_bank_version_ledger
        set status = 'active',
            activated_at = ?,
            reason = ?,
            updated_at = ?
        where id = ?
        """,
        (now, reason, now, target["id"]),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "select * from question_bank_version_ledger where id = ?",
        (target["id"],),
    ).fetchone()
    result = dict(row)
    result["status"] = "rolled_back"
    return result


def _graph_lineage_from_seed(graph: dict[str, Any], graph_hash: str) -> str:
    metadata = graph.get("metadata") if isinstance(graph, dict) else {}
    version = str((metadata or {}).get("version") or "unknown-graph-version")
    return f"{version}+sha256:{graph_hash}"


def backfill_current_seed_question_lineage(
    conn: sqlite3.Connection,
    *,
    graph_version: str,
    question_bank_version: str = question_bank.QUESTION_BANK_VERSION,
    commit: bool = True,
    dry_run: bool = False,
) -> dict[str, int]:
    rows = conn.execute(
        """
        select *
        from question_items
        where source_type = 'graph_generated'
          and item_version = ?
          and json_extract(source_json, '$.curated_manifest_id') = ?
        order by id
        """,
        (question_bank_version, question_bank.GRAPH_SEED_REVIEW_MANIFEST_ID),
    ).fetchall()
    scanned = 0
    changed = 0
    review_records_rehashed = 0
    skipped_non_seed = 0
    for row in rows:
        scanned += 1
        raw = json_load(row["raw_json"], {})
        source = json_load(row["source_json"], {})
        if (
            not isinstance(raw, dict)
            or not isinstance(source, dict)
            or source.get("curated_manifest_id") != question_bank.GRAPH_SEED_REVIEW_MANIFEST_ID
            or raw.get("source_type") != "graph_generated"
        ):
            skipped_non_seed += 1
            continue
        before_raw = json_dump(raw)
        before_source = json_dump(source)
        raw["source"] = source
        question_bank.apply_question_lineage(
            raw,
            graph_version=graph_version,
            question_bank_version=question_bank_version,
        )
        patched_source = raw.get("source") if isinstance(raw.get("source"), dict) else source
        if before_raw == json_dump(raw) and before_source == json_dump(patched_source):
            continue
        changed += 1
        candidate_sha256 = _digest_json(raw)
        if dry_run:
            active_records = conn.execute(
                """
                select count(*)
                from question_review_records
                where question_id = ?
                  and item_version = ?
                  and source_type = 'graph_generated'
                  and review_status = 'approved'
                  and active_eligible = 1
                """,
                (row["id"], question_bank_version),
            ).fetchone()[0]
            review_records_rehashed += int(active_records)
            continue
        conn.execute(
            "update question_items set source_json = ?, raw_json = ? where id = ?",
            (json_dump(patched_source), json_dump(raw), row["id"]),
        )
        result = conn.execute(
            """
            update question_review_records
            set candidate_sha256 = ?
            where question_id = ?
              and item_version = ?
              and source_type = 'graph_generated'
              and review_status = 'approved'
              and active_eligible = 1
            """,
            (candidate_sha256, row["id"], question_bank_version),
        )
        review_records_rehashed += int(result.rowcount or 0)
    if commit and not dry_run:
        conn.commit()
    return {
        "scanned_seed_questions": scanned,
        "lineage_backfilled_questions": changed,
        "review_records_rehashed": review_records_rehashed,
        "skipped_non_seed_rows": skipped_non_seed,
        "dry_run": 1 if dry_run else 0,
    }


def seed_external_question_bank_v12(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    *,
    project_root: Path,
    runner_receipt: dict[str, Any] | None = None,
    runner_receipt_path: Path | None = None,
    commit: bool = True,
) -> dict[str, int]:
    graph_path = project_root / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    report = question_bank.validate_external_question_bank_v12(manifest, graph)
    blocking = [issue for issue in report["issues"] if issue.get("severity") in {"P0", "P1"}]
    if blocking:
        sample = "; ".join(f"{issue['type']}:{issue.get('node_id', '-')}" for issue in blocking[:5])
        raise ValueError(f"V12 external question bank has blocking validation issues: {sample}")
    if runner_receipt is None and runner_receipt_path is not None:
        runner_receipt = json.loads(Path(runner_receipt_path).read_text(encoding="utf-8"))
    _assert_v12_trusted_live_runner_provenance(
        manifest,
        graph=graph,
        runner_receipt=runner_receipt,
    )
    nodes_by_id = {str(node.get("id") or ""): node for node in graph.get("nodes", []) if node.get("id")}
    counts = {
        "questions_upserted": 0,
        "designer_runs_recorded": 0,
        "reviewer_runs_recorded": 0,
        "node_set_review_runs_recorded": 0,
        "review_records_created": 0,
    }
    for node_entry in manifest.get("nodes") or []:
        node = nodes_by_id[str(node_entry["node_id"])]
        node_artifact = node_entry.get("node_review_artifact") if isinstance(node_entry.get("node_review_artifact"), dict) else {}
        node_candidate_sha256 = question_bank.v12_node_candidate_sha256(node_entry)
        node_set_trigger = f"v12:node_set_review:{manifest.get('manifest_id', '')}:{node_entry['node_id']}:{node_candidate_sha256}"
        existing_node_set_run = conn.execute(
            """
            select id
            from agent_runs
            where agent_key = ?
              and coalesce(session_id, '') = ''
              and phase = 'node_global_finalizer'
              and trigger = ?
            limit 1
            """,
            (question_bank.QUESTION_REVIEWER_AGENT_KEY, node_set_trigger),
        ).fetchone()
        if not existing_node_set_run:
            record_agent_run(
                conn,
                agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
                engine_type="hybrid",
                session_id=None,
                phase="node_global_finalizer",
                trigger=node_set_trigger,
                input_refs={
                    "manifest_id": manifest.get("manifest_id", ""),
                    "question_bank_version": manifest.get("question_bank_version", ""),
                    "graph_version": manifest.get("graph_version", ""),
                    "node_id": node_entry["node_id"],
                    "node_candidate_sha256": node_candidate_sha256,
                    "constituent_review_output_sha256": [
                        review.get("review_output_sha256", "")
                        for review in (node_artifact.get("constituent_reviews") or [])
                        if isinstance(review, dict)
                    ],
                    "aggregate_sha256": (node_artifact.get("aggregation") or {}).get("aggregate_sha256", ""),
                    "semantic_evidence_version": node_artifact.get("semantic_evidence_version", ""),
                    "semantic_evidence_sha256": node_artifact.get("semantic_evidence_sha256", ""),
                },
                prompt_version_id=str(node_artifact.get("prompt_version_id") or question_bank.V12_NODE_SET_REVIEWER_PROMPT_VERSION_ID),
                status="accepted",
                confidence=float(node_artifact.get("confidence") or 0.0),
                output={
                    "verdict": node_artifact.get("verdict", ""),
                    "distribution_scores": node_artifact.get("distribution_scores", {}),
                    "duplicate_groups": node_artifact.get("duplicate_groups", []),
                    "reasons": node_artifact.get("reasons", []),
                    "constituent_reviews": [
                        {
                            "shard_id": review.get("shard_id", ""),
                            "reviewed_slots": review.get("reviewed_slots", []),
                            "review_output_sha256": review.get("review_output_sha256", ""),
                            "batch_raw_response_sha256": review.get("batch_raw_response_sha256", ""),
                            "rendered_prompt_sha256": review.get("rendered_prompt_sha256", ""),
                            "semantic_evidence_version": review.get("semantic_evidence_version", ""),
                            "semantic_evidence_sha256": review.get("semantic_evidence_sha256", ""),
                            "focal_slot_reviews": (
                                (review.get("review_output") or {}).get("focal_slot_reviews", [])
                                if isinstance(review.get("review_output"), dict)
                                else []
                            ),
                        }
                        for review in (node_artifact.get("constituent_reviews") or [])
                        if isinstance(review, dict)
                    ],
                    "aggregation": node_artifact.get("aggregation", {}),
                    "semantic_evidence_version": node_artifact.get("semantic_evidence_version", ""),
                    "semantic_evidence_sha256": node_artifact.get("semantic_evidence_sha256", ""),
                    "semantic_evidence_coverage": node_artifact.get("semantic_evidence_coverage", []),
                    "node_ux_verdict": node_artifact.get("node_ux_verdict", ""),
                    "unprompted_slot_results": node_artifact.get("unprompted_slot_results", []),
                    "instruction_voice_distribution": node_artifact.get("instruction_voice_distribution", []),
                    "repetitive_instruction_clusters": node_artifact.get("repetitive_instruction_clusters", []),
                    "overloaded_slots": node_artifact.get("overloaded_slots", []),
                    "notation_failure_slots": node_artifact.get("notation_failure_slots", []),
                    "dignity_failure_slots": node_artifact.get("dignity_failure_slots", []),
                    "ux_rejected_slots": node_artifact.get("ux_rejected_slots", []),
                    "global_finalizer": {
                        "global_review_output_sha256": (
                            node_artifact.get("global_finalizer") or {}
                        ).get("global_review_output_sha256", ""),
                        "semantic_evidence_version": (
                            node_artifact.get("global_finalizer") or {}
                        ).get("semantic_evidence_version", ""),
                        "semantic_evidence_sha256": (
                            node_artifact.get("global_finalizer") or {}
                        ).get("semantic_evidence_sha256", ""),
                    },
                },
                model_provider=_v12_artifact_model_provider(node_artifact),
                model_name=_v12_artifact_model_name(node_artifact),
                model_alias=_v12_artifact_model_alias(node_artifact),
                model_params=_v12_artifact_model_params(
                    node_artifact,
                    external_run_id_key="external_node_reviewer_run_id",
                    external_run_id=node_artifact.get("node_reviewer_run_id", ""),
                ),
                prompt_template_sha256=str(node_artifact.get("prompt_template_sha256") or ""),
                rendered_prompt_sha256=str(node_artifact.get("rendered_prompt_sha256") or ""),
                response_schema_version=str(node_artifact.get("response_schema_version") or ""),
                response_schema_sha256=str(node_artifact.get("response_schema_sha256") or ""),
                commit=False,
            )
            counts["node_set_review_runs_recorded"] += 1
        for external_item in node_entry.get("items") or []:
            question_item = question_bank.external_v12_item_to_question_item(manifest, node, external_item)
            active_candidate_sha256 = _digest_json(question_item)
            external_candidate_sha256 = question_bank.v12_external_candidate_sha256(external_item)
            designer_artifact = external_item.get("designer_artifact") if isinstance(external_item.get("designer_artifact"), dict) else {}
            review_artifact = external_item.get("review_artifact") if isinstance(external_item.get("review_artifact"), dict) else {}
            designer_trigger = (
                f"v12:question_design:{manifest.get('manifest_id', '')}:{question_item['id']}:{external_candidate_sha256}"
            )
            designer_run = _find_agent_run_by_trigger(
                conn,
                agent_key=question_bank.QUESTION_DESIGNER_AGENT_KEY,
                phase="question_design",
                trigger=designer_trigger,
            )
            if designer_run is None:
                designer_run = record_agent_run(
                    conn,
                    agent_key=question_bank.QUESTION_DESIGNER_AGENT_KEY,
                    engine_type="model",
                    session_id=None,
                    phase="question_design",
                    trigger=designer_trigger,
                    input_refs={
                        "manifest_id": manifest.get("manifest_id", ""),
                        "question_bank_version": manifest.get("question_bank_version", ""),
                        "graph_version": manifest.get("graph_version", ""),
                        "node_id": question_item["node_id"],
                        "slot": external_item.get("slot"),
                        "external_candidate_sha256": external_candidate_sha256,
                    },
                    prompt_version_id=str(designer_artifact.get("prompt_version_id") or question_bank.V12_DESIGNER_PROMPT_VERSION_ID),
                    status="accepted",
                    confidence=1.0,
                    output={
                        "question_id": question_item["id"],
                        "candidate_status": "designed",
                        "external_candidate_sha256": external_candidate_sha256,
                        "design_rationale": designer_artifact.get("design_rationale", ""),
                    },
                    model_provider=_v12_artifact_model_provider(designer_artifact),
                    model_name=_v12_artifact_model_name(designer_artifact),
                    model_alias=_v12_artifact_model_alias(designer_artifact),
                    model_params=_v12_artifact_model_params(
                        designer_artifact,
                        external_run_id_key="external_designer_run_id",
                        external_run_id=designer_artifact.get("designer_run_id", ""),
                    ),
                    prompt_template_sha256=str(designer_artifact.get("prompt_template_sha256") or ""),
                    rendered_prompt_sha256=str(designer_artifact.get("rendered_prompt_sha256") or ""),
                    response_schema_version=str(designer_artifact.get("response_schema_version") or ""),
                    response_schema_sha256=str(designer_artifact.get("response_schema_sha256") or ""),
                    commit=False,
                )
                counts["designer_runs_recorded"] += 1
            reviewer_trigger = (
                f"v12:question_quality_review:{manifest.get('manifest_id', '')}:{question_item['id']}:{active_candidate_sha256}"
            )
            reviewer_run = _find_agent_run_by_trigger(
                conn,
                agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
                phase="question_quality_review",
                trigger=reviewer_trigger,
            )
            if reviewer_run is None:
                reviewer_run = record_agent_run(
                    conn,
                    agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
                    engine_type="model",
                    session_id=None,
                    phase="question_quality_review",
                    trigger=reviewer_trigger,
                    input_refs={
                        "question_id": question_item["id"],
                        "candidate_sha256": active_candidate_sha256,
                        "external_candidate_sha256": external_candidate_sha256,
                        "manifest_id": manifest.get("manifest_id", ""),
                        "question_bank_version": manifest.get("question_bank_version", ""),
                        "graph_version": manifest.get("graph_version", ""),
                        "node_id": question_item["node_id"],
                        "slot": external_item.get("slot"),
                    },
                    prompt_version_id=str(review_artifact.get("prompt_version_id") or question_bank.V12_REVIEWER_PROMPT_VERSION_ID),
                    status="accepted",
                    confidence=float(review_artifact.get("confidence") or 1.0),
                    output={
                        "review_status": "approved",
                        "active_eligible": True,
                        "scores": review_artifact.get("scores", {}),
                        "reasons": review_artifact.get("reasons", []),
                        "reviewer_evidence": review_artifact.get("reviewer_evidence", {}),
                        "semantic_evidence_version": review_artifact.get("semantic_evidence_version", ""),
                        "semantic_evidence_sha256": review_artifact.get("semantic_evidence_sha256", ""),
                        "semantic_evidence": review_artifact.get("semantic_evidence", {}),
                    },
                    model_provider=_v12_artifact_model_provider(review_artifact),
                    model_name=_v12_artifact_model_name(review_artifact),
                    model_alias=_v12_artifact_model_alias(review_artifact),
                    model_params=_v12_artifact_model_params(
                        review_artifact,
                        external_run_id_key="external_reviewer_run_id",
                        external_run_id=review_artifact.get("reviewer_run_id", ""),
                    ),
                    prompt_template_sha256=str(review_artifact.get("prompt_template_sha256") or ""),
                    rendered_prompt_sha256=str(review_artifact.get("rendered_prompt_sha256") or ""),
                    response_schema_version=str(review_artifact.get("response_schema_version") or ""),
                    response_schema_sha256=str(review_artifact.get("response_schema_sha256") or ""),
                    commit=False,
                )
                counts["reviewer_runs_recorded"] += 1
            upsert_question(
                conn,
                question_item,
                designer_run_id=designer_run["id"],
                reviewer_run_id=reviewer_run["id"],
            )
            counts["questions_upserted"] += 1
            review_rows = conn.execute(
                """
                select count(*)
                from question_review_records
                where question_id = ?
                  and item_version = ?
                  and source_type = 'graph_generated'
                  and reviewer_run_id = ?
                """,
                (question_item["id"], question_item["item_version"], reviewer_run["id"]),
            ).fetchone()[0]
            counts["review_records_created"] += int(review_rows)
    if commit:
        conn.commit()
    return counts


V12_LOCAL_PILOT_BANKS = (
    (
        "data/question_banks/math/math_question_bank_v12_pilot_eq_denom_v4.json",
        "data/question_banks/math/math_question_bank_v12_pilot_eq_denom_v4.json.runner_receipt.json",
    ),
    (
        "data/question_banks/math/math_question_bank_v12_pilot_solution_habit_v2.json",
        "data/question_banks/math/math_question_bank_v12_pilot_solution_habit_v2.json.runner_receipt.json",
    ),
)


def seed_local_v12_pilot_question_banks(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    activate: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    """Load reviewed local v12 pilot banks without claiming full v12 coverage."""
    loaded: list[dict[str, Any]] = []
    total_counts = {
        "questions_upserted": 0,
        "designer_runs_recorded": 0,
        "reviewer_runs_recorded": 0,
        "node_set_review_runs_recorded": 0,
        "review_records_created": 0,
    }
    for manifest_rel, receipt_rel in V12_LOCAL_PILOT_BANKS:
        manifest_path = project_root / manifest_rel
        receipt_path = project_root / receipt_rel
        if not manifest_path.is_file() or not receipt_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        counts = seed_external_question_bank_v12(
            conn,
            manifest,
            project_root=project_root,
            runner_receipt=receipt,
            commit=False,
        )
        for key, value in counts.items():
            total_counts[key] = total_counts.get(key, 0) + int(value or 0)
        loaded.append({
            "manifest_path": manifest_rel,
            "receipt_path": receipt_rel,
            "manifest_id": str(manifest.get("manifest_id") or ""),
            "manifest_sha256": question_bank.v12_canonical_manifest_sha256(manifest),
            "question_bank_version": str(manifest.get("question_bank_version") or ""),
            "graph_version": str(manifest.get("graph_version") or ""),
            "node_ids": [str(node.get("node_id") or "") for node in manifest.get("nodes") or []],
            "item_count": sum(len(node.get("items") or []) for node in manifest.get("nodes") or []),
        })
    if not loaded:
        if commit:
            conn.commit()
        return {"loaded": [], "counts": total_counts, "staged": None, "activated": None}

    graph_version = loaded[0]["graph_version"]
    active_before = get_active_question_bank_version(conn)
    staged = stage_question_bank_version(
        conn,
        question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
        graph_version=graph_version,
        manifest_id="local_v12_pilot_bundle",
        manifest_sha256=_digest_json({
            "bundle": "local_v12_pilot_bundle",
            "pilots": loaded,
        }),
        node_count=len({node_id for item in loaded for node_id in item["node_ids"]}),
        item_count=sum(int(item["item_count"] or 0) for item in loaded),
        commit=False,
    )
    activated = None
    if commit:
        conn.commit()
    return {
        "loaded": loaded,
        "counts": total_counts,
        "staged": staged,
        "activated": activated,
        "active_question_bank_version": active_before,
        "activation_blocked": "pilot_stage_only" if activate else "",
    }


def _assert_v12_trusted_live_runner_provenance(
    manifest: dict[str, Any],
    *,
    graph: dict[str, Any],
    runner_receipt: dict[str, Any] | None,
) -> None:
    if manifest.get("status") != "draft_live_model":
        raise ValueError("V12 active seed requires trusted live runner provenance: manifest status must be draft_live_model")
    for node_entry in manifest.get("nodes") or []:
        for item in node_entry.get("items") or []:
            item_id = str(item.get("id") or "")
            designer_artifact = item.get("designer_artifact") if isinstance(item.get("designer_artifact"), dict) else {}
            review_artifact = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
            for role, artifact in (("designer", designer_artifact), ("reviewer", review_artifact)):
                if artifact.get("provider_mode") != "live_model":
                    raise ValueError(f"V12 active seed requires trusted live runner provenance: {item_id}:{role}:provider_mode")
                if artifact.get("artifact_role") != role:
                    raise ValueError(f"V12 active seed requires trusted live runner provenance: {item_id}:{role}:artifact_role")
    if not isinstance(runner_receipt, dict):
        raise ValueError("V12 active seed requires trusted live runner receipt: missing runner receipt")
    if runner_receipt.get("schema_version") != question_bank.V12_RUNNER_RECEIPT_SCHEMA_VERSION:
        raise ValueError("V12 active seed requires trusted live runner receipt: schema_version")
    if runner_receipt.get("runner_mode") != "live" or runner_receipt.get("status") != "completed":
        raise ValueError("V12 active seed requires trusted live runner receipt: live completed status")
    if runner_receipt.get("canonical_manifest_sha256") != question_bank.v12_canonical_manifest_sha256(manifest):
        raise ValueError("V12 active seed requires trusted live runner receipt: manifest hash mismatch")
    if runner_receipt.get("graph_version") != manifest.get("graph_version"):
        raise ValueError("V12 active seed requires trusted live runner receipt: graph_version mismatch")
    if runner_receipt.get("question_bank_version") != manifest.get("question_bank_version"):
        raise ValueError("V12 active seed requires trusted live runner receipt: question_bank_version mismatch")
    expected_semantic_policy = question_bank.v12_semantic_evidence_policy()
    if runner_receipt.get("semantic_evidence_policy") != expected_semantic_policy:
        raise ValueError("V12 active seed requires trusted live runner receipt: semantic_evidence_policy")
    expected_shards = question_bank.v12_expected_node_set_review_shards()
    expected_shard_policy = {
        "node_review_concurrency": question_bank.V12_NODE_SET_REVIEW_ACTIVATION_CONCURRENCY,
        "node_set_review_shard_size": question_bank.V12_NODE_SET_REVIEW_SHARD_SIZE,
        "node_set_review_expected_shards": len(expected_shards),
        "global_finalizer_concurrency": 1,
    }
    manifest_execution_policy = manifest.get("execution_policy") if isinstance(manifest.get("execution_policy"), dict) else {}
    for key, value in expected_shard_policy.items():
        if key in manifest_execution_policy and manifest_execution_policy.get(key) != value:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: manifest:execution_policy:{key}")
    receipt_execution_policy = runner_receipt.get("execution_policy") if isinstance(runner_receipt.get("execution_policy"), dict) else {}
    for key, value in expected_shard_policy.items():
        if receipt_execution_policy.get(key) != value:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: runner_receipt:execution_policy:{key}")
    receipt_nodes = {}
    for receipt_node in runner_receipt.get("nodes") or []:
        if not isinstance(receipt_node, dict):
            continue
        receipt_nodes[str(receipt_node.get("node_id") or "")] = receipt_node
    manifest_nodes = [
        node for node in manifest.get("nodes") or [] if isinstance(node, dict)
    ]
    receipt_prompt_schema_hashes = (
        runner_receipt.get("prompt_schema_hashes")
        if isinstance(runner_receipt.get("prompt_schema_hashes"), dict)
        else {}
    )
    expected_verifier_role_hashes = {
        "node_set_global_verifier_prompt_template_sha256": sorted({
            str(((node.get("node_review_artifact") or {}).get("global_verifier") or {}).get("prompt_template_sha256") or "")
            for node in manifest_nodes
            if str(((node.get("node_review_artifact") or {}).get("global_verifier") or {}).get("prompt_template_sha256") or "")
        }),
        "node_set_global_verifier_response_schema_sha256": sorted({
            str(((node.get("node_review_artifact") or {}).get("global_verifier") or {}).get("response_schema_sha256") or "")
            for node in manifest_nodes
            if str(((node.get("node_review_artifact") or {}).get("global_verifier") or {}).get("response_schema_sha256") or "")
        }),
    }
    for key, expected_hashes in expected_verifier_role_hashes.items():
        if receipt_prompt_schema_hashes.get(key) != expected_hashes:
            raise ValueError(
                f"V12 active seed requires trusted live runner receipt: prompt_schema_hashes:{key}:mismatch"
            )
    graph_order = [
        str(node.get("id"))
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    ]
    manifest_node_ids = [str(node.get("node_id") or "") for node in manifest_nodes]
    full_inventory = (
        len(manifest_nodes) == question_bank.V12_FULL_BANK_NODE_COUNT
        and manifest_node_ids == graph_order
    )
    if full_inventory:
        cross_node_authority = (
            runner_receipt.get("cross_node_review_authority")
            if isinstance(runner_receipt.get("cross_node_review_authority"), dict)
            else {}
        )
        authority_payload = {
            key: value
            for key, value in cross_node_authority.items()
            if key != "commitment_sha256"
        }
        if (
            cross_node_authority.get("node_count")
            != question_bank.V12_FULL_BANK_NODE_COUNT
            or cross_node_authority.get("item_count")
            != question_bank.V12_FULL_BANK_ITEM_COUNT
            or cross_node_authority.get("ordered_node_ids") != graph_order
            or cross_node_authority.get("commitment_sha256")
            != _v12_sorted_digest_json(authority_payload)
        ):
            raise ValueError(
                "V12 active seed requires trusted live runner receipt: full_bank_cross_node_authority"
            )
    for node_index, node_entry in enumerate(manifest_nodes):
        node_id = str(node_entry.get("node_id") or "")
        artifact = node_entry.get("node_review_artifact") if isinstance(node_entry.get("node_review_artifact"), dict) else {}
        if artifact.get("provider_mode") != "live_model":
            raise ValueError(f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:provider_mode")
        if (
            artifact.get("artifact_role") != "node_set_review"
            or artifact.get("agent_key") != question_bank.QUESTION_REVIEWER_AGENT_KEY
            or artifact.get("phase") != "node_global_finalizer"
            or artifact.get("contract_key") != "math_question_bank_v12_node_set_global_finalizer"
            or artifact.get("contract_version") != question_bank.V12_GLOBAL_FINALIZER_CONTRACT_VERSION
            or artifact.get("prompt_version_id") != question_bank.V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID
            or artifact.get("response_schema_version") != question_bank.V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION
            or artifact.get("semantic_evidence_version") != question_bank.V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION
            or artifact.get("verdict") != "approved"
            or artifact.get("node_ux_verdict") != "approved"
            or any(artifact.get(key) for key in (
                "overloaded_slots",
                "notation_failure_slots",
                "dignity_failure_slots",
                "ux_rejected_slots",
                "invalid_difficulty_vector_slots",
                "gate_errors",
            ))
            or int(artifact.get("item_count") or 0) != question_bank.QUESTIONS_PER_GRAPH_NODE
            or int(artifact.get("node_local_mainline_count") or 0) < question_bank.V12_MAINLINE_ROLE_MINIMUM
            or int(artifact.get("controlled_stretch_count") or 0) > question_bank.V12_MAX_CONTROLLED_STRETCH_PER_NODE
        ):
            raise ValueError(f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review")
        node_candidate_sha256 = question_bank.v12_node_candidate_sha256(node_entry)
        if artifact.get("node_candidate_sha256") != node_candidate_sha256:
            raise ValueError(f"V12 active seed requires trusted live runner provenance: {node_id}:node_candidate_hash")
        artifact_execution_policy = artifact.get("execution_policy") if isinstance(artifact.get("execution_policy"), dict) else {}
        for key, value in expected_shard_policy.items():
            if artifact_execution_policy.get(key) != value:
                raise ValueError(f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:execution_policy:{key}")
        receipt_node = receipt_nodes.get(node_id)
        if not receipt_node:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: missing node receipt:{node_id}")
        if full_inventory:
            contexts = (
                receipt_node.get("cross_node_summary_contexts")
                if isinstance(receipt_node.get("cross_node_summary_contexts"), dict)
                else {}
            )
            generation_bundle = question_bank.v12_cross_node_summary_bundle(
                focal_node_id=node_id,
                source_node_entries=manifest_nodes[:node_index],
                graph=graph,
                registry_scope="graph_ordered_completed_predecessor_prefix",
            )
            generation_context = {
                **generation_bundle["context"],
                "required_predecessor_node_ids": graph_order[:node_index],
                "missing_predecessor_node_ids": [],
                "predecessor_prefix_complete": True,
            }
            full_audit_context = question_bank.v12_cross_node_summary_bundle(
                focal_node_id=node_id,
                source_node_entries=[
                    candidate
                    for candidate in manifest_nodes
                    if str(candidate.get("node_id") or "") != node_id
                ],
                graph=graph,
                registry_scope="full_completed_bank_excluding_focal_node",
            )["context"]
            if contexts.get("generation") != generation_context:
                raise ValueError(
                    f"V12 active seed requires trusted live runner receipt: {node_id}:generation_cross_node_context"
                )
            if contexts.get("full_bank_audit") != full_audit_context:
                raise ValueError(
                    f"V12 active seed requires trusted live runner receipt: {node_id}:full_bank_cross_node_audit"
                )
            budget = (
                receipt_node.get("model_budget_commitment")
                if isinstance(receipt_node.get("model_budget_commitment"), dict)
                else {}
            )
            if (
                budget.get("schema_version")
                != question_bank.V12_MODEL_BUDGET_SCHEMA_VERSION
                or budget.get("node_id") != node_id
                or not str(budget.get("counter_chain_head_sha256") or "")
                or not str(budget.get("integrity_sha256") or "")
            ):
                raise ValueError(
                    f"V12 active seed requires trusted live runner receipt: {node_id}:model_budget_commitment"
                )
        if receipt_node.get("node_candidate_sha256") != node_candidate_sha256:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: node candidate hash mismatch:{node_id}")
        semantic_commitment = question_bank.v12_node_semantic_evidence_commitment(node_entry)
        if receipt_node.get("semantic_evidence_commitment_version") != semantic_commitment["version"]:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:semantic_evidence_commitment_version")
        if receipt_node.get("semantic_evidence_commitment_sha256") != semantic_commitment["sha256"]:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:semantic_evidence_commitment_sha256")
        repair_chain_hash = str(receipt_node.get("repair_chain_hash") or "")
        if not repair_chain_hash:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:repair_chain_hash")
        expected_node_receipt = _v12_completed_node_receipt_for_seed(
            node_entry=node_entry,
            graph_version=str(manifest.get("graph_version") or ""),
            repair_chain_hash=repair_chain_hash,
            cross_node_summary_contexts=(
                receipt_node.get("cross_node_summary_contexts")
                if isinstance(receipt_node.get("cross_node_summary_contexts"), dict)
                else None
            ),
            model_budget_commitment=(
                receipt_node.get("model_budget_commitment")
                if isinstance(receipt_node.get("model_budget_commitment"), dict)
                and receipt_node.get("model_budget_commitment")
                else None
            ),
            include_cross_node_context_commitment=(
                "cross_node_summary_contexts" in receipt_node
                or "cross_node_context_commitment_sha256" in receipt_node
            ),
        )
        receipt_hash = str(receipt_node.get("completed_node_receipt_sha256") or "")
        if not receipt_hash:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:completed_node_receipt_sha256")
        if receipt_hash != expected_node_receipt["receipt_sha256"]:
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:completed_node_receipt_sha256:mismatch")
        reuse = node_entry.get("_runner_reuse") if isinstance(node_entry.get("_runner_reuse"), dict) else {}
        if receipt_node.get("reused_from_checkpoint"):
            if reuse and receipt_hash != str(reuse.get("completed_node_receipt_sha256") or ""):
                raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:completed_node_receipt_sha256:mismatch")
        receipt_role = receipt_node.get("node_set_review") if isinstance(receipt_node.get("node_set_review"), dict) else {}
        for key in (
            "agent_key",
            "phase",
            "artifact_role",
            "provider_mode",
            "model_provider",
            "model_name",
            "model_alias",
            "structured_json_mode",
            "prompt_template_sha256",
            "rendered_prompt_sha256",
            "response_schema_version",
            "response_schema_sha256",
            "batch_raw_response_sha256",
            "contract_key",
            "contract_version",
            "prompt_version_id",
            "node_candidate_sha256",
            "verdict",
            "semantic_evidence_version",
            "semantic_evidence_sha256",
        ):
            if not str(artifact.get(key) or "").strip():
                raise ValueError(f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:{key}")
            if receipt_role.get(key) != artifact.get(key):
                raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:{key}:mismatch")
        artifact_reviews = artifact.get("constituent_reviews") if isinstance(artifact.get("constituent_reviews"), list) else []
        receipt_reviews = receipt_role.get("constituent_reviews") if isinstance(receipt_role.get("constituent_reviews"), list) else []
        if len(artifact_reviews) != len(receipt_reviews) or len(artifact_reviews) != len(expected_shards):
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:constituent_reviews")
        for index, artifact_review in enumerate(artifact_reviews):
            receipt_review = receipt_reviews[index] if index < len(receipt_reviews) and isinstance(receipt_reviews[index], dict) else {}
            if not isinstance(artifact_review, dict):
                raise ValueError(f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:constituent:{index}")
            for key in (
                "agent_key",
                "phase",
                "artifact_role",
                "provider_mode",
                "model_provider",
                "model_name",
                "model_alias",
                "structured_json_mode",
                "prompt_template_sha256",
                "rendered_prompt_sha256",
                "response_schema_version",
                "response_schema_sha256",
                "batch_raw_response_sha256",
                "contract_key",
                "contract_version",
                "prompt_version_id",
                "shard_id",
                "review_output_sha256",
                "node_candidate_sha256",
                "semantic_evidence_version",
                "semantic_evidence_sha256",
            ):
                if not str(artifact_review.get(key) or "").strip():
                    raise ValueError(f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:constituent:{index}:{key}")
                if receipt_review.get(key) != artifact_review.get(key):
                    raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:constituent:{index}:{key}:mismatch")
            if list(receipt_review.get("reviewed_slots") or []) != list(artifact_review.get("reviewed_slots") or []):
                raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:constituent:{index}:reviewed_slots:mismatch")
            if list(artifact_review.get("reviewed_slots") or []) != expected_shards[index]:
                raise ValueError(f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:constituent:{index}:shard_policy")
            if (
                artifact_review.get("agent_key") != question_bank.QUESTION_REVIEWER_AGENT_KEY
                or artifact_review.get("phase") != "node_set_review"
                or artifact_review.get("artifact_role") != "node_set_focal_review_shard"
                or artifact_review.get("contract_key") != "math_question_bank_v12_node_set_focal_review"
                or artifact_review.get("contract_version") != question_bank.V12_NODE_SET_FOCAL_REVIEWER_CONTRACT_VERSION
                or artifact_review.get("prompt_version_id") != question_bank.V12_NODE_SET_FOCAL_REVIEWER_PROMPT_VERSION_ID
                or artifact_review.get("response_schema_version") != question_bank.V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION
                or artifact_review.get("semantic_evidence_version") != question_bank.V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION
                or artifact_review.get("provider_mode") != "live_model"
            ):
                raise ValueError(
                    f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:constituent:{index}:identity"
                )
        global_verifier = artifact.get("global_verifier") if isinstance(artifact.get("global_verifier"), dict) else {}
        receipt_global_verifier = (
            receipt_role.get("global_verifier")
            if isinstance(receipt_role.get("global_verifier"), dict)
            else {}
        )
        if not receipt_global_verifier:
            raise ValueError(
                f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:global_verifier:missing"
            )
        expected_verifier_identity = {
            "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
            "phase": "node_global_verifier",
            "artifact_role": "node_set_global_verifier",
            "contract_key": "math_question_bank_v12_node_set_global_verifier",
            "contract_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_CONTRACT_VERSION,
            "prompt_version_id": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_VERSION_ID,
            "response_schema_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_VERSION,
            "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_SEMANTIC_EVIDENCE_VERSION,
            "provider_mode": "live_model",
            "prompt_template_sha256": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_TEMPLATE_SHA256,
            "response_schema_sha256": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_SHA256,
            "request_lineage_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_REQUEST_LINEAGE_VERSION,
        }
        for key, value in expected_verifier_identity.items():
            if global_verifier.get(key) != value:
                raise ValueError(
                    f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:{key}"
                )
        for key in (
            "model_provider",
            "model_name",
            "model_alias",
            "structured_json_mode",
            "rendered_prompt_sha256",
            "batch_raw_response_sha256",
            "trusted_context_sha256",
            "untrusted_payload_sha256",
            "request_options_sha256",
            "request_input_sha256",
            "request_lineage_sha256",
            "model_judgment_output_sha256",
        ):
            if not str(global_verifier.get(key) or "").strip():
                raise ValueError(
                    f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:{key}"
                )
        expected_constituent_semantic_hashes = [
            review.get("semantic_evidence_sha256") or ""
            for review in artifact_reviews
            if isinstance(review, dict)
        ]
        if global_verifier.get("node_candidate_sha256") != node_candidate_sha256:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:node_candidate_sha256"
            )
        if global_verifier.get("constituent_semantic_evidence_sha256") != expected_constituent_semantic_hashes:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:constituents"
            )
        verifier_judgment = (
            global_verifier.get("model_judgment_output")
            if isinstance(global_verifier.get("model_judgment_output"), dict)
            else {}
        )
        expected_verifier_judgment_sha256 = _v12_sorted_digest_json(verifier_judgment)
        if global_verifier.get("model_judgment_output_sha256") != expected_verifier_judgment_sha256:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:model_judgment_output_sha256"
            )
        verifier_shards = (
            global_verifier.get("shard_artifacts")
            if isinstance(global_verifier.get("shard_artifacts"), list)
            else []
        )
        receipt_verifier_shards = (
            receipt_global_verifier.get("shard_artifacts")
            if isinstance(receipt_global_verifier.get("shard_artifacts"), list)
            else []
        )
        expected_verifier_shards = question_bank.v12_expected_global_verifier_shards()
        if (
            [
                list(shard.get("reviewed_slots") or [])
                for shard in verifier_shards
                if isinstance(shard, dict)
            ] != expected_verifier_shards
            or len(receipt_verifier_shards) != len(verifier_shards)
        ):
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:shard_coverage"
            )
        verifier_shard_semantic_hashes: list[str] = []
        top_level_verifier_route = {
            "model_provider": str(global_verifier.get("model_provider") or ""),
            "model_name": str(global_verifier.get("model_name") or ""),
            "model_alias": str(global_verifier.get("model_alias") or ""),
            "structured_json_mode": str(global_verifier.get("structured_json_mode") or ""),
        }
        verifier_shard_receipt_fields = (
            "agent_key",
            "phase",
            "artifact_role",
            "provider_mode",
            "model_provider",
            "model_name",
            "model_alias",
            "structured_json_mode",
            "prompt_template_sha256",
            "rendered_prompt_sha256",
            "response_schema_version",
            "response_schema_sha256",
            "batch_raw_response_sha256",
            "contract_key",
            "contract_version",
            "prompt_version_id",
            "semantic_evidence_version",
            "semantic_evidence_sha256",
            "pipeline_stage",
            "stage_attempt",
            "shard_id",
            "reviewed_slots",
            "compact_index_sha256",
            "node_candidate_sha256",
            "request_lineage_version",
            "trusted_context_sha256",
            "untrusted_payload_sha256",
            "request_options_sha256",
            "request_input_sha256",
            "request_lineage_sha256",
            "model_judgment_output_sha256",
            "constituent_semantic_evidence_sha256",
        )
        for index, verifier_shard in enumerate(verifier_shards):
            if not isinstance(verifier_shard, dict):
                raise ValueError(
                    f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:shard:{index}"
                )
            receipt_shard = (
                receipt_verifier_shards[index]
                if index < len(receipt_verifier_shards)
                and isinstance(receipt_verifier_shards[index], dict)
                else {}
            )
            reviewed_slots = expected_verifier_shards[index]
            expected_shard_identity = {
                "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
                "phase": "node_global_verifier",
                "artifact_role": "node_set_global_verifier_shard",
                "contract_key": "math_question_bank_v12_node_set_global_verifier",
                "contract_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_CONTRACT_VERSION,
                "prompt_version_id": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_VERSION_ID,
                "response_schema_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_VERSION,
                "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_SHARD_SEMANTIC_EVIDENCE_VERSION,
                "provider_mode": "live_model",
                "prompt_template_sha256": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_PROMPT_TEMPLATE_SHA256,
                "response_schema_sha256": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_SHA256,
                "request_lineage_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_REQUEST_LINEAGE_VERSION,
                "reviewed_slots": reviewed_slots,
                "shard_id": question_bank.v12_node_set_review_shard_id(reviewed_slots),
            }
            for key, value in expected_shard_identity.items():
                if verifier_shard.get(key) != value:
                    raise ValueError(
                        f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:shard:{index}:{key}"
                    )
            for key, value in top_level_verifier_route.items():
                if verifier_shard.get(key) != value:
                    raise ValueError(
                        f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:shard:{index}:{key}"
                    )
            if (
                verifier_shard.get("node_candidate_sha256") != node_candidate_sha256
                or verifier_shard.get("constituent_semantic_evidence_sha256")
                != expected_constituent_semantic_hashes
            ):
                raise ValueError(
                    f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:shard:{index}:subject"
                )
            shard_judgment = (
                verifier_shard.get("model_judgment_output")
                if isinstance(verifier_shard.get("model_judgment_output"), dict)
                else {}
            )
            if (
                verifier_shard.get("model_judgment_output_sha256")
                != _v12_sorted_digest_json(shard_judgment)
                or shard_judgment.get("reviewed_slots") != reviewed_slots
                or [
                    int(entry.get("slot") or 0)
                    for entry in shard_judgment.get("item_classifications") or []
                    if isinstance(entry, dict)
                ] != reviewed_slots
            ):
                raise ValueError(
                    f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:shard:{index}:judgment"
                )
            expected_shard_semantic = _v12_sorted_digest_json({
                "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_SHARD_SEMANTIC_EVIDENCE_VERSION,
                "node_candidate_sha256": node_candidate_sha256,
                "constituent_semantic_evidence_sha256": expected_constituent_semantic_hashes,
                "reviewed_slots": reviewed_slots,
                "compact_index_sha256": verifier_shard.get("compact_index_sha256") or "",
                "model_judgment_output_sha256": verifier_shard.get("model_judgment_output_sha256") or "",
            })
            if verifier_shard.get("semantic_evidence_sha256") != expected_shard_semantic:
                raise ValueError(
                    f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:shard:{index}:semantic_evidence_sha256"
                )
            for key in verifier_shard_receipt_fields:
                if receipt_shard.get(key) != verifier_shard.get(key):
                    raise ValueError(
                        f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:global_verifier:shard:{index}:{key}:mismatch"
                    )
            verifier_shard_semantic_hashes.append(
                str(verifier_shard.get("semantic_evidence_sha256") or "")
            )
        expected_verifier_shard_artifacts_sha256 = _v12_sorted_digest_json(
            verifier_shards
        )
        expected_verifier_shard_route_tuples = (
            question_bank.v12_global_verifier_shard_route_tuples(verifier_shards)
        )
        expected_verifier_shard_route_tuples_sha256 = _v12_sorted_digest_json(
            expected_verifier_shard_route_tuples
        )
        try:
            expected_verifier_judgment = (
                question_bank.v12_aggregate_global_verifier_shard_judgments(
                    node_entry,
                    verifier_shards,
                    graph_version=str(verifier_judgment.get("graph_version") or ""),
                )
            )
        except ValueError as exc:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:aggregate:{exc}"
            ) from exc
        if verifier_judgment != expected_verifier_judgment:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:aggregate_judgment"
            )
        if (
            global_verifier.get("shard_policy_version")
            != question_bank.V12_NODE_SET_GLOBAL_VERIFIER_SHARD_POLICY_VERSION
            or global_verifier.get("expected_shards") != expected_verifier_shards
            or global_verifier.get("shard_artifacts_sha256")
            != expected_verifier_shard_artifacts_sha256
            or global_verifier.get("shard_semantic_evidence_sha256s")
            != verifier_shard_semantic_hashes
            or global_verifier.get("shard_route_tuples")
            != expected_verifier_shard_route_tuples
            or global_verifier.get("shard_route_tuples_sha256")
            != expected_verifier_shard_route_tuples_sha256
        ):
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:shard_commitment"
            )
        expected_verifier_aggregate_commitment = _v12_sorted_digest_json({
            "version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_AGGREGATE_VERSION,
            "node_candidate_sha256": node_candidate_sha256,
            "expected_shards": expected_verifier_shards,
            "shard_semantic_evidence_sha256s": verifier_shard_semantic_hashes,
            "shard_artifacts_sha256": expected_verifier_shard_artifacts_sha256,
            "shard_route_tuples_sha256": expected_verifier_shard_route_tuples_sha256,
            "model_judgment_output_sha256": expected_verifier_judgment_sha256,
            "request_lineage_sha256": global_verifier.get("request_lineage_sha256") or "",
        })
        if (
            global_verifier.get("aggregate_commitment_sha256")
            != expected_verifier_aggregate_commitment
        ):
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:aggregate_commitment_sha256"
            )
        expected_verifier_semantic_sha256 = _v12_sorted_digest_json({
            "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_SEMANTIC_EVIDENCE_VERSION,
            "node_candidate_sha256": node_candidate_sha256,
            "constituent_semantic_evidence_sha256": expected_constituent_semantic_hashes,
            "shard_semantic_evidence_sha256s": verifier_shard_semantic_hashes,
            "aggregate_commitment_sha256": expected_verifier_aggregate_commitment,
            "model_judgment_output_sha256": expected_verifier_judgment_sha256,
        })
        if global_verifier.get("semantic_evidence_sha256") != expected_verifier_semantic_sha256:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_verifier:semantic_evidence_sha256"
            )
        verifier_receipt_fields = (
            "agent_key",
            "phase",
            "artifact_role",
            "provider_mode",
            "model_provider",
            "model_name",
            "model_alias",
            "structured_json_mode",
            "prompt_template_sha256",
            "rendered_prompt_sha256",
            "response_schema_version",
            "response_schema_sha256",
            "batch_raw_response_sha256",
            "contract_key",
            "contract_version",
            "prompt_version_id",
            "semantic_evidence_version",
            "semantic_evidence_sha256",
            "pipeline_stage",
            "stage_attempt",
            "node_candidate_sha256",
            "request_lineage_version",
            "trusted_context_sha256",
            "untrusted_payload_sha256",
            "request_options_sha256",
            "request_input_sha256",
            "request_lineage_sha256",
            "model_judgment_output_sha256",
            "shard_policy_version",
            "expected_shards",
            "shard_artifacts_sha256",
            "shard_semantic_evidence_sha256s",
            "shard_route_tuples",
            "shard_route_tuples_sha256",
            "aggregate_commitment_sha256",
            "constituent_semantic_evidence_sha256",
        )
        for key in verifier_receipt_fields:
            if receipt_global_verifier.get(key) != global_verifier.get(key):
                raise ValueError(
                    f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:global_verifier:{key}:mismatch"
                )

        global_finalizer = artifact.get("global_finalizer") if isinstance(artifact.get("global_finalizer"), dict) else {}
        receipt_global_finalizer = (
            receipt_role.get("global_finalizer")
            if isinstance(receipt_role.get("global_finalizer"), dict)
            else {}
        )
        expected_global_identity = {
            "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
            "phase": "node_global_finalizer",
            "artifact_role": "node_set_global_finalizer",
            "contract_key": "math_question_bank_v12_node_set_global_finalizer",
            "contract_version": question_bank.V12_GLOBAL_FINALIZER_CONTRACT_VERSION,
            "prompt_version_id": question_bank.V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID,
            "response_schema_version": question_bank.V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
            "semantic_evidence_version": question_bank.V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION,
            "provider_mode": "live_model",
        }
        for key, value in expected_global_identity.items():
            if global_finalizer.get(key) != value:
                raise ValueError(
                    f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_finalizer:{key}"
                )
        if global_finalizer.get("constituent_semantic_evidence_sha256") != expected_constituent_semantic_hashes:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_finalizer:constituents"
            )
        global_output = (
            global_finalizer.get("global_review_output")
            if isinstance(global_finalizer.get("global_review_output"), dict)
            else {}
        )
        if global_finalizer.get("global_review_output_sha256") != _v12_sorted_digest_json(global_output):
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_finalizer:output_hash"
            )
        expected_global_semantic_sha256 = _v12_sorted_digest_json({
            "semantic_evidence_version": question_bank.V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION,
            "node_candidate_sha256": node_candidate_sha256,
            "constituent_semantic_evidence_sha256": expected_constituent_semantic_hashes,
            "global_review_output_sha256": global_finalizer.get("global_review_output_sha256") or "",
        })
        if global_finalizer.get("semantic_evidence_sha256") != expected_global_semantic_sha256:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:global_finalizer:semantic_hash"
            )
        expected_aggregate_semantic_sha256 = question_bank.v12_node_set_review_semantic_evidence_sha256(
            node_entry,
            artifact_reviews,
            global_finalizer,
            artifact.get("global_verifier") if isinstance(artifact.get("global_verifier"), dict) else {},
        )
        if artifact.get("semantic_evidence_sha256") != expected_aggregate_semantic_sha256:
            raise ValueError(
                f"V12 active seed requires trusted live runner provenance: {node_id}:node_set_review:aggregate_semantic_hash"
            )
        for key in (
            "agent_key",
            "phase",
            "artifact_role",
            "provider_mode",
            "model_provider",
            "model_name",
            "model_alias",
            "structured_json_mode",
            "prompt_template_sha256",
            "rendered_prompt_sha256",
            "response_schema_version",
            "response_schema_sha256",
            "batch_raw_response_sha256",
            "contract_key",
            "contract_version",
            "prompt_version_id",
            "semantic_evidence_version",
            "semantic_evidence_sha256",
            "node_candidate_sha256",
            "global_review_output_sha256",
            "constituent_semantic_evidence_sha256",
        ):
            if receipt_global_finalizer.get(key) != global_finalizer.get(key):
                raise ValueError(
                    f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:global_finalizer:{key}:mismatch"
                )
        if receipt_role.get("execution_policy") != _v12_node_set_review_execution_policy_for_seed(artifact):
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:execution_policy:mismatch")
        if receipt_role.get("aggregation") != artifact.get("aggregation"):
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:aggregation:mismatch")
        if receipt_role.get("semantic_evidence_coverage") != artifact.get("semantic_evidence_coverage"):
            raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:semantic_evidence_coverage:mismatch")
        for key in (
            "node_ux_verdict",
            "unprompted_slot_results",
            "instruction_voice_distribution",
            "repetitive_instruction_clusters",
            "overloaded_slots",
            "notation_failure_slots",
            "dignity_failure_slots",
            "ux_rejected_slots",
            "item_count",
            "node_local_mainline_count",
            "controlled_stretch_count",
            "invalid_difficulty_vector_slots",
            "gate_errors",
        ):
            if receipt_role.get(key) != artifact.get(key):
                raise ValueError(f"V12 active seed requires trusted live runner receipt: {node_id}:node_set_review:{key}:mismatch")
    receipt_items = {}
    for receipt_item in runner_receipt.get("items") or []:
        if not isinstance(receipt_item, dict):
            continue
        receipt_items[
            (
                str(receipt_item.get("node_id") or ""),
                int(receipt_item.get("slot") or 0),
                str(receipt_item.get("item_id") or ""),
            )
        ] = receipt_item
    for node_entry in manifest.get("nodes") or []:
        for item in node_entry.get("items") or []:
            item_id = str(item.get("id") or "")
            slot = int(item.get("slot") or 0)
            receipt_item = receipt_items.get((str(node_entry.get("node_id") or ""), slot, item_id))
            if not receipt_item:
                raise ValueError(f"V12 active seed requires trusted live runner receipt: missing item receipt:{item_id}")
            candidate_sha256 = question_bank.v12_external_candidate_sha256(item)
            if receipt_item.get("candidate_sha256") != candidate_sha256:
                raise ValueError(f"V12 active seed requires trusted live runner receipt: candidate hash mismatch:{item_id}")
            designer_artifact = item.get("designer_artifact") if isinstance(item.get("designer_artifact"), dict) else {}
            review_artifact = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
            expected_identity = {
                "designer": {
                    "agent_key": question_bank.QUESTION_DESIGNER_AGENT_KEY,
                    "phase": "question_candidate",
                    "artifact_role": "designer",
                    "contract_key": "math_question_bank_v12_designer_batch",
                    "contract_version": question_bank.V12_DESIGNER_CONTRACT_VERSION,
                    "prompt_version_id": question_bank.V12_DESIGNER_PROMPT_VERSION_ID,
                    "response_schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                },
                "reviewer": {
                    "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
                    "phase": "question_review",
                    "artifact_role": "reviewer",
                    "contract_key": "math_question_bank_v12_reviewer_batch",
                    "contract_version": question_bank.V12_REVIEWER_CONTRACT_VERSION,
                    "prompt_version_id": question_bank.V12_REVIEWER_PROMPT_VERSION_ID,
                    "response_schema_version": question_bank.V12_REVIEWER_RESPONSE_SCHEMA_VERSION,
                    "semantic_evidence_version": question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
                },
            }
            for role, artifact in (("designer", designer_artifact), ("reviewer", review_artifact)):
                receipt_role = receipt_item.get(role) if isinstance(receipt_item.get(role), dict) else {}
                if artifact.get("provider_mode") != "live_model":
                    raise ValueError(f"V12 active seed requires trusted live runner provenance: {item_id}:{role}:provider_mode")
                for identity_key, expected_value in expected_identity[role].items():
                    if artifact.get(identity_key) != expected_value:
                        raise ValueError(
                            f"V12 active seed requires trusted live runner provenance: {item_id}:{role}:{identity_key}"
                        )
                    if receipt_role.get(identity_key) != expected_value:
                        raise ValueError(
                            f"V12 active seed requires trusted live runner receipt: {item_id}:{role}:{identity_key}:mismatch"
                        )
                audit_keys = (
                    "agent_key",
                    "phase",
                    "artifact_role",
                    "provider_mode",
                    "model_provider",
                    "model_name",
                    "model_alias",
                    "structured_json_mode",
                    "prompt_template_sha256",
                    "rendered_prompt_sha256",
                    "response_schema_version",
                    "response_schema_sha256",
                    "batch_raw_response_sha256",
                )
                if role == "reviewer":
                    audit_keys = (*audit_keys, "semantic_evidence_version", "semantic_evidence_sha256")
                for key in audit_keys:
                    if not str(artifact.get(key) or "").strip():
                        raise ValueError(f"V12 active seed requires trusted live runner provenance: {item_id}:{role}:{key}")
                    if receipt_role.get(key) != artifact.get(key):
                        raise ValueError(f"V12 active seed requires trusted live runner receipt: {item_id}:{role}:{key}:mismatch")
            if (receipt_item.get("reviewer") or {}).get("candidate_sha256") != review_artifact.get("candidate_sha256"):
                raise ValueError(f"V12 active seed requires trusted live runner receipt: reviewer candidate hash mismatch:{item_id}")
            if review_artifact.get("semantic_evidence_sha256") != question_bank.v12_item_review_semantic_evidence_sha256(item, review_artifact):
                raise ValueError(f"V12 active seed requires trusted live runner provenance: reviewer semantic evidence mismatch:{item_id}")
    expected_count = sum(len(node.get("items") or []) for node in manifest.get("nodes") or [])
    if int(runner_receipt.get("item_count") or 0) != expected_count or len(receipt_items) != expected_count:
        raise ValueError("V12 active seed requires trusted live runner receipt: item_count mismatch")
    expected_node_count = len(manifest.get("nodes") or [])
    if int(runner_receipt.get("node_count") or 0) != expected_node_count or len(receipt_nodes) != expected_node_count:
        raise ValueError("V12 active seed requires trusted live runner receipt: node_count mismatch")


def _v12_sorted_digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _v12_node_set_review_execution_policy_for_seed(artifact: dict[str, Any]) -> dict[str, int]:
    raw_policy = artifact.get("execution_policy") if isinstance(artifact.get("execution_policy"), dict) else {}
    concurrency = raw_policy.get("node_review_concurrency")
    if (
        not isinstance(concurrency, int)
        or isinstance(concurrency, bool)
        or concurrency != question_bank.V12_NODE_SET_REVIEW_ACTIVATION_CONCURRENCY
    ):
        raise ValueError("V12 active seed requires node_set_review execution_policy node_review_concurrency exactly 1")
    return {
        "node_review_concurrency": concurrency,
        "node_set_review_shard_size": question_bank.V12_NODE_SET_REVIEW_SHARD_SIZE,
        "node_set_review_expected_shards": len(question_bank.v12_expected_node_set_review_shards()),
        "global_finalizer_concurrency": 1,
    }


def _v12_completed_node_receipt_for_seed(
    *,
    node_entry: dict[str, Any],
    graph_version: str,
    repair_chain_hash: str,
    cross_node_summary_contexts: dict[str, Any] | None = None,
    model_budget_commitment: dict[str, Any] | None = None,
    include_cross_node_context_commitment: bool = True,
) -> dict[str, Any]:
    artifact = node_entry.get("node_review_artifact") if isinstance(node_entry.get("node_review_artifact"), dict) else {}
    global_verifier = artifact.get("global_verifier") if isinstance(artifact.get("global_verifier"), dict) else {}
    global_finalizer = artifact.get("global_finalizer") if isinstance(artifact.get("global_finalizer"), dict) else {}
    semantic_commitment = question_bank.v12_node_semantic_evidence_commitment(node_entry)
    payload = {
        "schema_version": question_bank.V12_COMPLETED_NODE_RECEIPT_SCHEMA_VERSION,
        "runner_mode": "live",
        "artifact_role": "completed_node_checkpoint_receipt",
        "node_id": node_entry.get("node_id"),
        "graph_version": graph_version,
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "node_candidate_sha256": question_bank.v12_node_candidate_sha256(node_entry),
        "item_candidate_sha256": [
            question_bank.v12_external_candidate_sha256(item)
            for item in sorted(node_entry.get("items") or [], key=lambda item: int(item.get("slot") or 0))
            if isinstance(item, dict)
        ],
        "repair_chain_hash": repair_chain_hash,
        "semantic_evidence_commitment_version": semantic_commitment["version"],
        "semantic_evidence_commitment_sha256": semantic_commitment["sha256"],
        "node_set_review": {
            "agent_key": artifact.get("agent_key", ""),
            "phase": artifact.get("phase", ""),
            "provider_mode": artifact.get("provider_mode", ""),
            "pipeline_stage": artifact.get("pipeline_stage", ""),
            "stage_attempt": artifact.get("stage_attempt", ""),
            "aggregate_sha256": (artifact.get("aggregation") or {}).get("aggregate_sha256", ""),
            "constituent_review_output_sha256": [
                review.get("review_output_sha256", "")
                for review in (artifact.get("constituent_reviews") or [])
                if isinstance(review, dict)
            ],
            "focal_semantic_evidence_sha256": [
                review.get("semantic_evidence_sha256", "")
                for review in (artifact.get("constituent_reviews") or [])
                if isinstance(review, dict)
            ],
            "global_verifier": {
                "agent_key": global_verifier.get("agent_key", ""),
                "phase": global_verifier.get("phase", ""),
                "artifact_role": global_verifier.get("artifact_role", ""),
                "contract_key": global_verifier.get("contract_key", ""),
                "contract_version": global_verifier.get("contract_version", ""),
                "prompt_version_id": global_verifier.get("prompt_version_id", ""),
                "response_schema_version": global_verifier.get("response_schema_version", ""),
                "semantic_evidence_version": global_verifier.get("semantic_evidence_version", ""),
                "semantic_evidence_sha256": global_verifier.get("semantic_evidence_sha256", ""),
                "model_judgment_output_sha256": global_verifier.get("model_judgment_output_sha256", ""),
            },
            "global_finalizer": {
                "agent_key": global_finalizer.get("agent_key", ""),
                "phase": global_finalizer.get("phase", ""),
                "artifact_role": global_finalizer.get("artifact_role", ""),
                "contract_key": global_finalizer.get("contract_key", ""),
                "contract_version": global_finalizer.get("contract_version", ""),
                "prompt_version_id": global_finalizer.get("prompt_version_id", ""),
                "response_schema_version": global_finalizer.get("response_schema_version", ""),
                "semantic_evidence_version": global_finalizer.get("semantic_evidence_version", ""),
                "semantic_evidence_sha256": global_finalizer.get("semantic_evidence_sha256", ""),
                "global_review_output_sha256": global_finalizer.get("global_review_output_sha256", ""),
                "constituent_semantic_evidence_sha256": global_finalizer.get(
                    "constituent_semantic_evidence_sha256",
                    [],
                ),
            },
            "semantic_evidence_version": artifact.get("semantic_evidence_version", ""),
            "semantic_evidence_sha256": artifact.get("semantic_evidence_sha256", ""),
            "node_ux_verdict": artifact.get("node_ux_verdict", ""),
            "instruction_voice_distribution": artifact.get("instruction_voice_distribution", []),
            "repetitive_instruction_clusters": artifact.get("repetitive_instruction_clusters", []),
            "overloaded_slots": artifact.get("overloaded_slots", []),
            "notation_failure_slots": artifact.get("notation_failure_slots", []),
            "dignity_failure_slots": artifact.get("dignity_failure_slots", []),
            "ux_rejected_slots": artifact.get("ux_rejected_slots", []),
            "item_count": artifact.get("item_count"),
            "node_local_mainline_count": artifact.get("node_local_mainline_count"),
            "controlled_stretch_count": artifact.get("controlled_stretch_count"),
            "invalid_difficulty_vector_slots": artifact.get("invalid_difficulty_vector_slots", []),
            "gate_errors": artifact.get("gate_errors", []),
            "execution_policy": _v12_node_set_review_execution_policy_for_seed(artifact),
        },
        "item_review_semantic_evidence": [
            {
                "slot": item.get("slot"),
                "item_id": item.get("id"),
                "semantic_evidence_version": (item.get("review_artifact") or {}).get("semantic_evidence_version", ""),
                "semantic_evidence_sha256": (item.get("review_artifact") or {}).get("semantic_evidence_sha256", ""),
            }
            for item in sorted(node_entry.get("items") or [], key=lambda item: int(item.get("slot") or 0))
            if isinstance(item, dict)
        ],
    }
    if include_cross_node_context_commitment:
        contexts = json.loads(json.dumps(
            cross_node_summary_contexts or {},
            ensure_ascii=False,
        ))
        payload["cross_node_summary_contexts"] = contexts
        payload["cross_node_context_commitment_sha256"] = _v12_sorted_digest_json(
            contexts
        )
    if model_budget_commitment is not None:
        payload["model_budget_commitment"] = dict(model_budget_commitment)
    return {**payload, "receipt_sha256": _v12_sorted_digest_json(payload)}


def _v12_artifact_model_provider(artifact: dict[str, Any]) -> str:
    return str(artifact.get("model_provider") or "")


def _v12_artifact_model_name(artifact: dict[str, Any]) -> str:
    return str(artifact.get("model_name") or "")


def _v12_artifact_model_alias(artifact: dict[str, Any]) -> str:
    return str(artifact.get("model_alias") or artifact.get("model_name") or "")


def _v12_artifact_model_params(
    artifact: dict[str, Any],
    *,
    external_run_id_key: str,
    external_run_id: Any,
) -> dict[str, Any]:
    return {
        "trust_mode": "recorded_model",
        "provider_mode": "recorded_model",
        "origin_provider_mode": str(artifact.get("provider_mode") or ""),
        "structured_json_mode": str(artifact.get("structured_json_mode") or ""),
        "batch_raw_response_sha256": str(artifact.get("batch_raw_response_sha256") or ""),
        external_run_id_key: str(external_run_id or ""),
    }


def _node_values(node: dict[str, Any], summer: dict[str, Any]) -> tuple[Any, ...]:
    return (
        node["id"],
        node.get("name", ""),
        node.get("stage", ""),
        node.get("domain", ""),
        node.get("priority", ""),
        summer.get("mode", "selective_core"),
        int(summer.get("sequence_band", 99)),
        json_dump(node.get("prerequisites", [])),
        json_dump(node.get("unlocks", [])),
        json_dump(node),
    )


def _node_has_attempts(conn: sqlite3.Connection, node_id: str) -> bool:
    return bool(conn.execute("select 1 from attempts where node_id = ? limit 1", (node_id,)).fetchone())


def _question_has_attempts(conn: sqlite3.Connection, question_id: str) -> bool:
    return bool(conn.execute("select 1 from attempts where question_id = ? limit 1", (question_id,)).fetchone())


def cleanup_obsolete_question_bank(conn: sqlite3.Connection) -> dict[str, int]:
    obsolete_filter = """
      (
        (source_type = 'graph_generated' and item_version != ?)
        or (source_type = 'evolved' and item_version != ?)
      )
      and not exists (
        select 1
        from question_bank_version_ledger l
        where l.question_bank_version = question_items.item_version
          and l.status in ('staged','active')
      )
      and not exists (
        select 1
        from attempts a
        where a.question_id = question_items.id
      )
    """
    params = (question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION)
    obsolete_questions = conn.execute(
        f"select count(*) from question_items where {obsolete_filter}",
        params,
    ).fetchone()[0]
    obsolete_review_records = conn.execute(
        f"""
        select count(*)
        from question_review_records
        where question_id in (
          select id
          from question_items
          where {obsolete_filter}
        )
        """,
        params,
    ).fetchone()[0]
    conn.execute(
        f"""
        delete from question_review_records
        where question_id in (
          select id
          from question_items
          where {obsolete_filter}
        )
        """,
        params,
    )
    conn.execute(f"delete from question_items where {obsolete_filter}", params)
    return {
        "obsolete_questions_deleted": int(obsolete_questions),
        "obsolete_review_records_deleted": int(obsolete_review_records),
    }


def seed_agent_profiles(conn: sqlite3.Connection) -> None:
    profiles = {
        "graph_agent": ("图谱 Agent", {"focus": "node_split_dependency", "capabilities": ["reference_audit", "coverage_audit", "weak_evidence_hotspot_detection"], "learned_rules": []}),
        "diagnostic_agent": ("诊断 Agent", {"focus": "evidence_status", "capabilities": ["graph_bound_probe_design", "abcd_state_interpretation"], "learned_rules": []}),
        "evaluation_agent": ("评估 Agent", {
            "focus": "mastery_diagnosis_planner_signal",
            "capabilities": [
                "valid_answer_analysis_gate",
                "dimension_mastery_diagnosis",
                "single_strong_not_stable_policy",
                "confirmation_need_decision",
                "planner_signal_contract",
            ],
            "input_contract": [
                "active_graded_attempts",
                "valid_answer_analysis",
                "graph_node_context",
                "question_kind_coverage",
                "prior_mastery_state",
            ],
            "output_contract": [
                "mastery_state",
                "gap_type",
                "intervention_need",
                "confirmation_type",
                "can_advance",
                "planner_signal",
            ],
            "learned_rules": [],
        }),
        "answer_analysis_agent": ("答案分析 Agent", {
            "focus": "reasoning_evidence_to_evaluation_support",
            "capabilities": [
                "optimal_solution_analysis",
                "child_solution_comparison",
                "alternative_solution_recognition",
                "five_dimension_evidence_comparison",
                "process_gap_explanation",
                "evaluation_support_summary",
                "next_hint_without_parent_grading",
            ],
            "input_contract": [
                "graph_bound_question",
                "reference_solution_and_rubric",
                "child_text_answer",
                "untrusted_photo_ocr_evidence",
            ],
            "output_contract": [
                "result_score_and_confidence",
                "five_dimension_comparison",
                "optimal_and_alternative_solutions",
                "process_gap",
                "evaluation_support",
                "child_safe_next_prompt",
            ],
            "learned_rules": [],
        }),
        "teaching_agent": ("教学 Agent", {"focus": "essence_model_variation", "learned_rules": []}),
        "question_agent": ("出题协调 Agent", {"focus": "designer_reviewer_coordination", "focus_error_tags": [], "learned_rules": []}),
        "question_designer_agent": ("命题 Agent", {"focus": "graph_bound_diagnostic_item_design", "capabilities": ["node_intent_to_item", "error_tag_targeting", "variant_ladder_design"], "learned_rules": []}),
        "question_reviewer_agent": ("审题 Agent", {"focus": "age_floor_and_diagnostic_quality_gate", "capabilities": ["reject_mechanical_drill", "reject_answer_only", "reject_child_facing_meta_prompt", "require_process_evidence"], "learned_rules": []}),
        "self_evolution_agent": ("自进化 Agent", {
            "focus": "evidence_driven_system_improvement",
            "capabilities": [
                "usable_evidence_filter",
                "profile_patch_proposal",
                "question_pattern_rule_proposal",
                "retest_candidate_request",
                "rollback_hint_proposal",
                "audit_and_rollback_contract",
            ],
            "input_contract": [
                "active_graded_attempts",
                "valid_answer_analysis",
                "current_graph_binding",
                "closed_or_authorized_evolution_context",
                "question_review_lineage",
                "prior_evolution_audits",
            ],
            "output_contract": [
                "no_action",
                "profile_patch",
                "question_pattern_rule",
                "retest_candidate_request",
                "rollback_hint",
                "prompt_delta",
            ],
            "non_authority": [
                "does_not_grade_raw_answers",
                "does_not_select_next_round_tasks",
                "does_not_approve_active_use_questions",
                "does_not_create_global_rules_from_single_attempt",
            ],
            "learned_rules": [],
        }),
        "planner_agent": ("规划 Agent", {
            "focus": "evaluation_signal_to_graph_bound_round",
            "capabilities": [
                "planner_signal_consumption",
                "current_active_question_inventory_gate",
                "graph_dependency_targeting",
                "ten_task_round_composition",
                "stale_plan_reuse_rejection",
            ],
            "input_contract": [
                "evaluation_planner_signal",
                "graph_dependencies",
                "current_active_question_bank",
                "valid_evidence_lineage",
                "recent_plan_history",
            ],
            "output_contract": [
                "planner_policy_version",
                "ten_task_plan",
                "task_type_sequence",
                "question_ids",
                "planning_signal_refs",
            ],
            "learned_rules": [],
        }),
        "qa_agent": ("QA Agent", {"focus": "real_evidence_only", "learned_rules": []}),
    }
    for agent_key, role in internal_agents.INTERNAL_AGENT_ROLES.items():
        display = role["display"]
        profile = profiles.get(agent_key, (display, {"learned_rules": []}))[1]
        profile = {
            **profile,
            "does": role["does"],
            "does_not": role["does_not"],
            "contract_key": role["contract_key"],
        }
        profiles[agent_key] = (display, profile)
    for key, (display, profile) in profiles.items():
        existing = conn.execute("select agent_key from agent_profiles where agent_key = ?", (key,)).fetchone()
        if existing:
            continue
        conn.execute(
            "insert into agent_profiles(agent_key, display_name, revision, profile_json, updated_at) values (?, ?, ?, ?, ?)",
            (key, display, 1, json_dump(profile), now_iso()),
        )


def upsert_question(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    created_by_event_id: str | None = None,
    *,
    designer_run_id: str | None = None,
    reviewer_run_id: str | None = None,
) -> None:
    existing = conn.execute(
        "select item_version from question_items where id = ?",
        (item["id"],),
    ).fetchone()
    if existing and str(existing["item_version"] or "") != str(
        item.get("item_version") or "2026-07-05.v1"
    ):
        raise ValueError(
            f"question id cannot be reused across bank versions: {item['id']}"
        )
    if _question_has_attempts(conn, item["id"]):
        return
    _validate_question_graph_references(conn, item)
    question_bank.validate_active_item_quality(item)
    normalized = question_bank.normalize_item_json(item)
    conn.execute(
        """
        insert or replace into question_items(
          id, item_version, source_type, node_id, secondary_node_ids_json, kind,
          question_type, variant_level, production_category, prompt, answer_format, expected_answer,
          rubric_json, solution_steps_json, error_tags_json,
          rollback_candidate_node_ids_json, rollback_candidate_relations_json,
          estimated_minutes, parent_observation, source_json, created_by_event_id, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["id"],
            item.get("item_version", "2026-07-05.v1"),
            item.get("source_type") or item.get("source", {}).get("type", "graph_generated"),
            item["node_id"],
            normalized["secondary_node_ids_json"],
            item.get("kind", "practice"),
            item.get("question_type", ""),
            item.get("variant_level", "L2"),
            item.get("production_category", ""),
            item["prompt"],
            item.get("answer_format", "关键步骤 + 答案"),
            item.get("expected_answer", ""),
            normalized["rubric_json"],
            normalized["solution_steps_json"],
            normalized["error_tags_json"],
            normalized["rollback_candidate_node_ids_json"],
            normalized["rollback_candidate_relations_json"],
            int(item.get("estimated_minutes", 3)),
            item.get("parent_observation", ""),
            normalized["source_json"],
            created_by_event_id or item.get("created_by_event_id"),
            json_dump(item),
        ),
    )
    upsert_question_usage_policy(conn, item, commit=False)
    source_type = item.get("source_type") or item.get("source", {}).get("type", "graph_generated")
    if source_type in {"graph_generated", "evolved"}:
        record_question_review_record(
            conn,
            question_id=item["id"],
            candidate_id=item.get("candidate_id") or item["id"],
            item_version=item.get("item_version", "2026-07-05.v1"),
            source_type=source_type,
            candidate=item,
            designer_run_id=designer_run_id,
            reviewer_run_id=reviewer_run_id,
            commit=False,
        )


def upsert_question_usage_policy(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    *,
    commit: bool = False,
) -> dict[str, Any]:
    policy = question_usage.policy_for_item(item)
    question_id = str(item.get("id") or "")
    item_version = str(item.get("item_version") or "")
    policy_digest = question_usage.policy_digest(policy)
    existing = conn.execute(
        """
        select *
        from question_usage_policies
        where question_id = ? and item_version = ? and status = 'active'
        limit 1
        """,
        (question_id, item_version),
    ).fetchone()
    if existing and existing["policy_digest_sha256"] == policy_digest:
        return question_usage_policy_row_to_dict(existing)
    now = now_iso()
    if existing:
        conn.execute(
            "update question_usage_policies set status = 'superseded', updated_at = ? where id = ?",
            (now, existing["id"]),
        )
    policy_id = f"QUP-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into question_usage_policies(
          id, question_id, item_version, policy_version, status,
          allowed_purposes_json, default_practice_family,
          allowed_practice_roles_json, diagnostic_roles_json, teaching_roles_json,
          primary_node_id, secondary_node_ids_json, structure_fingerprint,
          support_only, not_for_activation, policy_digest_sha256,
          source_json, created_at, updated_at
        ) values (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            policy_id,
            question_id,
            item_version,
            policy["schema_version"],
            json_dump(policy["allowed_purposes"]),
            policy["default_practice_family"],
            json_dump(policy["allowed_practice_roles"]),
            json_dump(policy["diagnostic_roles"]),
            json_dump(policy["teaching_roles"]),
            policy["primary_node_id"],
            json_dump(policy["secondary_node_ids"]),
            policy["structure_fingerprint"],
            1 if policy["support_only"] else 0,
            1 if policy["not_for_activation"] else 0,
            policy_digest,
            json_dump({"source": policy.get("source", ""), "policy": policy}),
            now,
            now,
        ),
    )
    if commit:
        conn.commit()
    return active_question_usage_policy(conn, question_id, item_version=item_version)


def question_usage_policy_row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["schema_version"] = data.pop("policy_version")
    data["allowed_purposes"] = json_load(data.pop("allowed_purposes_json", "[]"), [])
    data["allowed_practice_roles"] = json_load(data.pop("allowed_practice_roles_json", "[]"), [])
    data["diagnostic_roles"] = json_load(data.pop("diagnostic_roles_json", "[]"), [])
    data["teaching_roles"] = json_load(data.pop("teaching_roles_json", "[]"), [])
    data["secondary_node_ids"] = json_load(data.pop("secondary_node_ids_json", "[]"), [])
    data["support_only"] = bool(data.get("support_only"))
    data["not_for_activation"] = bool(data.get("not_for_activation"))
    source_meta = json_load(data.pop("source_json", "{}"), {})
    stored_policy = source_meta.get("policy") if isinstance(source_meta, dict) else None
    data["selection_preconditions"] = question_usage.normalize_selection_preconditions(
        (stored_policy or {}).get("selection_preconditions")
        if isinstance(stored_policy, dict)
        else None
    )
    data["support_routing"] = question_usage.normalize_support_routing(
        (stored_policy or {}).get("support_routing")
        if isinstance(stored_policy, dict)
        else None
    )
    data["source"] = str(
        (stored_policy or {}).get("source")
        if isinstance(stored_policy, dict)
        else (source_meta or {}).get("source")
        if isinstance(source_meta, dict)
        else ""
    )
    data["source_meta"] = source_meta
    return data


def active_question_usage_policy(
    conn: sqlite3.Connection,
    question_id: str,
    *,
    item_version: str | None = None,
) -> dict[str, Any] | None:
    filters = ["question_id = ?", "status = 'active'"]
    params: list[Any] = [question_id]
    if item_version:
        filters.append("item_version = ?")
        params.append(item_version)
    row = conn.execute(
        f"""
        select *
        from question_usage_policies
        where {' and '.join(filters)}
        order by updated_at desc, id desc
        limit 1
        """,
        params,
    ).fetchone()
    return question_usage_policy_row_to_dict(row) if row else None


def record_flow_step_usage_context(
    conn: sqlite3.Connection,
    *,
    flow_step_id: str,
    question_id: str,
    context: dict[str, Any],
    item_version: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    question_usage.validate_context(context)
    question = get_question(conn, question_id)
    exact_item_version = str(item_version or question.get("item_version") or "")
    policy = active_question_usage_policy(
        conn, question_id, item_version=exact_item_version
    )
    if not policy:
        raise ValueError("question usage policy is missing for the exact item version")
    if context["question_usage_policy_digest_sha256"] != policy["policy_digest_sha256"]:
        raise ValueError("step usage context does not bind the active question usage policy")
    digest = question_usage.context_digest(context)
    existing = conn.execute(
        "select * from flow_step_usage_contexts where flow_step_id = ? limit 1",
        (flow_step_id,),
    ).fetchone()
    if existing:
        if existing["context_digest_sha256"] != digest:
            raise ValueError("flow step usage context is immutable")
        return flow_step_usage_context_row_to_dict(existing)
    context_id = f"SUC-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into flow_step_usage_contexts(
          id, flow_step_id, question_usage_policy_id, context_version,
          purpose, purpose_role, practice_family, practice_role, hint_policy,
          mastery_evidence_weight, instability_signal_weight,
          mastery_update_eligible, mastery_state_ceiling,
          requires_diagnostic_confirmation, block_id, block_index,
          structure_fingerprint, context_digest_sha256, raw_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context_id,
            flow_step_id,
            policy["id"],
            context["schema_version"],
            context["purpose"],
            context["purpose_role"],
            context["practice_family"],
            context["practice_role"],
            context["hint_policy"],
            float(context["mastery_evidence_weight"]),
            float(context["instability_signal_weight"]),
            1 if context["mastery_update_eligible"] else 0,
            context["mastery_state_ceiling"],
            1 if context["requires_diagnostic_confirmation"] else 0,
            context["block_id"],
            int(context["block_index"]),
            context["structure_fingerprint"],
            digest,
            json_dump(context),
            now_iso(),
        ),
    )
    if commit:
        conn.commit()
    return flow_step_usage_context(conn, flow_step_id)


def flow_step_usage_context_row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["mastery_update_eligible"] = bool(data.get("mastery_update_eligible"))
    data["requires_diagnostic_confirmation"] = bool(data.get("requires_diagnostic_confirmation"))
    data["mastery_evidence_weight"] = float(data.get("mastery_evidence_weight") or 0.0)
    data["instability_signal_weight"] = float(data.get("instability_signal_weight") or 0.0)
    data["raw"] = json_load(data.pop("raw_json", "{}"), {})
    return data


def flow_step_usage_context(conn: sqlite3.Connection, flow_step_id: str) -> dict[str, Any]:
    row = conn.execute(
        "select * from flow_step_usage_contexts where flow_step_id = ? limit 1",
        (flow_step_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"Unknown flow step usage context: {flow_step_id}")
    return flow_step_usage_context_row_to_dict(row)


def record_attempt_usage_context_snapshot(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    flow_step_id: str,
    commit: bool = False,
) -> dict[str, Any]:
    context = flow_step_usage_context(conn, flow_step_id)
    snapshot = dict(context.get("raw") or {})
    step = conn.execute(
        "select question_item_version, prompt_package_json from flow_steps where id = ? limit 1",
        (flow_step_id,),
    ).fetchone()
    if not step:
        raise KeyError(f"Unknown flow step: {flow_step_id}")
    prompt_package = json_load(step["prompt_package_json"], {})
    presented_hint = str(prompt_package.get("hint") or "").strip()
    snapshot.update(
        {
            "question_item_version": str(step["question_item_version"] or ""),
            "presented_hint": presented_hint,
            "actual_hint_exposed": bool(presented_hint),
            "child_hint_exposed": bool(presented_hint),
        }
    )
    existing = conn.execute(
        "select * from attempt_usage_contexts where attempt_id = ? limit 1",
        (attempt_id,),
    ).fetchone()
    if existing:
        if existing["context_digest_sha256"] != context["context_digest_sha256"]:
            raise ValueError("attempt usage context snapshot is immutable")
        return attempt_usage_context(conn, attempt_id)
    snapshot_id = f"AUC-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into attempt_usage_contexts(
          id, attempt_id, flow_step_usage_context_id,
          context_digest_sha256, snapshot_json, created_at
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            attempt_id,
            context["id"],
            context["context_digest_sha256"],
            json_dump(snapshot),
            now_iso(),
        ),
    )
    if commit:
        conn.commit()
    return attempt_usage_context(conn, attempt_id)


def attempt_usage_context(conn: sqlite3.Connection, attempt_id: str) -> dict[str, Any]:
    row = conn.execute(
        "select * from attempt_usage_contexts where attempt_id = ? limit 1",
        (attempt_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"Unknown attempt usage context: {attempt_id}")
    data = dict(row)
    data["snapshot"] = json_load(data.pop("snapshot_json", "{}"), {})
    return data


def _backfill_question_usage_policies(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        select q.*
        from question_items q
        left join question_usage_policies up
          on up.question_id = q.id
         and up.item_version = q.item_version
         and up.status = 'active'
        where up.id is null
        order by q.id
        """
    ).fetchall()
    for row in rows:
        item = row_to_question(row)
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        merged = {**raw, **{key: value for key, value in item.items() if key != "raw"}}
        upsert_question_usage_policy(conn, merged, commit=False)


def _backfill_teaching_flow_step_usage_contexts(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        select s.id, s.step_type, s.question_id, s.question_item_version,
               s.selection_reason_json
        from flow_steps s
        left join flow_step_usage_contexts context
          on context.flow_step_id = s.id
        where s.step_type in ('worked_example', 'teaching_repair')
          and s.question_id is not null
          and context.id is null
        order by s.created_at, s.id
        """
    ).fetchall()
    for row in rows:
        policy = active_question_usage_policy(
            conn,
            row["question_id"],
            item_version=str(row["question_item_version"] or ""),
        )
        if not policy or "teaching" not in set(policy["allowed_purposes"]):
            continue
        role = (
            "worked_example"
            if row["step_type"] == "worked_example"
            else "targeted_repair"
        )
        if role not in set(policy["teaching_roles"]):
            continue
        selection_reason = json_load(row["selection_reason_json"], {})
        stored_context = (
            selection_reason.get("requested_usage_context")
            if isinstance(selection_reason, dict)
            and isinstance(selection_reason.get("requested_usage_context"), dict)
            else None
        )
        context = None
        if stored_context:
            try:
                question_usage.validate_context(stored_context)
                if (
                    stored_context.get("purpose") == "teaching"
                    and stored_context.get("purpose_role") == role
                    and stored_context.get("question_usage_policy_digest_sha256")
                    == policy["policy_digest_sha256"]
                ):
                    context = dict(stored_context)
            except ValueError:
                context = None
        if context is None:
            context = question_usage.context_for_step(
                policy,
                purpose="teaching",
                purpose_role=role,
                block_id=f"LEGACY-TEACH-{row['id']}",
                block_index=1,
            )
        record_flow_step_usage_context(
            conn,
            flow_step_id=row["id"],
            question_id=row["question_id"],
            item_version=str(row["question_item_version"] or ""),
            context=context,
            commit=False,
        )


def _backfill_attempt_evidence_revisions(conn: sqlite3.Connection) -> None:
    legacy_table = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'attempt_input_evidence'"
    ).fetchone()
    if not legacy_table:
        return
    rows = conn.execute(
        """
        select legacy.*
        from attempt_input_evidence legacy
        left join attempt_evidence_revisions revision
          on revision.attempt_id = legacy.attempt_id
        where revision.id is null
        order by legacy.created_at, legacy.id
        """
    ).fetchall()
    for row in rows:
        data = dict(row)
        record_attempt_evidence_revision(
            conn,
            attempt_id=data["attempt_id"],
            revision_kind="legacy_import",
            schema_version=str(data.get("schema_version") or multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION),
            input_mode=str(data.get("input_mode") or "typed"),
            recognition_status=str(data.get("recognition_status") or "not_required"),
            recognition_source=str(data.get("recognition_source") or "legacy_attempt_input_evidence"),
            recognized_text=str(data.get("recognized_text") or ""),
            effective_text=str(data.get("child_confirmed_text") or ""),
            recognition_confidence=data.get("recognition_confidence"),
            critical_token_uncertainties=json_load(
                data.get("critical_token_uncertainties_json"), []
            ),
            attachment_ids=json_load(data.get("attachment_ids_json"), []),
            raw={
                **json_load(data.get("raw_json"), {}),
                "legacy_evidence_id": data["id"],
                "legacy_child_confirmed": bool(data.get("child_confirmed")),
            },
            commit=False,
        )


def _validate_question_graph_references(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    source_type = item.get("source_type") or item.get("source", {}).get("type", "graph_generated")
    if source_type not in {"graph_generated", "evolved"}:
        return
    refs: set[str] = set()
    if item.get("node_id"):
        refs.add(str(item["node_id"]))
    for key in ("secondary_node_ids", "rollback_candidates", "rollback_candidate_node_ids"):
        value = item.get(key) or []
        if isinstance(value, list):
            refs.update(str(node_id) for node_id in value if str(node_id).strip())
    relations = item.get("rollback_candidate_relations") or []
    if isinstance(relations, list):
        for relation in relations:
            if isinstance(relation, dict) and relation.get("node_id"):
                refs.add(str(relation["node_id"]))
    missing = []
    for node_id in sorted(refs):
        exists = conn.execute("select 1 from graph_nodes where id = ? limit 1", (node_id,)).fetchone()
        if not exists:
            missing.append(node_id)
    if missing:
        raise ValueError(f"Question item {item.get('id')} references unknown graph nodes: {', '.join(missing)}")
    rollback_error = _question_rollback_reference_error(conn, item)
    if rollback_error:
        raise ValueError(rollback_error)


def _question_rollback_reference_error(conn: sqlite3.Connection, item: dict[str, Any]) -> str:
    source_type = item.get("source_type") or item.get("source", {}).get("type", "graph_generated")
    if source_type not in {"graph_generated", "evolved"}:
        return ""
    node_id = str(item.get("node_id") or "").strip()
    if not node_id:
        return "question_missing_primary_graph_node"
    try:
        node = get_graph_node(conn, node_id)
    except KeyError:
        return f"question_references_unknown_primary_graph_node:{node_id}"
    rollback = [
        str(candidate).strip()
        for candidate in (item.get("rollback_candidates") or item.get("rollback_candidate_node_ids") or [])
        if str(candidate).strip()
    ]
    if not rollback:
        return ""
    missing = [
        candidate for candidate in rollback
        if not conn.execute("select 1 from graph_nodes where id = ? limit 1", (candidate,)).fetchone()
    ]
    if missing:
        return f"question_references_unknown_rollback_nodes:{','.join(missing[:4])}"
    allowed = set(node.get("prerequisites", []) or [])
    allowed.update(node.get("error_diagnosis", {}).get("rollback_to") or [])
    allowed.add(node_id)
    illegal = [candidate for candidate in rollback if candidate not in allowed]
    if illegal:
        return f"question_rollback_not_on_prerequisite_chain:{','.join(illegal[:4])}"
    return ""


def row_to_question(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["secondary_node_ids"] = json_load(data.pop("secondary_node_ids_json"), [])
    data["rubric"] = json_load(data.pop("rubric_json"), [])
    data["solution_steps"] = json_load(data.pop("solution_steps_json"), [])
    data["target_error_tags"] = json_load(data.pop("error_tags_json"), [])
    data["rollback_candidate_node_ids"] = json_load(data.pop("rollback_candidate_node_ids_json"), [])
    data["rollback_candidate_relations"] = json_load(data.pop("rollback_candidate_relations_json"), [])
    data["source"] = json_load(data.pop("source_json"), {})
    data["raw"] = json_load(data.pop("raw_json"), {})
    if isinstance(data["raw"], dict):
        for key in (
            "age_floor",
            "selection_priority",
            "design_intent",
            "quality",
            "cognitive_level",
            "item_purpose",
            "requires_reasoning",
            "review_agent_check",
            "challenge_profile",
            "problem_family_id",
            "core_stem_id",
            "problem_instance_id",
            "node_alignment",
            "evidence_goal",
            "elicitation_mode",
            "child_surface_design",
            "intended_instruction_voice_family",
            "difficulty_vector",
            "accepted_alternatives",
            "interaction_schema",
            "node_local_mainline",
            "controlled_stretch",
            "scoring_targets",
            "assessment_policy",
            "usage_policy",
            "question_visual_asset_ref",
            "question_visual",
        ):
            if key in data["raw"]:
                data[key] = data["raw"][key]
        raw_quality = data["raw"].get("quality")
        if isinstance(raw_quality, dict) and "assessment_policy" in raw_quality:
            data["assessment_policy"] = raw_quality["assessment_policy"]
    return data


def question_snapshot_payload(question: dict[str, Any]) -> dict[str, Any]:
    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    node_alignment = question.get("node_alignment") if isinstance(question.get("node_alignment"), dict) else {}
    return {
        "id": question.get("id", ""),
        "item_version": question.get("item_version", ""),
        "source_type": question.get("source_type") or source.get("type", ""),
        "node_id": question.get("node_id", ""),
        "kind": question.get("kind", ""),
        "question_type": question.get("question_type", ""),
        "variant_level": question.get("variant_level", ""),
        "prompt": question.get("prompt", ""),
        "answer_format": question.get("answer_format", ""),
        "expected_answer": question.get("expected_answer", ""),
        "interaction_schema": question.get("interaction_schema") or {},
        "question_visual": question.get("question_visual") or {},
        "rubric": question.get("rubric", []),
        "solution_steps": question.get("solution_steps", []),
        "target_error_tags": question.get("target_error_tags", []),
        "rollback_candidate_node_ids": question.get("rollback_candidate_node_ids", []),
        "problem_family_id": (
            question.get("problem_family_id")
            or source.get("problem_family_id")
            or node_alignment.get("problem_family_id")
            or ""
        ),
        "core_stem_id": (
            question.get("core_stem_id")
            or source.get("core_stem_id")
            or node_alignment.get("core_stem_id")
            or ""
        ),
        "problem_instance_id": (
            question.get("problem_instance_id")
            or source.get("problem_instance_id")
            or node_alignment.get("problem_instance_id")
            or ""
        ),
    }


def question_snapshot_hash(question: dict[str, Any]) -> str:
    return _digest_json(question_snapshot_payload(question))


def question_snapshot_hashes_for_ids(conn: sqlite3.Connection, question_ids: Sequence[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for question_id in question_ids:
        question_id = str(question_id or "").strip()
        if not question_id:
            continue
        hashes[question_id] = question_snapshot_hash(get_question(conn, question_id))
    return hashes


def learning_session_question_snapshot_mismatches(
    conn: sqlite3.Connection,
    session: dict[str, Any],
) -> list[str]:
    expected_hashes = session.get("question_snapshot_hashes")
    if not isinstance(expected_hashes, dict) or not expected_hashes:
        return []
    mismatches: list[str] = []
    for question_id in session.get("expected_question_ids") or []:
        question_id = str(question_id or "").strip()
        if not question_id:
            continue
        expected_hash = str(expected_hashes.get(question_id) or "")
        if not expected_hash:
            mismatches.append(question_id)
            continue
        try:
            current_hash = question_snapshot_hash(get_question(conn, question_id))
        except KeyError:
            mismatches.append(question_id)
            continue
        if current_hash != expected_hash:
            mismatches.append(question_id)
    return mismatches


def learning_session_questions_are_current(conn: sqlite3.Connection, session: dict[str, Any]) -> bool:
    question_ids = session.get("expected_question_ids") or []
    return (
        not stale_active_question_ids(conn, question_ids)
        and not learning_session_question_snapshot_mismatches(conn, session)
    )


def assert_learning_session_questions_current(conn: sqlite3.Connection, session: dict[str, Any]) -> None:
    question_ids = session.get("expected_question_ids") or []
    stale = stale_active_question_ids(conn, question_ids)
    snapshot_mismatches = learning_session_question_snapshot_mismatches(conn, session)
    if stale or snapshot_mismatches:
        parts = []
        if stale:
            parts.append("stale=" + ", ".join(stale[:5]))
        if snapshot_mismatches:
            parts.append("snapshot_changed=" + ", ".join(snapshot_mismatches[:5]))
        raise ValueError("Learning session question set is no longer current: " + "; ".join(parts))


def get_graph_node(conn: sqlite3.Connection, node_id: str) -> dict[str, Any]:
    row = conn.execute("select raw_json from graph_nodes where id = ?", (node_id,)).fetchone()
    if not row:
        raise KeyError(f"Unknown graph node: {node_id}")
    return json_load(row["raw_json"], {})


DIMENSION_TARGET_TAGS = {
    "final_answer": ["calculation_or_symbol"],
    "model_or_relation": ["concept_confusion", "modeling_or_reading"],
    "steps": ["process_habit"],
    "symbols_units": ["calculation_or_symbol", "process_habit"],
    "check_or_explanation": ["process_habit", "concept_confusion"],
}


def _recent_question_ids_for_node(conn: sqlite3.Connection, node_id: str, limit: int = 30) -> set[str]:
    rows = conn.execute(
        """
        select question_id
        from attempts
        where node_id = ?
          and evidence_status = 'active'
        order by created_at desc, id desc
        limit ?
        """,
        (node_id, limit),
    ).fetchall()
    return {row["question_id"] for row in rows}


def _question_selection_score(
    question: dict[str, Any],
    *,
    prefer_evolved: bool,
    preferred_kinds: Sequence[str] | None,
    target_error_tags: Sequence[str] | None,
    unstable_dimensions: Sequence[str] | None,
    preferred_question_ids: Sequence[str] | None,
    avoid_question_ids: set[str],
    rotate_seed: str,
) -> tuple[float, str]:
    score = 0.0
    reasons: list[str] = []
    preferred_ids = set(preferred_question_ids or [])
    if question["id"] in preferred_ids:
        score += 200
        reasons.append("created_or_preferred_question")
    if question["id"] in avoid_question_ids:
        score -= 80
        reasons.append("recently_attempted_penalty")

    if prefer_evolved:
        if question.get("source_type") == "evolved":
            score += 45
            reasons.append("prefer_evolved")
    elif question.get("source_type") == "graph_generated":
        score += 25
        reasons.append("prefer_graph_generated")

    if preferred_kinds:
        try:
            kind_rank = list(preferred_kinds).index(question.get("kind", ""))
        except ValueError:
            kind_rank = len(preferred_kinds)
        score += max(0, 30 - kind_rank * 5)
        if kind_rank < len(preferred_kinds):
            reasons.append(f"kind:{question.get('kind')}")

    question_tags = set(question.get("target_error_tags") or [])
    requested_tags = {
        tag for tag in (target_error_tags or [])
        if tag in question_bank.CANONICAL_ERROR_TAGS
    }
    if requested_tags:
        overlap = question_tags & requested_tags
        if overlap:
            score += 35 + 5 * len(overlap)
            reasons.append("error_tag_match:" + ",".join(sorted(overlap)))
        else:
            score -= 12

    dimension_tags: set[str] = set()
    for dimension in unstable_dimensions or []:
        dimension_tags.update(DIMENSION_TARGET_TAGS.get(str(dimension), []))
    if dimension_tags:
        overlap = question_tags & dimension_tags
        if overlap:
            score += 24 + 4 * len(overlap)
            reasons.append("dimension_match:" + ",".join(sorted(overlap)))

    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    evidence_tag = source.get("evidence_error_tag")
    if evidence_tag and evidence_tag in requested_tags:
        score += 30
        reasons.append(f"evolved_evidence_tag:{evidence_tag}")

    has_diagnostic_signal = any([target_error_tags, unstable_dimensions, preferred_question_ids])
    if has_diagnostic_signal:
        digest = hashlib.sha256(f"{rotate_seed}:{question['id']}".encode("utf-8")).hexdigest()
        score += int(digest[:4], 16) / 65536
    return score, ";".join(reasons) or "latest_approved_candidate"


def find_question_for_node(
    conn: sqlite3.Connection,
    node_id: str,
    prefer_evolved: bool = False,
    preferred_kinds: Sequence[str] | None = None,
    target_error_tags: Sequence[str] | None = None,
    unstable_dimensions: Sequence[str] | None = None,
    preferred_question_ids: Sequence[str] | None = None,
    avoid_question_ids: Sequence[str] | None = None,
    rotate_seed: str | None = None,
    question_bank_version: str | None = None,
) -> dict[str, Any]:
    source_order = "case when q.source_type = 'evolved' then 0 when q.source_type = 'graph_generated' then 1 else 2 end" if prefer_evolved else "case when q.source_type = 'graph_generated' then 0 when q.source_type = 'evolved' then 1 else 2 end"
    active_version = question_bank_version or get_active_question_bank_version(conn)
    params: list[Any] = [node_id, active_version, question_bank.EVOLVED_ITEM_VERSION]
    kind_order = ""
    if preferred_kinds:
        kind_order = "case " + " ".join(f"when q.kind = ? then {index}" for index, _ in enumerate(preferred_kinds)) + f" else {len(preferred_kinds)} end,"
        params.extend(preferred_kinds)
    rows = conn.execute(
        f"""
        select q.*
        from question_items q
        where q.node_id = ?
          and (
            (q.source_type = 'graph_generated' and q.item_version = ?)
            or (q.source_type = 'evolved' and q.item_version = ?)
            or q.source_type not in ('graph_generated', 'evolved')
          )
        order by {source_order}, {kind_order} q.item_version desc,
          coalesce((
            select max(r.reviewed_at)
            from question_review_records r
            where r.question_id = q.id
              and r.item_version = q.item_version
              and r.source_type = q.source_type
              and r.review_status = 'approved'
              and r.active_eligible = 1
          ), '') desc,
          q.rowid desc, q.variant_level, q.id desc
        limit 200
        """,
        params,
    ).fetchall()
    approved: list[dict[str, Any]] = []
    for row in rows:
        question = row_to_question(row)
        if is_child_schedulable_question(conn, question, question_bank_version=active_version):
            approved.append(question)
    if approved:
        avoid = set(avoid_question_ids or []) | _recent_question_ids_for_node(conn, node_id)
        if not any([preferred_kinds, target_error_tags, unstable_dimensions, preferred_question_ids, avoid_question_ids, avoid]):
            question = approved[0]
            question["selection_reason"] = "latest_approved_candidate"
            question["selection_signal"] = {
                "target_error_tags": [],
                "unstable_dimensions": [],
                "preferred_question_ids": [],
                "avoided_recent_question_ids": [],
            }
            return question
        seed = rotate_seed or f"{node_id}:{now_iso()[:10]}"
        scored = [
            (
                *_question_selection_score(
                    question,
                    prefer_evolved=prefer_evolved,
                    preferred_kinds=preferred_kinds,
                    target_error_tags=target_error_tags,
                    unstable_dimensions=unstable_dimensions,
                    preferred_question_ids=preferred_question_ids,
                    avoid_question_ids=avoid,
                    rotate_seed=seed,
                ),
                question,
            )
            for question in approved
        ]
        best = max(scored, key=lambda item: item[0])
        question = best[2]
        question["selection_reason"] = best[1]
        question["selection_signal"] = {
            "target_error_tags": list(target_error_tags or []),
            "unstable_dimensions": list(unstable_dimensions or []),
            "preferred_question_ids": list(preferred_question_ids or []),
            "avoided_recent_question_ids": sorted(avoid),
        }
        return question
    if not rows:
        raise KeyError(f"No question for node: {node_id}")
    raise KeyError(f"No reviewer-approved active question for node: {node_id}")


def get_question(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    row = conn.execute("select * from question_items where id = ?", (question_id,)).fetchone()
    if not row:
        raise KeyError(f"Unknown question: {question_id}")
    return row_to_question(row)


def is_current_active_question(question: dict[str, Any], *, question_bank_version: str | None = None) -> bool:
    source_type = question.get("source_type") or question.get("source", {}).get("type")
    if source_type == "graph_generated":
        expected_version = question_bank_version or question_bank.QUESTION_BANK_VERSION
        return (
            question.get("item_version") == expected_version
            and question_bank.is_item_approved_for_active_use(question)
        )
    if source_type == "evolved":
        return (
            question.get("item_version") == question_bank.EVOLVED_ITEM_VERSION
            and question_bank.is_item_approved_for_active_use(question)
        )
    return True


def _evolved_question_source_invalidated(question: dict[str, Any]) -> bool:
    source_type = question.get("source_type") or question.get("source", {}).get("type")
    if source_type != "evolved":
        return False
    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    raw_source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    return source.get("evidence_status") == "invalidated" or raw_source.get("evidence_status") == "invalidated"


def _evolved_question_source_attempt_issue(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    *,
    seen_question_ids: set[str] | None = None,
    question_bank_version: str | None = None,
) -> dict[str, Any] | None:
    source_type = question.get("source_type") or question.get("source", {}).get("type")
    if source_type != "evolved":
        return None
    seen = set(seen_question_ids or set())
    question_id = str(question.get("id") or "").strip()
    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
    raw_source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    attempt_id = str(source.get("attempt_id") or raw_source.get("attempt_id") or "").strip()
    if not attempt_id:
        return {
            "question_id": question.get("id"),
            "source_attempt_id": "",
            "reason": "missing_source_attempt_id",
        }
    row = conn.execute("select * from attempts where id = ?", (attempt_id,)).fetchone()
    if not row:
        return {
            "question_id": question.get("id"),
            "source_attempt_id": attempt_id,
            "reason": "source_attempt_not_found",
        }
    attempt = attempt_row_to_dict(row)
    if attempt.get("evidence_status") != "active":
        return {
            "question_id": question.get("id"),
            "source_attempt_id": attempt_id,
            "reason": f"source_attempt_evidence_status:{attempt.get('evidence_status')}",
        }
    if attempt.get("grading_status") != "graded":
        return {
            "question_id": question.get("id"),
            "source_attempt_id": attempt_id,
            "reason": f"source_attempt_grading_status:{attempt.get('grading_status')}",
        }
    if not is_valid_answer_analysis(attempt.get("answer_analysis")):
        return {
            "question_id": question.get("id"),
            "source_attempt_id": attempt_id,
            "reason": "source_attempt_missing_valid_answer_analysis",
        }
    source_question_id = str(attempt.get("question_id") or "").strip()
    if not source_question_id:
        return {
            "question_id": question.get("id"),
            "source_attempt_id": attempt_id,
            "reason": "source_attempt_missing_question_id",
        }
    if source_question_id == question_id or source_question_id in seen:
        return {
            "question_id": question.get("id"),
            "source_attempt_id": attempt_id,
            "reason": "source_attempt_question_cycle",
        }
    try:
        source_question = get_question(conn, source_question_id)
    except KeyError:
        return {
            "question_id": question.get("id"),
            "source_attempt_id": attempt_id,
            "reason": "source_attempt_question_not_found",
        }
    source_question_bank_version = str(attempt.get("question_bank_version") or question_bank_version or "")
    if not _is_child_schedulable_question(
        conn,
        source_question,
        seen_question_ids=seen,
        question_bank_version=source_question_bank_version or None,
    ):
        return {
            "question_id": question.get("id"),
            "source_attempt_id": attempt_id,
            "reason": "source_attempt_question_not_current_child_schedulable",
        }
    return None


def question_review_record_allows_active_use(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    review_record_id: str | None,
) -> bool:
    source_type = question.get("source_type") or question.get("source", {}).get("type")
    if not source_type or not review_record_id:
        return False
    row = conn.execute(
        """
        select reviewer_run_id, candidate_sha256
        from question_review_records
        where id = ?
          and question_id = ?
          and item_version = ?
          and source_type = ?
          and review_status = 'approved'
          and active_eligible = 1
          and reviewer_run_id is not null
          and reviewer_run_id <> ''
        limit 1
        """,
        (review_record_id, question.get("id"), question.get("item_version"), source_type),
    ).fetchone()
    current_candidate = question.get("raw") if isinstance(question.get("raw"), dict) else question
    current_candidate_digests = {
        _digest_json(current_candidate),
        _canonical_digest_json(current_candidate),
    }
    return (
        bool(row)
        and row["candidate_sha256"] in current_candidate_digests
        and _reviewer_run_authorizes_question_review(
            conn,
            row["reviewer_run_id"],
            current_candidate,
            source_type,
        )
    )


def _has_active_question_review_record(conn: sqlite3.Connection, question: dict[str, Any]) -> bool:
    source_type = question.get("source_type") or question.get("source", {}).get("type")
    if not source_type:
        return False
    rows = conn.execute(
        """
        select id
        from question_review_records
        where question_id = ?
          and item_version = ?
          and source_type = ?
          and review_status = 'approved'
          and active_eligible = 1
          and reviewer_run_id is not null
          and reviewer_run_id <> ''
        """,
        (question.get("id"), question.get("item_version"), source_type),
    ).fetchall()
    return any(question_review_record_allows_active_use(conn, question, row["id"]) for row in rows)


def _is_child_schedulable_question(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    *,
    seen_question_ids: set[str] | None = None,
    question_bank_version: str | None = None,
) -> bool:
    """v2/v5 active-use seam: graph-bound, bank-version scoped, reviewer-approved question."""
    seen = set(seen_question_ids or set())
    question_id = str(question.get("id") or "").strip()
    if question_id and question_id in seen:
        return False
    if question_id:
        seen.add(question_id)
    if not question.get("node_id"):
        return False
    expected_version = question_bank_version or get_active_question_bank_version(conn)
    if not is_current_active_question(question, question_bank_version=expected_version):
        return False
    if _evolved_question_source_invalidated(question):
        return False
    if _question_rollback_reference_error(conn, question):
        return False
    if _evolved_question_source_attempt_issue(
        conn,
        question,
        seen_question_ids=seen,
        question_bank_version=expected_version,
    ):
        return False
    return _has_active_question_review_record(conn, question)


def is_child_schedulable_question(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    *,
    question_bank_version: str | None = None,
) -> bool:
    return _is_child_schedulable_question(
        conn,
        question,
        seen_question_ids=set(),
        question_bank_version=question_bank_version,
    )


def is_current_attempt_question(conn: sqlite3.Connection, attempt: dict[str, Any]) -> bool:
    try:
        question = get_question(conn, attempt["question_id"])
    except KeyError:
        return False
    if question.get("node_id") != attempt.get("node_id"):
        return False
    attempt_bank_version = str(attempt.get("question_bank_version") or "")
    return is_child_schedulable_question(
        conn,
        question,
        question_bank_version=attempt_bank_version or None,
    )


def attempt_review_meta_allows_downstream_evidence(attempt: dict[str, Any]) -> bool:
    review_meta = attempt.get("review_meta")
    if not isinstance(review_meta, dict) or not review_meta:
        return True
    if review_meta.get("confidence_policy") == LOW_CONFIDENCE_NO_EVIDENCE_POLICY:
        return False
    if review_meta.get("status") in {"low_confidence", "photo_ocr_unusable", "error", "not_configured", "queued"}:
        return False
    if "confidence" not in review_meta:
        return True
    try:
        confidence = float(review_meta.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return False
    return confidence >= MIN_REVIEW_CONFIDENCE_FOR_DOWNSTREAM_EVIDENCE


def is_current_usable_attempt_evidence(conn: sqlite3.Connection, attempt: dict[str, Any]) -> bool:
    try:
        input_evidence = latest_attempt_evidence_revision(
            conn, str(attempt.get("id") or "")
        )
    except KeyError:
        input_evidence = None
    return (
        attempt.get("evidence_status") == "active"
        and attempt.get("grading_status") == "graded"
        and is_valid_answer_analysis(attempt.get("answer_analysis"))
        and is_current_attempt_question(conn, attempt)
        and attempt_review_meta_allows_downstream_evidence(attempt)
        and multimodal_evidence.allows_downstream_evidence(input_evidence)
    )


def is_evolution_source_valid(conn: sqlite3.Connection, attempt: dict[str, Any]) -> bool:
    """v2 self-evolution source seam; false for pending, stale, fake, malformed, or invalidated evidence."""
    return EvidenceUsePolicy.is_usable_attempt(conn, attempt)


def current_active_attempts(
    conn: sqlite3.Connection,
    *,
    grading_status: str | None = None,
    processed_evolution_event_id_is_null: bool | None = None,
) -> list[dict[str, Any]]:
    filters = [
        "a.evidence_status = 'active'",
        """
        (
          (q.source_type = 'graph_generated' and q.item_version = ?)
          or (q.source_type = 'evolved' and q.item_version = ?)
          or q.source_type not in ('graph_generated', 'evolved')
        )
        """,
    ]
    params: list[Any] = [question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION]
    if grading_status:
        filters.append("a.grading_status = ?")
        params.append(grading_status)
    if processed_evolution_event_id_is_null is True:
        filters.append("a.processed_evolution_event_id is null")
    elif processed_evolution_event_id_is_null is False:
        filters.append("a.processed_evolution_event_id is not null")
    rows = conn.execute(
        f"""
        select a.*
        from attempts a
        join question_items q on q.id = a.question_id
        where {" and ".join(filters)}
        order by a.created_at, a.id
        """,
        params,
    ).fetchall()
    attempts = [attempt_row_to_dict(row) for row in rows]
    return [attempt for attempt in attempts if is_current_attempt_question(conn, attempt)]


def current_usable_attempts(
    conn: sqlite3.Connection,
    *,
    processed_evolution_event_id_is_null: bool | None = None,
) -> list[dict[str, Any]]:
    return [
        attempt
        for attempt in current_active_attempts(
            conn,
            grading_status="graded",
            processed_evolution_event_id_is_null=processed_evolution_event_id_is_null,
        )
        if is_current_usable_attempt_evidence(conn, attempt)
    ]


def current_attempts_missing_valid_analysis(
    conn: sqlite3.Connection,
    *,
    processed_evolution_event_id_is_null: bool | None = None,
) -> list[dict[str, Any]]:
    return [
        attempt
        for attempt in current_active_attempts(
            conn,
            grading_status="graded",
            processed_evolution_event_id_is_null=processed_evolution_event_id_is_null,
        )
        if not is_valid_answer_analysis(attempt.get("answer_analysis"))
    ]


def stale_active_question_ids(conn: sqlite3.Connection, question_ids: Sequence[str]) -> list[str]:
    stale: list[str] = []
    for question_id in question_ids:
        if not question_id:
            continue
        try:
            question = get_question(conn, question_id)
        except KeyError:
            stale.append(str(question_id))
            continue
        if not is_child_schedulable_question(conn, question):
            stale.append(str(question_id))
    return stale


def assert_current_active_question_ids(conn: sqlite3.Connection, question_ids: Sequence[str]) -> None:
    stale = stale_active_question_ids(conn, question_ids)
    if stale:
        preview = ", ".join(stale[:5])
        suffix = "" if len(stale) <= 5 else f" ...(+{len(stale) - 5})"
        raise ValueError(f"Learning session contains stale question bank items: {preview}{suffix}")


def create_session(
    conn: sqlite3.Connection,
    title: str,
    mode: str = "learning",
    *,
    plan_id: str | None = None,
    expected_question_ids: list[str] | None = None,
    question_snapshot_hashes: dict[str, str] | None = None,
    status: str = "active",
    closure_status: str = "not_started",
    commit: bool = True,
) -> str:
    session_id = f"S-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into learning_sessions(
          id, title, mode, plan_id, expected_question_ids_json, question_snapshot_hashes_json,
          status, closure_status, closure_result_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            title,
            mode,
            plan_id,
            json_dump(expected_question_ids or []),
            json_dump(question_snapshot_hashes or {}),
            status,
            closure_status,
            json_dump({}),
            now_iso(),
        ),
    )
    if commit:
        conn.commit()
    return session_id


def create_learning_session_for_plan(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    title: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    expected_question_ids = [task["question_id"] for task in plan.get("tasks", []) if task.get("question_id")]
    assert_current_active_question_ids(conn, expected_question_ids)
    question_snapshot_hashes = question_snapshot_hashes_for_ids(conn, expected_question_ids)
    session_id = create_session(
        conn,
        title or plan.get("title") or "学习任务组",
        mode="child_learning_group",
        plan_id=plan.get("id"),
        expected_question_ids=expected_question_ids,
        question_snapshot_hashes=question_snapshot_hashes,
        commit=False,
    )
    if commit:
        conn.commit()
    return get_learning_session(conn, session_id)


def retire_stale_child_learning_sessions(conn: sqlite3.Connection, *, commit: bool = True) -> dict[str, Any]:
    rows = conn.execute(
        """
        select id
        from learning_sessions
        where mode = 'child_learning_group'
          and status != 'closed'
        order by created_at, id
        """
    ).fetchall()
    retired: list[dict[str, Any]] = []
    now = now_iso()
    for row in rows:
        session = get_learning_session(conn, row["id"])
        stale = stale_active_question_ids(conn, session.get("expected_question_ids") or [])
        snapshot_mismatches = learning_session_question_snapshot_mismatches(conn, session)
        if not stale and not snapshot_mismatches:
            continue
        closure_result = {
            "closure_status": "blocked",
            "blocked_reason": "stale_question_bank_session_retired",
            "stale_question_ids": stale,
            "question_snapshot_mismatches": snapshot_mismatches,
            "current_question_bank_version": question_bank.QUESTION_BANK_VERSION,
            "current_evolved_item_version": question_bank.EVOLVED_ITEM_VERSION,
        }
        conn.execute(
            """
            update learning_sessions
            set status = 'closed',
                closure_status = 'blocked',
                closure_result_json = ?,
                closed_at = ?
            where id = ?
            """,
            (json_dump(closure_result), now, row["id"]),
        )
        retired.append({
            "session_id": row["id"],
            "stale_question_ids": stale,
            "question_snapshot_mismatches": snapshot_mismatches,
        })
    if commit:
        conn.commit()
    return {"retired_count": len(retired), "retired_sessions": retired}


def get_learning_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute("select * from learning_sessions where id = ?", (session_id,)).fetchone()
    if not row:
        raise KeyError(f"Unknown learning session: {session_id}")
    data = dict(row)
    data["expected_question_ids"] = json_load(data.pop("expected_question_ids_json"), [])
    data["question_snapshot_hashes"] = json_load(data.pop("question_snapshot_hashes_json", "{}"), {})
    data["closure_result"] = json_load(data.pop("closure_result_json"), {})
    return data


def attempts_for_session(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select *
        from attempts
        where session_id = ?
          and evidence_status = 'active'
        order by created_at, id
        """,
        (session_id,),
    ).fetchall()
    return [attempt_row_to_dict(row) for row in rows]


def session_completion_summary(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    session = get_learning_session(conn, session_id)
    attempts = attempts_for_session(conn, session_id)
    submitted_question_ids = {attempt["question_id"] for attempt in attempts}
    expected_question_ids = session["expected_question_ids"]
    missing_question_ids = [question_id for question_id in expected_question_ids if question_id not in submitted_question_ids]
    graded = [attempt for attempt in attempts if attempt["grading_status"] == "graded"]
    pending = [attempt for attempt in attempts if attempt["grading_status"] == "pending_review"]
    structurally_analyzed = [attempt for attempt in graded if is_valid_answer_analysis(attempt.get("answer_analysis"))]
    usable = [attempt for attempt in structurally_analyzed if EvidenceUsePolicy.is_usable_attempt(conn, attempt)]
    unusable = [attempt for attempt in structurally_analyzed if attempt["id"] not in {item["id"] for item in usable}]
    missing_analysis = [attempt for attempt in graded if not is_valid_answer_analysis(attempt.get("answer_analysis"))]
    unusable_attempt_ids = [attempt["id"] for attempt in unusable]
    return {
        "session_id": session_id,
        "expected": len(expected_question_ids),
        "submitted": len(submitted_question_ids),
        "attempt_count": len(attempts),
        "graded": len(graded),
        "pending": len(pending),
        "analyzed": len(usable),
        "structurally_analyzed": len(structurally_analyzed),
        "usable": len(usable),
        "missing_question_ids": missing_question_ids,
        "pending_attempt_ids": [attempt["id"] for attempt in pending],
        "missing_analysis_attempt_ids": [attempt["id"] for attempt in missing_analysis],
        "unusable_evidence_attempt_ids": unusable_attempt_ids,
        "missing_or_unusable_evidence_attempt_ids": [attempt["id"] for attempt in missing_analysis] + unusable_attempt_ids,
        "graded_attempt_ids": [attempt["id"] for attempt in graded],
        "structurally_analyzed_attempt_ids": [attempt["id"] for attempt in structurally_analyzed],
        "usable_attempt_ids": [attempt["id"] for attempt in usable],
        "analyzed_attempt_ids": [attempt["id"] for attempt in usable],
    }


def update_session_closure_state(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    status: str | None = None,
    closure_status: str | None = None,
    closure_result: dict[str, Any] | None = None,
    next_plan_id: str | None = None,
    closed_at: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    existing = get_learning_session(conn, session_id)
    conn.execute(
        """
        update learning_sessions
        set status = ?,
            closure_status = ?,
            closure_result_json = ?,
            next_plan_id = ?,
            closed_at = ?
        where id = ?
        """,
        (
            status or existing["status"],
            closure_status or existing["closure_status"],
            json_dump(closure_result if closure_result is not None else existing["closure_result"]),
            next_plan_id if next_plan_id is not None else existing.get("next_plan_id"),
            closed_at if closed_at is not None else existing.get("closed_at"),
            session_id,
        ),
    )
    if commit:
        conn.commit()
    return get_learning_session(conn, session_id)


def record_attempt(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    question_id: str,
    node_id: str,
    result: str,
    score_points: float,
    max_points: float,
    error_tags: list[str],
    answer_raw: str | None,
    parent_note: str,
    answer_analysis: dict[str, Any] | None = None,
    review_meta: dict[str, Any] | None = None,
    cause_analysis: dict[str, Any] | None = None,
    interaction_response: dict[str, Any] | None = None,
    evidence_status: str = "active",
    evidence_note: str = "",
    explanation_score: int | None = None,
    blocking_evidence: bool = False,
    grading_status: str = "graded",
    question_bank_version: str | None = None,
    commit: bool = True,
) -> str:
    _validate_attempt_values(
        result=result,
        grading_status=grading_status,
        score_points=score_points,
        max_points=max_points,
        error_tags=error_tags,
        explanation_score=explanation_score,
        blocking_evidence=blocking_evidence,
    )
    if evidence_status not in {"active", "invalidated", "stale"}:
        raise ValueError(f"Invalid evidence status: {evidence_status}")
    question = get_question(conn, question_id)
    if question.get("node_id") != node_id:
        raise ValueError("Attempt node_id must match question node_id")
    try:
        session = get_learning_session(conn, session_id)
    except KeyError:
        session = {}
    if session.get("mode") == "child_learning_group":
        expected_question_ids = session.get("expected_question_ids") or []
        if expected_question_ids and question_id not in expected_question_ids:
            raise ValueError("Question does not belong to this learning session")
        assert_learning_session_questions_current(conn, session)
    if evidence_status == "active":
        source = question.get("source") if isinstance(question.get("source"), dict) else {}
        raw = question.get("raw") if isinstance(question.get("raw"), dict) else {}
        raw_source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        if (
            question.get("source_type") == "evolved"
            and (source.get("evidence_status") == "invalidated" or raw_source.get("evidence_status") == "invalidated")
        ):
            raise ValueError("Cannot record active attempt for a question based on invalidated evidence")
        if not is_child_schedulable_question(conn, question, question_bank_version=question_bank_version):
            raise ValueError("Cannot record active attempt for a question that is not reviewer-approved for child active use")
    if answer_analysis is not None:
        validate_answer_analysis(answer_analysis)
    attempt_id = f"A-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into attempts(
          id, session_id, question_id, node_id, result, grading_status, evidence_status,
          score_points, max_points, error_tags_json, answer_raw, parent_note, evidence_note,
          explanation_score, answer_analysis_json, review_meta_json, cause_analysis_json, interaction_response_json,
          blocking_evidence, question_bank_version, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt_id,
            session_id,
            question_id,
            node_id,
            result,
            grading_status,
            evidence_status,
            score_points,
            max_points,
            json_dump(error_tags),
            answer_raw,
            parent_note,
            evidence_note,
            explanation_score,
            json_dump(answer_analysis or {}),
            json_dump(review_meta or {}),
            json_dump(cause_analysis or {}),
            json_dump(interaction_response or {}),
            1 if blocking_evidence else 0,
            str(question_bank_version or ""),
            now_iso(),
        ),
    )
    if commit:
        conn.commit()
    return attempt_id


def attempt_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["error_tags"] = json_load(data.pop("error_tags_json"), [])
    data["answer_analysis"] = json_load(data.pop("answer_analysis_json", "{}"), {})
    data["review_meta"] = json_load(data.pop("review_meta_json", "{}"), {})
    data["cause_analysis"] = json_load(data.pop("cause_analysis_json", "{}"), {})
    data["interaction_response"] = json_load(data.pop("interaction_response_json", "{}"), {})
    data["attachment_ids"] = json_load(data.pop("attachment_ids_json", "[]"), [])
    data["evidence_status"] = data.get("evidence_status", "active")
    data["evidence_note"] = data.get("evidence_note", "")
    data["blocking_evidence"] = bool(data["blocking_evidence"])
    return data


def record_attempt_attachment(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    kind: str,
    original_filename: str,
    filename: str,
    content_type: str,
    byte_size: int,
    sha256: str,
    relative_path: str,
    source: str = "answer_photo_data_url",
    commit: bool = True,
) -> dict[str, Any]:
    attachment_id = f"AT-{uuid.uuid4().hex[:12]}"
    created_at = now_iso()
    conn.execute(
        """
        insert into attempt_attachments(
          id, attempt_id, kind, original_filename, filename, content_type,
          byte_size, sha256, source, relative_path, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attachment_id,
            attempt_id,
            kind,
            original_filename,
            filename,
            content_type,
            byte_size,
            sha256,
            source,
            relative_path,
            created_at,
        ),
    )
    if commit:
        conn.commit()
    return {
        "id": attachment_id,
        "attempt_id": attempt_id,
        "kind": kind,
        "original_filename": original_filename,
        "filename": filename,
        "content_type": content_type,
        "byte_size": byte_size,
        "sha256": sha256,
        "source": source,
        "relative_path": relative_path,
        "created_at": created_at,
    }


def attachments_for_attempt(conn: sqlite3.Connection, attempt_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, attempt_id, kind, original_filename, filename, content_type,
               byte_size, sha256, source, relative_path, created_at
        from attempt_attachments
        where attempt_id = ?
        order by created_at, id
        """,
        (attempt_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_attachment(conn: sqlite3.Connection, attachment_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        select id, attempt_id, kind, original_filename, filename, content_type,
               byte_size, sha256, source, relative_path, created_at
        from attempt_attachments
        where id = ?
        """,
        (attachment_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"Unknown attachment: {attachment_id}")
    return dict(row)


def media_recognition_run_row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["math_objects"] = json_load(data.pop("math_objects_json", "[]"), [])
    data["critical_token_uncertainties"] = json_load(
        data.pop("critical_token_uncertainties_json", "[]"), []
    )
    return data


def find_media_recognition_run(
    conn: sqlite3.Connection,
    *,
    flow_step_id: str,
    step_revision: int,
    input_mode: str,
    media_sha256: str,
    media_byte_size: int,
    media_version: int,
    recognizer_version: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select * from media_recognition_runs
        where flow_step_id = ? and step_revision = ? and input_mode = ?
          and media_sha256 = ? and media_byte_size = ? and media_version = ?
          and recognizer_version = ?
        limit 1
        """,
        (
            flow_step_id,
            int(step_revision),
            input_mode,
            media_sha256,
            int(media_byte_size),
            int(media_version),
            recognizer_version,
        ),
    ).fetchone()
    return media_recognition_run_row_to_dict(row) if row else None


def record_media_recognition_run(
    conn: sqlite3.Connection,
    *,
    flow_step_id: str,
    step_revision: int,
    question_id: str,
    input_mode: str,
    media_sha256: str,
    media_byte_size: int,
    media_version: int,
    content_type: str,
    recognizer_version: str,
    recognition_status: str,
    provider_mode: str,
    recognition_source: str,
    trust_classification: str | None = None,
    route_digest_sha256: str,
    recognized_text: str,
    math_objects: list[Any] | None = None,
    critical_token_uncertainties: list[dict[str, Any]] | None = None,
    recognition_confidence: float | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    if input_mode not in {"handwriting", "voice", "photo", "mixed"}:
        raise ValueError("media recognition input mode must be handwriting, voice, photo, or mixed")
    if recognition_status not in multimodal_evidence.RECOGNITION_RUN_STATUSES:
        raise ValueError("unknown media recognition status")
    if not media_sha256 or int(media_byte_size) <= 0 or int(media_version) <= 0:
        raise ValueError("media recognition requires immutable media identity")
    if recognition_confidence is not None and not 0.0 <= float(recognition_confidence) <= 1.0:
        raise ValueError("recognition confidence must be between 0 and 1")
    trust_classification = trust_classification or multimodal_evidence.recognition_trust_classification(
        input_mode=input_mode,
        provider_mode=provider_mode,
        recognition_source=recognition_source,
    )
    if trust_classification not in multimodal_evidence.RECOGNITION_TRUST_CLASSIFICATIONS:
        raise ValueError("unknown recognition trust classification")
    existing = find_media_recognition_run(
        conn,
        flow_step_id=flow_step_id,
        step_revision=step_revision,
        input_mode=input_mode,
        media_sha256=media_sha256,
        media_byte_size=media_byte_size,
        media_version=media_version,
        recognizer_version=recognizer_version,
    )
    if existing:
        return existing
    payload = {
        "flow_step_id": flow_step_id,
        "step_revision": int(step_revision),
        "question_id": question_id,
        "input_mode": input_mode,
        "media_sha256": media_sha256,
        "media_byte_size": int(media_byte_size),
        "media_version": int(media_version),
        "content_type": content_type,
        "recognizer_version": recognizer_version,
        "recognition_status": recognition_status,
        "provider_mode": provider_mode,
        "recognition_source": recognition_source,
        "trust_classification": trust_classification,
        "route_digest_sha256": route_digest_sha256,
        "recognized_text": str(recognized_text or "")[:4000],
        "math_objects": list(math_objects or []),
        "critical_token_uncertainties": list(critical_token_uncertainties or []),
        "recognition_confidence": recognition_confidence,
    }
    run_id = f"MR-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into media_recognition_runs(
          id, flow_step_id, step_revision, question_id, input_mode,
          media_sha256, media_byte_size, media_version, content_type,
          recognizer_version, recognition_status, provider_mode,
          recognition_source, trust_classification, route_digest_sha256, recognized_text,
          math_objects_json, critical_token_uncertainties_json,
          recognition_confidence, output_digest_sha256, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            flow_step_id,
            int(step_revision),
            question_id,
            input_mode,
            media_sha256,
            int(media_byte_size),
            int(media_version),
            content_type,
            recognizer_version,
            recognition_status,
            provider_mode,
            recognition_source,
            trust_classification,
            route_digest_sha256,
            payload["recognized_text"],
            json_dump(payload["math_objects"]),
            json_dump(payload["critical_token_uncertainties"]),
            recognition_confidence,
            _canonical_digest_json(payload),
            now_iso(),
        ),
    )
    if commit:
        conn.commit()
    return get_media_recognition_run(conn, run_id)


def get_media_recognition_run(conn: sqlite3.Connection, recognition_handle: str) -> dict[str, Any]:
    row = conn.execute(
        "select * from media_recognition_runs where id = ? limit 1",
        (recognition_handle,),
    ).fetchone()
    if not row:
        raise KeyError(f"Unknown media recognition handle: {recognition_handle}")
    return media_recognition_run_row_to_dict(row)


def validate_media_recognition_run_integrity(recognition_run: dict[str, Any]) -> None:
    payload = {
        "flow_step_id": recognition_run.get("flow_step_id"),
        "step_revision": int(recognition_run.get("step_revision") or 0),
        "question_id": recognition_run.get("question_id"),
        "input_mode": recognition_run.get("input_mode"),
        "media_sha256": recognition_run.get("media_sha256"),
        "media_byte_size": int(recognition_run.get("media_byte_size") or 0),
        "media_version": int(recognition_run.get("media_version") or 0),
        "content_type": recognition_run.get("content_type"),
        "recognizer_version": recognition_run.get("recognizer_version"),
        "recognition_status": recognition_run.get("recognition_status"),
        "provider_mode": recognition_run.get("provider_mode"),
        "recognition_source": recognition_run.get("recognition_source"),
        "trust_classification": recognition_run.get("trust_classification"),
        "route_digest_sha256": recognition_run.get("route_digest_sha256"),
        "recognized_text": str(recognition_run.get("recognized_text") or "")[:4000],
        "math_objects": list(recognition_run.get("math_objects") or []),
        "critical_token_uncertainties": list(
            recognition_run.get("critical_token_uncertainties") or []
        ),
        "recognition_confidence": recognition_run.get("recognition_confidence"),
    }
    if _canonical_digest_json(payload) != str(
        recognition_run.get("output_digest_sha256") or ""
    ):
        raise ValueError("media recognition output digest mismatch")


def evidence_confirmation_row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["client_corrections"] = json_load(data.pop("client_corrections_json", "[]"), [])
    return data


def get_evidence_confirmation(conn: sqlite3.Connection, confirmation_id: str) -> dict[str, Any]:
    row = conn.execute(
        "select * from evidence_confirmations where id = ? limit 1",
        (confirmation_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"Unknown evidence confirmation: {confirmation_id}")
    return evidence_confirmation_row_to_dict(row)


def record_evidence_confirmation(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    recognition_run_id: str,
    action: str,
    confirmed_text: str,
    client_corrections: list[Any] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    if action not in {"confirmed", "corrected", "rejected"}:
        raise ValueError("unknown evidence confirmation action")
    text = str(confirmed_text or "").strip()[:4000]
    if action in {"confirmed", "corrected"} and not text:
        raise ValueError("confirmed evidence text is required")
    get_attempt(conn, attempt_id)
    get_media_recognition_run(conn, recognition_run_id)
    corrections = list(client_corrections or [])[:50]
    digest = _canonical_digest_json({
        "attempt_id": attempt_id,
        "recognition_run_id": recognition_run_id,
        "action": action,
        "confirmed_text": text,
        "client_corrections": corrections,
    })
    existing = conn.execute(
        """
        select * from evidence_confirmations
        where attempt_id = ? and recognition_run_id = ?
          and confirmation_digest_sha256 = ?
        limit 1
        """,
        (attempt_id, recognition_run_id, digest),
    ).fetchone()
    if existing:
        return evidence_confirmation_row_to_dict(existing)
    version = int(conn.execute(
        "select coalesce(max(confirmation_version), 0) + 1 from evidence_confirmations where attempt_id = ?",
        (attempt_id,),
    ).fetchone()[0])
    confirmation_id = f"EC-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into evidence_confirmations(
          id, attempt_id, recognition_run_id, confirmation_version,
          action, confirmed_text, client_corrections_json,
          confirmation_digest_sha256, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            confirmation_id,
            attempt_id,
            recognition_run_id,
            version,
            action,
            text,
            json_dump(corrections),
            digest,
            now_iso(),
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute("select * from evidence_confirmations where id = ?", (confirmation_id,)).fetchone()
    return evidence_confirmation_row_to_dict(row)


def attempt_evidence_revision_row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["critical_token_uncertainties"] = json_load(
        data.pop("critical_token_uncertainties_json", "[]"), []
    )
    data["attachment_ids"] = json_load(data.pop("attachment_ids_json", "[]"), [])
    data["raw"] = json_load(data.pop("raw_json", "{}"), {})
    data["child_confirmed"] = bool(data.get("confirmation_id")) and data.get("recognition_status") in {"confirmed", "corrected"}
    data["child_confirmed_text"] = data.get("effective_text") or ""
    return data


def attempt_evidence_revisions(conn: sqlite3.Connection, attempt_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select * from attempt_evidence_revisions where attempt_id = ? order by revision_number, id",
        (attempt_id,),
    ).fetchall()
    return [attempt_evidence_revision_row_to_dict(row) for row in rows]


def get_attempt_evidence_revision(conn: sqlite3.Connection, revision_id: str) -> dict[str, Any]:
    row = conn.execute(
        "select * from attempt_evidence_revisions where id = ? limit 1",
        (revision_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"Unknown attempt evidence revision: {revision_id}")
    return attempt_evidence_revision_row_to_dict(row)


def latest_attempt_evidence_revision(conn: sqlite3.Connection, attempt_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        select * from attempt_evidence_revisions
        where attempt_id = ?
        order by revision_number desc, created_at desc, id desc
        limit 1
        """,
        (attempt_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"Unknown attempt evidence revision: {attempt_id}")
    return attempt_evidence_revision_row_to_dict(row)


def record_attempt_evidence_revision(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    revision_kind: str,
    schema_version: str,
    input_mode: str,
    recognition_status: str,
    recognition_source: str = "",
    recognized_text: str = "",
    effective_text: str = "",
    recognition_confidence: float | None = None,
    critical_token_uncertainties: list[dict[str, Any]] | None = None,
    attachment_ids: list[str] | None = None,
    submission_request_digest_sha256: str = "",
    recognition_run_id: str | None = None,
    confirmation_id: str | None = None,
    parent_revision_id: str | None = None,
    raw: dict[str, Any] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    get_attempt(conn, attempt_id)
    if input_mode not in multimodal_evidence.INPUT_MODES:
        raise ValueError("unknown attempt evidence input mode")
    if recognition_status not in multimodal_evidence.RECOGNITION_STATUSES:
        raise ValueError("unknown attempt evidence recognition status")
    if recognition_run_id:
        get_media_recognition_run(conn, recognition_run_id)
    if confirmation_id:
        confirmation = conn.execute(
            "select * from evidence_confirmations where id = ? and attempt_id = ?",
            (confirmation_id, attempt_id),
        ).fetchone()
        if not confirmation:
            raise ValueError("evidence confirmation does not bind this attempt")
        if recognition_run_id and confirmation["recognition_run_id"] != recognition_run_id:
            raise ValueError("evidence confirmation does not bind this recognition run")
    try:
        latest = latest_attempt_evidence_revision(conn, attempt_id)
    except KeyError:
        latest = None
    expected_parent = latest["id"] if latest else None
    if parent_revision_id is not None and parent_revision_id != expected_parent:
        raise ValueError("attempt evidence revision parent is not the latest revision")
    parent_revision_id = expected_parent
    revision_number = int(latest["revision_number"] if latest else 0) + 1
    payload = {
        "attempt_id": attempt_id,
        "revision_number": revision_number,
        "parent_revision_id": parent_revision_id or "",
        "revision_kind": revision_kind,
        "schema_version": schema_version,
        "input_mode": input_mode,
        "recognition_status": recognition_status,
        "recognition_run_id": recognition_run_id or "",
        "confirmation_id": confirmation_id or "",
        "recognition_source": recognition_source,
        "recognized_text": str(recognized_text or "")[:4000],
        "effective_text": str(effective_text or "")[:4000],
        "recognition_confidence": recognition_confidence,
        "critical_token_uncertainties": list(critical_token_uncertainties or []),
        "attachment_ids": list(attachment_ids or []),
        "submission_request_digest_sha256": submission_request_digest_sha256,
        "raw": dict(raw or {}),
    }
    digest = _canonical_digest_json(payload)
    existing = conn.execute(
        "select * from attempt_evidence_revisions where attempt_id = ? and evidence_digest_sha256 = ? limit 1",
        (attempt_id, digest),
    ).fetchone()
    if existing:
        return attempt_evidence_revision_row_to_dict(existing)
    revision_id = f"AER-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        insert into attempt_evidence_revisions(
          id, attempt_id, revision_number, parent_revision_id, revision_kind,
          schema_version, input_mode, recognition_status, recognition_run_id,
          confirmation_id, recognition_source, recognized_text, effective_text,
          recognition_confidence, critical_token_uncertainties_json,
          attachment_ids_json, submission_request_digest_sha256,
          evidence_digest_sha256, raw_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            attempt_id,
            revision_number,
            parent_revision_id,
            revision_kind,
            schema_version,
            input_mode,
            recognition_status,
            recognition_run_id,
            confirmation_id,
            recognition_source,
            payload["recognized_text"],
            payload["effective_text"],
            recognition_confidence,
            json_dump(payload["critical_token_uncertainties"]),
            json_dump(payload["attachment_ids"]),
            submission_request_digest_sha256,
            digest,
            json_dump(payload["raw"]),
            now_iso(),
        ),
    )
    if commit:
        conn.commit()
    return get_attempt_evidence_revision(conn, revision_id)


def record_attempt_input_evidence(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    schema_version: str,
    input_mode: str,
    recognition_status: str,
    recognition_source: str = "",
    recognized_text: str = "",
    recognition_confidence: float | None = None,
    critical_token_uncertainties: list[dict[str, Any]] | None = None,
    child_confirmed: bool = False,
    child_confirmed_text: str = "",
    attachment_ids: list[str] | None = None,
    raw: dict[str, Any] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    return record_attempt_evidence_revision(
        conn,
        attempt_id=attempt_id,
        revision_kind="legacy_compatibility",
        schema_version=schema_version,
        input_mode=input_mode,
        recognition_status=recognition_status,
        recognition_source=recognition_source,
        recognized_text=recognized_text,
        effective_text=child_confirmed_text,
        recognition_confidence=recognition_confidence,
        critical_token_uncertainties=critical_token_uncertainties,
        attachment_ids=attachment_ids,
        raw={**(raw or {}), "legacy_child_confirmed": bool(child_confirmed)},
        commit=commit,
    )


def get_attempt_input_evidence(conn: sqlite3.Connection, attempt_id: str) -> dict[str, Any]:
    return latest_attempt_evidence_revision(conn, attempt_id)


def get_attempt(conn: sqlite3.Connection, attempt_id: str) -> dict[str, Any]:
    row = conn.execute("select * from attempts where id = ?", (attempt_id,)).fetchone()
    if not row:
        raise KeyError(f"Unknown attempt: {attempt_id}")
    return attempt_row_to_dict(row)


def grade_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    result: str,
    score_points: float,
    max_points: float,
    error_tags: list[str],
    answer_raw: str,
    parent_note: str,
    answer_analysis: dict[str, Any] | None = None,
    review_meta: dict[str, Any] | None = None,
    cause_analysis: dict[str, Any] | None = None,
    explanation_score: int | None = None,
    blocking_evidence: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    existing = get_attempt(conn, attempt_id)
    if existing.get("evidence_status") != "active":
        raise ValueError("Only active attempts can be graded")
    if existing["grading_status"] != "pending_review":
        raise ValueError("Only pending_review attempts can be graded")
    try:
        question = get_question(conn, existing["question_id"])
    except KeyError as exc:
        raise ValueError("Attempt question is missing") from exc
    if question.get("node_id") != existing.get("node_id"):
        raise ValueError("Attempt node_id must match question node_id before grading")
    try:
        session = get_learning_session(conn, existing["session_id"])
    except KeyError:
        session = {}
    if session.get("mode") == "child_learning_group":
        assert_learning_session_questions_current(conn, session)
    stored_answer_raw = existing["answer_raw"] if answer_raw is None else answer_raw
    _validate_attempt_values(
        result=result,
        grading_status="graded",
        score_points=score_points,
        max_points=max_points,
        error_tags=error_tags,
        explanation_score=explanation_score,
        blocking_evidence=blocking_evidence,
    )
    if answer_analysis is not None:
        validate_answer_analysis(answer_analysis)
    conn.execute(
        """
        update attempts
        set result = ?,
            grading_status = 'graded',
            score_points = ?,
            max_points = ?,
            error_tags_json = ?,
            answer_raw = ?,
            parent_note = ?,
            answer_analysis_json = ?,
            review_meta_json = ?,
            cause_analysis_json = ?,
            explanation_score = ?,
            blocking_evidence = ?
        where id = ?
        """,
        (
            result,
            score_points,
            max_points,
            json_dump(error_tags),
            stored_answer_raw,
            parent_note,
            json_dump(answer_analysis or {}),
            json_dump(review_meta or existing.get("review_meta") or {}),
            json_dump(cause_analysis or existing.get("cause_analysis") or {}),
            explanation_score,
            1 if blocking_evidence else 0,
            attempt_id,
        ),
    )
    if commit:
        conn.commit()
    return get_attempt(conn, attempt_id)


def invalidate_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    evidence_note: str,
    commit: bool = True,
) -> dict[str, Any]:
    existing = get_attempt(conn, attempt_id)
    note = (evidence_note or "").strip()
    if not note:
        raise ValueError("evidence_note is required when invalidating an attempt")
    conn.execute(
        """
        update attempts
        set evidence_status = 'invalidated',
            evidence_note = ?
        where id = ?
        """,
        (note[:500], attempt_id),
    )
    _invalidate_questions_from_source_attempt(conn, attempt_id=attempt_id, note=note)
    repair_invalidated_lineage(conn, commit=False)
    if commit:
        conn.commit()
    return get_attempt(conn, attempt_id)


def _invalidate_questions_from_source_attempt(conn: sqlite3.Connection, *, attempt_id: str, note: str) -> None:
    rows = conn.execute(
        """
        select id, source_json, raw_json
        from question_items
        where source_type = 'evolved'
          and json_extract(source_json, '$.attempt_id') = ?
        """,
        (attempt_id,),
    ).fetchall()
    for row in rows:
        source = json_load(row["source_json"], {})
        raw = json_load(row["raw_json"], {})
        source["evidence_status"] = "invalidated"
        source["invalidation_note"] = note[:500]
        raw_source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        raw_source.update(source)
        raw["source"] = raw_source
        quality = raw.get("quality") if isinstance(raw.get("quality"), dict) else {}
        quality.update({
            "review_status": "rejected",
            "age_floor": quality.get("age_floor", "incoming_grade_7"),
            "requires_reasoning": quality.get("requires_reasoning", True),
            "no_mechanical_drill": quality.get("no_mechanical_drill", True),
            "rejection_reasons": sorted(set((quality.get("rejection_reasons") or []) + ["invalidated_or_incomplete_source_evidence"])),
        })
        raw["quality"] = quality
        review_check = raw.get("review_agent_check") if isinstance(raw.get("review_agent_check"), dict) else {}
        review_check.update({
            "status": "rejected",
            "rejection_reasons": sorted(set((review_check.get("rejection_reasons") or []) + ["invalidated_or_incomplete_source_evidence"])),
        })
        raw["review_agent_check"] = review_check
        conn.execute(
            "update question_items set source_json = ?, raw_json = ? where id = ?",
            (json_dump(source), json_dump(raw), row["id"]),
        )


def update_attempt_answer_analysis(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    answer_analysis: dict[str, Any],
    commit: bool = True,
) -> dict[str, Any]:
    existing = get_attempt(conn, attempt_id)
    if existing.get("evidence_status") != "active":
        raise ValueError("Only active attempts can receive answer analysis")
    if existing["grading_status"] != "graded":
        raise ValueError("Only graded attempts can receive answer analysis")
    validate_answer_analysis(answer_analysis)
    conn.execute(
        "update attempts set answer_analysis_json = ? where id = ?",
        (json_dump(answer_analysis), attempt_id),
    )
    if commit:
        conn.commit()
    return get_attempt(conn, attempt_id)


def pending_attempts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select a.*, q.prompt, q.expected_answer, q.answer_format, n.name as node_name
        from attempts a
        join question_items q on q.id = a.question_id
        join graph_nodes n on n.id = a.node_id
        where a.grading_status = 'pending_review'
          and a.evidence_status = 'active'
        order by a.created_at desc, a.id desc
        """
    ).fetchall()
    pending = []
    for row in rows:
        item = attempt_row_to_dict(row)
        item["question"] = {
            "id": item["question_id"],
            "prompt": item.pop("prompt"),
            "expected_answer": item.pop("expected_answer"),
            "answer_format": item.pop("answer_format"),
        }
        item["node_name"] = item.pop("node_name")
        item["attachments"] = attachments_for_attempt(conn, item["id"])
        pending.append(item)
    return pending


def recent_attempts(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select a.*, q.prompt, q.expected_answer, q.answer_format, n.name as node_name
        from attempts a
        join question_items q on q.id = a.question_id
        join graph_nodes n on n.id = a.node_id
        where a.evidence_status = 'active'
        order by a.created_at desc, a.id desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    attempts = []
    for row in rows:
        item = attempt_row_to_dict(row)
        item["question"] = {
            "id": item["question_id"],
            "prompt": item.pop("prompt"),
            "expected_answer": item.pop("expected_answer"),
            "answer_format": item.pop("answer_format"),
        }
        item["node_name"] = item.pop("node_name")
        item["attachments"] = attachments_for_attempt(conn, item["id"])
        attempts.append(item)
    return attempts


def get_agent_profile(conn: sqlite3.Connection, agent_key: str) -> dict[str, Any]:
    row = conn.execute("select * from agent_profiles where agent_key = ?", (agent_key,)).fetchone()
    if not row:
        raise KeyError(f"Unknown agent profile: {agent_key}")
    data = dict(row)
    data["profile"] = json_load(data["profile_json"], {})
    return data


def update_agent_profile(conn: sqlite3.Connection, agent_key: str, profile: dict[str, Any]) -> dict[str, Any]:
    before = get_agent_profile(conn, agent_key)
    revision = int(before["revision"]) + 1
    conn.execute(
        "update agent_profiles set revision = ?, profile_json = ?, updated_at = ? where agent_key = ?",
        (revision, json_dump(profile), now_iso(), agent_key),
    )
    return get_agent_profile(conn, agent_key)


def questions_created_by_event(conn: sqlite3.Connection, event_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("select * from question_items where created_by_event_id = ? order by id", (event_id,)).fetchall()
    return [row_to_question(row) for row in rows]


def readiness(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "graph_nodes": conn.execute("select count(*) from graph_nodes").fetchone()[0],
        "graph_edges": conn.execute("select count(*) from graph_edges").fetchone()[0],
        "diagnostic_questions": conn.execute("select count(*) from question_items where source_type = 'diagnostic'").fetchone()[0],
        "practice_questions": conn.execute("select count(*) from question_items where source_type = 'graph_generated'").fetchone()[0],
        "evolved_questions": conn.execute("select count(*) from question_items where source_type = 'evolved'").fetchone()[0],
        "attempts": conn.execute("select count(*) from attempts where evidence_status = 'active'").fetchone()[0],
    }
