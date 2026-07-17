### ENGINEERING_CONTRACT - 听云（agentKey: `tingyun`）- 2026-07-11 CST

Objective:
Specify executable v5 contracts for the durable true-Agent math learning pipeline: child evidence -> answer analysis -> evidence gate -> evaluation -> planner -> optional teaching -> runtime materialization -> child projection/report.

Scope:
`DailyLearningRuntime`, `JobQueue`, `EvidenceGate`, `model_router`, `auto_review`/new model adapters, agent contracts/prompts, SQLite rows, server worker, child API projections, reports, tests, and compatibility aliases.

Non-goals:
No production code edit in this artifact update, no DB reset, no external model call, no parent Web UI, no active self-evolution, no new service/database.

Authoritative job DAG:

| Order | Durable job | True model call | Required predecessor | Runtime gate/reducer after success | Downstream |
|---|---|---|---|---|---|
| 1 | `answer_analysis` | `answer_analysis_agent` through text route and optional Doubao vision OCR | saved active attempt | validate schema, record `agent_runs`, run deterministic `EvidenceGate`, write `evidence_validations` | enqueue `evaluation_update` if usable; create `clarify_evidence`/blocked/summary if pending or unusable |
| 2 | `evaluation_update` | `evaluation_agent` | passed evidence validation | validate recommendation, apply or reject mastery through runtime only, write `mastery_decisions`/`learner_node_status` | enqueue `planner_decision` only after an accepted evaluation output |
| 3 | `planner_decision` | `planner_agent` | accepted `evaluation_agent` run plus accepted/applied-or-explicitly-rejected runtime evaluation reducer output | validate one action, candidate lineage, graph rollback policy, trust label, write `next_step_decisions` | materialize selected question/summary/blocked or enqueue `teaching_generation` |
| 4 | `teaching_generation` | `teaching_agent` | planner action requiring teaching/example/clarification support | validate child-safe teaching package and node binding | materialize `teaching_repair`, `worked_example`, `clarify_evidence`, or micro-check support |

`evidence_validation` is a deterministic gate phase, not a separately required external-model job. The existing `evidence_validation` job type may remain as compatibility/reserved, but v5 should not enqueue it for the normal hot path.

Terminal evaluation failure rule:
- `planner_decision` is never enqueued from `evaluation_update` jobs whose model output is malformed after retry, rejected by schema/lineage validation, `not_configured`, `blocked`, or `dead_letter`.
- Terminal evaluation failure is handled by runtime materialization only: child-safe `blocked` with retry/finish when honest, or safe `summary` when the day can close without pretending mastery.
- Safe pending/block contexts can be summarized by runtime, but they do not create a planner model job unless there is an accepted evaluation envelope to plan from.

Interface contracts:

| Interface | Method/symbol | Request/input | Response/output | Error behavior | Consumer |
|---|---|---|---|---|---|
| Child bootstrap | `GET /api/child-bootstrap` | none | canonical v5 child projection | blocked projection on recoverable server/runtime issue | child UI |
| Start review | `POST /api/daily-flow/review/start` | `client_day_key` | active flow and one current step | child-safe 409/blocked if graph/bank unavailable | child UI |
| Submit current step | `POST /api/current-step/submit` | `step_handle`, `position`, `client_idempotency_key`, text/photo/stuck | attempt saved, `answer_analysis` job enqueued, analyzing projection | duplicate idempotently reuses; stale step 409; no model sync wait | child UI, worker |
| Continue current step | `POST /api/current-step/continue` | handle/position/stuck | records exposure/transition and next micro-check or summary | stale handle 409; stuck handled as evidence, not mastery | child UI |
| New knowledge start | `POST /api/daily-flow/new-knowledge/start` | `client_day_key` | worked example or blocked/summary | no parent approval path | child UI |
| Finish | `POST /api/daily-flow/finish` | optional reason | terminal summary | cannot claim pending as mastered | child UI/report |
| Worker process | `DailyLearningRuntime.process_next_background_job(worker_id, flow_id=None)` | worker id | processes one due job and returns result refs | retry/block/dead_letter with operator-visible reason | server worker/tests |
| Queue adapter | `JobQueue.enqueue/claim/start/retry/finish/wait/block/dead_letter/recover` | job payload, idempotency, lease owner | durable status transition | stale owner no-op; invalid payload raises in caller transaction | runtime |
| Evidence gate | `EvidenceGate.validate_attempt` | attempt id, analysis version, provider mode, answer agent run id | validation row/result | fail closed as pending/rejected/blocked | runtime/evaluation/report |
| Model call boundary | `model_router.*_route` + structured adapter | trusted context + untrusted payload + schema | model envelope and parsed JSON | retryable `ModelCallError`, contract error, not_configured | model jobs |
| Operator inspect/report | existing operator/report functions | local date/flow | internal rows and trust labels | never child-safe guarantee | Codex/report |

Canonical child projection states:
- `start_resume`
- `current_step`
- `analyzing_pending`
- `feedback_teaching`
- `clarify_evidence`
- `ready_for_new_knowledge`
- `blocked`
- `summary`

Legacy aliases (`choose_review`, `analyzing`, `teaching`, `V3_*`, `_v3_*`) may be accepted by compatibility adapters and old tests, but new v5 emissions must use v5 names.

Job payload contract:

Common required fields for all v5 model jobs:
- `payload_schema_version`: `2026-07-11.v5.model-job.v1`
- `job_type`
- `flow_id`, `flow_revision`
- `flow_step_id`, `step_revision`
- `attempt_id`, `attempt_version` when attempt-bound
- `graph_version`, `question_bank_version`
- `node_id`
- `question_id` and `review_record_id` when question-bound
- `source_job_ids`
- `source_agent_run_ids`
- `source_evidence_validation_ids`
- `source_mastery_decision_ids`
- `candidate_packet_id`, `candidate_packet_hash` when planner-bound
- `provider_mode`
- `route_meta`: provider, model alias, timeout, prompt/schema versions
- `available_at`

Idempotency keys:
- `answer_analysis`: `v5:answer_analysis:{attempt_id}:{attempt_version}:{evidence_digest_sha256}`
- `evaluation_update`: `v5:evaluation_update:{attempt_id}:{evidence_validation_id}:{answer_analysis_agent_run_id}`
- `planner_decision`: `v5:planner_decision:{flow_id}:{flow_revision}:{source_step_id}:{evaluation_agent_run_id}:{candidate_packet_hash}`
- `teaching_generation`: `v5:teaching_generation:{flow_id}:{flow_revision}:{planner_decision_id}:{target_node_id}:{action}`
- Runtime materialization no-op key: existing unique indexes plus source ids/version/hash; do not create duplicate current steps or summaries on rerun.

Terminal-aware stage idempotency:
- V5 enqueue/handler code must first look up the same v5 idempotency/source-phase key across active and terminal statuses, not only active queue rows.
- If a matching `succeeded` stage exists and its source refs, graph/question-bank versions, provider/trust policy, and result refs are still valid, the runtime reuses that output and advances the dependent stage without re-calling the model.
- If a matching terminal `blocked`, `dead_letter`, or non-runnable `waiting` stage exists, the runtime reuses the terminal outcome for child projection/report unless an explicit retry/reconciler path creates a new source-phase key.
- Active-only lookup is insufficient because retry/restart after a terminal write could otherwise enqueue duplicate semantic model stages or duplicate materialized steps.
- Implementation may use existing `background_jobs.idempotency_key`, `result_refs_json`, source ids, `agent_runs` unique triggers, and current unique indexes; this contract does not require destructive schema changes.

Job status transitions:

```text
queued -> claimed -> running -> succeeded
queued -> claimed -> running -> retry -> queued
queued -> claimed -> running -> waiting
queued -> claimed -> running -> blocked
queued -> claimed -> running -> dead_letter
claimed/running with expired lease -> retry/queued by recover()
```

Status meanings:
- `queued`: ready when dependencies and `available_at` allow.
- `retry`: transient model/lease failure; runnable after `retry_after`.
- `waiting`: not runnable by generic worker; requires child clarification or explicit reconciler.
- `blocked`: safe terminal for known non-retryable issue; child gets retry/finish only if runtime can do it honestly.
- `dead_letter`: unexpected exception after worker-owned attempt; operator-visible.

Retry/backoff contract:
- Retryable model/provider errors: max 3 attempts per job, backoff 20s, 60s, 180s.
- Malformed JSON/schema output: max 2 attempts; then `blocked` with report label `blocked` and no mastery change.
- Not configured: no retry loop; `blocked` with provider mode `not_configured`.
- Lease expiry: recover to retry without incrementing semantic attempt beyond queue `run_count`.
- `run_count` and `last_error` must be visible in operator inspect/report.

Worker lifecycle:
- Startup and child bootstrap may wake due `queued`/`retry` jobs for open flows.
- In-process worker keeps one active thread per flow, with rerun flag if a new job arrives.
- Worker loop processes bounded jobs per pass and stops on idle, blocked, waiting, or max jobs.
- Exceptions must call runtime error recorder and mark the job/flow safely; silent swallow is forbidden.
- The worker must never expose job ids/statuses to the child projection.

Model envelope contract:

Every true model stage records an `agent_runs` row:
- `agent_key`: one of `answer_analysis_agent`, `evaluation_agent`, `planner_agent`, `teaching_agent`
- `engine_type`: `model`
- `phase`: same as job type
- `trigger`: stable v5 idempotency trigger
- `input_refs_json`: source ids only, not full hidden dumps
- `input_digest_sha256`
- `prompt_version_id`
- `prompt_template_sha256`
- `rendered_prompt_sha256`
- `model_provider`, `model_name`, `model_alias`
- `model_params_json`: timeout, temperature if applicable
- `response_schema_version`, `response_schema_sha256`
- `status`: `accepted`, `rejected`, `pending`, `error`
- `confidence`
- `output_json`
- `output_digest_sha256`
- `validation_errors_json`
- `error_reason`

Provider/trust labels:
- `live_model`: real configured provider call.
- `recorded_model`: deterministic replay of a captured model envelope; acceptable for tests/harness, never mislabeled live.
- `mock_only`: patch/fake data; cannot update mastery outside tests and must be labeled in reports.
- `not_configured`: provider unavailable; no mastery.
- `deterministic_runtime`: runtime/gate/service decision, not a semantic Agent.

Agent input/output contracts:

| Agent | Input limit | Required output | Runtime validator |
|---|---|---|---|
| `answer_analysis_agent` | one question package, one child response, optional OCR, rubric/valid approaches for selected question only | result, confidence, answer/process comparison, process gap, error tags, explanation support, next child prompt | schema, confidence, no internal leakage, node/question lineage, provider trust |
| `evaluation_agent` | one accepted answer analysis, node summary, recent usable evidence for affected node/prerequisites | node status recommendation, dimensions, reason, planner signal, confidence, source validation ids | evidence gate passed, no raw answer regrading, no direct DB mutation, conservative threshold |
| `planner_agent` | graph/learner summary, pending summary, budget, recent steps, 5-8 candidate metadata rows, max 2 teaching action options | exactly one action, selected candidate/action, target node, reason, branch policy, confidence | one action only, candidate in packet, rollback policy, no 10-task plan, no stale/mock evidence as confirmed |
| `teaching_agent` | one diagnosis, graph teaching contract, allowed teaching move, child-safe style constraints | teaching package or worked example/clarify copy, micro-check support, confidence | child-safe scan, graph node binding, no provider/rubric/internal ids, no mastery claim |

Planner candidate packet schema:
- `packet_id`, `packet_schema_version`, `packet_hash`
- `flow_id`, `flow_revision`
- `graph_version`, `question_bank_version`
- `target_node_id`, optional prerequisite path
- `source_review_target_id`
- `candidate_count`: 0-8; hot path target 5-8 when available
- `filter_summary`: active rows seen, excluded stale/inactive/duplicate/cooldown/mastered/missing-lineage
- `candidates[]`: `question_id`, `node_id`, `item_version`, `review_record_id`, `family`, `kind`, `difficulty_vector`, `evidence_goal`, `target_error_tags`, `requires_reasoning`, `recent_use_status`, `why_candidate`
- Forbidden in packet: full bank, full graph, answer solution banks for unselected candidates, long reports, provider internals.

Runtime reducers:
- Answer reducer: accepted answer analysis updates attempt analysis fields, records agent run, then calls `EvidenceGate`.
- Evidence gate: writes `evidence_validations`; rejected/pending evidence cannot enqueue mastery update except safe clarify/block/summary.
- Evaluation reducer: applies mastery only after accepted `evaluation_agent` output and passed evidence validation; runtime writes `mastery_decisions` and `learner_node_status`.
- Planner reducer: writes `next_step_decisions` only after accepted planner output or explicit safe fallback; runtime materializes exactly one next state.
- Teaching reducer: writes child-safe teaching step/package only after accepted teaching output; no mastery from reading/continuing.

Migration/compatibility:
- Mandatory destructive migration: none.
- Additive schema allowed only for:
  - phase/job dependency indexes if existing fields are insufficient,
  - agent contract version fields if not already covered by `agent_runs`,
  - operator-visible worker error audit if not representable in jobs/agent runs.
- Existing v3 rows/routes/env remain readable. New docs/code must emit v5 names and may map old names at boundaries.
- Existing legacy planner and prompt/contract files must not be used for v5 hot-path planner. Add v5 contracts/prompts instead of editing history in a way that breaks legacy tests.

Failure/rollback:
- If answer analysis fails retryably: keep child in bounded `analyzing_pending`; after terminal failure project `blocked` with retry/finish.
- If answer output is low-confidence/photo unclear: no mastery; ask `clarify_evidence` or allow cannot-provide.
- If evaluation fails: evidence remains recorded but no mastery update; planner may only choose safe blocked/summary after terminal failure.
- If planner fails: no new mastery change; current flow blocks or summarizes with source labels.
- If teaching fails: planner decision remains recorded; runtime can block, retry teaching, or summarize, but must not fabricate teaching.
- If job reruns after success: use idempotency/source hashes to no-op or reuse rows.
- Rollback is logical only: supersede steps, label invalid/blocked/stale, preserve audit rows.

Producer/consumer map:

| Producer | Data | Consumer |
|---|---|---|
| child submit route | attempt, attachment, `answer_analysis` job | answer worker, child projection |
| `answer_analysis_agent` job | `agent_runs`, attempt analysis, validation | EvidenceGate, evaluation job, reports |
| EvidenceGate | `evidence_validations`, trust label | evaluation job, planner, reports, summary |
| `evaluation_agent` job | evaluation envelope | runtime mastery reducer, planner job, reports |
| runtime mastery reducer | `mastery_decisions`, `learner_node_status` | planner, reports, future target pool |
| QuestionBank/Graph services | candidate packet, graph summaries | planner job |
| `planner_agent` job | accepted one-action plan | runtime materializer, optional teaching job, reports |
| `teaching_agent` job | child-safe teaching package | runtime materializer, child projection, reports |
| runtime summary reducer | `daily_summaries` | child UI, Codex/report |

Contract tests:
- DAG creation: submit creates exactly one `answer_analysis`; accepted answer creates exactly one `evaluation_update`; accepted evaluation creates exactly one `planner_decision`; teaching action creates exactly one `teaching_generation`; terminal evaluation failure creates blocked/summary runtime output and no planner job.
- Idempotency: duplicate submit, duplicate worker claim, retry after lease expiry, rerun after success, and rerun after terminal stage status reuse existing valid stage outputs and produce no duplicate attempts/current steps/mastery decisions/summaries/model calls.
- Trust labels: mock/recorded/live/not_configured/deterministic are separated; mock is never `live_model`.
- Malformed output: each agent malformed JSON/schema error retries then blocks without mastery.
- Evidence gate: pending/stale/missing-lineage/mock_only cannot update mastery.
- Planner: receives 5-8 packet where possible, never full bank, returns one action, rejects old 10-task schema.
- Graph rollback: wrong/blocking current node prefers prerequisite probe before blind same-type drilling.
- UX P0: analyzing terminal path, blocked retry, clarify cannot-provide, terminal summary action.
- Browser: real runtime states plus forbidden child leakage scan.
- Reports: phase lineage includes job ids, agent_run ids, validation ids, mastery ids, decision ids, candidate packet hash, trust labels.
- Harness: v5 10-lesson simulation uses recorded/patchable model envelopes and never labels them live.

ENGINEERING_CONTRACT_COVERAGE:
- interfaces_complete: yes
- job_dag_complete: yes
- payload_fields_complete: yes
- status_transitions_complete: yes
- retry_backoff_complete: yes
- worker_lifecycle_complete: yes
- model_envelopes_complete: yes
- true_vs_deterministic_labeling_complete: yes
- output_schemas_named: yes
- producer_consumer_complete: yes
- migration_compatibility_complete: yes
- failure_rollback_complete: yes
- contract_tests_named: yes
- blocking_gaps: none for design review; code waits for review

ENGINEERING_CONTRACT_QUALITY_GATE:
- verdict: CONTRACT_READY_FOR_DESIGN_REVIEW
- no_ambiguous_shared_fields: pass
- producers_consumers_complete: pass
- errors_permissions_complete: pass
- old_data_and_compatibility_complete: pass
- failure_retry_recovery_complete: pass
- contract_tests_or_validation_named: pass
- quality_evidence: tied to PRD v5, Product Structure v5, UX v5, runtime contract, MSG-20260711-002, and current code symbols
- blocking_quality_gaps: none

Stop condition:
This contract is ready for `implementation_blueprint_v5.md` and 镜花 DESIGN_REVIEW. It does not claim current code satisfies it.
