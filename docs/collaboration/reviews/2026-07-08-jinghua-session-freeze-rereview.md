### CODE_REVIEW / NEEDS_FIX - 镜花（agentKey: `jinghua`）- 2026-07-08 15:34 CST

Verdict:
`NEEDS_FIX`.

independence_required:
yes.

context_mode:
fresh targeted rereview.

context_origin:
User/若命 request for the completed child learning session state-machine fix.

diff_pin:
unavailable. `/Users/liuchang/Documents/gitproject/son-ai-learning-system` is not a Git worktree in this runtime, so I reviewed current files by path/line and used targeted runtime reproduction instead of a real git diff.

Scope:
`learning_system/server.py` behavior around `_current_child_plan_context`, `_open_child_sessions`, `_latest_open_child_session`, and `_current_child_session_id`; targeted tests in `tests/test_learning_system.py` named by the request; producer/consumer context in `learning_system/db.py`, `learning_system/orchestrator.py`, `learning_system/auto_review.py`, `learning_system/flow_nodes.py`, child UI polling behavior, browser smoke, and existing 10-lesson simulation report.

Project boundary overlay:
Applied from `AGENTS.md`, `docs/domain-index/math-learning.md`, and the direct request. Relevant constraints: this is a one-child AI-native math learning loop; normal child progress must not depend on parent/Codex intervention; child learning sessions use the `current-learning-group` handle and task positions, not internal ids; session close must not plan from pending, stale, invalidated, or missing-analysis evidence; old empty/blocked sessions must not hijack the prepared next group.

Source artifacts:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/roles/jinghua.md`
- `docs/collaboration/playbooks/code-review.md`
- `docs/collaboration/playbooks/artifact-contracts.md`
- `docs/project-rules/system-architecture-learning-addendum.md`
- `docs/domain-index/math-learning.md`
- `learning_system/server.py`
- `learning_system/db.py`
- `learning_system/orchestrator.py`
- `learning_system/auto_review.py`
- `learning_system/flow_nodes.py`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `scripts/simulate_child_learning_journey.py`
- `docs/system/qa/simulated_child_learning_journey_latest.md`

Evidence:
- Required startup files and relevant inbox/registry/index docs were read.
- `git status --short` failed with `fatal: not a git repository`; no production code was edited.
- Ran `python3 -m py_compile learning_system/server.py tests/test_learning_system.py scripts/child_learning_scenarios.py scripts/simulate_child_learning_journey.py`: pass.
- Ran focused requested tests:
  `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_child_completion_poll_ignores_stale_open_session_from_old_plan tests.test_learning_system.LearningSystemTest.test_child_completion_handle_rejects_unlinked_open_session_from_old_plan tests.test_learning_system.LearningSystemTest.test_child_submission_uses_open_session_plan_even_when_latest_plan_changes tests.test_learning_system.LearningSystemTest.test_child_bootstrap_recovers_waiting_ai_background_review tests.test_learning_system.LearningSystemTest.test_child_completion_without_model_returns_recoverable_system_state_not_waiting_forever tests.test_learning_system.LearningSystemTest.test_child_learning_semantic_scenario_matrix_covers_multi_state_answers -v`: `Ran 6 tests in 8.475s`, `OK`.
- Ran full unit suite: `python3 -m unittest tests/test_learning_system.py -v`: `Ran 134 tests in 139.248s`, `OK`.
- Ran browser smoke: `node tests/browser_smoke_learning_system.mjs`: `PASS browser smoke: child-only flow -> pending guard -> analyzed evidence evolution`.
- Inspected existing 10-lesson simulation report `docs/system/qa/simulated_child_learning_journey_latest.md`: `Verdict: PASS`, `Issues: 0`, each lesson reached `planned` with 10 succeeded jobs.
- Minimal temp-DB reproduction for multi-open-session priority:
  1. Create plan A and child session A.
  2. Record one active pending attempt in session A.
  3. Generate plan B and create empty child session B.
  4. Call `server._current_child_plan_context(conn)`.
  Observed selected session B, not session A: `session_a ... attempts 1`, `session_b ... attempts 0`, `selected_session` = session B.

Implementation fidelity:
The targeted fix correctly handles the covered cases:
- A single open session with active attempts freezes to its original plan even after a newer plan exists (`learning_system/server.py:568-578`; covered by `test_child_submission_uses_open_session_plan_even_when_latest_plan_changes`).
- Old empty/unlinked sessions from older plans no longer hijack the latest ready plan or completion handle (`learning_system/server.py:571-580`, `1211-1222`; covered by the two stale/unlinked old-plan tests).
- Completion polling can recover the latest closed group through `next_plan_id` and child bootstrap can surface the planned completion while the next group is not started (`learning_system/server.py:1213-1216`, `1444-1462`).
- No-model completion now becomes child-visible `blocked` / `needs_system_recovery` rather than unbounded `waiting_ai` (`learning_system/server.py:1389-1439`; covered by requested test).

Findings:

P1 - A newer empty open session can still override an older open session that already has real child attempts.
- File and lines:
  - `learning_system/server.py:568-578` iterates open child sessions newest-first and returns the first session whose plan is the latest plan, even if that session is empty.
  - `learning_system/server.py:611-632` defines `_open_child_sessions` / `_latest_open_child_session` as created-at newest-first without prioritizing sessions that contain active attempts or are already closing.
  - `learning_system/server.py:1027-1065` uses `_current_child_plan_context` for child task-position submission, so the selected empty session becomes the child-visible group.
  - `learning_system/server.py:1211-1222` uses the same context for `current-learning-group/complete`, so completion also targets the empty newer session.
- Trigger condition:
  More than one open `child_learning_group` exists: an older session has at least one active attempt, then a newer empty session is created for the latest generated plan, for example through `/api/learning-sessions`, `/api/operator/learning-sessions`, or any operator/system path that starts a new session before the in-progress group closes.
- Impact:
  The child-visible `today_plan` and subsequent `task_position` submissions switch to the empty latest-plan session while the real started group remains open. Completing `current-learning-group` can then block on the empty/new group instead of the actual in-progress group. This reintroduces the core class of drift the fix was meant to eliminate under a multi-open-session state and can make normal child continuation depend on parent/Codex cleanup of the abandoned session.
- Required fix boundary:
  Change selection priority so any open child session with active attempts, or any `closing` session, wins before an empty session merely because its plan is the latest plan. Only after no meaningful active/closing session exists should the selector choose an empty session for the latest plan. Alternatively, enforce a single open child-learning-group invariant by refusing or retiring empty new sessions while a different open session has active attempts. Keep the old empty/blocked old-plan behavior intact: an old empty session must still not hijack the prepared next plan.
- Validation expectation:
  Add a regression test that creates old plan/session A, records an active attempt in A, generates new plan B, creates empty session B, then asserts `/api/child-bootstrap` and a task-position submission still bind to A. Also assert completing `current-learning-group` targets A, not B. Keep existing stale empty old-plan tests passing.

Residual risk:
- Live model/OCR semantic quality was not exercised; model calls are patched in unit and simulation paths.
- The directory lacks git metadata, so this is a current-file/code-path review rather than a true diff review.
- Existing tests cover the stated stale-empty and latest-closed-polling cases well, but they currently miss the active-attempt-vs-new-empty priority false-pass case above.

Required next action:
听云 should fix the multi-open-session selection priority or enforce the single-open-session invariant, add the regression described above, then rerun focused session-freeze tests plus full `tests/test_learning_system.py` and browser smoke before returning for rereview.
