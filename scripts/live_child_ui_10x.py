#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import http.client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from learning_system import db, planner
from child_learning_scenarios import (
    FORBIDDEN_CHILD_TERMS,
    assert_required_coverage,
    scenario_for,
    validate_session_semantics,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_DB_PATH = PROJECT_ROOT / "data/local_learning_system.sqlite"
DEFAULT_REPORT = PROJECT_ROOT / "docs/system/qa/live_child_ui_10x_latest.md"
DEFAULT_JSON = PROJECT_ROOT / "docs/system/qa/live_child_ui_10x_latest.json"
DEFAULT_SCREENSHOT = PROJECT_ROOT / "docs/system/qa/live_child_ui_10x_latest.png"
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "artifacts/live-child-ui-10x"

NEXT_ROUND_BUTTON_MARKERS = ("看讲解", "开始下一组", "开始拔高题", "继续下一组", "开始")
REFRESH_BUTTON_MARKERS = ("再看一次", "刷新批阅状态")


@dataclass
class AnswerPayload:
    text: str
    photo_path: Path | None = None


def request_json(method: str, base_url: str, path: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    parsed = urlparse(base_url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    raw = response.read().decode("utf-8")
    conn.close()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"raw": raw}
    return {"status": response.status, "payload": data, "raw": raw}


def current_task_total(page) -> int:
    text = page.locator("#childProgressText").inner_text(timeout=5000)
    match = re.search(r"/\s*(\d+)", text)
    if not match:
        raise RuntimeError(f"Cannot read task total from progress text: {text}")
    return int(match.group(1))


def latest_generated_plan(conn) -> dict:
    row = conn.execute(
        "select * from generated_plans order by created_at desc, id desc limit 1"
    ).fetchone()
    if not row:
        raise RuntimeError("No generated plan exists")
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "tasks": db.json_load(row["tasks_json"], []),
    }


def question_by_id(conn, question_id: str) -> dict:
    return db.get_question(conn, question_id)


def latest_child_session(conn) -> dict | None:
    row = conn.execute(
        """
        select *
        from learning_sessions
        where mode = 'child_learning_group'
        order by created_at desc, id desc
        limit 1
        """
    ).fetchone()
    return db.get_learning_session(conn, row["id"]) if row else None


def jobs_for_session(conn, session_id: str) -> dict[str, int]:
    return {
        row["status"]: row["n"]
        for row in conn.execute(
            "select status, count(*) as n from background_jobs where session_id = ? group by status",
            (session_id,),
        ).fetchall()
    }


def active_job_count(jobs: dict[str, int]) -> int:
    return sum(jobs.get(status, 0) for status in ("queued", "running", "waiting", "error"))


def is_next_round_button(text: str) -> bool:
    normalized = " ".join((text or "").split())
    return any(marker in normalized for marker in NEXT_ROUND_BUTTON_MARKERS) and not is_refresh_button(normalized)


def is_refresh_button(text: str) -> bool:
    normalized = " ".join((text or "").split())
    return any(marker in normalized for marker in REFRESH_BUTTON_MARKERS)


def wait_for_session_planned(db_path: Path, task_total: int, timeout_seconds: float) -> dict:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        with db.connect(db_path) as conn:
            session = latest_child_session(conn)
            if session:
                summary = db.session_completion_summary(conn, session["id"])
                jobs = jobs_for_session(conn, session["id"])
                last = {
                    "session": session,
                    "summary": summary,
                    "jobs": jobs,
                }
                if (
                    session.get("status") == "closed"
                    and session.get("closure_status") == "planned"
                    and summary.get("pending") == 0
                    and summary.get("analyzed") == task_total
                    and active_job_count(jobs) == 0
                ):
                    return last
        time.sleep(0.25)
    return last


def wait_for_child_conclusion(
    page,
    timeout_seconds: float,
    *,
    refresh_after_seconds: float = 12.0,
) -> tuple[bool, bool, dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    start = time.time()
    clicked_refresh = False
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        state = page.evaluate(
            """
            () => {
              const text = (id) => {
                const el = document.querySelector(id);
                if (!el) return {missing: true};
                return {
                  hidden: el.hidden,
                  text: (el.innerText || el.textContent || '').trim(),
                };
              };
	              return {
	                heading: text('#childHeading'),
	                progress: text('#childProgressText'),
	                pending: text('#childPendingText'),
	                handoff: text('#childHandoffState'),
	                handoffTitle: text('#childHandoffTitle'),
	                handoffText: text('#childHandoffText'),
	                button: text('#startNextRoundBtn'),
	                form: text('#childAttemptForm'),
	                review: Array.from(document.querySelectorAll('#childReviewPoints .review-point')).map(el => (el.innerText || '').trim()),
	                coach: Array.from(document.querySelectorAll('#childCoachPoints .coach-point')).map(el => (el.innerText || '').trim()),
	              };
	            }
            """
        )
        last_state = state
        button_text = state.get("button", {}).get("text", "")
        handoff_visible = not state.get("handoff", {}).get("hidden", True)
        button_visible = not state.get("button", {}).get("hidden", True)
        if handoff_visible and button_visible and is_next_round_button(button_text):
            return True, clicked_refresh, state
        # The app polls every 3.5s while waiting for AI. Give that automatic
        # path a few cycles before using the child-visible manual refresh button.
        if (
            handoff_visible
            and button_visible
            and is_refresh_button(button_text)
            and not clicked_refresh
            and time.time() - start >= refresh_after_seconds
        ):
            page.click("#startNextRoundBtn")
            clicked_refresh = True
        time.sleep(0.5)
    return False, clicked_refresh, last_state


def ensure_task_form(page) -> None:
    for _ in range(4):
        try:
            page.wait_for_selector("#childAttemptForm:not([hidden])", timeout=2500)
            return
        except PlaywrightTimeoutError:
            button = page.locator("#startNextRoundBtn")
            if button.count() == 1 and button.is_visible() and is_next_round_button(button.inner_text(timeout=1000)):
                button.click()
                continue
            raise
    page.wait_for_selector("#childAttemptForm:not([hidden])", timeout=10000)


def write_photo(path: Path, text: str, *, unclear: bool = False) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1180, 760), (250, 250, 246))
    draw = ImageDraw.Draw(image)
    font = None
    for candidate in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ):
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, 34)
            break
    if font is None:
        font = ImageFont.load_default()
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        lines.extend(textwrap.wrap(paragraph, width=28) or [""])
    y = 44
    fill = (28, 32, 38) if not unclear else (185, 185, 185)
    for line in lines[:15]:
        draw.text((52, y), line, fill=fill, font=font)
        y += 46
    if unclear:
        image = image.filter(ImageFilter.GaussianBlur(radius=3.2))
    image.save(path)


def compact_answer_only(expected: str) -> str:
    text = " ".join(str(expected or "").split())
    if not text:
        return "最后答案略。"
    pieces = [piece.strip() for piece in re.split(r"[。；;\n]", text) if piece.strip()]
    marker_patterns = (
        r"解得\s*([^。；;]+)",
        r"(?:最终答案|答案|结果|结论|正确结论|正确|方程(?:为)?|列方程)[:：]?\s*([^。；;]+)",
    )
    for piece in reversed(pieces):
        for pattern in marker_patterns:
            match = re.search(pattern, piece)
            if match:
                candidate = match.group(1).strip(" ：:，,。；;")
                if candidate:
                    return candidate[:80]
    mathish = [piece for piece in reversed(pieces) if re.search(r"[0-9a-zA-Z=+×÷*/()]", piece)]
    if mathish:
        return mathish[0][:80]
    return pieces[-1][:80] if pieces else text[:80]


def scenario_answer(scenario_key: str, question: dict[str, Any], artifact_dir: Path, lesson: int, position: int) -> AnswerPayload:
    prompt = str(question.get("prompt") or "")
    expected = str(question.get("expected_answer") or "按题意完成结论。")
    steps = question.get("solution_steps") if isinstance(question.get("solution_steps"), list) else []
    compact_steps = "；".join(str(step) for step in steps[:3]) or "先写规则，再写关键步骤，最后检验。"
    if scenario_key == "correct_full":
        return AnswerPayload(
            "我按完整步骤写：\n"
            f"规则/关系：{compact_steps}\n"
            f"答案：{expected}\n"
            "检验：把结论代回题意，检查符号、单位、括号和数量关系都一致。"
        )
    if scenario_key == "answer_only":
        final_only = compact_answer_only(expected)
        return AnswerPayload(f"只写答案：{final_only}。没有写规则、步骤和检验。")
    if scenario_key == "stuck":
        return AnswerPayload("我卡住了：题目能读完，但不知道第一步应该找哪个关系，也不知道该列式还是先画图。")
    if scenario_key == "wrong_reason_right_answer":
        return AnswerPayload(
            f"答案我写成：{expected}\n"
            "但我不是按题意推出来的，我是看数字差不多硬凑的关系，所以过程可能不成立。"
        )
    if scenario_key == "partial_relation_wrong_final":
        return AnswerPayload(
            "我先找关系，感觉应该先列式或写等量关系；但是我最后符号/单位可能写反了，"
            "也没有代回检查，所以最终答案我不能确定。"
        )
    if scenario_key == "blank_or_no_evidence":
        return AnswerPayload("我不会，这题先空着。现在没有可用步骤，只知道应该先读题。")
    if scenario_key == "photo_correct":
        photo_text = (
            "纸面答案\n"
            f"题意关键词：{prompt[:80]}\n"
            f"步骤：{compact_steps}\n"
            f"答案：{expected}\n"
            "检验：代回原题成立。"
        )
        photo = artifact_dir / f"lesson-{lesson:02d}-task-{position:02d}-photo-correct.png"
        write_photo(photo, photo_text)
        return AnswerPayload("见照片。我在纸面写了规则、关键步骤、答案和检验。", photo)
    if scenario_key == "photo_unclear":
        photo = artifact_dir / f"lesson-{lesson:02d}-task-{position:02d}-photo-unclear.png"
        write_photo(photo, "看不清的纸面过程：符号、步骤和答案都不稳定。", unclear=True)
        return AnswerPayload("见照片，但照片不清。我没有补充完整可读步骤。", photo)
    return AnswerPayload("我先写规则，再写步骤，最后检查。")


def collect_session_detail(conn, session_id: str, scenarios: list[str], task_records: list[dict[str, Any]]) -> dict[str, Any]:
    session = db.get_learning_session(conn, session_id)
    attempts = db.attempts_for_session(conn, session_id)
    by_question = {attempt["question_id"]: db.get_attempt(conn, attempt["id"]) for attempt in attempts}
    ordered = []
    for index, task in enumerate(task_records, start=1):
        question_id = task.get("question_id")
        question = question_by_id(conn, question_id)
        attempt = by_question.get(question_id)
        if not attempt:
            continue
        analysis = attempt.get("answer_analysis") or {}
        review_meta = attempt.get("review_meta") if isinstance(attempt.get("review_meta"), dict) else {}
        ordered.append({
            "position": index,
            "attempt_id": attempt.get("id"),
            "scenario": scenarios[index - 1] if index - 1 < len(scenarios) else "",
            "question_id": question_id,
            "node_id": question.get("node_id"),
            "node_name": task.get("node_name"),
            "prompt": question.get("prompt"),
            "answer_raw": attempt.get("answer_raw"),
            "result": attempt.get("result"),
            "score_points": attempt.get("score_points"),
            "max_points": attempt.get("max_points"),
            "explanation_score": attempt.get("explanation_score"),
            "blocking_evidence": attempt.get("blocking_evidence"),
            "error_tags": attempt.get("error_tags"),
            "review_status": review_meta.get("status"),
            "review_model": review_meta.get("model"),
            "review_confidence": review_meta.get("confidence"),
            "vision": review_meta.get("vision") if isinstance(review_meta.get("vision"), dict) else None,
            "answer_analysis": {
                "optimal_answer": analysis.get("optimal_answer"),
                "child_answer_summary": analysis.get("child_answer_summary"),
                "comparison": analysis.get("comparison"),
                "process_gap": analysis.get("process_gap"),
                "teaching_explanation": analysis.get("teaching_explanation"),
                "next_child_prompt": analysis.get("next_child_prompt"),
            },
        })
    closure_result = session.get("closure_result") or {}
    next_plan = closure_result.get("next_plan") if isinstance(closure_result.get("next_plan"), dict) else {}
    return {
        "session": {
            "id": session.get("id"),
            "status": session.get("status"),
            "closure_status": session.get("closure_status"),
            "next_plan_id": session.get("next_plan_id"),
            "created_at": session.get("created_at"),
            "closed_at": session.get("closed_at"),
        },
        "attempt_summary": db.session_completion_summary(conn, session_id),
        "jobs": jobs_for_session(conn, session_id),
        "child_message": closure_result.get("child_message"),
        "next_plan": {
            "id": next_plan.get("id"),
            "title": next_plan.get("title"),
            "tasks": [
                {
                    "position": index + 1,
                    "task_type": task.get("task_type"),
                    "node_id": task.get("node_id"),
                    "node_name": task.get("node_name"),
                    "question_id": task.get("question_id"),
                    "question_type": (task.get("question") or {}).get("question_type"),
                    "prompt": (task.get("question") or {}).get("prompt"),
                    "planning_signal": task.get("planning_signal"),
                    "selected_question_reason": task.get("selected_question_reason"),
                    "source_node_ids": task.get("source_node_ids"),
                }
                for index, task in enumerate(next_plan.get("tasks") or [])
            ],
        },
        "attempts": ordered,
    }


def audit_lesson(detail: dict[str, Any], visible_state: dict[str, Any], conclusion_visible: bool, refresh_clicked: bool) -> list[str]:
    issues: list[str] = []
    semantic_results: list[Any] = []
    session = detail.get("session") or {}
    summary = detail.get("attempt_summary") or {}
    jobs = detail.get("jobs") or {}
    if session.get("status") != "closed" or session.get("closure_status") != "planned":
        issues.append(f"session {session.get('id')} did not close planned: {session}")
    if summary.get("pending") != 0 or summary.get("analyzed") != summary.get("attempt_count"):
        issues.append(f"session {session.get('id')} has incomplete analysis summary: {summary}")
    if active_job_count(jobs) != 0:
        issues.append(f"session {session.get('id')} has unfinished jobs: {jobs}")
    if not conclusion_visible:
        issues.append(f"session {session.get('id')} did not show child conclusion before timeout: {visible_state}")
    if refresh_clicked:
        issues.append(f"session {session.get('id')} needed manual refresh click before conclusion became visible")
    serialized_visible = json.dumps(visible_state, ensure_ascii=False)
    for term in FORBIDDEN_CHILD_TERMS:
        if term in serialized_visible:
            issues.append(f"child visible state leaked forbidden term `{term}`")
    attempts = detail.get("attempts") or []
    child_message = detail.get("child_message") if isinstance(detail.get("child_message"), dict) else {}
    child_review_points = child_message.get("review_points") if isinstance(child_message.get("review_points"), list) else []
    visible_review_points = visible_state.get("review") if isinstance(visible_state.get("review"), list) else []
    if len(child_review_points) != len(attempts):
        issues.append(
            f"session {session.get('id')} child_message review point count {len(child_review_points)} "
            f"does not match attempts {len(attempts)}"
        )
    if conclusion_visible and len(visible_review_points) != len(attempts):
        issues.append(
            f"session {session.get('id')} visible review point count {len(visible_review_points)} "
            f"does not match attempts {len(attempts)}"
        )
    for index in range(1, len(attempts) + 1):
        marker = f"第{index}题"
        if child_review_points and not any(marker in json.dumps(point, ensure_ascii=False) for point in child_review_points):
            issues.append(f"session {session.get('id')} child_message missing review marker {marker}")
        if visible_review_points and not any(marker in text for text in visible_review_points):
            issues.append(f"session {session.get('id')} visible review missing marker {marker}")
    for attempt in attempts:
        scenario = attempt.get("scenario")
        result = attempt.get("result")
        score = float(attempt.get("score_points") or 0)
        analysis = attempt.get("answer_analysis") or {}
        if attempt.get("review_status") != "graded":
            issues.append(f"task {attempt.get('position')} review_status is {attempt.get('review_status')}")
        if not analysis.get("comparison") or not analysis.get("teaching_explanation"):
            issues.append(f"task {attempt.get('position')} missing detailed answer_analysis")
        if scenario in {"answer_only", "wrong_reason_right_answer", "blank_or_no_evidence", "stuck"} and result == "correct" and score >= 2:
            issues.append(f"task {attempt.get('position')} scenario `{scenario}` was graded full correct")
        if scenario == "correct_full" and result == "wrong":
            issues.append(f"task {attempt.get('position')} correct_full answer was graded wrong")
    next_tasks = (detail.get("next_plan") or {}).get("tasks") or []
    if not next_tasks:
        issues.append(f"session {session.get('id')} did not create next plan tasks")
    weak_attempts = [
        attempt for attempt in detail.get("attempts") or []
        if attempt.get("result") != "correct" or float(attempt.get("score_points") or 0) < 2
    ]
    if weak_attempts:
        linked = False
        weak_node_ids = {attempt.get("node_id") for attempt in weak_attempts}
        for task in next_tasks:
            signal = task.get("planning_signal") if isinstance(task.get("planning_signal"), dict) else {}
            source_node_ids = set(task.get("source_node_ids") or [])
            if task.get("node_id") in weak_node_ids or source_node_ids & weak_node_ids:
                linked = True
            if set(signal.get("evidence_attempt_ids") or []) & {attempt.get("attempt_id") for attempt in weak_attempts}:
                linked = True
        if not linked:
            issues.append(f"next plan is not visibly linked to weak node evidence: weak_nodes={sorted(str(n) for n in weak_node_ids)}")
    return issues


def render_report(payload: dict[str, Any], issues: list[str]) -> str:
    verdict = "LIVE_CHILD_UI_10X_PASS" if not issues else "LIVE_CHILD_UI_10X_NEEDS_FIX"
    lines = [
        "# Live Child UI 10x QA",
        "",
        f"- Generated: {db.now_iso()}",
        f"- Verdict: `{verdict}`",
        f"- Scope: real browser operations against current 8765 and current local SQLite DB; mutates the test-stage learning ledger.",
        f"- Base URL: `{payload['base_url']}`",
        f"- DB path: `{payload['db_path']}`",
        f"- Lessons requested: {payload['lessons_requested']}",
        f"- Lessons completed: {len(payload['lessons'])}",
        f"- Elapsed seconds: {payload.get('elapsed_seconds')}",
        f"- Screenshot: `{payload.get('screenshot')}`",
        f"- JSON evidence: `{payload.get('json_report')}`",
        "",
        "## Issues",
        "",
    ]
    lines.extend([f"- {issue}" for issue in issues] or ["- None"])
    lines.extend([
        "",
        "## Lesson Summary",
        "",
        "| Lesson | Session | Tasks | Scenarios | Results | Tags | Conclusion Visible | Refresh Clicked | Closure | Jobs | Next Tasks | Seconds |",
        "|---:|---|---:|---|---|---|---|---|---|---|---|---:|",
    ])
    for lesson in payload["lessons"]:
        attempts = lesson.get("detail", {}).get("attempts", [])
        results = Counter(str(item.get("result")) for item in attempts)
        tags = Counter(tag for item in attempts for tag in (item.get("error_tags") or []))
        scenarios = Counter(str(item.get("scenario")) for item in attempts)
        next_types = [
            f"{task.get('task_type')}:{task.get('node_name')}"
            for task in lesson.get("detail", {}).get("next_plan", {}).get("tasks", [])
        ]
        lines.append(
            f"| {lesson['lesson']} | `{lesson.get('session_id')}` | {len(attempts)} | "
            f"`{dict(scenarios)}` | `{dict(results)}` | `{dict(tags)}` | "
            f"{lesson.get('conclusion_visible')} | {lesson.get('refresh_clicked')} | "
            f"{lesson.get('detail', {}).get('session', {}).get('closure_status')} | "
            f"`{lesson.get('detail', {}).get('jobs')}` | `{next_types}` | {lesson.get('elapsed_seconds')} |"
        )
    lines.extend([
        "",
        "## Per-Lesson Evidence",
        "",
    ])
    for lesson in payload["lessons"]:
        lines.extend([
            f"### Lesson {lesson['lesson']} - `{lesson.get('session_id')}`",
            "",
            f"- Visible conclusion: `{lesson.get('visible_state', {}).get('handoffTitle', {}).get('text', '')}` / `{lesson.get('visible_state', {}).get('button', {}).get('text', '')}`",
            f"- Child feedback: {lesson.get('visible_state', {}).get('handoffText', {}).get('text', '')}",
            "",
            "| Task | Scenario | Node | Result | Score | Tags | Process gap | Next prompt |",
            "|---:|---|---|---|---:|---|---|---|",
        ])
        for attempt in lesson.get("detail", {}).get("attempts", []):
            analysis = attempt.get("answer_analysis") or {}
            gap = str(analysis.get("process_gap") or "").replace("|", "/")
            next_prompt = str(analysis.get("next_child_prompt") or "").replace("|", "/")
            lines.append(
                f"| {attempt.get('position')} | `{attempt.get('scenario')}` | {attempt.get('node_name')} | "
                f"{attempt.get('result')} | {attempt.get('score_points')} | `{attempt.get('error_tags')}` | "
                f"{gap[:180]} | {next_prompt[:180]} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live browser-driven 10-round child learning QA against 8765.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--lessons", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--json-report", default=str(DEFAULT_JSON))
    parser.add_argument("--screenshot", default=str(DEFAULT_SCREENSHOT))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    issues: list[str] = []
    payload: dict[str, Any] = {
        "base_url": args.base_url,
        "db_path": str(db_path),
        "lessons_requested": args.lessons,
        "lessons": [],
        "json_report": str(Path(args.json_report)),
        "screenshot": str(Path(args.screenshot)),
    }
    start = time.perf_counter()

    bootstrap = request_json("GET", args.base_url, "/api/child-bootstrap")
    if bootstrap["status"] >= 400:
        raise SystemExit(f"Cannot reach child bootstrap: {bootstrap['status']} {bootstrap['raw'][:300]}")

    with sync_playwright() as playwright:
        chrome_path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        launch_kwargs: dict[str, Any] = {"headless": not args.headed}
        if chrome_path.exists():
            launch_kwargs["executable_path"] = str(chrome_path)
        browser = playwright.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(args.base_url, wait_until="domcontentloaded")
        page.wait_for_selector("#dbStatus", timeout=10000)

        for lesson in range(1, args.lessons + 1):
            lesson_start = time.perf_counter()
            ensure_task_form(page)
            task_total = current_task_total(page)
            if task_total != planner.LEARNING_ROUND_TASK_COUNT:
                issues.append(
                    f"lesson {lesson}: UI task_total={task_total}, expected {planner.LEARNING_ROUND_TASK_COUNT}"
                )
            with db.connect(db_path) as conn:
                plan = latest_generated_plan(conn)
                task_records = plan["tasks"]
                if len(task_records) != planner.LEARNING_ROUND_TASK_COUNT:
                    issues.append(
                        f"lesson {lesson}: latest DB plan has {len(task_records)} tasks, expected {planner.LEARNING_ROUND_TASK_COUNT}"
                    )
                if len(task_records) != task_total:
                    issues.append(f"lesson {lesson}: UI task_total={task_total}, latest DB plan has {len(task_records)} tasks")
                questions = [
                    question_by_id(conn, task["question_id"])
                    for task in task_records[:task_total]
                ]

            scenarios: list[str] = []
            scenario_objects: list[Any] = []
            for index in range(task_total):
                scenario = scenario_for(lesson, index + 1)
                scenarios.append(scenario.key)
                scenario_objects.append(scenario)
                answer = scenario_answer(scenario.key, questions[index], artifact_dir, lesson, index + 1)
                if answer.photo_path:
                    page.set_input_files("#childAnswerPhoto", str(answer.photo_path))
                    page.wait_for_selector("#childPhotoPreview:not([hidden])", timeout=10000)
                page.fill("#childAnswerRaw", answer.text)
                before_progress = page.locator("#childProgressText").inner_text(timeout=5000)
                page.click("#childSubmitBtn")
                if index < task_total - 1:
                    page.wait_for_function(
                        """
                        ([before]) => {
                          const form = document.querySelector('#childAttemptForm');
                          const textarea = document.querySelector('#childAnswerRaw');
                          const progress = document.querySelector('#childProgressText');
                          return form && !form.hidden && textarea && textarea.value === '' &&
                                 progress && progress.textContent !== before;
                        }
                        """,
                        arg=[before_progress],
                        timeout=15000,
                    )
                else:
                    page.wait_for_selector("#childHandoffState:not([hidden])", timeout=15000)

            db_state = wait_for_session_planned(db_path, task_total, args.timeout_seconds)
            conclusion_visible, refresh_clicked, visible_state = wait_for_child_conclusion(page, args.timeout_seconds)
            with db.connect(db_path) as conn:
                session_id = (db_state.get("session") or latest_child_session(conn) or {}).get("id", "")
                detail = collect_session_detail(conn, session_id, scenarios, task_records[:task_total])
                semantic = validate_session_semantics(conn, session_id, lesson, scenario_objects)
            semantic_results.append(semantic)
            lesson_payload = {
                "lesson": lesson,
                "session_id": session_id,
                "plan_id_at_start": plan["id"],
                "scenarios": scenarios,
                "conclusion_visible": conclusion_visible,
                "refresh_clicked": refresh_clicked,
                "visible_state": visible_state,
                "detail": detail,
                "semantic_validation": {
                    "scenario_counts": dict(semantic.scenario_counts),
                    "result_counts": dict(semantic.result_counts),
                    "error_tag_counts": dict(semantic.error_tag_counts),
                    "plan_task_types": semantic.plan_task_types,
                    "plan_node_ids": semantic.plan_node_ids,
                    "weak_attempt_ids": semantic.weak_attempt_ids,
                    "weak_node_ids": semantic.weak_node_ids,
                    "observations": semantic.observations,
                    "issues": semantic.issues,
                },
                "elapsed_seconds": round(time.perf_counter() - lesson_start, 3),
            }
            payload["lessons"].append(lesson_payload)
            issues.extend([f"lesson {lesson}: {issue}" for issue in audit_lesson(detail, visible_state, conclusion_visible, refresh_clicked)])
            issues.extend([f"lesson {lesson}: semantic oracle: {issue}" for issue in semantic.issues])

            if not conclusion_visible:
                break
            if lesson < args.lessons:
                page.click("#startNextRoundBtn")
                ensure_task_form(page)

        screenshot_path = Path(args.screenshot)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()

    issues.extend(assert_required_coverage(semantic_results, args.lessons))
    payload["elapsed_seconds"] = round(time.perf_counter() - start, 3)
    payload["issues"] = issues

    report_path = Path(args.report)
    json_path = Path(args.json_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_report(payload, issues), encoding="utf-8")
    print(report_path)
    print(json_path)
    if issues:
        for issue in issues:
            print(issue)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
