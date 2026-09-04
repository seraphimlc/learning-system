"""Run the new question-production workflow to a selected stage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_system import db
from learning_system.question_production_orchestrator import create_live_question_production_orchestrator


GRAPH_PATH = ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
STAGES = ("qf_design", "slot_design", "brief_generation", "candidate_generation")


def execute_action(orchestrator, args, *, node: dict | None = None) -> dict:
    """Dispatch one explicit lifecycle action to the production orchestrator."""
    action = args.action
    if action == "start":
        if not args.node or node is None:
            raise ValueError("--node is required for start")
        until = args.until or "qf_design"
        return orchestrator.run_until(
            args.node,
            {"node_id": args.node, "node": node},
            until,
        )

    if action == "rerun":
        if not args.node or node is None:
            raise ValueError("--node is required for rerun")
        if not args.source_run_id:
            raise ValueError("--source-run-id is required for rerun")
        return orchestrator.rerun(
            args.node,
            {"node_id": args.node, "node": node},
            source_run_id=args.source_run_id,
        )

    if action == "revise_structure":
        if not args.node or node is None:
            raise ValueError("--node is required for revise_structure")
        if not args.source_run_id:
            raise ValueError("--source-run-id is required for revise_structure")
        feedback = args.feedback
        if feedback is None:
            feedback = []
            source_input = orchestrator.conn.execute(
                "select input_json from production_runs where id=?",
                (args.source_run_id,),
            ).fetchone()
            if source_input:
                revision_context = json.loads(source_input[0] or "{}").get("revision_context") or {}
                feedback.extend(revision_context.get("feedback") or [])
            rows = orchestrator.conn.execute(
                "select stage_name,logical_key,validation_result_json from production_stages where run_id=? and status='rejected' order by stage_name,logical_key",
                (args.source_run_id,),
            ).fetchall()
            for row in rows:
                validation = json.loads(row["validation_result_json"] or "{}")
                review = validation.get("semantic_review") or {}
                feedback.append({
                    "source_stage": row["stage_name"],
                    "source_key": row["logical_key"],
                    "root_cause_stage": review.get("root_cause_stage"),
                    "issues": review.get("issues") or [],
                    "repair_instructions": review.get("repair_instructions") or [],
                })
        if not feedback:
            raise ValueError("source run has no rejected Reviewer feedback")
        return orchestrator.revise_structure(
            args.node,
            {"node_id": args.node, **node},
            source_run_id=args.source_run_id,
            feedback=feedback,
        )

    if not args.run_id:
        raise ValueError(f"--run-id is required for {action}")
    if action == "revalidate_candidates":
        return orchestrator.requeue_invalid_candidates(args.run_id)
    if action == "promote":
        if not args.question_bank_version or not args.graph_version:
            raise ValueError("--question-bank-version and --graph-version are required for promote")
        return orchestrator.promote(
            run_id=args.run_id,
            question_bank_version=args.question_bank_version,
            graph_version=args.graph_version,
            manifest_id=args.manifest_id,
        )
    if action == "resume":
        return orchestrator.resume(args.run_id, until_stage=args.until)
    if action == "retry":
        return orchestrator.retry(args.run_id)
    if action == "recover":
        return orchestrator.recover(args.run_id)
    raise ValueError(f"unknown production action: {action}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", default="start", choices=("start", "rerun", "resume", "retry", "recover", "revalidate_candidates", "promote", "revise_structure"))
    parser.add_argument("--node")
    parser.add_argument("--run-id")
    parser.add_argument("--until", choices=STAGES)
    parser.add_argument("--question-bank-version")
    parser.add_argument("--graph-version")
    parser.add_argument("--manifest-id")
    parser.add_argument("--source-run-id")
    parser.add_argument("--feedback", type=json.loads)
    parser.add_argument("--database", type=Path, default=ROOT / "data/local_learning_system.sqlite")
    args = parser.parse_args()

    node = None
    if args.action in {"start", "rerun", "revise_structure"}:
        if not args.node:
            parser.error("--node is required for --action start")
        graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        node = next((item for item in graph.get("nodes", []) if item.get("id") == args.node), None)
        if node is None:
            raise SystemExit(f"unknown node: {args.node}")
    conn = db.connect(args.database)
    try:
        db.init_schema(conn)
        orchestrator = create_live_question_production_orchestrator(conn)
        result = execute_action(orchestrator, args, node=node)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
