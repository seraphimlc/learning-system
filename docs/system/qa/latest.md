# Learning System QA Status - 2026-07-13

Generated CST: `2026-07-13 16:37`

## Verdict

`PASS_WITH_SCOPE`

v5 child-only daily runtime is runnable for the main local product path. A fresh live-model child-flow check advanced from step 1 to step 2 without getting stuck in review. This does not activate the v12 live-generated question-bank pipeline yet.

## What Is Working

- Child page at `http://127.0.0.1:8765/` is served by the current code and local SQLite DB.
- Child can start or resume the v5 flow, receive one current step, submit text/photo/stuck, and see honest pending/blocked/teaching/summary states.
- Submit is asynchronous: attempts and attachments are saved first, then durable background jobs run the semantic DAG.
- Main DAG tests cover `answer_analysis -> evidence_validation -> evaluation_update -> planner_decision -> teaching_generation`.
- Same-day restart is fixed: after a completed summary, an explicit review start creates a new active flow instead of returning blocked.
- Child-safe browser smoke passes and scans for internal enum/provider/rubric/id leakage.
- The v5 runtime rejects stale/mock/pending/missing-lineage evidence for mastery and dependent next-step decisions.
- Daily reports now label blocked jobs on already-completed historical flows as `historical_terminal`, so old terminal evidence is not confused with a current child blocker.

## Verification Evidence

- `python3 -m py_compile learning_system/daily_runtime.py learning_system/reports.py scripts/build_math_question_bank_v12.py tests/test_learning_system.py`: passed.
- Focused same-day restart regression passed:
  - `test_v5_start_review_reuses_bootstrap_flow_when_day_key_has_suffix`
  - `test_v5_start_review_after_same_day_summary_creates_new_active_flow`
  - `test_v5_start_review_normalizes_client_day_key_to_local_date`
- `node --check tests/browser_smoke_learning_system.mjs`: passed.
- `node tests/browser_smoke_learning_system.mjs`: passed.
- `python3 -m unittest tests/test_learning_system.py -v`: 332 tests passed in 164.582s.
- Focused v4 evidence identity/resume checks: passed.
- Local service on port `8765`: `Python` PID `73652` listening.
- Live API check: `/api/child-bootstrap` returned `schema_version=3.0.0-daily-flow`, `child_state=current_step`, topic `绝对值`, position `2`, input mode `text_photo`.
- Live flow check: submitted the current absolute-value step, observed `analyzing_pending`, then a new `current_step` at position `2`; latest live jobs are `answer_analysis/evaluation_update/planner_decision` all `succeeded/live_model`.
- Daily report regenerated: `docs/system/daily_reports/latest.md`; current snapshot shows `v5 blocked flows: 0`, `v5 pending attempts: 0`, and no P0 blockers.

## Not Yet Released

- v12 live question-bank generator activation remains held. Current production code expects v4 focal-review plus global-finalizer evidence.
- The specialty suite `tests/test_question_bank_v12.py tests/test_question_bank_v12_v3_contract.py tests/test_question_bank_v12_v4_contract.py` still has historical v3 contract drift: 26 errors and 1 failure in the last run.
- The failing v12 tests mostly exercise old `slot_semantic_evidence` / single-stage node-set review expectations against the newer v4 global-finalizer contract. Do not make v3 evidence activation-eligible merely to turn these tests green.
- One real v12 migration signature bug was fixed in `scripts/build_math_question_bank_v12.py`: pre-shard checkpoint migration now creates a v4 pending partial artifact instead of calling a removed aggregate signature.

## Next Engineering Target

Close the v12 specialty gap by migrating historical v3 contract tests to read-only/oracle scope and keeping activation on v4 focal-review plus global-finalizer evidence only.
