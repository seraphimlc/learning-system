### TECHNICAL_PLAN - 听云（agentKey: `tingyun`）- 2026-07-11 CST

Objective:
Define the authoritative v5 engineering direction for the single-child AI-native math loop after 若命 synthesis: runtime remains deterministic and authoritative, while `answer_analysis_agent`, `evaluation_agent`, `planner_agent`, and conditional `teaching_agent` become true durable, retryable model stages.

Scope:
- Child daily flow/current-step runtime.
- Durable async model stage DAG after saved child evidence.
- Deterministic evidence gate, state persistence, idempotency, recovery, and child projection.
- Model route/trust envelope, bounded context, no-full-bank planner input.
- SQLite/in-process worker hardening, reports, UI state alignment, and test/QA routing.

Non-goals:
- No production/test code edit in this artifact update.
- No DB reset, external model call, parent Web UI, multi-user shell, active self-evolution, new service, or MySQL.
- No change to PRD/Product Structure/UX docs.
- No QA PASS, UX PASS, live-course PASS, or implementation DONE claim.

Project boundary overlay:
- Single child, math first, local SQLite.
- Every question, analysis, evaluation, teaching, plan, and report binds to graph node lineage.
- Grade-7 failure checks prerequisite chains before blind same-type drilling.
- Child surface shows one current step and no graph ids, question ids, attempt ids, model/provider/job/queue/rubric internals.
- Pending/mock/stale/missing-lineage evidence cannot update mastery or be reported as confirmed.
- Mock/patch/recorded fixtures must never be labeled `live_model`.

Source readiness:
- PRD v5: `docs/product/ai_native_math_learning_prd_v5.md` requires save-before-analysis, AI semantic judgment, teaching/repair, next-step selection, summary, and honest failed/pending states.
- Product Structure v5: `docs/product/ai_native_math_learning_product_structure_v5.md` requires runtime-owned transitions, bounded candidate packets, no full-bank planner context, and trust labels.
- UX Flow v5: `docs/product/child_ux_flow_spec_v5.md` requires bounded analyzing, real blocked retry, clarify/cannot-provide, and terminal summary actions.
- Runtime contract: `docs/architecture/daily_learning_runtime_contract_v1.md` classifies runtime/service/agent/gate ownership and says planner chooses one current step, not a fixed list.
- MSG-20260711-002: `docs/collaboration/inbox.md` requires durable recovery, true acceptance, GPT text, Doubao vision, and no mock-as-live.
- Current code evidence:
  - `learning_system/daily_runtime.py` has `DailyLearningRuntime`, `persist_child_response`, `process_next_background_job`, inline `_handle_answer_analysis_job`, deterministic `_record_evaluation_update`, deterministic `_record_next_step_decision`, and child projection aliases.
  - `learning_system/job_queue.py` has durable queue primitives and reserved job types.
  - `learning_system/model_router.py` already exposes routes for answer analysis, evaluation, planner, teaching, and Doubao vision.
  - `learning_system/db.py` already has `agent_runs`, `background_jobs`, `evidence_validations`, `mastery_decisions`, `next_step_decisions`, `daily_summaries`, and relevant unique indexes.
  - `learning_system/internal_agents.py` and `learning_system/prompts/planner_transition.v1.md` still describe a legacy 10-task planner and must be replaced for v5.

ENGINEERING_SOURCE_READINESS:
- verdict: ENGINEERING_SOURCE_READY
- prd_quality_gate_checked: yes
- product_source_content_ready: yes
- downstream_guessing_risk: none for this architecture update
- product_scope_ready: yes
- product_structure_ready: yes
- ux_flow_ready: yes
- data_contract_ready: yes, supplied by this plan plus `engineering_contract_v5.md`
- project_boundary_ready: yes
- codebase_recon_ready: yes
- architecture_context_ready: yes
- authorization_ready: yes for editing the three v5 architecture docs only
- validation_targets_ready: yes
- missing_or_low_quality_sources: none blocking; real threshold tuning and live fixture policy remain conservative implementation/test constants
- impact_on_engineering_quality: source-ready for design review; production code must wait for 镜花 DESIGN_REVIEW
- route_back_to_ruoming: none
- allowed_scoped_output: update `technical_plan_v5.md`, `engineering_contract_v5.md`, `implementation_blueprint_v5.md`
- retry_condition: not applicable

Authoritative architecture decision:
Use a hybrid durable DAG.

```text
child submit text/photo/stuck
-> runtime saves attempt/attachments and enqueues answer_analysis
-> answer_analysis job calls true answer_analysis_agent, records agent_run
-> runtime runs deterministic EvidenceGate immediately
-> if evidence usable, enqueue evaluation_update
-> evaluation_update job calls true evaluation_agent
-> runtime validates output and applies/records mastery decision
-> enqueue planner_decision
-> planner_decision job calls true planner_agent with graph/learner summaries and 5-8 candidate packet
-> runtime validates one next action
-> if action needs generated teaching/example/clarification support, enqueue teaching_generation
-> teaching_generation job calls true teaching_agent
-> runtime validates and materializes teaching/current step
-> otherwise runtime materializes selected question, blocked state, ready checkpoint, or summary
```

Evidence validation is deterministic and not its own external-model job. It may be recorded as a phase/result ref inside the `answer_analysis` job and as an `evidence_validations` row.

Runtime/service/gate/agent split:
- Runtime: `DailyLearningRuntime`, server worker, state transitions, transactions, queue orchestration, idempotency, retry terminal policy, child projection, summary materialization.
- Service: graph lookup/rollback, learner-state summaries, question-bank active-use checks, candidate packet construction, report reads.
- Gate: `EvidenceGate`, child-safe projection scan, model output schema/lineage/trust validators, active-question gate.
- True model agents:
  - `answer_analysis_agent`: semantic answer/process/photo evidence analysis.
  - `evaluation_agent`: converts accepted evidence package into bounded mastery/evaluation recommendation.
  - `planner_agent`: selects exactly one next action/question from bounded summaries/candidate packet.
  - `teaching_agent`: conditionally generates child-safe teaching, worked example, clarification wording, or micro-check support.
- Deterministic records must be labeled `deterministic_runtime`, not as true model runs.

Job DAG decision:
- Required external-model job types: `answer_analysis`, `evaluation_update`, `planner_decision`, `teaching_generation`.
- Not an external-model job: `evidence_validation`.
- No old open question remains: v5 must not run evaluation/planner/teaching as deterministic pseudo-agent rows except as a temporary compatibility fallback clearly labeled `deterministic_runtime` and not counted as semantic Agent acceptance.
- Dependent job creation is runtime-owned and idempotent. Every downstream job depends on accepted output refs from its predecessor.

Planner decision:
- The v5 planner is not the legacy 10-task planner.
- It receives only compact trusted summaries plus a bounded 5-8 candidate packet.
- It returns exactly one action: `same_structure_retest`, `near_transfer_retest`, `prerequisite_probe`, `micro_teach`, `worked_example`, `clarify_evidence`, `continue_new_knowledge`, `stretch`, `summary`, or `blocked`.
- It must not receive the full graph, full question bank, long reports, all attempts, or solution banks for unselected candidates.
- Candidate packet rows contain metadata and active-use proof; full solution/rubric is fetched only by runtime after selection.

Model/provider strategy:
- Text semantic agents use GPT-compatible routes through `model_router` defaults and env overrides.
- Vision/OCR uses the Doubao vision route through `answer_photo_vision_route`.
- All calls use structured JSON contracts with `prompt_version_id`, schema version/hash, route metadata, input digest, output digest, confidence, provider mode, and trust label in `agent_runs`/job result refs.
- Provider modes: `live_model`, `recorded_model`, `mock_only`, `not_configured`, `deterministic_runtime`.
- Mastery-affecting writes require usable evidence and a route/trust label allowed by the current test/live policy. `mock_only`, `not_configured`, stale, pending, and missing-lineage never update mastery.

Worker/recovery strategy:
- Keep local SQLite plus one in-process durable worker loop.
- The worker claims due jobs by status and dependency, starts them under lease, heartbeats/recovers expired leases, and records operator-visible worker errors.
- Worker exceptions must not be silently swallowed. They must create job `dead_letter`/`blocked` state and an operator-visible `agent_run` or job error record.
- Child bootstrap may wake due `queued`/`retry` jobs, but `waiting` is not runnable unless an explicit reconciler changes it.
- Max retries/backoff are contract constants, tuneable after QA:
  - answer/evaluation/planner/teaching retryable model errors: max 3 attempts, backoff 20s, 60s, 180s.
  - malformed structured output: max 2 attempts, then `blocked` with child-safe retry/finish path.
  - not configured: no retry loop; block with operator-visible config reason.

Storage/migration direction:
- Use existing tables first.
- Additive migration only if implementation needs queryable phase fields not safely held in `background_jobs.result_refs_json` or existing `agent_runs`.
- Required compatibility:
  - v5 emits v5 route/env/status names.
  - legacy v3 rows/env/routes remain readable through compatibility aliases.
  - no destructive migration; preserve real learning data.

UX P0 routing:
- Analyzing cannot be unbounded: job terminal states must project to next current step, clarify, blocked retry, or summary.
- Blocked state must offer real retry when retryable work exists and finish-to-summary when safe.
- Clarify evidence must support cannot-provide/stuck, leading to teaching/blocked/summary without fake mastery.
- Summary must have a terminal child action and must not imply pending/mock/stale evidence is mastered.

QA P0 routing:
- Trust labels and provider modes are first-class contract fields.
- Every phase has lineage: predecessor job id, agent_run id, evidence validation id, mastery decision id, next-step decision id, candidate packet id/hash, or teaching package id.
- Lease/idempotency recovery must be tested across restart/retry.
- Malformed agent output must fail closed.
- Graph rollback before blind drilling must be tested.
- Browser states must be driven by real runtime projections, not only fixtures.
- A v5 10-lesson harness must simulate consecutive lessons using recorded/patchable semantic fixtures without labeling them live.

Alternatives rejected:
- Single root job that calls answer analysis and then deterministically evaluates/plans/teaches: rejected for final v5 because it violates the true semantic Agent boundary.
- Split deterministic evidence validation into its own durable job: rejected as unnecessary over-splitting; it is a runtime gate immediately after answer analysis.
- Legacy `planner.py` 10-task round or `planner_transition.v1` contract: rejected for v5 hot path.
- Full-bank/full-graph model planning: rejected by Product Structure and runtime contract.
- New service/database: rejected for current single-child local scale.

Validation strategy:
- Markdown/static: parse docs and scan for forbidden contradictions such as `10 tasks`, `root job remains`, or `reserved for later split`.
- Unit/API after implementation: durable job DAG, idempotency keys, retry terminal states, malformed output, trust labels, no mastery from mock/pending/stale/missing-lineage.
- Browser after implementation: current step, analyzing pending, clarify/cannot-provide, blocked retry, teaching, summary, no internal leakage.
- Report after implementation: phase lineage and trust labels from latest v5 daily flows.
- Harness: 10-lesson recorded/patchable v5 runtime simulation with no external model calls by default and no mock-as-live labels.

TECHNICAL_PLAN_QUALITY_GATE:
- verdict: TECH_PLAN_READY_FOR_DESIGN_REVIEW
- product_fit: pass
- architecture_fit: pass
- simplest_sufficient_design: pass; no new service/DB, deterministic gate not over-split
- contract_risks_identified: pass; true Agent stages, job DAG, trust labels, retry/recovery, compatibility named
- failure_resilience_planned: pass
- testability_planned: pass
- maintainability_fit: pass
- security_privacy_checked: pass
- operability_checked: pass
- performance_cost_checked: pass; bounded hot-path context and retry limits named
- quality_evidence: docs and current code symbols listed above; no implementation claimed
- blocking_quality_gaps: none for 镜花 DESIGN_REVIEW; production code waits for review

Stop condition:
This plan is ready for `engineering_contract_v5.md` and `implementation_blueprint_v5.md` in the same artifact update, then 镜花 DESIGN_REVIEW. It does not authorize production code.
