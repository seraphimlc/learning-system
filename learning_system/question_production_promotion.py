"""Promote reviewed production candidates into the staged question bank."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from typing import Any

from . import child_prompt, db, question_artifact, question_bank
from .question_production_audit import record_event
from .question_production_skills import validate_candidate


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _short_answer_interaction_schema() -> dict[str, Any]:
    return child_prompt.normalize_interaction_schema(
        {
            "schema_version": child_prompt.QUESTION_INTERACTION_SCHEMA_V2,
            "type": "short_text",
            "response_capture": "existing_control",
            "title": "作答",
            "allow_explanation": True,
            "requires_explanation": False,
            "explanation_label": "",
            "fields": [],
            "choices": [],
            "formula_label": "",
            "placeholder": "",
        },
        allow_legacy=False,
    )


def _candidate_item(
    candidate: dict[str, Any],
    brief: dict[str, Any],
    *,
    run_id: str,
    item_version: str,
    graph_version: str,
    review: dict[str, Any],
) -> dict[str, Any]:
    content = deepcopy(candidate.get("content") or {})
    version_digest = hashlib.sha256(item_version.encode("utf-8")).hexdigest()[:12]
    identity = {
        "question_id": f"QPROD-{version_digest}-{run_id}-{candidate['candidate_id']}",
        "node_id": candidate["node_id"],
        "qf_id": brief["qf_id"],
        "slot_id": brief["slot_id"],
    }
    candidate_envelope = {
        "candidate_id": candidate["candidate_id"],
        "brief_id": candidate["brief_id"],
        "node_id": candidate["node_id"],
        "content": content,
    }
    schema_validation = validate_candidate(
        {"node_id": candidate["node_id"], "brief_id": candidate["brief_id"]},
        candidate_envelope,
    )
    if schema_validation.status != "passed":
        details = ", ".join(schema_validation.error_codes())
        raise ValueError("candidate schema validation failed before promotion: " + details)
    response_mode = content["response_mode"]
    if response_mode in {"single_choice", "multi_choice", "fill_blank"}:
        compiled = question_artifact.compile_question_content(content, identity=identity)
        prompt = compiled["child_surface"]["prompt"]
        interaction_schema = compiled["child_surface"]["interaction_schema"]
        expected_answer = content["answer"]
        rubric = question_bank.BASE_RUBRIC
        solution_steps: list[str] = []
    else:
        prompt = str(content["prompt"]).strip()
        interaction_schema = _short_answer_interaction_schema()
        expected_answer = content["answer"]
        rubric = list(content["rubric"])
        solution_steps = list(content["solution_steps"])

    source = {
        "type": "graph_generated",
        "production_pipeline": "node_qf_slot_brief_candidate_v1",
        "production_run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "brief_id": candidate["brief_id"],
        "qf_id": brief["qf_id"],
        "slot_id": brief["slot_id"],
        "graph_version": graph_version,
        "question_bank_version": item_version,
        "semantic_review": review,
        "promotion_status": "staged",
    }
    return {
        "id": identity["question_id"],
        "item_version": item_version,
        "source_type": "graph_generated",
        "node_id": candidate["node_id"],
        "secondary_node_ids": [],
        "kind": "standard_example" if content["task_type"] == "calculation" else "variant",
        "question_type": content["task_type"],
        "variant_level": "L2",
        "prompt": prompt,
        "answer_format": (
            "fixed_answer" if response_mode in {"single_choice", "multi_choice", "fill_blank"}
            else "model_semantic_assessment"
        ),
        "expected_answer": _json(expected_answer),
        "rubric": rubric,
        "solution_steps": solution_steps,
        "target_error_tags": [],
        "rollback_candidates": [],
        "rollback_candidate_relations": [],
        "estimated_minutes": 5,
        "parent_observation": "",
        "interaction_schema": interaction_schema,
        "source": source,
        "raw_candidate": candidate,
        "production_lineage": {
            "run_id": run_id,
            "qf_id": brief["qf_id"],
            "slot_id": brief["slot_id"],
            "brief_id": candidate["brief_id"],
            "candidate_id": candidate["candidate_id"],
            "semantic_review": review,
        },
    }


def _prepare_runtime_review_item(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    *,
    review: dict[str, Any],
) -> dict[str, Any]:
    """Attach the runtime quality evidence that activation verifies.

    Production semantic review and child-runtime review records are separate
    boundaries. This adapter preserves the former as evidence and creates the
    stable metadata required by the latter without changing the child surface.
    """
    prepared = deepcopy(item)
    node = db.get_graph_node(conn, str(prepared["node_id"]))
    if not node:
        node = {"id": prepared["node_id"], "name": prepared["node_id"]}
    prepared["age_floor"] = question_bank.INCOMING_GRADE_7_AGE_FLOOR
    source = prepared.setdefault("source", {})
    source["reviewer_evidence"] = {
        "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
        "engine_type": "question_production_candidate_semantic_review",
        "provenance_type": "question_production_pipeline",
        "graph_version": prepared.get("graph_version") or source.get("graph_version") or "",
        "question_bank_version": prepared.get("question_bank_version") or source.get("question_bank_version") or prepared.get("item_version", ""),
        "contract_version": question_bank.QUESTION_PRODUCTION_CONTRACT_VERSION,
        "graph_bound": True,
        "incoming_grade_7_ready": True,
        "diagnostic_structure": True,
        "process_evidence_required": True,
        "not_mechanical_drill": True,
        "child_prompt_self_contained": True,
        "specific_expected_answer": True,
        "production_review": deepcopy(review),
        "review_rationale": "Candidate passed the production schema and independent semantic review; runtime evidence is bound to this immutable promoted item.",
    }
    question_bank._attach_question_identity_contract(
        prepared,
        node,
        str(prepared.get("question_type") or prepared.get("kind") or "question_production"),
    )
    quality = question_bank.review_item_quality(prepared)
    if quality.get("review_status") != "approved":
        raise ValueError(
            "candidate failed runtime quality gate before review record: "
            + ", ".join(quality.get("rejection_reasons") or [])
        )
    prepared["quality"] = quality
    prepared["requires_reasoning"] = quality["requires_reasoning"]
    prepared["review_agent_check"] = {
        "reviewer_agent": question_bank.QUESTION_REVIEWER_AGENT_KEY,
        "status": quality["review_status"],
        "rejection_reasons": quality["rejection_reasons"],
    }
    return prepared


def _record_runtime_review(
    conn: sqlite3.Connection,
    *,
    item: dict[str, Any],
    run_id: str,
    review: dict[str, Any],
) -> dict[str, Any]:
    """Create or reuse the reviewer run and bind it to the promoted item."""
    candidate_sha256 = db._digest_json(item)
    score = review.get("score")
    confidence = float(review.get("confidence") or 0)
    reviewer_run = db.record_agent_run(
        conn,
        agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
        engine_type="model",
        session_id=None,
        phase="question_quality_review",
        trigger=f"question-production:{run_id}:{item['id']}",
        input_refs={
            "question_id": item["id"],
            "candidate_sha256": candidate_sha256,
            "production_run_id": run_id,
        },
        prompt_version_id="question-production.candidate-review.v1",
        status="accepted",
        confidence=confidence,
        output={
            "review_status": "approved",
            "active_eligible": True,
            "production_review": deepcopy(review),
        },
        validation_errors=[],
        error_reason="",
        response_schema_version="semantic-review.v1",
        commit=False,
    )
    return db.record_question_review_record(
        conn,
        question_id=item["id"],
        candidate_id=str(item.get("raw_candidate", {}).get("candidate_id") or item["id"]),
        item_version=str(item["item_version"]),
        source_type=str(item["source_type"]),
        candidate=item,
        designer_run_id=None,
        reviewer_run_id=reviewer_run["id"],
        commit=False,
    )


def _candidate_rows(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        select a.*
        from production_artifacts a
        join production_stages s on s.id = a.stage_id
        where a.run_id = ? and a.artifact_type = 'candidate'
          and s.stage_name = 'candidate_generation'
          and s.status = 'completed'
        and a.artifact_attempt = (
          select max(latest.artifact_attempt)
          from production_artifacts latest
          where latest.run_id = a.run_id
            and latest.stage_id = a.stage_id
            and latest.artifact_type = a.artifact_type
            and latest.logical_key = a.logical_key
        )
        order by a.logical_key
        """,
        (run_id,),
    ).fetchall()
    if not rows:
        raise ValueError("promotion requires at least one completed candidate")
    return rows


def _merge_staged_ledger(
    conn: sqlite3.Connection,
    *,
    question_bank_version: str,
    graph_version: str,
    manifest_id: str,
    new_items: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    existing_ledger = conn.execute(
        "select * from question_bank_version_ledger where question_bank_version=? order by created_at desc,id desc limit 1",
        (question_bank_version,),
    ).fetchone()
    existing_items: list[dict[str, Any]] = []
    if existing_ledger:
        if existing_ledger["status"] not in {"staged", "active"}:
            raise ValueError("question bank version cannot be extended after leaving staged/active status")
        if existing_ledger["graph_version"] != graph_version or existing_ledger["manifest_id"] != manifest_id:
            raise ValueError("question bank version identity conflict")
        rows = conn.execute(
            "select raw_json from question_items where item_version=? and source_type='graph_generated' order by id",
            (question_bank_version,),
        ).fetchall()
        existing_items = [json.loads(row["raw_json"]) for row in rows]
    merged: dict[str, dict[str, Any]] = {str(item["id"]): item for item in existing_items}
    for item in new_items:
        item_id = str(item["id"])
        prior = merged.get(item_id)
        if prior is not None and _digest(prior) != _digest(item):
            raise ValueError(f"question item identity conflict: {item_id}")
        merged[item_id] = item
    merged_items = [merged[item_id] for item_id in sorted(merged)]
    digest = _digest(merged_items)
    node_count = len({item["node_id"] for item in merged_items})
    if existing_ledger:
        conn.execute(
            "update question_bank_version_ledger set manifest_sha256=?,node_count=?,item_count=?,updated_at=? where id=?",
            (digest, node_count, len(merged_items), db.now_iso(), existing_ledger["id"]),
        )
        ledger = dict(conn.execute("select * from question_bank_version_ledger where id=?", (existing_ledger["id"],)).fetchone())
    else:
        ledger = db.stage_question_bank_version(
            conn,
            question_bank_version=question_bank_version,
            graph_version=graph_version,
            manifest_id=manifest_id,
            manifest_sha256=digest,
            node_count=node_count,
            item_count=len(merged_items),
            commit=False,
        )
    return ledger, merged_items


def _brief_for_candidate(conn: sqlite3.Connection, run_id: str, candidate_row: sqlite3.Row) -> dict[str, Any]:
    parent_ids = json.loads(candidate_row["parent_artifact_ids_json"] or "[]")
    if len(parent_ids) != 1:
        raise ValueError(f"candidate {candidate_row['logical_key']} must have exactly one brief parent")
    row = conn.execute(
        "select artifact_type,payload_json from production_artifacts where run_id=? and id=?",
        (run_id, parent_ids[0]),
    ).fetchone()
    if not row or row["artifact_type"] != "brief":
        raise ValueError(f"candidate {candidate_row['logical_key']} has no brief parent")
    return json.loads(row["payload_json"])


def _promote_run_impl(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    question_bank_version: str,
    graph_version: str,
    manifest_id: str | None = None,
) -> dict[str, Any]:
    run = conn.execute("select status,node_id from production_runs where id=?", (run_id,)).fetchone()
    if not run:
        raise ValueError(f"unknown production run: {run_id}")
    if run["status"] != "completed":
        raise ValueError("promotion requires a completed production run")
    if not question_bank_version.strip() or not graph_version.strip():
        raise ValueError("promotion requires explicit question-bank and graph versions")

    candidate_rows = _candidate_rows(conn, run_id)
    prepared: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in candidate_rows:
        stage = conn.execute(
            "select validation_result_json from production_stages where id=?",
            (row["stage_id"],),
        ).fetchone()
        validation = json.loads(stage["validation_result_json"] or "{}")
        review = validation.get("semantic_review") or {}
        if review.get("decision") != "accepted":
            raise ValueError(f"candidate {row['logical_key']} is not semantically accepted")
        candidate = json.loads(row["payload_json"])
        brief = _brief_for_candidate(conn, run_id, row)
        prepared_item = _candidate_item(
            candidate,
            brief,
            run_id=run_id,
            item_version=question_bank_version,
            graph_version=graph_version,
            review=review,
        )
        prepared.append((_prepare_runtime_review_item(conn, prepared_item, review=review), review))

    items = [item for item, _ in prepared]
    ledger, _merged_items = _merge_staged_ledger(
        conn,
        question_bank_version=question_bank_version,
        graph_version=graph_version,
        manifest_id=manifest_id or f"production-{run_id}",
        new_items=items,
    )
    promoted_count = 0
    review_records: list[dict[str, Any]] = []
    try:
        for item, review in prepared:
            existing = conn.execute("select 1 from question_items where id=?", (item["id"],)).fetchone()
            db.stage_question_item(conn, item, commit=False)
            review_records.append(_record_runtime_review(conn, item=item, run_id=run_id, review=review))
            if not existing:
                promoted_count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "run_id": run_id,
        "question_bank_version": question_bank_version,
        "ledger_id": ledger["id"],
        "status": "staged",
        "promoted_count": promoted_count,
        "item_count": len(items),
        "question_ids": [item["id"] for item in items],
        "review_record_ids": [record["id"] for record in review_records],
    }


def promote_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    question_bank_version: str,
    graph_version: str,
    manifest_id: str | None = None,
) -> dict[str, Any]:
    """Run promotion and leave a durable success or failure audit event."""
    audit_input = {
        "run_id": run_id,
        "question_bank_version": question_bank_version,
        "graph_version": graph_version,
        "manifest_id": manifest_id or f"production-{run_id}",
    }
    try:
        result = _promote_run_impl(
            conn,
            run_id=run_id,
            question_bank_version=question_bank_version,
            graph_version=graph_version,
            manifest_id=manifest_id,
        )
        record_event(
            conn,
            run_id=run_id,
            stage_id=None,
            stage_name="promotion",
            logical_key=run_id,
            step_name="promotion",
            event_type="promotion",
            attempt=1,
            status="completed",
            input_value=audit_input,
            output_value=result,
            completed_at=_now(),
        )
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        record_event(
            conn,
            run_id=run_id,
            stage_id=None,
            stage_name="promotion",
            logical_key=run_id,
            step_name="promotion",
            event_type="promotion",
            attempt=1,
            status="failed",
            input_value=audit_input,
            output_value={},
            errors=[str(exc)],
            completed_at=_now(),
        )
        conn.commit()
        raise
