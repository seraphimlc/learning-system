### CODE_REVIEW / PASS_WITH_SCOPE - 镜花（agentKey: `jinghua`）- 2026-07-08 15:50 CST

Verdict:
`PASS_WITH_SCOPE`.

independence_required:
yes.

context_mode:
fresh targeted close re-review for prior P1.

context_origin:
User/若命 request to verify closure of prior P1: newer empty open session overriding an older started child learning session.

diff_pin:
unavailable. `/Users/liuchang/Documents/gitproject/son-ai-learning-system` is not a Git worktree in this runtime; `git status --short` returned `fatal: not a git repository`. Review is pinned to current workspace files, path/line inspection, targeted tests, browser smoke, and temporary simulation DB evidence.

Scope:
Only the session-freeze/session-selection fix around child learning group continuity:
- `_current_child_plan_context` selection priority.
- `current-learning-group` bootstrap, task-position submission, completion, and completion polling consumers.
- Regression coverage for the prior false-pass case.
- Adjacent risks named in the request: old empty session hijack, no-model blocked recovery, and latest closed group completion poll.

Project boundary overlay:
Applied from `AGENTS.md`, `docs/domain-index/math-learning.md`, `docs/architecture/technical_plan_v2.md`, `docs/architecture/data_contract_spec_v2.md`, and the direct request. Relevant constraints: one-child AI-native math loop; child APIs use `current-learning-group` and task positions, not internal ids; normal child progress must not depend on parent/Codex cleanup; session close/planning must not use pending, stale, invalidated, or missing-analysis evidence; child-facing projections stay simple and hide internal workflow details.

Source artifacts:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/roles/jinghua.md`
- `docs/collaboration/playbooks/code-review.md`
- `docs/collaboration/playbooks/artifact-contracts.md`
- `docs/project-rules/system-architecture-learning-addendum.md`
- `docs/domain-index/math-learning.md`
- `docs/architecture/technical_plan_v2.md`
- `docs/architecture/data_contract_spec_v2.md`
- `docs/qa/test_case_spec_v2.md`
- `docs/architecture/code_skeleton_pass_v2.md`
- `docs/collaboration/reviews/2026-07-08-jinghua-session-freeze-rereview.md`
- `learning_system/server.py`
- `learning_system/db.py`
- `learning_system/orchestrator.py`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `scripts/simulate_child_learning_journey.py`

Inputs reviewed:
- Fix summary from 若命/user.
- Prior P1 reproduction and expected fix boundary in `docs/collaboration/reviews/2026-07-08-jinghua-session-freeze-rereview.md`.
- Current implementation at `learning_system/server.py:551-583`, `learning_system/server.py:1005-1068`, `learning_system/server.py:1214-1225`, and `learning_system/server.py:1444-1480`.
- Session creation/retirement/completion summary behavior at `learning_system/db.py:2199-2318`.
- Close state machine behavior at `learning_system/orchestrator.py:705-957`.
- Regression tests at `tests/test_learning_system.py:3604`, `tests/test_learning_system.py:3667`, `tests/test_learning_system.py:3805`, and `tests/test_learning_system.py:4427`.

Commands:
- `python3 -m py_compile learning_system/server.py tests/test_learning_system.py scripts/child_learning_scenarios.py scripts/simulate_child_learning_journey.py` -> passed.
- `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_child_completion_poll_finds_latest_closed_group_after_next_plan_is_created tests.test_learning_system.LearningSystemTest.test_child_completion_poll_ignores_stale_open_session_from_old_plan tests.test_learning_system.LearningSystemTest.test_child_completion_handle_rejects_unlinked_open_session_from_old_plan tests.test_learning_system.LearningSystemTest.test_child_submission_uses_open_session_plan_even_when_latest_plan_changes tests.test_learning_system.LearningSystemTest.test_child_submission_prefers_started_session_over_newer_empty_session tests.test_learning_system.LearningSystemTest.test_child_bootstrap_recovers_waiting_ai_background_review tests.test_learning_system.LearningSystemTest.test_child_completion_without_model_returns_recoverable_system_state_not_waiting_forever -v` -> `Ran 7 tests in 12.706s`, `OK`.
- `python3 -m unittest tests/test_learning_system.py -v` -> `Ran 135 tests in 138.281s`, `OK`.
- `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs` -> `PASS browser smoke: child-only flow -> pending guard -> analyzed evidence evolution`.
- `python3 scripts/simulate_child_learning_journey.py --lessons 10 --keep-db /tmp/jinghua-sessionfix-r2.sqlite --report /tmp/jinghua-sessionfix-r2.md` -> `{"verdict": "PASS", "lessons": 10}`.
- `sqlite3 /tmp/jinghua-sessionfix-r2.sqlite ...` -> 10 child sessions, 100 attempts, 100 background jobs, 0 open child sessions, 10 closed/planned sessions, 100 succeeded jobs.

Evidence:
- Code-path proof for prior P1 closure: `_current_child_plan_context` now builds all non-stale open session contexts, first returns any open child session with active attempts or `status == "closing"`, and only then returns an empty open session for the latest generated plan (`learning_system/server.py:564-583`). This directly closes the old failure mode where a newer empty latest-plan session could win before an older started session.
- Child bootstrap uses the same selected context for `today_plan` and `learning_group`, so the visible task positions remain bound to the started session (`learning_system/server.py:710-716`, `learning_system/server.py:1444-1453`).
- Child task-position submission uses the same selected context and creates a session only if no matching selected session exists (`learning_system/server.py:1030-1068`), so the second answer in the regression is recorded on the old started session, not the newer empty session.
- `current-learning-group/complete` resolves through `_current_child_session_id`, which first uses the selected active/closing session, then falls back to the latest closed session whose `next_plan_id` matches the current plan (`learning_system/server.py:1214-1225`). This preserves latest-closed completion polling after a planned close.
- No-model blocked recovery is still reachable: bootstrap surfaces `waiting_ai` / recoverable `ai_review_unavailable` blocked completion for the selected closing session and restarts background processing once model routes are enabled (`learning_system/server.py:1454-1479`); orchestrator also allows a `closing` session with `blocked`/`waiting_ai` to proceed when ready (`learning_system/orchestrator.py:796-821`).
- Temporary simulation DB matched the report verdict rather than false-passing: every one of 10 child sessions closed as `planned`, each with 10 attempts; there were no open child sessions after the run.

Implementation fidelity:
- Prior P1 is closed in the reviewed code path. The selection rule now prioritizes meaningful in-progress sessions over empty latest-plan sessions.
- Old empty session hijack was not reintroduced in the checked paths. Empty sessions from older plans are ignored when the latest generated plan is different, while latest closed completion is still found through `next_plan_id`; focused tests for stale/unlinked old-plan sessions passed.
- No-model blocked recovery was not regressed. The selected `closing` session remains child-visible and recoverable instead of being displaced by a fresh empty plan/session; focused no-model recovery test passed.
- Completion poll latest closed group was not regressed. The fallback to `_latest_closed_child_session_for_next_plan` is still in place and covered by the focused poll test.
- The new regression test is false-pass-resistant for the prior P1: it creates old plan/session A, records a real active attempt in A, generates plan B, creates empty session B, then asserts bootstrap, task-position 2 submission, and current-group completion all continue to bind A while B remains `not_started`.

Findings:
None in the reviewed scope.

Not covered:
- Live GPT-compatible answer-analysis quality.
- Live Doubao/OCR quality.
- Human visual/taste review.
- Full release QA across all semantic/model/provider edge cases.
- True git diff comparison, because the workspace has no `.git` metadata in this runtime.

Residual risk:
- If future operator paths intentionally allow multiple simultaneous started child groups, the selector currently chooses the newest open session that has active attempts or is `closing`. That is acceptable for the current single-child/single-current-group contract, but a stronger DB-level single-open-session invariant would still be a useful hardening item if this system grows.
- `retire_stale_child_learning_sessions(..., commit=False)` remains a repeated in-memory filter when called from read-only bootstrap paths outside an explicit transaction. It does not affect this P1 closure because `_open_child_sessions` also filters stale sessions before selection, but it is worth keeping in mind for future cleanup/audit persistence work.

Required next action:
No code fix required for the prior P1. Treat this as a targeted `PASS_WITH_SCOPE` for the session-freeze fix, not as full live-model/OCR or release QA. Next gate may proceed to broader QA/release checks if 若命 wants to close the larger child-loop workline.
