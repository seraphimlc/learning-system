#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, reports


DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_DB_PATH = PROJECT_ROOT / "data/local_learning_system.sqlite"
DEFAULT_REPORT = PROJECT_ROOT / "docs/system/qa/live_child_acceptance_latest.md"


def request_json(method: str, base_url: str, path: str, payload: dict | None = None, timeout: float = 20.0) -> dict:
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


def command_output(args: list[str]) -> str:
    result = subprocess.run(args, cwd=PROJECT_ROOT, text=True, capture_output=True, check=False)
    return (result.stdout + result.stderr).strip()


def server_db_evidence() -> dict:
    lsof = command_output(["lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN"])
    pid = ""
    for line in lsof.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            pid = parts[1]
            break
    ps = ""
    if pid:
        ps = command_output(["ps", "-p", pid, "-o", "pid=,ppid=,command="])
    return {"lsof": lsof, "ps": ps}


def parse_generated_at(report_path: Path) -> datetime | None:
    if not report_path.exists():
        return None
    match = re.search(r"Generated UTC: `([^`]+)`", report_path.read_text(encoding="utf-8"))
    if not match:
        return None
    value = match.group(1)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def latest_session_row(conn) -> dict | None:
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


def run_read_only_checks(base_url: str, db_path: Path) -> tuple[list[str], dict]:
    issues: list[str] = []
    evidence: dict = {
        "target_base_url": base_url,
        "db_path": str(db_path),
        "model_mode": "live_config_observed_not_mutated",
        "patches_active": False,
        "write_real_submission": False,
    }

    if base_url != DEFAULT_BASE_URL:
        issues.append(f"target base URL must be {DEFAULT_BASE_URL}; got {base_url}")
    if db_path.resolve() != DEFAULT_DB_PATH.resolve():
        issues.append(f"DB path must be {DEFAULT_DB_PATH}; got {db_path}")

    server_evidence = server_db_evidence()
    evidence["server"] = server_evidence
    db_hint = str(db_path)
    relative_db_hint = str(db_path.resolve().relative_to(PROJECT_ROOT)) if db_path.resolve().is_relative_to(PROJECT_ROOT) else db_hint
    if db_hint not in server_evidence.get("ps", "") and relative_db_hint not in server_evidence.get("ps", ""):
        issues.append("running server command does not prove it is using data/local_learning_system.sqlite")

    bootstrap = request_json("GET", base_url, "/api/child-bootstrap")
    evidence["child_bootstrap_status"] = bootstrap["status"]
    if bootstrap["status"] >= 400:
        issues.append(f"/api/child-bootstrap returned {bootstrap['status']}: {bootstrap['raw'][:300]}")
    else:
        payload = bootstrap["payload"]
        evidence["child_bootstrap"] = {
            "task_count": len(payload.get("today_plan", {}).get("tasks", [])),
            "learning_group_state": payload.get("learning_group", {}).get("state"),
            "plan_key": payload.get("today_plan", {}).get("plan_key"),
        }
        serialized = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("agent_key", "session_id", "attempt_id", "model_name", "model_provider", "Codex"):
            if forbidden in serialized:
                issues.append(f"child bootstrap leaks internal term `{forbidden}`")

    with db.connect(db_path) as conn:
        latest_session = latest_session_row(conn)
        daily = reports.generate_daily_report(conn)
        lineage = db.lineage_integrity_audit(conn)
        active_jobs = {
            row["status"]: row["n"]
            for row in conn.execute(
                """
                select status, count(*) as n
                from background_jobs
                where status in ('queued', 'running', 'waiting', 'error')
                group by status
                """
            ).fetchall()
        }
        pending_attempts = conn.execute(
            "select count(*) from attempts where grading_status = 'pending_review' and evidence_status = 'active'"
        ).fetchone()[0]
        evidence["db"] = {
            "latest_session": {
                "id": latest_session["id"] if latest_session else "",
                "status": latest_session["status"] if latest_session else "",
                "closure_status": latest_session["closure_status"] if latest_session else "",
                "created_at": latest_session["created_at"] if latest_session else "",
                "closed_at": latest_session.get("closed_at") if latest_session else "",
            },
            "daily_summary": daily["summary"],
            "lineage_issue_count": lineage["issue_count"],
            "lineage_issues": lineage.get("issues", [])[:8],
            "active_background_jobs": active_jobs,
            "active_pending_attempts": pending_attempts,
        }
        if active_jobs:
            issues.append(f"active/unfinished background jobs remain: {active_jobs}")
        if pending_attempts:
            issues.append(f"{pending_attempts} active attempts are still pending_review")
        if lineage["issue_count"]:
            issues.append(f"lineage integrity issue_count is {lineage['issue_count']}")
        if latest_session and latest_session["closure_status"] not in {"planned", "blocked"}:
            issues.append(f"latest child session closure_status is {latest_session['closure_status']}")

    daily_latest = PROJECT_ROOT / "docs/system/daily_reports/latest.md"
    generated_at = parse_generated_at(daily_latest)
    evidence["daily_latest"] = {
        "path": str(daily_latest),
        "generated_at": generated_at.isoformat() if generated_at else "",
    }
    latest_closed_at = evidence.get("db", {}).get("latest_session", {}).get("closed_at")
    if generated_at and latest_closed_at:
        try:
            closed_at = datetime.fromisoformat(str(latest_closed_at).replace("Z", "+00:00"))
            if generated_at < closed_at:
                issues.append("docs/system/daily_reports/latest.md is older than the latest closed child session")
        except ValueError:
            issues.append(f"latest session closed_at is not parseable: {latest_closed_at}")
    elif not generated_at:
        issues.append("docs/system/daily_reports/latest.md has no parseable Generated UTC timestamp")

    return issues, evidence


def run_real_submission(base_url: str, timeout_seconds: float) -> tuple[list[str], dict]:
    issues: list[str] = []
    evidence: dict = {"write_real_submission": True}
    bootstrap = request_json("GET", base_url, "/api/child-bootstrap")
    if bootstrap["status"] >= 400:
        return [f"cannot start real submission; bootstrap returned {bootstrap['status']}"], evidence
    tasks = bootstrap["payload"].get("today_plan", {}).get("tasks", [])
    evidence["submitted_task_count"] = len(tasks)
    for task in tasks:
        prompt = task.get("question", {}).get("prompt", "")
        answer = (
            "我先读题，写出要证明或计算的关系；再列关键步骤；最后用代入、估算或单位检查。"
            f" 针对这题：{prompt[:80]}。"
        )
        response = request_json("POST", base_url, "/api/child-submissions", {
            "session_handle": "current-learning-group",
            "task_position": task["position"],
            "answer_raw": answer,
        }, timeout=timeout_seconds)
        if response["status"] >= 400:
            issues.append(f"submission task {task['position']} returned {response['status']}: {response['raw'][:300]}")
            break
    deadline = time.time() + timeout_seconds
    close = request_json("POST", base_url, "/api/learning-sessions/current-learning-group/complete", {}, timeout=timeout_seconds)
    while close["status"] < 400 and close["payload"].get("closure_status") == "waiting_ai" and time.time() < deadline:
        time.sleep(2)
        close = request_json("POST", base_url, "/api/learning-sessions/current-learning-group/complete", {}, timeout=timeout_seconds)
    evidence["close_status"] = close["status"]
    evidence["close_payload"] = close["payload"]
    if close["status"] >= 400:
        issues.append(f"completion returned {close['status']}: {close['raw'][:300]}")
    elif close["payload"].get("closure_status") != "planned":
        issues.append(f"real submission did not reach planned; got {close['payload'].get('closure_status')}")
    return issues, evidence


def render_report(verdict: str, issues: list[str], evidence: dict) -> str:
    lines = [
        "# Live Child Acceptance QA",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Verdict: `{verdict}`",
        f"- Target base URL: `{evidence.get('target_base_url', DEFAULT_BASE_URL)}`",
        f"- DB path: `{evidence.get('db_path', DEFAULT_DB_PATH)}`",
        f"- Model mode: `{evidence.get('model_mode', '')}`",
        f"- Patches active: `{evidence.get('patches_active', False)}`",
        f"- Write real submission: `{evidence.get('write_real_submission', False)}`",
        "",
        "## Issues",
        "",
    ]
    lines.extend([f"- {issue}" for issue in issues] or ["- None"])
    lines.extend(["", "## Evidence", "", "```json", json.dumps(evidence, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live acceptance checks for the current child learning system.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--write-real-submission", action="store_true", help="Mutates the real learning ledger through the child page/API.")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()

    db_path = Path(args.db)
    issues, evidence = run_read_only_checks(args.base_url, db_path)
    if args.write_real_submission:
        write_issues, write_evidence = run_real_submission(args.base_url, args.timeout_seconds)
        issues.extend(write_issues)
        evidence["real_submission"] = write_evidence
        evidence["write_real_submission"] = True
    else:
        issues.append("real child-submission acceptance was not run; use --write-real-submission only when mutating the real learning ledger is acceptable")

    verdict = "LIVE_ACCEPTANCE_PASS" if not issues and args.write_real_submission else "LIVE_ACCEPTANCE_NEEDS_FIX"
    report = render_report(verdict, issues, evidence)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(report_path)
    if issues:
        for issue in issues:
            print(issue)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
