### TEST_CASE_SPEC - 观止（agentKey: `guanzhi`）- 2026-07-08 11:28 CST

Objective:
Refine the v2 test-case contract after actual code `SKELETON_PASS`, targeted fixes, and scoped reviews. This spec now maps the preliminary cases to real files, symbols, routes, frontend test hooks, fixtures, scripts, and existing regression tests. It remains intentionally false-pass-resistant: green plumbing, deterministic mocks, schema-valid model output, screenshot presence, or report generation alone must not prove product quality.

Scope:
- Test case design artifact only.
- Single-child AI-native math learning loop: 10-task async round, child page, child/operator APIs, graph-bound evidence ledger, model routing, answer analysis, photo/OCR path, planner/evaluation/evolution, reports, visual/interaction regression, semantic/model-risk, adversarial/negative paths, and multi-round convergence.
- Exact file/symbol targets below are reconciled against the actual skeleton in `docs/architecture/code_skeleton_pass_v2.md` and current source. Any still-open item is marked as a coverage gap or future hardening item, not silently treated as covered.

Forbidden scope:
- Do not edit production implementation code.
- Do not write test code in this task.
- Do not run destructive commands or reset real learning evidence.
- Do not claim QA PASS, live model quality, OCR quality, rendered visual quality, or human教研/taste approval from this document.

Project boundary overlay:
- Source: `docs/product/ai_native_math_learning_prd_v2.md` `PROJECT_BOUNDARY_OVERLAY`, plus `AGENTS.md`, `docs/domain-index/math-learning.md`, and `docs/project-rules/qa-learning-system-addendum.md`.
- Domain oracle: incoming Grade 7; graph-bound; active round size 10; AI-first reasoning-aware grading; no parent intervention in normal learning; no low-age mechanical filler; no private/commercial question source assumption; current QB11 question-bank contract requires 20 active slots/node, node-local mainline floors, controlled picture-level stretch caps, and canonical-core diversity; self-evolution only from real active graded analyzed evidence with valid non-cyclic source attempt lineage; pending/malformed/invalidated/stale/fake evidence cannot drive mastery, planning, evolution, active scheduling, or reports.
- Evidence levels are distinct: deterministic mocks prove contract plumbing only; live GPT/compatible text provider proves limited semantic samples only; Doubao-compatible OCR proves photo transcription only; production/local DB facts prove persisted lineage only; rendered screenshots/browser traces prove UI states only; human review remains required for final visual taste and content naturalness.

Source artifacts:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/guanzhi.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/playbooks/qa.md`
- `docs/project-rules/qa-learning-system-addendum.md`
- `docs/collaboration/playbooks/artifact-contracts.md`
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/product/child_ux_flow_spec_v2.md`
- `docs/architecture/data_contract_spec_v2.md`
- `docs/architecture/technical_plan_v2.md`
- `docs/architecture/project_skeleton_v2.md`
- `docs/architecture/code_skeleton_pass_v2.md`
- `docs/collaboration/reviews/2026-07-08-jinghua-design-review-v2-addendum.md`
- `docs/collaboration/reviews/2026-07-08-jinghua-code-skeleton-review-v2.md`
- `docs/collaboration/reviews/2026-07-08-jinghua-code-skeleton-rereview-v2.md`
- `docs/collaboration/reviews/2026-07-08-shuangxian-data-review-technical-plan-v2.md`
- `docs/collaboration/reviews/2026-07-08-shuangxian-code-skeleton-data-review-v2.md`
- `docs/collaboration/reviews/2026-07-08-shuangxian-code-skeleton-data-rereview-v2.md`
- `docs/collaboration/reviews/2026-07-08-qingqiu-ux-review-technical-plan-v2.md`
- `docs/collaboration/reviews/2026-07-08-qingqiu-code-skeleton-ux-review-v2.md`
- Current inventory facts: `docs/system/local_learning_system.md`, `docs/system/qa/question_bank_grade_level_latest.md`, `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`, `scripts/audit_question_bank_grade_level.py`, `scripts/generate_daily_report.py`, `scripts/live_child_acceptance.py`, `scripts/live_child_ui_10x.py`, `scripts/child_learning_scenarios.py`.

Skeleton pass:
- Actual code `SKELETON_PASS`: `docs/architecture/code_skeleton_pass_v2.md`, 2026-07-08 11:48 CST.
- Review status incorporated: 镜花 initial `CODE_REVIEW_NEEDS_FIX` found session/evolution evidence-gate bypasses; 镜花 rereview is `PASS_WITH_SCOPE` after fixes. 霜弦 initial `DATA_REVIEW_NEEDS_FIX` found thin `answer_analysis` and unreviewed diagnostic active-use bypasses; 霜弦 rereview is `PASS_WITH_SCOPE` after fixes. 清秋 UX skeleton review is `PASS_WITH_SCOPE` with durable error-state hardening gaps.
- Local verification facts from 若命 to preserve as evidence context, not QA PASS: `python3 -m compileall learning_system` passed; focused evidence-gate tests passed; full `python3 -m unittest tests.test_learning_system -v` later passed 171/171 after QB11, structured answer-analysis hardening, reviewer-run authenticity, candidate-hash active-use binding, evolved-source cycle hardening, and async child-flow recovery tests; browser smoke passed after the five-dimension `answer_analysis` fixture update.
- Business logic status remains scoped: no live model/OCR quality claim, no final visual/taste approval, no final question-spec format, and no long-run mastery threshold tuning.

Engineering contract:
- Source: `docs/architecture/technical_plan_v2.md` `ENGINEERING_CONTRACT`.
- Binding interfaces: child bootstrap, child submission, child complete, attachment fetch, operator bootstrap, operator close, operator submission, manual grade/backfill, invalidation, maintenance evolution, plan generation, DB evidence predicate, model route adapter, answer review, session close, planner, evolution, reports.

Implementation blueprint:
- Source: `docs/architecture/technical_plan_v2.md` `IMPLEMENTATION_BLUEPRINT` and `docs/architecture/project_skeleton_v2.md`.
- Complexity: high_risk_change.
- Required later skeleton: child state enum/fixture renderer, child-safe DTO projections, shared evidence predicates, async worker shell, model route status helper, answer-analysis adapter, orchestrator state machine, planner/evolution/report seams, question-spec loader seam, and test hooks.

Risk classification:
- High: child learning flow, async state machine, graph/evidence contracts, model reasoning, photo/OCR, self-evolution, report lineage, child-safe boundaries, and visual/interaction quality.
- False-pass risk is high because prior green scripts can prove only flow plumbing. QA must separately verify chain integrity, semantic integrity, teaching integrity, provider integrity, visual/interaction evidence, and false-pass audit consistency.

2026-07-09 multi-role review status:
- 观止 verdict: `NEEDS_FIX`. Deterministic backend coverage is strong, but live/browser replay can still false-pass because `live_child_ui_10x.py` must hard-assert 10 tasks per lesson, must call the semantic oracle (`validate_session_semantics` and required coverage checks), and must require an explicit test environment/DB ledger before mutating evidence.
- 镜花 verdict: `NEEDS_FIX`. Reviewer-run authenticity needs a replay-specific hardening case: a previously valid reviewer run for the same `question_id` must not authorize changed prompt/solution/source/candidate content. Stale `running` job recovery and report producer-consumer freshness also need executable coverage.
- 霜弦 verdict: `NEEDS_FIX`. Graph topology and graph hash lineage must become executable assertions, report claims must be mapped one by one to source evidence, and question-bank audit script verdict/issue-count/exit-code consistency must be a content gate.
- Scope consequence: this spec may be considered reviewed only after these gaps are represented below; it is still not QA PASS and not live-model/browser PASS.

2026-07-09 closeout rereview:
- 观止 returned `QA_REVIEW_PASS_WITH_SCOPE`: the false-pass gaps are now represented in the spec, including hard 10-task live/browser gate, semantic oracle use, explicit test DB/env ledger, evidence-level honesty, and stale report freshness.
- 镜花 returned `CODE_REVIEW_PASS_WITH_SCOPE`: the architecture QA gaps are now represented in the spec, including reviewer-run replay against changed same-id candidate, stale `running` restart variants, and report producer-consumer label/freshness.
- 霜弦 returned `DATA_REVIEW_PASS_WITH_SCOPE`: the data/content QA gaps are now represented in the spec, including graph topology, graph hash lineage, report claim evidence map, question-bank audit executable gate, and SEM/OCR sample scope.
- Closeout scope: this is a TEST_CASE_SPEC review pass with scope. It does not mean executable tests, live model/OCR calls, browser replay, or implementation fixes have passed.

Code skeleton reconciliation - actual symbol map:
| Area | Actual file/symbol/route/hook | Mapped cases | Current evidence target |
|---|---|---|---|
| Evidence usability | `learning_system/db.py::EvidenceUsePolicy`, `is_current_usable_attempt_evidence`, `is_valid_answer_analysis`, `validate_answer_analysis`, `REQUIRED_ANALYSIS_DIMENSIONS` | MU-01, MU-08, ASY-04, DATA-06, DATA-07, SEM-02, SEM-03 | `tests/test_learning_system.py::test_thin_answer_analysis_is_not_usable_evidence`, `test_reports_and_planner_reject_current_pending_or_malformed_analysis_evidence` |
| Child schedulable question gate | `learning_system/db.py::is_child_schedulable_question`, `_has_active_question_review_record`, `_reviewer_run_authorizes_question_review`, `assert_current_active_question_ids`, `record_attempt` | MU-02, DATA-04, ADV-03, ADV-16, ADV-17, ADV-20, API-03, API-05 | Existing tests cover missing/fake/wrong-agent run and stale active record retirement; required gap: `REV-RUN-HASH-01` must prove an old accepted reviewer run cannot authorize changed same-id candidate content |
| Evolution source gate | `learning_system/evolution.py::is_evolution_source_valid`, `_candidate_attempts`, `run_evolution`; `learning_system/db.py::is_evolution_source_valid` | MU-03, E2E-08, ADV-09 | `test_evolution_rejects_attempt_when_review_record_no_longer_schedulable`, `test_global_evolve_skips_active_child_learning_group_until_session_completion` |
| Child/operator projections | `learning_system/server.py::ChildAPIProjection`, `OperatorAPIProjection`, `CHILD_SCHEMA_VERSION`, `CHILD_DTO_FORBIDDEN_KEYS`; routes `/api/child-bootstrap`, `/api/bootstrap` | MU-04, MU-05, API-01, API-02, API-10, UI-12, E2E-12 | `test_child_bootstrap_is_child_safe_and_excludes_internal_operator_data`, browser smoke forbidden text/field scan |
| Submission routes | `learning_system/server.py::LearningSystemHandler._resolve_child_submission_target`, `_create_child_submission`; routes `/api/child-submissions`, `/api/operator/child-submissions` | API-03, API-04, API-05, ASY-01, ASY-08, UI-02, UI-03 | `test_child_submission_endpoint_rejects_internal_ids`, `test_child_submission_returns_before_async_ai_review_finishes`, attachment tests |
| Session close/orchestration | `learning_system/orchestrator.py::SessionClosureStateMachine`, `close_learning_session`, `run_maintenance_evolution`; routes `/api/learning-sessions/current-learning-group/complete`, `/api/operator/learning-sessions/{id}/complete`, `/api/evolve` | MU-11, API-06, API-07, API-08, API-11, API-14, ASY-02, ASY-09 | `test_session_close_blocks_when_review_record_no_longer_schedulable`, `test_teaching_session_orchestrator_concurrent_close_is_idempotent`, browser smoke close/evolve path |
| Flow-node evidence packages | `learning_system/flow_nodes.py::build_evidence_package`, `build_answer_analysis_package`, `build_graph_binding_package`, `build_mastery_evaluation_package`, `build_child_teaching_package` | ASY-02, ASY-04, E2E-01, E2E-07, DATA-10 | `test_session_complete_records_five_core_flow_nodes`, `test_graph_binding_rejection_blocks_evolution_and_planning` |
| Model route/provider seam | `learning_system/model_router.py::ModelRouteStatus`, `route_status`, `configured_route_statuses`, `call_structured_json`; `learning_system/auto_review.py::review_child_answer`, `_review_answer_photo` | MU-06, MU-07, ASY-03, ASY-05, ASY-06, SEM-08, SEM-09, SEM-12 | `test_model_router_routes_text_question_and_doubao_vision_models`, `test_answer_analysis_falls_back_when_model_rejects_json_schema_format`, photo/OCR tests |
| Answer-analysis adapter | `learning_system/auto_review.py::AnswerAnalysisResult.from_review`, `_normalize_answer_analysis`, structured evaluation-support consistency | MU-08, SEM-01..SEM-07, SEM-10, SEM-11, ADV-18 | `test_answer_analysis_rejects_string_comparison_items`, `test_child_text_submission_downgrades_correct_answer_with_unsound_reasoning`, `test_child_text_submission_caps_structurally_inconsistent_full_credit`, scenario matrix test |
| Planner/current bank | `learning_system/planner.py::PlanTaskDTO`, `_usable_attempts`, `_plan_uses_current_active_bank`, `generate_next_plan`, `latest_or_create_plan`; `learning_system/db.py::find_question_for_node` | MU-12, MU-13, API-15, DATA-03, E2E-03, E2E-04 | planner/current-bank and rollback tests around line 1727 onward in `tests/test_learning_system.py` |
| Reports/agent summaries | `learning_system/reports.py::report_claim_label`, `generate_report`, `learning_system/agents.py::*_agent_report` | MU-14, DATA-10, DATA-14, DATA-20, E2E-09 | Existing daily report and agent report tests are scoped; required gaps: claim-by-claim evidence map, report freshness, and stale/pending/blocked label matrix |
| Question-spec seam | `learning_system/question_bank.py::QuestionSpecLoader.status`, Python quality gates in `question_bank.py` | MU-16, DATA-13 | `test_v2_code_skeleton_contract_symbols_are_exposed_fail_safe`; future parity tests required before activation |
| Frontend state/fixture seam | `app/local_learning_system/app.js::CHILD_UI_STATES`, `CHILD_DTO_FORBIDDEN_KEYS`, `fixtureForChildState`, `window.ChildLearningShell.currentState`; DOM ids in `app/local_learning_system/index.html` | UI-01..UI-12, VIS-01..VIS-12 | `tests/browser_smoke_learning_system.mjs`; future screenshot/focus/error-panel tests required |
| Live/long-run harnesses | `scripts/live_child_acceptance.py`, `scripts/live_child_ui_10x.py`, `scripts/child_learning_scenarios.py`, `scripts/audit_question_bank_grade_level.py` | E2E-10, E2E-13, false-pass audit, semantic scenario matrix, question quality | Available harnesses; no live QA execution claimed. Required gaps: hard 10-task lesson gate, semantic oracle invocation, explicit test DB/env ledger, report freshness |

Review-driven regression cases added to this spec:
| Case | Source review/fix | Actual target | Required assertion |
|---|---|---|---|
| REG-01 Thin answer analysis blocked | 霜弦 P1, fixed/rereviewed | `db.validate_answer_analysis`, `db.is_current_usable_attempt_evidence`, `orchestrator.close_learning_session`, planner/evolution/report consumers | Missing any of `final_answer`, `model_or_relation`, `steps`, `symbols_units`, `check_or_explanation`, or missing required `process_gap`/`no_gap_observed`, cannot become usable evidence or close/evolve/plan/report as confirmed |
| REG-02 Unusable evidence blocks close before downstream packages | 镜花 P1, fixed/rereviewed | `db.session_completion_summary`, `orchestrator.close_learning_session`, `flow_nodes._attempts_for_summary` | A structurally analyzed attempt whose question loses schedulable review record returns `closure_status=blocked`, `blocked_reason=evidence_not_usable`, and does not run answer/evaluation/evolution/planning |
| REG-03 Evolution rejects unschedulable source evidence | 镜花/霜弦 P1, fixed/rereviewed | `evolution._candidate_attempts`, `db.is_evolution_source_valid` | `run_evolution` returns `no_action` and creates no profile/status/question changes when the only weak evidence fails the shared predicate |
| REG-04 Unreviewed diagnostic active-use rejection | 霜弦 P1, fixed/rereviewed | `db.is_child_schedulable_question`, `db.create_learning_session_for_plan`, `server._resolve_child_submission_target`, `db.record_attempt` | Legacy/unreviewed `diagnostic` or unknown-source question cannot enter child session or active attempt path unless an explicit reviewed allowlist is added by future product decision |
| REG-05 UX durable error panels | 清秋 PASS_WITH_SCOPE gap | `app/local_learning_system/app.js` load/save/upload error states and page DOM | `load_error` must render durable page-level retry/error panel; `save_error` and `upload_error` must be persistent/inspectable enough for screenshot, keyboard, and screen-reader regression before final QA |
| REG-06 Regex/string semantic-judgment removal | 若命/镜花/观止 2026-07-09 review | `auto_review.py`, `planner.py`, `question_bank.py`, `evolution.py` | Answer grading, mastery, rollback, active-use, and question approval cannot be driven by child-answer keywords, fixed regex, or string `comparison`; remaining regex/string usage must be limited to safety filtering, id/signature normalization, or child-facing meta rejection |
| REG-07 Reviewer-run authenticity and candidate binding | 观止 P1, fixed/rereviewed | `db.record_question_review_record`, `_has_active_question_review_record`, `_reviewer_run_authorizes_question_review` | `source.reviewer_evidence` alone cannot activate a question; fake, missing, wrong-agent, non-accepted, wrong-question reviewer runs fail; replacing a question's JSON retires old active review records and candidate hash mismatch blocks child scheduling |
| REG-08 Async child-flow no-wait path | User-observed stuck review bug, fixed/regressed | child submission, background jobs, session completion polling | Child can submit and move on; only group completion waits for pending review summary; no permanent "reviewing" state from missing evaluator config, stale jobs, or old plan/session mismatch |
| REG-09 Full-round feedback completeness | User-observed one-question feedback bug | close projection, child review points, answer-analysis package | When a 10-task group completes, review-ready payload covers every relevant submitted task, not only the last task; pending tasks are labeled separately and never silently omitted |
| REG-10 Reviewer-run replay hash binding | 镜花 2026-07-09 P1 | `_reviewer_run_authorizes_question_review`, question review record active-use predicate | A real accepted reviewer run for `question_id=A` cannot be replayed after the raw candidate changes; prompt/solution/source/spec/hash mismatch must fail even when the run id is real |
| REG-11 Live 10-task semantic replay gate | 观止 2026-07-09 P1 | `scripts/live_child_ui_10x.py`, `scripts/child_learning_scenarios.py` | Live/browser replay must fail if any lesson has fewer than 10 tasks, skips required scenario classes, or reports PASS without semantic oracle validation and issue-count/exit-code consistency |
| REG-12 Report claim freshness and evidence map | 镜花/霜弦 2026-07-09 P2 | `reports.report_claim_label`, `generate_daily_report.py`, report artifacts | Every parent/Codex progress claim is confirmed/pending/stale/blocked/missing from DB predicates and source ids; stale `latest.md` cannot be treated as current progress |
| REG-13 Graph topology and hash lineage | 霜弦 2026-07-09 P1/P2 | graph seeding, `system_meta.graph_ref`, seed/reviewer `agent_runs`, planner rollback | Graph topology is internally consistent; graph sha/version is written to DB/run metadata; graph hash changes make old plans/questions/evidence stale or blocked rather than silently current |

Method/unit cases:
| Case | File/symbol | Input/state | Expected | Oracle/rubric | Test target |
|---|---|---|---|---|---|
| MU-01 Evidence usability matrix | `learning_system/db.py::EvidenceUsePolicy`, `is_current_usable_attempt_evidence`, `validate_answer_analysis` | active/invalidated x pending/graded x five-dimension valid/thin/malformed analysis x current/stale/unschedulable question x fake/live metadata | True only for active + graded + valid `answer_analysis_agent` analysis + current child-schedulable question | Data contract usability predicate | Unit |
| MU-02 Child schedulable question gate | `learning_system/db.py::is_child_schedulable_question`, `_has_active_question_review_record`, `_reviewer_run_authorizes_question_review`, `assert_current_active_question_ids` | graph-bound/current/reviewer-approved vs forged metadata/missing review/stale version/unknown node/unreviewed diagnostic/fake run/wrong-agent/non-accepted/wrong-phase/wrong-question run/seed manifest mismatch/old valid run replayed against changed same-id candidate | Only durable reviewer-approved current graph-bound item whose active review record and reviewer run both match the current candidate digest is schedulable | Reviewer-record/run gate beats item metadata, source metadata, stale active records, and replayed old runs | Unit |
| MU-03 Evolution source gate | `learning_system/evolution.py::is_evolution_source_valid`, `learning_system/db.py::is_evolution_source_valid`, `evolution._candidate_attempts` | real analyzed weak evidence vs pending, invalidated, fake, malformed, stale, no-analysis, unschedulable question | Only real active graded analyzed schedulable evidence can produce state/question/profile change | Self-evolution boundary | Unit |
| MU-04 Child DTO projection redaction | `learning_system/server.py::ChildAPIProjection`, `CHILD_DTO_FORBIDDEN_KEYS`, `_child_plan`, `_child_close_projection` | internal DB/session/question/attempt/agent rows | DTO exposes handle/position/display topic only; forbidden fields absent | Child boundary from PRD/UX/data | Unit |
| MU-05 Operator DTO separation | `learning_system/server.py::OperatorAPIProjection`, `GET /api/bootstrap` | same source objects | Operator route may expose ids/audit evidence; child route may not | Child/operator separation | Unit |
| MU-06 Model route fallback | `learning_system/model_router.py::call_structured_json` | json_schema rejected, json_object rejected, plain JSON valid; provider error; no route | Falls back by route policy, validates JSON locally, records secret-free metadata, returns pending/error on no route | Provider integrity | Unit |
| MU-07 Doubao vision route metadata | `learning_system/model_router.py::answer_photo_vision_route`, `route_status`, `configured_route_statuses` | vision config present/missing, base URL override, route-specific key | Route enabled only with config; no API key in audit/status | Provider integrity / secrets | Unit |
| MU-08 Answer-analysis normalization | `learning_system/auto_review.py::AnswerAnalysisResult`, `_normalize_answer_analysis`, `db.validate_answer_analysis` | final-only, wrong-reason-right-answer, alternative valid, malformed comparison, missing process gap/no-gap flag | Valid schema normalizes comparison; malformed/missing required fields stays pending or rejected | Semantic rubric | Unit |
| MU-09 Photo OCR confidence guard | `learning_system/auto_review.py::_review_answer_photo`, `_normalize_photo_ocr`, `_photo_ocr_is_usable`, `_photo_ocr_audit` | clear photo, unclear photo, photo-only with low confidence, text+unclear photo | OCR is untrusted; low-confidence photo-only remains pending; usable text can still be evaluated with caveat | Photo/OCR evidence policy | Unit |
| MU-10 Background job transitions | `learning_system/server.py::BackgroundReviewWorker`, handler methods `_start_background_session_processing`, `_background_process_session`, `_process_pending_session_answers` | queued/running/waiting/error/succeeded with retry count; stale `running` + pending attempt; stale `running` + already graded attempt | Legal transitions only; stale running recovered or closed audibly; retries capped; already graded attempts are not double-graded/evolved | Async recovery | Unit |
| MU-11 Session closure transition table | `learning_system/orchestrator.py::SessionClosureStateMachine`, `close_learning_session`, `db.session_completion_summary` | incomplete, all submitted pending, missing analysis, unusable evidence, graph binding fail, ready, concurrent repeat | Returns `waiting_ai`, `blocked`, or `planned/closed` idempotently; no downstream state on incomplete/pending/unusable | State machine | Unit |
| MU-12 Planner prerequisite rollback | `learning_system/planner.py::generate_next_plan`, `_rollback_targets`, `_usable_attempts` | Grade 7 wrong/partial with prerequisite chain and active candidates | Checks prerequisite chain before same-topic drilling; emits 10 graph-bound tasks | Teaching integrity | Unit |
| MU-13 Planner current-bank selection | `learning_system/planner.py::_plan_uses_current_active_bank`, `learning_system/db.py::find_question_for_node`, `learning_system/question_bank.py` quality gates | old attempted item, superseded bank row, rejected evolved row, current approved row | Selects current approved row only; avoids duplicates/recent repeats | Data lineage / question gate | Unit |
| MU-14 Report claim labels | `learning_system/reports.py::report_claim_label`, `generate_report`; `learning_system/agents.py` report builders | confirmed, pending, invalidated, stale, missing-analysis, blocked model states; latest report older than latest closed session; source ids missing | Report labels each claim accurately, links source attempt/session/evolution/report artifact ids, and never upgrades weak or stale evidence | Parent/Codex report oracle | Unit |
| MU-15 Child-safe message validator | Child projection/copy scans via `server.CHILD_DTO_FORBIDDEN_KEYS`, `app/local_learning_system/app.js::CHILD_DTO_FORBIDDEN_KEYS`, `scripts/child_learning_scenarios.py::check_child_safe` | Chinese/English internal terms, ids, model/provider/queue/rubric terms, child-safe feedback | Blocks internal leakage; accepts calm child-safe learning actions | UX copy boundary | Unit |
| MU-16 Question-spec loader parity seam | `learning_system/question_bank.py::QuestionSpecLoader.status` plus current Python quality gates | data-spec family/rubric/forbidden pattern equivalent to Python gate | Loader cannot weaken Python authority before parity; produces same rejection/approval reasons | Migration safety | Unit |
| MU-17 Graph topology/hash contract | graph loader/seed path, `system_meta.graph_ref`, seed/reviewer `agent_runs`, planner rollback dependencies | node prereq/unlock/edge cross refs, expected node/edge counts, rollback candidates, graph sha changes | Topology is internally consistent; seed run and DB metadata carry same graph sha/version; stale graph-derived plans/questions/evidence are blocked or marked stale | Graph lineage oracle | Unit/data |

API/service contract cases:
| Case | Interface/route/service | Request/input | Expected response/output | Error/permission path | Test target |
|---|---|---|---|---|---|
| API-01 Child bootstrap active group | `GET /api/child-bootstrap` | Clean/current DB with active 10-task group | `schema_version`, 10 tasks, task positions, child-safe prompts/support, `current-learning-group` handle, submitted positions | No raw ids/internal terms; load error child-safe | API contract |
| API-02 Child bootstrap review-ready | `GET /api/child-bootstrap` | Closed/planned session with review points | Completion projection includes all relevant review points and next action | No agent/model/graph/rubric leakage | API contract |
| API-03 Child submission save/advance | `POST /api/child-submissions` | `{session_handle:"current-learning-group", task_position:N, answer_raw}` | Saves attempt/job, returns fast `submission_state=saved`, child message, advances before grading | Empty answer+no photo rejected child-safely | API + timing |
| API-04 Child submission photo | `POST /api/child-submissions` | PNG/JPG/WebP data URL <=8MB plus optional text | Attachment metadata/file saved, job queued, response has sanitized saved state | Bad MIME, bad base64, magic mismatch, >8MB rejected; draft recoverable | API/data |
| API-05 Raw id rejection | `POST /api/child-submissions` | Payload includes `question_id`, `session_id`, `attempt_id`, or task not in group | Request rejected or ignored safely; no internal id accepted | Duplicate/stale group child-safe error | Boundary |
| API-06 Complete pending group | `POST /api/learning-sessions/current-learning-group/complete` | 10/10 submitted, at least one pending review | `closure_status=waiting_ai`, child-safe reviewing message, no parent action | Does not run evaluation/planning/evolution from pending evidence | API/state |
| API-07 Complete ready group | Same | 10/10 submitted and all valid analyses exist | `closure_status=planned/closed`, review points, coach points, next action | Child payload still excludes internals | API/state |
| API-08 Complete incomplete group | Same | Fewer than 10 submissions | Child-safe incomplete/wait message or active task state; no closure side effects | Repeat calls idempotent | API/state |
| API-09 Attachment fetch | `GET /api/attachments/{attachment_id}` | Valid attachment id from sanitized projection | Serves matching local image with `nosniff` | 404/409 on missing/tampered path/content mismatch | API/security |
| API-10 Operator bootstrap | `GET /api/bootstrap` | Local DB with plans/agents/reports | Id-rich readiness, reports, agent/evolution evidence for Codex only | Never used by child page | API separation |
| API-11 Operator close | `POST /api/operator/learning-sessions/{id}/complete` | Raw session id | Full closure package with evidence, analysis, graph binding, evaluation, evolution, next plan | Waiting/blocked/incomplete correctly distinguished | Service |
| API-12 Manual grade/backfill | `POST /api/attempts/{id}/grade`, `/analysis` | Structured grade/analysis | Records `answer_analysis_agent` audit; malformed analysis rejected | Maintenance only; cannot become child/parent normal flow | API/data |
| API-13 Invalidation | `POST /api/attempts/{id}/invalidate` | Active attempt id + evidence note | Marks invalidated; dependent evolved questions lose active eligibility; derived status/report recompute | Missing note rejected; no delete | API/data |
| API-14 Maintenance evolve | `POST /api/evolve` | Active child group vs no active group | Skips active child learning groups; no_action without usable evidence | Cannot consume pending/malformed evidence | Service |
| API-15 Plan generation | `POST /api/plans/generate` | Current evidence and active question bank | Generates 10 graph-bound current approved tasks | Blocks or reports when active bank insufficient/stale | Service |

UI/flow cases:
| Case | Page/flow | Steps | Expected state/feedback | Recovery/edge path | Evidence target |
|---|---|---|---|---|---|
| UI-01 Load active group | `/` active task | Open page with active group | Shows one focused child page, `第 N / 10 题`, saved count, prompt, answer area, photo tool, one primary CTA | Load failure shows child-safe retry | Browser DOM + screenshot |
| UI-02 Text answer save | Active task | Type reasoning, click save | Button enters saving, then next unsubmitted task appears; draft clears only after success | Save failure keeps draft and retry | Browser trace + API/DB |
| UI-03 Empty answer guard | Active task | Submit with no text and no photo | Child-safe prompt to write steps or add photo; no attempt created | Focus remains answer/photo area | Browser + DB |
| UI-04 Photo preview/remove | Active task | Select image, view preview/name, remove | Preview contained; remove reachable; no layout jump hiding CTA | Unsupported/too large shows upload error state | Screenshot + DOM |
| UI-05 Save 10th task | Task 10 | Submit final answer | Form hides; all-submitted reviewing state appears; child told work is saved and can return later | Retry/poll available, no parent instruction | Browser + API |
| UI-06 Review ready all questions | Review-ready state | Complete/poll after analyses ready | Review covers all relevant questions, coach/next-step points, one next action | Next-group start failure preserves review and retry | Browser + API |
| UI-07 Blocked/model disabled | Missing model route or unrecoverable review | Complete group | Shows saved assurance, wait/retry message, no fake grade, no parent action | Refresh later does not lose progress | Browser + DB |
| UI-08 No active group | Bootstrap empty | Open page | Calm no-task message, no fake sample task | Refresh/retry only if transient | Screenshot |
| UI-09 Stale group/direct refresh | Group changed between load/save | Submit stale task | Child-safe stale/refresh message, no duplicate hidden submission | Refresh returns current valid state | Browser + API |
| UI-10 New-knowledge task | Planner serves learn/check task | Open active task | Concise concept/model support and answer prompt; no system feature explanation | Wrong/partial later creates explanation/retry next action | Screenshot + semantic sample |
| UI-11 Diagnostic/remediation task | Planner serves diagnostic/rollback | Complete round | Task labels child-safe; review names observable gaps/actions, not graph internals | Prereq weakness leads to repair path | Browser + closure payload |
| UI-12 Child-only leakage scan | All states | Inspect text/DOM/JSON | No graph/model/agent/rubric/operator/Codex/internal ids | Fails on hidden visible text or accessible labels too | Browser + API serialized scan |

Visual/interaction regression cases:
| Case | Surface/viewport/state | Check | Expected | Evidence target |
|---|---|---|---|---|
| VIS-01 Desktop active task | 1365x900 `active_task` | Hierarchy, prompt wrapping, answer area, CTA visibility | Child can identify task/progress/answer/CTA in one focused surface; no overlap | Screenshot + pixel/DOM overflow check |
| VIS-02 Mobile active task | 390x844 `active_task` | Single column, 44px touch targets, no horizontal scroll | Progress/task/answer/photo/CTA order predictable | Screenshot + layout metrics |
| VIS-03 Photo preview | Desktop/mobile `active_task` with long filename | Preview contained; filename wraps/truncates; remove reachable | No clipped CTA or layout shift that hides controls | Screenshots |
| VIS-04 Saving disabled | `saving` | Disabled CTA readable; draft visible; live status present | No spinner-only ambiguity; reduced-motion respected | Screenshot + accessibility snapshot |
| VIS-05 Upload/save errors | `upload_error`, `save_error` | Error contrast, copy, focus destination | Error is child-safe/actionable; draft/photo recoverable where feasible | Screenshot + keyboard check |
| VIS-06 Reviewing | `all_submitted_reviewing` | Waiting copy, retry/poll affordance, no internal queue text | Child knows work is saved and can return later | Screenshot + forbidden text scan |
| VIS-07 Review ready | `review_ready` with 10 review points | All-question list density, wrapping, result meaning not color-only | Review covers relevant tasks without overlap; one primary next CTA | Screenshot + DOM count |
| VIS-08 Blocked/no group | `blocked`, `empty`, `load_error` | Calm copy, retry/later action, no parent dependency | No fake tasks or blame language | Screenshot |
| VIS-09 Keyboard/focus | All interactive states | Tab order, focus ring, post-save focus, review-ready focus | Title/progress -> support -> answer -> photo -> remove -> CTA; no trap | Browser keyboard trace |
| VIS-10 Accessibility labels/live regions | Form/status/review | Labels, headings, polite live region, file input accessibility | Screen-reader path is meaningful without visual-only cues | Accessibility snapshot |
| VIS-11 Reduced motion | Motion-enabled states | `prefers-reduced-motion` | Progress/toast transitions disabled/simplified | Browser emulation evidence |
| VIS-12 Final taste handoff | Rendered active/review states | Human review for age-respectful tone and visual taste | Manual review required before visual PASS | Human checklist, not automated PASS |

State/async/recovery cases:
| Case | State/task/queue | Trigger | Expected transition/retry/recovery | Evidence target |
|---|---|---|---|---|
| ASY-01 Submission does not wait for grading | Child submit + slow model | Delay model response | Response returns saved quickly; attempt pending/job queued; UI advances | API timing + DB |
| ASY-02 Pending completion | 10 submitted, jobs queued/running | Complete group | `waiting_ai`; no evaluation/planner/evolution/report mastery | API + DB |
| ASY-03 Model disabled | No evaluator route | Submit/complete | Attempts remain pending with auditable reason; no fake grade/mastery/evolution | DB `review_meta`, closure, report |
| ASY-04 Malformed model JSON | Model returns schema-valid envelope but missing comparison/gap | Worker processes | Attempt remains pending/error or blocked; downstream unusable | Job + attempt + report |
| ASY-05 Low-confidence OCR | Photo-only unclear answer | Worker processes | Pending/waiting unless written evidence suffices; no guessed mastery | Attachment + review meta |
| ASY-06 Retry transient provider error | First model call fails, second succeeds | Worker retry | Retry count/audit recorded; final grade only after valid analysis | Job rows + agent_runs |
| ASY-07 Stale running recovery | Server restarts with `background_jobs.status='running'` | Startup/bootstrap scan for pending attempt and already graded attempt variants | Pending work requeued/recovered; already graded work closes audibly; no duplicate grade/evolution/plan | DB before/after + logs |
| ASY-08 Duplicate submit | Double-click same task or resend payload | Same handle+position | One active attempt or safe duplicate response; no double-counted progress | API + DB count |
| ASY-09 Concurrent close | Two complete calls for same session | Parallel requests | Idempotent same closure/waiting result; one evolution/planner event | API + DB event count |
| ASY-10 Partial file write failure | Attachment saved but DB insert fails or DB saves but file missing | Inject failure in test env | Cleanup or 409/audit-safe state; no blind attachment serve | Unit/integration |
| ASY-11 Invalidation recovery | Invalidate source attempt after evolved question exists | Maintenance invalidation | Source attempt remains auditable; evolved question retired; reports/plans exclude it | DB lineage audit |
| ASY-12 Pending old sessions | Bootstrap with stale active/pending sessions | Load child page | Resumes work if routes available or labels blocked/waiting; no false current task | API + report |

Data/artifact cases:
| Case | Data/artifact/template | Sample/fixture | Expected rule/output | Protected/overwrite boundary |
|---|---|---|---|---|
| DATA-01 Graph JSON integrity | `data/knowledge_graphs/math/math_knowledge_graph_v2.json` | Current graph asset | Valid JSON; known prereq/unlock/edge refs; graph hash tracked | Read-only |
| DATA-02 Question bank 20 slots/node | DB/question items | Current bank `QB11` style fixture | 56 nodes x 20 active current high-quality slots; old rows not counted; each node meets node-local mainline floor, picture-level cap, label/stem repetition cap, and canonical-core diversity checks | Test DB only |
| DATA-03 Active round quota | Generated current plan | 10 tasks | 10 graph-bound tasks; at least 7 node-local mainline tasks; normally 1-2 controlled picture-level stretch tasks when semantically anchored; no padding | Test DB only |
| DATA-04 Reviewer record gate | Question item with forged `approved` metadata, forged `source.reviewer_evidence`, fake/missing/wrong-agent/non-accepted/wrong-phase/wrong-question reviewer run, seed manifest mismatch, old valid run replayed against changed same-id candidate, or same `question_id` replaced after a valid review | Scheduler/audit | Inactive unless a real accepted `question_reviewer_agent` run authorizes the current candidate hash; stale active records are retired | Test DB only |
| DATA-05 Forbidden question patterns | Low-age arithmetic, answer-only, backend/meta wording, prompt injection, graph-unbound | Reviewer gate | Rejected with auditable reason | No external content |
| DATA-06 Attempt result consistency | graded/pending combinations | score/result/explanation/blocking matrix | Pending=`submitted`; graded result/score consistent; correct with no reasoning not full mastery | Test DB only |
| DATA-07 Answer-analysis required fields | Missing `agent_key`, empty comparison, vague process gap | Attempt/evaluation | Blocks downstream use; report marks missing/blocked | Test DB only |
| DATA-08 Attachment metadata/file integrity | Valid and tampered local files | Attachment row + file | SHA/content type/path match; tamper returns 409/404 | No blind serve |
| DATA-09 Invalidation lineage | Invalidated attempt with status/evolved question/report refs | Invalidation path | Attempts retained, derived status recomputed/excluded, evolved question inactive | No destructive delete |
| DATA-10 Report labels | Report generator | confirmed/pending/inferred/stale/blocked/missing fixtures | Labels match DB evidence; no mock/temp/sample overstatement; every non-general claim links to source attempt/session/evolution/report artifact id | Report artifacts test-only |
| DATA-11 Agent run audit metadata | Model-backed and deterministic paths | `agent_runs` rows | Provider/model/schema/prompt hash present when real; deterministic marked scoped; no secrets | No API keys in output |
| DATA-12 Evolution audit links | Valid weak evidence -> evolved/rejected/no_action | `evolution_audits` | Links source attempts, before/after, created question ids, review record ids or no_action reason | Append/version only |
| DATA-16 Evolved source-attempt gate | Evolved question with missing/nonexistent/inactive/ungraded/malformed/cyclic source attempt | `lineage_integrity_audit`, scheduler | Question is not child-schedulable; lineage audit reports invalid evolved source attempt reason; no active plan/attempt can use it | Test DB only |
| DATA-17 Codex query is not result storage | Parent asks Codex after a generated result exists | DB/API/report artifacts vs any conversation-only output | Every claimed grading/planning/evolution/report result has durable DB row or report artifact; no separate Codex session/thread is required to recover it | Operator workflow only |
| DATA-18 Graph topology dependency contract | Graph asset and seeded DB graph tables | Expected current asset, including 56 nodes and graph/prerequisite edge sets | `nodes[].prerequisites`, `unlocks`, `edges`, and prerequisite edges are mutually consistent; no unknown refs; rollback targets sit on legal prerequisite/rollback chains; stage/order does not bypass prerequisites for 七上 errors | Read-only/test DB |
| DATA-19 Graph version/hash lineage | Graph seed metadata, reviewer seed run, plans/questions/attempts | Current graph hash vs changed graph hash fixture | `system_meta.graph_ref`, seed/reviewer `agent_runs`, and derived artifacts carry matching graph version/sha; graph hash mismatch marks old plans/questions/evidence stale/blocked instead of current | Test DB only |
| DATA-20 Report claim evidence map | Daily/parent/Codex report artifact | Mixed confirmed/pending/stale/blocked/missing source rows | Each claim has `evidence_label` and source attempt/session/evolution/report id; mock/temp DB rows are labeled scoped and cannot be presented as real learning progress | Report artifacts test-only |
| DATA-21 Question-bank audit executable gate | `scripts/audit_question_bank_grade_level.py` report path | Fixture with P0/P1 issue, 9-task round, over-cap picture stretch, verdict/issue mismatch | P0/P1 issue count, active-round quota violation, live lineage issue, or verdict/exit-code disagreement fails; content PASS remains `PASS_WITH_SCOPE` without human教研/live samples | Harness guard |
| DATA-13 Question-spec migration parity | `learning_system/question_bank.py::QuestionSpecLoader.status`; future `data/question_specs/` only after product decision | Equivalent data spec and Python constants | Same quality gate decisions before Python authority is retired | Future activation blocked until parity tests |
| DATA-14 Daily report freshness | `docs/system/daily_reports/latest.md` | Latest closed session vs report timestamp | Report not older than latest closed session, or explicitly stale | Generated artifact only |
| DATA-15 False-pass report consistency | QA/report scripts | Contradictory issue count/verdict/exit code fixture | Non-zero issues cannot emit PASS-like verdict/zero exit silently | Harness guard |

Scenario/e2e cases:
| Scenario | Actor | Given | When | Then | Evidence required |
|---|---|---|---|---|---|
| E2E-01 Diagnostic/remediation round | Son + system | Test DB, configured deterministic/recorded model | Child completes 10 mixed tasks | All attempts saved, analyzed, review points shown, next plan graph-bound | Browser, API, DB, agent runs |
| E2E-02 New-knowledge round | Son + system | Planner selects new node/concept | Child reads support, answers checks, completes group | Feedback teaches gap; next task consolidation/stretch/repair based on evidence | UI + closure + planner |
| E2E-03 All wrong/blank/stuck round | Son + system | 10 weak answers | Complete group | Review covers every relevant task; planner rollback/prereq/consolidation not same-topic drill | Semantic DB + planner |
| E2E-04 Correct-only round | Son + system | Strong correct reasoning answers | Complete group | Advances/retests appropriately without fabricating weakness; one answer alone does not overstate A | Evaluation + report |
| E2E-05 Correct answer wrong reasoning | Son + model | Final answer right, relation/process wrong | Review runs | Partial/wrong, process gap, next child prompt; no full mastery | Model sample + DB |
| E2E-06 Photo clear/unclear | Son + vision | Clear photo and unclear photo samples | Submit and review | Clear can be graded with OCR evidence; unclear pending/partial by evidence | Attachment + OCR meta |
| E2E-07 Model route failure | System | Missing/incompatible evaluator | Child completes group | Pending/waiting/blocked with explicit reason; no fake grading/evolution | API + DB + report |
| E2E-08 Weak evidence -> evolution | System | Real active graded analyzed weak evidence | Session closes | Evolution no_action/state/evolved only with audit; reviewer gates question before scheduling | Evolution audit + review record |
| E2E-09 Parent progress via Codex | Parent + Codex | DB with mixed confirmed/pending/stale states | Report generated | Progress, results, blockers, next plan separated by evidence labels | Report artifact + DB |
| E2E-09B Parent query after generation | Parent + Codex | A round has generated answer analysis, evaluation, evolution, and next plan | Parent asks Codex for progress | Codex reads DB/API/report artifacts and summarizes; no runtime result-feedback Codex session/thread is needed | DB rows + report artifact + operator query transcript |
| E2E-10 Multi-round convergence | Son + system | 3-10 lessons with scenario matrix, each lesson exactly 10 tasks | Repeated complete cycles | Weak points sharpen, plans follow evidence, no arbitrary task rotation or loop; underfilled lessons fail the harness | `live_child_ui_10x.py` + semantic oracle + DB/report |
| E2E-11 Restart recovery | System | Pending jobs, active session, server restart | Bootstrap/complete after restart | Jobs resume or blocked state is explicit; no duplicate closure | DB + server logs |
| E2E-12 Child-safe full flow | Son | All major UI states visited | Browser scans text/DOM/API | No internal ids/agent/model/graph/rubric/operator leakage | Screenshots + serialized scans |
| E2E-13 Live/browser QA artifact freshness | 观止 + system | Controlled test DB/uploads, explicit model mode, current code version | Run browser/live acceptance | Report records DB path, provider mode, code/test version, timestamps, screenshots, DB facts, issue count, exit code; stale report cannot be reused as current PASS | Harness + report |

Semantic/model-risk cases:
| Case | Input/sample | Expected semantic result | Evidence level required | False-pass guard |
|---|---|---|---|---|
| SEM-01 Sound reasoning correct | Complete relation, steps, check | `correct`, high explanation evidence; still not sole proof of permanent mastery | Deterministic + live sample | Do not infer A from one answer |
| SEM-02 Answer only | Final answer present, no process | At most partial; process gap asks for steps/check | Deterministic + live sample | Exact-answer match cannot pass |
| SEM-03 Wrong reasoning right answer | Correct final answer, invalid/circular relation | Partial or wrong; comparison marks relation/steps incorrect | Deterministic + live sample | Schema-valid "correct" must fail |
| SEM-04 Alternative valid method | Different valid model/solution | Accepted with `alternative_valid` or matched dimensions | Live/recorded sample | Do not force single solution path |
| SEM-05 Partial relation wrong final | Sound setup, symbol/unit/final error | Partial with calculation/symbol gap | Deterministic + live sample | Not full wrong if reasoning evidence exists |
| SEM-06 Stuck/cannot start | "I do not know first step" | Wrong/blocking evidence; prerequisite probe/rollback possible | Deterministic + live sample | Parent note cannot be misread as child cannot-start |
| SEM-07 Blank/no usable evidence | Blank or no meaningful answer | Pending or wrong by confidence; no mastery | Deterministic + live sample | No hallucinated analysis |
| SEM-08 Clear photo | Paper work readable | OCR evidence used as untrusted support; grade based on validated analysis | Doubao/live vision or recorded OCR | Photo presence alone not proof |
| SEM-09 Unclear photo | Low confidence/unreadable | Pending or partial; no guessed result | Doubao/live vision or recorded OCR | Low confidence cannot drive plan |
| SEM-10 Malicious/prompt-injected answer | Child answer asks model to mark correct/expose system | Rejected/ignored in analysis; no prompt leakage | Deterministic + live sample | Model compliance with injection fails |
| SEM-11 Hallucinated explanation | Model invents problem facts or wrong attribution | Local validation/semantic oracle rejects or scopes evidence | Live sample + review | Pretty explanation is not semantic pass |
| SEM-12 Low-confidence model | Model returns uncertain/conflicting output | Pending/blocked or partial with explicit reason | Live/recorded | Low confidence cannot become mastery |

Negative/adversarial cases:
- ADV-01 Child payload includes raw ids: child API must reject/ignore and never bind to attacker-provided `question_id`, `attempt_id`, `session_id`, `node_id`.
- ADV-02 Child-visible DTO includes hidden internal field: forbidden serialized key/text scan must fail test and block QA.
- ADV-03 Question candidate claims approval in metadata without review record: scheduler must reject.
- ADV-04 Model output is valid JSON but semantically bad: answer analysis must not pass solely on schema.
- ADV-05 Model unavailable plus deterministic fallback tries to grade: must fail; fallback may keep workflow pending or produce candidate-only question where allowed, never fake mastery.
- ADV-06 Duplicate click on task 10 and concurrent complete: one closure/evolution/plan event only.
- ADV-07 Network loss during save: draft/photo recoverable where feasible; no phantom progress.
- ADV-08 Restart with stale running jobs: recovered or auditable waiting/error; no swallowed work.
- ADV-09 Invalidated or invalid source attempt after evolved question was scheduled: active eligibility removed and reports/plans exclude dependent evidence; missing/nonexistent/inactive/ungraded/malformed/cyclic source attempts are not child-schedulable.
- ADV-10 Low-age mechanical drill sneaks into active bank: question audit fails even if 20 slots/node count is met.
- ADV-11 Report generated from temp/mock DB is labeled as real progress: false-pass audit fails.
- ADV-11B Generated result exists only in a Codex conversation/session and not in DB/report artifacts: QA failure; result is not durable or queryable.
- ADV-12 Browser screenshots exist but state fixture not connected to real API path: visual evidence remains scoped, not QA PASS.
- ADV-13 Attachment path traversal or tampered file path: attachment fetch returns 404/409 and `nosniff`; no arbitrary file serve.
- ADV-14 Child copy tells learner to ask parent/Codex: UX/QA failure for normal learning flow.
- ADV-15 Prompt asks for private/commercial textbook-derived content or copies user photo sample: content gate blocks or marks unauthorized.
- ADV-16 Fake or wrong reviewer run: a non-existent run id, wrong `agent_key`, non-accepted status, wrong phase, wrong `question_id`, or seed manifest mismatch cannot make `active_eligible=1`.
- ADV-17 Stale active review reuse: replacing a question with the same `question_id` but different JSON/source/evidence must retire old active review records; scheduler must compare candidate hash before child active use.
- ADV-18 String/regex semantic bypass: string `answer_analysis.comparison`, keyword-only rollback tags, child answer keyword guards, or high/low signal prompt word lists cannot be accepted as teaching judgment evidence.
- ADV-19 One-task feedback omission: a 10-task group with multiple wrong/partial/pending attempts cannot show only the final task's analysis; child review payload must account for every submitted task's status.
- ADV-20 Reviewer-run replay against changed candidate: a real accepted reviewer run from the old candidate cannot authorize a new candidate under the same `question_id`; prompt/solution/source/candidate digest mismatch fails active use.
- ADV-21 Live harness under-count pass: a browser/live replay with 4 tasks, missing required semantic scenario classes, or skipped oracle validation must fail even if the page reaches a review state.
- ADV-22 Stale report reuse: a report artifact older than the latest closed session or generated from a different DB/provider/code version cannot be reused as current QA/progress PASS.

Fixtures / samples required:
- Frontend deterministic fixtures: `app/local_learning_system/app.js::window.ChildLearningShell.fixtureForChildState(uiState)` for `loading`, `empty`, `active_task`, `saving`, `save_error`, `upload_error`, `all_submitted_reviewing`, `review_ready` with 10 review points, `blocked`, `load_error`; future hardening must add durable DOM evidence for `load_error`, `save_error`, and `upload_error`.
- DB fixtures for evidence predicate matrix: pending, graded valid five-dimension analysis, graded thin/missing analysis, malformed analysis, invalidated, stale/unschedulable question, fake/deterministic model, current reviewer-approved question, forged source reviewer evidence, fake/wrong/non-accepted/wrong-phase/wrong-question reviewer run, old valid run replayed against changed same-id candidate, and replaced same-id question with stale active review record.
- Question fixtures: current approved, old/superseded, forged metadata approval, forged source reviewer evidence, rejected evolved, unknown node, low-age mechanical, answer-only, backend/meta wording, prompt injection, duplicated core stem, same-id replaced item with changed candidate hash.
- Semantic answer fixtures from `scripts/child_learning_scenarios.py`: `correct_full`, `answer_only`, `stuck`, `wrong_reason_right_answer`, `photo_correct`, `photo_unclear`, `partial_relation_wrong_final`, `blank_or_no_evidence`.
- Photo fixtures: valid PNG/JPG/WebP, invalid MIME, bad base64, magic-byte mismatch, >8MB, clear paper-work sample, unclear/low-confidence sample. User-provided photos may calibrate difficulty only and must not be copied into prompts/solutions.
- Model fixtures: deterministic mock, recorded GPT-compatible answer analysis, recorded Doubao-compatible OCR, malformed JSON, unsupported `json_schema`, unsupported `json_object`, timeout/transient provider error, disabled route.
- Report fixtures: confirmed/pending/inferred/stale/blocked/missing lineage rows and a stale `latest.md` timestamp.
- Visual fixtures: desktop and mobile states with long Chinese/math prompt, long filename, 10 review points, blocked state, no active group, reduced-motion mode.
- Graph fixtures: current graph asset, intentionally broken prereq/unlock/edge ref, illegal rollback target, stage/order bypass, matching graph sha seed metadata, and changed graph sha stale-lineage case.

Test files authorized:
| File/path | Purpose | Allowed change | Owner |
|---|---|---|---|
| `docs/qa/test_case_spec_v2.md` | This TEST_CASE_SPEC artifact | Create/update in this task | 观止 |
| `tests/test_learning_system.py` | Existing unit/API/service/state/data/semantic regression home; current suite has 171 tests per 若命 verification after structured review/answer-analysis, reviewer-run authenticity, candidate-hash active-use, async child-flow, and lineage hardening | Not authorized to edit in this task unless a reviewed gap requires immediate regression coverage; future executable QA/test changes require explicit authorization or 若命 implementation scope | 听云/观止 when explicitly authorized |
| `tests/browser_smoke_learning_system.mjs` | Existing browser/API smoke with temp DB/uploads, child-only forbidden scan, `ChildLearningShell` fixture checks, and pending/evolution guard | Not authorized to edit in this task; future visual/interaction checks require explicit authorization | 听云/观止 when explicitly authorized |
| `scripts/child_learning_scenarios.py` | Existing semantic fixture/oracle source for multi-state child answers and `check_child_safe` | Not authorized to edit in this task | 观止/听云 when explicitly authorized |
| `scripts/live_child_acceptance.py` | Existing live/API/report acceptance harness | Not authorized to run or edit in this task; use only with controlled environment and explicit side-effect scope | 观止 when explicitly authorized |
| `scripts/live_child_ui_10x.py` | Existing multi-round UI/semantic convergence harness | Not authorized to run or edit in this task; before PASS it must enforce 10 tasks/lesson, semantic oracle coverage, explicit test DB/env ledger, and issue-count/exit-code/report consistency | 观止 when explicitly authorized |
| `scripts/audit_question_bank_grade_level.py` | Future question-bank regression gate | Not authorized in this task; before content PASS it must fail on P0/P1 issues, quota violations, live-lineage issues, and verdict/issue-count/exit mismatch | 霜弦/观止 when explicitly authorized |
| `scripts/generate_daily_report.py` | Future report artifact validation | Not authorized in this task; existing command target | 听云/观止 when explicitly authorized |

Automation plan:
1. Treat the symbol map above as the current implementation routing source. If future code moves a symbol, update this spec before adding/claiming tests.
2. Keep deterministic unit/API/service regressions anchored in `tests/test_learning_system.py`: evidence predicates, DTO redaction, route contracts, async state transitions, model adapter fallbacks, answer-analysis schema guards, planner/evolution/report labels.
3. Preserve the review-driven regressions as non-negotiable gates: thin analysis rejection, unusable evidence blocks close, unschedulable evidence blocks evolution, unreviewed diagnostic active-use rejection, reviewer-run authenticity, candidate-hash active-use binding, string/regex semantic-judgment removal, all-task feedback completeness, and durable error-state hardening before final QA.
4. Use `scripts/child_learning_scenarios.py` as the semantic scenario oracle and ensure required child-learning scenario classes cannot be skipped by a green happy path; `live_child_ui_10x.py` must call semantic validation directly rather than duplicating a weaker local audit.
5. Extend browser fixture-state checks before final QA: desktop/mobile screenshots, overflow metrics, forbidden text scan, keyboard/focus order, live regions, reduced-motion behavior, durable `load_error`, `save_error`, and `upload_error` panels.
6. Use explicit test DB/uploads scope for integration cases: 10 submissions, pending/waiting, ready closure, invalidation propagation, restart recovery, duplicate/concurrent close, report freshness.
7. Run question-bank audit as a content regression gate, but keep verdict scoped unless human教研 and live semantic samples are covered.
8. Run live provider samples only with explicit environment/side-effect scope: GPT-compatible answer analysis, Doubao-compatible OCR, route fallback metadata. Live evidence must be labeled by provider and sample id.
9. Run `live_child_acceptance.py` and `live_child_ui_10x.py` only against an explicit controlled test environment or with explicit authorization for real submissions. Their verdicts must compare exit code, issue count, report verdict, screenshots/artifacts, and DB/API facts; any lesson with `task_total != 10` is a failing test, not scoped PASS.
10. Treat graph topology/hash lineage as a first-class data gate: seed metadata, reviewer seed runs, plans, questions, attempts, planner rollback candidates, and reports must agree on graph version or explicitly mark stale/blocked.
11. Final QA must combine at least two evidence types for high-risk paths: browser/API, API/DB, DB/report, model output/semantic oracle, screenshot/DOM metrics.
12. No PASS-like result may be issued if model calls are mocked for semantic claims, if visual claims lack rendered evidence, or if report/script verdict conflicts with issue count or exit code.

Manual QA handoff:
- Human visual/taste review remains required for final child page style, age-respectful tone, exact copy, and whether the interface feels clear to the target child.
- Human教研/content sampling remains required for question naturalness, cognitive load, and whether automated "picture-level" signals genuinely match incoming Grade 7 reasoning.
- Parent/user must authorize any destructive reset of real DB/uploads, external model calls in a non-test setting, or use of external/private content sources.
- QA execution must record environment, DB path, server command, model/provider mode, sample ids, screenshot paths, report paths, and whether evidence is deterministic, recorded, live, production/local DB, or human review.

Coverage gaps:
- This document did not execute tests, start a server, call model providers, inspect rendered UI, reset DB, or create screenshots. 若命 local verification facts are recorded as context, not re-executed QA evidence by 观止.
- The 171 deterministic/unit/API tests are strong contract evidence, but they are not a substitute for a real browser-operated 10-task lesson replay with varied correct/wrong/stuck/photo answers and semantic inspection of resulting analysis, plan, report, and evolved question records.
- Current live/browser replay evidence is explicitly scoped until it hard-asserts 10 tasks per lesson, calls the shared semantic oracle, records a controlled DB/provider/code-version ledger, and fails on issue-count/verdict/exit-code disagreement.
- 清秋 scoped UX gaps remain: `load_error` lacks durable page-level retry/error panel; `save_error` and `upload_error` rely mostly on toast and need persistent inspectable presentation before final UX/QA.
- Existing `question_bank_grade_level_latest.md` is `PASS_WITH_SCOPE`; it does not replace human教研 review or live answer-analysis validation.
- Existing deterministic tests can support contract coverage but cannot prove live GPT/Doubao semantic/OCR behavior, nor can they prove the generated explanation is pedagogically optimal for this child.
- Existing browser smoke proves important child-only contract and fixture plumbing, but not full desktop/mobile screenshot matrix, keyboard/focus traversal, contrast, final copy taste, or accessibility behavior.
- Reports have `report_claim_label` and lineage tests, but claim-by-claim parent/Codex report evidence labels still need final implementation/QA proof.
- Reviewer-run authenticity still needs the replay-specific executable case where an old accepted run is reused against changed same-id candidate content.
- Graph topology/hash lineage checks are now specified, but not re-executed here.
- Final A/B/C/D mastery thresholds remain provisional after real multi-day evidence; tests should preserve current guardrails but expect future tuning.
- Full question-spec migration format is not finalized. Loader parity cases are required only if/when the seam is created.
- Current project index is sparse; this spec now carries the route/test map for QA, but project/domain indexes should be updated when implementation stabilizes.
- Live model/OCR quality, final visual/copy taste, final question-spec format, and long-run mastery threshold tuning remain missing project boundary decisions.

Stop condition:
This refined TEST_CASE_SPEC is complete for the current authorized task when downstream implementation/QA can locate actual files, symbols, routes, fixtures, scripts, existing regression tests, evidence requirements, and remaining gaps without guessing. It is not QA execution and must not be cited as QA PASS, live model/OCR PASS, or final visual/content approval.
