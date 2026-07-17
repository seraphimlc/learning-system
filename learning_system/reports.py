from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import agents, db, evolution, question_bank


CORE_PIPELINE_PHASES = [
    "evidence_package",
    "answer_analysis_package",
    "graph_binding",
    "evaluation_decision",
    "teaching_decision",
    "planner_transition",
    "teaching_step",
    "session_close",
]


REPORT_CLAIM_LABELS = db.V3_REPORT_CLAIM_LABELS
V5_MODEL_JOB_PHASES = ("answer_analysis", "evaluation_update", "planner_decision", "teaching_generation")


def report_claim_label(
    *,
    confirmed: bool = False,
    pending: bool = False,
    stale: bool = False,
    blocked: bool = False,
    mock_only: bool = False,
    missing_lineage: bool = False,
    inferred: bool = False,
) -> str:
    if blocked:
        return "blocked"
    if stale:
        return "stale"
    if missing_lineage:
        return "missing_lineage"
    if mock_only:
        return "mock_only"
    if pending:
        return "pending"
    if inferred:
        return "inferred"
    if confirmed:
        return "confirmed"
    return "missing_lineage"


def _scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(query, params).fetchone()[0])


def v5_stage_lineage_summary(conn: sqlite3.Connection, flow_id: str) -> dict[str, Any]:
    """Read-only skeleton for the v5 true-Agent DAG lineage report."""
    jobs = [dict(row) for row in conn.execute(
        """
        select id, job_type, status, attempt_id, provider_mode, result_refs_json,
               run_count, idempotency_key, depends_on_job_id, retry_after,
               available_at, started_at, finished_at,
               last_error, blocked_reason, dead_letter_reason
        from background_jobs
        where flow_id = ?
          and job_type in ('answer_analysis','evaluation_update','planner_decision','teaching_generation')
        order by created_at, id
        """,
        (flow_id,),
    ).fetchall()]
    phases = {phase: [] for phase in V5_MODEL_JOB_PHASES}
    for job in jobs:
        phases.setdefault(str(job.get("job_type") or ""), []).append({
            "job_id": job.get("id"),
            "status": job.get("status"),
            "attempt_id": job.get("attempt_id"),
            "provider_mode": job.get("provider_mode"),
            "result_refs": db.json_load(job.get("result_refs_json"), {}),
            "run_count": int(job.get("run_count") or 0),
            "idempotency_key": job.get("idempotency_key") or "",
            "depends_on_job_id": job.get("depends_on_job_id") or "",
            "retry_after": job.get("retry_after") or "",
            "available_at": job.get("available_at") or "",
            "started_at": job.get("started_at") or "",
            "finished_at": job.get("finished_at") or "",
            "last_error": job.get("last_error") or job.get("blocked_reason") or job.get("dead_letter_reason") or "",
        })
    return {"flow_id": flow_id, "phases": phases}


def _latest_child_sessions(conn: sqlite3.Connection, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select *
        from learning_sessions
        where mode = 'child_learning_group'
        order by created_at desc, id desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [db.get_learning_session(conn, row["id"]) for row in rows]


def _latest_daily_flows(conn: sqlite3.Connection, *, report_date: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select *
        from daily_flows
        where local_date <= ?
        order by local_date desc, updated_at desc, id desc
        limit ?
        """,
        (report_date, limit),
    ).fetchall()
    flow_summaries: list[dict[str, Any]] = []
    for row in rows:
        flow = dict(row)
        steps = [dict(item) for item in conn.execute(
            "select * from flow_steps where flow_id = ? order by position, created_at, id",
            (flow["id"],),
        ).fetchall()]
        attempts = [dict(item) for item in conn.execute(
            """
            select a.*, q.prompt as question_prompt, q.kind as question_kind
            from attempts a
            left join question_items q on q.id = a.question_id
            where a.flow_step_id in (
              select id from flow_steps where flow_id = ?
            )
            order by a.created_at, a.id
            """,
            (flow["id"],),
        ).fetchall()]
        validations = [dict(item) for item in conn.execute(
            """
            select *
            from evidence_validations
            where attempt_id in (
              select id
              from attempts
              where flow_step_id in (select id from flow_steps where flow_id = ?)
            )
            order by created_at, id
            """,
            (flow["id"],),
        ).fetchall()]
        decisions = [dict(item) for item in conn.execute(
            "select * from next_step_decisions where flow_id = ? order by created_at, id",
            (flow["id"],),
        ).fetchall()]
        mastery_rows = [dict(item) for item in conn.execute(
            "select * from mastery_decisions where session_id = ? order by created_at, id",
            (flow.get("legacy_session_id") or "",),
        ).fetchall()]
        summary_row = conn.execute(
            """
            select *
            from daily_summaries
            where flow_id = ?
            order by created_at desc, id desc
            limit 1
            """,
            (flow["id"],),
        ).fetchone()
        summary = dict(summary_row) if summary_row else {}
        report_labels: dict[str, int] = {}
        if summary:
            report_labels = db.json_load(summary.get("report_label_json"), {})
        for validation in validations:
            predicate = db.json_load(validation.get("predicate_result_json"), {})
            label = str(predicate.get("report_label") or validation.get("gate_status") or "pending")
            if not summary:
                report_labels[label] = report_labels.get(label, 0) + 1
        freshness = "current"
        if summary:
            freshness = "current" if int(summary.get("flow_revision") or 0) == int(flow.get("flow_revision") or 0) else "stale"
        elif flow.get("status") in {"completed", "superseded"}:
            freshness = "missing_summary"
        else:
            freshness = "open"
        step_by_id = {step["id"]: step for step in steps}
        attempt_evidence = []
        for attempt in attempts:
            step = step_by_id.get(attempt.get("flow_step_id"), {})
            analysis = db.json_load(attempt.get("answer_analysis_json"), {})
            review_meta = db.json_load(attempt.get("review_meta_json"), {})
            attempt_evidence.append({
                "attempt_id": attempt["id"],
                "step_type": step.get("step_type", ""),
                "node_id": attempt.get("node_id", ""),
                "question_id": attempt.get("question_id", ""),
                "question_kind": attempt.get("question_kind", ""),
                "question_prompt": str(attempt.get("question_prompt") or "")[:500],
                "selection_reason": db.json_load(step.get("selection_reason_json"), {}),
                "answer_raw": str(attempt.get("answer_raw") or "")[:800],
                "result": attempt.get("result", ""),
                "grading_status": attempt.get("grading_status", ""),
                "analysis_status": attempt.get("analysis_status", ""),
                "process_gap": str(analysis.get("process_gap") or "")[:600],
                "child_answer_summary": str(analysis.get("child_answer_summary") or "")[:600],
                "next_child_prompt": str(analysis.get("next_child_prompt") or "")[:400],
                "review_status": str(review_meta.get("status") or ""),
                "review_confidence": review_meta.get("confidence"),
            })
        mastery_updates = [
            {
                "id": item["id"],
                "node_id": item.get("node_id", ""),
                "decision": item.get("decision", ""),
                "new_status_code": item.get("new_status_code", ""),
                "applied": bool(item.get("applied")),
                "reason": item.get("reason", ""),
                "evaluation_agent_run_id": item.get("evaluation_agent_run_id") or item.get("agent_run_id") or "",
                "source_validation_ids": db.json_load(item.get("source_evidence_validation_ids_json"), []),
                "dimension_scores": db.json_load(item.get("dimension_scores_json"), {}),
            }
            for item in mastery_rows
        ]
        next_decisions = [
            {
                "id": item["id"],
                "action": item.get("action", ""),
                "target_node_id": item.get("target_node_id", ""),
                "decision_status": item.get("decision_status", ""),
                "report_label": item.get("report_label", ""),
                "provider_mode": item.get("provider_mode", ""),
                "reason": item.get("reason", ""),
                "planner_agent_run_id": item.get("planner_agent_run_id", ""),
                "source_attempt_ids": db.json_load(item.get("source_attempt_ids_json"), []),
                "source_validation_ids": db.json_load(item.get("source_evidence_validation_ids_json"), []),
                "source_mastery_ids": db.json_load(item.get("source_mastery_decision_ids_json"), []),
                "candidate_packet_id": item.get("candidate_packet_id", ""),
            }
            for item in decisions
        ]
        flow_summaries.append({
            "id": flow["id"],
            "local_date": flow["local_date"],
            "mode": flow["mode"],
            "status": flow["status"],
            "flow_revision": int(flow.get("flow_revision") or 0),
            "current_step_id": flow.get("current_step_id"),
            "summary_id": summary.get("id", ""),
            "summary_revision": int(summary.get("flow_revision") or 0) if summary else 0,
            "summary_freshness": freshness,
            "step_count": len(steps),
            "attempt_count": len(attempts),
            "validation_count": len(validations),
            "decision_count": len(decisions),
            "touched_node_ids": sorted({attempt["node_id"] for attempt in attempts if attempt.get("node_id")}),
            "report_labels": report_labels,
            "pending_attempt_ids": [attempt["id"] for attempt in attempts if attempt.get("grading_status") == "pending_review"],
            "blocked_reason": flow.get("blocked_reason", ""),
            "attempt_evidence": attempt_evidence,
            "mastery_updates": mastery_updates,
            "next_step_decisions": next_decisions,
            "phase_lineage": v5_stage_lineage_summary(conn, flow["id"]),
            "latest_decision": {
                "id": decisions[-1]["id"],
                "action": decisions[-1]["action"],
                "report_label": decisions[-1]["report_label"],
                "reason": decisions[-1]["reason"],
            } if decisions else {},
            "operator_summary": db.json_load(summary.get("operator_summary_json"), {}) if summary else {},
        })
    return flow_summaries


def _pipeline_status(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    phases = [
        row["phase"] for row in conn.execute(
            """
            select distinct phase
            from session_steps
            where session_id = ?
            order by phase
            """,
            (session_id,),
        ).fetchall()
    ]
    missing = [phase for phase in CORE_PIPELINE_PHASES if phase not in phases]
    if not phases:
        completeness = "none"
    elif missing:
        completeness = "partial"
    else:
        completeness = "complete"
    return {
        "session_id": session_id,
        "lineage_completeness": completeness,
        "recorded_phases": phases,
        "missing_phases": missing,
    }


def generate_daily_report(conn: sqlite3.Connection, *, report_date: str | None = None) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report_date = report_date or generated_at[:10]
    agent_reports = agents.build_agent_reports(conn)
    sessions = _latest_child_sessions(conn)
    daily_flows = _latest_daily_flows(conn, report_date=report_date)
    session_summaries = []
    for session in sessions:
        summary = db.session_completion_summary(conn, session["id"])
        pipeline = _pipeline_status(conn, session["id"])
        session_summaries.append({
            "id": session["id"],
            "title": session["title"],
            "status": session["status"],
            "closure_status": session["closure_status"],
            "created_at": session["created_at"],
            "closed_at": session.get("closed_at"),
            "attempt_summary": summary,
            "lineage_completeness": pipeline["lineage_completeness"],
            "missing_phases": pipeline["missing_phases"],
        })

    pending_attempts = len(db.current_active_attempts(conn, grading_status="pending_review"))
    missing_analysis = len(db.current_attempts_missing_valid_analysis(conn))
    latest_pipeline = _pipeline_status(conn, sessions[0]["id"]) if sessions else {
        "lineage_completeness": "not_applicable",
        "missing_phases": [],
    }
    quality_audit = agent_reports["question_production_agent"]["quality_audit"]
    lineage_audit = db.lineage_integrity_audit(conn)
    coverage_row = conn.execute(
        """
        select min(item_count) as min_count,
               max(item_count) as max_count,
               count(*) as node_count,
               sum(item_count) as total_count
        from (
          select n.id, count(q.id) as item_count
          from graph_nodes n
          left join question_items q on q.node_id = n.id
            and q.source_type = 'graph_generated'
            and q.item_version = ?
          group by n.id
        )
        """,
        (question_bank.QUESTION_BANK_VERSION,),
    ).fetchone()
    issues = []
    v5_pending = sum(len(flow.get("pending_attempt_ids", [])) for flow in daily_flows)
    stale_v5 = [flow for flow in daily_flows if flow.get("summary_freshness") in {"stale", "missing_summary"}]
    blocked_v5 = [flow for flow in daily_flows if flow.get("status") == "blocked"]
    v5_label_counts: dict[str, int] = {}
    for flow in daily_flows:
        for label, count in (flow.get("report_labels") or {}).items():
            v5_label_counts[str(label)] = v5_label_counts.get(str(label), 0) + int(count or 0)
    has_learning_evidence = bool(sessions) or any(
        int(flow.get("attempt_count") or 0) > 0
        or int(flow.get("validation_count") or 0) > 0
        or int(flow.get("decision_count") or 0) > 0
        or flow.get("summary_freshness") == "current"
        for flow in daily_flows
    )
    if v5_pending:
        issues.append(f"v5 daily flow 仍有 {v5_pending} 条提交等待分析")
    if stale_v5:
        issues.append(f"{len(stale_v5)} 个 v5 summary 不是当前 flow_revision")
    if blocked_v5:
        issues.append(f"{len(blocked_v5)} 个 v5 daily flow 处于 blocked")
    if v5_label_counts.get("mock_only"):
        issues.append(f"v5 daily flow 有 {v5_label_counts['mock_only']} 条 mock-only 证据，不能作为真实掌握证据")
    if v5_label_counts.get("missing_lineage"):
        issues.append(f"v5 daily flow 有 {v5_label_counts['missing_lineage']} 条 missing-lineage 证据")
    if pending_attempts:
        issues.append(f"{pending_attempts} 条提交仍在等待系统分析")
    if missing_analysis:
        issues.append(f"{missing_analysis} 条已评分记录缺结构化答案分析")
    if quality_audit.get("issues"):
        issues.append(f"{len(quality_audit['issues'])} 道题未通过当前审题门")
    if sessions and latest_pipeline["lineage_completeness"] != "complete":
        issues.append(f"最近学习组流程 lineage 为 {latest_pipeline['lineage_completeness']}")
    if lineage_audit["issue_count"]:
        issues.append(f"{lineage_audit['issue_count']} 个 lineage integrity 问题需要修复")
    if not issues:
        issues.append("当前没有 P0 阻塞，继续观察真实学习数据")

    return {
        "report_date": report_date,
        "generated_at": generated_at,
        "summary": {
            "child_learning_sessions": len(sessions),
            "v5_daily_flows": len(daily_flows),
            "v5_pending_attempts": v5_pending,
            "v5_stale_or_missing_summaries": len(stale_v5),
            "v5_blocked_flows": len(blocked_v5),
            "pending_attempts": pending_attempts,
            "missing_answer_analysis": missing_analysis,
            "recent_evolution_events": _scalar(conn, "select count(*) from evolution_events"),
            "latest_pipeline_completeness": latest_pipeline["lineage_completeness"],
            "question_quality_issues": len(quality_audit.get("issues", [])),
            "lineage_integrity_issues": lineage_audit["issue_count"],
            "evidence_label": report_claim_label(
                confirmed=has_learning_evidence
                and not (
                    pending_attempts
                    or missing_analysis
                    or lineage_audit["issue_count"]
                    or v5_pending
                    or stale_v5
                    or blocked_v5
                    or v5_label_counts.get("mock_only")
                    or v5_label_counts.get("missing_lineage")
                    or v5_label_counts.get("pending")
                    or v5_label_counts.get("blocked")
                ),
                pending=bool(pending_attempts or missing_analysis or v5_pending or v5_label_counts.get("pending")),
                stale=bool(stale_v5 or v5_label_counts.get("stale")),
                blocked=bool(lineage_audit["issue_count"] or blocked_v5 or v5_label_counts.get("blocked")),
                mock_only=bool(v5_label_counts.get("mock_only")),
                missing_lineage=bool(v5_label_counts.get("missing_lineage")),
                inferred=not has_learning_evidence,
            ),
            "question_bank_version": question_bank.QUESTION_BANK_VERSION,
            "current_practice_questions": int(coverage_row["total_count"] or 0),
            "current_practice_nodes": int(coverage_row["node_count"] or 0),
            "current_practice_min_per_node": int(coverage_row["min_count"] or 0),
            "current_practice_max_per_node": int(coverage_row["max_count"] or 0),
        },
        "daily_flows": daily_flows,
        "sessions": session_summaries,
        "agent_reports": agent_reports,
        "lineage_integrity": lineage_audit,
        "recent_evolution_events": evolution.recent_events(conn, 8),
        "issues": issues,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# Learning System Daily Report - {report['report_date']}",
        "",
        f"Generated UTC: `{report['generated_at']}`",
        "",
        "## Snapshot",
        "",
        f"- Child learning sessions checked: {summary['child_learning_sessions']}",
        f"- v5 daily flows checked: {summary['v5_daily_flows']}",
        f"- v5 pending attempts: {summary['v5_pending_attempts']}",
        f"- v5 stale/missing summaries: {summary['v5_stale_or_missing_summaries']}",
        f"- v5 blocked flows: {summary['v5_blocked_flows']}",
        f"- Pending attempts: {summary['pending_attempts']}",
        f"- Missing structured answer analysis: {summary['missing_answer_analysis']}",
        f"- Recent evolution events: {summary['recent_evolution_events']}",
        f"- Latest pipeline completeness: `{summary['latest_pipeline_completeness']}`",
        f"- Current question bank: `{summary['question_bank_version']}` "
        f"{summary['current_practice_questions']} questions, "
        f"per-node range {summary['current_practice_min_per_node']}-{summary['current_practice_max_per_node']}",
        f"- Question quality issues: {summary['question_quality_issues']}",
        f"- Lineage integrity issues: {summary['lineage_integrity_issues']}",
        "",
        "## Current Issues",
        "",
    ]
    lines.extend(f"- {issue}" for issue in report["issues"])
    lines.extend(["", "## v5 Daily Flows", ""])
    if not report.get("daily_flows"):
        lines.append("- No v5 daily flow yet.")
    for flow in report.get("daily_flows", [])[:8]:
        labels = flow.get("report_labels") or {}
        label_text = ", ".join(f"{key}:{value}" for key, value in sorted(labels.items())) or "none"
        latest_decision = flow.get("latest_decision") or {}
        decision_text = "none"
        if latest_decision:
            decision_text = (
                f"{latest_decision.get('action', 'unknown')} "
                f"[{latest_decision.get('report_label', 'missing_lineage')}]"
            )
        nodes = ", ".join(flow.get("touched_node_ids") or []) or "none"
        lines.append(
            "- "
            f"`{flow['id']}` {flow['local_date']} | "
            f"status `{flow['status']}` rev `{flow['flow_revision']}` | "
            f"steps {flow['step_count']}, attempts {flow['attempt_count']}, validations {flow['validation_count']} | "
            f"summary `{flow['summary_freshness']}` | labels `{label_text}`"
        )
        lines.append(f"  Nodes touched: `{nodes}`")
        lines.append(f"  Latest decision: `{decision_text}`")
        if flow.get("pending_attempt_ids"):
            lines.append(f"  Pending attempts: `{len(flow['pending_attempt_ids'])}`")
        if flow.get("status") == "blocked" and flow.get("blocked_reason"):
            lines.append(f"  Blocked reason: {flow['blocked_reason']}")
        phase_lineage = (flow.get("phase_lineage") or {}).get("phases") or {}
        terminal_historical_flow = flow.get("status") in {"completed", "superseded"}
        for phase in V5_MODEL_JOB_PHASES:
            phase_jobs = phase_lineage.get(phase) or []
            if not phase_jobs:
                continue
            phase_text = ", ".join(
                (
                    f"`{item.get('job_id', 'unknown')}` "
                    f"{item.get('status', 'unknown')}/{item.get('provider_mode', 'not_configured')}"
                    f"{'/historical_terminal' if terminal_historical_flow and item.get('status') in {'blocked', 'dead_letter'} else ''} "
                    f"runs={item.get('run_count', 0)}"
                )
                for item in phase_jobs
            )
            lines.append(f"  Agent phase `{phase}`: {phase_text}")
            for item in phase_jobs:
                dependency = item.get("depends_on_job_id") or "root"
                lines.append(
                    f"    Job `{item.get('job_id')}` depends_on `{dependency}` "
                    f"idempotency `{item.get('idempotency_key') or 'missing'}`"
                )
                if item.get("retry_after") or item.get("available_at"):
                    lines.append(
                        f"      Retry/availability: `{item.get('retry_after') or 'none'}` / "
                        f"`{item.get('available_at') or 'none'}`"
                    )
                if item.get("last_error"):
                    if terminal_historical_flow and item.get("status") in {"blocked", "dead_letter"}:
                        lines.append(f"      Historical terminal error: {item['last_error']}")
                    else:
                        lines.append(f"      Last error: {item['last_error']}")
        for evidence in flow.get("attempt_evidence") or []:
            prompt = " ".join(str(evidence.get("question_prompt") or "").split())
            answer = " ".join(str(evidence.get("answer_raw") or "").split())
            gap = " ".join(str(evidence.get("process_gap") or "").split())
            reason = evidence.get("selection_reason") or {}
            why = str(reason.get("reason") or reason.get("selection_reason") or "")
            lines.append(
                "  Attempt "
                f"`{evidence.get('attempt_id')}` node `{evidence.get('node_id')}` "
                f"result `{evidence.get('result')}/{evidence.get('analysis_status')}` "
                f"review `{evidence.get('review_status') or 'unknown'}`"
            )
            if why:
                lines.append(f"    Why selected: {why}")
            if prompt:
                lines.append(f"    Question: {prompt[:360]}")
            if answer:
                lines.append(f"    Child evidence: {answer[:420]}")
            if gap:
                lines.append(f"    Process gap: {gap[:420]}")
        for mastery in flow.get("mastery_updates") or []:
            lines.append(
                "  Mastery update "
                f"`{mastery.get('id')}` node `{mastery.get('node_id')}` -> "
                f"`{mastery.get('new_status_code') or mastery.get('decision')}` "
                f"applied `{str(bool(mastery.get('applied'))).lower()}`"
            )
            if mastery.get("reason"):
                lines.append(f"    Evaluation reason: {mastery['reason']}")
        for decision in flow.get("next_step_decisions") or []:
            lines.append(
                "  Next-step decision "
                f"`{decision.get('id')}` action `{decision.get('action')}` "
                f"target `{decision.get('target_node_id') or 'none'}` "
                f"label `{decision.get('report_label') or 'missing_lineage'}` "
                f"mode `{decision.get('provider_mode') or 'not_configured'}`"
            )
            if decision.get("reason"):
                lines.append(f"    Planner reason: {decision['reason']}")
    lines.extend(["", "## Latest Sessions", ""])
    if not report["sessions"]:
        lines.append("- No child learning session yet.")
    for session in report["sessions"][:5]:
        attempt = session["attempt_summary"]
        lines.append(
            "- "
            f"`{session['id']}` {session['title']} | "
            f"status `{session['status']}/{session['closure_status']}` | "
            f"submitted {attempt['submitted']}/{attempt['expected']}, "
            f"graded {attempt['graded']}, pending {attempt['pending']}, analyzed {attempt['analyzed']} | "
            f"lineage `{session['lineage_completeness']}`"
        )
        if session["missing_phases"]:
            lines.append(f"  Missing phases: `{', '.join(session['missing_phases'])}`")
    lines.extend(["", "## Runtime / Agent State", ""])
    lines.append("- DailyLearningRuntime: authoritative flow, persistence, evidence gate, and child projection owner")
    lines.append("- Graph source: versioned initialization asset; not a per-answer semantic agent")
    for key in (
        "answer_analysis_agent",
        "evaluation_agent",
        "teaching_agent",
        "planner_agent",
        "question_designer_agent",
        "question_reviewer_agent",
    ):
        item = report["agent_reports"].get(key, {})
        status = item.get("status") or item.get("stage") or "unknown"
        display = item.get("display_name", key)
        if key == "evaluation_agent":
            lines.append(f"- {display} teaching_stage: `{status}`")
        else:
            lines.append(f"- {display}: `{status}`")
    lines.append("- Self-evolution: `paused`; proposals may be recorded but cannot mutate active graph, bank, mastery, or plan")
    lines.extend(["", "## Recent Evolution", ""])
    if not report["recent_evolution_events"]:
        lines.append("- No evolution events recorded.")
    for event in report["recent_evolution_events"]:
        lines.append(
            f"- `{event['id']}` status `{event['status']}` type `{event['event_type']}` "
            f"evidence {len(event.get('evidence_attempt_ids', []))} created questions {len(event.get('created_question_ids', []))}"
        )
    lines.append("")
    return "\n".join(lines)


def write_daily_report(conn: sqlite3.Connection, output_dir: Path, *, report_date: str | None = None) -> dict[str, Any]:
    report = generate_daily_report(conn, report_date=report_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    dated_path = output_dir / f"{report['report_date']}.md"
    latest_path = output_dir / "latest.md"
    text = render_markdown(report)
    dated_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    return {**report, "paths": {"dated": str(dated_path), "latest": str(latest_path)}}
