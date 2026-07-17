### CODE_REVIEW / NEEDS_FIX - 镜花（agentKey: `jinghua`）- 2026-07-08 15:25 CST

Verdict:
`NEEDS_FIX`.

independence_required:
yes.

context_mode:
fresh.

context_origin:
new mainline audit after REG-05 closed.

diff_pin:
not_applicable; current workspace is not a git repo per dispatch packet.

Scope:
End-to-end child learning session completion chain: child UI submit -> `/api/child-submissions` -> attempt/attachment/background job -> background answer review -> `/api/learning-sessions/current-learning-group/complete` -> answer analysis, graph binding, evaluation, evolution, planner -> child-safe completion projection.

Project boundary overlay:
Applied from `AGENTS.md`, `docs/domain-index/math-learning.md`, `docs/product/ai_native_math_learning_prd_v2.md`, `docs/architecture/technical_plan_v2.md`, and `docs/architecture/data_contract_spec_v2.md`. Relevant constraints: one child Web端 only; normal child progress must not depend on parent/Codex intervention; async review must be recoverable; child API must not expose internal ids/agents/models; session close must not plan from pending, invalid, stale, invalidated, or missing-analysis evidence.

Source artifacts:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/roles/jinghua.md`
- `docs/project-rules/system-architecture-learning-addendum.md`
- `docs/domain-index/math-learning.md`
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/architecture/technical_plan_v2.md`
- `docs/architecture/data_contract_spec_v2.md`
- `docs/architecture/code_skeleton_pass_v2.md`
- `learning_system/server.py`
- `learning_system/auto_review.py`
- `learning_system/db.py`
- `learning_system/orchestrator.py`
- `learning_system/planner.py`
- `learning_system/evolution.py`
- `learning_system/agents.py`
- `learning_system/model_router.py`
- `learning_system/flow_nodes.py`
- `learning_system/internal_agents.py`
- `app/local_learning_system/app.js`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`

Evidence:
- Identity binding validated: `docs/collaboration/roles/jinghua.md` YAML header matches `docs/collaboration/agent-registry.json` for `agentKey=jinghua`.
- Code inspection traced producer/consumer paths above.
- Ran `env -u OPENAI_API_KEY -u AI_EVALUATOR_API_KEY -u AI_ANSWER_ANALYSIS_AGENT_ANSWER_REVIEW_API_KEY -u AI_ANSWER_REVIEW_API_KEY -u AI_QUESTION_MODEL -u AI_EVALUATOR_MODEL -u AI_VISION_MODEL python3 -m unittest tests/test_learning_system.py -v`.
- Result: `Ran 133 tests in 133.276s` and `OK`.
- No implementation files edited. No DB mutation outside test temp fixtures. No external model calls intentionally allowed.

Implementation fidelity:
- Child API shape is mostly aligned: child bootstrap/submission/complete use handle/position projections, and tests assert internal ids/model/agent fields are absent.
- Close/evolution/planner trust boundary is materially improved: `db.session_completion_summary` separates pending, missing-analysis, structurally analyzed, usable, and unusable evidence; `orchestrator.close_learning_session` blocks before graph/evaluation/evolution/planner on pending, missing, or unusable evidence; planner/evolution use `db.is_current_usable_attempt_evidence`/`db.is_evolution_source_valid`.
- Main blocker is recoverability: a normal low-confidence or unusable-photo answer can keep the child in `waiting_ai` with no child-side way to replace evidence.

Findings:

P1 - Low-confidence or unusable review results can leave a completed 10-task group in an unrecoverable child wait loop.
- File/lines:
  - `learning_system/auto_review.py:145-154` returns pending for unusable photo OCR.
  - `learning_system/auto_review.py:197-209` returns pending for low confidence.
  - `learning_system/server.py:1620-1634` marks that background job `waiting` and leaves the attempt `pending_review`.
  - `learning_system/orchestrator.py:740-757` maps any pending attempt to `waiting_ai`.
  - `app/local_learning_system/app.js:537-542` and `app/local_learning_system/app.js:637-657` keep polling `current-learning-group/complete`.
  - `learning_system/server.py:1033-1044` rejects another active submission for the same question, so the child cannot fix the unclear attempt by resubmitting the task position.
- Trigger condition:
  A child finishes all 10 tasks, but one submission is photo-only with low OCR confidence, model low confidence, or repeated malformed answer-analysis output. The background worker exhausts retry passes or keeps returning a pending review.
- Impact:
  The system correctly refuses to plan/evolve from bad evidence, but the child remains stuck waiting. Normal progress then depends on operator/Codex/manual backfill or a future model route improvement, which violates the project boundary that normal child progress must not depend on parent/Codex intervention and async review must be recoverable.
- Required fix boundary:
  Add a child-recoverable terminal review state for pending evidence that is not expected to resolve by retry alone, such as `needs_clearer_evidence`/`needs_child_resubmission`, keyed by child task position rather than attempt id. The child projection should show a safe prompt to re-upload/retype the affected task, and the submission endpoint should allow replacing or invalidating the prior active pending attempt through `current-learning-group + task_position` without exposing internal ids. Keep such attempts excluded from evaluation/evolution/planning until replaced by valid graded analysis.
- Validation expectation:
  Add an API and browser/state test where a 10-task child session contains one low-confidence photo or low-confidence model result. Completion should not poll forever; it should return a child-safe recoverable state, allow resubmission by task position, then close to `planned` only after the replacement has valid `answer_analysis`. Assert no `evolution_event`, `mastery_decision`, or `next_plan` is created before valid replacement evidence exists.

P2 - Child review-point numbering is derived from attempt order, not explicit task position.
- File/lines:
  - `learning_system/flow_nodes.py:62-67` selects usable attempts from `attempts_for_session`.
  - `learning_system/db.py:2272-2283` orders attempts by `created_at, id`.
  - `learning_system/flow_nodes.py:429-447` labels review points by `enumerate(attempts, start=1)`.
  - `learning_system/server.py:381-407` has the same fallback enumeration behavior.
- Trigger condition:
  If child submissions arrive out of plan order through the child API or after a future UI change, the review title `第N题` can refer to submission order rather than the original task position.
- Impact:
  This is not currently a normal UI blocker because the current UI submits the first unsubmitted task, but it weakens the child-safe completion projection contract that review points correspond to the child-visible 10-task group.
- Required fix boundary:
  Build review points from `learning_sessions.expected_question_ids` or the current plan's question-position map and sort/map attempts by that position.
- Validation expectation:
  Add a child/API test that submits positions 2 then 1 and verifies completion review points are still labeled and ordered as task 1, task 2, etc.

Residual risk:
- Live model semantic quality and Doubao/OCR quality were not exercised; tests use patched model responses.
- Browser smoke was read but not rerun in this review.
- Final human visual/taste review remains outside this code review.
- The current chain appears safe against planning/evolution from pending, invalidated, stale, missing-analysis, or graph-binding-failed evidence, but the low-confidence pending path is not child-recoverable.

Required next action:
听云 should implement the P1 recoverable-pending/resubmission boundary in the child API, DB state model, background worker, close projection, and child UI. After that, rerun unit tests plus a browser smoke that covers low-confidence/photo-unusable completion recovery. Then return to 镜花 for re-review and 观止 for QA; no QA PASS is claimed here.
