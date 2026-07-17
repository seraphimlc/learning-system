### DATA_REVIEW / NEEDS_FIX - 霜弦（agentKey: `shuangxian`）- 2026-07-10 19:20 CST

Verdict: `DATA_REVIEW_NEEDS_FIX`

independence_required: yes

context_mode: fresh

context_origin: spawned only for skeleton data review; did not implement

diff_pin: no git; reviewed named SKELETON_PASS files

Scope:

- DATA_REVIEW of v3 `SKELETON_PASS` implementation only.
- Checked actual skeleton schema, lineage fields, fail-closed evidence gates, candidate packet shell, report labels, and focused tests against `docs/architecture/technical_plan_v3.md`.
- Forbidden scope honored: no implementation code edits, no final `DATA_CONTRACT_SPEC` approval, no semantic model quality approval, no live model run.

Project boundary overlay:

- `AGENTS.md`
- PRD v3: `docs/product/ai_native_math_learning_prd_v3.md`
- technical plan v3: `docs/architecture/technical_plan_v3.md`
- mandatory addendum: `docs/collaboration/playbooks/data-learning-system-addendum.md`

Data ops risk:

- High. These rows are planned to become the data spine for graph-bound attempts, evidence validation, mastery decisions, next-step decisions, late reconciliation, and parent/Codex reports.
- Project rule applied: pending, stale, mock-only, missing-lineage, invalidated, low-confidence, or unvalidated evidence must not drive mastery, planning, or report `confirmed` claims.

Fact sources:

- `docs/collaboration.md`
- `docs/collaboration/roles/shuangxian.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/playbooks/data-learning-system-addendum.md`
- `AGENTS.md`
- `docs/project-index.md`
- `docs/domain-index/math-learning.md`
- `docs/product/ai_native_math_learning_prd_v3.md`
- `docs/architecture/technical_plan_v3.md`
- `docs/architecture/code_skeleton_pass_v3.md`
- `learning_system/db.py`
- `learning_system/evidence_gate.py`
- `learning_system/question_bank.py`
- `learning_system/graph_runtime.py`
- `learning_system/daily_runtime.py`
- `learning_system/job_queue.py`
- `learning_system/server.py`
- `learning_system/reports.py`
- `tests/test_learning_system.py`

Lineage checked:

- Tables: `daily_flows`, `flow_steps`, `review_targets`, `evidence_validations`, `next_step_decisions`, `late_evidence_reconciliations`, `daily_summaries`.
- Additive fields: `attempts`, `background_jobs`, `mastery_decisions`, `learner_node_status`.
- Predicates and labels: `EvidenceUsePredicate`, `EvidenceGate.validate_attempt`, `QuestionBankService.candidate_packet_for_node`, v3 report label constants.

Samples/artifacts:

- Identity validation: role YAML header matched `docs/collaboration/agent-registry.json` for `agentKey=shuangxian`.
- Safe in-memory DB inspection: `db.init_schema(:memory:)` confirmed v3 table/column/index creation.
- Safe in-memory gate reproduction: seeded temp DB only; no live DB/model/external side effects.
- Focused skeleton tests run:

```text
python3 -m unittest \
  tests.test_learning_system.LearningSystemTest.test_v3_skeleton_schema_additive_and_indexes_exist \
  tests.test_learning_system.LearningSystemTest.test_v3_skeleton_modules_expose_fail_closed_contracts \
  tests.test_learning_system.LearningSystemTest.test_v3_child_route_shell_returns_child_safe_payload_when_enabled \
  tests.test_learning_system.LearningSystemTest.test_v3_feature_flag_disabled_keeps_legacy_child_bootstrap -v

Ran 4 tests in 5.848s
OK
```

Findings:

1. P1 - Evidence gate can mark missing-lineage evidence as `usable` / `confirmed`.

   `technical_plan_v3` requires v3 attempts to carry `graph_version`, `node_id`, `question_id`, `question_bank_version`, `flow_step_id`, attempt version, idempotency, and active question/review lineage before they can drive gate/planner/report claims (`docs/architecture/technical_plan_v3.md:503`, `docs/architecture/technical_plan_v3.md:513`, `docs/architecture/technical_plan_v3.md:528`). It also says `confirmed` is allowed only when all required source rows are current, non-mock, lineage-complete, and pass the relevant predicate (`docs/architecture/technical_plan_v3.md:793`).

   Actual code checks only status fields, provider mode, non-empty `flow_step_id`, graph version, bank version, and `gate_status` (`learning_system/evidence_gate.py:57`). It does not verify that `flow_step_id` points to a real `flow_steps` row, that `attempt.node_id` is present and graph-valid, that `attempt.question_id` is present/current, that the attempt node/question matches the flow step, or that `review_record_id` points to an active-use review record. `EvidenceGate.validate_attempt` then writes an `evidence_validations` row from that predicate (`learning_system/evidence_gate.py:116`).

   Reproduction in a temp DB: a graded/valid attempt with no real `flow_steps` row, `node_id=''`, and `review_record_id=''` returned:

```text
direct_missing_node {'usable': True, 'projection_status': 'usable', 'failed_fields': [], 'report_label': 'confirmed'}
validate_missing_node {'gate_status': 'passed', 'predicate': {'usable': True, 'projection_status': 'usable', 'failed_fields': [], 'report_label': 'confirmed'}}
```

   Impact: this violates the project boundary and technical plan. If later evaluation/planner/report code consumes this predicate as designed, missing-lineage evidence can become mastery/planning/report-confirmed evidence.

   Required fix before business-logic fill: make the evidence predicate fail closed unless the attempt, flow step, graph node, question item, active review record, graph version, question bank version, attempt/analysis versions, and provider mode all validate together. Add regression tests for empty/mismatched `node_id`, missing step row, mismatched step/attempt node, missing `question_id`, missing `review_record_id`, inactive/stale review record, and legacy attempts.

2. P2 - Report label readiness is not aligned with v3 label contract.

   `technical_plan_v3` requires the v3 labels exactly: `confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`, `missing_lineage`, with explicit precedence (`docs/architecture/technical_plan_v3.md:774`). The DB defines `V3_REPORT_CLAIM_LABELS` with those labels, but the general report module still exports the old `REPORT_CLAIM_LABELS` and `report_claim_label()` can return `missing`, not `missing_lineage` (`learning_system/db.py:30`, `learning_system/db.py:31`, `learning_system/reports.py:23`, `learning_system/reports.py:26`).

   In addition, `EvidenceGate.validate_attempt()` can relabel pending evidence as `missing_lineage`: direct predicate on a pending/missing-analysis attempt returned `report_label='pending'`, but after validation the written predicate contained `failed_fields=['grading_status','analysis_status','gate_status']` and `report_label='missing_lineage'`, because `_report_label_for_failed_fields()` treats any non-passed `gate_status` as missing lineage before checking pending analysis (`learning_system/evidence_gate.py:171`, `learning_system/evidence_gate.py:173`, `learning_system/evidence_gate.py:177`).

   Impact: this does not create a false `confirmed` claim by itself, but v3 report label semantics are not ready for parent/Codex progress claims or QA label-precedence tests.

   Required fix: separate "gate row pending/rejected" from true missing lineage, route v3 reports/summaries through `V3_REPORT_CLAIM_LABELS`, and add tests covering all seven labels plus precedence.

3. P2 - `background_jobs` skeleton is useful but not yet faithful to the planned additive queue contract.

   The schema has important v3 queue fields: `idempotency_key`, `flow_id`, `flow_revision`, `flow_step_id`, `step_revision`, `attempt_version`, `analysis_version`, `graph_version`, `question_bank_version`, `question_id`, `review_record_id`, `candidate_packet_id`, `depends_on_json`, `provider_mode`, `payload_schema_version`, lease fields, `retry_after`, `result_refs_json`, and `blocked_reason` (`learning_system/db.py:850`). The active idempotency index exists (`learning_system/db.py:786`), and `JobQueue.enqueue()` requires core lineage payload fields (`learning_system/job_queue.py:51`).

   However, `technical_plan_v3` names additive queue fields `available_at`, `dead_letter_reason`, `depends_on_job_id`, and `route_meta_json`, and first-slice job types include `teaching_generation` plus legacy `answer_review` alias (`docs/architecture/technical_plan_v3.md:260`, `docs/architecture/technical_plan_v3.md:264`). Actual schema substitutes or omits those fields, and `V3_JOB_TYPES` is only `answer_analysis`, `evidence_validation`, `evaluation_update`, `planner_decision` (`learning_system/job_queue.py:11`).

   Impact: not a direct data-safety false pass, but provider route audit, dependency lineage, dead-letter reporting, and teaching-shell queue readiness are not contract-complete.

   Required fix or explicit plan update: either add the named fields/job aliases, or update `technical_plan_v3` / DATA_CONTRACT_SPEC with an explicit equivalence map that preserves the same lineage and recovery meaning.

Positive checks:

- Additive schema exists for all requested v3 tables. In-memory PRAGMA inspection confirmed lineage/provenance columns on `daily_flows`, `flow_steps`, `review_targets`, `evidence_validations`, `next_step_decisions`, `late_evidence_reconciliations`, `daily_summaries`, `attempts`, `background_jobs`, `mastery_decisions`, and `learner_node_status`.
- Important uniqueness gates exist: one active flow per child/date, one current step per flow, one active attempt per step, submit idempotency, active job idempotency, validation uniqueness, next-decision uniqueness, and daily-summary uniqueness (`learning_system/db.py:766` through `learning_system/db.py:800`).
- `QuestionBankService.candidate_packet_for_node()` is metadata-only and excludes missing-lineage/stale/inactive/cooldown/duplicate/mastered rows before planner context (`learning_system/question_bank.py:187`, `learning_system/question_bank.py:223`, `learning_system/question_bank.py:283`, `learning_system/question_bank.py:295`). Current v2 bank rows are excluded as missing lineage until a deterministic backfill exists.
- `GraphRuntimeService` provides a deterministic graph version hash and graph binding validation shell (`learning_system/graph_runtime.py`).
- `DailyLearningRuntime` creates/resumes a v3 daily flow with graph and bank versions, then blocks safely at the target-selection seam instead of inventing a fake question (`learning_system/daily_runtime.py:96`, `learning_system/daily_runtime.py:139`).
- v3 child route shell tests passed and the feature flag preserves legacy v2 bootstrap when disabled.

Not covered:

- No final `DATA_CONTRACT_SPEC` approval.
- No semantic model quality, live provider, OCR quality, teaching quality, or answer-analysis rubric approval.
- No full adaptive 10-20 step day, late evidence chain, mastery reducer, planner decision quality, or final report QA.
- No browser/taste review.
- No production DB mutation or external side effect.

Residual risk:

- The skeleton tests currently prove table/index presence and some fail-closed route behavior, but they do not yet test the strongest lineage false-pass cases for evidence gate, report labels, job route metadata, or planner/mastery consumers.

Required next action:

- Route to 听云 for code fixes before business-logic fill.
- P1 evidence gate lineage false-positive must be fixed before this skeleton can pass data review.
- P2 report label and queue-field gaps can be fixed in skeleton or explicitly resolved in the next DATA_CONTRACT_SPEC/technical-plan update before report/queue claims are accepted.
