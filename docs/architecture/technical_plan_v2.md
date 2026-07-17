# AI Native Math Learning System v2 Technical Package

Status: draft for design review  
Owner: 听云 (agentKey: `tingyun`)  
Created: 2026-07-08 CST  
Scope: PRD-first restart architecture/spec package only. No production code or skeleton implementation is included in this file.

## Sources And Evidence

Identity and collaboration sources:
- `docs/collaboration.md`
- `docs/collaboration/roles/tingyun.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/inbox.md`
- `docs/collaboration/playbooks/artifact-contracts.md`
- `AGENTS.md`

Product/data/UX sources:
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/product/child_ux_flow_spec_v2.md`
- `docs/architecture/data_contract_spec_v2.md`
- `docs/domain-index/math-learning.md`
- `docs/system/local_learning_system.md`
- `docs/system/qa/question_bank_grade_level_latest.md`

Implementation fact sources:
- `app/local_learning_system/index.html`
- `app/local_learning_system/app.js`
- `app/local_learning_system/styles.css`
- `learning_system/server.py`
- `learning_system/db.py`
- `learning_system/model_router.py`
- `learning_system/auto_review.py`
- `learning_system/orchestrator.py`
- `learning_system/planner.py`
- `learning_system/evolution.py`
- `learning_system/question_bank.py`
- `learning_system/internal_agents.py`
- `learning_system/agent_contracts/*.json`
- `learning_system/prompts/*.md`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `scripts/*.py`

Environment note:
- `git status --short` could not run in this directory because `/Users/liuchang/Documents/gitproject/son-ai-learning-system` is not currently a git repository in this runtime. No git operation is required for this package.

## TECHNICAL_PLAN - 听云（agentKey: `tingyun`）- 2026-07-08 CST

Objective:
Define the v2 architecture for the child-only math learning system so a later SKELETON_PASS can create route/module/schema/test skeletons without guessing product behavior, data meaning, async boundaries, model routes, or validation commands.

Scope:
- One child Web surface at `/`.
- Local HTTP backend and local SQLite evidence ledger.
- Child/operator API separation.
- Graph-bound question, attempt, evaluation, planning, evolution, and reporting contracts.
- 10-task async learning round.
- Text answer analysis through GPT-compatible route by default.
- Answer photo transcription through Doubao-compatible vision route by default.
- Compatibility adapter for DeepSeek, Doubao, and other OpenAI-compatible routes.
- Planned migration path for question specs/rubrics/forbidden patterns out of Python-only content.
- Technical skeleton definition for later SKELETON_PASS.

Non-goals:
- No production code edit in this task.
- No parent Web dashboard.
- No multi-user auth, cloud deployment, payment, SaaS admin, or English implementation.
- No external textbook/commercial question import.
- No manual parent grading as normal flow.
- No secrets in source, docs, reports, tests, or audit rows.
- No destructive reset or deletion of real attempts/uploads/evidence.

Project boundary overlay:
- Source: `docs/product/ai_native_math_learning_prd_v2.md` `PROJECT_BOUNDARY_OVERLAY`.
- Single-child private math system for incoming Grade 7 summer bridge.
- Parent uses Codex, not a parent dashboard.
- Codex is an on-demand query/operator surface only. Runtime teaching agents must persist generated results to SQLite/report artifacts and must not create or depend on separate Codex sessions/threads as the result-feedback channel.
- Every teaching, diagnosis, question, attempt, evaluation, plan, and evolution event must bind to graph nodes.
- Active round target is 10 tasks.
- Pending, malformed, invalidated, stale, low-confidence, fake, or missing-analysis evidence cannot drive mastery, planning, evolution, or reports.
- Questions require graph binding, current version, durable reviewer record, and high-signal Grade 7 reasoning gate.
- Current QB11 planning contract requires a node-local mainline evidence floor and controlled picture-level stretch caps: a 10-task round should contain at least 7 node-local mainline tasks and normally 1-2 semantically anchored picture-level extension tasks.
- Evolved questions require valid source attempt lineage before active use: source attempt id exists, source attempt is active + graded + valid answer_analysis, its source question is still child-schedulable, and source question lineage is non-cyclic.
- GPT-compatible text is default; Doubao-compatible vision is default for photo OCR; DeepSeek/provider changes go through adapter routes.

Product structure spec:
- Consumed from `docs/product/ai_native_math_learning_prd_v2.md` `PRODUCT_STRUCTURE_SPEC`.
- Technical design keeps the product module map: child learning surface, session orchestration, graph binding, question production/review, answer analysis, evaluation/planning, teaching feedback, self-evolution, evidence ledger, model routing, Codex reports, QA harness.

UX flow spec:
- Consumed from `docs/product/child_ux_flow_spec_v2.md`.
- The route shell must model child-visible states: `loading`, `empty`, `active_task`, `saving`, `all_submitted_reviewing`, `review_ready`, `blocked`, `load_error`, `save_error`.
- Child state must never expose graph ids, question ids, attempt ids, session ids, model/provider names, agent names, rubrics, OCR confidence, queue internals, or operator actions.

Data contract spec:
- Consumed from `docs/architecture/data_contract_spec_v2.md`.
- The implementation must preserve the usability predicate: `active + graded + valid answer_analysis + current active question`.
- `answer_analysis_json` is required before evaluation/planning/evolution/report claims.
- Question active eligibility requires graph binding, current version, recomputed reviewer approval, and durable `question_review_records`.

Facts checked:
- Current v1.6 already has stdlib HTTP server, vanilla child UI, SQLite schema, child/operator API split, background jobs, attachment storage, model router compatibility adapter, internal agent contracts/prompts, orchestrator close path, planner/evolution chain, and broad tests.
- Current DB schema includes `graph_nodes`, `graph_edges`, `question_items`, `learning_sessions`, `attempts`, `attempt_attachments`, `learner_node_status`, `agent_profiles`, `evolution_events`, `generated_plans`, `agent_runs`, `agent_handoffs`, `session_steps`, `mastery_decisions`, `question_review_records`, `evolution_audits`, and `background_jobs`.
- Current tests cover seed integrity, model routing fallback, question quality gates, stale lineage repair, child-safe bootstrap, async submission, restart recovery, idempotent session close, background retry/error, photo handling, semantic grading cases, and browser child-flow smoke.

Architecture decisions:
- sync_vs_async: Child submission is synchronous only for validation and persistence. Grading/review is async through durable `background_jobs`; the child advances immediately after save. Session close is sync-fast when all analyses are ready and returns `waiting_ai`/`blocked` when not.
- model_provider_choice: `answer_analysis_agent` and `question_designer_agent` use GPT-compatible text routes by default. `answer_analysis_agent` vision OCR uses Doubao-compatible route by default. DeepSeek and future providers are allowed only through `model_router.resolve_route` and `call_structured_json` fallback modes.
- service_api_boundary: Keep child APIs handle/position based and sanitized; keep operator APIs id-based and audit-rich for Codex maintenance. Child endpoint responses are projections, not raw DB/domain objects.
- data_state_contract: SQLite remains the local evidence ledger for this cycle. Add/normalize schema through additive migrations/helpers only; source evidence is append/version/invalidate, not destructive-delete.
- result_delivery_contract: Internal agent outputs are durable rows/artifacts first: attempts, answer analysis, background jobs, session steps, mastery decisions, evolution audits, generated plans, agent runs, and daily/QA reports. Codex progress answers must query those sources; spawning/forking Codex sessions or asking the parent to copy results between sessions is not a product mechanism.
- queue_task_state: Use durable `background_jobs` with statuses `queued`, `running`, `succeeded`, `waiting`, `error`; recover queued/running/pending attempts on server start and child bootstrap when model route is available.
- failure_retry_idempotency: Use idempotent session closure by session id, unique-ish agent run triggers, duplicate submission checks per session/question, reusable waiting/error background jobs per attempt, and closure status guards.
- rollback_recovery: Roll back by marking attempts invalidated and retiring dependent evolved questions/review records. For deployment rollback, preserve old DB and uploads; revert app/server code while leaving audit rows readable.
- child_safety_boundary: All child-facing messages pass a child-safe projection and validator equivalent to `internal_agents.validate_child_safe_message`.
- question_spec_migration: Stage migration from Python-only content to data specs. Stage 1 define data files/loaders for families/rubrics/forbidden patterns while retaining current Python gates; Stage 2 parity-load into current runtime; Stage 3 retire duplicated Python constants only after tests and reviewer records prove equivalence.

Alternatives considered:
- Keep all current v1.6 code as-is: rejected for v2 planning because contracts are spread across implementation and tests, making skeleton/review gates guess too much.
- Replace SQLite with Postgres or a task queue service now: rejected. Local/private single-child scope and current evidence ledger fit SQLite; staged alternative only if concurrency, long-running model jobs, or WAL contention becomes a measured blocker.
- Direct provider calls inside agents: rejected. PRD and existing router require adapter paths and local schema validation.
- Parent dashboard for reports: rejected by product boundary. Reports remain Codex/operator artifacts.
- Codex sessions as generated-result containers: rejected. They are useful for development-time review/delegation only; runtime learning results must be DB/report backed so any later Codex query can reconstruct the truth.
- Full question-spec migration in first implementation slice: deferred as staged unless 若命/霜弦 approve a larger data migration slice.

Blueprint requirement:
- This is a high-risk, multi-module/stateful architecture change. A later implementation must first create a program/page/API/test skeleton and stop at SKELETON_PASS before business logic fill.

Risks and tradeoffs:
- SQLite plus in-process background threads is acceptable locally but not a cloud-scale queue. Mitigation: explicit `background_jobs` ledger, restart scanning, idempotent close, and future queue adapter seam.
- Model semantic quality cannot be fully proven by deterministic tests. Mitigation: contract tests, semantic scenario matrix, live-model samples, and pending evidence exclusion.
- Current question bank has PASS_WITH_SCOPE, not expert final approval. Mitigation: keep reviewer records and audit scripts as release gates.
- Full data-spec migration may disturb the working bank. Mitigation: loader parity stage and old-attempt compatibility before retiring Python constants.
- Visual taste remains provisional. Mitigation: skeleton includes deterministic fixture states and screenshots for 清秋/user review.

Validation:
- Read-only/pre-skeleton validation commands:
  - `jq empty data/knowledge_graphs/math/math_knowledge_graph_v2.json`
  - `jq '.nodes | length' data/knowledge_graphs/math/math_knowledge_graph_v2.json`
  - `python3 scripts/audit_question_bank_grade_level.py --db data/local_learning_system.sqlite`
- Test-environment mutating validation commands:
  - `python3 scripts/init_learning_system_db.py` writes/refreshes the local SQLite test ledger and must not be run against preserved real-session evidence without backup and explicit test scope.
  - `python3 scripts/generate_daily_report.py --db data/local_learning_system.sqlite` writes report markdown files and is a report-generation validation, not read-only inspection.
  - `python3 -m unittest tests/test_learning_system.py -v` may create/reset local test DB state depending on test setup and must run in an explicit test scope.
  - `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs` requires a controlled local server/test state and may create screenshots/artifacts.
- Service/manual validation commands:
  - `python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765` starts a local service and may resume queued background jobs when model routes are configured; run only in explicit test/operation scope.
- Later visual validation must include desktop/mobile screenshots for all UX states named in the UX spec.

Files likely touched in later SKELETON_PASS:
- `app/local_learning_system/index.html`
- `app/local_learning_system/app.js`
- `app/local_learning_system/styles.css`
- `learning_system/server.py`
- `learning_system/db.py`
- `learning_system/model_router.py`
- `learning_system/auto_review.py`
- `learning_system/orchestrator.py`
- `learning_system/planner.py`
- `learning_system/evolution.py`
- `learning_system/question_bank.py`
- `learning_system/internal_agents.py`
- `learning_system/agent_contracts/*.json`
- `learning_system/prompts/*.md`
- `learning_system/reports.py`
- `scripts/*.py`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- Planned new data-spec paths under `data/question_specs/` only if the staged migration slice is approved.

Open questions:
- Final rendered visual taste and exact child copy require human review.
- Long-run A/B/C/D threshold tuning remains provisional after real multi-day evidence.
- Full question-spec migration stage may be phased; this plan defines seams and gates, not a mandate to complete the migration in one slice.

## ENGINEERING_CONTRACT - 听云（agentKey: `tingyun`）- 2026-07-08 CST

Objective:
Define API/interface, field, call-chain, async, storage, compatibility, idempotency, and test contracts for v2.

Scope:
Same as TECHNICAL_PLAN. This contract is for later skeleton/review/implementation; it does not authorize code changes by itself.

Non-goals:
No production implementation, no parent dashboard, no external platform side effects, no secret writes.

Project boundary overlay:
Applied from PRD v2 `PROJECT_BOUNDARY_OVERLAY`.

Interface contracts:
| Interface | Type | Method/route/symbol | Request/input | Response/output | Errors | Auth/permission |
|---|---|---|---|---|---|---|
| Child bootstrap | frontend_api | `GET /api/child-bootstrap` | none | `schema_version`, `today_plan{title, display_key?, tasks[position, kind_label, display_topic, estimated_minutes, question{prompt, answer_format}, support{essence_or_hint}]}`, `learning_group{handle,state,submitted_task_positions}`, optional `completion` child projection | retryable JSON error; child-safe copy only | child surface; no raw ids, graph-shaped field names, or internals; `display_key` is optional opaque UI continuity text, not a plan id |
| Child submission | frontend_api | `POST /api/child-submissions` | `session_handle=current-learning-group`, `task_position`, `answer_raw?`, `answer_photo_data_url?`, `answer_photo_name?` | `submission_state=saved`, `review_state=being_reviewed|reviewed`, `child_message`, `attachments_saved` | invalid photo, empty answer/photo, duplicate, stale/closed group; all child-safe | child surface; rejects `question_id`, `session_id`, `attempt_id` |
| Child complete group | frontend_api | `POST /api/learning-sessions/current-learning-group/complete` | `{}` | `session{handle,state}`, `closure_status=waiting_ai|blocked|planned`, `child_message` with review points when ready | incomplete/waiting/blocked; no internal ids | child surface only |
| Attachment fetch | frontend_api | `GET /api/attachments/{attachment_id}` | attachment id from sanitized projection only | local image with `nosniff` | 404/409 on mismatch/tamper | local child/operator evidence viewer; path constrained |
| Operator bootstrap | frontend_api | `GET /api/bootstrap` | none | readiness, plans, pending/recent attempts, weak nodes, coverage, profiles, reports, evolution events | DB error | Codex/operator only |
| Operator session close | frontend_api | `POST /api/operator/learning-sessions/{session_id}/complete` | raw session id | full closure package: evidence, answer analysis, graph binding, mastery evaluation, evolution, next plan, agent chain | blocked/waiting/incomplete | Codex/operator only |
| Operator submission | frontend_api | `POST /api/operator/child-submissions` | raw ids allowed for maintenance | id-rich attempt/session/question result | validation/model errors | Codex/operator maintenance |
| Manual grade/backfill | frontend_api | `POST /api/attempts/{id}/grade`, `POST /api/attempts/{id}/analysis` | structured grade or answer_analysis | graded/backfilled attempt | rejects malformed analysis or invalid grading values | Codex/operator maintenance only |
| Evidence invalidation | frontend_api | `POST /api/attempts/{id}/invalidate` | `evidence_note` | invalidated attempt and lineage repair | requires note; no delete | Codex/operator with explicit authorization |
| Maintenance evolution | frontend_api | `POST /api/evolve` | `trigger` | no_action/state/evolved + next plan/report | skips active child group | Codex/operator only |
| Plan generation | frontend_api | `POST /api/plans/generate` | none | id-rich generated plan + planner audit | stale/missing active bank errors | Codex/operator only |
| DB helpers | internal_module | `db.is_current_usable_attempt_evidence` | attempt dict | bool | false on stale/malformed/pending | hard gate for evaluation/planner/evolution/report |
| Model route | internal_module | `model_router.resolve_route`, `call_structured_json` | route, payload, schema | parsed JSON and mode metadata | route disabled, provider error, invalid JSON | all model calls only |
| Answer review | service_interface | `auto_review.review_child_answer` | question, answer text, optional photo data URL | graded review or pending reason | low confidence, malformed output, no route | answer_analysis_agent only |
| Session close | service_interface | `orchestrator.close_learning_session` | session id | closure package or waiting/blocked | incomplete, pending, missing analysis, graph binding failed | authoritative state machine |
| Planner | service_interface | `planner.generate_next_plan` | evidence ledger | 10-task graph-bound plan | no active question candidates | planner_agent boundary |
| Evolution | service_interface | `evolution.run_evolution` | valid analyzed attempts/session | event + audits + optional questions | no_action on no valid evidence | self_evolution_agent boundary |
| Reports | service_interface | `scripts/generate_daily_report.py`, report API/helpers | DB path | Codex-readable evidence report | labels stale/pending/missing | Codex/operator only |
| Codex progress query | operator_workflow | Codex reads DB/API/report artifacts | question such as "进展如何" | summarized progress/results/blockers/next plan based on persisted evidence | must say unknown/stale if evidence is absent | no new runtime result thread/session; no copy-paste handoff |

Field contracts:
| Field | Owner/source | Type | Required/default | Allowed values | Old-data/null handling | Consumers |
|---|---|---|---|---|---|---|
| `node_id` | graph/data | text | required | known graph node id | unknown blocks active use | question, attempt, planner, report |
| `item_version` | question bank | text | required for generated/evolved | current bank/evolved version for scheduling | old attempted rows remain audit only | planner, QA |
| `source_type` | question bank | text | required | `diagnostic`, `graph_generated`, `evolved`, explicit future source | unknown inactive until reviewed | planner, audit |
| `question_review_records.active_eligible` | reviewer gate | bool | required | 0/1 derived from recomputed criteria | missing means inactive for generated/evolved | planner, QA |
| `learning_sessions.status` | orchestrator | text | default `active` | `active`, `closing`, `closed` | legacy mapped to safe blocked/stale if needed | child/operator close |
| `learning_sessions.closure_status` | orchestrator | text | default `not_started` | `not_started`, `waiting_ai`, `blocked`, `evolving`, `planned` | missing means lineage incomplete | child UI, report |
| `learning_sessions.expected_question_ids_json` | planner/session | JSON array | required for child groups | current active question ids | stale ids retire/block session | child submit/close |
| `attempts.grading_status` | answer analysis | text | child submit defaults `pending_review` | `pending_review`, `graded` | pending cannot drive downstream | all agents/report |
| `attempts.result` | answer analysis | text | `submitted` while pending | `submitted`, `correct`, `partial`, `wrong` | submitted valid only pending | evaluation/report |
| `attempts.evidence_status` | evidence ledger | text | default `active` | `active`, `invalidated` | invalidated remains audit, excluded | planner/evolution/report |
| `attempts.answer_analysis_json` | answer_analysis_agent | JSON object | required for usable graded evidence | schema with `agent_key=answer_analysis_agent`, optimal answer, steps, comparison, process gap, teaching explanation, next child prompt | `{}` means missing; blocks downstream | graph/evaluation/planner/evolution/report |
| `attempts.review_meta_json` | model/router | JSON object | required for model audit or pending reason | no secrets | missing scopes evidence claim | QA/report |
| `attempt_attachments` | child submit | row + file | required when photo submitted | png/jpeg/webp, <=8MB, sha256, local path | mismatch returns 409; no blind serve | answer analysis, attachment API |
| `background_jobs.status` | async worker | text | `queued` | `queued`, `running`, `succeeded`, `waiting`, `error` | stale running recovered on startup | worker/session close/report |
| `agent_runs` | internal agents/router | row | required for material agent action | `accepted`, `rejected`, `pending`, `error`; engine `model|deterministic|hybrid|manual_maintenance` | no secrets; missing lineage marked incomplete | review/report/QA |
| `mastery_decisions.applied` | evaluation | bool | required | 0/1 | pending/missing analysis cannot apply | planner/report |
| `evolution_audits` | self_evolution_agent | row | required for evolution event | links attempts, before/after, question review ids | no_action records reason | reports/QA |
| `daily_report` evidence label | reports | enum text | required per claim | `confirmed`, `pending`, `inferred`, `stale`, `blocked`, `missing` | unknown preserved | parent via Codex |

Call chain:
| Step | Caller | Callee | Sync/async | Transaction/state boundary | Failure/retry behavior |
|---|---|---|---|---|---|
| 1 | Browser `/` | `GET /api/child-bootstrap` | sync | may create/load current plan; retire stale sessions | load error -> child retry state |
| 2 | Browser submit | `POST /api/child-submissions` | sync persist | one DB transaction creates session if needed, validates task, records attempt/attachment/job/agent run | duplicate/stale/photo errors return child-safe error; written file cleaned on DB failure |
| 3 | Browser advances | UI state | immediate | no model dependency | keeps draft on save failure |
| 4 | Server after submit/bootstrap/complete | `_start_background_session_processing` | async thread | durable job rows, in-process session lock/rerun set | retries passes; records background errors |
| 5 | Worker | `auto_review.review_child_answer` | async model call outside write lock where possible | no DB writes while waiting for model where tests require | pending on no route/low confidence/malformed analysis |
| 6 | Worker | `db.grade_attempt` + `finish_background_job` | sync DB | only active pending attempt can grade | waiting/error job remains auditable |
| 7 | Browser or worker | `orchestrator.close_learning_session` | sync state machine | missing -> blocked; pending -> waiting_ai; missing analysis -> blocked; ready -> evolving/planned | idempotent closed result on repeat/concurrent calls |
| 8 | Orchestrator | evidence package -> answer package -> graph binding | sync DB | records `agent_runs`, `agent_handoffs`, `session_steps` | graph binding rejection blocks evolution/planning |
| 9 | Orchestrator | `evolution.run_evolution` | sync reducer/model candidate optional | consumes only usable analyzed evidence | no_action if none; audit always records |
| 10 | Orchestrator | `planner.generate_next_plan` | sync | writes `generated_plans` | only current active bank/evolved reviewed questions |
| 11 | Orchestrator | teaching projection | sync | validates child-safe message | child gets review-ready or blocked/waiting projection |
| 12 | Codex report | report script/API | read-only except generated report file | summarizes DB state | labels stale/pending/missing, never invents |

Async/queue decisions:
- async_boundary: Child answer analysis and photo OCR are outside the child request path.
- queue_or_task: Keep local `background_jobs` table and in-process worker for this cycle. Do not introduce Redis/Celery unless a measured local reliability blocker appears.
- idempotency_key: `job_type + session_id + attempt_id` for active job reuse; `session_id` for close; `session_handle + task_position` plus duplicate active attempt check for child submissions.
- timeout_retry_backoff: route timeout from `AI_*_TIMEOUT_SECONDS`; background retry passes from `AI_BACKGROUND_REVIEW_MAX_PASSES`; short exponential sleep capped around current 5s behavior.
- cancellation_recovery: no user cancel in scope. Restart recovery scans `background_jobs` active statuses and active pending child attempts; child bootstrap restarts waiting-ai work when routes are enabled.
- concurrency: `AI_BACKGROUND_REVIEW_CONCURRENCY` capped to a small local number; DB writes serialized per connection/transaction.

Storage/scale decisions:
- database/schema/index: SQLite with additive migrations. Keep existing indexes on question node/source, attempts node/processed status, attachments attempt, agent runs session, mastery session, background job session/status and attempt.
- partitioning_or_sharding: not applicable for single-child local private system.
- expected volume trigger: current release target 56 nodes * 20 active slots + diagnostic/evolved/history. If attempts/agent_runs exceed practical local query latency, add indexes or archive reports before changing DB engine.
- migration/backfill: only additive columns/tables and explicit repair scripts. Question-spec data migration must keep old attempted rows and review records auditable.

External side effects:
- Allowed later implementation side effects: local DB writes, local upload files, generated reports, configured model API calls through router.
- Forbidden without explicit authorization: external publishing/import/export, cloud deployment, account writes, bulk deletion, real-evidence reset, private/commercial content ingestion, secret writes.

Compatibility:
- Child API schema version may increment from current `1.4.0-child`; old raw-id child behavior must remain rejected.
- Operator schema can expose internal ids but must label stale/legacy lineage.
- Existing attempts/questions remain auditable under their original versions; active scheduling uses current-version and reviewer eligibility.
- Missing AI route yields pending/blocked state, not deterministic fake grading.

Contract tests:
- Child projection excludes internal fields and words.
- Child submission rejects internal ids and advances before grading.
- Background jobs recover after restart and do not lock DB during model calls.
- `db.is_current_usable_attempt_evidence` excludes pending, stale, invalidated, missing-analysis, fake/malformed evidence.
- Question reviewer record active gate overrides forged metadata.
- Correct answer with missing/wrong reasoning is capped by semantic/model or local process-evidence guard.
- Photo-only low-confidence OCR stays pending.
- Session close is idempotent and blocks on missing/pending/missing-analysis/graph-binding failure.
- Evolution has `no_action` without valid analyzed evidence and creates audit-linked changes only from usable evidence.
- Daily report separates confirmed/pending/inferred/stale/blocked.

Open questions:
- Final A/B/C/D thresholds and exact data-spec migration stage.
- Human visual/content taste review remains outside this technical contract.

## IMPLEMENTATION_BLUEPRINT - 听云（agentKey: `tingyun`）- 2026-07-08 CST

Objective:
Define file/symbol-level construction plan for a later v2 SKELETON_PASS and subsequent implementation.

Complexity: high_risk_change

Scope:
Program/page/API/schema/test skeleton for the child-only math v2 architecture.

Non-goals:
No business logic fill before skeleton review and TEST_CASE_SPEC. No production code edit in this current task.

Engineering contract:
Use the `ENGINEERING_CONTRACT` above as the binding interface/field/call-chain source.

Behavior contract:
- inputs: child typed answer, optional photo, current learning group handle, task position, operator maintenance requests, model route env vars, graph/question/evidence rows.
- outputs: child-safe state projections, pending/graded attempts, background job rows, structured answer analysis, agent audit rows, next 10-task plan, Codex reports.
- state/data changes: append/version/invalidate evidence; never destructive-delete real evidence; derived status can be recomputed.
- errors/recovery: child-safe retries, pending/waiting/blocked closure, background restart recovery, idempotent close, explicit model unavailable state.
- old-data/backward compatibility: old attempts/questions remain audit evidence; stale active scheduling blocked or retired; reports label incomplete lineage.

Change map for later implementation:
| Step | File/path | Symbol/route/command | Change | Producer/consumer impact | Validation |
|---|---|---|---|---|---|
| 1 | `learning_system/db.py` | schema + predicates | Add explicit v2 schema constants/helpers for session, attempt, job, evidence usability, graph hash, report labels; keep additive migrations | All agents consume one predicate set | unit tests for null/old-data/status matrix |
| 2 | `learning_system/server.py` | child/operator routes | Refactor projections into named v2 serializer functions; keep child handle/position boundary and raw-id rejection | Frontend consumes stable child contract; operator keeps full evidence | API tests + browser smoke |
| 3 | `learning_system/server.py` | background worker | Extract worker shell names for claim/process/retry/recover; keep in-process implementation | Async review becomes reviewable module boundary | restart/retry/concurrency tests |
| 4 | `learning_system/model_router.py` | route resolver/JSON adapter | Preserve GPT default text, Doubao vision, DeepSeek-compatible fallback; expose route status without secrets | All model callers share adapter | router fallback tests |
| 5 | `learning_system/auto_review.py` | answer analysis | Define v2 answer-analysis schema adapter and local validation; keep pending-on-malformed/no-route | Evaluation/planner consume only valid analysis | semantic sample tests |
| 6 | `learning_system/orchestrator.py` | close state machine | Make v2 phase/status transitions explicit; preserve idempotent `waiting_ai|blocked|planned` closure | Child UI/report know exact states | close idempotency and blocked-state tests |
| 7 | `learning_system/planner.py` | plan generator | Keep 10-task graph-bound selection and prerequisite rollback; expose v2 plan task DTO | Child API and reports consume consistent plan | planner tests + question audit |
| 8 | `learning_system/evolution.py` | evolution reducer | Keep no_action for no valid evidence; require audit-linked question review records | Reports/QA can trace evolution | evolution/invalidation tests |
| 9 | `learning_system/question_bank.py` | quality gates + loader seam | Add data-spec loader seam while preserving Python gate as authority in Stage 1 | Future specs can migrate without bypassing reviewer | parity tests, grade-level audit |
| 10 | `learning_system/internal_agents.py`, contracts/prompts | child-safe/schema metadata | Define v2 agent contract version metadata and child-safe validation hooks | agent audit rows remain traceable | prompt/contract tests |
| 11 | `learning_system/reports.py`, `scripts/generate_daily_report.py` | reports | Define v2 report evidence labels and pending/blocker sections | Parent via Codex gets evidence-grounded report | report CLI tests |
| 12 | `app/local_learning_system/*` | `/` route shell | Create explicit state renderer fixtures for loading/empty/active/saving/reviewing/review_ready/blocked/errors | 清秋/观止 can screenshot states | browser visual/state tests |
| 13 | `tests/test_learning_system.py` | test shells | Add/organize v2 contract tests before logic fill | 观止 can produce TEST_CASE_SPEC from skeleton | unittest discovery |
| 14 | `tests/browser_smoke_learning_system.mjs` | browser state fixtures | Add deterministic screenshots/checks for all UX states | visual QA and child-boundary checks | Playwright smoke |
| 15 | `scripts/*.py` | validation commands | Keep audit/report/live scripts compatible with v2 schema labels | operator validation stable | command smoke |

Skeleton plan:
| Step | File/path | Module/type/interface/class/function/route/handler | Skeleton to create | Compile/static check |
|---|---|---|---|---|
| 1 | `learning_system/db.py` | `EvidenceUsePolicy`, `SessionClosureStatus`, helper predicates | constants/functions with existing implementation delegated or stubbed safe | `python3 -m unittest tests/test_learning_system.py -v` |
| 2 | `learning_system/server.py` | `ChildAPIProjection`, `OperatorAPIProjection`, route handlers | named projection helpers and route shells matching contract | API unit tests |
| 3 | `learning_system/server.py` | `BackgroundReviewWorker` shell | claim/process/recover method skeleton wrapping current logic | background tests |
| 4 | `learning_system/model_router.py` | `ModelRoute`, structured JSON adapter | v2-compatible route status helper, no secrets | router tests |
| 5 | `learning_system/auto_review.py` | `AnswerAnalysisResult` schema adapter | normalize/validate/pending result shell | semantic tests |
| 6 | `learning_system/orchestrator.py` | `SessionClosureStateMachine` shell | explicit transition functions and closure result DTO | close tests |
| 7 | `learning_system/planner.py` | `PlanTaskDTO`, `generate_next_plan` seam | task DTO sanitizer and evidence-signal helper | planner tests |
| 8 | `learning_system/evolution.py` | `EvolutionAuditPackage` shell | audit package builder and no-action guard | evolution tests |
| 9 | `learning_system/question_bank.py` or `data/question_specs/` | `QuestionSpecLoader` seam | loader interface/stub; Python gate remains active | audit + parity shell |
| 10 | `app/local_learning_system/app.js` | state machine/render functions | deterministic state fixture renderer and API adapter shell | browser smoke |
| 11 | `app/local_learning_system/index.html` | semantic child layout | shell DOM slots for all UX states | browser smoke |
| 12 | `app/local_learning_system/styles.css` | responsive state styles | stable dimensions and focus/error/review states | screenshots |
| 13 | `tests/test_learning_system.py` | v2 contract classes | failing/pending test shells if business logic not filled; no false PASS | unittest |
| 14 | `tests/browser_smoke_learning_system.mjs` | fixture state checks | visual/interaction skeleton smoke | node smoke |

Page prototype / route shell plan:
| Surface/route | Prototype or shell | Primary states | Data/API placeholders | Validation |
|---|---|---|---|---|
| `/` child learning page | One focused learning surface, no dashboard | loading, empty, active_task, saving, save_error, upload_error, all_submitted_reviewing, review_ready, blocked, load_error | fixture DTOs for 10 tasks, photo preview, review points, pending/blocked completion | desktop/mobile screenshots, text overflow, keyboard/focus |
| `/api/child-bootstrap` | child-safe DTO shell | no group, active group, reviewing, review ready | no raw ids, no internal terms | API test + forbidden text scan |
| `/api/child-submissions` | save-and-advance shell | saved, duplicate, stale, invalid photo | handle + task position only | API timing + duplicate tests |
| `/api/learning-sessions/current-learning-group/complete` | closure projection shell | waiting_ai, blocked, planned | child message with all-question review list when planned | API/browser tests |
| Operator routes | id-rich shells | full audit/readiness/report | raw ids allowed only here | unit/API tests |

Tests to add/update later:
- API contract tests for every child/operator route shape.
- State-machine tests for all session close statuses and idempotency.
- Evidence usability matrix tests for pending/graded/missing-analysis/invalidated/stale/fake.
- Model router compatibility tests for GPT JSON schema, JSON object fallback, plain JSON fallback, DeepSeek chat-completions fallback, Doubao vision route.
- Semantic answer-analysis samples: right answer no process, wrong reasoning, alternative valid, blank, stuck, photo low-confidence, no evaluator route.
- Question quality migration parity tests if data specs are introduced.
- Browser fixture screenshots for all UX states and mobile.
- Report tests for confirmed/pending/inferred/stale/blocked labels.

Test design handoff:
- expected TEST_CASE_SPEC: required, because this is high-risk, semantic/model-heavy, async/stateful, graph/data-bound, and child-facing.
- test file targets: `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`, optional scenario/live scripts under `scripts/` for QA-owned evidence.

Validation commands:
- Read-only inspection:
  - `jq empty data/knowledge_graphs/math/math_knowledge_graph_v2.json`
  - `jq '.nodes | length' data/knowledge_graphs/math/math_knowledge_graph_v2.json`
  - `python3 scripts/audit_question_bank_grade_level.py --db data/local_learning_system.sqlite`
- Test-environment mutating validation:
  - `python3 scripts/init_learning_system_db.py` writes/refreshes the local SQLite ledger.
  - `python3 scripts/generate_daily_report.py --db data/local_learning_system.sqlite` writes daily report markdown artifacts.
  - `python3 -m unittest tests/test_learning_system.py -v` may create/reset local test DB state through test setup.
  - `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs` requires a controlled local server/test state and may create screenshot artifacts.
- Service/manual validation:
  - `python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765` starts local service and may resume queued background jobs when model routes are configured.

Implementation order for later:
1. Create/normalize skeleton types, DTOs, projection helpers, and status constants without changing business behavior.
2. Add test shells/fixtures for contracts.
3. Stop at SKELETON_PASS for 镜花/清秋/霜弦 review and 观止 TEST_CASE_SPEC.
4. After gates, fill business logic in DB/API/worker/router/orchestrator/planner/evolution order.
5. Run validation and self-review against this blueprint.

Rollback/recovery notes:
- Before any real DB-affecting implementation run, back up `data/local_learning_system.sqlite` and `data/uploads/answers/`.
- Keep migrations additive and old evidence readable.
- If v2 route breaks, revert route/projection code while preserving DB audit rows.
- If question-spec loader fails parity, disable loader and keep Python gates authoritative.
- If model route fails, attempts remain pending/blocked and do not drive downstream state.

Blueprint stop conditions:
- Stop after skeleton creation and before non-trivial business logic.
- Stop if any upstream product/UX/data contract contradiction appears.
- Stop if implementation would require parent dashboard, external content, destructive evidence changes, or secret handling.

Open questions:
- Exact final data-spec file format for full question migration.
- Final visual/copy taste after rendered review.
- Long-run mastery threshold tuning.

## Project skeleton definition

Purpose:
Define the planned skeleton that a later SKELETON_PASS must create or normalize before business logic fill.

Skeleton modules:
| Layer | Planned skeleton | Required visible contracts |
|---|---|---|
| Frontend child shell | `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css` | one child page; explicit state enum; fixture renderer; photo picker/preview/remove; primary CTA; all-question review list; blocked/retry state; no internal leakage |
| Child API projection | `learning_system/server.py` projection helpers | child DTOs for bootstrap/submission/complete; no raw ids; no model/agent/graph/rubric terms |
| Operator API projection | `learning_system/server.py` operator helpers | id-rich audit DTOs; reports/maintenance only; clearly not child/parent dashboard |
| Evidence ledger | `learning_system/db.py` | additive schema helpers, evidence usability predicate, graph/hash/version fields, invalidation repair hooks |
| Async review | `learning_system/server.py` worker shell + `background_jobs` helpers | durable job state, claim/run/finish/wait/error/recover methods, startup/bootstrap recovery |
| Model routing | `learning_system/model_router.py` | GPT text default, Doubao vision default, provider/env override, responses/chat endpoint fallback, JSON mode fallback, secret-free audit metadata |
| Answer analysis | `learning_system/auto_review.py` | structured schema adapter, local validation, process-evidence guard, photo OCR untrusted evidence, pending-on-no-route |
| Internal agents | `learning_system/internal_agents.py`, `agent_contracts`, `prompts` | nine-agent registry; contract metadata; prompt/schema hash; child-safe validator |
| Orchestrator | `learning_system/orchestrator.py` | explicit close state machine, evidence package, answer package, graph binding, evaluation, planner, teaching, close audit |
| Graph/evaluation/planner | `learning_system/planner.py`, `flow_nodes`/existing helpers | prerequisite rollback, 10-task plan DTO, current active question gate, node-local mainline floor, controlled picture-level quota |
| Evolution | `learning_system/evolution.py` | no_action guard, audit package, reviewer-gated evolved question path, invalidated-source exclusion |
| Question spec migration seam | `learning_system/question_bank.py`, optional `data/question_specs/` | loader interface/stub; Python quality gate remains source of truth until parity approved |
| Reports | `learning_system/reports.py`, `scripts/generate_daily_report.py` | DB-derived report labels; pending/blocker/system issue sections |
| Tests/QA hooks | `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`, `scripts/*.py` | contract tests, fixture states, semantic matrix hooks, visual smoke commands |

Skeleton acceptance checklist:
- Child route renders all UX states with deterministic fixtures.
- Child API contracts are represented by named DTO/projection helpers.
- Operator API remains id-rich but separated from child flow.
- SQLite tables/predicates are explicit enough for review.
- Background worker boundary is visible and idempotency keys are named.
- Model router routes and fallback modes are visible and testable.
- Answer-analysis schema and pending/error states are visible.
- Agent chain boundaries and audit rows are visible.
- Planner/evolution/report consumers all call the same evidence usability predicate.
- Validation commands are present in docs/tests/scripts.
- Business logic can remain stubbed or delegated, but stubs must fail safe and must not claim feature completion.

Required next gates after SKELETON_PASS:
- 镜花 design review for architecture, state machine, async recovery, model adapter, child-safe boundary, and skeleton fidelity.
- 清秋 UX review for child route states, responsive layout, copy boundary, and interaction clarity.
- 霜弦 data/content review for graph/question/evidence contracts and question-spec migration seam.
- 观止 TEST_CASE_SPEC before business logic implementation.

## Stop condition

This technical package stops when it is concrete enough for 镜花 design review and, if approved, for a later code SKELETON_PASS without guessing interfaces, fields, async boundaries, model routes, validation commands, or child/operator boundaries.

Current task stop status:
- Completed for architecture/spec package.
- No production code edited.
- No skeleton files created.
- No external side effects performed.
