#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from learning_system import daily_runtime, db, knowledge_map, server


DEFAULT_DB = PROJECT_ROOT / "data/local_learning_system.sqlite"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts/guanzhi-browser-regression"
V51_BROWSER_ENV = {
    "V3_DAILY_RUNTIME_ENABLED": "1",
    "KNOWLEDGE_MAP_HOME_POLICY": "v5.1",
    "ANSWER_ASSESSMENT_POLICY": "v5.1",
    "V5_DAILY_FLOW_WORKER_MAX_JOBS": "50",
    "AI_BACKGROUND_REVIEW_CONCURRENCY": "4",
}
FORBIDDEN_CHILD_SURFACE = re.compile(
    r"node_id|graph_version|question_id|attempt_id|flow_id|job_id|provider|rubric|"
    r"queue|agent_run|candidate_packet|expected_answer|response_schema|api_key",
    re.IGNORECASE,
)
ENGLISH_FEEDBACK = re.compile(
    r"\b(Missing|Add one sentence|Briefly state|The calculation|correct but|"
    r"wrong because|gap|improvement|standard answer)\b"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _open_conn(path: Path) -> sqlite3.Connection:
    conn = db.connect(path)
    db.init_schema(conn)
    return conn


def _active_question_assets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select qi.*, ac.id as answer_contract_id, ac.contract_version,
               ac.contract_digest_sha256, ac.review_record_id,
               ac.graph_version as contract_graph_version,
               ac.question_bank_version as contract_question_bank_version,
               ac.reference_solution_json, ac.score_points_json
        from answer_contracts ac
        join question_items qi
          on qi.id = ac.question_id and qi.item_version = ac.item_version
        where ac.status = 'active'
        order by qi.node_id, qi.id
        """
    ).fetchall()
    assets: list[dict[str, Any]] = []
    for row in rows:
        raw = _json_row(row)
        question_row = {key: raw[key] for key in raw.keys() if key in {
            "id",
            "item_version",
            "source_type",
            "node_id",
            "secondary_node_ids_json",
            "kind",
            "question_type",
            "variant_level",
            "prompt",
            "answer_format",
            "expected_answer",
            "rubric_json",
            "solution_steps_json",
            "error_tags_json",
            "rollback_candidate_node_ids_json",
            "rollback_candidate_relations_json",
            "estimated_minutes",
            "parent_observation",
            "source_json",
            "created_by_event_id",
            "raw_json",
        }}
        question = db.row_to_question(question_row)
        review_record_id = str(raw.get("review_record_id") or "")
        bank_version = str(raw.get("contract_question_bank_version") or question.get("item_version") or "")
        if not (
            db.is_child_schedulable_question(conn, question, question_bank_version=bank_version)
            and db.question_review_record_allows_active_use(conn, question, review_record_id)
        ):
            continue
        assets.append({
            "question": question,
            "node_id": str(question.get("node_id") or ""),
            "question_id": str(question.get("id") or ""),
            "review_record_id": review_record_id,
            "answer_contract": {
                "id": raw.get("answer_contract_id"),
                "contract_version": int(raw.get("contract_version") or 1),
                "contract_digest_sha256": raw.get("contract_digest_sha256"),
                "reference_solution": db.json_load(raw.get("reference_solution_json"), {}),
                "score_points": db.json_load(raw.get("score_points_json"), []),
            },
            "graph_version": str(raw.get("contract_graph_version") or question.get("graph_version") or ""),
            "question_bank_version": bank_version,
        })
    return assets


def _clear_learning_state(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("pragma foreign_keys = off")
        for table in (
            "daily_summaries",
            "next_step_decisions",
            "mastery_decisions",
            "evidence_validations",
            "background_jobs",
            "attempt_attachments",
            "attempts",
            "flow_steps",
            "daily_flows",
            "learning_target_intents",
            "learning_sessions",
        ):
            try:
                conn.execute(f"delete from {table}")
            except sqlite3.OperationalError:
                pass
        conn.execute("pragma foreign_keys = on")


def _materialize_question_as_current_step(
    conn: sqlite3.Connection,
    asset: dict[str, Any],
    *,
    position: int,
    mini_group: bool = False,
    mini_group_size: int = 3,
) -> dict[str, Any]:
    _clear_learning_state(conn)
    runtime = daily_runtime.DailyLearningRuntime(conn, project_root=PROJECT_ROOT)
    now = db.now_iso()
    session_id = f"LS-guanzhi-{uuid.uuid4().hex[:10]}"
    flow_id = f"DF-guanzhi-{uuid.uuid4().hex[:10]}"
    with conn:
        conn.execute(
            "insert into learning_sessions(id, title, mode, status, created_at) "
            "values (?, 'guanzhi browser question render', 'daily_flow_v3', 'active', ?)",
            (session_id, now),
        )
        conn.execute(
            """
            insert into daily_flows(
              id, child_key, local_date, mode, status, current_step_id,
              graph_version, question_bank_version, legacy_session_id,
              assessment_policy_version, created_at, updated_at
            ) values (?, ?, ?, 'review_old_knowledge', 'reviewing', null,
                      ?, ?, ?, 'v5.1', ?, ?)
            """,
            (
                flow_id,
                db.V3_DEFAULT_CHILD_KEY,
                date.today().isoformat(),
                asset["graph_version"],
                asset["question_bank_version"],
                session_id,
                now,
                now,
            ),
        )
        selection_reason = {
            "reason": "guanzhi_browser_regression_every_active_question",
            "question_id": asset["question_id"],
        }
        if mini_group:
            flow = conn.execute("select * from daily_flows where id = ?", (flow_id,)).fetchone()
            selection_reason = runtime._mini_group_selection_reason(
                selection_reason,
                flow=flow,
                step_type="question",
                group_role="review_short_set",
                group_size=mini_group_size,
                target_node_id=str(asset["node_id"] or ""),
            )
        step_id = runtime._create_question_step(
            flow_id=flow_id,
            position=position,
            graph_version=asset["graph_version"],
            question=asset["question"],
            review_record_id=asset["review_record_id"],
            selection_reason=selection_reason,
            candidate_packet={"packet_id": f"guanzhi-render-{position}"},
            support_hint="先完成当前这一步。",
            step_type="question",
            answer_input_mode=None,
            initial_status="selected",
            answer_contract=asset["answer_contract"],
        )
        conn.execute(
            "update daily_flows set current_step_id = ?, updated_at = ? where id = ?",
            (step_id, now, flow_id),
        )
    return {"flow_id": flow_id, "session_id": session_id, "step_id": step_id}


def _request_json(page, path: str) -> dict[str, Any]:
    return page.evaluate(
        """async (path) => {
          const response = await fetch(path);
          let payload = {};
          try { payload = await response.json(); } catch (_) {}
          return {status: response.status, payload};
        }""",
        path,
    )


def _current_browser_diagnostics(page) -> dict[str, Any]:
    return page.evaluate(
        """() => ({
          readyState: document.readyState,
          currentState: window.ChildLearningShell?.currentState?.() || null,
          bodyText: (document.body?.innerText || '').slice(0, 1200),
          dbStatus: document.querySelector('#dbStatus')?.textContent || '',
          heading: document.querySelector('#childHeading')?.textContent || '',
          knowledgeHidden: document.querySelector('#view-knowledge-home')?.hidden ?? null,
          childHidden: document.querySelector('#view-child')?.hidden ?? null,
          promptText: document.querySelector('[data-child-prompt]')?.textContent || '',
          formHidden: document.querySelector('#childAttemptForm')?.hidden ?? null,
          answerDisabled: document.querySelector('#childAnswerRaw')?.disabled ?? null,
          submitDisabled: document.querySelector('#childSubmitBtn')?.disabled ?? null,
          formOffsetParent: Boolean(document.querySelector('#childAttemptForm')?.offsetParent),
          submitOffsetParent: Boolean(document.querySelector('#childSubmitBtn')?.offsetParent)
        })"""
    )


def _ensure_current_step_surface(page, *, timeout_ms: int = 15000) -> bool:
    deadline = time.perf_counter() + (timeout_ms / 1000)
    clicked_resume = False
    while time.perf_counter() < deadline:
        try:
            current_state = page.evaluate("() => window.ChildLearningShell?.currentState?.() || ''")
        except Exception:  # noqa: BLE001 - browser may still be navigating
            current_state = ""
        if current_state == "current_step":
            return True
        resume = page.locator("[data-resume-learning]:visible")
        try:
            if resume.count() >= 1:
                resume.first.click()
                clicked_resume = True
        except Exception:
            pass
        page.wait_for_timeout(250 if clicked_resume else 150)
    return False


def _current_step_answer_surface_ready(page) -> bool:
    return bool(page.evaluate(
        """() => {
          const prompt = document.querySelector('[data-child-prompt]');
          const form = document.querySelector('#childAttemptForm');
          const answer = document.querySelector('#childAnswerRaw');
          const submit = document.querySelector('#childSubmitBtn');
          return window.ChildLearningShell?.currentState?.() === 'current_step'
            && Boolean(prompt?.textContent?.trim())
            && Boolean(form)
            && form.hidden === false
            && Boolean(answer)
            && answer.disabled === false
            && Boolean(submit)
            && submit.disabled === false;
        }"""
    ))


def _wait_for_current_step_answer_surface(page, *, timeout_ms: int = 15000) -> bool:
    deadline = time.perf_counter() + (timeout_ms / 1000)
    while time.perf_counter() < deadline:
        if _ensure_current_step_surface(page, timeout_ms=1000) and _current_step_answer_surface_ready(page):
            return True
        page.wait_for_timeout(200)
    return _current_step_answer_surface_ready(page)


def _child_safe_text(text: str, *, context: str, issues: list[str]) -> None:
    if FORBIDDEN_CHILD_SURFACE.search(text or ""):
        issues.append(f"{context}: child surface leaks internal terms")
    if ENGLISH_FEEDBACK.search(text or ""):
        issues.append(f"{context}: child surface contains English feedback")


def _knowledge_home_browser_audit(page, *, output_dir: Path) -> dict[str, Any]:
    issues: list[str] = []
    page.reload(wait_until="networkidle")
    try:
        page.wait_for_selector("#knowledgeHomeBtn:not([hidden])", timeout=15000)
        page.locator("#knowledgeHomeBtn").click()
        page.wait_for_selector("#view-knowledge-home:not([hidden])", timeout=15000)
        page.wait_for_selector("[data-knowledge-home]", timeout=15000)
    except PlaywrightTimeoutError:
        issues.append("knowledge home did not open from the child shell")
        return {
            "status": "NEEDS_FIX",
            "node_count": 0,
            "rendered_node_count": 0,
            "clicked_node_count": 0,
            "issues": issues,
            "issue_count": len(issues),
        }
    projection_result = _request_json(page, "/api/knowledge-map")
    projection = projection_result["payload"]
    nodes = projection.get("nodes") if isinstance(projection.get("nodes"), list) else []
    if projection_result["status"] != 200:
        issues.append(f"knowledge-map status={projection_result['status']}")
    if len(nodes) < 50:
        issues.append(f"knowledge-map exposes too few child nodes: {len(nodes)}")
    body_text = page.locator("body").inner_text(timeout=5000)
    _child_safe_text(body_text, context="knowledge-home", issues=issues)
    if "图谱" in body_text:
        issues.append("knowledge home still shows graph wording")
    if "学习流程与错因" in body_text or "解题步骤与检验习惯" in body_text:
        issues.append("knowledge home exposes internal process module")
    page.screenshot(path=str(output_dir / "knowledge-home-initial.png"), full_page=False)

    explorer_button = page.locator("[data-map-explorer-toggle]:visible")
    explorer_body = page.locator("[data-map-explorer-body]")
    body_hidden = explorer_body.count() == 0 or explorer_body.first.evaluate("el => el.hidden")
    if explorer_button.count() >= 1 and body_hidden:
        explorer_button.first.click()
    page.wait_for_selector("[data-map-explorer-body]:not([hidden])", timeout=15000)
    page.wait_for_selector('[aria-label="我的数学知识目录"]:visible', timeout=15000)
    rendered_buttons = page.locator(".knowledge-node-button")
    rendered_count = rendered_buttons.count()
    if rendered_count != len(nodes):
        issues.append(f"browser rendered {rendered_count} nodes, API exposed {len(nodes)} nodes")

    clicked = 0
    for node in nodes:
        handle = str(node.get("handle") or "")
        name = str(node.get("name") or "")
        if not handle:
            issues.append(f"{name or '<unnamed>'}: missing opaque handle")
            continue
        button = page.locator(f'.knowledge-node-button[data-node-handle="{handle}"]')
        if button.count() != 1:
            issues.append(f"{name}: node button count={button.count()}")
            continue
        button.click()
        page.wait_for_selector("[data-knowledge-detail]:not([hidden])", timeout=5000)
        detail_text = page.locator("[data-knowledge-detail]").inner_text(timeout=5000)
        if name and name not in detail_text:
            issues.append(f"{name}: detail panel did not preserve selected node")
        _child_safe_text(detail_text, context=f"knowledge-detail:{name}", issues=issues)
        actions = node.get("action_descriptors") if isinstance(node.get("action_descriptors"), list) else []
        if not actions:
            issues.append(f"{name}: no action descriptors")
        clicked += 1
    page.screenshot(path=str(output_dir / "knowledge-home-after-node-scan.png"), full_page=False)
    return {
        "status": "PASS" if not issues else "NEEDS_FIX",
        "node_count": len(nodes),
        "rendered_node_count": rendered_count,
        "clicked_node_count": clicked,
        "issues": issues[:100],
        "issue_count": len(issues),
    }


def _question_render_browser_audit(
    conn: sqlite3.Connection,
    page,
    assets: list[dict[str, Any]],
    *,
    output_dir: Path,
    max_questions: int | None,
    shard_index: int,
    shard_count: int,
) -> dict[str, Any]:
    issues: list[str] = []
    sampled: list[dict[str, Any]] = []
    success_count = 0
    if shard_count > 1:
        target_assets = [
            asset
            for index, asset in enumerate(assets)
            if index % shard_count == shard_index
        ]
    else:
        target_assets = list(assets)
    target_assets = target_assets[:max_questions] if max_questions else target_assets
    for index, asset in enumerate(target_assets, 1):
        try:
            materialized = _materialize_question_as_current_step(conn, asset, position=index)
        except Exception as exc:  # noqa: BLE001 - QA report needs exact failing question
            issues.append(f"{asset['question_id']}: failed to materialize current step: {type(exc).__name__}: {exc}")
            continue
        page.reload(wait_until="domcontentloaded")
        reached_current_step = _wait_for_current_step_answer_surface(page, timeout_ms=15000)
        if not reached_current_step:
            state = _request_json(page, "/api/child-bootstrap")
            page.screenshot(path=str(output_dir / f"question-render-{index:03d}-failed.png"), full_page=False)
            issues.append(
                f"{asset['question_id']}: browser did not reach current_step; "
                f"bootstrap={state}; diagnostics={_current_browser_diagnostics(page)}"
            )
            continue
        state = _request_json(page, "/api/child-bootstrap")
        payload = state["payload"]
        current = payload.get("current_step") if isinstance(payload.get("current_step"), dict) else {}
        visible = page.evaluate(
            """() => ({
              state: window.ChildLearningShell?.currentState?.(),
              heading: document.querySelector('#childHeading')?.textContent || '',
              type: document.querySelector('#childTaskType')?.textContent || '',
              prompt: document.querySelector('#childTaskContent')?.textContent || '',
              answerPanel: document.querySelector('#interactionAnswerPanel')?.textContent || '',
              formVisible: Boolean(document.querySelector('#childAttemptForm')?.offsetParent),
              submitVisible: Boolean(document.querySelector('#childSubmitBtn')?.offsetParent),
            })"""
        )
        text = " ".join(str(visible.get(key) or "") for key in visible)
        _child_safe_text(text, context=f"question-render:{asset['question_id']}", issues=issues)
        _child_safe_text(json.dumps(payload, ensure_ascii=False), context=f"question-bootstrap:{asset['question_id']}", issues=issues)
        if state["status"] != 200 or payload.get("child_state") != "current_step":
            issues.append(f"{asset['question_id']}: bootstrap status/state invalid: {state['status']} {payload.get('child_state')}")
        if current.get("topic_label") != visible.get("heading"):
            issues.append(
                f"{asset['question_id']}: heading mismatch payload={current.get('topic_label')} visible={visible.get('heading')}"
            )
        if not str(visible.get("prompt") or "").strip():
            issues.append(f"{asset['question_id']}: empty visible prompt")
        if not visible.get("formVisible") or not visible.get("submitVisible"):
            issues.append(f"{asset['question_id']}: answer form or submit button hidden")
        if index <= 3:
            page.screenshot(path=str(output_dir / f"question-render-{index:03d}.png"), full_page=False)
        success_count += 1
        sampled.append({
            "question_id": asset["question_id"],
            "node_id": asset["node_id"],
            "flow_id": materialized["flow_id"],
            "step_id": materialized["step_id"],
            "topic": current.get("topic_label"),
            "prompt_preview": str(current.get("prompt") or "")[:120],
        })
        if index % 100 == 0:
            print(f"question_render_progress={index}/{len(target_assets)}", flush=True)
    return {
        "status": "PASS" if not issues else "NEEDS_FIX",
        "eligible_active_question_count": len(assets),
        "target_question_count": len(target_assets),
        "success_question_count": success_count,
        "failure_question_count": len(target_assets) - success_count,
        "rendered_question_count": success_count,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "sampled": sampled[:12],
        "issues": issues[:200],
        "issue_count": len(issues),
    }


def _submit_scenarios_browser_audit(
    conn: sqlite3.Connection,
    page,
    assets: list[dict[str, Any]],
    *,
    output_dir: Path,
) -> dict[str, Any]:
    issues: list[str] = []
    scenarios = [
        ("stuck_text", "我不会", {
            "expected_states": {"feedback_teaching", "teaching", "assessment_feedback", "blocked"},
            "expected_review_status": "support_requested",
            "mini_group": False,
            "max_elapsed": 5,
        }),
        ("mini_group_answer", "3.456", {
            "expected_states": {"current_step"},
            "expected_review_status": "deferred_until_group_end",
            "mini_group": True,
            "max_elapsed": 5,
        }),
    ]
    observed: list[dict[str, Any]] = []
    for index, (name, answer, spec) in enumerate(scenarios, 1):
        if not assets:
            issues.append(f"{name}: no active question available for submit scenario")
            continue
        materialized = _materialize_question_as_current_step(
            conn,
            assets[(index - 1) % len(assets)],
            position=index,
            mini_group=bool(spec.get("mini_group")),
        )
        before_attempt_count = int(conn.execute("select count(*) from attempts").fetchone()[0])
        before_job_count = int(conn.execute("select count(*) from background_jobs").fetchone()[0])
        page.reload(wait_until="domcontentloaded")
        reached_current_step = _wait_for_current_step_answer_surface(page, timeout_ms=15000)
        if not reached_current_step:
            page.screenshot(path=str(output_dir / f"submit-scenario-{index}-{name}-start-failed.png"), full_page=False)
            issues.append(f"{name}: cannot start from current_step; diagnostics={_current_browser_diagnostics(page)}")
            continue
        before_bootstrap = _request_json(page, "/api/child-bootstrap")
        before_step = before_bootstrap.get("payload", {}).get("current_step") if isinstance(before_bootstrap.get("payload"), dict) else {}
        before_step_handle = str((before_step or {}).get("step_handle") or "")
        page.locator("#childAnswerRaw").fill(answer)
        before = time.perf_counter()
        page.locator("#childSubmitBtn").click()
        try:
            page.wait_for_function(
                """(allowed) => allowed.includes(window.ChildLearningShell?.currentState?.())""",
                arg=list(spec["expected_states"]),
                timeout=20000,
            )
        except PlaywrightTimeoutError:
            issues.append(f"{name}: submit did not reach an expected state")
        elapsed = round(time.perf_counter() - before, 3)
        state = page.evaluate(
            """() => ({
              state: window.ChildLearningShell?.currentState?.(),
              text: document.body.innerText || ''
            })"""
        )
        _child_safe_text(state.get("text", ""), context=f"submit:{name}", issues=issues)
        if elapsed > float(spec.get("max_elapsed") or 20):
            issues.append(f"{name}: expected fast path within {spec.get('max_elapsed')}s, observed {elapsed}s")
        attempts = conn.execute(
            """
            select *
            from attempts
            where flow_step_id = ?
            order by created_at desc
            limit 2
            """,
            (materialized["step_id"],),
        ).fetchall()
        after_attempt_count = int(conn.execute("select count(*) from attempts").fetchone()[0])
        after_job_count = int(conn.execute("select count(*) from background_jobs").fetchone()[0])
        if after_attempt_count != before_attempt_count + 1:
            issues.append(f"{name}: expected exactly one new attempt, before={before_attempt_count}, after={after_attempt_count}")
        if len(attempts) != 1:
            issues.append(f"{name}: expected one attempt for submitted step, found={len(attempts)}")
            review_status = ""
        else:
            review_meta = db.json_load(attempts[0]["review_meta_json"], {})
            review_status = str(review_meta.get("status") or "")
            if review_status != spec.get("expected_review_status"):
                issues.append(
                    f"{name}: review_meta.status expected {spec.get('expected_review_status')}, got {review_status}"
                )
        if spec.get("mini_group"):
            after_bootstrap = _request_json(page, "/api/child-bootstrap")
            after_step = after_bootstrap.get("payload", {}).get("current_step") if isinstance(after_bootstrap.get("payload"), dict) else {}
            after_step_handle = str((after_step or {}).get("step_handle") or "")
            if state.get("state") == "current_step" and after_step_handle == before_step_handle:
                issues.append(f"{name}: stayed on the same current_step after submit")
            if after_job_count != before_job_count:
                issues.append(
                    f"{name}: expected no model job before group end, before_jobs={before_job_count}, after_jobs={after_job_count}"
                )
        observed.append({
            "scenario": name,
            "elapsed_seconds": elapsed,
            "state": state.get("state"),
            "attempt_delta": after_attempt_count - before_attempt_count,
            "job_delta": after_job_count - before_job_count,
            "review_status": review_status,
        })
        page.screenshot(path=str(output_dir / f"submit-scenario-{index}-{name}.png"), full_page=False)
    return {
        "status": "PASS" if not issues else "NEEDS_FIX",
        "observed": observed,
        "issues": issues,
        "issue_count": len(issues),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="观止 browser regression over knowledge nodes and active questions.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-questions", type=int, default=0, help="0 means every eligible active question")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--skip-knowledge-home", action="store_true")
    parser.add_argument("--skip-submit", action="store_true")
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
    with tempfile.TemporaryDirectory(prefix="guanzhi-browser-regression-") as tmp:
        temp_root = Path(tmp)
        test_db = temp_root / "learning-regression.sqlite"
        shutil.copy2(source_db, test_db)
        with closing(_open_conn(test_db)) as conn:
            _clear_learning_state(conn)
            assets = _active_question_assets(conn)
            if not assets:
                report = {
                    "status": "NEEDS_FIX",
                    "issues": ["no eligible active questions found"],
                    "output_dir": str(output_dir),
                }
                (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 1

            with patch.dict(os.environ, V51_BROWSER_ENV, clear=False):
                httpd, base_url = server.start_test_server(test_db)
                try:
                    with sync_playwright() as playwright:
                        launch_kwargs: dict[str, Any] = {"headless": not args.headed}
                        chrome_path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                        if chrome_path.exists():
                            launch_kwargs["executable_path"] = str(chrome_path)
                        browser = playwright.chromium.launch(**launch_kwargs)
                        try:
                            context = browser.new_context(viewport={"width": 1280, "height": 880})
                            page = context.new_page()
                            page.goto(base_url, wait_until="networkidle")
                            knowledge_result = (
                                {
                                    "status": "SKIPPED",
                                    "coverage_scope": "not_exercised",
                                    "node_count": 0,
                                    "rendered_node_count": 0,
                                    "clicked_node_count": 0,
                                    "issues": [],
                                    "issue_count": 0,
                                }
                                if args.skip_knowledge_home
                                else _knowledge_home_browser_audit(page, output_dir=output_dir)
                            )
                            question_result = _question_render_browser_audit(
                                conn,
                                page,
                                assets,
                                output_dir=output_dir,
                                max_questions=args.max_questions or None,
                                shard_index=args.shard_index,
                                shard_count=args.shard_count,
                            )
                            submit_result = (
                                {
                                    "status": "SKIPPED",
                                    "coverage_scope": "not_exercised",
                                    "issues": [],
                                    "issue_count": 0,
                                }
                                if args.skip_submit
                                else _submit_scenarios_browser_audit(conn, page, assets, output_dir=output_dir)
                            )
                            context.close()
                        finally:
                            browser.close()
                finally:
                    httpd.shutdown()
                    httpd.server_close()

    sections = {
        "knowledge_home": knowledge_result,
        "active_question_render": question_result,
        "submit_scenarios": submit_result,
    }
    issue_count = sum(int(section.get("issue_count") or 0) for section in sections.values())
    skipped_sections = [name for name, section in sections.items() if section.get("status") == "SKIPPED"]
    status = "NEEDS_FIX" if issue_count else ("PASS_WITH_SCOPE" if skipped_sections else "PASS")
    report = {
        "schema_version": "guanzhi-browser-regression.v1",
        "status": status,
        "coverage_scope": "real_browser_real_api_temp_db",
        "issue_count": issue_count,
        "skipped_sections": skipped_sections,
        "command": " ".join([sys.executable, *sys.argv]),
        "args": vars(args),
        "source_db": str(source_db),
        "source_db_sha256": _sha256_file(source_db),
        "source_db_mtime": source_stat.st_mtime,
        "output_dir": str(output_dir),
        "sections": sections,
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 观止浏览器回归报告",
        "",
        f"- Verdict: `{status}`",
        f"- Active questions rendered: `{question_result.get('success_question_count')}` / `{question_result.get('target_question_count')}` target, `{question_result.get('eligible_active_question_count')}` eligible",
        f"- Knowledge nodes clicked: `{knowledge_result.get('clicked_node_count')}` / `{knowledge_result.get('node_count')}`",
        f"- Issue count: `{issue_count}`",
        f"- Skipped sections: `{', '.join(skipped_sections) if skipped_sections else 'none'}`",
        f"- Output dir: `{output_dir}`",
        "",
        "## Issues",
    ]
    all_issues: list[str] = []
    for name, section in sections.items():
        for issue in section.get("issues") or []:
            all_issues.append(f"{name}: {issue}")
    lines.extend(f"- {issue}" for issue in all_issues[:200])
    if not all_issues:
        lines.append("- None")
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status in {"PASS", "PASS_WITH_SCOPE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
