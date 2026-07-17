### DESIGN_REVIEW / NEEDS_FIX - 镜花（agentKey: `jinghua`）- 2026-07-10 18:35 CST

Verdict:
`NEEDS_FIX`. The direction is coherent, but `docs/architecture/technical_plan_v3.md` is not yet hard enough to serve as the v3 first-slice technical plan, engineering contract, and implementation blueprint for high-risk runtime/schema/queue work.

independence_required:
yes

context_mode:
fresh

context_origin:
spawned only for this review; did not author the plan

diff_pin:
`docs/architecture/technical_plan_v3.md`

Scope:
Reviewed engineering executability and system stability only: runtime state machine, current-step API, SQLite additive schema, v2/v3 compatibility, background queue, idempotency, late evidence, model-router isolation, child-safe boundary, and test prerequisites.

Project boundary overlay:
Applied `docs/product/ai_native_math_learning_prd_v3.md` `PROJECT_BOUNDARY_OVERLAY`, `AGENTS.md`, and `docs/domain-index/math-learning.md`. Key applied rules: single child, no parent dashboard, one visible current step, runtime/service/gate own execution, agents semantic only, graph-bound evidence, model calls only through router, no fixed pre-generated worksheet, and no pending/invalid/stale/mock/missing-lineage evidence driving mastery or planning.

Source artifacts:
`docs/architecture/technical_plan_v3.md`, `docs/product/ai_native_math_learning_prd_v3.md`, `docs/architecture/ai_native_learning_system_architecture_v3.md`, `docs/architecture/daily_learning_runtime_contract_v1.md`, `docs/project-index.md`, `docs/domain-index/math-learning.md`, `learning_system/db.py`, `learning_system/server.py`, `learning_system/model_router.py`, `learning_system/auto_review.py`, `learning_system/planner.py`, `learning_system/question_bank.py`, `tests/test_learning_system.py`, and `docs/project-rules/system-architecture-learning-addendum.md`.

Commands:
Read-only shell inspection only. Used `sed`, `nl -ba`, `rg`, `wc -l`, `ls`, and `date`. No server, browser, DB mutation, tests, or model calls were run.

Evidence:
- `technical_plan_v3.md` correctly names high-risk scope, missing UX/DATA gates, no parent dashboard, model-router-only calls, current-step API, and skeleton-before-business-logic order.
- Current code facts match the plan's broad diagnosis: child bootstrap still projects a fixed `today_plan.tasks` list from `learning_system/server.py:495` and `learning_system/server.py:801`; child submissions resolve `task_position` in `learning_system/server.py:1186`; current `attempts` and `background_jobs` are v2/session oriented in `learning_system/db.py:343` and `learning_system/db.py:520`; existing background job types only include `answer_review` in `learning_system/db.py:577`.

Implementation fidelity:
Not applicable as code review; no implementation was changed. This is a design/contract sufficiency review.

Findings:

1. [P1] Schema contract does not carry graph lineage through all v3 runtime rows
   File: `docs/architecture/technical_plan_v3.md`
   Lines: 116-117, 468-491, 681
   Trigger: Implementing the additive SQLite tables exactly from the field contract.
   Impact: The plan says every question, step, attempt, analysis, evaluation, plan, summary, and report claim must bind to `graph_node_id` and `graph_version`, but the field contract only makes `daily_flows.graph_version` and `attempts.graph_version` explicit. It does not fully specify required lineage fields for `flow_steps`, `review_targets`, `evidence_validations`, `next_step_decisions`, `late_evidence_reconciliations`, or `daily_summaries`. This conflicts with PRD lineage requirements in `docs/product/ai_native_math_learning_prd_v3.md:406` and `docs/product/ai_native_math_learning_prd_v3.md:410`, and leaves implementers guessing where gates/reports should read current-vs-stale graph evidence.
   Required fix: Expand the engineering contract field table before schema work. For every new table, specify required `graph_node_id`/`node_id`, `graph_version`, source attempt/step/decision ids, agent run ids where relevant, version fields, old-data/null behavior, and consumers. State how missing lineage blocks planning/report-confirmed claims.
   Validation: Add schema tests using `PRAGMA table_info`/indexes and runtime tests proving rows without required graph lineage cannot drive evidence gate, planner, summary, or Codex report confirmed labels.

2. [P1] Core idempotency invariants are stated but not enforceable from the SQLite/index/transaction contract
   File: `docs/architecture/technical_plan_v3.md`
   Lines: 262-273, 508-531, 681, 684
   Trigger: Duplicate bootstrap/start/submit/recovery calls, concurrent background workers, or repeated polling during model delay.
   Impact: The plan requires one active daily flow, one current step, one active attempt per step, one answer-analysis job per attempt version, one validation per analysis version, and one next-step decision per flow revision. The storage contract lists only non-unique indexes and does not define partial unique indexes, transaction boundaries, or version columns such as `attempt_version`, `analysis_version`, or `flow_revision`. Existing v2 code shows why this must be explicit: `enqueue_background_job()` deduplicates by a SELECT without a unique constraint in `learning_system/db.py:610`, and `background_jobs` has no idempotency key in `learning_system/db.py:520`.
   Required fix: Add an enforceable invariant section to the engineering contract: exact unique/partial indexes, idempotency key uniqueness, `step_handle` uniqueness scope, active-flow uniqueness for the implicit child/date, active-attempt-per-step rule, attempt/analysis/flow revision fields, and the transaction boundary that persists response + attachment rows + job enqueue atomically.
   Validation: Add tests for duplicate review start, repeated submit with same and different idempotency keys, concurrent submit/recovery claims, and restart recovery. Tests must assert DB row counts and not only API status.

3. [P1] Queue/worker lease and recovery semantics are too underspecified for the new multi-stage pipeline
   File: `docs/architecture/technical_plan_v3.md`
   Lines: 251-260, 510-522, 691, 760-769
   Trigger: Server restart, stale `running` jobs, model timeout, malformed model JSON, or two workers trying to recover the same flow.
   Impact: The plan introduces `answer_analysis`, `evaluation_update`, `planner_decision`, and `teaching_generation`, but does not define the `JobQueue` state machine, atomic lease/claim query, `locked_at` timeout threshold, retry/backoff fields, dependency ordering, dead-letter/operator-attention states, or how late evidence waits for a safe transition before eval/planning. Without this, the first slice can still lose jobs, double-grade/evaluate, or apply a late result while the child is answering a newer step. The current worker is explicitly session-oriented and marks jobs running in bulk before threaded review (`learning_system/server.py:1770`, `learning_system/server.py:1791`, `learning_system/server.py:1804`), so the v3 wrapper needs a precise replacement contract, not just a file name.
   Required fix: Specify `JobQueue` method contracts and job state transitions: enqueue, claim/lease, heartbeat or stale unlock, finish, retry, wait, block, and recovery scan. Include payload fields for flow/step/attempt/analysis versions and dependency links, plus the late-evidence reconciliation safe-transition check.
   Validation: Add queue tests for stale running unlock, duplicate worker claim prevention, model-disabled blocking, retry-after timing, late evidence arriving after an independent step, and no inert queued job after bootstrap/startup recovery.

4. [P2] Evidence validation vocabulary is inconsistent with the PRD data contract
   File: `docs/architecture/technical_plan_v3.md`
   Lines: 247-249, 489, 574-576
   Trigger: Implementing `EvidenceGate` and writing report/planner tests.
   Impact: PRD v3 defines the canonical evidence-validation vocabulary as `usable`, `pending`, `rejected`, `blocked` in `docs/product/ai_native_math_learning_prd_v3.md:385` and `docs/product/ai_native_math_learning_prd_v3.md:391`, while the technical plan stores `gate_status` as `passed`, `pending`, `rejected`, `blocked`. The plan also says `usable` is a predicate, not a stored status, which may be right, but the mapping is not stated. This creates a preventable mismatch between runtime gate rows, reports, and 观止/霜弦 test oracles.
   Required fix: Choose one canonical storage/report vocabulary or add an explicit mapping such as `gate_status=passed` maps to predicate/report `usable`, with consumers named.
   Validation: Evidence-gate and summary/report tests must assert the same vocabulary the child/Codex/API surfaces consume.

Not covered:
- No QA PASS, no data/content final judgment, no UI aesthetic review.
- No server/browser/model execution.
- No production code review beyond current-code fact checking needed to validate the plan.

Residual risk:
The plan honestly scopes missing UX_FLOW_SPEC v3 and DATA_CONTRACT_SPEC v3 as later gates, but because the first slice starts with schema creation, the data naming/lineage portions above should be fixed before `db.init_schema` skeleton work, not deferred until after additive tables exist.

Required next action:
听云 should revise `technical_plan_v3.md` before implementation/skeleton work. Re-review should focus on the corrected schema/lineage contract, enforceable idempotency/indexes, queue lease/recovery state machine, late-evidence safe-transition semantics, and evidence vocabulary mapping. After that, 观止 can derive `TEST_CASE_SPEC` from the actual skeleton targets.
