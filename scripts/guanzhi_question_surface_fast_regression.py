#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, question_bank  # noqa: E402


DEFAULT_DB = PROJECT_ROOT / "data/local_learning_system.sqlite"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts/guanzhi-question-surface-fast"
APP_ROOT = PROJECT_ROOT / "app/local_learning_system"
FORBIDDEN_CHILD_SURFACE = re.compile(
    r"node_id|graph_version|question_id|attempt_id|flow_id|job_id|provider|rubric|"
    r"queue|agent_run|candidate_packet|expected_answer|response_schema|api_key",
    re.IGNORECASE,
)
ENGLISH_FEEDBACK = re.compile(
    r"\b(Missing|Add one sentence|Briefly state|The calculation|correct but|"
    r"wrong because|gap|improvement|standard answer)\b"
)


def _active_payloads(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select qi.*, ac.review_record_id, gn.name as node_title
        from answer_contracts ac
        join question_items qi
          on qi.id = ac.question_id and qi.item_version = ac.item_version
        left join graph_nodes gn on gn.id = qi.node_id
        where ac.status = 'active'
        order by qi.node_id, qi.id
        """
    ).fetchall()
    payloads: list[dict[str, Any]] = []
    for row in rows:
        question = db.row_to_question(row)
        review_record_id = str(row["review_record_id"] or "")
        if not (
            db.is_child_schedulable_question(
                conn,
                question,
                question_bank_version=str(question.get("item_version") or ""),
            )
            and db.question_review_record_allows_active_use(conn, question, review_record_id)
        ):
            continue
        surface = question_bank.canonical_child_surface_projection(question)
        prompt = str(surface["prompt"] or "")
        topic = str(row["node_title"] or question.get("node_id") or "当前知识点")
        payloads.append(
            {
                "schema_version": "3.0.0-daily-flow",
                "child_state": "current_step",
                "ready_for_new_knowledge": False,
                "message": {},
                "current_step": {
                    "step_handle": f"surface-{len(payloads) + 1}",
                    "position": len(payloads) + 1,
                    "kind_label": "小检测",
                    "topic_label": topic,
                    "prompt_format": surface["prompt_format"],
                    "prompt": prompt,
                    "prompt_segments": surface["prompt_segments"],
                    "child_surface_projection_sha256": surface["projection_sha256"],
                    "answer_input_mode": "text_photo",
                    "allowed_response_modes": ["text", "photo", "text_photo", "stuck"],
                    "upload_enabled": True,
                    "stuck_enabled": True,
                    "state": "selected",
                    "support": {"hint": "按你平时的方式完成，系统会根据过程判断下一步。"},
                    "interaction_schema": surface["interaction_schema"],
                    "interaction_rendering": surface["interaction_rendering"],
                },
                "_audit": {
                    "question_id": question["id"],
                    "node_id": question["node_id"],
                    "prompt_preview": prompt[:120],
                },
            }
        )
    return payloads


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_text(text: str, *, label: str, issues: list[str]) -> None:
    if FORBIDDEN_CHILD_SURFACE.search(text or ""):
        issues.append(f"{label}: child surface leaks internal terms")
    if ENGLISH_FEEDBACK.search(text or ""):
        issues.append(f"{label}: child surface contains English feedback")


def _request_failure_text(req: Any) -> str:
    try:
        failure = req.failure
        if callable(failure):
            failure = failure()
        return str(failure or "")
    except Exception as exc:  # noqa: BLE001 - QA event logging must never break the run
        return f"failure_unavailable:{type(exc).__name__}"


def _start_static_app_server(payloads: list[dict[str, Any]], current: dict[str, int]) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler API
            return

        def _send_json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/child-bootstrap":
                if not payloads:
                    self._send_json({"error": "no payload"}, status=404)
                    return
                payload = {key: value for key, value in payloads[current["index"]].items() if key != "_audit"}
                self._send_json(payload)
                return
            if path == "/api/knowledge-map":
                self._send_json({"state": "disabled", "message": "题面扫描不打开知识首页。"}, status=404)
                return
            file_path = APP_ROOT / ("index.html" if path == "/" else path.lstrip("/"))
            try:
                resolved = file_path.resolve()
            except OSError:
                self.send_error(404)
                return
            if not str(resolved).startswith(str(APP_ROOT.resolve())) or not resolved.is_file():
                self.send_error(404)
                return
            content = resolved.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{mimetypes.guess_type(str(resolved))[0] or 'text/plain'}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = __import__("threading").Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    return httpd, f"http://{host}:{port}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast Guanzhi browser render audit for every child-eligible question.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-questions", type=int, default=0)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    if args.shard_count < 1:
        parser.error("--shard-count must be >= 1")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        parser.error("--shard-index must satisfy 0 <= index < shard-count")

    source_db = Path(args.db).resolve()
    source_stat = source_db.stat()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output_dir).resolve() / stamp
    output_dir.mkdir(parents=True, exist_ok=True)

    issues: list[str] = []
    sampled: list[dict[str, Any]] = []
    target_count = 0
    with tempfile.TemporaryDirectory(prefix="guanzhi-question-surface-") as tmp:
        db_path = Path(tmp) / "surface.sqlite"
        shutil.copy2(source_db, db_path)
        with closing(db.connect(db_path)) as conn:
            db.init_schema(conn)
            payloads = _active_payloads(conn)
        eligible_count = len(payloads)
        if args.shard_count > 1:
            payloads = [
                payload
                for index, payload in enumerate(payloads)
                if index % args.shard_count == args.shard_index
            ]
        if args.max_questions:
            payloads = payloads[: args.max_questions]
        target_count = len(payloads)
        if not payloads:
            issues.append("no child-eligible active questions")

        current = {"index": 0}
        httpd, base_url = _start_static_app_server(payloads, current)
        try:
            with sync_playwright() as playwright:
                launch_kwargs: dict[str, Any] = {"headless": not args.headed}
                chrome_path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                if chrome_path.exists():
                    launch_kwargs["executable_path"] = str(chrome_path)
                browser = playwright.chromium.launch(**launch_kwargs)
                context = browser.new_context(viewport={"width": 390, "height": 844})
                context.add_init_script("window.localStorage.clear(); window.sessionStorage.clear();")
                page = context.new_page()
                browser_events: list[str] = []
                page.on("console", lambda msg: browser_events.append(f"console:{msg.type}:{msg.text}"))
                page.on("pageerror", lambda exc: browser_events.append(f"pageerror:{exc}"))
                page.on(
                    "requestfailed",
                    lambda req: browser_events.append(
                        f"requestfailed:{req.url}:{_request_failure_text(req)}"
                    ),
                )
                for index, payload in enumerate(payloads):
                    current["index"] = index
                    page.goto(base_url, wait_until="domcontentloaded")
                    resume = page.locator("[data-resume-learning]:visible")
                    if resume.count() >= 1:
                        resume.first.click()
                    try:
                        page.wait_for_function(
                            "() => window.ChildLearningShell?.currentState?.() === 'current_step'",
                            timeout=5000,
                        )
                        page.wait_for_selector("#childAttemptForm:not([hidden])", timeout=5000)
                        page.wait_for_selector("[data-child-prompt]", timeout=5000)
                    except PlaywrightTimeoutError:
                        page.screenshot(
                            path=str(output_dir / f"question-{index + 1:03d}-render-failed.png"),
                            full_page=False,
                        )
                        diagnostics = page.evaluate(
                            """() => ({
                              readyState: document.readyState,
                              currentState: window.ChildLearningShell?.currentState?.() || null,
                              bodyText: document.body?.innerText || '',
                              dbStatus: document.querySelector('#dbStatus')?.textContent || '',
                              heading: document.querySelector('#childHeading')?.textContent || '',
                              errorTitle: document.querySelector('#childErrorTitle')?.textContent || '',
                              errorBody: document.querySelector('#childErrorBody')?.textContent || ''
                            })"""
                        )
                        issues.append(f"{payload['_audit']['question_id']}: did not render current_step")
                        issues.append(
                            f"{payload['_audit']['question_id']}: render diagnostics="
                            f"{json.dumps(diagnostics, ensure_ascii=False)[:800]}"
                        )
                        if browser_events:
                            issues.append(
                                f"{payload['_audit']['question_id']}: browser events="
                                f"{json.dumps(browser_events[-20:], ensure_ascii=False)[:800]}"
                            )
                        continue
                    visible = page.evaluate(
                        """() => ({
                          heading: document.querySelector('#childHeading')?.textContent || '',
                          type: document.querySelector('#childTaskType')?.textContent || '',
                          prompt: document.querySelector('#childTaskContent')?.textContent || '',
                          formVisible: Boolean(document.querySelector('#childAttemptForm')?.offsetParent),
                          submitVisible: Boolean(document.querySelector('#childSubmitBtn')?.offsetParent),
                          interactionText: document.querySelector('#interactionAnswerPanel')?.textContent || ''
                        })"""
                    )
                    rendered_text = " ".join(str(value or "") for value in visible.values())
                    _safe_text(rendered_text, label=payload["_audit"]["question_id"], issues=issues)
                    if not str(visible.get("prompt") or "").strip():
                        issues.append(f"{payload['_audit']['question_id']}: empty prompt")
                    if not visible.get("formVisible") or not visible.get("submitVisible"):
                        issues.append(f"{payload['_audit']['question_id']}: missing answer form or submit")
                    if index < 3:
                        page.screenshot(path=str(output_dir / f"question-{index + 1:03d}.png"), full_page=False)
                    if index % 100 == 0 and index:
                        print(f"surface_render_progress={index}/{len(payloads)}", flush=True)
                    sampled.append(payload["_audit"])
                context.close()
                browser.close()
        finally:
            httpd.shutdown()
            httpd.server_close()

    report = {
        "schema_version": "guanzhi-question-surface-fast.v1",
        "coverage_scope": "synthetic_bootstrap_browser_render_only",
        "status": "PASS" if not issues else "NEEDS_FIX",
        "command": " ".join([sys.executable, *sys.argv]),
        "args": vars(args),
        "source_db": str(source_db),
        "source_db_sha256": _sha256_file(source_db),
        "source_db_mtime": source_stat.st_mtime,
        "output_dir": str(output_dir),
        "target_question_count": target_count,
        "eligible_question_count": eligible_count,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "success_question_count": len(sampled),
        "failure_question_count": target_count - len(sampled),
        "rendered_question_count": len(sampled),
        "sampled": sampled[:12],
        "issues": issues[:200],
        "issue_count": len(issues),
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
