### TEST_CASE_SPEC - 观止（agentKey: `guanzhi`）- 2026-07-11 10:27 CST

Objective:

Prepare the first v5 QA baseline for the single-child math learning loop:
child opens one Web surface, sees one current step, answers by text/photo/stuck,
AI analyzes reasoning, runtime gates evidence, teaching/repair happens, next step
is selected from graph evidence, and the session/report stays truthful.

Scope:

- Child-flow continuity: start/resume, current step, answer, feedback/repair,
  continue, ready-for-new-knowledge, summary.
- Semantic answer-analysis oracle: final answer, method, reasoning, process gap,
  alternatives, confidence, error tags, teaching/next action.
- Photo/OCR: readable, unclear, text-photo conflict, no usable work, OCR guess.
- Async/restart: pending analysis, model failure, queued/running/waiting jobs,
  restart recovery, duplicate submit, stale report.
- Child-safe boundary: no parent/operator/internal ids, graph ids, provider/model,
  queue state, rubrics, Codex instructions, or internal agent wording.
- Report truthfulness: confirmed/weak/partial/pending/blocked/stale/mock-only and
  missing-lineage facts must remain separated.
- Graph rollback: prerequisite probe/repair vs same-structure retest vs
  near-transfer must follow evidence, not drill repetition.

Forbidden scope:

- No production code changes.
- No QA execution in this artifact.
- No live model/browser/local ledger mutation without a separate QA audit plan and
  explicit authorization.
- No QA PASS claim from mock models, happy-path smoke, schema-valid output, or
  generated report formatting alone.

Project boundary overlay:

- Single child, math first, summer bridge from primary prerequisite gaps to Grade
  7 preview; no generic product shell or parent dashboard.
- Every question, answer analysis, teaching action, evaluation, plan, and report
  must bind to graph nodes.
- A Grade 7 failure checks prerequisite chains before same-type drilling.
- Correct final answer with missing/wrong reasoning is not mastery.
- The child page stays simple and child-safe; complex evidence stays in runtime,
  internal records, and Codex-readable reports.
- Mocks prove state/contract stability only. Semantic PASS requires `live_model`
  or an accepted recorded oracle.

Source artifacts:

| Source | Used for | Evidence / path | Missing or stale? |
|---|---|---|---|
| `AGENTS.md` | Project boundary and 观止 QA addendum trigger | project scope lines 5-17; QA strengthening lines 25-28 | no |
| `docs/collaboration/roles/guanzhi.md` | QA authority and `TEST_CASE_SOURCE_READINESS` contract | identity/permissions lines 1-27; source-readiness rules lines 82-95; output template lines 148-237 | no |
| `docs/project-rules/qa-learning-system-addendum.md` | Mandatory QA stance and verdict rules | chain/semantic/teaching/provider split lines 7-25; required scenarios lines 27-40; verdict rules lines 42-48 | no |
| `docs/product/ai_native_math_learning_prd_v5.md` | Product acceptance, oracle fixtures, evidence policy | result summary lines 58-121; AC-01..AC-26 lines 341-370; oracle/photo/day/evidence policy lines 401-505; failure/recovery lines 564-574; readiness lines 648-672 | no for product baseline; not enough for full executable spec alone |
| `docs/product/ai_native_math_learning_product_structure_v5.md` | Modules, state model, data objects, trust labels, acceptance paths | modules lines 63-77; step/state/response modes lines 94-156; trust labels lines 173-194; acceptance paths lines 249-264; downstream artifacts/gate lines 266-292 | no for product structure; still routes UX/engineering |
| `app/local_learning_system/index.html` | Current child surface DOM targets | answer textarea/photo/preview/remove/submit controls lines 58-79 | current UI, not final UX spec |
| `app/local_learning_system/app.js` | Current browser state machine and child-safe client checks | `CHILD_UI_STATES` lines 1-18; forbidden keys lines 20-38; bootstrap line 282; v3 state mapping lines 330-338; current-step submit lines 994-1030 | useful scoped target; exact v5 UX states still pending |
| `learning_system/server.py` | Current HTTP route and child projection targets | routes lines 860-1099; photo parsing line 199; child close projection line 355; child submission line 1281; bootstrap line 1647; pending processing line 1820 | useful scoped target; final v5 route contract still pending |
| `learning_system/daily_runtime.py` | Current daily flow runtime, async worker, projection, planner, summary | `CurrentStepSubmission` line 74; runtime line 116; persist line 239; worker line 394; answer-analysis handler line 598; projection line 459; next decision line 1549; summary line 1693 | strongest current v5-ish implementation map, still labeled v3 internally |
| `learning_system/job_queue.py` | Current async/restart/idempotency target | lineage-required enqueue lines 45-121; claim/start/finish/retry/wait/block/recover lines 130-247 | useful scoped target; final worker policy pending engineering contract |
| `learning_system/evidence_gate.py` | Current trust-label and evidence-use target | predicate line 44; report labels lines 68-110 and 270-298; `EvidenceGate.validate_attempt` lines 116-194 | useful scoped target; semantic oracle samples still required |
| `learning_system/db.py` | Current persistence ledger and uniqueness targets | tables lines 292-809; v5 columns lines 812-883; attempt/photo/report helpers lines 3458-3577 and 3752-3817 | useful scoped target; final storage/report snapshot policy pending |
| `tests/test_learning_system.py` | Existing unit/API coverage hooks | submit/photo/stuck lines 1034-1133; evidence labels lines 1391-1642; async/restart lines 6241-6455; semantic/mastery lines 7668-7869; photo/OCR lines 9946-10044; semantic matrix lines 10150-10201; report lineage lines 8353-8544 | current hooks are v2/v3-era names, not proof of v5 acceptance |
| `tests/browser_smoke_learning_system.mjs` | Existing browser smoke hooks | load/save/upload error panels lines 90-147 and 229-303; child-safe boundary lines 167-220; 10 task completion and child-safe close lines 361-443 | disables/patches model path; not semantic PASS |
| `scripts/child_learning_scenarios.py` | Existing scenario fixture/oracle seed | scenario set lines 68-190; coverage requirement lines 540-563; semantic/photo/plan validators lines 566-741 | missing v5 conflict/OCR hallucination/day pattern expansion |
| `scripts/simulate_child_learning_journey.py` | Existing mock multi-lesson simulation entry | run lesson lines 114-191; report lines 195-265; default `--lessons 10` and mock patches lines 268-324 | mock-only; no live semantic/OCR proof |
| `scripts/live_child_ui_10x.py` | Existing browser-driven live 10x harness | default local targets lines 35-40; scenario answers lines 281-325; lesson audit lines 406-478; report lines 481-549; main browser loop lines 552-705 | mutates local ledger; requires explicit QA authorization |
| `scripts/live_child_acceptance.py` | Existing live acceptance/readiness probe | read-only checks lines 88-184; optional real write lines 187-220; no real submission means NEEDS_FIX lines 260-262 | useful but insufficient alone for v5 semantic/day oracle |

Current implementation target map:

| Layer | Current target | Required QA evidence | False-pass guard |
|---|---|---|---|
| Child DOM | `app/local_learning_system/index.html` controls `#childAnswerRaw`, `#childAnswerPhoto`, `#childPhotoPreview`, `#removeChildPhoto`, `#childSubmitBtn`; state text panels `#childPendingText`, `#childErrorPanel`, `#childHandoffState`, `#childReviewPoints` | screenshot, DOM text scan, focus/keyboard assertions, upload preview/error state | DOM present is not enough; must also match child-safe API payload and DB state |
| Browser state | `app/local_learning_system/app.js` `CHILD_UI_STATES`, `v3UiState`, `/api/child-bootstrap`, `/api/current-step/submit`, legacy `/api/child-submissions`, photo validation | state transition evidence for loading/current_step/analyzing/teaching/summary/blocked/save_error/upload_error | fixture states and patched routes cannot prove runtime behavior |
| Child API | `learning_system/server.py` routes `/api/child-bootstrap`, `/api/current-step/submit`, `/api/child-submissions`, `/api/learning-sessions/{id}/complete`, `/api/attachments/{id}` | request/response payloads, child-safe projection scan, upload validation, idempotent retry | child-safe copy must not hide pending/blocked/model failure truth |
| Daily runtime | `DailyLearningRuntime.load_or_create_daily_flow`, `start_review_mode`, `persist_child_response`, `process_next_background_job`, `_handle_answer_analysis_job`, `_handle_pending_answer_analysis`, `project_child_state`, `_project_step`, `_record_next_step_decision`, `_ensure_daily_summary` | flow/step/attempt/job/validation/decision/summary rows before and after each action | reaching a next step is not PASS unless source evidence and graph reason match |
| Async queue | `JobQueue.enqueue`, `claim`, `start`, `finish`, `retry`, `wait`, `block`, `dead_letter`, `recover` | job lineage fields, status transitions, retry/recover counts, idempotency key uniqueness | retry/recovery PASS must also prove no duplicate attempt, decision, mastery, or summary |
| Evidence gate | `EvidenceUsePredicate.evaluate`, `EvidenceGate.validate_attempt` | `evidence_validations.predicate_result_json`, `gate_status`, `provider_mode`, `report_label` | `mock`/`not_configured`/stale/missing-lineage cannot become confirmed mastery |
| Persistence ledger | DB tables `daily_flows`, `flow_steps`, `attempts`, `attempt_attachments`, `background_jobs`, `agent_runs`, `evidence_validations`, `mastery_decisions`, `learner_node_status`, `next_step_decisions`, `daily_summaries` | row-level source ids and versions for each session step | summary/report cannot use only latest row or omit pending/blocked records |
| Current tests | `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`, `scripts/*child*` | unit/API/browser/script reports plus artifacts | current green result is regression signal only; semantic/model PASS requires live/accepted recorded oracle |

Runtime evidence ledger required per high-risk case:

| Evidence object | Current DB table/field family | Proves | Must be cross-checked with |
|---|---|---|---|
| Daily/session thread | `daily_flows`, `learning_sessions` | active/resumable/summary/blocked state and revision | child bootstrap payload and `flow_steps.current` uniqueness |
| Child-visible action | `flow_steps` | one selected step, graph/question lineage, position, step type | DOM one-action state and planner decision |
| Child answer | `attempts.answer_raw`, `answer_source`, `flow_step_id`, `client_idempotency_key`, `analysis_status` | evidence saved before model analysis and retry idempotency | `background_jobs`, `attempt_attachments`, child pending state |
| Photo evidence | `attempt_attachments`, `attempts.attachment_ids_json`, `review_meta_json.vision` | bytes/hash/source saved; OCR/vision remains auditable | upload UI, MIME/magic-byte validation, analysis confidence |
| Model/analysis run | `agent_runs`, `attempts.answer_analysis_json`, `review_meta_json`, `cause_analysis_json` | provider mode, accepted/pending/error status, comparison/process gap | semantic oracle expected fields and evidence gate |
| Evidence usability | `evidence_validations` | `confirmed`/`pending`/`blocked`/`stale`/`mock_only`/`missing_lineage` split | provider mode, graph/bank versions, attempt lineage |
| Mastery/evaluation | `mastery_decisions`, `learner_node_status` | applied or rejected learning evidence by node/dimension | validation ids and semantic oracle; never pending/mock/stale |
| Next step | `next_step_decisions`, next `flow_steps` | same-structure/transfer/prerequisite/teaching/summary reason | graph rollback oracle and source evidence ids |
| Summary/report | `daily_summaries` and generated reports/query output | all session evidence represented with freshness and trust labels | source step/attempt/validation/decision ids, report timestamp/version |

TEST_CASE_SOURCE_READINESS:

- verdict: `TEST_CASE_SOURCE_READY`
- scoped_baseline_ready: yes.
- implementation_stage_test_spec_ready: yes, for red tests that constrain the v5
  skeleton/runtime implementation.
- final_QA_execution_ready: no. This is not a QA PASS basis until the red tests
  are implemented, production behavior is hardened, and live/recorded semantic
  evidence is executed under a separate QA audit lane.
- prd_quality_gate_checked: yes.
- source_content_quality_ready: yes.
- downstream_guessing_risk: none for the authorized red tests.
- prd_quality_ready: yes.
- product_structure_ready: yes.
- ux_flow_ready: yes for test design. Exact rendered UX PASS remains a later
  清秋/观止 execution gate.
- data_rule_sources_ready: yes via Product Structure v5 plus
  `docs/architecture/engineering_contract_v5.md`.
- technical_plan_ready: yes.
- engineering_contract_ready: yes.
- blueprint_ready: yes.
- skeleton_ready: not applicable for red-test design; current production is the
  intentionally failing target.
- code_runtime_targets_clear: yes for current `DailyLearningRuntime`,
  `JobQueue`, `EvidenceGate`, child APIs, browser shell, and report tests.
- project_boundary_ready: yes.
- resolved_history:
  - The previous draft marked `TEST_CASE_SOURCE_NEEDS_FIX` because UX flow,
    engineering contract, blueprint, and architecture review were not yet
    available.
  - Current sources now include v5 PRD/Product Structure/UX, updated Technical
    Plan, Engineering Contract, Implementation Blueprint, and
    `MSG-20260711-002`.
- missing_or_low_quality_sources: none blocking red tests.
- impact_on_test_case_quality: tests can now name the durable DAG, trust labels,
  queue status semantics, canonical child states, DB rows, and false-pass
  oracles. Live semantic/OCR quality remains a later evidence lane, not a source
  blocker for red tests.
- route_back_to_ruoming: none for this update.

Current authoritative v5 DAG basis:

| Stage | Durable job | Model/agent source | Runtime reducer and DB evidence | Downstream rule |
|---|---|---|---|---|
| 1 | `answer_analysis` | `answer_analysis_agent` with optional OCR evidence | accepted model envelope, `agent_runs`, attempt analysis, deterministic `EvidenceGate`, `evidence_validations` | enqueue `evaluation_update` only if validation passes; clarify/block/summary otherwise |
| 2 | `evaluation_update` | `evaluation_agent` | accepted evaluation envelope, runtime-applied `mastery_decisions` and `learner_node_status` | enqueue `planner_decision` only after accepted evaluation |
| 3 | `planner_decision` | `planner_agent` | bounded candidate packet, exactly one accepted action, `next_step_decisions` | materialize one next state or enqueue `teaching_generation` |
| 4 | `teaching_generation` | `teaching_agent` | child-safe teaching package and lineage | materialize `teaching_repair`, `worked_example`, `clarify_evidence`, or micro-check support |

Controller clarifications applied:

- `evidence_validation` is deterministic and not a normal v5 model job.
- `planner_decision` is enqueued only after accepted evaluation.
- Terminal evaluation failure is handled by runtime blocked/summary; no planner
  job may be created without accepted evaluation.
- v5 idempotency reuses terminal succeeded jobs by the same key/source phase.
- `waiting` is non-runnable and means child/evidence wait only.
- Patched/mock tests must be labeled `mock_only` or accepted `recorded_model`,
  never `live_model`.

Allowed scoped output:

- Durable source-ready `TEST_CASE_SPEC` for implementation-stage red tests.
- No QA execution verdict and no semantic/live PASS claim.

Skeleton pass: not required before red tests; red tests intentionally describe
the skeleton/runtime behavior that does not yet exist.

Engineering contract: ready. Source:
`docs/architecture/engineering_contract_v5.md`.

Implementation blueprint: ready. Source:
`docs/architecture/implementation_blueprint_v5.md`.

Risk classification:

High risk. The product can falsely pass when UI flows complete but semantic
judgment, OCR confidence, prerequisite rollback, async recovery, model honesty,
or report truthfulness is wrong.

Coverage matrix:

| Area | Required coverage | Cases | Gap / reason |
|---|---|---|---|
| Child flow continuity | start/resume, one current step, text/photo/stuck, feedback/repair, continue, summary | CF-01..CF-10 | ready for red tests against canonical v5 states |
| Semantic answer analysis | correct reasoning, answer-only, wrong reason/right answer, alternative method, symbol/unit/procedure error, blank, stuck | SEM-01..SEM-09 | live semantic remains later; recorded/mock red tests must label scope |
| Photo/OCR | readable, unclear, conflict, no usable work, OCR hallucination | OCR-01..OCR-08 | fixture contract ready; live OCR later |
| Async/model/restart | pending, slow model, missing model, low confidence, restart, double submit, stale report | ASY-01..ASY-09 | ready for DAG, retry, lease, waiting red tests |
| DAG/model jobs | answer -> evaluation -> planner -> optional teaching | DAG-01..DAG-10 | new implementation-stage P0 red suite |
| Trust labels | mock_only/recorded/live/not_configured/deterministic separated | TRUST-01..TRUST-05 | mock/patch must never be `live_model` |
| Graph planning/rollback | same-structure, near-transfer, prerequisite probe, rollback depth, no blind drill | GR-01..GR-08 | ready for prerequisite-before-drill red tests |
| Question quality | no low-age filler, no answer-only prompt, graph-bound, reasoning exposing, no fake prior-error claims | QQ-01..QQ-06 | final question-generation changes later; current bank guards remain |
| Child-safe/browser | child-only DOM/API, hidden internals, focus/retry, upload/save/load errors, XSS, responsive | UI-01..UI-12 | ready for canonical v5 browser red expectations |
| Reports/Codex query | confirmed/weak/pending/blocked/stale/mock-only/missing-lineage separation, source ids, freshness | REP-01..REP-10 | ready for phase lineage and summary freshness red tests |
| 10-lesson simulation | real browser plus model/recorded oracle, 10 cycles, 10-20 interactions or safe early stop, day patterns covered | E2E-10X | ready for v5 harness contract shell; final live execution later |

Depth expansion:

| Risk/area | Normal | Boundary | Negative/adversarial | Recovery/interruption | Evidence target |
|---|---|---|---|---|---|
| Semantic judgment | sound answer improves evidence conservatively | answer-only or one strong answer | wrong reasoning marked full correct | low confidence stays pending/blocked | analysis JSON, gate result, evaluation update, next decision |
| Photo/OCR | readable photo yields usable OCR audit | no text + photo only | OCR invents symbols, photo/text conflict | clarify/retry after unclear photo | attachment hash, vision envelope, confidence, analysis lineage |
| Planning | stable evidence selects transfer/new knowledge | unstable but prerequisites stable | weak evidence produces random drill | stale plan after evidence invalidated | next_step_decision, candidate packet, graph chain |
| Async | save returns before model completes | model slow/timeout | model missing but grade fabricated | restart resumes queued/waiting job | DB attempts/jobs, child pending/blocked state |
| Report | summary covers all attempts | mixed confirmed/pending/blocked | stale report treated as current truth | record changes after report | report version, source record ids, freshness label |
| Child safety | one current action shown | load/save/upload error | internal ids/provider leak or XSS | refresh/double submit/retry | DOM/API scan, screenshot, keyboard/focus |

Method/unit cases:

| Case | Source trace | File/symbol | Input/state | Expected | Oracle/rubric | Test target |
|---|---|---|---|---|---|---|
| UNIT-EVIDENCE-01 trust labels reject mock/stale/missing-lineage | PRD AC-25/26; product trust labels | current hook: `tests/test_learning_system.py` evidence gate lines 1391-1642 | graded attempt with mock provider, stale graph/bank, missing lineage, pending status | not usable; report label is `mock_only`/`stale`/`missing_lineage`/`pending`/`blocked` | QA addendum provider integrity | revise against v5 evidence gate symbol after skeleton |
| UNIT-SEM-01 answer-only cannot become full mastery | PRD AC-07; addendum verdict rules | current hooks: lines 10045-10148, 7668-7869 | right final answer, missing/invalid reasoning | partial/unstable; process gap; teaching or retest | semantic oracle | revise against v5 evaluator/gate reducer |
| UNIT-SEM-02 alternative valid method passes | PRD semantic fixture | future v5 answer analysis service | different valid setup/method with sound constraints | accepted as valid method; no false error tag | accepted oracle sample | needs fixture/sample |
| UNIT-OCR-01 OCR usable/unusable boundary | PRD photo fixtures | current hooks: lines 9946-10044 | readable vs low-confidence photo | readable can feed analysis; low confidence stays pending/clarify | OCR confidence and transcript evidence | revise against v5 vision adapter |
| UNIT-PLAN-01 rollback vs retest decision | PRD graph rollback fixtures | current hooks: planner/evaluation around lines 7668-8120 | failed current node with prerequisite unknown/stable/failed | nearest prerequisite probe, same-structure, or transfer according to evidence | graph chain + planner signal | needs v5 planner contract |
| UNIT-REPORT-01 stale/missing-lineage report | PRD AC-25/26 | current hooks: lines 8353-8544 | invalidated attempt/report after record change | report labels lineage issue; stale cannot pass | report truth policy | needs v5 report freshness fields |

API/service contract cases:

| Case | Source trace | Interface/route/service | Request/input | Expected response/output | Error/permission path | Test target |
|---|---|---|---|---|---|---|
| API-CF-01 child bootstrap one current step | PRD AC-01/02; product state model | current `/api/child-bootstrap` hooks | child opens page | exactly one child-safe actionable step or honest blocked/summary | load failure -> child-safe retry | final v5 child projection route |
| API-CF-02 text submit saves before model | PRD AC-03; product Evidence Capture | current `/api/child-submissions`, runtime hooks lines 1034-1083 | text answer with reasoning | attempt persisted, job queued, child sees analyzing/pending | duplicate submit idempotent | final v5 submission route |
| API-CF-03 photo submit saves attachment before OCR | PRD AC-04 | current lines 1084-1112 and browser lines 229-255 | valid image + optional text | attachment bytes/hash saved; OCR untrusted until validation | invalid image no stale preview/file leak | final upload/attachment route |
| API-CF-04 stuck submit drives teach/probe | PRD AC-05 | current lines 1114-1133 | stuck with no answer | stuck evidence saved; no mastery; micro-teach/probe/safe stop | repeated stuck safe summary | final v5 stuck route |
| API-ASY-01 missing model cannot fake grade | PRD AC-18/19 | current hooks lines 6320-6455, 10344-10422 | no key/route, incomplete analysis, low confidence | pending/blocked; no evolution/mastery | recovery after server restart | final model adapter/queue contract |
| API-REP-01 Codex progress query separates labels | PRD AC-25/26 | current reports/API hooks | parent asks via Codex/report | confirmed/weak/pending/blocked/stale/mock-only/missing-lineage separated | stale report explicitly rejected | final report/query contract |

UI/flow cases:

| Case | Source trace | Page/flow | Steps | Expected state/feedback | Recovery/edge path | Evidence target |
|---|---|---|---|---|---|---|
| UI-01 start/resume | PRD scenario and AC-01/02 | child Web surface | open page with active/no active flow | one current action; no worksheet | graph/bank unavailable -> blocked | screenshot + DOM + API payload |
| UI-02 text answer round | AC-03/06/07 | current step question | submit text with reasoning/answer-only | saved, pending/analyzing, then feedback/next step | duplicate submit no duplicate attempt/job | DOM state + DB attempts/jobs |
| UI-03 photo answer round | AC-04/11 | current step photo | upload readable/unclear photo | preview, saved evidence, usable or clarify | invalid file/upload failure preserves draft | screenshot + attachment audit |
| UI-04 stuck round | AC-05 | current step | child clicks stuck | not shamed; smaller step/teaching/probe | repeated stuck safe stop | DOM copy + decision reason |
| UI-05 teaching/micro-check | AC-16 | feedback/teaching state | wrong/partial/stuck evidence | first break explanation and one small action | no mastery by reading only | child projection + teaching record |
| UI-06 ready/new knowledge | AC-15 | checkpoint | review stable enough | continue_new or finish available | unsafe/pending -> summary/blocked | readiness record + page state |
| UI-07 summary | AC-22/25/26 | finish state | close mixed day | child-safe short result; Codex record complete | stale/pending labels visible to Codex | child screenshot + report |

Visual/interaction regression cases:

| Case | Source trace | Surface/viewport/state | Check | Expected | Evidence target |
|---|---|---|---|---|---|
| VIS-01 child-only desktop/mobile | product UX constraints; browser hooks lines 167-220 | child page 390x844 and 1280x900 | DOM text scan, overflow, focus, keyboard path | no internal/parent/operator leakage; usable one-step action | Playwright screenshots + DOM scan |
| VIS-02 error panels | PRD failure/recovery; browser hooks lines 90-147, 229-303 | load/save/upload errors | durable panel, focus, aria-live, retry copy, draft/photo preservation | honest child-safe recovery | screenshots + focus assertions |
| VIS-03 pending/blocked states | PRD AC-18/19 | analyzing/pending/blocked | child sees saved/pending/blocked without fake grade | short honest copy; retry/finish where safe | screenshot + state payload |
| VIS-04 summary/review points | PRD AC-22 | summary | each attempt represented; not only last question | concise child-safe summary, no ids/providers | screenshot + child payload |

State/async/recovery cases:

| Case | Source trace | State/task/queue | Trigger | Expected transition/retry/recovery | Evidence target |
|---|---|---|---|---|---|
| ASY-01 save-before-analysis | PRD AC-03, failure/recovery | attempt/job | submit while model slow | child request returns before model finishes; attempt pending | timestamps + job row |
| ASY-02 restart recovery | PRD AC-23 | queued/running/waiting job | stop server with pending job; restart | job recovered once; no duplicate attempt/decision/summary | before/after DB rows |
| ASY-03 model route missing | PRD AC-19 | model adapter | no key/route | blocked/pending label, no mastery/evolution | child state + report label |
| ASY-04 incomplete analysis | PRD evidence policy | answer analysis | model omits required fields | stays pending/blocked; no `confirmed` | analysis status + gate result |
| ASY-05 low confidence | PRD photo/model policy | answer/OCR analysis | confidence below threshold | clarify or pending/blocked, not mastery | confidence field + decision |
| ASY-06 double submit/refresh | PRD AC-23 | idempotency | same/different client retry | no duplicate attempts/jobs | unique rows + API response |
| ASY-07 stale report | PRD AC-26 | report snapshot | records mutate after report | report marked stale/not current | version/timestamp comparison |

Implementation-stage P0 red tests:

| Test name | Layer | Oracle | Expected DB/status/lineage | False-pass prevention |
|---|---|---|---|---|
| `test_v5_answer_success_enqueues_evaluation_job_without_inline_mastery_or_planner` | integration/unit | Accepted recorded answer-analysis is only stage 1 | `answer_analysis` job `succeeded`; exactly one `evaluation_update` job enqueued with source answer job/agent/validation ids; zero `mastery_decisions`; zero `next_step_decisions`; no new current step/summary from answer stage alone | prevents inline reducer from making mastery/planner look complete |
| `test_v5_evaluation_job_accepts_true_agent_envelope_and_enqueues_planner` | integration/unit | evaluation job consumes passed validation and accepted `evaluation_agent` envelope | `evaluation_update` job `succeeded`; one `agent_runs.evaluation_agent`; one `mastery_decisions`/`learner_node_status` row; exactly one `planner_decision` job enqueued with evaluation run/mastery ids | prevents planner without accepted evaluation and prevents direct mastery from answer job |
| `test_v5_planner_job_uses_bounded_candidate_packet_and_rejects_legacy_10_task_plan` | integration/unit | planner receives 5-8 candidate metadata rows and returns exactly one action | `planner_decision` job stores packet hash/id; exactly one `next_step_decisions` row; legacy output containing `tasks[10]` is rejected/retried/blocked with no materialized 10-task worksheet | prevents legacy fixed planner from satisfying v5 one-step loop |
| `test_v5_teaching_generation_only_for_teaching_action_and_records_lineage` | integration/unit | teaching job exists only after planner action requiring teaching/example/clarify | `teaching_generation` job depends on planner decision; `agent_runs.teaching_agent`; `flow_steps.teaching_repair/worked_example/clarify_evidence` has source planner id, attempt id, validation id, mastery id; no teaching job for transfer/summary action | prevents deterministic hidden teaching with no true-agent lineage |
| `test_v5_mock_recorded_live_trust_labels_never_conflate` | unit/integration | mock, recorded, live, not_configured, deterministic_runtime remain distinct | patched review rows use `mock_only` or `recorded_model`, never `live_model`; `mock_only` cannot pass EvidenceGate or create mastery; recorded may pass only through accepted fixture path | prevents fake semantic PASS |
| `test_v5_malformed_agent_output_retries_then_blocks_without_mastery` | integration/unit | malformed/schema-invalid model output is controlled retry then terminal block | first malformed answer/evaluation/planner/teaching result -> `retry`; after max attempts -> `blocked`; `attempt.analysis_status != valid`; no mastery/current step/summary from malformed data | prevents KeyError/dead_letter or score-only acceptance from becoming learning evidence |
| `test_v5_retry_lease_and_terminal_job_reuse_are_exactly_once` | queue/integration | idempotency reuses active and terminal succeeded jobs for same source phase | duplicate enqueue with same idempotency key reuses terminal job; expired lease recovered once; stale worker finish no-op; exactly one validation/evaluation/planner/summary per source ids/version | prevents duplicate stage outputs after restart |
| `test_v5_waiting_jobs_are_child_wait_only_not_generic_worker_runnable` | queue/unit | `waiting` is not generic-worker runnable | `JobQueue.claim()` never claims `waiting`; waiting job remains inspectable and requires child clarification/reconciler | prevents worker loops from treating child evidence wait as runnable retry |
| `test_v5_wrong_blocking_grade7_evidence_prefers_prerequisite_probe_before_blind_drill` | integration/planner | Grade 7 failure rolls back prerequisite before same-type drill when prerequisite unknown/weak | `next_step_decisions.action='prerequisite_probe'`; `target_node_id` is prerequisite/rollback node; source attempt, validation, evaluation, candidate packet ids present | enforces project boundary from `AGENTS.md` |
| `test_v5_summary_report_phase_lineage_includes_mastery_agent_and_job_refs` | integration/report | sequentially consume recorded-model `answer_analysis -> evaluation_update -> planner_decision`; `budget_min=1` closes with summary | all three durable jobs succeed in order and use `recorded_model`; answer/evaluation/planner agent runs exist; `daily_summaries.operator_summary_json.phase_lineage` retains answer/evaluation/planner job and agent-run keys, optional teaching keys, mastery/next-step ids, and provider modes | prevents a one-worker-call false pass and prevents report truth from being only the answer stage or partial lineage |

Browser implementation-stage red expectations:

| Test area | Layer | Expected | False-pass prevention |
|---|---|---|---|
| canonical states | browser | real `/api/child-bootstrap` emits `start_resume`, `current_step`, `analyzing_pending`, `feedback_teaching`, `clarify_evidence`, `ready_for_new_knowledge`, `blocked`, `summary` only; compatibility aliases are test-scoped only | prevents v3 state names from becoming v5 acceptance |
| real blocked retry | browser/runtime | blocked state offers retry/finish without answer form; retry does not expose queue/job/provider and does not fabricate grade | prevents child-facing fake recovery |
| bounded analyzing terminal path | browser/runtime | analyzing is bounded; terminal model failure becomes blocked/summary with trust label, not endless spinner | prevents pending being counted as success |
| clarify cannot-provide | browser/runtime | clarify page allows clearer text/photo and a child-safe cannot-provide/stuck path; no mastery if child cannot provide evidence | prevents unclear photo loop |
| terminal summary action | browser/runtime | summary action is terminal/rest/start-next-day safe path; no answer form and no internal report labels in child DOM | prevents summary from acting like hidden worksheet |
| forbidden leakage | browser/API | no provider/model/agent/queue/job/attempt/question/flow/rubric/Codex/internal terms in child DOM/API | prevents UI-only pass with API leakage |

V5 10-lesson harness contract:

| Requirement | Contract |
|---|---|
| route family | use `/api/child-bootstrap`, `/api/daily-flow/review/start`, `/api/current-step/submit`, `/api/current-step/continue`, finish/new-knowledge routes; do not use legacy `generated_plans`, `learning_sessions`, `/api/child-submissions`, or `planner.LEARNING_ROUND_TASK_COUNT` |
| lesson meaning | ten session/day cycles through one-current-step adaptive runtime; not ten questions |
| model mode | harness fixtures are `recorded_model` or `mock_only`; never label patched output `live_model`; live model execution is later and explicitly authorized |
| day patterns | correct-only, all-wrong, all-partial, mixed, repeated stuck, readable photo, unclear/conflict/hallucinated photo, model failure/restart, graph rollback |
| required evidence | per lesson: browser state trace, DB attempts/attachments/jobs/agent_runs/validations/mastery/decisions/summaries, trust labels, model mode, no internal child leakage |

Data/artifact cases:

| Case | Source trace | Data/artifact/template | Sample/fixture | Expected rule/output | Protected/overwrite boundary |
|---|---|---|---|---|---|
| DATA-01 graph-bound every learning fact | AGENTS; PRD boundary | step/question/attempt/evaluation/plan/report | any active session | node ids present internally and traceable; hidden from child | child payload strips ids |
| DATA-02 trust vs mastery label split | Product trust labels | evidence_validation/daily_summary | confirmed, pending, blocked, stale, mock-only, missing-lineage | trust labels not mixed with `weak`/`partial`/`stable_for_now` | report/API scan |
| DATA-03 model evidence scope | PRD evidence policy | model transcript/snapshot | `live_model`, `recorded_model`, `mock_only` | semantic PASS only live/accepted recorded; mock labeled | no secrets in docs/logs/screenshots |
| DATA-04 photo artifact integrity | PRD photo fixtures | attachment file/DB | valid, invalid, tampered image | hash/path/content type verified; invalid cleaned | no path traversal/secrets |
| DATA-05 report completeness | PRD summary fields | daily_summary/report markdown/json | mixed day with all evidence types | all steps/evidence/analysis/teaching/evaluation/next decisions listed | stale/missing lineage labels |

Scenario/e2e cases:

| Scenario | Source trace | Actor | Given | When | Then | Evidence required |
|---|---|---|---|---|---|---|
| E2E-01 normal mixed lesson | PRD AC-01..AC-22 | child | current graph-bound review step exists | child completes text/photo/stuck/mixed attempts | summary separates confirmed, weak, pending/blocked; next plan linked | browser trace, DB, report |
| E2E-02 all wrong day | PRD Day-Level Outcome Oracle | child/runtime | multiple wrong attempts | session progresses | system teaches/probes/early-stops; no blind drill | decisions, teaching, graph chain |
| E2E-03 all partial day | PRD Day-Level Outcome Oracle | child/runtime | repeated partial evidence | session closes | partial dimensions recorded; repair/transfer/probe selected | analysis + evaluation |
| E2E-04 correct-only day | QA addendum required scenario | child/runtime | all attempts sound | session closes | no fabricated weakness; still conservative about durable mastery | evaluation + next decision |
| E2E-05 repeated stuck | PRD Day-Level Outcome Oracle | child/runtime | stuck repeats | child asks help | smaller step/teaching/probe/safe summary, no shame/loop | child copy + decisions |
| E2E-06 repeated photo uncertainty | PRD Day-Level Outcome Oracle | child/runtime | unclear photos repeat | system analyzes | clarify/text request or pending/blocked summary, no OCR guess mastery | attachment/OCR/report labels |
| E2E-07 graph rollback | PRD graph rollback fixtures | runtime/planner | Grade 7 node fails | planner selects next | nearest prerequisite probe/teach unless prerequisite stable | graph chain + planner reason |
| E2E-08 model failure honesty | PRD AC-18/19 | child/runtime/Codex | model slow/missing/failing | child submits | saved evidence, pending/blocked state, report cause | job/model metadata + child state |
| E2E-09 restart/double submit | PRD AC-23 | runtime | pending job and repeated submit | restart/refresh/retry | idempotent recovery; no duplicates | DB before/after |
| E2E-10 Codex progress query | PRD AC-25/26 | parent via Codex | mixed records exist | parent asks progress | answer separates evidence labels and freshness; no stale current claim | query/report source ids |

10 次课真实模拟定义:

- "10 次课" means ten independent child learning session/day cycles through the
  child Web surface, not ten isolated API calls.
- Each lesson starts from `/` or child bootstrap, creates/resumes one current
  step, proceeds through child submissions, async analysis, teaching/repair,
  next-step decision, and summary or safe stop.
- A normal lesson targets 10-20 child interactions. A lesson may stop early only
  when product rules make that safer: repeated stuck, repeated unclear photo,
  blocked model/OCR/config, or intensive prerequisite repair.
- The ten lessons together must include these day patterns:
  1. correct-only with no fabricated weakness;
  2. all wrong with teaching/prerequisite/safe stop;
  3. all partial with dimension-specific repair;
  4. mixed confirmed/weak/pending/blocked;
  5. repeated stuck;
  6. readable photo;
  7. unclear or repeated photo uncertainty;
  8. photo/text conflict, no usable work, or OCR hallucination;
  9. slow/missing model plus restart/double-submit recovery;
  10. graph rollback across at least one required prerequisite chain.
- "真实模拟" requires either `live_model` calls or an explicitly accepted
  `recorded_model` oracle for semantic/OCR judgment. A patched evaluator,
  deterministic fake OCR, or disabled model route may only produce `mock_only`
  or state-machine scope evidence.
- Required evidence per lesson: browser trace or screenshot, child-safe DOM/API
  payload, DB attempt/attachment/job rows, answer_analysis/evidence gate output,
  teaching_package, evaluation_update, next_step_decision, report/query facts,
  trust labels, and model mode.
- A `LIVE_CHILD_UI_10X_PASS`-style report is valid only if report verdict, issue
  count, process exit code, DB/API facts, screenshots, semantic oracle, and model
  evidence scope all agree.

Semantic oracle:

| ID | Fixture | Required graph area | Child evidence pattern | Expected oracle result | Must not pass if |
|---|---|---|---|---|---|
| SEM-01 | Correct with reasoning | any current review node | correct final answer plus valid steps/explanation/check | evidence may improve node state conservatively; no durable mastery from one answer | analysis lacks process evidence |
| SEM-02 | Correct answer only | algebra/equation | final answer present, reasoning missing | process gap; no full mastery; retest/ask method | graded as stable/full mastery |
| SEM-03 | Wrong reason, right answer | algebra simplification/equation | final result right by coincidence, invalid transformation | partial/wrong; teach first invalid step | final answer match overrides reasoning |
| SEM-04 | Alternative valid method | equation/word problem | different valid setup/method | accept if constraints/reasoning sound; record alternative | non-canonical method rejected without reason |
| SEM-05 | Symbol/unit/procedure error | geometry/unit/signed number | relation mostly right, sign/unit/bracket/procedure wrong | partial; targeted repair | treated as careless but stable |
| SEM-06 | Blank/unclear | any node | empty/no usable evidence | ask for evidence or block; no mastery | missing answer becomes inferred mastery |
| SEM-07 | Stuck | prerequisite-sensitive node | child cannot start | micro-teach, smaller step, or prerequisite probe | random next drill or shame copy |
| SEM-08 | Schema-valid but reasoning-bad model output | any node | model returns full score but comparison/process_gap contradict | evidence gate downgrades or blocks | score field alone controls mastery |
| SEM-09 | Low confidence model output | any node | confidence below threshold or missing analysis fields | pending/blocked/clarify; no evolution/mastery | low-confidence output updates graph |

Semantic oracle field evidence map:

| Oracle family | Required answer-analysis fields | Required runtime/gate fields | Required next action evidence |
|---|---|---|---|
| Correct with reasoning | `comparison` dimensions all sound; empty/benign `process_gap`; confidence above accepted threshold; no error tags | `analysis_status='valid'`; `evidence_validations.gate_status='passed'`; provider is `live_model` or accepted `recorded_model` | conservative `mastery_decisions`/`learner_node_status` delta and retest/transfer/new-knowledge reason, not durable mastery from one answer |
| Correct answer only | final answer marked right but `method`/`steps`/`check` missing; explicit `process_gap` | validation may pass only as limited evidence; mastery dimension remains partial/unstable | ask for method, same-structure retest, or micro-check |
| Wrong reason, right answer | final answer right; `comparison` or `process_gap` names invalid transformation/relation | gate/evaluation rejects stable mastery even if `score_points` is high | `micro_teach`, `same_structure_retest`, or prerequisite probe targeting first invalid step |
| Alternative valid method | non-canonical method recorded; constraints and reasoning sound | validation passes if lineage/provider/method evidence complete | transfer/retest can proceed without forcing canonical solution |
| Symbol/unit/procedure error | specific sign/unit/bracket/procedure tag; partial comparison | partial/weak evidence only; no stable mastery | targeted repair tied to graph node and error tag |
| Blank/unclear/stuck | missing evidence or stuck status visible in review meta; low/no confidence | pending/blocked/missing evidence; no mastery update | clarify, micro-teach, smaller step, prerequisite probe, or safe summary |
| Low confidence/model incomplete | missing required fields or confidence below threshold | `pending`/`blocked` report label; no graph/evaluation update | clarify/blocked/retry; never confirmed summary |

Photo/OCR oracle:

| ID | Fixture | Evidence | Expected result | Must not pass if |
|---|---|---|---|---|
| OCR-01 | Readable photo | clear handwritten work with enough steps | saved attachment, OCR audit, transcript/math objects, eligible for analysis after validation | photo bypasses answer_analysis |
| OCR-02 | Unclear photo | blurry/cropped/low contrast | ask for clearer photo/text or mark pending/blocked; no mastery | guessed transcript drives mastery |
| OCR-03 | Photo/text conflict | typed answer and photo disagree | conflict flagged; clarify or deterministic runtime rule applied with evidence | system silently picks convenient answer |
| OCR-04 | No usable work | final answer only or unrelated photo | process gap or clarify; no full mastery | photo existence counts as reasoning |
| OCR-05 | OCR hallucination/guess | unsupported symbols/steps invented | low confidence; rejected from mastery | hallucinated content appears as confirmed |
| OCR-06 | Invalid/tampered image | wrong MIME, path traversal, corrupt data | upload error/clean rollback; no stale preview or file leak | invalid file remains attached |

Graph rollback oracle:

| ID | Chain purpose | Graph chain | Failure pattern | Expected next action |
|---|---|---|---|---|
| GR-01 | 去括号到整式 | `M-PRE-DISTRIBUTIVE` -> `M-G7-PARENTHESIS` -> `M-G7-COMBINE-LIKE` -> `M-G7-POLY-ADD-SUB` | sign flips incorrectly after parentheses | prerequisite probe or micro-teach on nearest break, not random整式 drill |
| GR-02 | 等量关系到方程应用 | `M-PRE-QUANTITY-RELATION` -> `M-PRE-EQUATION-BASIC` -> `M-G7-EQUALITY-PROP` -> `M-G7-EQ-SOLVE` -> `M-G7-EQ-WORD` | word problem fails because relation/model is not formed | rollback to relation/equation setup, not arithmetic drill |
| GR-03 | 数轴到有理数运算 | `M-G7-NUMBER-LINE` -> `M-G7-OPPOSITE` -> `M-G7-ABSOLUTE` -> `M-G7-COMPARE` -> `M-G7-RATIONAL-ADD-SUB` | wrong direction/sign or absolute-value comparison | probe number-line/opposite/absolute-value break |
| GR-04 | 单位到几何度量 | `M-PRE-UNIT-CONVERSION` -> `M-G7-LINE-RAY-SEGMENT` -> `M-G7-SEGMENT-MEASURE` -> `M-G7-ANGLE` | relation right but unit/measure meaning breaks result | repair unit or segment/angle representation |

Rollback depth rule:

- Unknown immediate prerequisite evidence -> probe nearest prerequisite first.
- Immediate prerequisite fails -> continue one edge backward until the first
  teachable break or safe summary.
- Prerequisites stable but current structure unstable -> same-structure retest or
  near-transfer, not prerequisite rollback.

Question quality cases:

| ID | Risk | Required test |
|---|---|---|
| QQ-01 | Low-age mechanical drill sneaks in | Reject bare arithmetic/filler unless narrow weakness evidence justifies it |
| QQ-02 | Answer-only prompt hides reasoning | Reject prompts that can pass with final answer only |
| QQ-03 | Graph-unbound or wrong-node task | Reject missing/incorrect graph lineage and semantic node mismatch |
| QQ-04 | Fake prior-error claim | Reject child-facing "you made this mistake" unless source attempt exists |
| QQ-05 | Backend/meta wording leaks | Reject prompt text mentioning agent, generator, rubric, graph id, Codex |
| QQ-06 | Repetitive drill instead of evidence-driven plan | Verify recent-use exclusion, unique semantic core, and reasoned candidate packet |

Report truthfulness cases:

| ID | Situation | Required truth label behavior |
|---|---|---|
| REP-01 | all confirmed/weak mixed | Summary separates node/action evidence, not only last question |
| REP-02 | pending analysis | Pending cannot appear as mastery; child-safe note says work is saved/analyzing |
| REP-03 | blocked model/OCR/config | Blocked cause visible to Codex; child sees safe retry/finish |
| REP-04 | stale report | Report timestamp/source version compared with records; stale cannot be current PASS |
| REP-05 | mock-only run | Report says `mock_only`; semantic/model quality remains unproven |
| REP-06 | missing lineage | Report flags missing lineage; evaluation/planning rejects the evidence |
| REP-07 | all-wrong/all-partial day | Summary names weak/partial dimensions and repair/probe, not "完成得很好" |
| REP-08 | Codex progress query | Parent answer cites source session/step/evidence ids internally and separates labels |

Current test entrypoints and required upgrades:

| Entrypoint | Current value | Cannot prove | Required v5 upgrade |
|---|---|---|---|
| `tests/test_learning_system.py` | Broad unit/API hooks for submit, photo, stuck, evidence gate, async, reports, semantic matrix | final v5 route/schema/UX acceptance; live model semantics | split v5-focused tests after engineering contract; bind to final symbols |
| `tests/browser_smoke_learning_system.mjs` | Browser checks for child-only page, error panels, pending guard, 10 review points, XSS | real semantic/OCR/model quality | add v5 state names from UX spec; use v5 child-safe scan and screenshots |
| `scripts/child_learning_scenarios.py` | Fixture seed for eight semantic scenarios and validators | photo/text conflict, no usable work, OCR hallucination, day patterns | expand to full v5 oracle set; label live/recorded/mock |
| `scripts/simulate_child_learning_journey.py` | 10-lesson state/contract simulation through local HTTP with temp DB | semantic PASS because evaluator/OCR are patched | keep as `mock_only` contract regression; add v5 report labels |
| `scripts/live_child_ui_10x.py` | Browser-driven 10-lesson harness with screenshot/json/report | safe to run without authorization; accepted recorded oracle policy | gate behind QA plan; add conflict/OCR hallucination/all-wrong/all-partial/restart patterns |
| `scripts/live_child_acceptance.py` | Read-only live DB/server/report checks plus optional real submission | full v5 acceptance or semantic coverage | use as preflight; extend to model scope and report freshness proof |

Minimum case-to-entrypoint map for the next v5 revision:

| Case group | Browser/API target | Runtime symbol target | DB evidence target | Semantic/oracle target |
|---|---|---|---|---|
| CF text continuity | `#childAnswerRaw`, `#childSubmitBtn`, `/api/current-step/submit` | `CurrentStepSubmission.from_payload`, `DailyLearningRuntime.persist_child_response`, `project_child_state` | `daily_flows`, `flow_steps`, `attempts`, `background_jobs` | SEM-01, SEM-02, SEM-03 |
| Photo/OCR | `#childAnswerPhoto`, `#childPhotoPreview`, `/api/current-step/submit`, `/api/attachments/{id}` | `_save_answer_photo`, `_handle_answer_analysis_job`, `_handle_pending_answer_analysis` | `attempt_attachments`, `attempts.review_meta_json`, `agent_runs`, `evidence_validations` | OCR-01..OCR-06 |
| Stuck/clarify | stuck support UI, `/api/current-step/submit` with `stuck=true` | `persist_child_response`, `_handle_pending_answer_analysis`, `_create_clarify_step`, `_block_flow` | `attempts.answer_source`, `flow_steps`, `next_step_decisions`, `daily_summaries` | SEM-06, SEM-07, repeated stuck day |
| Async/model failure | child analyzing/blocked state, `/api/child-bootstrap` refresh | `process_next_background_job`, `JobQueue.recover`, `_handle_pending_answer_analysis` | `background_jobs`, `agent_runs`, `attempts.analysis_status`, `evidence_validations` | SEM-08, SEM-09, model evidence policy |
| Evidence/mastery | API/report/query output | `EvidenceUsePredicate.evaluate`, `EvidenceGate.validate_attempt`, `_record_evaluation_update` | `evidence_validations`, `mastery_decisions`, `learner_node_status` | trust-vs-mastery split |
| Planner/rollback | child next step after analysis | `_advance_after_analysis`, `_record_next_step_decision`, `_select_next_review_question` | `next_step_decisions`, next `flow_steps`, candidate packet metadata | GR-01..GR-04 |
| Summary/report | summary child state, Codex/report read | `_ensure_daily_summary`, report/query generation entrypoint | `daily_summaries` with source step/attempt/validation/decision ids | REP-01..REP-08, day-level oracle |
| Child-safe/browser | DOM/API payload scan | `_project_step`, `_assert_child_safe_projection`, server child projection helpers | no internal ids required in child payload; internal ids remain DB-only | child-safe forbidden term/key oracle |

What cannot count as PASS:

- A green unit suite with fake evaluator/OCR when the claim is semantic quality.
- A browser smoke that reaches "completed" but uses manual/API grading or disabled
  model routes.
- A report file that exists but lacks source ids, freshness version, lineage
  labels, model mode, or pending/blocked/stale/mock-only separation.
- A correct final answer accepted as mastery when reasoning/method/check evidence
  is missing or wrong.
- A photo answer accepted from OCR guesswork, low confidence, or text-photo
  conflict without clarification/evidence rule.
- A next plan that changes task type but is not traceable to attempt ids, graph
  nodes, evaluation decisions, or rollback candidates.
- A child flow that requires parent/Codex intervention for a normal round.
- A screenshot-only "looks fine" claim without DOM/API/DB evidence.
- A stale/generated historical QA report used as proof of current v5 behavior.
- Any PASS that does not state `live_model`, accepted `recorded_model`, `mock_only`,
  `pending`, or `blocked` evidence scope.

Fixtures / samples required:

| Fixture set | Minimum contents | Owner / next action |
|---|---|---|
| `semantic_oracle_v5` | SEM-01..SEM-09 with graph node, prompt, reference rubric, child answer, expected analysis fields, expected teaching/next action | 若命 + 观止 define; 听云 stores/loads |
| `photo_ocr_oracle_v5` | OCR-01..OCR-06 image/text samples, confidence, transcript/math objects, conflict rule | 若命 + 观止 define; 听云 implements fixture harness |
| `graph_rollback_oracle_v5` | GR-01..GR-04 with current/prerequisite status permutations | 若命 confirms graph seed; 听云 planner contract |
| `day_pattern_oracle_v5` | all wrong, all partial, mixed, repeated stuck, repeated photo uncertainty, correct-only | 观止 owns QA definition; 若命 confirms product tolerance |
| `report_truth_oracle_v5` | Codex-readable summary examples with confirmed/weak/pending/blocked/stale/mock-only/missing-lineage | 若命 + 听云 report contract |
| `child_safe_oracle_v5` | forbidden DOM/API terms, focus/keyboard/retry expectations, child copy redlines | 清秋 UX spec + 观止 tests |

Test files authorized:

| File/path | Purpose | Allowed change | Owner |
|---|---|---|---|
| `docs/qa/test_case_spec_v5.md` | Durable source-ready test spec | update authorized now | 观止 |
| `tests/test_learning_system.py` | v5 red unit/integration coverage | add focused red tests now; no production fixes | 观止 |
| `tests/browser_smoke_learning_system.mjs` | v5 browser red expectations and harness contract check | strengthen smoke expectations now | 观止 |
| `tests/fixtures/v5_10_lesson_harness_contract.json` | v5 10-lesson harness contract shell | add optional structured fixture now | 观止 |
| `scripts/child_learning_scenarios.py` | Future oracle fixture expansion | not authorized in this task | 观止 after oracle decision |
| `scripts/live_child_ui_10x.py` | Future v5 10-lesson live/recorded harness implementation | not authorized in this task | 观止/听云 with explicit ledger/model authorization |
| `scripts/live_child_acceptance.py` | Future live acceptance preflight | not authorized in this task | 观止 with QA audit plan |

TEST_CASE_REVIEW - 2026-07-11 16:08 CST:

- source_artifacts_checked:
  - `AGENTS.md`
  - `docs/collaboration/inbox.md#MSG-20260711-002`
  - `docs/product/ai_native_math_learning_prd_v5.md`
  - `docs/product/ai_native_math_learning_product_structure_v5.md`
  - `docs/product/child_ux_flow_spec_v5.md`
  - `docs/architecture/engineering_contract_v5.md`
  - `docs/architecture/implementation_blueprint_v5.md`
  - this `TEST_CASE_SPEC`
  - current `tests/test_learning_system.py` and
    `tests/browser_smoke_learning_system.mjs`
  - 清秋 `UX_REVIEW_NEEDS_FIX` hardening deltas supplied in the dispatch
- existing_cases_checked:
  - blocked state already exposed retry/finish controls, but no test proved the
    primary retry performed recovery work
  - analyzing tests covered one retry only, not the configured terminal budget
  - clarify tests covered low-confidence entry and a generic stuck control, not
    a distinct cannot-provide action or loop exit
  - summary browser coverage hid the answer form, but terminal finish idempotence
    and every continuation control were not fully asserted
  - child bootstrap covered due `answer_analysis` retry only; startup and the
    other v5 model job types were not matrix-tested
  - `today_plan` was checked on initial bootstrap only, not recursively across
    current/analyzing/blocked/summary payloads
- stale_or_missing_cases:
  - blocked primary retry with provider recovery
  - analyzing terminal transition after retry budget
  - clarify cannot-provide/still-unclear exit without mastery or another clarify
  - terminal summary repeat-finish no-op
  - startup and child-bootstrap wake matrix for all v5 model job types with
    `waiting` exclusion
  - recursive legacy fixed-group payload rejection across v5 child states
- updates_made:
  - added
    `test_v5_blocked_primary_retry_recovers_when_model_route_becomes_available`
  - added
    `test_v5_analyzing_retry_budget_ends_with_saved_evidence_and_honest_terminal_state`
  - added
    `test_v5_clarify_cannot_provide_exits_without_false_mastery_or_repeat_loop`
  - strengthened `test_v5_ready_checkpoint_can_finish_to_summary` with repeat
    finish idempotence and no-current-step checks
  - added
    `test_v5_startup_recovery_wakes_every_model_job_type_but_not_waiting`
  - added
    `test_v5_child_bootstrap_recovery_wakes_every_model_job_type_but_not_waiting`
  - added
    `test_v5_child_route_never_exposes_legacy_fixed_group_or_today_plan_payload`
  - strengthened browser smoke with a distinct cannot-provide/still-unclear
    control and submit contract, blocked primary recovery interaction, terminal
    summary action scan, and recursive legacy child-payload scan
- updates_not_made_reason:
  - no production code was authorized
  - no external model or OCR call was authorized
  - no real learning DB was touched; all Python cases use temporary SQLite and
    browser smoke uses its temporary DB/upload directory
  - no new fixture was needed for these state-machine contracts
- authorized_test_files_changed:
  - `tests/test_learning_system.py`
  - `tests/browser_smoke_learning_system.mjs`
  - `docs/qa/test_case_spec_v5.md`
- ready_for_execution: yes for the focused red/green contract subset; no for a
  QA PASS or live semantic claim

Focused red/green evidence:

| Delta | Test/evidence | Result against current production | Expected implementation meaning |
|---|---|---|---|
| Blocked primary retry | `test_v5_blocked_primary_retry_recovers_when_model_route_becomes_available` | RED: after the model route becomes available, the terminal blocked job is never reprocessed and no succeeded stage appears | retry must perform bounded recovery work and project recovered step/clarify/summary, or an explicitly honest still-blocked outcome |
| Bounded analyzing | `test_v5_analyzing_retry_budget_ends_with_saved_evidence_and_honest_terminal_state` | RED: job remains `retry` after the configured attempt budget | preserve one saved attempt, create no mastery, then leave analyzing for blocked/summary/clarify/recovered step |
| Clarify cannot provide | `test_v5_clarify_cannot_provide_exits_without_false_mastery_or_repeat_loop` | RED: a stuck/still-unclear clarification creates another active `clarify_evidence` step | child can safely stop or summarize without mastery and without an endless clarification loop |
| Terminal summary no-op | strengthened `test_v5_ready_checkpoint_can_finish_to_summary` | RED: a repeated finish raises `ChildSafeRuntimeError` | repeated finish is an idempotent no-op with the same summary id/revision and no answer/current-step action |
| Startup all job types | `test_v5_startup_recovery_wakes_every_model_job_type_but_not_waiting` | GREEN | startup recognizes `answer_analysis`, `evaluation_update`, `planner_decision`, and `teaching_generation` in due queued/retry states and excludes waiting |
| Child bootstrap all job types | `test_v5_child_bootstrap_recovery_wakes_every_model_job_type_but_not_waiting` | GREEN | child bootstrap applies the same due-job matrix and never wakes waiting jobs |
| Legacy child payload | `test_v5_child_route_never_exposes_legacy_fixed_group_or_today_plan_payload` | GREEN | start/current/analyzing/blocked/summary projections contain no `today_plan`, `learning_group`, task-list, plan, or fixed-group payload/copy |
| Browser cannot provide | `tests/browser_smoke_learning_system.mjs` | RED at the first focused browser assertion: clarify exposes only generic stuck reasons, not a distinct cannot-provide/still-unclear action | rendered child flow must name the exit action and submit it as explicit child evidence |

Focused commands and outcomes:

- `python3 -m py_compile tests/test_learning_system.py`: pass.
- `node --check tests/browser_smoke_learning_system.mjs`: pass.
- focused seven-test `unittest` selection: 3 passed, 4 expected red failures;
  no unexpected harness/setup error remained.
- browser smoke: exit 1 at the intended clarify cannot-provide red assertion;
  later browser assertions were not treated as executed evidence after that stop.

Source gaps routed to 若命:

| Gap | Impact | Suggested owner | Required artifact or decision |
|---|---|---|---|
| Blocked retry transport and eligibility are not executable in the current contract. UX requires a primary retry, while the engineering contract says terminal blocked stages are reused unless an explicit retry/reconciler creates a new source-phase key; no route/method, eligibility rule, retry budget, or still-blocked outcome marker is defined. | 听云 could implement incompatible retry semantics, duplicate semantic stages, or leave the current generic-refresh loop. | 若命, then 听云 for engineering contract | Confirm whether blocked retry uses child bootstrap or a dedicated action, which blocked reasons are retryable, how a new source-phase key is formed, and how recovered/still-blocked/summary outcomes are represented. |
| `clarify_evidence` names `stuck/cannot provide`, but the submit interface only has text/photo/stuck and no stable cannot-provide reason code or child-action label. | UI, runtime, report, and tests may overload generic stuck differently and fail to distinguish inability to clarify from a new learning-content stuck event. | 若命, with 清秋 and 听云 | Confirm the child-visible label and stable payload representation, plus whether cannot-provide closes immediately or after one bounded deterministic reconciliation. |

Automation plan:

1. Implementation-stage red suite: run the named focused unit/browser commands
   and keep them red until 听云 implements the v5 DAG/runtime hardening.
2. Mock-only contract regression: after implementation, run unit/API/browser smoke and
   `simulate_child_learning_journey.py --lessons 10`; label results
   `QA_PASS_WITH_SCOPE` at most for semantic/model claims.
3. Recorded oracle regression: replay accepted semantic/OCR samples against the
   answer-analysis and planner contracts; require exact expected fields and
   teaching/next-action class.
4. Live model probe: run a small live semantic/OCR sample set with provider
   transcripts/scope labels; compare to recorded oracle.
5. 10-lesson real simulation: run browser-driven `live_child_ui_10x.py` only
   after explicit authorization for local ledger writes and model calls.
6. Report/Codex audit: generate/read current summary and progress query; compare
   source records and freshness labels.

Manual QA handoff:

- 清秋 must review child-visible copy/state/visual quality before UI PASS.
- Human review is required for whether teaching explanations are age-respectful,
  but human taste review cannot replace semantic oracle checks.
- Live model runs must preserve provider scope and avoid secrets in screenshots,
  reports, DB rows, or logs.

False-pass risks:

- Mock evaluator returns perfect `answer_analysis`; tests only verify persistence.
- Browser path submits 10 answers but never verifies reasoning quality.
- OCR transcript is accepted without confidence/vision audit.
- Report verdict says PASS while issue count or process exit code indicates
  failure.
- Current v2/v3 script names pass while v5 product states/contracts changed.
- Planner output contains a new task but no evidence lineage.
- Daily summary omits pending/blocked/missing-lineage evidence.
- Child surface hides some internals but leaks provider/model/ids in API payload.
- Restart test checks recovery from queued jobs but not completed-unapplied
  analysis or duplicate summaries.

Coverage gaps:

- Current production still handles only `answer_analysis` and inlines
  deterministic evaluation/planner/teaching; P0 red tests now lock the desired
  four-stage DAG.
- Existing semantic scenario library still needs accepted recorded fixtures for
  photo/text conflict, no usable work, OCR hallucination, all-wrong day,
  all-partial day, repeated stuck day, and repeated photo uncertainty day before
  semantic PASS.
- Existing live 10x harness is legacy fixed-round; v5 harness must use daily-flow
  current-step routes and recorded/mock labels before live execution.
- Final rendered UX, accessibility, and live provider evidence remain later QA
  lanes, not blockers to these red tests.

TEST_CASE_REVIEW CORRECTION - 2026-07-11 16:50 CST:

- correction_target:
  `test_v5_summary_report_phase_lineage_includes_mastery_agent_and_job_refs`
- source_contract:
  `docs/architecture/engineering_contract_v5.md` and
  `docs/architecture/implementation_blueprint_v5.md` define one durable worker
  claim per stage: `answer_analysis -> evaluation_update -> planner_decision`.
- stale_case_evidence:
  before correction the test called `process_next_background_job()` once,
  consumed only `answer_analysis`, and failed at `summary is not None`.
- correction_made:
  the test now calls the worker three times, in DAG order, with explicit
  `recorded_model` routes for answer, evaluation, and planner; `budget_min=1`
  remains the summary-closing fixture.
- lineage_assertions_preserved_and_strengthened:
  the original required summary keys remain asserted; the case additionally
  checks stage-to-stage job-id linkage, all three succeeded job rows,
  `recorded_model` provider mode, accepted agent-run rows, a nonempty mastery
  decision id, a nonempty next-step decision id, and their presence in summary
  phase-lineage arrays.
- no_inline_guard:
  `test_v5_answer_success_enqueues_evaluation_job_without_inline_mastery_or_planner`
  remains unchanged and verifies the answer stage alone creates neither
  mastery nor planner decision.
- focused_command:
  `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_v5_summary_report_phase_lineage_includes_mastery_agent_and_job_refs tests.test_learning_system.LearningSystemTest.test_v5_answer_success_enqueues_evaluation_job_without_inline_mastery_or_planner`
- focused_result:
  GREEN, 2 tests passed in 1.911 seconds on the final verification run.
- evidence_scope:
  temporary SQLite databases and recorded fixtures only; no external model
  call, production-code edit, or real learning database mutation.
- correction_verdict: `TEST_CASE_CORRECTED`

TEST_CASE_QUALITY_GATE:

- verdict: `TEST_CASE_READY_FOR_IMPLEMENTATION_STAGE_RED_TESTS`
- scoped_baseline_ready: yes
- product_acceptance_coverage: pass for baseline coverage inventory.
- technical_contract_coverage: pass for current red-test stage.
- code_runtime_targets_verified: pass for current production-as-failing-target
  scope.
- coverage_matrix_complete: pass for implementation-stage red tests.
- depth_expansion_sufficient: pass for baseline high-risk map.
- negative_adversarial_cases_present: pass.
- false_pass_risks_identified: pass.
- evidence_standard_defined: pass.
- coverage_gaps_explicit: pass.
- blocking_quality_gaps:
  - none blocking implementation-stage red tests.
- later_final_QA_gaps:
  - production implementation must pass the P0 red suite first.
  - accepted semantic/OCR recorded oracle fixtures must be executed before
    semantic PASS.
  - live model/OCR evidence remains a later explicitly authorized QA lane.
  - rendered UX review and final browser screenshots remain later gates.

Stop condition:

This spec is ready for 观止 to implement the authorized red tests in
`tests/test_learning_system.py` and `tests/browser_smoke_learning_system.mjs`.
Do not claim QA PASS from these tests; they are intended to fail against the
current inline first-slice implementation until the v5 DAG/runtime hardening is
implemented.
