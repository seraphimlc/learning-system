from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import nullcontext
from copy import deepcopy
from typing import Any

from . import assessment_policy, db


_CHILD_FEEDBACK_FIELDS = (
    "reference_answer",
    "answer_gap",
    "improvement_direction",
    "expression_judgment",
    "teaching_explanation",
)


def _nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _verdict(value: Any) -> Any:
    return value.get("verdict") if isinstance(value, dict) else value


def _contract_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    authoritative_node_id = result.pop("authoritative_node_id", None)
    if authoritative_node_id is not None:
        result["node_id"] = authoritative_node_id
    result["reference_solution"] = db.json_load(
        result.pop("reference_solution_json"), {}
    )
    result["score_points"] = db.json_load(result.pop("score_points_json"), [])
    result["review_receipt"] = db.json_load(
        result.pop("review_receipt_json"), {}
    )
    result["rejection_reason"] = db.json_load(
        result.pop("rejection_reason_json"), {}
    )
    return result


def _assessment_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["superseded_assessment_id"] = result.get("supersedes_assessment_id")
    result["criterion_judgments"] = db.json_load(
        result.pop("criterion_judgments_json"), []
    )
    result["reference_answer"] = db.json_load(
        result.pop("reference_answer_json"), None
    )
    result["improvement_direction"] = db.json_load(
        result.pop("improvement_direction_json"), []
    )
    result["question_passed"] = bool(result["question_passed"])
    return result


def _policy_contract(contract: dict[str, Any]) -> dict[str, Any]:
    score_points = deepcopy(contract.get("score_points") or [])
    scoring_targets = []
    for point in score_points:
        if not isinstance(point, dict):
            raise TypeError("each stored score point must be a mapping")
        target = {
            "key": point.get("source_target_key"),
            "criterion": point.get("criterion"),
            "dimension": point.get("dimension"),
            "required_for_pass": point.get("required_for_pass"),
        }
        if "reference_component" in point:
            target["reference_component"] = deepcopy(point["reference_component"])
        scoring_targets.append(target)
    return {
        "question_id": contract.get("question_id"),
        "item_version": contract.get("item_version"),
        "node_id": contract.get("node_id"),
        "reference_solution": deepcopy(contract.get("reference_solution")),
        "scoring_targets": scoring_targets,
        "score_points": score_points,
        "status": "draft",
    }


def policy_contract_for_assessment(contract: dict[str, Any]) -> dict[str, Any]:
    """Return the deterministic policy projection for a stored contract."""
    projected = _policy_contract(contract)
    assessment_policy.validate_contract(projected)
    return projected


def _validate_contract_policy(contract: dict[str, Any]) -> None:
    assessment_policy.validate_contract(_policy_contract(contract))


def _agent_run_if_present(conn: sqlite3.Connection, run_id: Any) -> str | None:
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    row = conn.execute("select id from agent_runs where id = ?", (run_id,)).fetchone()
    return row["id"] if row else None


def _require_contract_reviewer_run(
    conn: sqlite3.Connection, review_row: sqlite3.Row, contract: dict[str, Any]
) -> str:
    reviewer_run_id = review_row["reviewer_run_id"]
    if not isinstance(reviewer_run_id, str) or not reviewer_run_id.strip():
        raise ValueError("question review record must reference a reviewer run")
    if contract.get("review_run_id") != reviewer_run_id:
        raise ValueError("contract review run does not match review lineage")
    run = conn.execute(
        "select * from agent_runs where id = ?", (reviewer_run_id,)
    ).fetchone()
    if not run:
        raise ValueError("contract reviewer run does not exist")
    expected = {
        "agent_key": "answer_contract_reviewer_agent",
        "phase": "answer_contract_review",
        "status": "accepted",
        "model_provider": "openai",
        "model_name": "gpt-5.5",
        "model_alias": "gpt-5.5",
    }
    if any(run[field] != value for field, value in expected.items()):
        raise ValueError("contract reviewer run is not accepted live GPT-5.5 lineage")
    return reviewer_run_id


def _ensure_busy_timeout(conn: sqlite3.Connection, minimum_ms: int = 2000) -> None:
    current = int(conn.execute("pragma busy_timeout").fetchone()[0])
    if current < minimum_ms:
        conn.execute(f"pragma busy_timeout = {minimum_ms}")


def _contract_version_row(
    conn: sqlite3.Connection, stable_contract_id: str, contract_version: int
) -> sqlite3.Row | None:
    return conn.execute(
        """
        select ac.*, qi.node_id as authoritative_node_id
        from answer_contracts ac
        join question_items qi on qi.id = ac.question_id
        where ac.stable_contract_id = ? and ac.contract_version = ?
        """,
        (stable_contract_id, contract_version),
    ).fetchone()


def _semantic_review_receipt(contract: dict[str, Any]) -> dict[str, Any]:
    receipt = deepcopy(contract.get("review_receipt") or {})
    receipt.update(
        {
            "question_correctness": contract.get("question_correctness"),
            "question_node_alignment": contract.get("question_node_alignment"),
            "evidence_role_alignment": contract.get("evidence_role_alignment"),
            "provider_mode": contract.get("review_provider_mode"),
            "review_run_id": contract.get("review_run_id"),
        }
    )
    return receipt


def _validate_semantic_eligibility(contract: dict[str, Any]) -> None:
    if _verdict(contract.get("question_correctness")) != "pass":
        raise ValueError("question correctness review must pass")
    if _verdict(contract.get("question_node_alignment")) != "aligned":
        raise ValueError("question-node review must be aligned")
    if _verdict(contract.get("evidence_role_alignment")) != "aligned":
        raise ValueError("evidence-role review must be aligned")
    if contract.get("review_provider_mode") != "live_model":
        raise ValueError("contract activation requires a live review receipt")
    _nonempty_text(contract.get("review_receipt_sha256"), "review_receipt_sha256")
    _nonempty_text(contract.get("review_run_id"), "review_run_id")


def _load_contract_exact(
    conn: sqlite3.Connection,
    *,
    contract_id: Any,
    contract_version: Any,
    contract_digest_sha256: Any,
) -> dict[str, Any]:
    contract_id = _nonempty_text(contract_id, "contract id")
    contract_version = _positive_int(contract_version, "contract version")
    contract_digest_sha256 = _nonempty_text(
        contract_digest_sha256, "contract digest"
    )
    row = conn.execute(
        """
        select ac.*, qi.node_id as authoritative_node_id
        from answer_contracts ac
        join question_items qi on qi.id = ac.question_id
        where ac.id = ?
        """,
        (contract_id,),
    ).fetchone()
    if not row:
        raise ValueError("answer contract does not exist")
    stored = _contract_from_row(row)
    if (
        stored["contract_version"] != contract_version
        or stored["contract_digest_sha256"] != contract_digest_sha256
    ):
        raise ValueError("answer contract version or digest mismatch")
    return stored


def activate_contract(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    review_record_id: str,
    contract: dict[str, Any],
    generator_version: str,
) -> dict[str, Any]:
    if not isinstance(question, dict) or not isinstance(contract, dict):
        raise TypeError("question and contract must be mappings")
    _validate_semantic_eligibility(contract)
    _validate_contract_policy(contract)

    stable_id = _nonempty_text(contract.get("stable_contract_id"), "stable_contract_id")
    version = _positive_int(contract.get("contract_version"), "contract_version")
    digest = _nonempty_text(
        contract.get("contract_digest_sha256"), "contract_digest_sha256"
    )
    generator_version = _nonempty_text(generator_version, "generator_version")
    review_record_id = _nonempty_text(review_record_id, "review_record_id")
    question_row = conn.execute(
        "select * from question_items where id = ?", (contract.get("question_id"),)
    ).fetchone()
    if not question_row:
        raise ValueError("contract question does not exist")
    authoritative_question = db.row_to_question(question_row)
    for field in ("id", "item_version", "node_id"):
        contract_field = "question_id" if field == "id" else field
        if contract.get(contract_field) != authoritative_question[field]:
            raise ValueError(f"contract {contract_field} does not match question row")
        if question.get(field) != authoritative_question[field]:
            raise ValueError(f"caller question {field} does not match question row")

    review_row = conn.execute(
        """
        select * from question_review_records
        where id = ? and question_id = ? and item_version = ?
        """,
        (review_record_id, authoritative_question["id"], authoritative_question["item_version"]),
    ).fetchone()
    if (
        not review_row
        or review_row["review_status"] != "approved"
        or int(review_row["active_eligible"] or 0) != 1
    ):
        raise ValueError("question review record is not activation eligible")
    reviewer_run_id = _require_contract_reviewer_run(conn, review_row, contract)
    _ensure_busy_timeout(conn)

    for race_attempt in range(3):
        existing = _contract_version_row(conn, stable_id, version)
        if existing:
            canonical = _contract_from_row(existing)
            if canonical["contract_digest_sha256"] != digest:
                raise ValueError("immutable contract version has a conflicting digest")
            return canonical
        try:
            with conn:
                lineage_rows = conn.execute(
                    """
                    select stable_contract_id, contract_version
                    from answer_contracts
                    where question_id = ? and item_version = ?
                    order by contract_version desc
                    """,
                    (authoritative_question["id"], authoritative_question["item_version"]),
                ).fetchall()
                if lineage_rows:
                    if any(row["stable_contract_id"] != stable_id for row in lineage_rows):
                        raise ValueError("question contract lineage changed stable id")
                    if version <= max(int(row["contract_version"]) for row in lineage_rows):
                        raise ValueError("new contract version must increase monotonically")

                now = db.now_iso()
                conn.execute(
                    """
                    update answer_contracts
                    set status = 'retired', superseded_at = ?, updated_at = ?
                    where question_id = ? and item_version = ? and status = 'active'
                    """,
                    (now, now, authoritative_question["id"], authoritative_question["item_version"]),
                )
                row_id = f"ACR-{uuid.uuid4().hex[:16]}"
                conn.execute(
                    """
                    insert into answer_contracts(
                      id, stable_contract_id, question_id, item_version, contract_version,
                      contract_digest_sha256, question_digest_sha256, graph_version,
                      question_bank_version, reference_solution_json, score_points_json,
                      generator_version, generator_run_id, review_record_id, review_run_id,
                      review_receipt_json, review_receipt_sha256,
                      fingerprint_policy_version, prompt_instance_fingerprint,
                      core_structure_fingerprint, status, rejection_reason_json,
                      approved_at, activated_at, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'active', '{}', ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        stable_id,
                        authoritative_question["id"],
                        authoritative_question["item_version"],
                        version,
                        digest,
                        str(contract.get("question_digest_sha256") or ""),
                        str(contract.get("graph_version") or ""),
                        str(contract.get("question_bank_version") or authoritative_question["item_version"]),
                        db.json_dump(contract["reference_solution"]),
                        db.json_dump(contract["score_points"]),
                        generator_version,
                        _agent_run_if_present(conn, contract.get("generator_run_id")),
                        review_record_id,
                        reviewer_run_id,
                        db.json_dump(_semantic_review_receipt(contract)),
                        contract["review_receipt_sha256"],
                        str(contract.get("fingerprint_policy_version") or ""),
                        str(contract.get("prompt_instance_fingerprint") or ""),
                        str(contract.get("core_structure_fingerprint") or ""),
                        now,
                        now,
                        now,
                        now,
                    ),
                )
            stored = _contract_version_row(conn, stable_id, version)
            if not stored:
                raise ValueError("activated contract could not be read back")
            return _contract_from_row(stored)
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
            conn.rollback()
            canonical_row = _contract_version_row(conn, stable_id, version)
            if canonical_row:
                canonical = _contract_from_row(canonical_row)
                if canonical["contract_digest_sha256"] != digest:
                    raise ValueError("immutable contract version has a conflicting digest") from exc
                return canonical
            if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower() and race_attempt < 2:
                time.sleep((0.02, 0.05)[race_attempt])
                continue
            raise ValueError("contract activation could not converge") from exc
    raise ValueError("contract activation could not converge")


def active_contract_for_question(
    conn: sqlite3.Connection, question_id: str, item_version: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select * from answer_contracts
        where question_id = ? and item_version = ? and status = 'active'
        order by contract_version desc, id desc
        limit 1
        """,
        (question_id, item_version),
    ).fetchone()
    return _contract_from_row(row) if row else None


def bound_active_contract_for_flow_step(
    conn: sqlite3.Connection, flow_step_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select fs.*, df.assessment_policy_version
        from flow_steps fs
        join daily_flows df on df.id = fs.flow_id
        where fs.id = ?
        """,
        (flow_step_id,),
    ).fetchone()
    if not row or row["assessment_policy_version"] != "v5.1":
        return None
    if not (
        row["answer_contract_id"]
        and row["answer_contract_version"]
        and row["answer_contract_digest_sha256"]
    ):
        return None
    contract = _load_contract_exact(
        conn,
        contract_id=row["answer_contract_id"],
        contract_version=row["answer_contract_version"],
        contract_digest_sha256=row["answer_contract_digest_sha256"],
    )
    if contract["status"] != "active":
        return None
    if (
        contract["question_id"] != row["question_id"]
        or contract["item_version"] != row["question_item_version"]
    ):
        raise ValueError("flow step contract does not match question lineage")
    return contract


def bind_contract_to_flow_step(
    conn: sqlite3.Connection,
    flow_step_id: str,
    contract: dict[str, Any],
) -> None:
    if not isinstance(contract, dict):
        raise TypeError("contract must be a mapping")
    stored = _load_contract_exact(
        conn,
        contract_id=contract.get("id"),
        contract_version=contract.get("contract_version"),
        contract_digest_sha256=contract.get("contract_digest_sha256"),
    )
    if stored["status"] != "active":
        raise ValueError("only an active contract can be bound to a flow step")

    with conn:
        step = conn.execute(
            "select * from flow_steps where id = ?", (flow_step_id,)
        ).fetchone()
        if not step:
            raise ValueError("flow step does not exist")
        if (
            step["question_id"] != stored["question_id"]
            or step["question_item_version"] != stored["item_version"]
        ):
            raise ValueError("flow step question lineage does not match contract")
        conn.execute(
            """
            update flow_steps
            set answer_contract_id = ?, answer_contract_version = ?,
                answer_contract_digest_sha256 = ?, updated_at = ?
            where id = ?
            """,
            (
                stored["id"],
                stored["contract_version"],
                stored["contract_digest_sha256"],
                db.now_iso(),
                flow_step_id,
            ),
        )


def record_pending_assessment(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    attempt_version: int,
    contract: dict[str, Any],
    assessment_input_digest_sha256: str,
) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise TypeError("contract must be a mapping")
    attempt_version = _positive_int(attempt_version, "attempt_version")
    input_digest = _nonempty_text(
        assessment_input_digest_sha256, "assessment_input_digest_sha256"
    )
    stored_contract = _load_contract_exact(
        conn,
        contract_id=contract.get("id"),
        contract_version=contract.get("contract_version"),
        contract_digest_sha256=contract.get("contract_digest_sha256"),
    )
    attempt = conn.execute(
        "select * from attempts where id = ? and attempt_version = ?",
        (attempt_id, attempt_version),
    ).fetchone()
    if not attempt:
        raise ValueError("attempt does not exist at the requested version")
    step = conn.execute(
        "select * from flow_steps where id = ?", (attempt["flow_step_id"],)
    ).fetchone()
    if not step or (
        step["answer_contract_id"] != stored_contract["id"]
        or step["answer_contract_version"] != stored_contract["contract_version"]
        or step["answer_contract_digest_sha256"]
        != stored_contract["contract_digest_sha256"]
    ):
        raise ValueError("attempt flow step is not bound to the exact contract")
    if attempt["question_id"] != stored_contract["question_id"]:
        raise ValueError("attempt question does not match contract")

    key_params = (attempt_id, attempt_version, stored_contract["id"], input_digest)

    def read_canonical() -> sqlite3.Row | None:
        return conn.execute(
            """
            select * from attempt_assessments
            where attempt_id = ? and attempt_version = ?
              and answer_contract_id = ? and assessment_input_digest_sha256 = ?
            limit 1
            """,
            key_params,
        ).fetchone()

    existing = read_canonical()
    if existing:
        return _assessment_from_row(existing)

    _ensure_busy_timeout(conn)
    for race_attempt in range(3):
        now = db.now_iso()
        try:
            with conn:
                conn.execute(
                    """
                    insert into attempt_assessments(
                      id, attempt_id, attempt_version, assessment_version,
                      assessment_digest_sha256, assessment_input_digest_sha256,
                      question_id, question_item_version, answer_contract_id,
                      answer_contract_version, answer_contract_digest_sha256,
                      criterion_judgments_json, score_out_of_10, question_passed,
                      reference_answer_json, improvement_direction_json,
                      status, created_at, updated_at
                    ) values (
                      ?, ?, ?,
                      (select coalesce(max(assessment_version), 0) + 1
                       from attempt_assessments
                       where attempt_id = ? and attempt_version = ?),
                      '', ?, ?, ?, ?, ?, ?, '[]', null, 0, ?, '[]',
                      'pending', ?, ?
                    )
                    on conflict(
                      attempt_id, attempt_version, answer_contract_id,
                      assessment_input_digest_sha256
                    ) do nothing
                    """,
                    (
                        f"AS-{uuid.uuid4().hex[:16]}",
                        attempt_id,
                        attempt_version,
                        attempt_id,
                        attempt_version,
                        input_digest,
                        stored_contract["question_id"],
                        stored_contract["item_version"],
                        stored_contract["id"],
                        stored_contract["contract_version"],
                        stored_contract["contract_digest_sha256"],
                        db.json_dump(stored_contract["reference_solution"]),
                        now,
                        now,
                    ),
                )
            canonical = read_canonical()
            if canonical:
                return _assessment_from_row(canonical)
            raise ValueError("pending assessment insert produced no canonical row")
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            canonical = read_canonical()
            if canonical:
                return _assessment_from_row(canonical)
            raise ValueError("pending assessment idempotency conflict") from exc
        except sqlite3.OperationalError as exc:
            conn.rollback()
            canonical = read_canonical()
            if canonical:
                return _assessment_from_row(canonical)
            if "locked" in str(exc).lower() and race_attempt < 2:
                time.sleep((0.02, 0.05)[race_attempt])
                continue
            raise ValueError("pending assessment database race did not converge") from exc
    raise ValueError("pending assessment database race did not converge")


def accepted_assessment_for_attempt(
    conn: sqlite3.Connection, attempt_id: str, attempt_version: int
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select * from attempt_assessments
        where attempt_id = ? and attempt_version = ? and status = 'accepted'
        order by assessment_version desc, id desc
        limit 1
        """,
        (attempt_id, attempt_version),
    ).fetchone()
    return _assessment_from_row(row) if row else None


def _validated_feedback(feedback: Any) -> dict[str, Any]:
    if not isinstance(feedback, dict):
        raise TypeError("feedback must be a mapping")
    missing = [field for field in _CHILD_FEEDBACK_FIELDS if field not in feedback]
    if missing:
        raise ValueError(f"feedback is missing fields: {', '.join(missing)}")
    if not isinstance(feedback["improvement_direction"], list):
        raise TypeError("improvement_direction must be a list")
    for field in (
        "reference_answer",
        "answer_gap",
        "expression_judgment",
        "teaching_explanation",
    ):
        _nonempty_text(feedback[field], field)
    return {field: deepcopy(feedback[field]) for field in _CHILD_FEEDBACK_FIELDS}


def accept_assessment(
    conn: sqlite3.Connection,
    *,
    assessment_id: str,
    criterion_judgments: list[dict[str, Any]],
    score_out_of_10: float | int | None,
    question_passed: bool,
    feedback: dict[str, Any],
    assessment_digest_sha256: str,
    answer_analysis_agent_run_id: str | None,
    provider_mode: str,
    compatibility_score_points: float | int | None = None,
    compatibility_result: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    assessment_id = _nonempty_text(assessment_id, "assessment_id")
    digest = _nonempty_text(
        assessment_digest_sha256, "assessment_digest_sha256"
    )
    provider_mode = _nonempty_text(provider_mode, "provider_mode")

    with (conn if commit else nullcontext()):
        row = conn.execute(
            "select * from attempt_assessments where id = ?", (assessment_id,)
        ).fetchone()
        if not row:
            raise ValueError("assessment does not exist")
        pending = _assessment_from_row(row)
        if pending["status"] == "accepted":
            if pending["assessment_digest_sha256"] != digest:
                raise ValueError("accepted assessment retry has a conflicting digest")
            return pending
        if pending["status"] != "pending":
            raise ValueError("only a pending assessment can be accepted")

        current = conn.execute(
            """
            select * from attempt_assessments
            where attempt_id = ? and attempt_version = ? and status = 'accepted'
            limit 1
            """,
            (pending["attempt_id"], pending["attempt_version"]),
        ).fetchone()
        if current:
            raise ValueError("an accepted assessment already exists for this attempt version")

        contract = _load_contract_exact(
            conn,
            contract_id=pending["answer_contract_id"],
            contract_version=pending["answer_contract_version"],
            contract_digest_sha256=pending["answer_contract_digest_sha256"],
        )
        policy_contract = _policy_contract(contract)
        assessment_policy.validate_contract(policy_contract)
        assessment_policy.validate_criterion_judgments(
            policy_contract, criterion_judgments
        )
        calculated = assessment_policy.calculate_assessment(
            policy_contract, criterion_judgments
        )
        if not calculated["finalized"]:
            raise ValueError("unclear criterion judgments cannot be accepted")
        if score_out_of_10 != calculated["score_out_of_10"]:
            raise ValueError("score does not match deterministic policy")
        if question_passed is not calculated["question_passed"]:
            raise ValueError("question pass result does not match deterministic policy")
        derived_compatibility_score = calculated["score_out_of_10"] / 5
        if calculated["score_out_of_10"] == 10 and calculated["question_passed"]:
            derived_compatibility_result = "correct"
        elif calculated["score_out_of_10"] == 0:
            derived_compatibility_result = "wrong"
        else:
            derived_compatibility_result = "partial"
        if (
            compatibility_score_points is not None
            and compatibility_score_points != derived_compatibility_score
        ):
            raise ValueError("compatibility score does not match deterministic policy")
        if (
            compatibility_result is not None
            and compatibility_result != derived_compatibility_result
        ):
            raise ValueError("compatibility result does not match deterministic policy")
        child_feedback = _validated_feedback(feedback)

        attempt_before = conn.execute(
            """
            select answer_raw, attachment_ids_json, interaction_response_json
            from attempts where id = ? and attempt_version = ?
            """,
            (pending["attempt_id"], pending["attempt_version"]),
        ).fetchone()
        if not attempt_before:
            raise ValueError("assessment attempt no longer exists")

        previous = conn.execute(
            """
            select id from attempt_assessments
            where attempt_id = ? and attempt_version = ? and status = 'superseded'
            order by assessment_version desc, id desc
            limit 1
            """,
            (pending["attempt_id"], pending["attempt_version"]),
        ).fetchone()
        now = db.now_iso()
        run_id = _agent_run_if_present(conn, answer_analysis_agent_run_id)
        if answer_analysis_agent_run_id and not run_id:
            raise ValueError("answer analysis agent run does not exist")
        conn.execute(
            """
            update attempt_assessments
            set assessment_digest_sha256 = ?, criterion_judgments_json = ?,
                score_out_of_10 = ?, question_passed = ?, reference_answer_json = ?,
                answer_gap = ?, improvement_direction_json = ?,
                expression_judgment = ?, teaching_explanation = ?,
                trust_label = 'accepted', provider_mode = ?,
                answer_analysis_agent_run_id = ?, status = 'accepted',
                supersedes_assessment_id = ?, accepted_at = ?, updated_at = ?
            where id = ? and status = 'pending'
            """,
            (
                digest,
                db.json_dump(criterion_judgments),
                calculated["score_out_of_10"],
                1 if calculated["question_passed"] else 0,
                db.json_dump(child_feedback["reference_answer"]),
                child_feedback["answer_gap"],
                db.json_dump(child_feedback["improvement_direction"]),
                child_feedback["expression_judgment"],
                child_feedback["teaching_explanation"],
                provider_mode,
                run_id,
                previous["id"] if previous else None,
                now,
                now,
                assessment_id,
            ),
        )
        analysis_projection = {
            "score_out_of_10": calculated["score_out_of_10"],
            "question_passed": calculated["question_passed"],
            "reference_answer": child_feedback["reference_answer"],
            "answer_gap": child_feedback["answer_gap"],
            "improvement_direction": child_feedback["improvement_direction"],
            "expression_judgment": child_feedback["expression_judgment"],
            "teaching_explanation": child_feedback["teaching_explanation"],
        }
        conn.execute(
            """
            update attempts
            set score_points = ?, max_points = 2, result = ?,
                answer_analysis_json = ?, grading_status = 'graded',
                analysis_status = 'valid'
            where id = ? and attempt_version = ?
            """,
            (
                derived_compatibility_score,
                derived_compatibility_result,
                db.json_dump(analysis_projection),
                pending["attempt_id"],
                pending["attempt_version"],
            ),
        )
        attempt_after = conn.execute(
            """
            select answer_raw, attachment_ids_json, interaction_response_json
            from attempts where id = ? and attempt_version = ?
            """,
            (pending["attempt_id"], pending["attempt_version"]),
        ).fetchone()
        if tuple(attempt_before) != tuple(attempt_after):
            raise ValueError("raw attempt evidence changed during assessment acceptance")

        accepted = conn.execute(
            "select * from attempt_assessments where id = ?", (assessment_id,)
        ).fetchone()
        return _assessment_from_row(accepted)


def supersede_assessment(
    conn: sqlite3.Connection, *, assessment_id: str, reason: str
) -> dict[str, Any]:
    assessment_id = _nonempty_text(assessment_id, "assessment_id")
    reason = _nonempty_text(reason, "reason")
    with conn:
        row = conn.execute(
            "select * from attempt_assessments where id = ?", (assessment_id,)
        ).fetchone()
        if not row:
            raise ValueError("assessment does not exist")
        assessment = _assessment_from_row(row)
        if assessment["status"] == "superseded":
            return assessment
        if assessment["status"] != "accepted":
            raise ValueError("only an accepted assessment can be superseded")
        now = db.now_iso()
        conn.execute(
            """
            update attempt_assessments
            set status = 'superseded', rejection_reason = ?,
                superseded_at = ?, updated_at = ?
            where id = ? and status = 'accepted'
            """,
            (reason, now, now, assessment_id),
        )
        conn.execute(
            """
            update attempts
            set score_points = 0, max_points = 2, result = 'pending',
                answer_analysis_json = '{}', grading_status = 'pending_review',
                analysis_status = 'pending'
            where id = ? and attempt_version = ?
            """,
            (assessment["attempt_id"], assessment["attempt_version"]),
        )
        superseded = conn.execute(
            "select * from attempt_assessments where id = ?", (assessment_id,)
        ).fetchone()
        return _assessment_from_row(superseded)


def assessment_feedback_projection(assessment: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(assessment, dict):
        raise TypeError("assessment must be a mapping")
    score = assessment.get("score_out_of_10")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("accepted assessment score is required")
    score_text = f"{score:g}"
    return {
        "score_label": f"{score_text}/10",
        "reference_answer": deepcopy(assessment.get("reference_answer")),
        "answer_gap": assessment.get("answer_gap", ""),
        "improvement_direction": deepcopy(
            assessment.get("improvement_direction") or []
        ),
        "expression_judgment": assessment.get("expression_judgment", ""),
    }
