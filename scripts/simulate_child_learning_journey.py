#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from learning_system import auto_review, db, evolution, model_router, reports, server
from child_learning_scenarios import (
    FORBIDDEN_CHILD_TERMS,
    LearningScenario,
    SemanticValidation,
    answer_payload_for_scenario,
    assert_required_coverage,
    check_child_safe,
    counter_to_dict,
    fake_answer_review,
    fake_photo_ocr,
    scenario_for,
    validate_session_semantics,
)


@dataclass
class CaseResult:
    lesson: int
    task_count: int
    submit_latencies: list[float] = field(default_factory=list)
    submit_states: list[str] = field(default_factory=list)
    closure_status: str = ""
    closure_seconds: float = 0.0
    session_id: str = ""
    plan_key_before: str = ""
    plan_key_after: str = ""
    graded: int = 0
    pending: int = 0
    analyzed: int = 0
    background_job_counts: dict[str, int] = field(default_factory=dict)
    scenarios: list[str] = field(default_factory=list)
    semantic: SemanticValidation | None = None
    issues: list[str] = field(default_factory=list)


class ApiClient:
    def __init__(self, base_url: str):
        parsed = base_url.removeprefix("http://").split(":")
        self.host = parsed[0]
        self.port = int(parsed[1])

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else None
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw}
        return resp.status, data

    def json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        status, data = self.request(method, path, payload)
        if status < 200 or status >= 300:
            raise RuntimeError(f"{method} {path} failed with {status}: {data}")
        return data


def session_id_for_latest_child_group(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        select id
        from learning_sessions
        where mode = 'child_learning_group'
        order by created_at desc, id desc
        limit 1
        """
    ).fetchone()
    return row["id"] if row else ""


def background_job_counts(conn: sqlite3.Connection, session_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        select status, count(*) as c
        from background_jobs
        where session_id = ?
        group by status
        order by status
        """,
        (session_id,),
    ).fetchall()
    return {row["status"]: int(row["c"]) for row in rows}


def run_lesson(client: ApiClient, conn: sqlite3.Connection, lesson: int, *, submit_threshold: float) -> CaseResult:
    bootstrap = client.json("GET", "/api/child-bootstrap")
    result = CaseResult(
        lesson=lesson,
        task_count=len(bootstrap["today_plan"]["tasks"]),
        plan_key_before=bootstrap["today_plan"].get("display_key", ""),
    )
    result.issues.extend(check_child_safe(bootstrap, f"lesson {lesson} bootstrap"))
    if result.task_count == 0:
        result.issues.append("no child tasks available")
        return result

    scenarios: list[LearningScenario] = []
    for index, task in enumerate(bootstrap["today_plan"]["tasks"], start=1):
        scenario = scenario_for(lesson, index)
        scenarios.append(scenario)
        result.scenarios.append(scenario.key)
        answer_raw, photo_data_url = answer_payload_for_scenario(scenario)
        payload = {
            "session_handle": "current-learning-group",
            "task_position": task["position"],
            "answer_raw": answer_raw,
        }
        if photo_data_url:
            payload["answer_photo_data_url"] = photo_data_url
            payload["answer_photo_name"] = f"lesson-{lesson}-task-{index}.png"
        start = time.perf_counter()
        submitted = client.json("POST", "/api/child-submissions", payload)
        latency = time.perf_counter() - start
        result.submit_latencies.append(latency)
        result.submit_states.append(str(submitted.get("review_state", "")))
        result.issues.extend(check_child_safe(submitted, f"lesson {lesson} submission {index}"))
        if latency > submit_threshold:
            result.issues.append(f"submission {index} took {latency:.3f}s, above {submit_threshold:.3f}s")
        if submitted.get("review_state") != "being_reviewed":
            result.issues.append(f"submission {index} returned unexpected review_state={submitted.get('review_state')}")

        if index == 1:
            duplicate_status, duplicate_payload = client.request("POST", "/api/child-submissions", payload)
            if duplicate_status != 400:
                result.issues.append(f"duplicate submission expected 400, got {duplicate_status}:{duplicate_payload}")

    close_start = time.perf_counter()
    closure = {}
    deadline = time.time() + 20
    while time.time() < deadline:
        closure = client.json("POST", "/api/learning-sessions/current-learning-group/complete", {})
        result.issues.extend(check_child_safe(closure, f"lesson {lesson} closure"))
        if closure.get("closure_status") == "planned":
            break
        time.sleep(0.2)
    result.closure_seconds = time.perf_counter() - close_start
    result.closure_status = str(closure.get("closure_status", ""))
    if result.closure_status != "planned":
        result.issues.append(f"closure did not reach planned; got {result.closure_status}")

    result.session_id = session_id_for_latest_child_group(conn)
    if result.session_id:
        summary = db.session_completion_summary(conn, result.session_id)
        result.graded = int(summary["graded"])
        result.pending = int(summary["pending"])
        result.analyzed = int(summary["analyzed"])
        result.background_job_counts = background_job_counts(conn, result.session_id)
        if result.pending:
            result.issues.append(f"{result.pending} attempts still pending after closure")
        if result.analyzed != result.task_count:
            result.issues.append(f"analyzed count {result.analyzed} != task_count {result.task_count}")
        if result.background_job_counts.get("queued") or result.background_job_counts.get("running"):
            result.issues.append(f"unfinished background jobs: {result.background_job_counts}")
        semantic = validate_session_semantics(conn, result.session_id, lesson, scenarios)
        result.semantic = semantic
        result.issues.extend(semantic.issues)

    next_bootstrap = client.json("GET", "/api/child-bootstrap")
    result.plan_key_after = next_bootstrap["today_plan"].get("display_key", "")
    result.issues.extend(check_child_safe(next_bootstrap, f"lesson {lesson} next bootstrap"))
    if result.plan_key_after == result.plan_key_before:
        result.issues.append("next lesson did not expose a new plan key")
    return result


def write_report(path: Path, results: list[CaseResult], db_path: Path, report_date: str | None) -> None:
    semantic_results = [result.semantic for result in results if result.semantic is not None]
    coverage_issues = assert_required_coverage(semantic_results, len(results))
    failures = [issue for result in results for issue in result.issues] + coverage_issues
    lines = [
        "# Child Learning Journey QA Simulation",
        "",
        f"- Generated: {db.now_iso()}",
        f"- DB: `{db_path}`",
        f"- Lessons simulated: {len(results)}",
        f"- Verdict: {'PASS' if not failures else 'NEEDS_FIX'}",
        f"- Issues: {len(failures)}",
        "",
        "## Lesson Summary",
        "",
        "| Lesson | Session | Tasks | Scenarios | Results | Tags | Follow-up | Submit latency max | Closure | Closure seconds | Jobs | Issues |",
        "|---:|---|---:|---|---|---|---|---:|---|---:|---|---:|",
    ]
    for result in results:
        max_latency = max(result.submit_latencies or [0.0])
        semantic = result.semantic
        scenario_counts = counter_to_dict(semantic.scenario_counts) if semantic else {}
        result_counts = counter_to_dict(semantic.result_counts) if semantic else {}
        tag_counts = counter_to_dict(semantic.error_tag_counts) if semantic else {}
        follow_up = semantic.plan_task_types if semantic else []
        lines.append(
            f"| {result.lesson} | `{result.session_id}` | {result.task_count} | "
            f"`{json.dumps(scenario_counts, ensure_ascii=False)}` | "
            f"`{json.dumps(result_counts, ensure_ascii=False)}` | "
            f"`{json.dumps(tag_counts, ensure_ascii=False)}` | "
            f"`{json.dumps(follow_up, ensure_ascii=False)}` | {max_latency:.3f}s | "
            f"{result.closure_status} | {result.closure_seconds:.2f}s | "
            f"`{json.dumps(result.background_job_counts, ensure_ascii=False)}` | {len(result.issues)} |"
        )
    lines.extend([
        "",
        "## Attempt Semantic Samples",
        "",
        "| Lesson | Task | Scenario | Result | Score | Tags | Blocking | Process gap | Comparison | Photo |",
        "|---:|---:|---|---|---:|---|---|---|---|---|",
    ])
    for result in results:
        if not result.semantic:
            continue
        for item in result.semantic.observations:
            tags = ",".join(item.get("error_tags") or [])
            comparison = ",".join(item.get("comparison") or [])
            gap = str(item.get("process_gap") or "").replace("|", "/")
            lines.append(
                f"| {item['lesson']} | {item['task']} | `{item['scenario']}` | {item['result']} | "
                f"{item['score']} | `{tags}` | {item['blocking']} | {gap} | `{comparison}` | "
                f"{item.get('photo_status') or '-'} |"
            )
    lines.extend(["", "## Issues", ""])
    if failures:
        for result in results:
            for issue in result.issues:
                lines.append(f"- L{result.lesson}: {issue}")
        for issue in coverage_issues:
            lines.append(f"- coverage: {issue}")
    else:
        lines.append("- None")
    lines.extend(["", "## Notes", ""])
    lines.append("- Child submissions are expected to return `being_reviewed` immediately; model review is simulated with 180 ms latency.")
    lines.append("- Semantic QA validates correct, wrong, stuck, answer-only, wrong-reason-right-answer, photo, unclear-photo, and partial-relation cases.")
    lines.append("- The script verifies persisted result/error tags/process gaps/photo OCR/cause analysis/node status and evidence-linked next plans.")
    lines.append("- The simulation uses a temporary DB by default and does not mutate the real learning ledger.")
    if report_date:
        lines.append(f"- Daily report date override: `{report_date}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate multiple child learning lessons through the real local HTTP API.")
    parser.add_argument("--lessons", type=int, default=10)
    parser.add_argument("--db-copy-from", default="")
    parser.add_argument("--keep-db", default="")
    parser.add_argument("--report", default=str(PROJECT_ROOT / "docs/system/qa/child_learning_simulation_latest.md"))
    parser.add_argument("--submit-threshold", type=float, default=0.75)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        db_path = Path(args.keep_db) if args.keep_db else tmpdir / "simulation.sqlite"
        upload_root = tmpdir / "uploads" / "answers"
        if args.db_copy_from:
            shutil.copy2(args.db_copy_from, db_path)
        with db.connect(db_path) as conn:
            db.init_schema(conn)
            if not args.db_copy_from:
                db.seed_from_assets(conn, PROJECT_ROOT)

        env = {
            "OPENAI_API_KEY": "simulation-key",
            "OPENAI_BASE_URL": "https://simulation.invalid/v1",
            "AI_EVALUATOR_MODEL": "gpt-5.5",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "AI_VISION_MODEL": "doubao-seed-2-0-pro-260215",
            "AI_BACKGROUND_REVIEW_CONCURRENCY": "4",
            "AI_BACKGROUND_REVIEW_MAX_PASSES": "3",
        }
        with patch.dict(os.environ, env, clear=False), \
            patch.object(auto_review, "_call_openai_evaluator", side_effect=fake_answer_review), \
            patch.object(auto_review, "_review_answer_photo", side_effect=fake_photo_ocr), \
            patch.object(evolution, "_call_openai_question_candidate", side_effect=evolution.QuestionCandidateError("simulation skips live question model")):
            httpd, base_url = server.start_test_server(db_path, upload_root=upload_root)
            client = ApiClient(base_url)
            results: list[CaseResult] = []
            try:
                with db.connect(db_path) as conn:
                    for lesson in range(1, args.lessons + 1):
                        results.append(run_lesson(client, conn, lesson, submit_threshold=args.submit_threshold))
            finally:
                httpd.shutdown()
                httpd.server_close()

        with db.connect(db_path) as conn:
            db.init_schema(conn)
            qa_report_dir = PROJECT_ROOT / "docs/system/qa"
            reports.write_daily_report(conn, qa_report_dir, report_date=None)
        report_path = Path(args.report)
        write_report(report_path, results, db_path, report_date=None)
        print(report_path)
        semantic_results = [result.semantic for result in results if result.semantic is not None]
        failures = [issue for result in results for issue in result.issues] + assert_required_coverage(semantic_results, len(results))
        if failures:
            print(json.dumps({"verdict": "NEEDS_FIX", "issues": failures}, ensure_ascii=False, indent=2))
            raise SystemExit(1)
        print(json.dumps({"verdict": "PASS", "lessons": len(results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
