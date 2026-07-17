# Product Structure And Runtime v5 Design Review

### DESIGN_REVIEW / NEEDS_FIX - 镜花（agentKey: `jinghua`）- 2026-07-11 CST

Verdict: `DESIGN_REVIEW_NEEDS_FIX`

independence_required: yes

context_mode: direct user dispatch, same project, read-only source review

context_origin: v5 product structure plus current runtime cutover risk review

diff_pin: source artifacts and current files, no implementation diff

Scope:

- Product sources: `docs/product/ai_native_math_learning_prd_v5.md`, `docs/product/ai_native_math_learning_product_structure_v5.md`
- Runtime/code sources: `learning_system/daily_runtime.py`, `learning_system/server.py`, `learning_system/job_queue.py`, `learning_system/model_router.py`, `learning_system/evidence_gate.py`, `learning_system/db.py`, `learning_system/question_bank.py`, `learning_system/graph_runtime.py`, `learning_system/orchestrator.py`, `learning_system/planner.py`, `app/local_learning_system/index.html`, `app/local_learning_system/app.js`
- Test/evidence orientation only: `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`

Project boundary overlay:

- Single child, math first, graph-bound learning.
- Runtime owns state transitions, persistence, queue/recovery, child-safe projection, and evidence gates.
- Parent uses Codex only; no parent Web dashboard.
- No fixed worksheet; runtime selects one current step from evidence and graph state.
- Pending/mock/stale/missing-lineage evidence cannot drive mastery or dependent next steps.
- Child surface must not expose graph ids, question ids, attempt ids, provider/model names, rubrics, queue/job internals, or Codex/operator workflow.

Source artifacts:

- PRD v5 says the system must run a stable adaptive loop and preserve persisted records for step, question reason, answer, analysis, teaching, evaluation, next-step decision, and summary (`docs/product/ai_native_math_learning_prd_v5.md:56-105`).
- PRD v5 assigns Runtime ownership of state, persistence, queue/recovery, child-safe projection, and evidence gates (`docs/product/ai_native_math_learning_prd_v5.md:132-153`).
- PRD v5 AC-18 through AC-26 require pending/model-failure/restart/child-safe/report-freshness behavior (`docs/product/ai_native_math_learning_prd_v5.md:362-370`).
- Product Structure v5 defines one child surface, no parent dashboard, graph-bound adaptive selection, child-safe projection plus Codex-readable records (`docs/product/ai_native_math_learning_product_structure_v5.md:16-23`).
- Product Structure v5 defines step taxonomy, visible states, flow contracts, data objects, response modes, planner actions, trust labels, candidate rules, summary split, and acceptance paths (`docs/product/ai_native_math_learning_product_structure_v5.md:94-264`).
- Product Structure v5 explicitly does not authorize implementation by itself (`docs/product/ai_native_math_learning_product_structure_v5.md:266-292`).
- The architecture addendum requires end-to-end traces for child submission, review pipeline, session close, model adapter, evidence lineage, and restart/retry; it blocks pass when async review can lose/double-grade, session close can plan from pending/stale/missing analysis, provider logic leaks, child-safe leaks internals, or tests falsely pass (`docs/project-rules/system-architecture-learning-addendum.md:11-44`).

Evidence:

- Files were read directly. No external calls were made.
- No tests were run; this is not QA PASS.
- Current code inspection found v3 skeleton components and legacy fixed-group components coexisting. Some primitives are useful, but the v5 runtime cutover is not architecture-ready.

Implementation fidelity:

- Product Structure v5 is adequate as source input for UX, technical reverse, and technical planning.
- Current runtime does not yet implement the v5 loop end to end. It can save one current-step answer and enqueue a skeleton job, but it does not complete answer analysis, evidence gate, evaluation, teaching/repair, next-step decision, or summary lineage through the v5 daily-flow path.

## Findings

### P0 - v5 current-step submissions can enter `analyzing` with no v5 worker that consumes the queued job

File and line:

- `learning_system/daily_runtime.py:238-371`
- `learning_system/job_queue.py:12-20`
- `learning_system/job_queue.py:45-128`
- `learning_system/job_queue.py:227-251`
- `learning_system/server.py:1783-1824`

Trigger condition:

When `V3_DAILY_RUNTIME_ENABLED` is enabled and the child submits a current-step answer, `DailyLearningRuntime.persist_child_response()` records an attempt, stores attachment refs, enqueues `answer_analysis`, sets `provider_mode: "not_configured"`, and marks the step analyzing (`learning_system/daily_runtime.py:337-359`). The queue adapter defines job types and queue state, but only queue mechanics are present (`learning_system/job_queue.py:12-20`, `learning_system/job_queue.py:45-128`). The recovery method only expires leases and requeues due retries; it explicitly returns `missing_attempt_jobs_created: 0` (`learning_system/job_queue.py:227-251`). The existing background processor handles only legacy `child_learning_group` sessions and skips any other mode (`learning_system/server.py:1820-1823`).

Impact:

Normal child progress can stall indefinitely in `analyzing` after evidence is saved. This violates PRD AC-18/AC-19/AC-23 and the addendum rule that async review must not lose attempts or make child progress depend on parent/Codex intervention.

Required fix boundary:

Before cutting over to v5 runtime, implement or explicitly scope a v5 job worker/reconciler that consumes `background_jobs` for daily-flow attempts and produces normalized `answer_analysis`, `evidence_validation`, `evaluation_update`, `teaching_generation`, `planner_decision`, and summary/blocked outputs. The fix must include stuck-job recovery, completed-unapplied reconciliation, missing-job recreation, and model-unavailable blocked/pending behavior.

Validation expectation:

Use one sample current-step submission and verify, with DB + API evidence, that attempt -> job -> model/OCR/blocked result -> evidence gate -> next visible child state completes after normal run and after simulated restart/lease expiry. Duplicate submit must not create duplicate attempts/jobs/decisions/summaries.

### P0 - v5 state machine is not implemented past first selected question

File and line:

- `learning_system/daily_runtime.py:19-22`
- `learning_system/daily_runtime.py:204-236`
- `learning_system/daily_runtime.py:373-374`
- `learning_system/daily_runtime.py:402-460`
- `learning_system/daily_runtime.py:495-582`
- `docs/product/ai_native_math_learning_product_structure_v5.md:94-130`

Trigger condition:

Product Structure v5 requires `question`, `micro_check`, `teaching_repair`, `worked_example`, `clarify_evidence`, `ready_for_new_knowledge`, `blocked`, and `summary` step types, plus visible states such as `analyzing_pending`, `feedback_teaching`, `clarify_evidence`, and `summary` (`docs/product/ai_native_math_learning_product_structure_v5.md:94-120`). Current `daily_runtime.py` has a v3 status shell (`learning_system/daily_runtime.py:19-22`), can start review mode (`learning_system/daily_runtime.py:204-236`), but `_ensure_first_review_step()` selects only a first active question with a `v3_skeleton_first_active_review_question` reason (`learning_system/daily_runtime.py:495-582`). `complete_summary()` is a blocked stub (`learning_system/daily_runtime.py:373-374`), and `project_child_state()` returns only choose review, current step, analyzing, ready, blocked, or a placeholder summary (`learning_system/daily_runtime.py:402-460`).

Impact:

Switching to v5/current-step runtime would not deliver the product loop: answer -> AI judge -> teach/repair -> select next step -> summary. The child cannot receive real teaching repair, clarification, micro-check, new-knowledge progression, or evidence-backed summary through this path.

Required fix boundary:

Define and implement a canonical v5 transition table across `daily_flow`, `flow_step`, `attempt`, `background_jobs`, `evidence_validations`, `next_step_decisions`, and `daily_summaries`. The table must cover all Product Structure step types/states and specify idempotent commands, terminal states, stale-step handling, and late evidence handling.

Validation expectation:

For at least one text, photo, and stuck sample, verify transitions across DB rows and child API: current step -> analyzing -> teaching/clarify/retest/summary. Include repeated stuck, blocked model, and no-question-available paths.

### P0 - legacy fixed-group flow remains the default child path and can mask v5 regressions

File and line:

- `learning_system/daily_runtime.py:99-112`
- `learning_system/server.py:1647-1689`
- `learning_system/server.py:920-924`
- `learning_system/server.py:1066-1075`
- `app/local_learning_system/app.js:279-320`
- `app/local_learning_system/app.js:635-760`
- `app/local_learning_system/app.js:924-1034`

Trigger condition:

`V3_DAILY_RUNTIME_ENABLED` gates the current-step daily runtime (`learning_system/daily_runtime.py:99-112`). If the flag is not enabled, `/api/child-bootstrap` falls back to the legacy plan/learning-group payload (`learning_system/server.py:1647-1689`). The front end branches on schema version: v3 payloads use current-step rendering, while non-v3 payloads render legacy task-group behavior (`app/local_learning_system/app.js:279-320`, `app/local_learning_system/app.js:635-760`). The same form still supports both `/api/child-submissions` legacy submit and `/api/current-step/submit` v3 submit (`app/local_learning_system/app.js:924-1034`). Legacy close still runs `/api/learning-sessions/current-learning-group/complete` (`learning_system/server.py:1066-1075`).

Impact:

Product Structure v5 removes fixed worksheets and requires adaptive one-step selection (`docs/product/ai_native_math_learning_product_structure_v5.md:16-23`, `docs/product/ai_native_math_learning_product_structure_v5.md:67-76`). With dual paths still active, tests/browser smoke can pass the legacy fixed-group path while v5 current-step is incomplete. This creates a high false-pass risk and an ambiguous rollout boundary.

Required fix boundary:

The technical plan must define the v5 cutover and legacy retirement strategy: which route is canonical, which routes are disabled or operator-only, how existing legacy sessions are read-only/migrated/closed, and how tests prove the child surface no longer receives fixed-group `today_plan.tasks` as the primary learning loop.

Validation expectation:

A child bootstrap test must prove the release path returns only the v5 child-safe current-step projection. Legacy fixed-group routes may remain only behind explicit compatibility/operator scope and must not be counted as v5 acceptance coverage.

### P1 - model adapter exists, but v5 runtime has no normalized model-result envelope

File and line:

- `learning_system/model_router.py:27-57`
- `learning_system/model_router.py:119-176`
- `learning_system/model_router.py:305-345`
- `learning_system/daily_runtime.py:337-355`
- `docs/product/ai_native_math_learning_prd_v5.md:491-505`

Trigger condition:

`model_router.py` exposes model routes for answer analysis, question design, evaluation, planner, teaching, and vision/OCR (`learning_system/model_router.py:119-176`) and has structured JSON fallback (`learning_system/model_router.py:305-345`). However, the v3 current-step job payload only records `provider_mode: "not_configured"` and route metadata (`learning_system/daily_runtime.py:337-355`). There is no v5 result envelope tying provider mode, live/recorded/mock labels, confidence, raw model output snapshot, parse failures, low-confidence OCR, and child-safe blocked/pending output into the daily-flow job sequence.

Impact:

Provider differences and model failures can either stall the queue or leak into business logic/reporting. PRD v5 requires reports/QA to distinguish `live_model`, `recorded_model`, `mock_only`, `pending`, and `blocked`, and forbids `mock_only` semantic PASS (`docs/product/ai_native_math_learning_prd_v5.md:491-505`).

Required fix boundary:

Define the model adapter output contract consumed by v5 jobs: route id, provider mode, model scope label, confidence, structured parse mode, redacted audit metadata, child-safe failure reason, and replay/snapshot references. Business state transitions must consume this normalized envelope, not provider-specific exceptions.

Validation expectation:

Recorded tests must cover configured live/recorded response, unsupported structured JSON fallback, invalid JSON, timeout/model route missing, low-confidence OCR, and mock-only state-machine tests. Child API must not expose provider/model names.

### P1 - evidence gate is fail-closed, but v5 consumers are not wired through it

File and line:

- `learning_system/evidence_gate.py:44-113`
- `learning_system/evidence_gate.py:130-202`
- `learning_system/db.py:670-718`
- `learning_system/daily_runtime.py:238-371`
- `learning_system/orchestrator.py:906-1217`

Trigger condition:

`EvidenceUsePredicate` rejects inactive, ungraded, missing/invalid analysis, mock/not-configured provider, stale graph/question-bank version, and missing lineage (`learning_system/evidence_gate.py:44-113`). `EvidenceGate.validate_attempt()` records validation rows (`learning_system/evidence_gate.py:130-202`), and v3 tables include `evidence_validations` and `next_step_decisions` (`learning_system/db.py:670-718`). But current-step submit stops after attempt/job/analyzing (`learning_system/daily_runtime.py:238-371`). The legacy session close path has a separate orchestrator pipeline (`learning_system/orchestrator.py:906-1217`) that is not the v5 `daily_flow` chain.

Impact:

The existence of a gate primitive can create false confidence while evaluation, planner, summary, report, and evolution consumers may still read graded attempts through legacy paths or not read v5 validations at all. This risks planning from pending, stale, mock-only, or missing-analysis evidence.

Required fix boundary:

Make `evidence_validation` the only source for v5 evaluation, next-step decision, summary, and report claims. Define producer/consumer contracts for validation ids, source attempt ids, analysis versions, graph/question-bank versions, provider mode, and trust labels.

Validation expectation:

For each trust label (`confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`, `missing_lineage`), demonstrate DB rows and report/query output showing that only gate-passed confirmed evidence can update mastery or drive dependent next steps.

### P1 - summary lineage is schema-ready but not produced by v5 runtime

File and line:

- `learning_system/db.py:739-758`
- `learning_system/db.py:806-809`
- `learning_system/daily_runtime.py:373-374`
- `learning_system/daily_runtime.py:430-439`
- `docs/product/ai_native_math_learning_product_structure_v5.md:210-231`

Trigger condition:

Product Structure v5 requires child-safe summary fields plus Codex-readable flow/session handle, freshness version, graph nodes, steps, child evidence ids, answer-analysis status/trust label, teaching actions, evaluation updates, next-step decisions, pending/blocked/stale/mock-only/missing-lineage flags, and report generation timestamp/source versions (`docs/product/ai_native_math_learning_product_structure_v5.md:210-231`). The DB has a `daily_summaries` table and uniqueness index (`learning_system/db.py:739-758`, `learning_system/db.py:806-809`). But v5 `complete_summary()` is a stub (`learning_system/daily_runtime.py:373-374`), and completed/superseded projection returns a placeholder with `labels: {"pending": 1}` (`learning_system/daily_runtime.py:430-439`).

Impact:

The child may see a finish state that is not backed by the required evidence lineage, and Codex/report consumers cannot reliably distinguish current truth from stale or partial reports. This violates PRD AC-22/AC-25/AC-26.

Required fix boundary:

Implement v5 summary generation as a deterministic reducer over source steps, attempts, validations, evaluation updates, next-step decisions, late evidence reconciliations, and graph/question-bank versions. Store source ids and freshness/version fields before child or Codex consumers can treat the summary as authoritative.

Validation expectation:

Simulate mixed correct/partial/wrong/pending/blocked evidence. Verify child-safe summary and Codex-readable summary from the same DB source ids, then mutate a source record and prove old report becomes stale.

### P1 - child-safe projection relies on string filtering and dual DTO conventions, not a v5 allowlist contract

File and line:

- `learning_system/daily_runtime.py:30-51`
- `learning_system/daily_runtime.py:679-696`
- `learning_system/daily_runtime.py:749-764`
- `app/local_learning_system/app.js:20-42`
- `app/local_learning_system/app.js:365-410`
- `learning_system/server.py:868-882`

Trigger condition:

The current v3 child projection strips and scans forbidden terms (`learning_system/daily_runtime.py:30-51`, `learning_system/daily_runtime.py:749-764`) and projects a selected subset of step fields (`learning_system/daily_runtime.py:679-696`). The front end also declares forbidden DTO keys (`app/local_learning_system/app.js:20-42`), but the runtime does not use a shared schema/allowlist contract. The server also exposes operator-like data endpoints such as `/api/questions`, `/api/evolution-events`, and `/api/agent-reports` on the same unauthenticated local server path space (`learning_system/server.py:868-882`).

Impact:

String filtering is brittle against model-generated text, prompt packages, route errors, or newly added fields. The same local app can accidentally mix child and operator surfaces. PRD AC-24 requires no graph ids, question ids, attempt ids, provider names, rubrics, or queue internals in child API/DOM.

Required fix boundary:

Define a v5 child API allowlist schema per child-visible state and make the server construct child payloads only from allowlisted fields. Keep operator/Codex endpoints separate by route namespace and test scope. Do not rely on string replacement as the primary safety mechanism.

Validation expectation:

Automated child API and DOM scans must run against all v5 states: start/resume, current_step, submitting/analyzing, teaching, clarify, ready_for_new_knowledge, blocked, summary, load/save/upload error. Include generated teaching/model failure text in the scan fixtures.

### P1 - graph/question target selection has reusable primitives but the v5 target pool is not wired

File and line:

- `learning_system/question_bank.py:167-272`
- `learning_system/graph_runtime.py:61-90`
- `learning_system/daily_runtime.py:495-582`
- `learning_system/planner.py:12-18`
- `learning_system/planner.py:136-173`
- `docs/product/ai_native_math_learning_product_structure_v5.md:195-208`

Trigger condition:

Product Structure v5 requires Runtime to prefilter graph targets from untested, weak, failed, due, prerequisite, and new-learning nodes, then build a bounded candidate packet; planner/model must never receive the full bank (`docs/product/ai_native_math_learning_product_structure_v5.md:195-208`). `QuestionBankService.candidate_packet_for_node()` provides bounded packet and lineage/hash fields (`learning_system/question_bank.py:167-272`), and `GraphRuntimeService` can summarize prerequisites/rollback candidates (`learning_system/graph_runtime.py:61-90`). But v3 daily runtime currently chooses the first eligible active question by node/id order (`learning_system/daily_runtime.py:495-582`). Legacy planner constants still define 10-task rounds and fixed paths (`learning_system/planner.py:12-18`, `learning_system/planner.py:136-173`).

Impact:

The v5 cutover can silently regress into first-question or fixed-path behavior rather than graph/evidence-driven next-step selection. This undermines prerequisite rollback and few-but-diagnostic question selection.

Required fix boundary:

Wire v5 daily runtime target selection to learner node state, evidence validations, graph prerequisites/rollback candidates, due spacing, recent-use exclusions, and candidate packets. Keep fixed legacy round construction out of the v5 child path.

Validation expectation:

Use fixtures for prerequisite gap, same-structure retest, near-transfer, repeated stuck, and no-candidate cases. Verify `review_targets`, `candidate_packet_id/hash`, `next_step_decisions`, and child projection all refer to the same graph/version lineage.

### P1 - test architecture is rich but can falsely pass via v3 skeleton or legacy path

File and line:

- `tests/test_learning_system.py:713-1707`
- `tests/test_learning_system.py:1941-2184`
- `tests/test_learning_system.py:6095-6789`
- `tests/browser_smoke_learning_system.mjs:305-310`
- `tests/browser_smoke_learning_system.mjs:439-479`

Trigger condition:

Tests cover useful slices: v3 schema/child shell/current-step submit/job queue/evidence gate/child projection (`tests/test_learning_system.py:713-1707`), model router behavior (`tests/test_learning_system.py:1941-2184`), and legacy learning-group behavior (`tests/test_learning_system.py:6095-6789`). Browser smoke verifies pending evidence should not evolve and child output should not expose evolution internals (`tests/browser_smoke_learning_system.mjs:305-310`, `tests/browser_smoke_learning_system.mjs:439-479`). But these do not prove the v5 end-to-end loop.

Impact:

Green tests can be mistaken for v5 runtime readiness while the actual daily-flow path still lacks worker completion, evidence-gated evaluation, next-step decisions, and summary lineage.

Required fix boundary:

Define v5 acceptance tests mapped to PRD AC-01 through AC-26 and add the addendum trace matrix: child submission, review pipeline, session close, model adapter, evidence lineage, restart/retry. Separate legacy regression tests from v5 release gates.

Validation expectation:

At least one scenario must trace the same sample through browser/API/DB/report after restart. Mock-only tests can validate state mechanics but cannot prove answer-analysis, teaching quality, question quality, or planner reasonability.

## Residual Risk

The current codebase has useful v3 skeleton pieces: durable DB tables, unique indexes, job queue mechanics, model route resolution, evidence gate predicates, graph lineage helpers, candidate packet generation, and child projection tests. These are good starting points for 听云's technical reverse and technical plan. They are not enough for v5 runtime cutover because the producer/consumer chain is incomplete.

## Required Next Action

1. 听云 should produce `TECHNICAL_REVERSE_SPEC` focused on the current split between legacy fixed-group and v3 daily-flow runtime.
2. 听云 should then produce `TECHNICAL_PLAN v5` only after source readiness passes, with explicit decisions for:
   - canonical v5 state machine
   - v5 queue worker/recovery/reconciler
   - model adapter result envelope
   - evidence gate consumer contracts
   - summary lineage/freshness
   - child API allowlist
   - graph/question target selection
   - legacy fixed-group deprecation/compatibility boundary
   - v5-specific tests and false-pass separation
3. 镜花 should rereview the technical plan/contract before skeleton or implementation proceeds.

Stop condition met: `DESIGN_REVIEW_NEEDS_FIX`.
