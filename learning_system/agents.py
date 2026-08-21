from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from . import db, evolution, planner, question_bank


def _scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(query, params).fetchone()[0])


def _latest_generated_plan_report(conn: sqlite3.Connection) -> tuple[dict[str, Any] | None, bool]:
    row = conn.execute(
        """
        select id, title, tasks_json, planner_policy_version, created_at
        from generated_plans
        order by created_at desc, rowid desc
        limit 1
        """
    ).fetchone()
    if not row:
        return None, False
    plan = {
        "id": row["id"],
        "title": row["title"],
        "planner_policy_version": row["planner_policy_version"],
        "plan_policy_version": row["planner_policy_version"],
        "tasks": db.json_load(row["tasks_json"], []),
        "created_at": row["created_at"],
    }
    current = (
        row["planner_policy_version"] == planner.PLANNER_POLICY_VERSION
        and planner.plan_uses_current_active_bank(conn, plan)
    )
    return plan, current


CURRENT_ATTEMPT_VERSION_FILTER = """
(
  (q.source_type = 'graph_generated' and q.item_version = ?)
  or (q.source_type = 'evolved' and q.item_version = ?)
  or q.source_type not in ('graph_generated', 'evolved')
)
"""


def _active_current_attempt_count(
    conn: sqlite3.Connection,
    *,
    extra_where: str = "",
    extra_params: tuple[Any, ...] = (),
) -> int:
    return _scalar(
        conn,
        f"""
        select count(*)
        from attempts a
        join question_items q on q.id = a.question_id
        where a.evidence_status = 'active'
          and {CURRENT_ATTEMPT_VERSION_FILTER}
          {extra_where}
        """,
        (question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION, *extra_params),
    )


def _json_list(value: str | None) -> list[Any]:
    loaded = db.json_load(value, [])
    return loaded if isinstance(loaded, list) else []


def _node_ref_issues(conn: sqlite3.Connection) -> list[dict[str, str]]:
    known = {row["id"] for row in conn.execute("select id from graph_nodes").fetchall()}
    issues: list[dict[str, str]] = []
    for row in conn.execute("select id, prerequisites_json, unlocks_json from graph_nodes order by id").fetchall():
        for field in ("prerequisites_json", "unlocks_json"):
            relation = "prerequisite" if field == "prerequisites_json" else "unlock"
            for target in _json_list(row[field]):
                if target not in known:
                    issues.append({"node_id": row["id"], "missing_node_id": str(target), "relation": relation})
    for row in conn.execute(
        """
        select e.from_node_id, e.to_node_id, e.relation
        from graph_edges e
        left join graph_nodes f on f.id = e.from_node_id
        left join graph_nodes t on t.id = e.to_node_id
        where f.id is null or t.id is null
        order by e.from_node_id, e.to_node_id, e.relation
        """
    ).fetchall():
        issues.append({
            "node_id": row["from_node_id"],
            "missing_node_id": row["to_node_id"],
            "relation": row["relation"],
        })
    return issues


def _question_ref_issues(conn: sqlite3.Connection) -> list[dict[str, str]]:
    issues = []
    for row in conn.execute(
        """
        select q.id as question_id, q.node_id
        from question_items q
        left join graph_nodes n on n.id = q.node_id
        where n.id is null
        order by q.id
        """
    ).fetchall():
        issues.append({"question_id": row["question_id"], "missing_node_id": row["node_id"], "relation": "primary_node"})
    known = {row["id"] for row in conn.execute("select id from graph_nodes").fetchall()}
    for row in conn.execute(
        """
        select id, rollback_candidate_node_ids_json
        from question_items
        order by id
        """
    ).fetchall():
        for node_id in _json_list(row["rollback_candidate_node_ids_json"]):
            if node_id not in known:
                issues.append({"question_id": row["id"], "missing_node_id": str(node_id), "relation": "rollback_candidate"})
    return issues


def _question_quality_audit(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        select *
        from question_items
        where source_type in ('graph_generated', 'evolved')
        order by source_type, node_id, id
        """
    ).fetchall()
    active_rows = []
    legacy_rows = []
    archived_rows = []
    issues = []
    status_counts: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    latest_versions = {question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION}
    for row in rows:
        item = db.row_to_question(row)
        if (item.get("source") or {}).get("evidence_status") == "invalidated":
            archived_rows.append(item)
            continue
        if item["item_version"] not in latest_versions:
            legacy_rows.append(item)
            continue
        active_rows.append(item)
        quality = item.get("quality") or {}
        status_counts[quality.get("review_status", "missing")] += 1
        for reason in quality.get("rejection_reasons", []):
            rejection_reasons[reason] += 1
        if not question_bank.is_item_approved_for_active_use(item):
            issues.append({
                "question_id": item["id"],
                "node_id": item["node_id"],
                "item_version": item["item_version"],
                "reason": quality.get("rejection_reasons") or ["missing_or_unapproved_quality_metadata"],
            })
    return {
        "active_count": len(active_rows),
        "legacy_count": len(legacy_rows),
        "archived_count": len(archived_rows),
        "status_counts": dict(status_counts),
        "rejection_reason_counts": dict(rejection_reasons),
        "issues": issues[:30],
    }


def _hotspots(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for attempt in db.current_usable_attempts(conn):
        node = conn.execute("select name from graph_nodes where id = ?", (attempt["node_id"],)).fetchone()
        item = grouped.setdefault(attempt["node_id"], {
            "node_id": attempt["node_id"],
            "node_name": node["name"] if node else attempt["node_id"],
            "graded_count": 0,
            "weak_count": 0,
            "blocking_count": 0,
            "evidence_attempt_ids": [],
            "error_tags": [],
        })
        item["graded_count"] += 1
        weak = attempt["result"] in {"wrong", "partial"} and float(attempt["score_points"]) < float(attempt["max_points"])
        if weak:
            item["weak_count"] += 1
            item["evidence_attempt_ids"].append(attempt["id"])
        if attempt["blocking_evidence"]:
            item["blocking_count"] += 1
        item["error_tags"].extend(attempt.get("error_tags") or [])

    hotspots = []
    for item in grouped.values():
        if item["weak_count"] == 0 and item["blocking_count"] == 0:
            continue
        item["dominant_error_tags"] = [tag for tag, _ in Counter(item.pop("error_tags")).most_common()]
        hotspots.append(item)
    return sorted(hotspots, key=lambda x: (-x["blocking_count"], -x["weak_count"], x["node_id"]))[:8]


def graph_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    thin_nodes = [
        dict(row) for row in conn.execute(
            """
            select n.id as node_id, n.name, count(q.id) as practice_count
            from graph_nodes n
            left join question_items q on q.node_id = n.id
              and q.source_type = 'graph_generated'
              and q.item_version = ?
            group by n.id
            having practice_count < ?
            order by n.sequence_band, n.id
            """,
            (question_bank.QUESTION_BANK_VERSION, question_bank.QUESTIONS_PER_GRAPH_NODE),
        ).fetchall()
    ]
    node_issues = _node_ref_issues(conn)
    question_issues = _question_ref_issues(conn)
    quality_audit = _question_quality_audit(conn)
    hotspots = _hotspots(conn)
    diagnostic_covered_nodes = _scalar(conn, "select count(distinct node_id) from question_items where source_type = 'diagnostic'")
    status = "ready"
    if node_issues or question_issues or thin_nodes or quality_audit["issues"]:
        status = "needs_repair"
    elif any(item["blocking_count"] or item["weak_count"] >= 2 for item in hotspots):
        status = "watch"

    recommendations: list[dict[str, Any]] = []
    if node_issues or question_issues:
        recommendations.append({
            "type": "repair_references",
            "priority": "P0",
            "text": "图谱或题目存在断裂引用，先修引用再使用相关节点。",
            "evidence_count": len(node_issues) + len(question_issues),
        })
    if thin_nodes:
        recommendations.append({
            "type": "fill_practice_gap",
            "priority": "P1",
            "text": "存在当前活跃版本题量低于每节点20题覆盖线的节点，需要补齐独立题型槽位。",
            "evidence_count": len(thin_nodes),
        })
    if quality_audit["issues"]:
        recommendations.append({
            "type": "repair_question_quality_gate",
            "priority": "P0",
            "text": "存在最新版图谱题/自进化题未通过命题-审题质量门，不能进入主动调度。",
            "evidence_count": len(quality_audit["issues"]),
        })
    for item in hotspots[:3]:
        recommendations.append({
            "type": "review_node_grain_or_prerequisite",
            "priority": "P1" if item["blocking_count"] else "P2",
            "node_id": item["node_id"],
            "text": "真实已处理弱证据集中，图谱 Agent 应复查节点粒度、前置链或错因标签是否过粗。",
            "evidence_attempt_ids": item["evidence_attempt_ids"],
            "dominant_error_tags": item["dominant_error_tags"],
        })
    if not recommendations:
        recommendations.append({
            "type": "graph_ready_for_session",
            "priority": "P3",
            "text": "当前图谱引用完整，题库覆盖达到本地学习最低线；继续用真实证据观察节点粒度。",
        })

    return {
        "agent_key": "graph_agent",
        "display_name": "图谱 Agent",
        "status": status,
        "summary": {
            "graph_nodes": _scalar(conn, "select count(*) from graph_nodes"),
            "graph_edges": _scalar(conn, "select count(*) from graph_edges"),
            "diagnostic_covered_nodes": diagnostic_covered_nodes,
            "thin_practice_nodes": len(thin_nodes),
            "node_reference_issues": len(node_issues),
            "question_reference_issues": len(question_issues),
            "evidence_hotspots": len(hotspots),
        },
        "thin_practice_nodes": thin_nodes,
        "node_reference_issues": node_issues[:20],
        "question_reference_issues": question_issues[:20],
        "question_quality_audit": quality_audit,
        "evidence_hotspots": hotspots,
        "recommendations": recommendations,
    }


def question_production_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    quality_audit = _question_quality_audit(conn)
    profiles = {}
    for key in (
        question_bank.QUESTION_COORDINATOR_AGENT_KEY,
        question_bank.QUESTION_DESIGNER_AGENT_KEY,
        question_bank.QUESTION_REVIEWER_AGENT_KEY,
    ):
        try:
            profile = db.get_agent_profile(conn, key)
        except KeyError:
            profiles[key] = {"missing": True}
            continue
        profiles[key] = {
            "display_name": profile["display_name"],
            "revision": profile["revision"],
            "profile": profile["profile"],
        }

    status = "ready" if not quality_audit["issues"] else "needs_repair"
    recommendations = []
    if quality_audit["issues"]:
        recommendations.append({
            "type": "block_unreviewed_or_rejected_items",
            "priority": "P0",
            "text": "调度前必须替换或修复未过审题；不能用数量覆盖质量问题。",
            "count": len(quality_audit["issues"]),
        })
    else:
        recommendations.append({
            "type": "production_gate_ready",
            "priority": "P2",
            "text": "最新版图谱题和自进化题均带命题意图、六升七年龄底线、过程证据要求和审题通过记录。",
        })

    return {
        "agent_key": "question_production_agent",
        "display_name": "题库生产 Agent 组",
        "status": status,
        "profiles": profiles,
        "quality_audit": quality_audit,
        "invariants": [
            "命题 Agent 只产出图谱绑定、面向六升七的诊断题候选。",
            "审题 Agent 拒绝低龄机械题、答案-only题、孩子端元话术和缺少过程证据的题。",
            "调度只使用最新版且审题通过的 graph_generated/evolved 题。",
        ],
        "recommended_actions": recommendations,
    }


def evaluation_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    pending_count = len(db.current_active_attempts(conn, grading_status="pending_review"))
    graded_count = len(db.current_active_attempts(conn, grading_status="graded"))
    unprocessed_graded = len(db.current_usable_attempts(conn, processed_evolution_event_id_is_null=True))
    missing_analysis_count = len(
        db.current_attempts_missing_valid_analysis(conn, processed_evolution_event_id_is_null=True)
    )
    status_counts = db.current_learner_node_status_counts(conn)
    latest_plan, latest_plan_current = _latest_generated_plan_report(conn)
    tasks = latest_plan["tasks"] if latest_plan and latest_plan_current else []

    if pending_count:
        stage = "system_review_needed"
    elif missing_analysis_count:
        stage = "answer_analysis_needed"
    elif unprocessed_graded:
        stage = "ready_to_evolve"
    elif not graded_count:
        stage = "baseline_ready"
    elif status_counts.get("D", 0):
        stage = "blocked_prerequisite_repair"
    elif status_counts.get("C", 0) or status_counts.get("B", 0):
        stage = "remediation_cycle"
    else:
        stage = "continue_core_path"

    actions: list[dict[str, Any]] = []
    if pending_count:
        actions.append({
            "type": "process_pending_evidence",
            "priority": "P0",
            "text": "先由系统 AI 完成待处理提交的批阅；照片-only 或低置信答案未处理前不算掌握证据。",
            "count": pending_count,
        })
    if missing_analysis_count:
        actions.append({
            "type": "complete_answer_analysis",
            "priority": "P0",
            "text": "已评分证据缺少结构化答案分析，不能进入自进化或下一轮计划判断。",
            "count": missing_analysis_count,
        })
    if unprocessed_graded:
        actions.append({
            "type": "run_evolution",
            "priority": "P0",
            "text": "存在未进化的已处理证据，运行进化后再判断下一步。",
            "count": unprocessed_graded,
        })
    if status_counts.get("D", 0):
        actions.append({
            "type": "repair_blocked_prerequisite",
            "priority": "P0",
            "text": "有 D 状态节点，暂停直接推进，沿前置链回补。",
            "count": status_counts["D"],
        })
    if status_counts.get("C", 0):
        actions.append({
            "type": "remediate_weak_nodes",
            "priority": "P1",
            "text": "有 C 状态节点，先做微课、少量变式和复测。",
            "count": status_counts["C"],
        })
    if not actions:
        actions.append({
            "type": "start_or_continue_plan",
            "priority": "P2",
            "text": "没有待处理证据；按今日任务开始，或继续下一条 P0 核心路径。",
            "count": len(tasks),
        })

    return {
        "agent_key": "evaluation_agent",
        "display_name": "评估 Agent",
        "stage": stage,
        "summary": {
            "pending_attempts": pending_count,
            "graded_attempts": graded_count,
            "unprocessed_graded_attempts": unprocessed_graded,
            "missing_analysis_attempts": missing_analysis_count,
            "status_counts": status_counts,
            "latest_plan_id": latest_plan["id"] if latest_plan and latest_plan_current else None,
            "latest_plan_current": latest_plan_current,
            "latest_plan_task_count": len(tasks),
        },
        "invariants": [
            "待处理证据只代表孩子已提交，不代表掌握。",
            "只有系统已批阅且带结构化答案分析的证据能进入 A/B/C/D 与自进化。",
            "D 状态必须来自明确卡住或前置链失败证据。",
        ],
        "recommended_actions": actions,
    }


def answer_analysis_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    pending_count = len(db.current_active_attempts(conn, grading_status="pending_review"))
    graded_attempts = db.current_active_attempts(conn, grading_status="graded")
    graded_count = len(graded_attempts)
    analyzed_count = len([attempt for attempt in graded_attempts if db.is_current_usable_attempt_evidence(conn, attempt)])
    missing_analysis_count = len([
        attempt for attempt in graded_attempts
        if not db.is_valid_answer_analysis(attempt.get("answer_analysis"))
    ])
    recent_attempts = sorted(
        graded_attempts,
        key=lambda attempt: (attempt.get("created_at") or "", attempt["id"]),
        reverse=True,
    )[:12]

    recent_gaps = []
    recent_missing = []
    for attempt in recent_attempts:
        analysis = attempt.get("answer_analysis") if isinstance(attempt.get("answer_analysis"), dict) else {}
        node = conn.execute("select name from graph_nodes where id = ?", (attempt["node_id"],)).fetchone()
        if not db.is_valid_answer_analysis(analysis):
            recent_missing.append({
                "attempt_id": attempt["id"],
                "node_id": attempt["node_id"],
                "node_name": node["name"] if node else attempt["node_id"],
                "result": attempt["result"],
            })
            continue
        gap = str(analysis.get("process_gap") or "").strip()
        if gap:
            recent_gaps.append({
                "attempt_id": attempt["id"],
                "node_id": attempt["node_id"],
                "node_name": node["name"] if node else attempt["node_id"],
                "result": attempt["result"],
                "process_gap": gap[:240],
            })

    if pending_count:
        status = "pending_system_analysis"
    elif graded_count == 0:
        status = "waiting_for_evidence"
    elif missing_analysis_count:
        status = "needs_analysis"
    else:
        status = "ready"

    recommendations: list[dict[str, Any]] = []
    if pending_count:
        recommendations.append({
            "type": "analyze_pending_answers",
            "priority": "P0",
            "text": "存在待处理答案，需由系统 AI 完成最优解、孩子解法、差异和下一步提示分析。",
            "count": pending_count,
        })
    if missing_analysis_count:
        recommendations.append({
            "type": "complete_structured_answer_analysis",
            "priority": "P1",
            "text": "部分已处理证据缺结构化答案分析；后续方向讨论不能只看分数和一句评语。",
            "count": missing_analysis_count,
        })
    if graded_count == 0 and not pending_count:
        recommendations.append({
            "type": "wait_for_child_submission",
            "priority": "P3",
            "text": "暂无已处理答案；孩子提交并完成系统 AI 处理后再生成答案分析。",
            "count": 0,
        })
    if not recommendations:
        recommendations.append({
            "type": "answer_analysis_ready",
            "priority": "P2",
            "text": "已处理证据带有结构化答案分析，可用于内部评估、自进化和下一轮计划。",
            "count": analyzed_count,
        })

    return {
        "agent_key": "answer_analysis_agent",
        "display_name": "答案分析 Agent",
        "status": status,
        "summary": {
            "pending_attempts": pending_count,
            "graded_attempts": graded_count,
            "analyzed_attempts": analyzed_count,
            "missing_analysis_attempts": missing_analysis_count,
            "recent_process_gaps": len(recent_gaps),
        },
        "invariants": [
            "参考答案只是 rubric 上下文，不能做字符串匹配。",
            "最终答案正确但模型、步骤、单位、检验证据不足时不能判为完全掌握。",
            "答案分析必须区分最优解、孩子解法、可行替代解法和真实思路缺口。",
        ],
        "recent_process_gaps": recent_gaps,
        "recent_missing_analysis": recent_missing,
        "recommended_actions": recommendations,
    }


def session_closure_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        select *
        from learning_sessions
        where mode = 'child_learning_group'
        order by created_at desc
        limit 1
        """
    ).fetchone()
    if not row:
        return {
            "agent_key": "session_closure_agent",
            "display_name": "学习闭环 Agent",
            "status": "waiting_for_session",
            "summary": {
                "expected": 0,
                "submitted": 0,
                "graded": 0,
                "pending": 0,
                "analyzed": 0,
            },
            "recommended_actions": [{
                "type": "start_learning_session",
                "priority": "P2",
                "text": "等待孩子开始一组学习任务。",
                "count": 0,
            }],
        }

    session = db.get_learning_session(conn, row["id"])
    summary = db.session_completion_summary(conn, session["id"])
    if summary["missing_question_ids"]:
        status = "collecting_answers"
        action = {
            "type": "continue_child_session",
            "priority": "P1",
            "text": "本组题还没有交齐，继续让孩子在页面完成剩余题目。",
            "count": len(summary["missing_question_ids"]),
        }
    elif summary["pending_attempt_ids"]:
        status = "waiting_ai_review"
        action = {
            "type": "review_pending_attempts",
            "priority": "P0",
            "text": "本组已交齐，但仍有答案等待系统 AI 批阅。",
            "count": len(summary["pending_attempt_ids"]),
        }
    elif summary["missing_analysis_attempt_ids"]:
        status = "waiting_answer_analysis"
        action = {
            "type": "complete_answer_analysis",
            "priority": "P0",
            "text": "本组已评分，但缺结构化答案分析，不能进入自进化。",
            "count": len(summary["missing_analysis_attempt_ids"]),
        }
    elif session["closure_status"] in {"planned", "closed"}:
        status = "closed"
        action = {
            "type": "next_plan_ready",
            "priority": "P2",
            "text": "本组已完成内部批阅、错因分析、自进化和下一轮计划生成。",
            "count": summary["analyzed"],
        }
    else:
        status = "ready_to_close"
        action = {
            "type": "close_learning_session",
            "priority": "P0",
            "text": "本组证据已具备，可以触发内部 agent 闭环。",
            "count": summary["analyzed"],
        }

    return {
        "agent_key": "session_closure_agent",
        "display_name": "学习闭环 Agent",
        "status": status,
        "session": session,
        "summary": summary,
        "invariants": [
            "孩子完成整组题后才触发闭环，不在每题后打断。",
            "待系统 AI 批阅或缺答案分析时不进化、不生成掌握结论。",
            "闭环输出必须包含批阅、答案分析、错因归因、自进化结果和下一轮计划。",
        ],
        "recommended_actions": [action],
    }


def session_orchestrator_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    report = session_closure_agent_report(conn)
    return {
        **report,
        "agent_key": "session_orchestrator_agent",
        "display_name": "会话编排 Agent",
        "authority": "authoritative_state_machine",
        "invariants": [
            "控制一整轮状态机，决定下一步是讲、练、回退还是拔高。",
            "不直接出题、不直接判分。",
            "只有整组证据交齐、已批阅且有结构化答案分析后，才进入 session close。",
            "重复 close 返回既有结果，不重复写入 close audit。",
        ],
    }


def question_designer_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    quality_audit = _question_quality_audit(conn)
    profile = db.get_agent_profile(conn, "question_designer_agent")
    return {
        "agent_key": "question_designer_agent",
        "display_name": "命题 Agent",
        "status": "ready" if not quality_audit["issues"] else "blocked_by_review_gate",
        "profile": {
            "revision": profile["revision"],
            "profile": profile["profile"],
        },
        "summary": {
            "active_approved_questions": quality_audit["active_count"],
            "legacy_questions": quality_audit["legacy_count"],
            "archived_questions": quality_audit["archived_count"],
            "quality_issues": len(quality_audit["issues"]),
        },
        "invariants": [
            "按节点、错因、目标证据生成题。",
            "不出低龄机械题。",
            "生成的是候选题；审题 Agent 通过后才可进入主动调度。",
        ],
        "recommended_actions": [{
            "type": "continue_graph_bound_generation" if not quality_audit["issues"] else "repair_rejected_candidates",
            "priority": "P2" if not quality_audit["issues"] else "P0",
            "text": "继续根据真实错因补候选题。" if not quality_audit["issues"] else "先修复未通过审题门的候选题。",
            "count": quality_audit["active_count"] if not quality_audit["issues"] else len(quality_audit["issues"]),
        }],
    }


def question_reviewer_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    quality_audit = _question_quality_audit(conn)
    review_counts = {
        row["review_status"]: row["count"]
        for row in conn.execute(
            """
            select review_status, count(*) as count
            from question_review_records
            group by review_status
            order by review_status
            """
        ).fetchall()
    }
    active_review_records = _scalar(
        conn,
        """
        select count(*)
        from question_review_records r
        join question_items q on q.id = r.question_id
        where r.active_eligible = 1
          and (
            (q.source_type = 'graph_generated' and q.item_version = ?)
            or (
              q.source_type = 'evolved'
              and q.item_version = ?
              and coalesce(json_extract(q.source_json, '$.evidence_status'), 'active') = 'active'
              and coalesce(json_extract(q.raw_json, '$.source.evidence_status'), 'active') = 'active'
            )
          )
        """,
        (question_bank.QUESTION_BANK_VERSION, question_bank.EVOLVED_ITEM_VERSION),
    )
    return {
        "agent_key": "question_reviewer_agent",
        "display_name": "审题 Agent",
        "status": "ready" if not quality_audit["issues"] else "needs_repair",
        "summary": {
            "review_records": sum(review_counts.values()),
            "active_eligible_records": active_review_records,
            "review_counts": review_counts,
            "quality_issues": len(quality_audit["issues"]),
        },
        "quality_audit": quality_audit,
        "invariants": [
            "拦截低价值题、无法区分掌握状态的题、无效书写负担题。",
            "不追求题量。",
            "调度前必须重新计算质量门，不能相信候选题自带的 approved 元数据。",
        ],
        "recommended_actions": [{
            "type": "review_gate_ready" if not quality_audit["issues"] else "block_or_repair_unapproved_items",
            "priority": "P2" if not quality_audit["issues"] else "P0",
            "text": "当前最新版题库审题门可用。" if not quality_audit["issues"] else "存在题目不满足审题门，不能主动调度。",
            "count": active_review_records if not quality_audit["issues"] else len(quality_audit["issues"]),
        }],
    }


def teaching_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    analyzed_count = len(db.current_usable_attempts(conn))
    child_message_runs = _scalar(
        conn,
        "select count(*) from agent_runs where agent_key = 'answer_analysis_agent'",
    )
    return {
        "agent_key": "teaching_agent",
        "display_name": "讲解 Agent",
        "status": "ready",
        "summary": {
            "analyzed_attempts_available": analyzed_count,
            "answer_analysis_runs": child_message_runs,
        },
        "invariants": [
            "给孩子生成针对性讲解和下一题前提示。",
            "不输出后台分析。",
            "孩子可见内容只允许 child-safe 字段，不能包含 agent、Codex、图谱、节点、审计或家长流程。",
        ],
        "recommended_actions": [{
            "type": "use_child_safe_feedback",
            "priority": "P2",
            "text": "讲解只从已验证的答案分析和图谱本质中生成，不把后台分析原样给孩子。",
            "count": analyzed_count,
        }],
    }


def planner_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    latest_plan, latest_plan_current = _latest_generated_plan_report(conn)
    tasks = latest_plan["tasks"] if latest_plan and latest_plan_current else []
    task_types = Counter(task.get("task_type", "unknown") for task in tasks)
    status = "ready" if latest_plan_current else ("needs_regeneration" if latest_plan else "waiting_for_plan")
    return {
        "agent_key": "planner_agent",
        "display_name": "规划 Agent",
        "status": status,
        "summary": {
            "latest_plan_id": latest_plan["id"] if latest_plan and latest_plan_current else None,
            "latest_plan_current": latest_plan_current,
            "latest_plan_task_count": len(tasks),
            "task_types": dict(task_types),
        },
        "invariants": [
            "决定巩固题、回退题、拔高题和下一轮学习点。",
            "不机械按日历排课。",
            "D 先回退前置，C 先查前置再修复，B 做复测；无弱点时再走核心路径。",
        ],
        "recommended_actions": [{
            "type": "plan_ready" if latest_plan_current else "generate_plan",
            "priority": "P2",
            "text": "下一轮计划已根据当前证据生成。" if latest_plan_current else "暂无当前有效计划，需重新生成学习任务组。",
            "count": len(tasks),
        }],
    }


def self_evolution_agent_report(conn: sqlite3.Connection) -> dict[str, Any]:
    events = evolution.recent_events(conn, 12)
    audit_count = _scalar(conn, "select count(*) from evolution_audits")
    latest_audit = conn.execute(
        "select * from evolution_audits order by created_at desc, rowid desc limit 1"
    ).fetchone()
    return {
        "agent_key": "self_evolution_agent",
        "display_name": "自进化 Agent",
        "status": "ready",
        "summary": {
            "recent_events": len(events),
            "evolution_audits": audit_count,
            "latest_audit_id": latest_audit["id"] if latest_audit else None,
        },
        "recent_events": events,
        "invariants": [
            "根据真实证据改题型规则、错因规则、agent profile。",
            "不为了测试而假进化。",
            "只有 graded + active + valid answer_analysis 的证据能触发状态、题型或 profile 改动。",
        ],
        "recommended_actions": [{
            "type": "wait_for_real_evidence" if not events else "inspect_recent_evolution",
            "priority": "P3" if not events else "P2",
            "text": "等待真实已分析证据。" if not events else "已有自进化事件，可按 audit 追溯证据链。",
            "count": audit_count,
        }],
    }


def build_agent_reports(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {
        "graph_agent": graph_agent_report(conn),
        "session_orchestrator_agent": session_orchestrator_agent_report(conn),
        "question_designer_agent": question_designer_agent_report(conn),
        "question_reviewer_agent": question_reviewer_agent_report(conn),
        "teaching_agent": teaching_agent_report(conn),
        "planner_agent": planner_agent_report(conn),
        "self_evolution_agent": self_evolution_agent_report(conn),
        "evaluation_agent": evaluation_agent_report(conn),
        "answer_analysis_agent": answer_analysis_agent_report(conn),
        "question_production_agent": question_production_agent_report(conn),
        "session_closure_agent": session_closure_agent_report(conn),
    }
