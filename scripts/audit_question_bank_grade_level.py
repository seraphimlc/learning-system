#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, planner, question_bank

DEFAULT_DB_PATH = PROJECT_ROOT / "data/local_learning_system.sqlite"
DEFAULT_GRAPH_PATH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"


GENERIC_PROMPT_PARTS = (
    "先写出本题用到的关键规则，再完成：",
    "先判断这题真正考的是什么，再完成：",
    "把下面题目当成一次错因辨析，先找最容易混淆的概念，再完成：",
    "请用“错在哪里、为什么错、怎样改”三步完成：",
    "换一种相近情境来做，先写模型或关系，再完成：",
    "不要急着套模板，先判断结构是否相同，再完成：",
    "请从结论或条件反推关键关系，再完成：",
    "先列出解题必须确认的条件，再完成：",
    "把题意先换成另一种表示方式，再完成：",
    "这次重点不是快算，而是解释清楚。请完成：",
    "做完必须检查。请先想一种检验方法，再完成：",
    "先用估算或模型选择判断答案大致范围，再完成：",
    "先写出这题依赖的前一个基础规则，再完成：",
    "在不增加机械计算量的前提下做一个拔高判断：",
    "请比较两种可能做法的适用条件，再完成：",
    "先想一个边界情况或反例，再完成：",
    "先检查符号、单位、括号或维度，再完成：",
    "先预测自己最可能犯的一个错，再完成：",
    "这题先选择模型，不要直接列式。请完成：",
    "请把关系、步骤和结论说完整，再完成：",
    "先判断考点，再作答：",
    "最后用检验、错因或模型说明关键一步为什么成立。",
    "最后用一句话说明为什么这个规则适用。",
    "请说明只看最终答案会漏掉什么。",
    "如果有人只背公式，请指出他最可能错在哪一步。",
    "做完后把最容易错的一步圈出来。",
    "把你认为最危险的一步圈出来，并写一个检查办法。",
    "说明这道变式和原规则相比，改变的是数字还是结构。",
    "再改一个数字，说明哪条规则不变。",
    "再改一个条件，说明方法中哪一部分保持不变。",
    "用反向检验说明你的关系没有写反。",
    "指出如果少看一个条件，答案可能怎样偏掉。",
    "说明这种表示为什么能帮助你避免读题错误。",
    "写一句给低年级同学也能听懂的理由。",
    "最后写出你用的是代入、估算、反例还是单位检查。",
    "说明估算怎样帮你发现不合理答案。",
    "如果这里卡住，请写清楚是读题、概念、符号还是步骤卡住。",
    "说明这题比标准题多了哪一个思考点。",
    "写出你选择的方法，并说明另一种方法的风险。",
    "判断这个规则是不是在所有类似情况都成立。",
    "写出最容易因为符号或单位丢分的地方。",
    "完成后按你预测的错法检查一遍。",
    "说明你排除了哪一种看起来相似但不适用的方法。",
    "最后指出只留下一个数或式子错在哪里，并写一句完整答句。",
)


def normalize_text(value: str) -> str:
    text = value
    for part in GENERIC_PROMPT_PARTS:
        text = text.replace(part, " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[，。；：、,.!?？!“”\"'`]+", "", text)
    return text.strip()


def core_signature(item: dict[str, Any]) -> str:
    signature = question_bank.canonical_core_signature(item)
    if signature:
        return signature
    payload = {
        "core_prompt": normalize_text(str(item.get("prompt") or "")),
        "expected_answer": normalize_text(str(item.get("expected_answer") or "")),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16]


def problem_family_signature(item: dict[str, Any]) -> str:
    problem_family_id = str(item.get("problem_family_id") or "")
    if problem_family_id.startswith("PF-"):
        return problem_family_id
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    source_family_id = str(source.get("problem_family_id") or "")
    if source_family_id.startswith("PF-"):
        return source_family_id
    payload = {
        "node_id": item.get("node_id", ""),
        "question_type": item.get("question_type", ""),
        "core_prompt": normalize_text(str(item.get("prompt") or "")),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16]


def node_alignment(item: dict[str, Any]) -> dict[str, Any]:
    alignment = item.get("node_alignment")
    if isinstance(alignment, dict):
        return alignment
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    alignment = source.get("node_alignment")
    return alignment if isinstance(alignment, dict) else {}


def load_items() -> list[dict[str, Any]]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        db.init_schema(conn)
        db.seed_from_assets(conn, PROJECT_ROOT)
        rows = conn.execute(
            """
            select *
            from question_items
            where source_type = 'graph_generated'
              and item_version = ?
            order by node_id, id
            """,
            (question_bank.QUESTION_BANK_VERSION,),
        ).fetchall()
        return [db.row_to_question(row) for row in rows]
    finally:
        conn.close()


def audit_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prompt_to_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    picture_stem_nodes: dict[tuple[str, str], set[str]] = defaultdict(set)
    issues: list[dict[str, Any]] = []
    for item in items:
        by_node[item["node_id"]].append(item)
        prompt_to_items[normalize_text(str(item.get("prompt") or ""))].append(item)
        for label in question_bank.picture_level_challenge_labels(item):
            picture_stem_nodes[(label, question_bank.canonical_core_signature(item))].add(str(item.get("node_id") or ""))
        quality = question_bank.review_item_quality_for_active_use(item)
        if quality["review_status"] != "approved":
            issues.append({
                "severity": "P0",
                "type": "quality_gate_rejects_active_item",
                "node_id": item["node_id"],
                "question_id": item["id"],
                "detail": quality["rejection_reasons"],
            })
        if not question_bank.is_item_approved_for_active_use(item):
            issues.append({
                "severity": "P0",
                "type": "active_use_not_approved",
                "node_id": item["node_id"],
                "question_id": item["id"],
                "detail": "Active graph-generated item is not approved for active use.",
            })
        if not str(item.get("problem_family_id") or "").startswith("PF-"):
            issues.append({
                "severity": "P0",
                "type": "missing_problem_family_id",
                "node_id": item["node_id"],
                "question_id": item["id"],
                "detail": "Active item lacks explicit problem_family_id.",
            })
        if not str(item.get("core_stem_id") or "").startswith("CS-"):
            issues.append({
                "severity": "P0",
                "type": "missing_core_stem_id",
                "node_id": item["node_id"],
                "question_id": item["id"],
                "detail": "Active item lacks explicit core_stem_id.",
            })
        alignment = node_alignment(item)
        if alignment.get("primary_node_id") != item.get("node_id") or not str(alignment.get("reason") or "").strip():
            issues.append({
                "severity": "P0",
                "type": "missing_or_mismatched_node_alignment",
                "node_id": item["node_id"],
                "question_id": item["id"],
                "detail": "Active item lacks traceable node_alignment.reason for its primary graph node.",
            })

    for prompt_signature, prompt_items in sorted(prompt_to_items.items()):
        node_ids = sorted({item["node_id"] for item in prompt_items})
        if len(node_ids) <= 1:
            continue
        sample_items = prompt_items[:6]
        issues.append({
            "severity": "P1",
            "type": "cross_node_exact_prompt_reuse",
            "node_id": ",".join(node_ids[:5]),
            "detail": f"{len(prompt_items)} items share the same child-facing prompt across {len(node_ids)} nodes",
            "samples": [
                {
                    "count": 1,
                    "question_id": item["id"],
                    "kind": item.get("kind"),
                    "prompt": item.get("prompt"),
                }
                for item in sample_items
            ],
        })

    node_summaries = []
    for node_id, node_items in sorted(by_node.items()):
        signature_counts = Counter(core_signature(item) for item in node_items)
        family_counts = Counter(problem_family_signature(item) for item in node_items)
        prompt_core_counts = Counter(normalize_text(str(item.get("prompt") or "")) for item in node_items)
        picture_items = [item for item in node_items if question_bank.picture_level_challenge_labels(item)]
        picture_label_counts = Counter(
            label
            for item in picture_items
            for label in question_bank.picture_level_challenge_labels(item)
        )
        node_local_mainline_items = [
            item for item in node_items
            if question_bank.is_node_local_mainline_item(item)
        ]
        kind_count = len({item.get("kind") for item in node_items})
        question_type_count = len({item.get("question_type") for item in node_items})
        tag_tuple_count = len({tuple(item.get("target_error_tags") or []) for item in node_items})
        max_core_repeat = max(signature_counts.values() or [0])
        max_family_repeat = max(family_counts.values() or [0])
        unique_core_count = len(signature_counts)
        unique_family_count = len(family_counts)
        node_summary = {
            "node_id": node_id,
            "items": len(node_items),
            "kinds": kind_count,
            "question_types": question_type_count,
            "tag_patterns": tag_tuple_count,
            "problem_families": unique_family_count,
            "max_problem_family_repeat": max_family_repeat,
            "unique_core_signatures": unique_core_count,
            "max_core_repeat": max_core_repeat,
            "node_local_mainline_items": len(node_local_mainline_items),
            "picture_level_items": len(picture_items),
            "top_core_prompt": next(iter(prompt_core_counts.most_common(1)), ("", 0))[0],
        }
        node_summaries.append(node_summary)

        if len(node_items) != question_bank.QUESTIONS_PER_GRAPH_NODE:
            issues.append({
                "severity": "P0",
                "type": "node_question_count_not_20",
                "node_id": node_id,
                "detail": f"{len(node_items)} items",
            })
        if len(node_local_mainline_items) < question_bank.MIN_NODE_LOCAL_MAINLINE_ITEMS_PER_NODE:
            issues.append({
                "severity": "P1",
                "type": "too_few_node_local_mainline_items",
                "node_id": node_id,
                "detail": f"{len(node_local_mainline_items)} mainline items; minimum {question_bank.MIN_NODE_LOCAL_MAINLINE_ITEMS_PER_NODE}",
            })
        if len(picture_items) > question_bank.MAX_PICTURE_LEVEL_CHALLENGES_PER_NODE:
            issues.append({
                "severity": "P1",
                "type": "too_many_picture_level_extensions_for_node",
                "node_id": node_id,
                "detail": f"{len(picture_items)} picture-level items; cap {question_bank.MAX_PICTURE_LEVEL_CHALLENGES_PER_NODE}",
            })
        if max(picture_label_counts.values() or [0]) > question_bank.MAX_SAME_PICTURE_CHALLENGE_LABEL_PER_NODE:
            label, count = picture_label_counts.most_common(1)[0]
            issues.append({
                "severity": "P1",
                "type": "one_picture_level_label_repeated_too_often",
                "node_id": node_id,
                "detail": f"{label} repeats {count}; cap {question_bank.MAX_SAME_PICTURE_CHALLENGE_LABEL_PER_NODE}",
            })
        if kind_count < question_bank.MIN_DISTINCT_QUESTION_KINDS_PER_NODE:
            issues.append({
                "severity": "P1",
                "type": "insufficient_kind_variety",
                "node_id": node_id,
                "detail": f"{kind_count} kinds",
            })
        if unique_family_count < question_bank.MIN_PROBLEM_FAMILIES_PER_NODE:
            repeated_examples = []
            for signature, count in family_counts.most_common(3):
                sample = next(item for item in node_items if problem_family_signature(item) == signature)
                repeated_examples.append({
                    "count": count,
                    "question_id": sample["id"],
                    "kind": sample.get("kind"),
                    "problem_family_id": signature,
                    "prompt": sample.get("prompt"),
                })
            issues.append({
                "severity": "P1",
                "type": "too_few_problem_families_for_20_items",
                "node_id": node_id,
                "detail": f"{unique_family_count} problem families / {len(node_items)} items",
                "samples": repeated_examples,
            })
        if max_family_repeat > question_bank.MAX_PROBLEM_FAMILY_REPEAT_PER_NODE:
            signature, count = family_counts.most_common(1)[0]
            sample = next(item for item in node_items if problem_family_signature(item) == signature)
            issues.append({
                "severity": "P1",
                "type": "one_problem_family_repeated_too_often",
                "node_id": node_id,
                "detail": f"{signature} repeats {count}; cap {question_bank.MAX_PROBLEM_FAMILY_REPEAT_PER_NODE}",
                "samples": [{
                    "count": count,
                    "question_id": sample["id"],
                    "kind": sample.get("kind"),
                    "problem_family_id": signature,
                    "prompt": sample.get("prompt"),
                }],
            })
        if unique_core_count < question_bank.MIN_CANONICAL_CORE_STEMS_PER_NODE:
            repeated_examples = []
            for signature, count in signature_counts.most_common(3):
                sample = next(item for item in node_items if core_signature(item) == signature)
                repeated_examples.append({
                    "count": count,
                    "question_id": sample["id"],
                    "kind": sample.get("kind"),
                    "prompt": sample.get("prompt"),
                })
            issues.append({
                "severity": "P1",
                "type": "twenty_items_reuse_too_few_core_questions",
                "node_id": node_id,
                "detail": f"{unique_core_count} unique core signatures / {len(node_items)} items",
                "samples": repeated_examples,
            })
        if max_core_repeat > question_bank.MAX_CORE_STEM_REPEAT_PER_NODE:
            issues.append({
                "severity": "P1",
                "type": "one_core_question_repeated_too_often",
                "node_id": node_id,
                "detail": f"max repeat {max_core_repeat}; cap {question_bank.MAX_CORE_STEM_REPEAT_PER_NODE}",
            })

    for (label, signature), node_ids in sorted(picture_stem_nodes.items()):
        if len(node_ids) > question_bank.MAX_SAME_PICTURE_CHALLENGE_STEM_NODES:
            issues.append({
                "severity": "P1",
                "type": "picture_level_stem_reused_across_too_many_nodes",
                "node_id": ",".join(sorted(node_ids)[:5]),
                "detail": f"{label}/{signature} appears on {len(node_ids)} nodes; cap {question_bank.MAX_SAME_PICTURE_CHALLENGE_STEM_NODES}",
            })

    return {
        "item_count": len(items),
        "node_count": len(by_node),
        "node_summaries": node_summaries,
        "issues": issues,
    }


def audit_active_round() -> dict[str, Any]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        db.init_schema(conn)
        db.seed_from_assets(conn, PROJECT_ROOT)
        plan = planner.latest_or_create_plan(conn)
        tasks = plan.get("tasks", [])
        task_summaries = []
        challenge_count = 0
        node_local_mainline_count = 0
        for task in tasks:
            question = task.get("question") if isinstance(task.get("question"), dict) else {}
            labels = question_bank.picture_level_challenge_labels(question)
            if labels:
                challenge_count += 1
            if question_bank.is_node_local_mainline_item(question):
                node_local_mainline_count += 1
            task_summaries.append({
                "position": len(task_summaries) + 1,
                "question_id": task.get("question_id"),
                "node_id": task.get("node_id"),
                "kind": question.get("kind"),
                "evidence_role": question_bank.question_evidence_role(question),
                "labels": labels,
                "prompt": question.get("prompt", ""),
            })
        issues = []
        if len(tasks) != planner.LEARNING_ROUND_TASK_COUNT:
            issues.append({
                "severity": "P0",
                "type": "active_round_task_count_not_10",
                "node_id": "-",
                "detail": f"{len(tasks)} tasks",
            })
        if challenge_count < question_bank.MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND:
            issues.append({
                "severity": "P1",
                "type": "active_round_picture_level_challenge_coverage_too_low",
                "node_id": "-",
                "detail": f"{challenge_count}/{len(tasks)} picture-level challenge tasks; minimum {question_bank.MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND}",
            })
        if challenge_count > question_bank.MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND:
            issues.append({
                "severity": "P1",
                "type": "active_round_picture_level_challenge_over_cap",
                "node_id": "-",
                "detail": f"{challenge_count}/{len(tasks)} picture-level challenge tasks; cap {question_bank.MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND}",
            })
        if node_local_mainline_count < question_bank.MIN_NODE_LOCAL_MAINLINE_TASKS_PER_ROUND:
            issues.append({
                "severity": "P1",
                "type": "active_round_node_local_mainline_too_low",
                "node_id": "-",
                "detail": f"{node_local_mainline_count}/{len(tasks)} node-local mainline tasks; minimum {question_bank.MIN_NODE_LOCAL_MAINLINE_TASKS_PER_ROUND}",
            })
        return {
            "lane": "legacy_10_task_round",
            "plan_id": plan.get("id"),
            "task_count": len(tasks),
            "picture_level_challenge_count": challenge_count,
            "node_local_mainline_count": node_local_mainline_count,
            "minimum_required": question_bank.MIN_PICTURE_LEVEL_CHALLENGES_PER_ROUND,
            "maximum_allowed": question_bank.MAX_PICTURE_LEVEL_CHALLENGES_PER_ROUND,
            "node_local_mainline_minimum": question_bank.MIN_NODE_LOCAL_MAINLINE_TASKS_PER_ROUND,
            "tasks": task_summaries,
            "issues": issues,
        }
    finally:
        conn.close()


def audit_external_asset(manifest: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    report = question_bank.validate_external_question_bank_v12(manifest, graph)
    report["lane"] = "external_v12_asset"
    for node_entry in manifest.get("nodes") or []:
        if not isinstance(node_entry, dict):
            continue
        node_id = str(node_entry.get("node_id") or "")
        items = [item for item in node_entry.get("items") or [] if isinstance(item, dict)]
        declared_core_counts = Counter(str(item.get("math_core_signature") or item.get("core_stem_id") or item.get("id") or "") for item in items)
        node_artifact = node_entry.get("node_review_artifact") if isinstance(node_entry.get("node_review_artifact"), dict) else {}
        for summary in report.get("node_summaries") or []:
            if summary.get("node_id") == node_id:
                summary["declared_core_signatures"] = len(declared_core_counts)
                summary["declared_max_core_repeat"] = max(declared_core_counts.values() or [0])
                summary["declared_core_evidence_authority"] = "declared_only_not_semantic_duplicate_proof"
                summary["node_set_semantic_evidence_version"] = node_artifact.get("semantic_evidence_version", "")
                summary["node_ux_verdict"] = node_artifact.get("node_ux_verdict", "")
                summary["instruction_voice_family_count"] = len(node_artifact.get("instruction_voice_distribution") or [])
                summary["model_semantic_duplicate_group_count"] = len(node_artifact.get("duplicate_groups") or [])
                summary.pop("unique_core_signatures", None)
        for group in node_artifact.get("duplicate_groups") or []:
            slots = group.get("slots") if isinstance(group, dict) else []
            if slots:
                report["issues"].append({
                    "severity": "P1",
                    "type": "v12_node_set_reviewer_duplicate_group",
                    "node_id": node_id,
                    "detail": str(group.get("reason") or "node-set reviewer reported duplicate group"),
                    "slots": slots,
                })
    if not manifest.get("nodes"):
        report["issues"].append({
            "severity": "P1",
            "type": "v12_external_asset_empty",
            "node_id": "-",
            "detail": "external v12 asset contains no generated/reviewed nodes yet",
        })
    report["legacy_active_round"] = {
        "lane": "legacy_10_task_round",
        "status": "not_v5_acceptance_gate",
        "reason": "v5 uses one-current-step planner candidate packets; legacy 10-task round is reported only for historical compatibility.",
    }
    return report


def audit_live_lineage(db_path: Path | None) -> dict[str, Any]:
    if db_path is None or not db_path.exists():
        return {
            "db_path": str(db_path) if db_path else "",
            "checked": False,
            "issue_count": 0,
            "issues": [],
            "audit": {},
        }
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        audit = db.lineage_integrity_audit(conn)
        issues = []
        mapped_issue_count = 0
        if audit.get("active_attempts_on_superseded_bank_questions"):
            mapped_issue_count += len(audit["active_attempts_on_superseded_bank_questions"])
            issues.append({
                "severity": "P0",
                "type": "live_db_active_attempts_on_superseded_bank_questions",
                "node_id": "-",
                "detail": f"{len(audit['active_attempts_on_superseded_bank_questions'])} stale active attempts",
            })
        if audit.get("superseded_bank_review_records"):
            mapped_issue_count += len(audit["superseded_bank_review_records"])
            issues.append({
                "severity": "P1",
                "type": "live_db_superseded_bank_review_records_active",
                "node_id": "-",
                "detail": f"{len(audit['superseded_bank_review_records'])} stale review records",
            })
        if audit.get("learner_status_invalid_refs"):
            mapped_issue_count += len(audit["learner_status_invalid_refs"])
            issues.append({
                "severity": "P0",
                "type": "live_db_learner_status_invalid_refs",
                "node_id": "-",
                "detail": f"{len(audit['learner_status_invalid_refs'])} learner status rows reference invalid evidence",
            })
        if audit.get("stale_review_records"):
            mapped_issue_count += len(audit["stale_review_records"])
            issues.append({
                "severity": "P1",
                "type": "live_db_invalidated_source_review_records_active",
                "node_id": "-",
                "detail": f"{len(audit['stale_review_records'])} invalidated-source review records remain active",
            })
        if audit.get("active_attempts_on_invalidated_source_questions"):
            mapped_issue_count += len(audit["active_attempts_on_invalidated_source_questions"])
            issues.append({
                "severity": "P0",
                "type": "live_db_active_attempts_on_invalidated_source_questions",
                "node_id": "-",
                "detail": f"{len(audit['active_attempts_on_invalidated_source_questions'])} active attempts on invalidated evolved questions",
            })
        if audit.get("superseded_review_records"):
            mapped_issue_count += len(audit["superseded_review_records"])
            issues.append({
                "severity": "P1",
                "type": "live_db_superseded_duplicate_review_records_active",
                "node_id": "-",
                "detail": f"{len(audit['superseded_review_records'])} superseded active review records",
            })
        if audit.get("invalid_evolved_source_attempts"):
            mapped_issue_count += len(audit["invalid_evolved_source_attempts"])
            issues.append({
                "severity": "P1",
                "type": "live_db_evolved_questions_with_invalid_source_attempts",
                "node_id": "-",
                "detail": f"{len(audit['invalid_evolved_source_attempts'])} evolved questions have missing or unusable source attempts",
            })
        if int(audit.get("issue_count", 0)) > mapped_issue_count:
            issues.append({
                "severity": "P1",
                "type": "live_db_unmapped_lineage_issue_count",
                "node_id": "-",
                "detail": f"lineage_integrity_audit.issue_count={audit.get('issue_count', 0)} but mapped={mapped_issue_count}",
            })
        return {
            "db_path": str(db_path),
            "checked": True,
            "issue_count": int(audit.get("issue_count", 0)),
            "issues": issues,
            "audit": audit,
        }
    finally:
        conn.close()


def write_report(report: dict[str, Any], path: Path) -> None:
    issues = report["issues"]
    severity_counts = Counter(issue["severity"] for issue in issues)
    needs_fix = any(issue["severity"] in {"P0", "P1"} for issue in issues) or int(
        report.get("live_lineage", {}).get("issue_count", 0) or 0
    ) > 0
    worst_nodes = sorted(
        report["node_summaries"],
        key=lambda item: (
            item.get("problem_families", item.get("unique_math_core_count", 0)),
            -item.get("max_problem_family_repeat", 0),
            item.get("unique_core_signatures", item.get("unique_math_core_count", 0)),
            -item.get("max_core_repeat", 0),
            item.get("node_id", ""),
        ),
    )[:12]
    active_round = report.get("active_round", {})
    lines = [
        "# Question Bank Grade-Level Content Audit",
        "",
        f"- Generated: `{db.now_iso()}`",
        f"- Question bank: `{report.get('question_bank_version') or question_bank.QUESTION_BANK_VERSION}`",
        f"- Lane: `{report.get('lane', 'active_seed_lane')}`",
        f"- Items audited: {report.get('item_count', 0)}",
        f"- Nodes audited: {report.get('node_count', 0)}",
        f"- Active round picture-level tasks: {active_round.get('picture_level_challenge_count', 0)}/{active_round.get('task_count', 0)} (min {active_round.get('minimum_required', 0)}, max {active_round.get('maximum_allowed', 0)})",
        f"- Active round node-local mainline tasks: {active_round.get('node_local_mainline_count', 0)}/{active_round.get('task_count', 0)} (min {active_round.get('node_local_mainline_minimum', 0)})",
        f"- Live DB lineage checked: {'yes' if report.get('live_lineage', {}).get('checked') else 'no'}",
        f"- Live DB lineage issues: {report.get('live_lineage', {}).get('issue_count', 0)}",
        f"- Verdict: {'NEEDS_FIX' if needs_fix else 'PASS_WITH_SCOPE'}",
        f"- P0/P1/P2 issues: {severity_counts.get('P0', 0)}/{severity_counts.get('P1', 0)}/{severity_counts.get('P2', 0)}",
        "",
        "## Interpretation",
        "",
        "- This audit checks hard content-regression signals for an incoming grade-7 learner: graph binding, reviewer gate, reasoning demand, low-age mechanical drill rejection, explicit problem-family/core-stem lineage, node-alignment reasons, per-node 20 item count, type variety, and repeated core-question risk.",
        "- It also checks the child-facing active round: 10 tasks, with a controlled picture-level extension range and a node-local mainline evidence floor.",
        "- When a live DB path is available, it also checks evidence lineage: old bank/evolved attempts and review records must not remain active.",
        "- It does not replace expert human review or live-model semantic grading. A PASS here would still be scoped.",
        "- A node fails content regression when 20 items mostly reuse the same mathematical stem/answer and only change wrapper instructions.",
        "",
        "## Weakest Nodes By Core Variety",
        "",
        "| Node | Items | Mainline | Picture | Kinds | Question types | Tag patterns | Problem families | Max family repeat | Canonical core stems | Max core repeat |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in worst_nodes:
        lines.append(
            f"| `{item.get('node_id', '')}` | {item.get('items', item.get('item_count', 0))} | {item.get('node_local_mainline_items', item.get('node_local_mainline_count', 0))} | {item.get('picture_level_items', item.get('controlled_stretch_count', 0))} | "
            f"{item.get('kinds', 0)} | {item.get('question_types', 0)} | "
            f"{item.get('tag_patterns', 0)} | {item.get('problem_families', item.get('unique_math_core_count', 0))} | {item.get('max_problem_family_repeat', 0)} | "
            f"{item.get('unique_core_signatures', item.get('unique_math_core_count', 0))} | {item.get('max_core_repeat', 0)} |"
        )
    lines.extend(["", "## Legacy Active Round Difficulty Gate", ""])
    lines.append("")
    lines.append("This lane is legacy compatibility evidence only. It is not a v5 PASS definition.")
    lines.append("")
    lines.append("| # | Question | Node | Kind | Evidence role | Picture-level labels | Prompt |")
    lines.append("|---:|---|---|---|---|---|---|")
    for task in active_round.get("tasks", []):
        prompt = str(task.get("prompt") or "").replace("\n", " ")
        if len(prompt) > 180:
            prompt = prompt[:177] + "..."
        labels = ", ".join(task.get("labels") or []) or "-"
        lines.append(
            f"| {task['position']} | `{task.get('question_id')}` | `{task.get('node_id')}` | `{task.get('kind')}` | `{task.get('evidence_role')}` | {labels} | {prompt} |"
        )
    lines.extend(["", "## Live DB Lineage Gate", ""])
    live_lineage = report.get("live_lineage", {})
    if not live_lineage.get("checked"):
        lines.append(f"- Not checked. DB path missing: `{live_lineage.get('db_path', '')}`")
    else:
        lines.append(f"- DB path: `{live_lineage.get('db_path')}`")
        lines.append(f"- Issue count: `{live_lineage.get('issue_count', 0)}`")
        audit = live_lineage.get("audit") or {}
        for key in (
            "active_attempts_on_superseded_bank_questions",
            "superseded_bank_review_records",
            "learner_status_invalid_refs",
            "stale_review_records",
            "active_attempts_on_invalidated_source_questions",
            "superseded_review_records",
            "invalid_evolved_source_attempts",
        ):
            values = audit.get(key) or []
            lines.append(f"- `{key}`: {len(values)}")
    lines.extend(["", "## Issues", ""])
    if issues:
        for issue in issues[:80]:
            lines.append(
                f"- [{issue['severity']}] `{issue['type']}` on `{issue.get('node_id', '-')}`: {issue.get('detail', '')}"
            )
            for sample in issue.get("samples", [])[:2]:
                prompt = str(sample.get("prompt") or "").replace("\n", " ")
                if len(prompt) > 220:
                    prompt = prompt[:217] + "..."
                lines.append(
                    f"  sample `{sample.get('question_id')}` x{sample.get('count')}: {prompt}"
                )
        if len(issues) > 80:
            lines.append(f"- ... {len(issues) - 80} more issues omitted from this report.")
    else:
        lines.append("- None")
    lines.extend(["", "## Required Next Action", ""])
    if needs_fix:
        lines.extend([
            "- 命题 Agent 不能只套 20 个题型壳；每个节点需要足够多的 `problem_family_id`、canonical core stem 和 node-local mainline evidence，并按概念、本质、错解、建模、迁移、表达分别产出。",
            "- 审题 Agent 必须执行“核心题干重复度”门禁：重复核心题不得因为外壳不同而通过。",
            "- 下一轮回归要补 live-model answer-analysis 抽样，验证真实孩子式答案是否会被正确区分为会、半会、不会、答案对但思路错。",
        ])
    else:
        lines.extend([
            "- 当前题库已通过核心题干重复度硬门；继续保留该脚本作为题库回归门禁。",
            "- 下一轮仍需补 live-model answer-analysis 抽样，验证真实孩子式答案是否会被正确区分为会、半会、不会、答案对但思路错。",
            "- 仍需人工/教研抽样审阅题干自然度和认知负荷；本报告只能给 `PASS_WITH_SCOPE`。",
        ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit graph-generated question bank grade-level suitability.")
    parser.add_argument("--report", default=str(PROJECT_ROOT / "docs/system/qa/question_bank_grade_level_latest.md"))
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Optional live SQLite DB for lineage audit.")
    parser.add_argument("--external-asset", default="", help="Optional v12 external question-bank asset JSON to audit instead of the active v11 seed lane.")
    parser.add_argument("--allow-needs-fix", action="store_true")
    args = parser.parse_args()

    if args.external_asset:
        manifest = json.loads(Path(args.external_asset).read_text(encoding="utf-8"))
        graph = json.loads(DEFAULT_GRAPH_PATH.read_text(encoding="utf-8"))
        report = audit_external_asset(manifest, graph)
        report["active_round"] = report["legacy_active_round"]
        report["live_lineage"] = {"checked": False, "issue_count": 0, "issues": []}
        report.setdefault("node_summaries", [])
        report.setdefault("item_count", sum(summary.get("item_count", 0) for summary in report.get("node_summaries", [])))
        report.setdefault("node_count", len(report.get("node_summaries", [])))
    else:
        report = audit_items(load_items())
        active_round = audit_active_round()
        live_lineage = audit_live_lineage(Path(args.db) if args.db else None)
        report["active_round"] = active_round
        report["live_lineage"] = live_lineage
        report["issues"].extend(active_round["issues"])
        report["issues"].extend(live_lineage["issues"])
    write_report(report, Path(args.report))
    print(args.report)
    blocking = [issue for issue in report["issues"] if issue["severity"] in {"P0", "P1"}]
    if blocking and not args.allow_needs_fix:
        for issue in blocking[:20]:
            print(f"{issue['severity']} {issue['type']} {issue.get('node_id', '-')}: {issue.get('detail', '')}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
