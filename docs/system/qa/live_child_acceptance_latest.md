# Live Child Acceptance QA

- Generated: 2026-07-07T15:01:37+00:00
- Verdict: `LIVE_ACCEPTANCE_NEEDS_FIX`
- Target base URL: `http://127.0.0.1:8765`
- DB path: `data/local_learning_system.sqlite`
- Model mode: `live_config_observed_not_mutated`
- Patches active: `False`
- Write real submission: `False`

## Issues

- real child-submission acceptance was not run; use --write-real-submission only when mutating the real learning ledger is acceptable

## Evidence

```json
{
  "target_base_url": "http://127.0.0.1:8765",
  "db_path": "data/local_learning_system.sqlite",
  "model_mode": "live_config_observed_not_mutated",
  "patches_active": false,
  "write_real_submission": false,
  "server": {
    "lsof": "COMMAND   PID     USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\nPython  81688 liuchang    4u  IPv4 0x913374f7c111ba93      0t0  TCP 127.0.0.1:8765 (LISTEN)",
    "ps": "81688 81687 /opt/homebrew/Cellar/python@3.13/3.13.11/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python -m learning_system.server --db data/local_learning_system.sqlite --port 8765"
  },
  "child_bootstrap_status": 200,
  "child_bootstrap": {
    "task_count": 10,
    "learning_group_state": "not_started",
    "plan_key": "172899660a7f9605"
  },
  "db": {
    "latest_session": {
      "id": "S-763b10075273",
      "status": "closed",
      "closure_status": "planned",
      "created_at": "2026-07-07T14:20:10.674828+00:00",
      "closed_at": "2026-07-07T14:20:52.383154+00:00"
    },
    "daily_summary": {
      "child_learning_sessions": 8,
      "pending_attempts": 0,
      "missing_answer_analysis": 0,
      "recent_evolution_events": 46,
      "latest_pipeline_completeness": "complete",
      "question_quality_issues": 0,
      "lineage_integrity_issues": 0,
      "question_bank_version": "2026-07-07.bank.v8",
      "current_practice_questions": 1120,
      "current_practice_nodes": 56,
      "current_practice_min_per_node": 20,
      "current_practice_max_per_node": 20
    },
    "lineage_issue_count": 0,
    "lineage_issues": [],
    "active_background_jobs": {},
    "active_pending_attempts": 0
  },
  "daily_latest": {
    "path": "/Users/liuchang/Documents/gitproject/son-ai-learning-system/docs/system/daily_reports/latest.md",
    "generated_at": "2026-07-07T15:01:36+00:00"
  }
}
```
