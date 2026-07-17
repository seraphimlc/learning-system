#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from learning_system import auto_review, db, evolution, server
from child_learning_scenarios import (
    FORBIDDEN_CHILD_TERMS,
    answer_payload_for_scenario,
    assert_required_coverage,
    check_child_safe,
    counter_to_dict,
    fake_answer_review,
    fake_photo_ocr,
    scenario_for,
    validate_session_semantics,
)


def current_task_total(page) -> int:
    text = page.locator("#childProgressText").inner_text()
    match = re.search(r"/\s*(\d+)", text)
    if not match:
        raise RuntimeError(f"Cannot read task total from progress text: {text}")
    return int(match.group(1))


def latest_session_metrics(conn, lesson: int) -> dict:
    latest_session = conn.execute(
        """
        select *
        from learning_sessions
        where mode = 'child_learning_group'
        order by created_at desc, id desc
        limit 1
        """
    ).fetchone()
    if not latest_session:
        return {"lesson": lesson, "session": "", "status": "", "closure_status": "", "summary": {}, "jobs": {}}
    summary = db.session_completion_summary(conn, latest_session["id"])
    jobs = conn.execute(
        "select status, count(*) as c from background_jobs where session_id = ? group by status",
        (latest_session["id"],),
    ).fetchall()
    return {
        "lesson": lesson,
        "session": latest_session["id"],
        "status": latest_session["status"],
        "closure_status": latest_session["closure_status"],
        "summary": summary,
        "jobs": {row["status"]: row["c"] for row in jobs},
    }


def wait_for_closed_lesson(db_path: Path, lesson: int, task_total: int, *, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last_metrics: dict = {}
    while time.time() < deadline:
        with db.connect(db_path) as conn:
            last_metrics = latest_session_metrics(conn, lesson)
        summary = last_metrics.get("summary") or {}
        jobs = last_metrics.get("jobs") or {}
        active_jobs = sum(jobs.get(status, 0) for status in ("queued", "running", "waiting", "error"))
        if (
            last_metrics.get("closure_status") == "planned"
            and summary.get("pending") == 0
            and summary.get("analyzed") == task_total
            and active_jobs == 0
        ):
            return last_metrics
        time.sleep(0.1)
    return last_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser smoke test for the child learning UI.")
    parser.add_argument("--lessons", type=int, default=10)
    parser.add_argument("--report", default=str(PROJECT_ROOT / "docs/system/qa/child_ui_smoke_latest.md"))
    parser.add_argument("--screenshot", default=str(PROJECT_ROOT / "docs/system/qa/child_ui_smoke_latest.png"))
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        db_path = tmpdir / "ui-smoke.sqlite"
        upload_root = tmpdir / "uploads" / "answers"
        photo_path = tmpdir / "paper-answer.png"
        photo_path.write_bytes(b"\x89PNG\r\n\x1a\nui-smoke-photo")
        with db.connect(db_path) as conn:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)

        env = {
            "OPENAI_API_KEY": "ui-smoke-key",
            "OPENAI_BASE_URL": "https://simulation.invalid/v1",
            "AI_EVALUATOR_MODEL": "gpt-5.5",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "AI_VISION_MODEL": "doubao-seed-2-0-pro-260215",
            "AI_BACKGROUND_REVIEW_CONCURRENCY": "4",
            "AI_BACKGROUND_REVIEW_MAX_PASSES": "3",
        }
        issues: list[str] = []
        metrics = {"lessons": []}
        semantic_results = []
        with patch.dict(os.environ, env, clear=False), \
            patch.object(auto_review, "_call_openai_evaluator", side_effect=fake_answer_review), \
            patch.object(auto_review, "_review_answer_photo", side_effect=fake_photo_ocr), \
            patch.object(evolution, "_call_openai_question_candidate", side_effect=evolution.QuestionCandidateError("ui smoke skips live question model")):
            httpd, base_url = server.start_test_server(db_path, upload_root=upload_root)
            try:
                with sync_playwright() as playwright:
                    chrome_path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                    launch_kwargs = {"headless": True}
                    if chrome_path.exists():
                        launch_kwargs["executable_path"] = str(chrome_path)
                    browser = playwright.chromium.launch(**launch_kwargs)
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    page.goto(base_url, wait_until="networkidle")
                    page.wait_for_selector("#childAttemptForm:not([hidden])", timeout=5000)
                    page.wait_for_function("document.querySelector('#dbStatus')?.textContent?.includes('准备好了')")
                    start = time.perf_counter()
                    for lesson in range(1, args.lessons + 1):
                        page.wait_for_selector("#childAttemptForm:not([hidden])", timeout=10000)
                        task_total = current_task_total(page)
                        lesson_start = time.perf_counter()
                        scenarios = []
                        for index in range(task_total):
                            scenario = scenario_for(lesson, index + 1)
                            scenarios.append(scenario)
                            answer, _photo_data_url = answer_payload_for_scenario(scenario)
                            if scenario.has_photo:
                                page.set_input_files("#childAnswerPhoto", str(photo_path))
                                page.wait_for_selector("#childPhotoPreview:not([hidden])", timeout=5000)
                            page.fill("#childAnswerRaw", answer)
                            page.click("#childSubmitBtn")
                            if index < task_total - 1:
                                page.wait_for_function(
                                    "document.querySelector('#childAnswerRaw')?.value === '' && "
                                    "document.querySelector('#childAttemptForm') && !document.querySelector('#childAttemptForm').hidden",
                                    timeout=5000,
                                )
                            else:
                                page.wait_for_selector("#childHandoffState:not([hidden])", timeout=10000)
                        lesson_metrics = wait_for_closed_lesson(db_path, lesson, task_total)
                        try:
                            page.wait_for_function(
                                "(() => {"
                                "const handoff = document.querySelector('#childHandoffState');"
                                "const button = document.querySelector('#startNextRoundBtn');"
                                "const text = button?.textContent || '';"
                                "return handoff && !handoff.hidden && button && !button.hidden && "
                                "!text.includes('再看一次') && !text.includes('稍后');"
                                "})()",
                                timeout=10000,
                            )
                        except PlaywrightTimeoutError:
                            body_text = page.locator("body").inner_text()
                            issues.append(f"lesson {lesson}: UI did not expose the completion review handoff after DB closure. Body: {body_text[:500]}")
                        with db.connect(db_path) as conn:
                            lesson_semantic = validate_session_semantics(conn, lesson_metrics["session"], lesson, scenarios)
                        lesson_metrics["task_total"] = task_total
                        lesson_metrics["elapsed_seconds"] = round(time.perf_counter() - lesson_start, 3)
                        lesson_metrics["scenario_counts"] = counter_to_dict(lesson_semantic.scenario_counts)
                        lesson_metrics["result_counts"] = counter_to_dict(lesson_semantic.result_counts)
                        lesson_metrics["error_tag_counts"] = counter_to_dict(lesson_semantic.error_tag_counts)
                        lesson_metrics["plan_task_types"] = lesson_semantic.plan_task_types
                        lesson_metrics["observations"] = lesson_semantic.observations
                        metrics["lessons"].append(lesson_metrics)
                        semantic_results.append(lesson_semantic)
                        if lesson_metrics["closure_status"] != "planned":
                            issues.append(f"lesson {lesson}: latest session closure_status={lesson_metrics['closure_status']}")
                        summary = lesson_metrics.get("summary") or {}
                        if summary.get("pending") != 0 or summary.get("analyzed") != task_total:
                            issues.append(f"lesson {lesson}: inconsistent summary {summary}")
                        jobs = lesson_metrics.get("jobs") or {}
                        if jobs.get("queued") or jobs.get("running") or jobs.get("waiting") or jobs.get("error"):
                            issues.append(f"lesson {lesson}: unfinished jobs {jobs}")
                        issues.extend(lesson_semantic.issues)
                        if lesson < args.lessons:
                            page.click("#startNextRoundBtn")
                            try:
                                page.wait_for_selector("#childAttemptForm:not([hidden])", timeout=10000)
                            except PlaywrightTimeoutError:
                                body_text = page.locator("body").inner_text()
                                bootstrap_after_click = page.evaluate(
                                    "() => fetch('/api/child-bootstrap').then(r => r.json()).then(j => ({"
                                    "plan: j.today_plan?.plan_key,"
                                    "group: j.learning_group,"
                                    "completion: j.completion ? {status: j.completion.closure_status, state: j.completion.session?.state, title: j.completion.child_message?.child_title} : null"
                                    "}))"
                                )
                                button_after_click = page.evaluate(
                                    "() => { const b = document.querySelector('#startNextRoundBtn'); return b ? {hidden: b.hidden, disabled: b.disabled, text: b.textContent, rect: b.getBoundingClientRect().toJSON?.() || {x:b.getBoundingClientRect().x,y:b.getBoundingClientRect().y,width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height}} : null; }"
                                )
                                storage_after_click = page.evaluate(
                                    "() => Object.fromEntries(Object.keys(localStorage).sort().map(k => [k, localStorage.getItem(k)]))"
                                )
                                issues.append(f"lesson {lesson}: after completion handoff click, next task form did not appear. Body: {body_text[:500]}")
                                issues.append(f"lesson {lesson}: bootstrap after click {bootstrap_after_click}")
                                issues.append(f"lesson {lesson}: button after click {button_after_click}")
                                issues.append(f"lesson {lesson}: localStorage after click {storage_after_click}")
                                break
                    metrics["elapsed_seconds"] = round(time.perf_counter() - start, 3)
                    body_text = page.locator("body").inner_text()
                    for term in FORBIDDEN_CHILD_TERMS:
                        if term in body_text:
                            issues.append(f"visible body text leaked `{term}`")
                    issues.extend(assert_required_coverage(semantic_results, args.lessons))
                    screenshot_path = Path(args.screenshot)
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    browser.close()
            finally:
                httpd.shutdown()
                httpd.server_close()

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Child UI Mocked Regression QA",
        "",
        f"- Generated: {db.now_iso()}",
        f"- Verdict: {'MOCKED_REGRESSION_PASS' if not issues else 'MOCKED_REGRESSION_NEEDS_FIX'}",
        "- Scope: temp DB, mocked evaluator/OCR/question-model paths; this is not live-system acceptance.",
        f"- Target base URL: `{base_url}`",
        f"- DB path: `{db_path}`",
        "- Model mode: `mocked`",
        "- Patches active: `auto_review._call_openai_evaluator`, `auto_review._review_answer_photo`, `evolution._call_openai_question_candidate`",
        f"- Lessons: {args.lessons}",
        f"- Elapsed seconds: {metrics.get('elapsed_seconds')}",
        f"- Screenshot: `{Path(args.screenshot)}`",
        "",
        "## Lesson Summary",
        "",
        "| Lesson | Session | Tasks | Scenarios | Results | Tags | Follow-up | Status | Closure | Seconds | Summary | Jobs |",
        "|---:|---|---:|---|---|---|---|---|---|---:|---|---|",
    ]
    for item in metrics.get("lessons", []):
        summary = item.get("summary", {})
        summary_text = {
            "submitted": summary.get("submitted"),
            "graded": summary.get("graded"),
            "pending": summary.get("pending"),
            "analyzed": summary.get("analyzed"),
        }
        lines.append(
            f"| {item.get('lesson')} | `{item.get('session')}` | {item.get('task_total')} | "
            f"`{item.get('scenario_counts')}` | `{item.get('result_counts')}` | "
            f"`{item.get('error_tag_counts')}` | `{item.get('plan_task_types')}` | "
            f"{item.get('status')} | {item.get('closure_status')} | {item.get('elapsed_seconds')} | "
            f"`{summary_text}` | `{item.get('jobs')}` |"
        )
    lines.extend([
        "",
        "## Attempt Semantic Samples",
        "",
        "| Lesson | Task | Scenario | Result | Score | Tags | Blocking | Process gap | Comparison | Photo |",
        "|---:|---:|---|---|---:|---|---|---|---|---|",
    ])
    for lesson_item in metrics.get("lessons", []):
        for item in lesson_item.get("observations", []):
            tags = ",".join(item.get("error_tags") or [])
            comparison = ",".join(item.get("comparison") or [])
            gap = str(item.get("process_gap") or "").replace("|", "/")
            lines.append(
                f"| {item['lesson']} | {item['task']} | `{item['scenario']}` | {item['result']} | "
                f"{item['score']} | `{tags}` | {item['blocking']} | {gap} | `{comparison}` | "
                f"{item.get('photo_status') or '-'} |"
            )
    lines.extend([
        "",
        "## Issues",
        "",
    ])
    lines.extend([f"- {issue}" for issue in issues] or ["- None"])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report_path)
    if issues:
        for issue in issues:
            print(issue)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
