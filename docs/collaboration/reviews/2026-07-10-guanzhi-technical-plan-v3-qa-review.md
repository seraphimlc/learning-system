### QA / NEEDS_FIX - 观止（agentKey: `guanzhi`）- 2026-07-10 CST

Verdict:
`NEEDS_FIX`

independence_required:
yes

context_mode:
fresh

context_origin:
spawned only for this review; did not author the plan

diff_pin:
`docs/architecture/technical_plan_v3.md`

Scope:
Review whether `docs/architecture/technical_plan_v3.md` contains a test design strong enough to prevent the v3 first implementation slice from falsely passing. Scope includes current-step child flow, old-knowledge review hot path, async answer analysis, model unavailable/slow, idempotency/duplicate submit, late evidence, stuck/blank/photo, answer-only, wrong-reason-right-answer, 10-20 step adaptive day, no fixed question list, next-step evidence trace, child-safe projection/no internals, and report evidence labels.

Forbidden scope:
No QA PASS. No production code or test code changes. No implementation work for 听云. No replacement for 镜花 engineering review or 霜弦 data/content review.

Project boundary overlay:
Applied from `docs/product/ai_native_math_learning_prd_v3.md` `PROJECT_BOUNDARY_OVERLAY`, `AGENTS.md`, and `docs/domain-index/math-learning.md`. Core QA oracle: flow completion is insufficient; QA must distinguish chain integrity, semantic integrity, teaching integrity, and provider integrity. Mocked tests cannot prove live model intelligence.

Source artifacts:
- `docs/collaboration.md`
- `docs/collaboration/roles/guanzhi.md`
- `docs/collaboration/agent-registry.json`
- `docs/project-rules/qa-learning-system-addendum.md`
- `AGENTS.md`
- `docs/project-index.md`
- `docs/domain-index/math-learning.md`
- `docs/architecture/technical_plan_v3.md`
- `docs/product/ai_native_math_learning_prd_v3.md`
- `docs/architecture/ai_native_learning_system_architecture_v3.md`
- `docs/architecture/daily_learning_runtime_contract_v1.md`
- `docs/qa/test_case_spec_v2.md`
- `docs/system/qa/live_child_ui_10x_latest.md`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `scripts/simulate_child_learning_journey.py`
- `scripts/child_learning_scenarios.py`
- `scripts/live_child_ui_10x.py`

Environment:
Read-only planning review. Shell read/search commands only. No server, browser, model provider, or test execution.

Test case spec:
Not produced. There is no v3 `SKELETON_PASS` yet, so a final skeleton-derived `TEST_CASE_SPEC` would be premature. This review records mandatory coverage that must enter the later `TEST_CASE_SPEC`.

Evidence:
- Identity binding passed: `docs/collaboration/roles/guanzhi.md` YAML header matches `docs/collaboration/agent-registry.json` for `agentKey=guanzhi`, display `观止`, role type `qa_test_design_and_audit_gate`, permissions, lifecycle, and output contracts.
- `technical_plan_v3` has useful test direction: validation strategy covers schema/current-step/evidence gate/candidate packet/recovery, child API, model-disabled cases, semantic fixtures, browser states, and DB-derived reports at lines 337-350.
- The engineering contract has contract-test bullets for v3 schema, child bootstrap redaction, one visible current step, duplicate submit, evidence gate, candidate packet, model config missing, late evidence, and summary labels at lines 559-586.
- The implementation blueprint lists v3 test targets and script updates at lines 681-698 and named tests at lines 724-733.
- PRD v3 acceptance requires pending evidence handling, late evidence reconciliation, stuck/blank/photo scenarios, 10-20 continuous adaptive day, evidence-scoped summary, and report labels at lines 342-366.
- Architecture v3 explicitly requires four QA integrities, required semantic scenarios, restart/repeated-poll/duplicate coverage, old fixed-flow/stale-report false-pass defense, and provider mode labeling at lines 1064-1128.
- Runtime contract requires slow-model independent-step vs wait behavior, OCR unclear handling, model config failure, hot-path context budget, and latency/provider metadata at lines 839-892.
- Current tests and harnesses are mainly v2-shaped: `today_plan.tasks`, fixed `child_learning_group`, `/api/child-submissions`, and fixed group close. They are reusable evidence patterns, not proof of the v3 `daily_flow` current-step runtime.

False-pass audit:
The plan is directionally correct but not yet sufficient to prevent a v3 first-slice false pass. It leaves too much of the anti-false-pass burden to a future `TEST_CASE_SPEC` without making several cross-state and cross-evidence cases non-negotiable. Because false-pass risk remains, the gate is `NEEDS_FIX`, not `PASS_WITH_SCOPE`.

Failures:

1. `[P1] 10-20 adaptive-day coverage is mentioned but not made a hard first-slice gate.`
   `technical_plan_v3` says to add a v3 mode to `scripts/simulate_child_learning_journey.py` for a 10-20 adaptive simulation, but the named tests only cover single start/submit/candidate/gate/summary cases and browser smoke. A short happy path, a one-step loop, or a fixed hidden sequence could pass the listed tests while violating PRD AC-25. The later `TEST_CASE_SPEC` must require a v3 current-step 10-20 day trace with mixed evidence, all-correct segment, slow-model branch, skipped mastered nodes, no fixed-list regression, and evidence-scoped summary.

2. `[P1] Async/model-slow recovery matrix is too shallow.`
   The plan covers model config missing and one late-evidence non-rewrite assertion, but does not explicitly require tests for slow model with independent safe target, slow model with no independent target, stale queued/running jobs, pending attempt with no job, repeated polling, and one applied analysis/evaluation/planner decision per attempt/version. Runtime contract makes these separate branches. Without them, a system can pass by handling only "model not configured" while still hanging, double-applying, or planning from pending evidence.

3. `[P1] "No fixed list" and next-step trace are under-specified.`
   The contract test forbids `today_plan.tasks` in the v3 child payload and requires one visible step, which is necessary but not enough. A runtime could precompute a whole hidden sequence and expose it one step at a time. The later `TEST_CASE_SPEC` must require every next `flow_step` to be backed by a `next_step_decision` written after the previous usable/pending evidence state, with source attempt ids, node status, review target, candidate packet/filter summary, skipped alternatives, and gate verdict.

4. `[P1] Semantic cases are listed, but not tied to full downstream consequences.`
   Recorded/mock cases for answer-only, wrong-reason-right-answer, stuck, blank, photo usable/unusable, and symbol/unit are listed. The false-pass risk remains unless each case asserts `answer_analysis.comparison`, `process_gap`, error tags, evidence validation status, mastery decision behavior, child-safe feedback/repair, and the planner branch. In particular, a correct final answer with wrong reasoning must not become mastery, and blank/photo-unclear evidence must not drive planning.

5. `[P2] Provider integrity and report verdict honesty need explicit harness gates.`
   The plan says live model semantic quality cannot be proven by unit tests and mock/live labels must be separate, but the test design does not yet require issue-count/verdict/exit-code consistency, provider mode on every QA report, stale `latest` rejection, or old v2 fixed-flow artifacts being treated as non-v3 evidence. Architecture v3 makes those anti-false-pass requirements explicit.

Defect severity:
High for first-slice QA readiness because the missing items affect release-critical false-pass risk in the child learning loop, async evidence chain, semantic judgment, and parent/Codex report truth.

Not covered:
No test execution, live model/OCR calls, browser screenshots, DB mutation, visual taste review, or implementation inspection beyond existing source/test files. No final `TEST_CASE_SPEC` because v3 code skeleton does not exist yet.

Residual risk:
Even after the plan is amended, mock-only execution can at most support `QA_PASS_WITH_SCOPE` for semantic/model claims. Full child-flow PASS will still need at least two evidence types, such as browser/API plus DB facts, and live/recorded provider evidence clearly labeled.

Required next action:
Before or at `SKELETON_PASS`, update the test-design handoff so the later skeleton-derived `TEST_CASE_SPEC` must include the mandatory coverage below. Do not let the first v3 implementation slice claim QA readiness from only the current named tests in `technical_plan_v3`.

Mandatory next `TEST_CASE_SPEC` coverage:

1. Current-step child flow and old-review hot path
   - `GET /api/child-bootstrap` v3 schema has `child_state/current_step` and no `today_plan.tasks`.
   - `POST /api/daily-flow/review/start` creates or resumes one `daily_flow`, one visible `flow_step`, graph-bound `review_targets`, and a backing `daily_flow_v3` session only if needed for compatibility.
   - Review target pool prioritizes blocked/unpassed, weak confirmation, untested, prerequisite, and new-learning readiness cases; mastered nodes are skipped unless spaced confirmation is due.
   - No hidden fixed daily list: each next step is created after the latest step/evidence transition and has a fresh decision record.

2. Idempotency, duplicate submit, and repeated polling
   - Same `step_handle/position/client_idempotency_key` returns the same receipt and does not create a second attempt/job.
   - Same step with different evidence/key conflicts safely.
   - Mismatched/stale handle or position returns child-safe reload/retry with no attempt.
   - Repeated bootstrap polling does not create extra steps, flows, jobs, decisions, summaries, or stale recovery actions.
   - Concurrent submit/poll/recovery paths leave one active attempt, one active analysis job, one evidence validation, and one next decision per valid version.

3. Async/model unavailable/slow/recovery
   - Model config missing: attempt pending/blocked with operator reason, child-safe message, no fake grading.
   - Model slow and independent safe target exists: runtime moves to independent step without using pending evidence.
   - Model slow and no independent target exists: child sees honest wait/retry; no parent/Codex intervention required.
   - Stale `queued/running/error` jobs, pending attempts with no job, and completed model output not applied are recovered idempotently on startup/bootstrap.
   - Timeout/retry/fallback metadata is recorded without secrets; fallback cannot mark mastery or invent teaching conclusions.

4. Late evidence
   - Late analysis after an independent step is displayed is recorded immediately but cannot rewrite the visible prompt, expected evidence, or current answer target.
   - Late evidence can affect mastery/planning only at safe transition points and must write a reconciliation record.
   - Summary/report labels must say whether late evidence was included or excluded.
   - Late evidence that invalidates the current plan leads to an auditable reconsideration after the current step ends.

5. Evidence gate and semantic/model oracle
   - Matrix covers active/invalidated/stale x graded/pending/blocked x valid/missing/malformed/mock/low-confidence/missing-lineage analysis.
   - Required child scenarios: sound correct reasoning, answer-only, stuck/cannot start, blank/no usable evidence, wrong-reason-right-answer, partial relation/wrong final, symbol/unit issue, readable photo, unclear photo.
   - For each scenario assert analysis dimensions, process gap, error tags, OCR usability, confidence policy, validation status, mastery decision, and next-step branch.
   - Schema-valid but semantically bad model output must fail the semantic oracle.
   - Mock, recorded, and live provider evidence must be reported separately; mock-only semantic QA is never full PASS.

6. Candidate packet and hot-path context
   - Packet has 5-8 metadata rows, no full bank/solutions, includes graph version, review record, item version, family/signature, evidence goal, target error tags, `why_candidate`, and filter summary.
   - Excludes stale/inactive/duplicate/cooldown/mastered-node extras before planner sees them.
   - Agent audit records candidate/context size, latency, timeout/retry/fallback mode, provider route, and validation verdict.

7. Next-step evidence trace and teaching integrity
   - Every `next_step_decision` traces to source attempts, evidence validations, node status, graph version, review target, candidate packet, and branch policy.
   - Wrong model chooses contrast/reteach/prerequisite/rollback, not blind same-type drill.
   - Answer-only chooses explanation/retest/clarification, not mastery.
   - All-correct segment advances or retests without fabricating weakness.
   - Ready-for-new-knowledge occurs only after old-review high-priority targets are cleared enough, with prerequisite summary.

8. 10-20 continuous adaptive day
   - Browser/API simulation runs a v3 `daily_flow` for 10-20 current steps, not fixed group close.
   - Mixed correct, wrong, stuck, blank, photo, slow-model, pending, and correct-only segments are present.
   - Checks skip mastered nodes, no fixed-list regression, no parent intervention, no hidden raw ids, all steps represented in summary, and all next decisions evidence-linked.

9. Child-safe projection and UI/browser coverage
   - All child states: loading, choose review, current step, saving, analyzing/waiting, blocked, clarification, teaching shell, ready-for-new-knowledge, summary, load/save/upload error.
   - Child payload/DOM/accessibility text has no graph ids, question ids, attempt ids, model/provider names, agent names, rubrics, queue internals, Codex/parent instructions, or private upload paths.
   - Desktop/mobile screenshots or DOM metrics prove one current step, no overflow, preserved draft/photo on errors, keyboard/focus path, and honest waiting/blocked states.

10. Report/evidence labels and false-pass harness
   - Every child summary and Codex/report claim carries one of `confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`, `missing_lineage`, with source step/attempt/decision ids.
   - Stale `latest` reports and v2 fixed-flow artifacts cannot satisfy v3 PASS evidence.
   - QA report records base URL, DB path, provider mode, code/version marker, sampled flow/step/attempt ids, screenshots/artifacts, report path, and whether it wrote to real or isolated ledger.
   - Any issue-count/report-verdict/exit-code disagreement is `NEEDS_FIX`.

Stop condition:
This review is complete when the above requirements are available to 若命/听云 for the next v3 `SKELETON_PASS` and skeleton-derived `TEST_CASE_SPEC`. It is not QA execution and must not be cited as QA PASS.
