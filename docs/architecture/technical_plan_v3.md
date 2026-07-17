# AI Native Math Learning System Technical Plan v3

Status: reviewed baseline, ready for v3 skeleton planning
Owner: 听云 (`tingyun`)
Created: 2026-07-10 CST
Scope: technical direction for PRD v3 plus first implementation slice contract
Review log: initial 镜花 `DESIGN_REVIEW_NEEDS_FIX`, 霜弦
`DATA_REVIEW_NEEDS_FIX`, 观止 `QA_NEEDS_FIX`; revised by 听云; focused
re-review passed with scope from 镜花, 霜弦, and 观止.

This file is a planning artifact only. It does not claim implementation,
review PASS, QA PASS, or release readiness.

## Sources And Evidence

Collaboration and role sources:

- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/roles/tingyun.md`
- `docs/collaboration/inbox.md`
- `docs/collaboration/playbooks/artifact-contracts.md`

Product and architecture sources:

- `docs/product/ai_native_math_learning_prd_v3.md`
- `docs/architecture/ai_native_learning_system_architecture_v3.md`
- `docs/architecture/daily_learning_runtime_contract_v1.md`
- `docs/project-index.md`
- `docs/domain-index/math-learning.md`
- `docs/architecture/technical_plan_v2.md`
- `docs/architecture/code_skeleton_pass_v2.md`

Current implementation facts checked:

- `learning_system/db.py`
- `learning_system/server.py`
- `learning_system/model_router.py`
- `learning_system/auto_review.py`
- `learning_system/orchestrator.py`
- `learning_system/planner.py`
- `learning_system/question_bank.py`
- `learning_system/flow_nodes.py`
- `learning_system/internal_agents.py`
- `learning_system/agents.py`
- `app/local_learning_system/app.js`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `scripts/simulate_child_learning_journey.py`
- `scripts/audit_question_bank_grade_level.py`

Environment note:

- `git status --short` failed with `fatal: not a git repository`. This plan
  therefore does not rely on git rollback or diff evidence. Implementation must
  use additive schema changes, explicit file backups only when authorized, and
  validation artifacts rather than git state.

## TECHNICAL_PLAN - 听云（agentKey: `tingyun`）- 2026-07-10 CST

Objective:

Convert PRD v3 and the Daily Learning Runtime Contract into a stable
implementation direction for a single-child, graph-bound, one-current-step math
learning system. The full v3 direction covers review, new knowledge, agents,
reports, model routing, and QA seams. The first implementation slice is limited
to the runtime skeleton and old-knowledge review hot path.

Scope:

- Full v3 direction:
  - one child Web surface only;
  - parent/Codex progress through persisted DB/report evidence only;
  - deterministic Learning Flow Runtime;
  - Graph Runtime Service;
  - Question Bank Service candidate packet;
  - model-router-only agent calls;
  - answer analysis, evidence gate, evaluation, planner, and teaching seams;
  - late evidence reconciliation;
  - child-safe projection;
  - report labels and operator/Codex query surfaces;
  - future agent Knowledge Packs and proposal-only self-evolution.
- First implementation slice:
  - `daily_flow` and `flow_step` runtime skeleton;
  - old-knowledge review mode hot path;
  - current-step child API;
  - answer/photo persistence;
  - async answer-analysis job hook;
  - evidence gate;
  - planner candidate packet from Question Bank Service;
  - conservative node-state update hook;
  - next-step decision record;
  - child-safe summary;
  - recovery, idempotency, and late-evidence audit hooks;
  - `ready_for_new_knowledge`, teaching-step shell, and test hooks only.

Non-goals:

- No parent Web dashboard.
- No multi-user/auth/SaaS/admin surface.
- No fixed 10-question worksheet generated up front.
- No external textbook or commercial question-bank ingestion.
- No automatic self-evolution mutating graph, active bank, mastery, or next plan.
- No broad replacement of SQLite in the first slice.
- No production code implementation in this document task.
- No claim that v3 UI visual design, DATA_CONTRACT_SPEC v3, or QA v3 is already
  complete.

Project boundary overlay:

- Source: PRD v3 `PROJECT_BOUNDARY_OVERLAY`, `AGENTS.md`, and
  `docs/domain-index/math-learning.md`.
- Stable facts applied:
  - users are exactly the son and the parent;
  - the son uses one Web page;
  - the parent uses Codex only;
  - normal learning cannot depend on parent grading or copying results;
  - every question, step, attempt, analysis, evaluation, plan, teaching package,
    summary, and report claim must bind to `graph_node_id` and `graph_version`;
  - runtime/service/gate own execution, persistence, idempotency, recovery,
    evidence gating, and child-safe projection;
  - agents own semantic judgment/generation only and cannot directly mutate
    state;
  - planner must not receive the whole question bank;
  - pending, invalidated, stale, mock-only, missing-lineage, low-confidence, or
    operator-attention evidence cannot drive mastery or planning.

Product structure spec:

- Consumed from PRD v3 `PRODUCT_STRUCTURE_SPEC`.
- The product module boundary is preserved:
  `Child Learning Surface`, `Daily Learning Runtime`, `Graph Runtime Service`,
  `Question Bank Service`, `Planner Agent`, `Answer Analysis Agent`,
  `Evidence Gate`, `Evaluation Agent`, `Teaching Agent`, `Model Router`,
  `Report/Codex Surface`, and async bank maintenance.

UX flow spec:

- A dedicated UX_FLOW_SPEC v3 is still required before final child UI polish.
- For the first slice, the runtime/API contract can proceed from PRD v3 and the
  runtime contract because the UI surface and states are already constrained:
  one child page, one current step, open text answer, photo upload, honest
  waiting/blocked states, ready-for-new-knowledge transition, teaching shell,
  child-safe summary, no internals.

Data contract spec:

- A dedicated DATA_CONTRACT_SPEC v3 is still required before final data/content
  gate.
- For the first slice, this plan uses the canonical data/state meaning embedded
  in PRD v3 and architecture v3:
  graph version lineage, active-use question gate, attempt evidence statuses,
  analysis validation, evidence gate, mastery decision provenance, next-step
  decision provenance, and report labels.

Facts checked:

- Current code is v2-oriented. The child page loads `/api/child-bootstrap`,
  sees `today_plan.tasks`, submits `task_position` to `/api/child-submissions`,
  and closes a fixed learning group through
  `/api/learning-sessions/current-learning-group/complete`.
- Current DB has useful ledger assets:
  `graph_nodes`, `question_items`, `learning_sessions`, `attempts`,
  `attempt_attachments`, `learner_node_status`, `agent_runs`,
  `mastery_decisions`, `question_review_records`, `background_jobs`, and report
  helpers.
- Current DB does not yet have `daily_flow`, `flow_step`, `review_target`,
  `evidence_validation`, `next_step_decision`, `late_evidence_reconciliation`,
  or `daily_summary` tables.
- Current `attempts` already carry `evidence_status`, `grading_status`,
  `answer_analysis_json`, `review_meta_json`, and `cause_analysis_json`, but do
  not carry first-class `flow_step_id`, `graph_version`, `analysis_status`, or
  evidence-gate status.
- Current `background_jobs` is durable enough for local first-slice use but is
  session/attempt oriented and only allows `answer_review`.
- Current `model_router.py` already has provider aliasing, GPT defaults,
  Doubao vision default, DeepSeek/Doubao JSON compatibility, response-format
  fallback, and secret-free route status helpers.
- Current `auto_review.py` already treats reference answers as rubric context,
  calls through `model_router`, distinguishes reasoning dimensions, rejects
  malformed analysis, and can keep evidence pending on missing config,
  low-confidence OCR, malformed model output, or low confidence.
- Current `question_bank.py` and tests have stronger bank quality than earlier
  demos: 56 graph nodes, 20 current graph-generated items per node, reviewer
  records, high-signal gates, duplicate/core-family checks, and active-use
  predicates.
- Current tests are broad for v2 but do not yet prove a v3 continuous
  `daily_flow` current-step runtime or late-evidence-safe next-step loop.

Current architecture:

- Local stdlib HTTP server in `learning_system/server.py`.
- Vanilla child UI under `app/local_learning_system/`.
- SQLite ledger initialized by `learning_system/db.py` and
  `scripts/init_learning_system_db.py`.
- Existing v2 flow:
  generated plan -> fixed task group -> child submits positions -> async answer
  review -> close session -> next generated plan.
- Target v3 flow:
  daily flow -> build review targets -> select exactly one current step ->
  submit response -> analyze/validate/evaluate -> decide next step -> repeat,
  teach, ready-for-new-knowledge, or summarize.

Architecture decisions:

- sync_vs_async:
  - Synchronous path is only validation, persistence, current-step projection,
    and safe deterministic state transitions.
  - Answer analysis, OCR, evaluation, planner, and teaching generation run
    through queued jobs or short bounded calls behind runtime gates.
  - The child never waits for hidden work unless the next visible step depends
    on that evidence and no independent safe step exists.
  - First slice uses conservative behavior: after a dependent answer, show an
    honest analyzing state; if an independent approved review target exists,
    runtime may select it without using pending evidence.

- model_provider_choice:
  - Default text route: GPT-compatible `gpt-5.5`.
  - Default vision route: Doubao-compatible
    `doubao-seed-2-0-pro-260215`.
  - DeepSeek and future providers are allowed only through
    `model_router.call_structured_json` compatibility modes.
  - First slice adds route definitions for planner/evaluation/teaching but may
    keep deterministic fallback paths for tests and model-disabled operation.
  - Model outputs never mutate runtime state directly; gates validate schema,
    lineage, confidence, and child-safe projection first.

- service_api_boundary:
  - `DailyLearningRuntime` is the only component that creates or advances
    `daily_flow` and `flow_step`.
  - `GraphRuntimeService` owns graph lookup, prerequisite summaries, rollback
    candidates, graph version/hash, and graph-binding validation.
  - `QuestionBankService` owns active-use filtering and compact candidate
    packet construction.
  - `EvidenceGate` owns reusable predicates and evidence validation records.
  - `ModelRouter` owns all external model calls.
  - Agents return structured packages only; runtime records accepted/rejected
    decisions and applies state changes.

- data_state_contract:
  - SQLite remains the first-slice local evidence ledger.
  - Schema changes must be additive and old rows remain auditable.
  - Existing v2 `learning_sessions` can remain for legacy/operator paths, but v3
    child flow uses new `daily_flows`/`flow_steps`.
  - To avoid a disruptive attempts rewrite, a `daily_flow` may create a backing
    `learning_sessions` row with mode `daily_flow_v3`; `attempts.session_id`
    continues to satisfy the current foreign key while `flow_steps.attempt_id`
    links the response to the current-step runtime.
  - `usable` is implemented as a predicate, not a stored status. Stored gate
    rows may record `gate_status=passed`, but `passed` maps to the PRD/API
    evidence-validation result `usable` only after
    `EvidenceUsePredicate.is_usable(...)` rechecks lineage, current graph and
    bank versions, analysis validity, and non-mock provider status. Consumers
    must call the predicate before mastery/planning/report-confirmed claims.

- queue_task_state:
  - First slice uses the existing `background_jobs` table through a new queue
    service wrapper.
  - Additive columns should include `flow_id`, `flow_step_id`,
    `idempotency_key`, `lease_owner`, `lease_expires_at`, `available_at`,
    `locked_at`, `retry_after`, `dead_letter_reason`, `depends_on_job_id`, and
    `route_meta_json`.
  - Supported first-slice job types:
    `answer_analysis`, `evaluation_update`, `planner_decision`,
    `teaching_generation`, with `answer_review` kept as a legacy alias.
  - Worker recovery scans queued/running stale jobs, pending attempts without
    jobs, model outputs not applied to attempts, and flows stuck in analyzing.

- failure_retry_idempotency:
  - One active `daily_flow` per child/date unless superseded.
  - One visible current `flow_step` per active flow.
  - One active attempt per flow step.
  - One active answer-analysis job per attempt version.
  - One evidence validation record per attempt analysis version.
  - One mastery decision per accepted evidence package.
  - One next-step decision per flow revision.
  - Child submit requires `step_handle`, `position`, and
    `client_idempotency_key`.
  - Repeated polling must not create steps; repeated submit returns the original
    receipt when the idempotency key matches.

- rollback_recovery:
  - Old evidence is never silently deleted.
  - Wrong, contaminated, graph-mismatched, or version-stale evidence is marked
    `invalidated` or `stale`.
  - Late evidence is recorded immediately but only applied at safe transition
    points.
  - If model config is missing, the attempt remains pending/blocked with
    operator-visible reason; the child sees a safe message, not fake grading.
  - Feature rollback should use a runtime flag such as
    `V3_DAILY_RUNTIME_ENABLED=0` to fall back to v2 child projection while
    preserving additive tables.

Alternatives considered:

- Keep v2 fixed-group flow and improve prompts: rejected. It keeps the product
  failure that PRD v3 explicitly corrects.
- Replace SQLite with MySQL/Postgres now: rejected for first slice. Current
  single-child local scope and existing SQLite ledger are sufficient; additive
  schema plus queue wrapper preserves a later migration path.
- Let planner agent search all question rows: rejected. It violates hot-path
  efficiency and would make model cost/latency unstable.
- Generate each next question live from the model: rejected for the hot path.
  Bank maintenance may be async; child scheduling uses reviewed active slots.
- Store `usable` as a status field: rejected. `usable` remains a derived
  predicate over stored statuses, lineage, validation, and current graph/bank
  versions.
- Start with full new-knowledge teaching intelligence: deferred. First slice
  only exposes readiness state, teaching shell, and tests hooks.

Decision rationale:

The existing system has useful evidence, bank, model-router, and child-safe
assets. The problem is not lack of code; it is that the central runtime state is
the wrong shape. The least risky v3 path is an additive runtime layer that
reuses the ledger, router, question bank, and answer-analysis adapter while
replacing the child mainline from fixed session groups to a `daily_flow` state
machine.

Blueprint requirement:

This is a high-risk, multi-module, stateful change. Before implementation, use
the `ENGINEERING_CONTRACT` and `IMPLEMENTATION_BLUEPRINT` below. Implementation
should then create a skeleton pass and stop for review/test-case design before
business logic fill unless 若命/user explicitly waives that gate.

Risks and tradeoffs:

- The v3 runtime may coexist with v2 code for a while. Mitigation: route-level
  feature flag, clear legacy/v3 function names, tests proving v3 child payload
  does not contain v2 fixed `today_plan.tasks`.
- SQLite in-process queue is not a cloud queue. Mitigation: idempotency keys,
  recovery scanning, stale-running unlock, and adapter seam.
- Live model semantic quality cannot be proven by unit tests. Mitigation:
  separate mock/recorded/live QA labels and persisted `agent_runs`.
- DATA_CONTRACT_SPEC v3 and UX_FLOW_SPEC v3 are not final. Mitigation: first
  slice keeps UI minimal and data additive; final release needs 清秋/霜弦 review.
- New `graph_version` must be consistent. Mitigation: central
  `GraphRuntimeService.current_graph_version()` and tests that all v3 rows carry
  the same version.

Validation strategy:

- Unit tests for schema migration, current-step idempotency, evidence gate,
  candidate packet filtering, planner decisions, and recovery.
- Integration tests for child API:
  open page -> start review -> see one step -> submit text/photo -> queued
  analysis -> evidence gate -> next step/summary.
- Model-disabled tests proving missing config becomes blocked/pending, not fake
  grading.
- Recorded/mock model tests for answer-only, wrong-reason-right-answer, stuck,
  blank, photo usable/unusable, and symbol/unit cases.
- Browser tests for one-current-step rendering, no raw ids/internals, honest
  waiting, ready-for-new-knowledge, teaching shell, summary labels, and mobile
  layout.
- Report tests proving Codex-readable facts come from DB rows and labels, not
  stale `latest` text.

Files likely touched:

- `learning_system/db.py`
- `learning_system/daily_runtime.py` (new)
- `learning_system/graph_runtime.py` (new)
- `learning_system/evidence_gate.py` (new)
- `learning_system/job_queue.py` (new)
- `learning_system/question_bank.py`
- `learning_system/planner.py`
- `learning_system/model_router.py`
- `learning_system/auto_review.py`
- `learning_system/server.py`
- `learning_system/reports.py`
- `learning_system/internal_agents.py`
- `app/local_learning_system/app.js`
- `app/local_learning_system/index.html`
- `app/local_learning_system/styles.css`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `scripts/simulate_child_learning_journey.py`
- `scripts/generate_daily_report.py`

Open questions:

- UX copy and visual density require 清秋 v3 review before final UI release.
- DATA_CONTRACT_SPEC v3 should confirm final column/table names and report label
  vocabulary before code fill.
- Long-run A/B/C/D mastery thresholds remain conservative until real multi-day
  evidence exists.
- Whether all QA runs use live providers or recorded provider samples remains a
  QA-mode decision; reports must label provider mode.

Stop condition:

This technical plan is ready for 镜花/霜弦/观止 review when the first-slice
contract below is concrete enough to implement without guessing runtime state,
interfaces, field meanings, or validation commands.

## ENGINEERING_CONTRACT - 听云（agentKey: `tingyun`）- 2026-07-10 CST

Objective:

Define the first implementation slice contracts for runtime skeleton + old
knowledge review hot path + current-step child API + evidence gate + planner
candidate packet + child-safe summary.

Scope:

- Add v3 runtime tables and service modules.
- Keep existing v2 evidence ledger and model/question assets.
- Migrate child mainline API to current-step projection.
- Preserve legacy endpoints as operator/compatibility paths until v3 is proven.
- New-knowledge implementation is limited to readiness state, teaching shell,
  and test hooks.

Non-goals:

- No full new-knowledge teaching intelligence.
- No production self-evolution mutator.
- No MySQL/Postgres migration.
- No parent dashboard.
- No fixed worksheet generation.
- No direct model call outside `model_router`.

Project boundary overlay:

Applied from PRD v3 and `AGENTS.md`.

Product structure spec:

Applied from PRD v3 `PRODUCT_STRUCTURE_SPEC`.

UX flow spec:

First slice uses PRD v3 child-state constraints; full UX_FLOW_SPEC v3 remains a
required review input before final UI polish.

Data contract spec:

First slice uses PRD v3 canonical data/state vocabulary and architecture v3.
DATA_CONTRACT_SPEC v3 review by 霜弦 remains required before final data gate.

Facts checked:

- Existing `record_attempt()` only enforces expected question membership for
  `learning_sessions.mode == 'child_learning_group'`, so a `daily_flow_v3`
  backing session can reuse attempts without fixed expected question ids.
- Existing `db.is_current_usable_attempt_evidence()` is a strong starting point
  but must be wrapped/extended to include `graph_version`, `flow_step_id`,
  analysis status, and late-evidence state.
- Existing `find_question_for_node()` returns one active question, not a compact
  planner candidate packet. A new `QuestionBankService` function is needed.
- Existing background worker is session-oriented and can process pending
  attempts concurrently, but v3 needs step/flow-aware idempotency and recovery.

Interface contracts:

| Interface | Type | Method/route | Request/input | Response/output | Errors | Auth/permission |
|---|---|---|---|---|---|---|
| Child bootstrap | backend_api | `GET /api/child-bootstrap` | none | `schema_version=3.0.0-daily-flow`, `child_state`, optional `current_step`, optional `summary`, optional `ready_for_new_knowledge` | DB/graph unavailable returns child-safe retry/blocked payload | Child; no raw ids or internals |
| Start review | backend_api | `POST /api/daily-flow/review/start` | optional `{client_day_key}` | current child projection; creates/resumes review mode | duplicate active flow resumes; graph unavailable blocks safely | Child; no raw ids |
| Submit current step | backend_api | `POST /api/current-step/submit` | `step_handle`, `position`, `client_idempotency_key`, `answer_text?`, `answer_photo_data_url?`, `answer_photo_name?`, `stuck?` | receipt with `submission_state=saved`, `next_poll_after_ms`, child-safe message | empty evidence, handle mismatch, duplicate conflict, photo invalid | Child; handle/position only |
| Poll current state | backend_api | `GET /api/child-bootstrap` | none | same as bootstrap; used for polling | child-safe retry/blocked | Child |
| Operator daily flow inspect | backend_api | `GET /api/operator/daily-flow/today` | none | id-rich flow, steps, attempts, jobs, evidence gates, decisions | DB error | Codex/operator only |
| Runtime load/create | service_interface | `DailyLearningRuntime.load_or_create_daily_flow(date)` | child/date | `DailyFlowProjection` | duplicate flow recovery, DB unavailable | Runtime only |
| Runtime start review | service_interface | `DailyLearningRuntime.start_review_mode(flow_id)` | flow id | target pool and current projection | graph unavailable, no target | Runtime only |
| Runtime submit | service_interface | `DailyLearningRuntime.persist_child_response(command)` | handle/position/idempotency/evidence | attempt, attachments, jobs | duplicate/mismatch/invalid evidence | Runtime only |
| Candidate packet | service_interface | `QuestionBankService.candidate_packet(node_id, graph_version, limits, exclusions)` | target node, cooldowns, recent questions | 5-8 metadata rows plus filter summary | no active candidates -> bank gap | Runtime/planner only |
| Evidence gate | internal_module | `EvidenceGate.validate_attempt(attempt_id, analysis_version)` | attempt + analysis + graph/bank version | gate record and predicate result | pending/rejected/blocked with reasons | Runtime only |
| Model route | internal_module | `model_router.*_route`, `call_structured_json` | route/payload/schema | JSON result + route mode metadata | disabled, timeout, malformed JSON | Agents only through router |
| Summary | service_interface | `DailyLearningRuntime.complete_summary(flow_id)` | flow id | child-safe summary + report facts | report generation fallback | Runtime/report |

Field contracts:

| Field | Owner/source | Type | Required/default | Allowed values | Old-data/null handling | Consumers |
|---|---|---|---|---|---|---|
| `daily_flows.id` | runtime | text | required | `DF-*` | n/a | runtime, child projection, reports |
| `daily_flows.local_date` | runtime | text | required | `YYYY-MM-DD` | n/a | one-flow-per-day rule |
| `daily_flows.mode` | runtime | text | `review_old_knowledge` once started | `not_selected`, `review_old_knowledge`, `new_knowledge` | old rows default `not_selected` | runtime, child |
| `daily_flows.status` | runtime | text | `new` | `new`, `reviewing`, `ready_for_new_knowledge`, `learning_new`, `paused`, `completed`, `blocked`, `superseded` | unknown -> block/operator attention | runtime, child, report |
| `daily_flows.graph_version` | graph service | text | required | asset version + content hash | missing -> stale/missing_lineage | all v3 rows |
| `daily_flows.current_step_id` | runtime | text/null | nullable | known `flow_steps.id` | null means choose/start/summary state | child projection |
| `daily_flows.legacy_session_id` | runtime/db compat | text | required first slice | `learning_sessions.id` with mode `daily_flow_v3` | missing -> recovery creates or blocks | attempts FK compat |
| `flow_steps.id` | runtime | text | required | `FS-*` | n/a | runtime, attempts |
| `flow_steps.step_handle` | runtime projection | text | required unique active handle | opaque, non-id-like | old/null not child-visible | child API |
| `flow_steps.position` | runtime | integer | required | positive increasing | n/a | child API |
| `flow_steps.step_type` | runtime/planner | text | required | `question`, `teaching`, `interactive_check`, `clarification`, `summary`, `ready_for_new_knowledge` | unknown -> block projection | child/runtime |
| `flow_steps.status` | runtime | text | `selected` | `selected`, `displayed`, `responded`, `analyzing`, `evaluated`, `superseded`, `blocked` | unknown -> operator attention | runtime |
| `flow_steps.node_id` | graph service | text | required except summary | known graph node | missing -> missing_lineage | gate/planner/report |
| `flow_steps.question_id` | bank service | text/null | required for question step | active eligible question id | stale -> block/reselect | attempts/analysis |
| `flow_steps.expected_evidence_json` | planner/runtime | JSON text | `{}` | process/answer/photo/check expectations | empty blocks process mastery | answer analysis/gate |
| `review_targets.status` | runtime/planner | text | `candidate` | `candidate`, `active`, `skipped`, `completed`, `blocked`, `pending` | unknown -> rebuild target pool | planner/report |
| `attempts.flow_step_id` | runtime | text/null | required for v3 attempts | known `flow_steps.id` | legacy null allowed | gate/report |
| `attempts.graph_version` | graph service/runtime | text | required for v3 attempts | current graph version | legacy empty -> missing_lineage/stale | gate/report |
| `attempts.evidence_status` | runtime/operator | text | `active` | `active`, `invalidated`, `stale` | legacy active accepted if lineage passes | gate |
| `attempts.grading_status` | answer analysis | text | `pending_review` | `pending_review`, `graded`, `blocked` | legacy values mapped conservatively | gate/report |
| `attempts.analysis_status` | evidence gate | text | `missing` | `missing`, `valid`, `invalid_analysis`, `low_confidence`, `mock_only`, `operator_attention_required` | missing column/default -> `missing` | gate/planner |
| `evidence_validations.gate_status` | evidence gate | text | required | `passed`, `pending`, `rejected`, `blocked` | no row -> not usable | planner/evaluation/report |
| `next_step_decisions.action` | planner/runtime | text | required | `continue_review`, `same_structure_retest`, `near_transfer_retest`, `prerequisite_probe`, `micro_teach`, `enter_new_knowledge`, `ask_clarification`, `daily_summary`, `ready_for_new_knowledge` | unknown rejected | runtime |
| `daily_summaries.report_label_json` | report service | JSON text | required | confirmed/pending/blocked/inferred/stale/mock_only/missing_lineage claims | missing -> minimal summary only | child/Codex |

Graph lineage and provenance contract:

Every v3 row that can affect child state, mastery, planning, or report claims
must carry enough graph/question/evidence lineage for a later Codex query to
reconstruct why the row exists. Missing lineage does not make the row invisible;
it makes it non-confirming.

| Table/object | Required graph/version fields | Required source/provenance fields | Old-data/null behavior | Consumers |
|---|---|---|---|---|
| `daily_flows` | `graph_version`, `planned_graph_node_ids_json`, `question_bank_version` | `legacy_session_id`, `flow_revision`, `created_by_runtime_version`, `source_plan_id` nullable | missing graph or bank version -> flow can resume only as `blocked` or `missing_lineage` summary; cannot create confirmed claims | runtime, child projection, report |
| `flow_steps` | `graph_version`, `node_id` except summary, `question_bank_version`, `question_id` for question steps | `flow_id`, `position`, `step_handle`, `source_review_target_id`, `source_next_step_decision_id`, `candidate_packet_id`, `attempt_id` nullable until response | missing node/version -> do not display as question/teaching; block or project safe retry | child projection, attempt, gate, report |
| `review_targets` | `graph_version`, `node_id`, `prerequisite_node_ids_json`, `question_bank_version` | `flow_id`, `source_status_id`, `source_mastery_decision_id`, `source_attempt_ids_json`, `priority`, `reason_json` | legacy status-only target becomes `candidate` with `missing_lineage=true`; planner may use as hint, not confirmed target | runtime, planner, summary |
| `attempts` | `graph_version`, `node_id`, `question_id`, `question_bank_version` | `flow_step_id`, `attempt_version`, `client_idempotency_key`, `answer_source`, attachment ids, `legacy_session_id` via `session_id` | legacy attempts lacking `flow_step_id`/`graph_version` are auditable only; v3 labels them `missing_lineage` unless migrated by an explicit compatibility rule | answer analysis, evidence gate, report |
| `evidence_validations` | `graph_version`, `node_id`, `question_id`, `question_bank_version` | `attempt_id`, `attempt_version`, `analysis_version`, `answer_analysis_agent_run_id`, `gate_version`, `failed_fields_json`, `gate_status` | no validation row -> not usable; mismatched version -> stale/rejected | evaluation, planner, report |
| `mastery_decisions` | `graph_version`, `node_id`, `question_bank_version` | `source_attempt_ids_json`, `source_evidence_validation_ids_json`, `evaluation_agent_run_id`, `decision_version`, `old_status_id`, `new_status_code`, `dimension_scores_json` | legacy decisions without graph/bank/source validation ids are not planner-usable; report label `missing_lineage` or `stale` | learner status, planner, report |
| `learner_node_status` | `graph_version`, `node_id`, `question_bank_version` | `mastery_decision_id`, `source_attempt_ids_json`, `source_evidence_validation_ids_json`, `updated_by_agent_run_id`, `status_revision`, `status_reason` | legacy rows are status hints only; they must be recomputed from current mastery decisions before driving review target or confirmed plan | review target builder, planner, report |
| `next_step_decisions` | `graph_version`, `target_node_id`, `question_bank_version` | `flow_id`, `flow_revision`, `source_step_id`, `source_attempt_ids_json`, `source_evidence_validation_ids_json`, `source_mastery_decision_ids_json`, `candidate_packet_id`, `candidate_packet_hash`, `planner_agent_run_id`, `decision_status`, `branch_policy_json`, `report_label` | missing source ids or stale graph/bank version -> decision can be displayed only as fallback/blocked/pending, never confirmed | runtime, child projection, report |
| `late_evidence_reconciliations` | `graph_version`, `node_id`, `question_bank_version` | `flow_id`, `late_attempt_id`, `late_analysis_version`, `late_validation_id`, `visible_step_id_at_arrival`, `safe_transition_step_id`, `applied_mastery_decision_id`, `planner_reconsideration_decision_id`, `included_in_summary` | missing safe transition -> record `pending_safe_transition`; cannot rewrite visible step | runtime recovery, planner, summary |
| `daily_summaries` | `graph_version`, `touched_node_ids_json`, `question_bank_version` | `flow_id`, `source_step_ids_json`, `source_attempt_ids_json`, `source_evidence_validation_ids_json`, `source_mastery_decision_ids_json`, `source_next_step_decision_ids_json`, `late_evidence_included_ids_json`, `late_evidence_excluded_ids_json`, `summary_version` | missing source ids -> minimal summary with `missing_lineage`; no confirmed claims | child summary, Codex report |

Planner-usable `learner_node_status` and `mastery_decisions`:

- A `learner_node_status` row is planner-usable only when it references a
  current `mastery_decision_id`.
- That mastery decision must reference source attempts that all pass
  `EvidenceUsePredicate.is_usable(...)` under the same `graph_version` and
  active `question_bank_version`.
- Its `source_evidence_validation_ids_json` must all point to validations with
  `gate_status=passed`, current attempt/analysis versions, non-mock provider
  status, active question review records, and no stale graph/bank lineage.
- Legacy `learner_node_status` rows without `graph_version`,
  `mastery_decision_id`, and source validation ids may help target discovery as
  `missing_lineage` hints only. They cannot drive `confirmed` report claims,
  `A` mastery skip, or `ready_for_new_knowledge` by themselves.
- If a graph or bank version changes, affected status rows remain auditable but
  become planner-unusable until recomputed or migrated by an explicit
  compatibility rule that writes a new mastery decision.

Evidence vocabulary mapping:

| Storage field | Stored values | PRD/API projection | Can drive mastery/planning? | Notes |
|---|---|---|---|---|
| `attempts.evidence_status` | `active`, `invalidated`, `stale` | same | only `active` can pass predicate | `stale` is explicit after graph/bank version drift |
| `attempts.grading_status` | `pending_review`, `graded`, `blocked` | same | only `graded` can pass predicate | `blocked` may drive clarification, not mastery |
| `attempts.analysis_status` | `missing`, `valid`, `invalid_analysis`, `low_confidence`, `mock_only`, `operator_attention_required` | same | only `valid` and non-mock can pass predicate | mock-only is preserved for QA/provider integrity |
| `evidence_validations.gate_status` | `passed`, `pending`, `rejected`, `blocked` | `usable`, `pending`, `rejected`, `blocked` | only `passed` plus full predicate maps to `usable` | `passed` alone is not sufficient |
| Report claim label | n/a | `confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`, `missing_lineage` | only `confirmed` | precedence below applies |

The code must not store a bare attempt status called `usable`. It may project
`gate_status=passed` as `evidence_validation=usable` only for API/report
readability and only when the full predicate succeeds.

Candidate packet exact schema:

The planner hot path receives a packet object with a stable id and hash:

```json
{
  "packet_id": "CP-*",
  "packet_schema_version": "2026-07-10.v3.candidate-packet",
  "graph_version": "metadata.version+sha256",
  "question_bank_version": "QB* or explicit bank version",
  "target_node_id": "graph node id",
  "flow_id": "DF-*",
  "flow_revision": 1,
  "source_review_target_id": "RT-*",
  "candidate_count": 5,
  "filter_summary": {
    "active_rows_seen": 0,
    "excluded_stale": 0,
    "excluded_inactive": 0,
    "excluded_duplicate": 0,
    "excluded_cooldown": 0,
    "excluded_mastered_extra": 0,
    "excluded_missing_lineage": 0
  },
  "candidates": []
}
```

Each candidate row must contain exactly the hot-path metadata needed by the
planner and must not contain full reference answers, solution steps, full
rubrics, or common-wrong-path bodies:

| Candidate row field | Required | Meaning |
|---|---|---|
| `question_id` | yes | active question id; opaque to child |
| `node_id` | yes | primary graph node id and must match packet target or approved prerequisite/rollback target |
| `graph_version` | yes | current graph version assigned by `GraphRuntimeService` |
| `item_version` | yes | current item version |
| `review_record_id` | yes | durable active-use reviewer record |
| `question_family` | yes | family/diversity grouping |
| `variant_signature` | yes | variant/cooldown signature |
| `difficulty_vector` | yes | concept/model/procedure/transfer/expression/stretch dimensions |
| `evidence_goal` | yes | what evidence the question is meant to expose |
| `target_error_tags` | yes | canonical tags targeted |
| `requires_reasoning` | yes | boolean; false rows excluded unless explicit non-question clarification |
| `last_used_at` | yes nullable | recent-use/cooldown check |
| `why_candidate` | yes | concise deterministic reason |
| `filter_summary` | yes | per-row active-use and exclusion proof |
| `active_use_proof` | yes | `{active_eligible, reviewer_agent_key, reviewer_run_id, review_contract_version}` |
| `question_bank_version` | yes | bank version used for active-use proof |
| `lineage_status` | yes | `current`, `stale`, or `missing_lineage`; only `current` can be sent to planner |

v2 bank rows can enter v3 packets only after a deterministic backfill step
sets `graph_version = graph.metadata.version + sha256(graph_json)`,
`question_bank_version`, and an active `review_record_id` for the same
`item_version`. Rows lacking that proof are excluded before planner context and
counted in `filter_summary.excluded_missing_lineage`. After the planner selects
one candidate, runtime fetches the full question/rubric/solution package for
display and answer analysis; the planner model never receives the full bank or
solution banks.

Next-step decision schema:

`next_step_decisions` is a decision ledger, not a log string. Required fields:

| Field | Required | Allowed/meaning |
|---|---|---|
| `id` | yes | `NSD-*` |
| `flow_id`, `flow_revision` | yes | decision is bound to the current flow revision |
| `decision_status` | yes | `accepted`, `rejected`, `fallback`, `blocked` |
| `action` | yes | PRD/runtime action enum |
| `graph_version`, `question_bank_version` | yes | current lineage |
| `target_node_id` | yes nullable | null only for summary/block |
| `source_step_id` | yes nullable | previous step or null for initial selection |
| `source_attempt_ids_json` | yes | attempts considered |
| `source_evidence_validation_ids_json` | yes | validations considered |
| `source_mastery_decision_ids_json` | yes | mastery decisions considered |
| `review_target_id` | yes nullable | target that led to the decision |
| `candidate_packet_id`, `candidate_packet_hash` | required for question selection | proves compact packet context |
| `candidate_filter_summary_json` | required for question selection | skipped/excluded alternatives |
| `pending_evidence_ids_json` | yes | evidence intentionally not used |
| `skipped_node_ids_json` | yes | mastered/due/not-due alternatives and reasons |
| `branch_policy_json` | yes | correct/partial/wrong/stuck/answer-only/pending branches |
| `planner_agent_run_id` | nullable | required when model planner was used |
| `provider_mode` | yes | `deterministic`, `mock`, `recorded`, `live`, `not_configured` |
| `fallback_reason` | nullable | required for `fallback` or `blocked` |
| `stale_lineage_ids_json` | yes | stale evidence/targets excluded |
| `mock_source_ids_json` | yes | mock/recorded sources excluded from confirmed claims |
| `report_label` | yes | report label for this decision |
| `reason` | yes | concise operator-readable reason |

A decision can drive a confirmed next step only when
`decision_status=accepted`, `provider_mode` is not `mock` unless the claim is
explicitly scoped, lineage is current, candidate packet hash exists for question
actions, and all source evidence either passed the predicate or is explicitly
listed as pending/excluded. Missing required fields force
`decision_status=rejected|blocked` and report label `missing_lineage` or
`blocked`.

SQLite invariant and transaction contract:

Required version columns:

- `daily_flows.flow_revision`: increments whenever current step, status,
  target pool, summary, or reconciliation state changes.
- `flow_steps.step_revision`: increments when status/projection changes.
- `attempts.attempt_version`: starts at 1 and increments only if the same
  attempt receives a new analysis/application version.
- `attempts.analysis_version`: starts at 0, increments when a model or recorded
  analysis is accepted for validation.
- `next_step_decisions.decision_version`: starts at 1 for the flow revision.

Required unique or partial unique indexes in SQLite:

| Invariant | Index/constraint |
|---|---|
| One active flow per implicit child/date | unique partial index on `(child_key, local_date)` where `status in ('new','reviewing','ready_for_new_knowledge','learning_new','paused','blocked')` |
| One current displayed/selected step per active flow | unique partial index on `flow_steps(flow_id)` where `status in ('selected','displayed','analyzing') and superseded_by_step_id is null` |
| Unique step handle while visible | unique index on `flow_steps(step_handle)` |
| One active attempt per step | unique partial index on `attempts(flow_step_id)` where `evidence_status='active'` |
| Idempotent child submit | unique index on `(flow_step_id, client_idempotency_key)` for v3 attempts |
| One active job per idempotency key | unique partial index on `background_jobs(idempotency_key)` where `status in ('queued','claimed','running','waiting','retry')` |
| One validation per attempt analysis version | unique index on `evidence_validations(attempt_id, attempt_version, analysis_version, gate_version)` |
| One mastery application per evidence package | unique index on `mastery_decisions(node_id, graph_version, source_evidence_validation_hash, decision_version)` |
| One next decision per flow revision and source step | unique index on `next_step_decisions(flow_id, flow_revision, coalesce(source_step_id,''), decision_version)` |
| One summary per flow revision | unique index on `daily_summaries(flow_id, flow_revision, summary_version)` |

Submit transaction boundary:

1. Load current flow and step by `step_handle` and `position` inside one DB
   transaction.
2. Verify flow status, step status, graph version, and no superseding current
   step.
3. Check existing `(flow_step_id, client_idempotency_key)`.
4. If same key and same normalized evidence digest exists, return existing
   receipt.
5. If same step but different key/evidence already has active attempt, reject
   with child-safe reload/retry; do not create a second attempt.
6. Insert attempt, attachment metadata, evidence digest, attempt version, and
   analysis status `missing`.
7. Update step to `responded` or `analyzing`.
8. Enqueue `answer_analysis` job with idempotency key
   `answer_analysis:{attempt_id}:{attempt_version}`.
9. Increment `daily_flows.flow_revision`.
10. Commit. File upload writes must either complete before commit with cleanup
    on rollback, or use temp file + DB commit + atomic rename with mismatch
    repair on recovery.

Queue/worker lease and recovery state machine:

Job statuses:

`queued -> claimed -> running -> succeeded`

Alternative branches:

- `queued|claimed|running -> retry` after timeout or retryable provider/schema
  error.
- `retry -> queued` when `retry_after <= now`.
- `running -> waiting` when the job needs upstream evidence or safe transition.
- `waiting -> queued` when dependency/safe transition is satisfied.
- `queued|claimed|running|retry|waiting -> blocked` for missing config,
  invalid lineage, non-retryable schema failure, or operator-required action.
- `blocked -> dead_letter` after max attempts or explicit operator decision.

Required `JobQueue` methods:

| Method | Contract |
|---|---|
| `enqueue(job_type, idempotency_key, payload, depends_on_job_id=None)` | insert or return existing active job; payload validated before insert |
| `claim(worker_id, now, limit)` | atomically update eligible `queued/retry` rows to `claimed`, set `lease_owner`, `locked_at`, `lease_expires_at`; no two workers can claim same row |
| `start(job_id, worker_id)` | move `claimed` to `running` only for current lease owner |
| `heartbeat(job_id, worker_id)` | extend lease without changing versions |
| `finish(job_id, result_refs)` | mark succeeded, store output refs, enqueue dependent jobs if gates allow |
| `retry(job_id, reason, retry_after)` | increment run count, preserve last error, schedule retry |
| `wait(job_id, dependency_reason)` | wait for upstream validation or safe transition |
| `block(job_id, reason)` | fail closed with operator-visible reason |
| `dead_letter(job_id, reason)` | terminal failure after retry limit |
| `recover(now)` | unlock expired `claimed/running` leases, requeue due retries, create missing jobs for pending attempts, and detect unapplied outputs |

Required job payload version fields:

- `payload_schema_version`
- `flow_id`
- `flow_revision`
- `flow_step_id`
- `step_revision`
- `attempt_id`
- `attempt_version`
- `analysis_version` when applicable
- `graph_version`
- `question_bank_version`
- `question_id`
- `review_record_id`
- `candidate_packet_id` for planner jobs
- `depends_on`: source job ids or source validation ids
- `provider_mode`

Dependency order:

`answer_analysis -> evidence_validation -> evaluation_update -> planner_decision -> teaching_generation/current_step_projection`

Runtime may skip later jobs when evidence is not usable and can instead enqueue
`planner_decision` with a pending/clarification branch. No job may update
mastery or confirmed plan from pending, stale, invalidated, mock-only, or
missing-lineage evidence.

Late evidence safe transition:

- When a late `answer_analysis` or `evidence_validation` arrives for a step that
  is no longer the visible current step, runtime writes
  `late_evidence_reconciliations` immediately.
- If the current visible step is unanswered, runtime must not rewrite its
  prompt, expected evidence, node, question, or answer target.
- The late result can be applied only when current step is submitted, teaching
  interaction completes, child returns to summary, runtime pauses, or current
  step is explicitly superseded before display.
- If late evidence invalidates the current plan, runtime writes a
  `planner_reconsideration_decision_id` after the safe transition and labels the
  summary as including or excluding that late evidence.

Report label enum and precedence:

Allowed labels are exactly:

`confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`,
`missing_lineage`.

Precedence for a claim with multiple conditions:

1. `blocked`: required runtime/model/data path failed and no child-safe
   independent progress is available.
2. `stale`: graph/question/evidence version is not current.
3. `missing_lineage`: required source ids, graph version, bank version, gate row,
   or decision provenance is missing.
4. `mock_only`: source depends only on mock/fixture model evidence.
5. `pending`: analysis/OCR/evaluation/planner result is not complete or safe
   transition has not applied late evidence.
6. `inferred`: report is an operator inference from weak but non-blocking facts;
   cannot be used for mastery/planning.
7. `confirmed`: all required source rows are current, non-mock, lineage-complete,
   and pass the relevant predicate.

Report tests must cover all seven labels, and especially `stale`, `mock_only`,
and `missing_lineage`. `confirmed` must be impossible unless the same evidence
is planner/mastery usable under current `graph_version` and
`question_bank_version`.

Call chain:

| Step | Caller | Callee | Sync/async | Transaction/state boundary | Failure/retry behavior |
|---|---|---|---|---|---|
| 1 | child page | `GET /api/child-bootstrap` | sync | read or create/resume flow | DB/graph fail -> child-safe blocked/retry |
| 2 | child page | `POST /api/daily-flow/review/start` | sync | create flow/backing session/targets/current step | idempotent resume if already reviewing |
| 3 | runtime | `QuestionBankService.candidate_packet` | sync deterministic | no model; read active bank metadata | no candidate -> bank gap + teaching/alternate target |
| 4 | runtime | planner selection | bounded sync or queued | writes `next_step_decision` and `flow_step` after gate | model fail -> deterministic safe fallback or block |
| 5 | child page | `POST /api/current-step/submit` | sync persistence | write attempt/attachment/job; mark step responded/analyzing | duplicate idempotency returns receipt |
| 6 | job worker | answer analysis route | async | record `agent_runs`, analysis, attempt statuses | disabled/timeout/malformed -> pending/blocked |
| 7 | worker/runtime | `EvidenceGate.validate_attempt` | sync gate | write evidence validation | rejected evidence cannot drive planning |
| 8 | worker/runtime | evaluation update hook | bounded sync or queued | write `mastery_decision` only from usable predicate | invalid output -> no status update |
| 9 | worker/runtime | planner next-step | bounded sync or queued | write `next_step_decision` and next `flow_step` or summary | pending-safe fallback or blocked |
| 10 | child page polling | `GET /api/child-bootstrap` | sync | project current state only | no duplicate state changes |

Async/queue decisions:

- async_boundary:
  child submission returns after durable save and job enqueue.
- queue_or_task:
  SQLite `background_jobs` via `learning_system/job_queue.py` wrapper.
- idempotency_key:
  `current_step_submit:{flow_id}:{step_id}:{client_idempotency_key}` and
  `answer_analysis:{attempt_id}:{attempt_version}`.
- timeout_retry_backoff:
  answer analysis text 3-8s target, photo 8-20s target; retry once for schema
  incompatibility, then pending/blocked with model route metadata.
- cancellation_recovery:
  no hard cancellation in first slice; stale `running` jobs are unlocked on
  server start/bootstrap after timeout and retried idempotently.

Storage/scale decisions:

- database/schema/index:
  SQLite additive tables/columns plus the enforceable unique/partial unique
  indexes listed in `SQLite invariant and transaction contract`. Non-unique
  read indexes may also be added for `daily_flows(local_date,status)`,
  `flow_steps(flow_id,status,position)`,
  `review_targets(flow_id,status,priority)`, `background_jobs(flow_id,status)`,
  and `evidence_validations(attempt_id,created_at)`, but those are not a
  substitute for invariants.
- partitioning_or_sharding:
  not applicable for single-child local phase; preserve table names and service
  wrappers for later migration.
- expected volume trigger:
  if daily rows exceed local performance needs or multiple children are added,
  replace queue/storage adapter before productizing.
- migration/backfill:
  no destructive migration. Existing v2 sessions remain legacy; v3 starts new
  additive rows. Legacy attempts with no `flow_step_id` remain reportable only
  through legacy reports or labeled `missing_lineage` in v3 reports.

External side effects:

- Local DB writes, local upload file writes, and configured model API calls only.
- No secrets written to DB/docs/reports/screenshots.
- No external platform/cloud/account action.

Compatibility:

- Existing `/api/bootstrap`, `/api/questions`, `/api/agent-reports`,
  `/api/attachments/{id}`, and operator routes remain available.
- Existing v2 child endpoints can remain behind compatibility code while the UI
  moves to v3 endpoints.
- Existing `attempts` and `background_jobs` rows remain readable.
- Existing tests may continue to cover legacy behavior until v3 tests replace
  the child mainline assertions.

Contract tests:

- Schema:
  `daily_flows`, `flow_steps`, `review_targets`,
  `evidence_validations`, `next_step_decisions`,
  `late_evidence_reconciliations`, `daily_summaries`, additive
  attempt/job/status columns, and required indexes exist after
  `db.init_schema`. Tests must use `PRAGMA table_info`, `PRAGMA index_list`,
  and duplicate-write attempts, not just successful inserts.
- Graph lineage:
  rows in `daily_flows`, `flow_steps`, `review_targets`, `attempts`,
  `evidence_validations`, `mastery_decisions`, `learner_node_status`,
  `next_step_decisions`, `late_evidence_reconciliations`, and
  `daily_summaries` without required `graph_version` or source ids cannot drive
  evidence gate, planner, summary, or report `confirmed` labels.
- SQLite invariants:
  tests must assert one active flow per child/date, one visible current step per
  flow, one active attempt per step, one active job per idempotency key, one
  validation per attempt/analysis version, one next decision per flow revision,
  and atomic submit transaction behavior.
- Child bootstrap:
  no raw ids, graph ids, agent names, model/provider names, rubrics, OCR
  confidence, queue internals, or parent/Codex instructions.
- Current-step:
  exactly one visible step; no fixed `today_plan.tasks` list in v3 child
  payload; no hidden fixed daily list because every next step must reference a
  `next_step_decision` written after the previous step/evidence state.
- Idempotency:
  duplicate submit with same key returns same receipt; duplicate with different
  evidence conflicts safely; repeated bootstrap polling does not create extra
  flows, steps, attempts, jobs, decisions, summaries, or recovery actions.
- Evidence gate:
  pending/missing/malformed/mock/stale/invalidated/missing-lineage evidence does
  not update mastery or next-step confirmed decisions. The matrix must cover
  `active/invalidated/stale x pending_review/graded/blocked x
  valid/missing/invalid_analysis/low_confidence/mock_only/missing_lineage`.
- Candidate packet:
  packet size is 5-8 rows, contains required metadata, excludes stale/inactive
  duplicates, cooldown violations, mastered-node extras, and missing-lineage v2
  bank rows before planner sees them. It must include packet id/hash and exact
  PRD metadata fields, and must not include full solution banks.
- Next-step trace:
  every `next_step_decision` includes source attempts, evidence validations,
  mastery decisions, graph version, review target, candidate packet hash/filter
  summary, pending evidence, branch policy, provider/fallback mode, and report
  label.
- Model config missing:
  attempt stays pending/blocked with operator reason; child message is honest.
- Async/model slow:
  slow model with independent safe target, slow model with no independent
  target, stale `queued/running/error` jobs, pending attempts with no job, and
  completed model output not applied are all recovered idempotently.
- Late evidence:
  completed late analysis records reconciliation but does not rewrite a
  currently displayed step; it applies only at a safe transition and records
  whether summary/report included or excluded it.
- Summary:
  includes all report labels: `confirmed`, `pending`, `blocked`, `inferred`,
  `stale`, `mock_only`, `missing_lineage`; tests must prove label precedence
  and reject stale `latest` or v2 fixed-flow artifacts as v3 PASS evidence.
- Semantic downstream consequences:
  answer-only, wrong-reason-right-answer, stuck/cannot-start, blank/no usable
  evidence, partial relation/wrong final, symbol/unit issue, readable photo, and
  unclear photo tests must assert answer-analysis dimensions, process gap,
  error tags, OCR usability, confidence policy, validation status, mastery
  behavior, child feedback/repair, planner branch, and report label.
- Provider integrity:
  mock, recorded, and live provider evidence are reported separately. Mock-only
  semantic/model QA can at most support `QA_PASS_WITH_SCOPE`.
- 10-20 adaptive day:
  browser/API simulation must run a v3 `daily_flow` for 10-20 current steps with
  mixed evidence, all-correct segment, slow-model branch, skipped mastered
  nodes, no parent intervention, no fixed-list regression, all steps in
  summary, and evidence-linked next decisions.

Open questions:

- Whether to preserve v2 child endpoint paths as aliases for one release or
  fully switch the UI to v3 paths in one slice.
- Final DATA_CONTRACT_SPEC v3 may rename some rows/columns; implementation
  should stop after skeleton if reviewers request naming changes.

Stop condition:

The first slice is implementation-ready only after this contract is reviewed for
runtime/state/model/data sufficiency and 观止 can derive v3 TEST_CASE_SPEC from
the skeleton targets.

## IMPLEMENTATION_BLUEPRINT - 听云（agentKey: `tingyun`）- 2026-07-10 CST

Objective:

Provide a file/symbol-level施工图 for the first implementation slice.

Complexity: high_risk_change

Scope:

- Runtime skeleton and old-knowledge review hot path.
- Current-step child API.
- Evidence gate and candidate packet.
- Async analysis/recovery hooks.
- Child-safe summary.
- New-knowledge readiness and teaching shell only.

Non-goals:

- Full new-knowledge teaching intelligence.
- Full agent Knowledge Pack migration.
- External storage/queue migration.
- Parent dashboard or multi-user system.

Project boundary overlay:

PRD v3 + `AGENTS.md`.

Product structure spec:

PRD v3 `PRODUCT_STRUCTURE_SPEC`.

UX flow spec:

PRD v3 constrained states for first slice; full UX_FLOW_SPEC v3 remains a
required later gate.

Data contract spec:

PRD v3 embedded data contract + architecture v3; DATA_CONTRACT_SPEC v3 review
required before final release.

Facts checked:

- Current fixed-group logic is concentrated in `server.py`,
  `_current_child_plan_context`, `_child_bootstrap`, `_create_child_submission`,
  `_close_learning_session`, and `planner.latest_or_create_plan`.
- Current active-use question logic lives in `db.is_child_schedulable_question`,
  `db.find_question_for_node`, and `question_bank.is_item_approved_for_active_use`.
- Current answer-analysis logic lives in `auto_review.review_child_answer` and
  `model_router.call_structured_json`.
- Current tests are centralized in `tests/test_learning_system.py` plus browser
  smoke in `tests/browser_smoke_learning_system.mjs`.

Engineering contract:

Use the `ENGINEERING_CONTRACT` section above.

Behavior contract:

- inputs:
  child opens page, starts review, submits text/photo/stuck response for the
  current step, and polls bootstrap.
- outputs:
  one child-safe current step or state, durable attempt/evidence rows, queued
  model jobs, validated evidence decisions, next-step decisions, and summary.
- state/data changes:
  additive v3 runtime rows; attempts linked to flow steps; existing v2 rows
  preserved.
- errors/recovery:
  fail closed, label pending/blocked, retry idempotently, and never use pending
  or invalid evidence for mastery/planning.
- old-data/backward compatibility:
  legacy sessions/attempts remain readable; v3 reports label missing lineage
  rather than silently promoting old evidence.

Change map:

| Step | File/path | Symbol/route/command | Change | Producer/consumer impact | Validation |
|---|---|---|---|---|---|
| 1 | `learning_system/db.py` | `init_schema` | Add v3 tables and additive columns with lineage/version fields: `daily_flows`, `flow_steps`, `review_targets`, `evidence_validations`, `next_step_decisions`, `late_evidence_reconciliations`, `daily_summaries`; add `attempts.flow_step_id`, `attempts.graph_version`, `attempts.question_bank_version`, `attempts.attempt_version`, `attempts.analysis_version`, `attempts.analysis_status`, `attempts.client_idempotency_key`; add job lease/idempotency/dependency fields | Runtime can persist v3 without disrupting v2; stale/missing-lineage rows fail closed | schema, lineage, partial-index, duplicate-write tests |
| 2 | `learning_system/graph_runtime.py` | `GraphRuntimeService` | New service for graph version/hash, node lookup, prerequisite summaries, rollback candidates, graph-binding validation | All v3 rows get one graph-version authority | graph version tests |
| 3 | `learning_system/evidence_gate.py` | `EvidenceGate`, `EvidenceUsePredicate` | New gate wrapping current usable predicates plus graph_version/flow_step/attempt/analysis versions, provider mode, active bank lineage, and `passed -> usable` projection mapping | Evaluation/planner/report consume one predicate and cannot promote mock/stale/missing lineage | evidence matrix and report-label tests |
| 4 | `learning_system/job_queue.py` | `JobQueue` | New wrapper over `background_jobs`: enqueue/claim lease/start/heartbeat/finish/retry/wait/block/dead-letter/recover by idempotency key, flow/step/attempt versions, and dependencies | Server and worker stop hand-writing queue rules; duplicate workers cannot claim same job | lease/recovery/stale unlock tests |
| 5 | `learning_system/question_bank.py` | `QuestionBankService.candidate_packet_for_node` | Add exact candidate packet builder with active-use filtering, v2 graph_version backfill/exclusion, diversity/cooldown exclusion, packet id/hash, and metadata-only rows | Planner receives 5-8 current lineage rows, not full bank or solution banks | candidate schema/backfill/exclusion tests |
| 6 | `learning_system/planner.py` | `select_next_step_v3`, DTO/schema helpers | Add v3 planner adapter accepting latest evidence summary, target summary, pending summary, budget, candidate packet; writes complete `next_step_decisions` schema and deterministic fallback for tests/model-disabled | Runtime can ask for one next step with full source trace | planner branch/no-hidden-list tests |
| 7 | `learning_system/model_router.py` | route helpers | Add `planner_route`, `evaluation_route`, `teaching_route` status helpers and audit metadata; keep adapter fallback | All new model calls stay routed | router tests |
| 8 | `learning_system/daily_runtime.py` | `DailyLearningRuntime` | New runtime implementing load/create, start_review_mode, build_targets, select/project step, submit, apply analysis, decide next, summary | Central v3 state machine | service integration tests |
| 9 | `learning_system/auto_review.py` | adapter function | Expose answer-analysis call usable by v3 worker with route metadata and analysis status mapping | Current evaluator reused in v3 | answer-analysis tests |
| 10 | `learning_system/server.py` | child routes | Add `/api/daily-flow/review/start`, `/api/current-step/submit`, v3 `/api/child-bootstrap` projection, operator inspect route; keep legacy routes guarded | Child UI moves to current-step API | API tests |
| 11 | `learning_system/server.py` | background startup/worker | Start v3 queue recovery on server start and bootstrap; process answer analysis -> gate -> eval -> planner chain idempotently | No queued job remains inert after restart | recovery tests |
| 12 | `app/local_learning_system/app.js` | state model and API client | Replace fixed task list rendering with current-step rendering/polling; keep photo upload, stuck action, honest wait, summary, ready-for-new-knowledge shell | Son sees one step only | browser smoke |
| 13 | `app/local_learning_system/index.html` | DOM shell | Adjust labels/containers for current step, teaching shell, summary, blocked/waiting | No parent/operator surface | browser smoke/accessibility |
| 14 | `app/local_learning_system/styles.css` | current-step states | Keep dense age-respectful styling, no childish cards or internals | Stable mobile/desktop layout | screenshots |
| 15 | `learning_system/reports.py` and `scripts/generate_daily_report.py` | v3 report facts | Include daily_flow, step ids, evidence labels, pending/blocked/model config facts | Codex can query persisted truth | report tests |
| 16 | `tests/test_learning_system.py` | v3 unit/integration tests | Add tests for schema, current-step, idempotency, evidence gate, candidate packet, model disabled, late evidence, summary | Guard core runtime | unittest |
| 17 | `tests/browser_smoke_learning_system.mjs` | v3 browser path | Simulate open/start/answer/photo/stuck/wait/summary with no internals | Guard child flow | browser smoke |
| 18 | `scripts/simulate_child_learning_journey.py` | v3 mode | Add 10-20 adaptive step simulation using browser/API, with mixed correct/wrong/stuck/photo/model cases | 观止 can run realistic QA | simulation report |

Skeleton plan:

| Step | File/path | Module/type/interface/class/function/route/handler | Skeleton to create | Compile/static check |
|---|---|---|---|---|
| 1 | `learning_system/graph_runtime.py` | `GraphRuntimeService` | class with method signatures and deterministic graph hash | `python3 -m py_compile` |
| 2 | `learning_system/evidence_gate.py` | `EvidenceGate` | predicate and validation-result dataclass/function signatures | `python3 -m py_compile` |
| 3 | `learning_system/job_queue.py` | `JobQueue` | enqueue/lock/finish/recover signatures with safe no-op stubs | `python3 -m py_compile` |
| 4 | `learning_system/daily_runtime.py` | `DailyLearningRuntime` | state-machine method signatures and fail-closed stubs | `python3 -m py_compile` |
| 5 | `learning_system/server.py` | v3 routes | route shells wired to runtime stubs; child-safe error projection | `python3 -m py_compile` |
| 6 | `tests/test_learning_system.py` | v3 test class | failing/xfail-safe tests converted to active after skeleton | focused unittest |
| 7 | `app/local_learning_system/app.js` | `ChildLearningShell` v3 state enum | current-step state shells and fixture hook | browser smoke fixture |

Page prototype / route shell plan:

| Surface/route | Prototype or shell | Primary states | Data/API placeholders | Validation |
|---|---|---|---|---|
| `/` child page | Current-step renderer | loading, choose_review, current_step, saving, analyzing, blocked, ready_for_new_knowledge, teaching, summary | `GET /api/child-bootstrap`, `POST /api/daily-flow/review/start`, `POST /api/current-step/submit` | browser smoke |
| Current step | One question/interaction at a time | displayed, draft, saved, waiting, evaluated | `current_step.handle`, `position`, prompt, input mode | DOM no internals |
| Teaching shell | Minimal teaching/micro-check | explanation, micro_check, submitted | teaching package placeholder | child-safe validation |
| Summary | End/transition | confirmed, pending, blocked, next move | daily summary labels | report/API matching |

Tests to add/update:

- `test_v3_schema_additive_and_legacy_rows_remain_readable`
- `test_v3_schema_has_required_lineage_columns_and_unique_indexes`
- `test_v3_legacy_status_rows_are_missing_lineage_hints_not_planner_confirmed`
- `test_v3_child_bootstrap_has_no_fixed_task_list_or_internal_ids`
- `test_v3_start_review_creates_one_daily_flow_and_one_current_step`
- `test_v3_submit_current_step_is_idempotent_and_enqueues_analysis`
- `test_v3_submit_transaction_is_atomic_for_attempt_attachment_and_job`
- `test_v3_candidate_packet_is_small_active_and_metadata_only`
- `test_v3_candidate_packet_excludes_v2_rows_without_graph_version_backfill`
- `test_v3_evidence_gate_rejects_pending_stale_invalidated_mock_missing_lineage`
- `test_v3_evidence_validation_passed_maps_to_usable_projection_only_after_predicate`
- `test_v3_right_answer_wrong_reason_is_not_mastery`
- `test_v3_model_not_configured_blocks_honestly`
- `test_v3_model_slow_independent_target_vs_no_independent_target`
- `test_v3_queue_stale_running_unlock_and_duplicate_claim_prevention`
- `test_v3_late_evidence_waits_for_safe_transition`
- `test_v3_next_step_decision_requires_full_source_lineage`
- `test_v3_no_hidden_fixed_list_each_step_has_fresh_decision_after_evidence`
- `test_v3_summary_label_precedence_all_v3_labels`
- `test_v3_semantic_cases_assert_analysis_gate_mastery_planner_report`
- Browser smoke for open/start/answer/photo/stuck/wait/ready-for-new/teaching
  shell/summary/no-internals.
- Browser/API simulation for a 10-20 current-step adaptive day with mixed
  evidence and no fixed hidden list.

Test design handoff:

- expected TEST_CASE_SPEC: required. This is a high-risk child-learning runtime
  change with async/model/evidence/semantic behavior.
- Hard QA handoff gates for the skeleton-derived TEST_CASE_SPEC:
  - current-step old-review flow proves `child_state/current_step`, no
    `today_plan.tasks`, graph-bound targets, and no hidden fixed daily list;
  - idempotency/repeated polling/concurrent submit assertions check DB row
    counts, not just HTTP status;
  - async/model matrix covers not configured, slow with independent safe target,
    slow with no independent target, stale queued/running/error jobs, pending
    attempt without job, unapplied completed output, retry metadata, and no fake
    mastery;
  - late evidence tests require reconciliation rows, no visible-step rewrite,
    safe-transition-only application, summary inclusion/exclusion labels, and
    auditable reconsideration;
  - semantic cases must assert downstream analysis -> gate -> mastery ->
    planner -> report consequences, not only model JSON shape;
  - candidate packet tests must assert exact schema, 5-8 metadata rows, no
    solution banks, exclusion counts, context size, latency/fallback/provider
    audit, and missing-lineage v2 exclusion/backfill;
  - every next step must trace to source attempts, evidence validations, node
    status, graph version, review target, candidate packet, and branch policy;
  - the 10-20 adaptive-day simulation must include mixed correct/wrong/stuck,
    blank, photo, slow-model, pending, answer-only, all-correct segment, skipped
    mastered nodes, no parent intervention, all steps in summary, and no fixed
    list regression;
  - child-safe browser checks must cover loading, choose review, current step,
    saving, analyzing/waiting, blocked, clarification, teaching shell,
    ready-for-new-knowledge, summary, load/save/upload errors, mobile/desktop,
    focus, draft/photo preservation, and no internal ids/text;
  - report/QA harness must record base URL, DB path, provider mode, version
    marker, sampled flow/step/attempt ids, screenshots/artifacts, report path,
    real vs isolated ledger, and must fail on issue-count/verdict/exit-code
    disagreement.
- test file targets:
  `tests/test_learning_system.py`,
  `tests/browser_smoke_learning_system.mjs`,
  `scripts/simulate_child_learning_journey.py`, and generated QA report paths
  under `docs/system/qa/`.

Validation commands:

```bash
python3 -m py_compile learning_system/db.py learning_system/server.py learning_system/model_router.py learning_system/auto_review.py learning_system/planner.py learning_system/question_bank.py
python3 -m py_compile learning_system/daily_runtime.py learning_system/graph_runtime.py learning_system/evidence_gate.py learning_system/job_queue.py
python3 -m unittest tests/test_learning_system.py -v
/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs
python3 scripts/generate_daily_report.py --db data/local_learning_system.sqlite
```

Live-model validation must be reported separately from mock/recorded validation
and must not expose API keys.

Implementation order:

1. Add schema and DB helper skeletons.
2. Add graph runtime, evidence gate, and queue wrappers.
3. Add candidate packet service.
4. Add daily runtime skeleton and route shells.
5. Add current-step child UI shell and fixtures.
6. Stop for SKELETON_PASS review and 观止 TEST_CASE_SPEC unless gate waived.
7. Fill old-review hot path: load/create, start review, target pool, candidate
   packet, select/project step, submit, enqueue, analyze, validate, evaluate,
   decide next, summary.
8. Add recovery and late-evidence reconciliation.
9. Add browser/API/report validation.

Rollback/recovery notes:

- Additive DB changes are not rolled back destructively.
- Use `V3_DAILY_RUNTIME_ENABLED=0` to serve legacy v2 child flow if needed.
- Mark v3 flows `blocked` or `superseded` rather than deleting rows.
- Preserve uploaded photos and attempts.
- If model routes fail, rows remain pending/blocked and reports label them.

Blueprint stop conditions:

- Stop after skeleton if reviewers object to table names, API paths, gate
  vocabulary, or runtime/service boundaries.
- Stop before business logic fill if UX_FLOW_SPEC v3 or DATA_CONTRACT_SPEC v3
  contradicts this plan.
- Stop if implementation would require deleting real attempts/uploads/reports.
- Stop if a model call path bypasses `model_router`.
- Stop if candidate selection requires passing full question bank content to a
  model.

Open questions:

- Final route aliases for legacy child endpoints.
- Final visual copy and child-state wording.
- Final DATA_CONTRACT_SPEC v3 table/field naming review.
- Live provider QA cadence.

## Review Fix Log - 听云（agentKey: `tingyun`）- 2026-07-10 CST

Scope:

Revision of `docs/architecture/technical_plan_v3.md` only, in response to
NEEDS_FIX reviews from 镜花、霜弦、观止. No code, review file, DB, test, or
commit changes.

### 镜花 Findings

1. P1 Schema graph lineage across all v3 rows:
   - Fixed by adding `Graph lineage and provenance contract`.
   - Explicitly covers `daily_flows`, `flow_steps`, `review_targets`,
     `attempts`, `evidence_validations`, `mastery_decisions`,
     `learner_node_status`, `next_step_decisions`,
     `late_evidence_reconciliations`, and `daily_summaries`.
   - Added required `graph_version`, source ids, agent run ids, bank version,
     old/null handling, and consumers.
   - Added tests requiring rows without lineage to fail evidence gate, planner,
     summary, and report-confirmed claims.

2. P1 Idempotency not enforceable from SQLite/index/transaction contract:
   - Fixed by adding `SQLite invariant and transaction contract`.
   - Added `flow_revision`, `step_revision`, `attempt_version`,
     `analysis_version`, and `decision_version`.
   - Added required unique/partial unique indexes for active flow, current
     step, step handle, active attempt per step, submit idempotency, active job,
     validation version, mastery package, next decision, and summary.
   - Added the submit transaction boundary that atomically validates current
     step, saves attempt/attachment metadata, enqueues answer analysis, updates
     step/flow revision, and handles duplicate keys.

3. P1 Queue/worker lease and recovery underspecified:
   - Fixed by adding `Queue/worker lease and recovery state machine`.
   - Added statuses, methods, lease fields, stale unlock, retry/wait/block,
     dead-letter, recovery scan, payload version fields, dependency ordering,
     and late-evidence safe-transition rules.
   - Updated change map and tests for stale running unlock, duplicate claim
     prevention, model-disabled blocking, retry timing, late evidence, and no
     inert queued jobs.

4. P2 Evidence vocabulary mismatch:
   - Fixed by adding `Evidence vocabulary mapping`.
   - Preserved internal `gate_status=passed` but explicitly maps it to PRD/API
     `usable` only after `EvidenceUsePredicate.is_usable(...)`.
   - Added consumer/test rule: `passed` alone is never enough for mastery,
     planning, or `confirmed` report claims.

### 霜弦 Findings

1. P1 `learner_node_status` / `mastery_decision` lineage too loose:
   - Fixed by adding required provenance fields and a dedicated
     `Planner-usable learner_node_status and mastery_decisions` contract.
   - Legacy status rows are now explicitly `missing_lineage` hints only until
     recomputed from current mastery decisions and source evidence validations.

2. P1 `next_step_decision` lineage/status under-specified:
   - Fixed by adding `Next-step decision schema`.
   - Required fields now include `decision_status`, graph/bank version, source
     attempts, evidence validations, mastery decisions, candidate packet id/hash,
     filter summary, pending evidence, provider/fallback mode, stale/mock
     sources, branch policy, report label, and reason.
   - Missing fields force rejected/blocked/fallback semantics rather than
     confirmed planning/report claims.

3. P1 Candidate packet / active question graph-version handling:
   - Fixed by adding `Candidate packet exact schema`.
   - Packet row schema now matches PRD fields and includes active-use proof,
     lineage status, packet id/hash, exact filter summary, and no solution/rubric
     bodies.
   - v2 bank rows require deterministic graph-version backfill plus reviewer
     proof before v3 scheduling; otherwise excluded as `missing_lineage`.

4. P2 Report label vocabulary/test contract:
   - Fixed by adding `Report label enum and precedence`.
   - Added all labels and precedence:
     `confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`,
     `missing_lineage`.
   - Tests now explicitly cover `stale`, `mock_only`, and `missing_lineage`.

### 观止 Findings

1. P1 10-20 adaptive-day coverage not hard gate:
   - Fixed by making a 10-20 current-step browser/API simulation mandatory in
     contract tests and QA handoff.
   - It must include mixed evidence, all-correct segment, slow-model branch,
     skipped mastered nodes, no fixed-list regression, all steps represented in
     summary, and evidence-linked next decisions.

2. P1 Async/model-slow recovery matrix shallow:
   - Fixed by adding explicit async/model slow contract tests and QA handoff
     gates for model missing, slow with independent safe target, slow with no
     independent target, stale jobs, pending attempt without job, unapplied
     output, retry metadata, and no fake mastery.

3. P1 No fixed list and next-step trace under-specified:
   - Fixed by adding current-step contract test that forbids hidden fixed lists:
     each next `flow_step` must reference a fresh `next_step_decision` after the
     prior evidence transition.
   - Added full next-step source trace requirements.

4. P1 Semantic cases not tied to downstream consequences:
   - Fixed by requiring answer-only, wrong-reason-right-answer, stuck, blank,
     partial relation/wrong final, symbol/unit, readable photo, and unclear
     photo cases to assert analysis dimensions, process gap, error tags, OCR
     usability, confidence, validation, mastery behavior, planner branch, child
     feedback, and report label.

5. P2 Provider integrity and false-pass harness:
   - Fixed by adding provider integrity, report-label precedence, stale latest
     report/v2 artifact rejection, QA report metadata, real vs isolated ledger,
     and issue-count/verdict/exit-code disagreement as `NEEDS_FIX`.

Residual scope after this fix:

- This document is still a technical plan, not implementation.
- UX_FLOW_SPEC v3 and DATA_CONTRACT_SPEC v3 remain required review artifacts
  before final release, but the first-slice skeleton now has hard lineage,
  invariant, queue, evidence, candidate, decision, report, and QA contracts to
  review.
