# SKELETON_PASS - 听云（agentKey: `tingyun`）- 2026-07-08 11:48 CST

Objective:
Create the actual code skeleton for the v2 child-only AI-native math learning architecture, exposing page/API/service/worker/model/evidence/question/report/test seams before non-trivial business logic fill.

Identity:
- Role: 听云
- agentKey: `tingyun`
- Identity binding: role YAML header validated against `docs/collaboration/agent-registry.json`

Project boundary overlay:
- Source: `docs/product/ai_native_math_learning_prd_v2.md` `PROJECT_BOUNDARY_OVERLAY` plus `AGENTS.md`.
- Applied constraints: one child Web端 only; parent via Codex; graph-bound teaching/evidence/planning/evolution; 10-task round; child-safe DTOs separated from operator DTOs; no external model calls; no destructive local DB/uploads mutation; no parent dashboard; no business logic fill beyond skeleton wrappers.

Files read:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/roles/tingyun.md`
- `docs/collaboration/inbox.md`
- `docs/project-index.md`
- `docs/domain-index/math-learning.md`
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/product/child_ux_flow_spec_v2.md`
- `docs/architecture/data_contract_spec_v2.md`
- `docs/architecture/technical_plan_v2.md`
- `docs/architecture/project_skeleton_v2.md`
- `docs/qa/test_case_spec_v2.md`
- `docs/collaboration/reviews/2026-07-08-jinghua-design-review-v2-addendum.md`
- `docs/collaboration/reviews/2026-07-08-shuangxian-data-review-technical-plan-v2.md`
- `docs/collaboration/reviews/2026-07-08-qingqiu-ux-review-technical-plan-v2.md`
- `docs/00_PROJECT_BLUEPRINT.md`
- `docs/system/local_learning_system.md`
- `docs/system/qa/question_bank_grade_level_latest.md`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.md`
- Current code under `learning_system/`, `app/local_learning_system/`, `tests/`, and selected validation scripts.

Files changed:
- `learning_system/db.py`
- `learning_system/planner.py`
- `learning_system/server.py`
- `learning_system/model_router.py`
- `learning_system/auto_review.py`
- `learning_system/orchestrator.py`
- `learning_system/reports.py`
- `learning_system/evolution.py`
- `learning_system/question_bank.py`
- `app/local_learning_system/app.js`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`
- `docs/architecture/code_skeleton_pass_v2.md`

Validation artifact touched:
- `docs/system/qa/question_bank_grade_level_latest.md` was refreshed by `python3 scripts/audit_question_bank_grade_level.py --db data/local_learning_system.sqlite`. This command reported the existing report path and did not mutate `data/local_learning_system.sqlite` or `data/uploads`; it may update the generated QA report timestamp/content.

Engineering contract:
- Source: `docs/architecture/technical_plan_v2.md` `ENGINEERING_CONTRACT`.
- Preserved existing v1 behavior while adding named v2 shells around child DTOs, operator DTOs, shared evidence predicates, async worker, model route status, answer-analysis adapter, close state machine, planner DTO, evolution audit package, question-spec migration seam, report labels, and tests.

Implementation blueprint:
- Source: `docs/architecture/technical_plan_v2.md` `IMPLEMENTATION_BLUEPRINT` and `docs/architecture/project_skeleton_v2.md`.
- Complexity: `high_risk_change`.
- Stop condition honored: stopped after skeleton/contract normalization and validation; did not continue into business logic fill.

Page prototype / route shells:
| Surface/route | File/path | Shell state | UI states represented | Notes |
|---|---|---|---|---|
| `/` child learning page | `app/local_learning_system/app.js` | Explicit `CHILD_UI_STATES` enum and `window.ChildLearningShell` test hook | `loading`, `empty`, `active_task`, `saving`, `save_error`, `upload_error`, `all_submitted_reviewing`, `review_ready`, `blocked`, `load_error` | Adds deterministic `fixtureForChildState`, including 10 review points for review-ready fixture. |
| Child active task | `app/local_learning_system/app.js` | DTO-normalized renderer | active, saving, save_error, upload_error | Uses `display_topic`, `support.essence_or_hint`, and `display_key`; no child dependency on `node_name`/`plan_key`. |
| Child review handoff | `app/local_learning_system/app.js` | Existing review renderer with explicit state assignments | reviewing, review_ready, blocked | Preserves all-question review list and next action behavior. |

Skeleton created:
| File/path | Module/type/interface/class/function/route/handler | Status | Notes |
|---|---|---|---|
| `learning_system/db.py` | `EvidenceUsePolicy`, `SESSION_CLOSURE_STATUSES`, `REPORT_CLAIM_LABELS`, `is_child_schedulable_question`, `is_evolution_source_valid` | created | Shared v2 predicates delegate to existing DB/question-review gates. |
| `learning_system/planner.py` | `PlanTaskDTO` | created | Child-safe task projection shell for `position`, `kind_label`, `display_topic`, `question`, `support`. |
| `learning_system/server.py` | `ChildAPIProjection`, `OperatorAPIProjection`, `BackgroundReviewWorker`, `CHILD_UI_STATES`, `CHILD_SCHEMA_VERSION` | created | Routes now use named projection shells; child schema is `2.0.0-child-skeleton`. |
| `learning_system/model_router.py` | `ModelRouteStatus`, `route_status`, `configured_route_statuses` | created | Secret-free model route status seam; no external calls. |
| `learning_system/auto_review.py` | `AnswerAnalysisResult` | created | Structured adapter for valid/pending answer-analysis shell. |
| `learning_system/orchestrator.py` | `SessionClosureStateMachine` | created | Explicit close-state transition shell; actual closure logic unchanged. |
| `learning_system/evolution.py` | `EvolutionAuditPackage`, `is_evolution_source_valid` | created | Self-evolution source seam points to shared DB predicate. |
| `learning_system/question_bank.py` | `QuestionSpecLoader` | created | Stage-1 migration seam only; Python gates remain authoritative. |
| `learning_system/reports.py` | `report_claim_label`, `REPORT_CLAIM_LABELS` | created | Report evidence-label seam. |
| `tests/test_learning_system.py` | `test_v2_code_skeleton_contract_symbols_are_exposed_fail_safe` | created | Contract shell test for v2 symbols and fail-safe defaults. |
| `tests/browser_smoke_learning_system.mjs` | dynamic port, model-disabled env, child shell checks | updated | Prevents external model calls and verifies child state/fixture seam. |

Program framework:
| File/path | Class/function/method/API/task/test shell | Signature/contract | Stub behavior |
|---|---|---|---|
| `learning_system/db.py` | `EvidenceUsePolicy.is_usable_attempt(conn, attempt)` | active + graded + valid answer analysis + current reviewer-approved question | Delegates to existing predicate; false on invalid/malformed/stale. |
| `learning_system/db.py` | `is_child_schedulable_question(conn, question)` | graph-bound/current-version/reviewer-approved active question | Requires durable `question_review_records` for generated/evolved items. |
| `learning_system/server.py` | `ChildAPIProjection.bootstrap/completion/submission` | child-safe DTOs only | Delegates to existing route projection helpers. |
| `learning_system/server.py` | `OperatorAPIProjection.bootstrap` | id-rich operator/Codex DTO | Delegates to existing `_bootstrap`. |
| `learning_system/server.py` | `BackgroundReviewWorker.idempotency_key` | `answer_review:{session_id}:{attempt_id}` | Naming shell; existing in-process worker remains. |
| `learning_system/model_router.py` | `route_status(route)` | provider/model/json modes/endpoints without secrets | Read-only status; no network call. |
| `learning_system/auto_review.py` | `AnswerAnalysisResult.from_review(review)` | `valid` or `pending` adapter | Validates with DB schema, otherwise pending. |
| `learning_system/orchestrator.py` | `SessionClosureStateMachine.status_for_summary(summary)` | incomplete/pending/missing-analysis/ready transition shell | Conservative mapping to `blocked`, `waiting_ai`, or `planned`. |
| `learning_system/question_bank.py` | `QuestionSpecLoader.status()` | future data-spec loader contract | Disabled and Python-gate-authoritative until parity is approved. |
| `app/local_learning_system/app.js` | `window.ChildLearningShell` | frontend state enum, forbidden keys, fixtures | Deterministic fixtures only; no backend logic. |

Skeleton contracts exposed:
- Page seam: explicit child UI state enum and deterministic fixture renderer.
- API seam: child/operator projection classes and schema versions.
- Service seam: orchestrator close state shell, planner DTO shell, report-label helper.
- Worker seam: `BackgroundReviewWorker` naming and idempotency shell.
- Model seam: secret-free route status DTO and configured route status helper.
- Evidence seam: `EvidenceUsePolicy` plus shared schedulable question/evolution source predicates.
- Question seam: `QuestionSpecLoader` disabled migration seam; Python quality gates remain authoritative.
- Report seam: `report_claim_label` and DB-derived summary `evidence_label`.
- Test seam: unit contract test and browser smoke checks for schema/state/fixture contract.

Compile/static check:
- `python3 -m compileall learning_system` -> passed.
- `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_v2_code_skeleton_contract_symbols_are_exposed_fail_safe tests.test_learning_system.LearningSystemTest.test_child_bootstrap_is_child_safe_and_excludes_internal_operator_data -v` -> 2 tests passed.
- `python3 -m unittest tests/test_learning_system.py -v` -> 129 tests passed at initial skeleton time; superseded by later QB11 hardening evidence below.

Runtime/browser check:
- `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs` -> passed.
- The smoke starts a temporary local server with a temporary SQLite DB and temporary uploads directory, chooses a free port dynamically, disables inherited model API env vars, and cleans up temp files at the end.

Read-only/domain checks:
- `jq empty data/knowledge_graphs/math/math_knowledge_graph_v2.json` -> passed.
- `jq '.nodes | length' data/knowledge_graphs/math/math_knowledge_graph_v2.json` -> `56`.
- `python3 scripts/audit_question_bank_grade_level.py --db data/local_learning_system.sqlite` -> completed and reported `docs/system/qa/question_bank_grade_level_latest.md`.

Stub safety:
- Child DTO keeps child API handle/position based and no longer relies on `node_name`/`plan_key`.
- Model route status helpers do not include API keys and do not perform network calls.
- Question-spec loader is disabled until parity tests/gates exist.
- Browser smoke now clears model API env vars, preventing accidental external model calls.
- Evidence source shells are conservative and delegate to existing active/current/reviewer-approved/analysis-valid gates.

Business logic status:
`minimal_safe_stub_only`.

Deferred implementation:
- No new grading, planning, evolution, question generation, OCR, or mastery threshold logic was filled.
- No parent dashboard was created.
- No final question-spec data format was created.
- No production-like SQLite reset or upload mutation was performed.
- No external model call was made.

Deviations from blueprint:
- Child schema version was advanced to `2.0.0-child-skeleton` to make the skeleton contract visible. This is a contract marker, not a release/DONE claim.
- `QuestionSpecLoader` was added as a disabled code seam only; `data/question_specs/` files were not created because the final data-spec format remains undecided.
- `scripts/audit_question_bank_grade_level.py --db data/local_learning_system.sqlite` refreshed the generated QA report artifact path. This was validation evidence, not skeleton code.
- No project index update was made because the task requested code skeleton evidence and this directory is not a git repository for diff-based index maintenance.

Unverified scope:
- Live GPT-compatible answer-analysis quality.
- Live Doubao vision/OCR quality.
- Human visual/taste review of the rendered child page.
- Human教研 review of all question naturalness/cognitive load.
- Long-run mastery thresholds.
- Final question-spec file format and parity migration.
- Full independent architecture/data/UX/QA gates after this skeleton.

Residual risk:
- Downstream implementation could still bypass `EvidenceUsePolicy` unless review enforces it across evaluation/planner/evolution/report consumers.
- The child UI has fixture/state seams, but final mobile screenshots, focus traversal, contrast, and copy tone still require rendered review.
- `report_claim_label` is currently a shell label helper; later report implementation must prove claim-by-claim evidence labels.
- `QuestionSpecLoader` is intentionally inactive; activating it without parity tests would weaken the current Python/reviewer gate.

Ready for review/test design:
Yes, for skeleton review only.

Next gate:
`DESIGN_REVIEW` / `CODE_REVIEW` by 镜花, `UX_REVIEW` by 清秋, `DATA_REVIEW` by 霜弦, then 观止 `TEST_CASE_SPEC` refinement against the actual symbols above before any non-trivial business logic implementation.

## P1 Evidence-Gate Wiring Fix Note - 听云（agentKey: `tingyun`）- 2026-07-08

Scope:
- Addressed only 镜花 P1 evidence-gate findings and the additional 霜弦 P1 data evidence-gate findings.
- No parent dashboard, no DB/upload reset, no external model calls, and no unrelated business-logic fill.

Fix summary:
- `EvidenceUsePolicy` now represents `active + graded + valid_answer_analysis + current_child_schedulable_question`.
- `answer_analysis` validity now requires coverage of `final_answer`, `model_or_relation`, `steps`, `symbols_units`, and `check_or_explanation`, plus non-empty teaching/next prompt and either a meaningful `process_gap` or explicit `no_gap_observed`.
- Child active-use gates now require durable reviewer-record eligibility through `is_child_schedulable_question`; unreviewed diagnostic/unknown-source items cannot enter child sessions or active attempts.
- Session completion summaries distinguish structurally analyzed attempts from usable attempts and block closure on `unusable_evidence_attempt_ids` before answer/evaluation/evolution/planning packages are built.
- Flow-node answer/evaluation packages consume only usable attempt ids.
- Self-evolution candidate filtering now uses `db.is_evolution_source_valid(conn, attempt)` as the final authority.

Regression tests added/updated:
- `test_thin_answer_analysis_is_not_usable_evidence`
- `test_session_close_blocks_when_review_record_no_longer_schedulable`
- `test_evolution_rejects_attempt_when_review_record_no_longer_schedulable`
- `test_unreviewed_diagnostic_question_cannot_enter_child_active_use`
- Existing normalization/child submission/lineage tests updated to match the stricter evidence contract.

Validation:
- `python3 -m compileall learning_system` -> passed.
- Focused evidence-gate unittest command covering the new tests -> 5 tests passed.
- Focused regression rerun for previously affected tests -> 6 tests passed.
- `python3 -m unittest tests/test_learning_system.py -v` -> 133 tests passed at P1 evidence-gate fix time; superseded by later QB11 hardening evidence below.

Next gate:
Re-review by 镜花 and 霜弦 for the corrected evidence-gate wiring. No review/QA PASS is claimed by 听云.

## QB11 Question-Bank And Evolved-Source Hardening Addendum - 若命/听云 - 2026-07-08

Scope:
- Replaced the old broad picture-level challenge assumption with the QB11 contract: 20 active slots per node, node-local mainline evidence floor, controlled picture-level stretch caps, canonical-core diversity, and a 10-task round with at least 7 node-local mainline tasks plus normally 1-2 semantically anchored picture-level extension tasks.
- Added source-attempt validity as an active-use gate for evolved questions: missing, nonexistent, inactive, ungraded, malformed, invalidated, stale, or cyclic source-attempt lineage blocks child scheduling and appears in lineage audit.
- Kept real `data/local_learning_system.sqlite` untouched; current live local DB remains a separate v9/no-session state until explicitly initialized or migrated.

Implementation areas:
- `learning_system/question_bank.py`: QB11 bank version, canonical core signatures, evidence roles, node-local floors, controlled picture-level allowlist/caps, and semantic mismatch rejection.
- `learning_system/planner.py`: round-level node-local mainline floor and picture-level cap.
- `learning_system/db.py`: evolved-source attempt gate, child-schedulable recursion guard, lineage audit for invalid evolved source attempts, and null-safe active status checks.
- `scripts/audit_question_bank_grade_level.py`: canonical-core audit, node-local/picture-level checks, active-round checks, live-lineage false-pass guards.
- `tests/test_learning_system.py`: regression coverage for source-attempt gate variants, cycle/self-reference, duplicate-core false passes, and live-lineage issue-count verdicts.

Validation recorded:
- `python3 -m py_compile learning_system/question_bank.py learning_system/db.py learning_system/planner.py scripts/audit_question_bank_grade_level.py tests/test_learning_system.py` -> passed.
- `python3 -m unittest tests/test_learning_system.py -v` -> 146 tests passed in 232.698s.
- `python3 scripts/audit_question_bank_grade_level.py --report docs/system/qa/question_bank_grade_level_latest.md --db ''` -> `PASS_WITH_SCOPE`, `QB11`, 1120 items, 56 nodes, active round 2/10 controlled picture-level and 8/10 node-local mainline.
- Browser smoke before this doc refresh: `tests/browser_smoke_learning_system.mjs` -> PASS for child-only flow, pending guard, and analyzed-evidence evolution.
- 10-lesson deterministic simulation before this doc refresh: 10 lessons, 100 attempts, 100 background jobs succeeded, 10 evolution events, 11 generated plans, all attempts graded, latest plan has 10 tasks.

Review status:
- 霜弦 returned `DATA_REVIEW_PASS_WITH_SCOPE` for QB11 content/data gates.
- 镜花 returned `CODE_REVIEW_PASS_WITH_SCOPE` for state/evidence/lineage gates; the later cycle guard closes the noted residual risk.
- 观止 returned `QA_PASS_WITH_SCOPE` after adding the evolved-source cycle/self-reference case.

Scope honesty:
- Deterministic tests and simulations prove contract behavior, not live GPT/DeepSeek/Doubao semantic quality.
- Human/content review is still needed for naturalness, cognitive load, and final child-facing taste.
- Real local DB initialization/migration to QB11 is a separate explicit operation because current `data/local_learning_system.sqlite` is not silently mutated.
