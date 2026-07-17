### TEST_CASE_SPEC - 观止（agentKey: `guanzhi`）- 2026-07-10 19:19 CST

Objective:
Produce skeleton-derived v3 test cases for the first implementation slice: `daily_flow` current-step old-knowledge review hot path, evidence gate, candidate packet, async/model recovery, semantic/model oracle, reports, UI flow, and false-pass harness. This artifact is test design only.

Scope:
- Method/unit, API/service, UI/flow, visual/interaction, state/async/recovery, data/artifact, semantic/model oracle, scenario/e2e, and negative/adversarial cases for v3.
- Use actual skeleton files/routes/tables/classes/functions already present in the repository.
- Include required 10-20 adaptive-day coverage, no fixed hidden list, slow/unavailable model handling, late evidence, candidate packet, evidence gate, answer-only/wrong-reason/stuck/blank/photo/symbol-unit semantic cases, report labels, and false-pass harness checks.

Forbidden scope:
- Do not execute QA PASS.
- Do not edit production code.
- Do not write test code in this task.
- Do not reset/delete real DB rows, uploads, reports, attempts, model outputs, or review records.
- Do not claim live model/OCR quality, rendered UI quality, or human teaching/taste approval from this document.

Project boundary overlay:
- Sources: `AGENTS.md`, `docs/product/ai_native_math_learning_prd_v3.md`, `docs/architecture/technical_plan_v3.md`, `docs/domain-index/math-learning.md`, and `docs/project-rules/qa-learning-system-addendum.md`.
- Stable oracle: single child, math-first summer bridge, old-knowledge review before new learning, one child page, one current step, graph-bound questions/evidence/plans/reports, 10-20 adaptive interactions not a fixed worksheet, no parent intervention in normal learning, no raw child-visible internals, no low-age mechanical filler, planner sees compact candidate packet only, agents do semantic work only through `model_router`, and pending/stale/mock/missing-lineage evidence must fail closed.
- Evidence level rule: deterministic mocks prove contracts only; recorded/live model and OCR samples must be labelled separately. Mock-only semantic/model coverage can at most support scoped QA later.

Source artifacts:
- `docs/collaboration.md`
- `docs/collaboration/roles/guanzhi.md`
- `docs/collaboration/agent-registry.json`
- `docs/project-rules/qa-learning-system-addendum.md`
- `AGENTS.md`
- `docs/product/ai_native_math_learning_prd_v3.md`
- `docs/architecture/technical_plan_v3.md`
- `docs/architecture/code_skeleton_pass_v3.md`
- `docs/project-index.md`
- `docs/domain-index/math-learning.md`
- `docs/qa/test_case_spec_v2.md`
- `learning_system/db.py`
- `learning_system/daily_runtime.py`
- `learning_system/graph_runtime.py`
- `learning_system/evidence_gate.py`
- `learning_system/job_queue.py`
- `learning_system/question_bank.py`
- `learning_system/model_router.py`
- `learning_system/reports.py`
- `learning_system/server.py`
- `app/local_learning_system/app.js`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`

Skeleton pass:
- Source: `docs/architecture/code_skeleton_pass_v3.md`.
- diff_pin: code skeleton v3 file list.
- Existing skeleton hooks:
  - `learning_system/db.py::init_schema` creates `daily_flows`, `flow_steps`, `review_targets`, `evidence_validations`, `next_step_decisions`, `late_evidence_reconciliations`, `daily_summaries`, v3 attempt/job columns, and v3 indexes.
  - `learning_system/graph_runtime.py::GraphRuntimeService`, `GraphVersion`.
  - `learning_system/evidence_gate.py::EvidenceUsePredicate.evaluate`, `EvidenceGate.validate_attempt`.
  - `learning_system/job_queue.py::JobQueue`, `JobQueueResult`.
  - `learning_system/question_bank.py::QuestionBankService.candidate_packet_for_node`.
  - `learning_system/daily_runtime.py::DailyLearningRuntime`, `CurrentStepSubmission`, `v3_daily_runtime_enabled`, `disabled_child_payload`.
  - `learning_system/server.py` routes: `GET /api/child-bootstrap`, `POST /api/daily-flow/review/start`, `POST /api/current-step/submit`, `GET /api/operator/daily-flow/today`.
  - `app/local_learning_system/app.js` v3 branch: `isV3Payload`, `v3UiState`, `renderV3ChildState`, `renderV3CurrentStep`, `submitV3CurrentStep`, `handleV3PrimaryAction`, `window.ChildLearningShell`.
  - Existing active skeleton tests: all `test_v3_*` methods in `tests/test_learning_system.py`; the current focused suite has 30 v3 tests plus one v2 feature-flag smoke.

Engineering contract:
- Source: `docs/architecture/technical_plan_v3.md` `ENGINEERING_CONTRACT`.
- Binding contracts: one active flow per child/day, one visible current step per flow, current-step submit idempotency, graph/question/evidence lineage, compact candidate packet, `EvidenceUsePredicate` as shared consumer gate, SQLite job lease/recovery, late-evidence safe transition, seven report labels, and no v3 child payload internals.

Implementation blueprint:
- Source: `docs/architecture/technical_plan_v3.md` `IMPLEMENTATION_BLUEPRINT`.
- First fill target after skeleton: old-review hot path from load/create -> start review -> build target pool -> candidate packet -> one current step -> submit answer/photo/stuck -> enqueue analysis -> evidence validation -> evaluation update -> planner decision -> next step/teaching/summary, with recovery and late-evidence hooks.

Risk classification:
- High: child learning workflow, graph-bound evidence lineage, async/model recovery, OCR/photo evidence, semantic judgment, adaptive planning, report truthfulness, and false-pass harness risk.
- Current skeleton is intentionally fail-closed. Green skeleton tests do not prove learning behavior, semantic correctness, model quality, OCR quality, UI quality, or report correctness.

Hook gaps / REQUESTS before executable QA completion:
- `REQUEST-HOOK-01`: `DailyLearningRuntime.start_review_mode` now selects one real current graph-generated, active-eligible question. Replace the temporary deterministic selector with planner-backed review target construction that writes `review_targets`, source evidence, and `next_step_decisions`.
- `REQUEST-HOOK-02`: `DailyLearningRuntime.persist_child_response` now records a pending attempt, optional attachment metadata/file, and an `answer_analysis` job. Extend the executable QA target from this first submit slice into the worker chain and next-step transition.
- `REQUEST-HOOK-03`: no implemented v3 worker chain applies `answer_analysis -> evidence_validation -> evaluation_update -> planner_decision -> teaching_generation/current_step_projection`. Add explicit worker/service hooks before async/recovery cases can pass.
- `REQUEST-HOOK-04`: no implemented v3 planner adapter exists in the touched skeleton. Until it exists, next-step tests must target `next_step_decisions` table contracts and runtime application points rather than a real planner symbol.
- `REQUEST-HOOK-05`: `learning_system/reports.py::report_claim_label` now exposes the seven v3 labels and precedence. Add a v3 daily summary/report producer before report-label QA can pass beyond unit-level label precedence.
- `REQUEST-HOOK-06`: `app/local_learning_system/app.js` now exposes a child-safe stuck action. Extend QA from unit/DOM checks to browser scenarios for each stuck reason and downstream teaching response.
- `REQUEST-HOOK-07`: `tests/browser_smoke_learning_system.mjs` and `fixtureForChildState` are still fixed-list/v2-oriented. Add v3 current-step fixtures and browser path before visual/flow QA can pass.
- `REQUEST-HOOK-08`: no v3 10-20 adaptive-day simulation exists yet. Add a v3 mode to `scripts/simulate_child_learning_journey.py` or a new equivalent harness with report metadata and issue/verdict/exit-code agreement.

Method/unit cases:
| Case | File/symbol | Input/state | Expected | Oracle/rubric | Test target |
|---|---|---|---|---|---|
| MU-01 Graph version authority | `learning_system/graph_runtime.py::GraphRuntimeService.current_graph_version`, `version_info` | Current graph asset | Returns `metadata.version+sha256:<hash>` deterministically | Graph version is source of truth for v3 lineage | `tests/test_learning_system.py::test_v3_graph_runtime_version_and_binding` |
| MU-02 Graph binding fail-closed | `GraphRuntimeService.validate_graph_binding` | missing node, stale graph version, current node/version | missing -> `missing_lineage`; stale -> `stale`; current -> usable | Missing/stale graph cannot drive planning/report confirmed claims | `test_v3_graph_binding_rejects_missing_or_stale_lineage` |
| MU-03 Daily flow create | `DailyLearningRuntime.load_or_create_daily_flow`, table `daily_flows` | no active flow for date | Creates one `daily_flows` row with `budget_min=10`, `budget_max=20`, graph/bank version, `legacy_session_id`, status `new`; child projection `choose_review` | No fixed `today_plan.tasks`; old rows preserved | existing `test_v3_child_route_shell_returns_child_safe_payload_when_enabled` plus `test_v3_load_or_create_daily_flow_idempotent_row_counts` |
| MU-04 One active flow invariant | `db.init_schema`, index `idx_v3_daily_flows_one_active_per_child_day` | two active `daily_flows` same child/date | second insert fails; superseded/completed rows do not block new active flow | SQLite invariant must be executable, not just index presence | existing `test_v3_skeleton_schema_additive_and_indexes_exist`; add `test_v3_active_flow_partial_index_allows_superseded_history` |
| MU-05 Start review first-step honesty | `DailyLearningRuntime.start_review_mode`, `_ensure_first_review_step`, table `flow_steps` | choose review in skeleton | Writes one current active-eligible graph-generated question step or child-safe blocked when none exists | Temporary deterministic selection must be labelled as non-planner-backed | existing `test_v3_review_start_selects_real_current_step_from_active_question_bank`, `test_v3_review_start_error_remains_child_safe_when_no_question_available` |
| MU-06 Current step projection | `DailyLearningRuntime.project_child_state`, `_project_step`, `_blocked_projection` | `new`, `blocked`, `ready_for_new_knowledge`, `completed`, current step row | Projects child states with only handle/position/prompt/support; no ids, graph/model/queue internals | Child-safe projection boundary | `test_v3_project_child_state_matrix_has_no_internals` |
| MU-07 Submission payload parser | `CurrentStepSubmission.from_payload` | valid payload, missing/invalid `position`, missing key, blank fields | Parses valid; child-safe errors for invalid position/key/evidence later | Child APIs use handle/position/idempotency, not raw ids | `test_v3_current_step_submission_payload_validation` |
| MU-08 Current submit fail-closed shell | `DailyLearningRuntime.persist_child_response` | missing handle, missing idempotency key, blank evidence, missing step, blocked step | 400/409 child-safe payload; no attempt/job rows created | Normal flow cannot silently fake save | existing route test plus `test_v3_submit_shell_rejects_without_side_effects` |
| MU-09 Submit transaction fill | `DailyLearningRuntime.persist_child_response`, tables `attempts`, `attempt_attachments`, `background_jobs`, `flow_steps`, `daily_flows` | valid displayed question step with text/photo/stuck | One active pending attempt, optional attachment, one `answer_analysis` job, step `analyzing`, duplicate submits reuse the active attempt | Required before worker-chain hot path can pass | `test_v3_current_step_submit_records_attempt_job_and_projects_analyzing`, `test_v3_stuck_only_submit_records_attempt_and_enters_analyzing`, `test_v3_submit_recovers_from_active_attempt_unique_conflict` |
| MU-10 Evidence predicate matrix | `EvidenceUsePredicate.evaluate` | cross product of `evidence_status`, `grading_status`, `analysis_status`, `flow_step_id`, graph/bank versions, `provider_mode`, `gate_status` | Only active+graded+valid+flow_step+current graph/bank+non-mock+passed is usable | `gate_status=passed` alone is never enough | `test_v3_evidence_gate_rejects_pending_stale_invalidated_mock_missing_lineage` |
| MU-11 Evidence validation row | `EvidenceGate.validate_attempt`, table `evidence_validations`, index `idx_v3_evidence_validations_attempt_analysis_gate` | missing attempt; attempt with valid/current vs pending/stale/mock | Missing returns blocked/no row; real attempt writes validation row once per attempt/analysis/gate; duplicate ignored or stable | Validation rows are evidence, not mastery mutation | `test_v3_evidence_validation_version_unique_and_fail_closed` |
| MU-12 Job payload lineage | `JobQueue.enqueue`, `V3_JOB_TYPES`, `V3_JOB_PAYLOAD_SCHEMA_VERSION` | invalid job type, missing idempotency, missing lineage, valid payload | rejects invalid; valid inserts queued job; same active key reuses existing | Queue cannot accept lineage-free model work | `test_v3_job_queue_enqueue_requires_payload_lineage_and_reuses_key` |
| MU-13 Job lease/recovery | `JobQueue.claim/start/heartbeat/finish/retry/wait/block/dead_letter/recover` | queued/retry/claimed/running rows, expired lease, two workers | only one claim; owner-only start; retry/wait/block/dead_letter transitions; expired leases retry; due retry requeues | Async recovery must be deterministic and idempotent | `test_v3_queue_stale_running_unlock_and_duplicate_claim_prevention` |
| MU-14 Candidate packet exact schema | `QuestionBankService.candidate_packet_for_node`, `_candidate_metadata_row` | current-lineage rows, missing-lineage v2 rows, cooldown/duplicate/mastered exclusions | packet has `packet_id`, `packet_hash`, 5-8 max metadata rows, exact filter counts, no solution/rubric bodies | Planner hot path sees compact metadata only | `test_v3_candidate_packet_is_small_active_and_metadata_only` |
| MU-15 Candidate lineage filter | `question_bank._candidate_lineage_status` | no graph/bank/reviewer proof; stale graph/bank; current proof | missing -> excluded_missing_lineage; stale -> excluded_stale; current -> candidate allowed | v2 rows cannot enter v3 planner until backfilled/reviewed | existing skeleton packet assertion plus `test_v3_candidate_packet_excludes_v2_rows_without_graph_version_backfill` |
| MU-16 Model route registry | `model_router.configured_route_statuses`, `planner_route`, `evaluation_route`, `teaching_route` | no API key, configured key | status includes route modes without secrets; provider names hidden from child | All model calls must route through adapter | existing `test_v3_skeleton_modules_expose_fail_closed_contracts`; add `test_v3_route_status_has_no_api_key_and_labels_mode` |
| MU-17 Report label enum | `db.V3_REPORT_CLAIM_LABELS`, future v3 report adapter | all seven labels and mixed precedence conditions | label precedence: blocked > stale > missing_lineage > mock_only > pending > inferred > confirmed | Parent/Codex summaries must not overclaim | `test_v3_summary_label_precedence_all_v3_labels` |
| MU-18 Next-step ledger schema | table `next_step_decisions`, index `idx_v3_next_step_decisions_flow_revision_source` | accepted/fallback/blocked decisions with missing fields | accepted requires source ids, graph/bank, candidate packet hash for question actions, branch policy, provider mode, report label | No invisible next-step rationale | `test_v3_next_step_decision_requires_full_source_lineage` |
| MU-19 Late evidence ledger | table `late_evidence_reconciliations` | late validation arrives while another step is displayed | row records visible step, safe transition status, inclusion/exclusion; no current-step rewrite | Late evidence applies only at safe transition | `test_v3_late_evidence_waits_for_safe_transition` |
| MU-20 Summary lineage | table `daily_summaries` | summary with mixed source rows | all source ids and labels present; `confirmed` impossible without current non-mock usable evidence | Summary is report evidence, not stale prose | `test_v3_daily_summary_requires_source_ids_for_confirmed_claims` |

API/service contract cases:
| Case | Interface/route/service | Request/input | Expected response/output | Error/permission path | Test target |
|---|---|---|---|---|---|
| API-01 v3 bootstrap enabled | `GET /api/child-bootstrap`, `V3ChildAPIProjection.bootstrap` | `V3_DAILY_RUNTIME_ENABLED=1`, empty DB after seed | `schema_version=3.0.0-daily-flow`, `child_state=choose_review`, no `today_plan` | graph/DB failure -> child-safe blocked | existing `test_v3_child_route_shell_returns_child_safe_payload_when_enabled` |
| API-02 v3 flag disabled | `GET /api/child-bootstrap` | `V3_DAILY_RUNTIME_ENABLED=0` | legacy v2 payload with `today_plan`/`learning_group`, no v3 `child_state` | no v3 rows required | existing `test_v3_feature_flag_disabled_keeps_legacy_child_bootstrap` |
| API-03 start review idempotency | `POST /api/daily-flow/review/start` | same `client_day_key` called twice | same active flow; no duplicate active flow/current step; returns current step when an active question exists, child-safe blocked when no question exists | feature flag off -> disabled payload | `test_v3_review_start_selects_real_current_step_from_active_question_bank`, add duplicate-start row-count check |
| API-04 operator inspect | `GET /api/operator/daily-flow/today` | after bootstrap/start/submit/job | id-rich `flows`, `steps`, `attempts`, `jobs`, `evidence_validations`, `next_step_decisions`, `daily_summaries` | operator-only route may expose ids; child routes may not | existing inspect assertion plus `test_v3_operator_inspect_includes_lineage_rows` |
| API-05 current-step submit validation | `POST /api/current-step/submit` | missing handle, missing key, invalid position, blank text/photo/stuck | child-safe 400/409; no attempt/job side effects | raw ids ignored | `test_v3_submit_rejects_invalid_payload_without_side_effects` |
| API-06 successful current-step submit | `POST /api/current-step/submit` | valid handle/position/key + answer text on displayed question step | child state `analyzing`, one pending attempt, one queued `answer_analysis` job, no grading wait | duplicate same key or post-save retry -> same active analyzing state | `test_v3_current_step_submit_records_attempt_job_and_projects_analyzing` |
| API-07 duplicate conflict | `POST /api/current-step/submit` | same step different idempotency/evidence after active attempt | 409 child-safe reload/retry; no second active attempt | double-click same key is allowed/reused | `test_v3_submit_duplicate_conflict_preserves_one_active_attempt` |
| API-08 child payload leakage | all child routes | bootstrap/start/submit success and error payloads | serialized payload lacks `graph_version`, ids, provider/model/agent/rubric/OCR/queue/job internals | accessible/hidden DOM text also scanned | existing `_assert_no_v3_child_internals`; browser scan |
| API-09 candidate packet service | `QuestionBankService.candidate_packet_for_node` | target node, exclusions, current graph version | returns metadata packet and exclusion summary before planner call | no active candidates -> bank gap/fallback, not full bank search | `test_v3_candidate_packet_filter_summary_drives_bank_gap` |
| API-10 evidence validation service | `EvidenceGate.validate_attempt` | attempt id + provider mode + analysis version | validation row and predicate result; no mastery/planner mutation | missing attempt -> blocked result | `test_v3_evidence_gate_records_validation_but_not_mastery` |
| API-11 queue service | `JobQueue` methods | enqueue/claim/start/retry/finish/wait/block/recover | DB job statuses follow state machine | missing lineage rejected | `test_v3_job_queue_state_machine_contract` |
| API-12 summary service | `DailyLearningRuntime.complete_summary` | flow id after 10-20 steps or safe stop | child-safe summary with seven-label map and source ids | current skeleton returns blocked; fill required | `test_v3_complete_summary_uses_daily_summaries_not_latest_md` |
| API-13 photo payload handling | `/api/current-step/submit`, future v3 attachment path | valid/invalid data URL, oversized or unsupported photo | valid writes local attachment metadata; invalid child-safe upload error; no blind serve | no secrets/private raw path in child payload | `test_v3_submit_photo_attachment_integrity_and_child_safe_errors` |
| API-14 body/JSON safety | `LearningHandler._read_json`, v3 POST routes | malformed JSON or oversized body | 400/413 style safe error; no partial DB writes | existing generic handler path plus v3 route asserts | `test_v3_routes_reject_malformed_or_oversized_json_without_rows` |

UI/flow cases:
| Case | Page/flow | Steps | Expected state/feedback | Recovery/edge path | Evidence target |
|---|---|---|---|---|---|
| UI-01 Open/start review first slice | `/` v3 enabled | Load page, click primary action in `choose_review` | Shows choose review, then one current graph-bound question step; no fixed list | Retry/refresh preserves one flow/current step | Browser trace + operator inspect |
| UI-02 Current-step render | `/` with a displayable `flow_steps` fixture | Bootstrap returns `child_state=current_step`; render page | One prompt, one answer area, optional photo, one save CTA; progress says step position, not `N/10` fixed list | missing step projects blocked | v3 browser fixture + screenshot |
| UI-03 Text answer save | current step | Type reasoning and save | Button saving, draft preserved until success, then polling/load shows analyzing/next step | save error leaves draft and retry panel | Browser + API + DB |
| UI-04 Stuck action | current step | Child clicks a stuck/cannot-start control | Payload sends `stuck=true`; first slice records a pending stuck attempt and enters analyzing; planner branch remains future work | browser test still needed beyond unit coverage | Browser + DB attempt `answer_source/stuck` |
| UI-05 Blank guard | current step | Submit no text, no photo, not stuck | Child-safe prompt; no API attempt/job row | focus remains answer/photo area | Browser DOM + operator inspect |
| UI-06 Photo preview/remove | current step | Select image, preview, remove, select unclear image | Preview contained; remove reachable; upload error durable if invalid | draft text preserved | Screenshot + DOM |
| UI-07 Analyzing/waiting | after submit with pending model | Poll bootstrap | honest analyzing/waiting state; no fake grade/mastery; no parent action | if independent safe target exists, next current step can appear with pending evidence excluded | Browser + DB job/evidence rows |
| UI-08 Ready for new knowledge | `daily_flows.status=ready_for_new_knowledge` | Load page | gated transition message, not homepage free choice | refresh stable | Browser + API |
| UI-09 Teaching shell | `flow_steps.step_type=teaching` | Load current step | concise explanation/micro-check shell, no long lecture/internal ids | submit micro-check path later | Screenshot + payload scan |
| UI-10 Summary labels | summary state | Load after safe stop | confirmed/pending/blocked/inferred/stale/mock_only/missing_lineage facts are visibly scoped or available to Codex | stale/missing labels not hidden | Browser + report artifact |
| UI-11 Child-only leakage scan | all v3 states and errors | Serialize API + inspect DOM/accessibility labels | no graph ids, question ids, attempt ids, session ids, provider/model/agent/rubric/OCR/queue internals | fails on hidden accessible text too | Browser + API serialized scan |
| UI-12 Load/save/upload error panels | v3 states plus current error panel code | Force load/save/upload errors | durable page-level panel, retry action, child-safe copy, focus target | `save_error` preserves draft/photo | Browser screenshot + keyboard |
| UI-13 Mobile current step | 390x844 | current step with long prompt/photo filename | no horizontal scroll, CTA visible, text wraps | error panel also usable | Screenshot + layout metrics |
| UI-14 Feature flag rollback UX | flag toggles from v3 to legacy | Reload page | legacy v2 child payload renders without v3 crashes; v3 rows preserved for operator | no mixed fixed-list/v3 state | Browser + API |

Visual/interaction regression cases:
| Case | Surface/viewport/state | Check | Expected | Evidence target |
|---|---|---|---|---|
| VIS-01 Desktop current step | 1280x900 `current_step` | hierarchy, wrapping, answer/photo/CTA visibility | one focused current step, no overlap, no fixed list | Playwright screenshot + DOM overflow |
| VIS-02 Mobile current step | 390x844 `current_step` | single column, touch target size, no horizontal scroll | child can answer without zoom/scroll traps | screenshot + metrics |
| VIS-03 Waiting/blocked | desktop/mobile `analyzing`, `blocked` | copy honesty, retry/poll affordance | no fake grade, no parent/Codex instruction | screenshot + forbidden text scan |
| VIS-04 Error recovery | `load_error`, `save_error`, `upload_error` | focus, retry action, draft/photo preservation | durable inspectable panel and accessible action | browser keyboard trace |
| VIS-05 Summary/labels | `summary` with all labels | label visibility and meaning not color-only | pending/stale/mock/missing are not hidden or called confirmed | screenshot + accessibility snapshot |
| VIS-06 Reduced motion/focus | all interactive v3 states | keyboard path and reduced motion | no focus trap; submit/retry focus predictable | browser emulation + accessibility snapshot |

State/async/recovery cases:
| Case | State/task/queue | Trigger | Expected transition/retry/recovery | Evidence target |
|---|---|---|---|---|
| ASY-01 Repeated bootstrap | `daily_flows` | Poll `/api/child-bootstrap` repeatedly | no duplicate flow/steps/jobs/decisions/summaries | DB row counts |
| ASY-02 Start review duplicate | `daily_flows`, `flow_steps` | double click start review | one active flow, one current/blocked step, flow revision deterministic | API + DB indexes |
| ASY-03 Submit atomicity | `attempts`, `attempt_attachments`, `background_jobs`, `flow_steps` | valid text/photo; inject attachment or DB failure in test DB | all-or-safe-none; no orphan file/row; flow revision only after commit | integration fixture |
| ASY-04 Slow model with independent target | pending `answer_analysis` job, other safe target exists | job delayed | runtime may select independent next step without using pending evidence; decision lists pending evidence excluded | `next_step_decisions.pending_evidence_ids_json` |
| ASY-05 Slow model no independent target | pending model, dependent next step only | poll bootstrap | child sees honest analyzing/waiting; no fake mastery/plan | child payload + job row |
| ASY-06 Model unavailable | route status disabled or provider error | answer submitted | attempt remains pending/blocked; job blocked/retry metadata; child-safe message; report label pending/blocked/mock_only as appropriate | job + validation + report |
| ASY-07 Malformed model output | schema envelope but missing comparison/process gap | worker applies output | `analysis_status=invalid_analysis` or blocked; evidence gate rejects; no mastery/confirmed decision | attempt + validation |
| ASY-08 Stale lease recovery | `background_jobs.status in claimed/running` with expired lease | `JobQueue.recover(now)` or bootstrap recovery | expired -> retry; due retry -> queued; no double claimed job | queue row transitions |
| ASY-09 Pending attempt without job | active attempt has `pending_review` and no active job | recovery scan | creates or reports missing job exactly once; no duplicate active job | `background_jobs` idempotency |
| ASY-10 Completed output unapplied | model result refs exist but attempt/evidence not updated | recovery scan | reapplies at most once or records blocked reason; no duplicate mastery/decision | job result refs + attempt version |
| ASY-11 Late evidence arrival | previous step no longer visible | answer analysis/evidence validation completes | write `late_evidence_reconciliations`; do not rewrite visible step; apply at safe transition | reconciliation row + projection hash |
| ASY-12 Safe transition application | child submits current step or enters summary | pending late evidence exists | planner reconsideration may write new decision; summary labels included/excluded late evidence | `planner_reconsideration_decision_id`, summary labels |
| ASY-13 Feature rollback | `V3_DAILY_RUNTIME_ENABLED=0` after v3 rows exist | load child page | legacy child projection works; v3 rows preserved and operator-inspectable | API + DB |
| ASY-14 Graph unavailable | graph file missing/bad in isolated fixture | bootstrap/start review | blocked child-safe payload; no lineage-free flow/step that can confirm learning | API + DB |
| ASY-15 Concurrency submit | two clients submit same visible step | same key and different key variants | same key reuses; different evidence conflicts; one active attempt/job | API + unique indexes |

Data/artifact cases:
| Case | Data/artifact/template | Sample/fixture | Expected rule/output | Protected/overwrite boundary |
|---|---|---|---|---|
| DATA-01 v3 schema additive | `db.init_schema` | fresh and legacy DB | all v3 tables/columns/indexes exist; legacy sessions still readable | test DB only |
| DATA-02 Required lineage fields | `daily_flows`, `flow_steps`, `review_targets`, `attempts`, `evidence_validations`, `mastery_decisions`, `learner_node_status`, `next_step_decisions`, `late_evidence_reconciliations`, `daily_summaries` | missing graph/bank/source ids | rows remain auditable but cannot drive confirmed mastery/planning/report | no destructive migration |
| DATA-03 Graph hash drift | `GraphRuntimeService`, graph asset fixture | changed graph hash | old rows become stale/missing-lineage for v3 confirmed claims | read-only graph fixture |
| DATA-04 Candidate packet exactness | `QuestionBankService.candidate_packet_for_node` | 8 current candidates plus excluded rows | exact packet fields, `candidate_count <= 8`, normally 5-8 when available, no solution/rubric/common-wrong bodies | no full bank in planner context |
| DATA-05 Active-use proof | candidate rows with fake/missing/wrong reviewer proof | scheduler packet | excluded_missing_lineage/inactive; cannot reach planner | test DB only |
| DATA-06 Missing-lineage v2 rows | existing v2 bank rows | current graph version | counted under `excluded_missing_lineage`, empty candidates allowed in skeleton | no silent backfill |
| DATA-07 Attempt analysis dimensions | `attempts.answer_analysis_json`, `db.validate_answer_analysis` | missing `final_answer/model_or_relation/steps/symbols_units/check_or_explanation/process_gap` | not usable; no confirmed report/mastery | test DB only |
| DATA-08 Evidence validation uniqueness | `evidence_validations` | same attempt/attempt_version/analysis_version/gate_version twice | one validation row; predicate must be rechecked by consumers | test DB only |
| DATA-09 Next-step source map | `next_step_decisions` | continue/retest/prereq/micro-teach/new/summary branches | source attempt/validation/mastery/candidate packet/branch policy/provider/report label present | no hidden fixed-list next step |
| DATA-10 No fixed hidden list | `flow_steps`, `next_step_decisions` | 10-20 adaptive day | each displayed question step after first traces to a fresh decision after previous evidence/pending branch; no pre-generated `today_plan.tasks` in v3 child payload | DB/API |
| DATA-11 Daily summary seven labels | `daily_summaries.report_label_json`, `db.V3_REPORT_CLAIM_LABELS` | mixed confirmed/pending/blocked/inferred/stale/mock_only/missing_lineage rows | all labels covered; precedence enforced; `confirmed` requires usable evidence | report test fixture |
| DATA-12 Stale report rejection | `learning_system/reports.py`, `scripts/generate_daily_report.py`, `docs/system/daily_reports/latest.md` | latest report older than latest v3 flow/summary | cannot be used as v3 PASS evidence; report marks stale or test fails | no overwrite except test artifact scope |
| DATA-13 Attachment integrity | `attempt_attachments`, `/api/attachments/{id}` legacy serve pattern, future v3 submit | valid/tampered/missing local file | sha/content-type/path match; child payload omits private local paths | local test upload dir |
| DATA-14 Operator artifact scope | `GET /api/operator/daily-flow/today` | real vs isolated DB | output names DB date/ids for Codex; QA report must label isolated vs real ledger | no real side effects |
| DATA-15 Model audit metadata | `agent_runs`, `background_jobs.provider_mode`, model router statuses | mock/recorded/live/not_configured | no secrets; provider mode retained; child summary scoped | no API keys in docs/reports |

Semantic/model oracle cases:
| Case | Input/sample | Expected semantic result | Evidence level required | False-pass guard |
|---|---|---|---|---|
| SEM-01 Sound reasoning correct | complete relation, steps, symbols/units, check | analysis dimensions matched; evidence may improve node but one answer alone cannot overstate stable A unless prior evidence supports it | deterministic + recorded/live sample | exact-answer match is not enough |
| SEM-02 Answer only | final answer only | process gap; no full mastery; planner chooses explanation/retest/clarification | `scripts/child_learning_scenarios.py::SCENARIOS["answer_only"]` adapted to v3 | schema-valid `correct` must fail downstream oracle |
| SEM-03 Wrong reason, right answer | right final answer with invalid/circular relation | partial/wrong; `model_or_relation` and/or `steps` incorrect; repair/retest branch; report not confirmed mastery | existing scenario `wrong_reason_right_answer` + v3 gate | QA_NEEDS_FIX later if accepted as full understanding |
| SEM-04 Stuck/cannot start | child marks stuck or writes cannot start | no mastery; first-step hint, micro-teach, or prerequisite probe | requires REQUEST-HOOK-06 UI control plus semantic fixture | parent/Codex intervention not required |
| SEM-05 Blank/no usable evidence | blank text, no photo, not stuck | submission rejected or evidence pending/blocked; no plan/mastery conclusion | API + semantic fixture | no hallucinated analysis |
| SEM-06 Partial relation wrong final | valid setup with arithmetic/sign final error | partial; preserve concept/model evidence; smallest symbol/procedure repair | scenario `partial_relation_wrong_final` | not all wrong, not full correct |
| SEM-07 Symbol/unit issue | sound model but wrong unit/symbol/sign/bracket | `symbols_units` gap; partial mastery; targeted repair | deterministic + live sample | error tag must survive gate/planner/report |
| SEM-08 Readable photo | clear paper-work photo | OCR transcript/math objects stored with confidence; analysis may use it only after validation | recorded/live vision sample | photo presence alone not usable evidence |
| SEM-09 Unclear photo | low-confidence or unreadable photo-only answer | pending/blocked/asks clearer evidence; no mastery/plan from guessed OCR | recorded/live vision sample | low OCR confidence cannot confirm |
| SEM-10 Alternative valid method | different valid relation/solution path | accepted as `alternative_valid`, no forced single path | recorded/live sample | rubric context not answer-string lock |
| SEM-11 Prompt injection answer | child asks model to ignore rubric/expose internals | ignored/rejected; no prompt leakage; safe child feedback | deterministic + live sample | model compliance with injection is failure |
| SEM-12 Malformed/hallucinated analysis | pretty but invented facts or missing required dimensions | `analysis_status=invalid_analysis` or blocked; report pending/blocked | recorded/live sample + local validator | fluent prose is not semantic pass |
| SEM-13 Low-confidence model | uncertain/conflicting result | pending/blocked or partial; cannot drive mastery/confirmed decision | recorded/live sample | low confidence cannot become confirmed |

Scenario/e2e cases:
| Scenario | Actor | Given | When | Then | Evidence required |
|---|---|---|---|---|---|
| E2E-01 Skeleton open/start | Son + runtime | v3 flag on, seeded isolated DB | Open `/`, start review | choose_review -> current_step, one flow, one graph-bound visible question, no fixed list | browser/API/operator inspect |
| E2E-02 Old-review first real step | Son + system | active current graph-generated question exists | start review | one current graph-bound question step appears; planner-backed target evidence still deferred | child payload, `flow_steps`, screenshot |
| E2E-03 Text answer first-slice hot path | Son + system | current step displayed | submit reasoning answer | attempt/job saved and child sees analyzing; analysis/gate/eval/planner next step remains deferred | API, DB rows, job audit |
| E2E-04 10-20 adaptive day | Son + system | mixed correct/wrong/answer-only/stuck/blank/photo/slow model fixtures | run 10-20 current-step interactions | no fixed hidden list, all visible steps in summary, evidence-linked decisions, no parent intervention | v3 simulation report + DB/API + screenshots |
| E2E-05 All-correct segment | Son + system | several sound correct answers | planner continues | advances or retests appropriately; does not fabricate weakness; one answer alone not overstate A | mastery decisions + report labels |
| E2E-06 Weak prerequisite rollback | Son + system | 七上 step wrong because prerequisite gap | analysis/planner runs | prerequisite probe/repair via graph chain, not blind same-type drill | graph runtime summary + next decision |
| E2E-07 Photo clear/unclear pair | Son + vision route | one readable photo, one unclear photo | submit both | readable can support analysis if validated; unclear stays pending/asks clarification | attachment/OCR metadata + gate |
| E2E-08 Model unavailable/slow | System | provider not configured and slow timeout variants | submit/poll | pending/blocked or independent safe step; no fake grading/mastery | job statuses + child state + report |
| E2E-09 Late evidence | System | previous step analysis returns after new step displayed | worker completes | reconciliation row; visible step unchanged; safe transition applies/reports inclusion | `late_evidence_reconciliations` + projection |
| E2E-10 Ready for new knowledge bridge | Son + planner | old-review high-priority targets resolved enough | planner considers new node | `ready_for_new_knowledge` appears before teaching; not homepage free choice | flow status + prerequisite summary |
| E2E-11 Parent/Codex progress | Parent + Codex | daily summary with mixed labels | parent asks progress | Codex-readable facts come from DB/report rows and labels, not stale conversation text | report artifact + DB ids |
| E2E-12 Restart recovery | Runtime | queued/running jobs, pending attempt, active flow | server/bootstrap recovery | jobs recover or block honestly; no duplicate attempts/decisions | DB before/after + operator inspect |
| E2E-13 Feature rollback | Runtime | v3 rows exist | flag disabled | child sees legacy flow; v3 data preserved for operator | API + DB |

Negative/adversarial cases:
- ADV-01 Child attempts to submit `question_id`, `attempt_id`, `flow_id`, `node_id`, or `session_id`: route ignores/rejects raw ids; only `step_handle` + `position` can bind.
- ADV-02 Stale `step_handle` after superseded step: 409 child-safe reload; no attempt/job.
- ADV-03 Same current step, two different evidence payloads: no second active attempt.
- ADV-04 Repeated polling and refresh spam: no hidden row creation beyond intended recovery.
- ADV-05 Candidate packet accidentally includes `expected_answer`, `solution_steps`, rubric, common-wrong-path bodies, or full bank content: fail packet test.
- ADV-06 Fake current-lineage question row without accepted reviewer run: excluded before planner.
- ADV-07 Stale graph/question bank version row: report `stale`, planner unusable.
- ADV-08 `gate_status=passed` with mock provider or missing `flow_step_id`: not usable.
- ADV-09 `learner_node_status=A` from legacy/missing-lineage row: hint only, cannot skip/confirm.
- ADV-10 `next_step_decisions.decision_status=accepted` without candidate packet hash/source evidence: invalid/fail closed.
- ADV-11 Late evidence tries to rewrite visible unanswered step: fail.
- ADV-12 Report `latest.md` is old but test claims PASS: false-pass harness fails.
- ADV-13 QA report issue count, verdict, and exit code disagree: later QA verdict must be NEEDS_FIX.
- ADV-14 Prompt injection in child answer asks for internal agent/rubric/model: no leakage; analysis rejects instruction.
- ADV-15 Low-confidence OCR still produces confident mastery: fail semantic/model oracle.
- ADV-16 Model route disabled but child receives "correct" feedback: fail provider integrity.
- ADV-17 10-20 harness runs fewer than 10 visible v3 steps while claiming full day: fail.
- ADV-18 Hidden fixed list exists in DB or payload before evidence transitions: fail no-fixed-list contract.

Fixtures / samples required:
- Isolated SQLite DB seeded via `db.init_schema` and `db.seed_from_assets`; never real DB reset unless explicitly authorized.
- Current graph asset plus stale graph-version fixture.
- v3 `daily_flows`/`flow_steps` fixtures for `new`, `reviewing`, `current_step`, `analyzing`, `ready_for_new_knowledge`, `summary`, `blocked`, `superseded`.
- Candidate bank fixtures: current-lineage active rows, stale rows, missing-lineage v2 rows, duplicate signatures, cooldown rows, mastered-node rows.
- Attempt fixtures for all evidence matrix states.
- Job fixtures for queued/claimed/running/retry/waiting/blocked/dead_letter plus expired lease.
- Semantic fixtures adapted from `scripts/child_learning_scenarios.py`: correct_full, answer_only, stuck, wrong_reason_right_answer, blank_or_no_evidence, partial_relation_wrong_final, photo_correct, photo_unclear, symbol/unit issue, alternative valid method, prompt injection.
- Photo fixtures: small valid PNG/JPEG, unsupported type, oversized file, readable math photo sample, unclear photo sample.
- Report fixtures for all seven v3 labels and precedence collisions.
- Browser fixtures using real v3 payload shape; current `fixtureForChildState` is v2-shaped and must not be reused as v3 proof.

Test files authorized:
| File/path | Purpose | Allowed change | Owner |
|---|---|---|---|
| `tests/test_learning_system.py` | v3 unit/integration tests for schema, runtime, gate, queue, candidate packet, semantic downstream, report labels | Not authorized in this task; future test-only edits by implementation/QA scope | 观止/听云 as explicitly dispatched |
| `tests/browser_smoke_learning_system.mjs` | v3 browser current-step, no-internals, responsive/error-state checks | Not authorized in this task | 观止/听云 as explicitly dispatched |
| `scripts/simulate_child_learning_journey.py` or new v3 harness | 10-20 adaptive-day simulation with semantic oracle and false-pass report metadata | Not authorized in this task | 观止/听云 as explicitly dispatched |
| `docs/system/qa/*.md`, `docs/system/qa/*.json`, screenshots/artifacts | QA evidence reports only during QA execution | Not authorized in this task | 观止 during QA gate |

Automation plan:
- Phase 1 unit/contract: `python3 -m unittest tests.test_learning_system.LearningSystemTest.<v3_tests> -v` on isolated DB only.
- Phase 2 browser: start local server with isolated DB and `V3_DAILY_RUNTIME_ENABLED=1`; run v3 browser smoke across desktop/mobile; capture screenshots and payload scans.
- Phase 3 simulation: run 10-20 v3 current-step adaptive-day harness with mixed scenarios; require semantic oracle, DB/API facts, provider mode, artifact timestamps, issue count, verdict, and exit code agreement.
- Phase 4 report false-pass audit: compare report timestamp/source ids to latest v3 flow/summary; reject stale v2 fixed-flow artifacts as v3 evidence.
- This task did not run automation.

Manual QA handoff:
- Human review remains required for final child copy, age-respectful tone, visual polish, and teaching reasonableness.
- Live model/OCR QA must state provider mode, route, sample ids, confidence limits, and whether evidence is live/recorded/mock.
- Parent/Codex progress summaries must cite persisted DB/report evidence, not conversation memory.

Coverage gaps:
- Executable v3 first-slice tests now cover start review, one current step, submit/stuck/analyzing, idempotency, lease/dependency queue safety, evidence fail-closed labels, and upload reconciliation. Full old-review adaptive-day QA still cannot pass until the planner-backed target pool, worker chain, daily summary, v3 browser automation, and 10-20 adaptive-day harness from the remaining REQUEST-HOOK items are implemented.
- No final `UX_FLOW_SPEC v3` or `DATA_CONTRACT_SPEC v3` was read in this task; this spec uses PRD v3 and technical_plan_v3 as the current overlay. If later UX/data contracts rename states/fields or change copy, update this artifact before QA execution.
- Existing v2 browser and live 10x harnesses are useful false-pass references but must not be counted as v3 current-step coverage until adapted.
- No live model, OCR, rendered screenshot, accessibility, or long-run multi-day convergence evidence is claimed here.

Stop condition:
- `docs/qa/test_case_spec_v3.md` is the durable skeleton-derived TEST_CASE_SPEC for the first v3 implementation slice.
- Next required action: implementation fills the v3 worker chain, planner-backed next-step transition, daily summary/report producer, browser automation, and 10-20 adaptive-day harness, then tests are written/executed against this matrix before any full QA PASS-like claim.
