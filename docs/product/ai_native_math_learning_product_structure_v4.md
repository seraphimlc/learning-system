# AI Native Math Learning Product Structure v4

Status: HISTORICAL_ARCHIVE_DO_NOT_USE_FOR_CURRENT_PRODUCT_BASELINE
Owner: 若命 (`ruoming`)
Created: 2026-07-11 CST
Source PRD: `docs/product/ai_native_math_learning_prd_v4.md`

This file is retained as historical context only. Do not use it as the current
product-structure source for v5 planning, UX, implementation, QA, or review.

At the time it was written, this product structure turned PRD v4 into an
executable product map. It is now archived and must not be used as the v5
product-structure source.

## Entry Lock

- request_type: `product_structure`
- selected_contract: `PRODUCT_STRUCTURE_SPEC`
- source_artifacts:
  - `docs/product/ai_native_math_learning_prd_v4.md`
  - `AGENTS.md`
  - `docs/domain-index/math-learning.md`
  - `data/knowledge_graphs/math/math_knowledge_graph_v2.md`
  - `docs/system/qa/latest.md`
  - `docs/system/qa/question_bank_grade_level_latest.md`
  - current user decisions through 2026-07-11
- project_boundary_overlay: PRD v4 overlay, stable for product structure;
  technical storage/model-routing thresholds remain downstream decisions
- output_target: durable doc
  `docs/product/ai_native_math_learning_product_structure_v4.md`
- validation_required: multi-role review by 清秋, 听云, 观止, 镜花 before
  technical planning or implementation
- stop_condition: product structure is review-ready or missing product facts are
  routed back to 若命/user

## PRODUCT_STRUCTURE_SPEC - 若命（agentKey: `ruoming`）- 2026-07-11 CST

Objective:

Define the product modules, features, child surface, flows, states, permissions,
data meanings, model/content behavior, and acceptance paths for the simplified
adaptive learning loop:

```text
select step -> answer -> AI judge -> teach/repair -> select next step -> summary
```

Source PRD / decisions:

- `docs/product/ai_native_math_learning_prd_v4.md`
- User-confirmed boundary: one child Web surface, parent through Codex only.
- User-confirmed daily model: review old knowledge first, then graph-guided new
  knowledge learning when readiness is sufficient.
- User-confirmed interaction model: 10-20 daily interactions selected
  step-by-step, not a fixed worksheet.
- User-confirmed quality model: AI judges answer and reasoning; final answer
  alone is not mastery.
- User-confirmed runtime model: deterministic runtime owns stable execution,
  persistence, async work, recovery, and child-safe projection.

Scope:

- Child-only learning surface.
- Daily flow creation/resume.
- Adaptive target selection from graph evidence.
- One visible current step.
- Text answer, photo answer, and stuck signal.
- AI answer analysis.
- Evaluation and mastery update.
- Teaching, repair, retest, prerequisite rollback, and stretch selection.
- Graph-guided new knowledge learning.
- Daily summary and Codex-readable records.
- Product-level model/content guardrails.
- Product-level QA acceptance paths.

Non-goals:

- Parent Web dashboard.
- Multi-user identity/productization.
- Fixed worksheet generated before evidence is known.
- Manual parent grading as normal flow.
- Low-age mechanical drill flow unless narrow weakness evidence justifies it.
- Olympiad track as mainline.
- Automatic self-evolution mutating active graph, bank, mastery, or plan.
- External textbook/commercial question import without explicit source.

Project boundary overlay:

- Single private child; incoming Grade 7 bridge math.
- All teaching, diagnosis, questions, plans, analysis, and reports bind to graph
  nodes.
- Seven-grade failure first checks prerequisite chain.
- Child sees simple product states only; internal ids, model names, rubrics,
  queue details, graph internals, and Codex instructions stay hidden.
- Structured learning records must support later Codex query and replay.
- Self-evolution is proposal-only in this cycle.
- Question selection must be efficient and must not feed the full bank to a
  model for each step.

Actors / user roles:

| Actor / role | Product role | In scope | Excluded |
|---|---|---|---|
| Son | Primary learner | Opens page, answers, uploads photo, says stuck, receives feedback/teaching/summary | Sees internal ids, queue/model state, parent reports, agent names |
| Parent | System owner through Codex | Asks Codex for progress, weak points, evidence, system issues, next improvement | Operates a parent dashboard, grades normal attempts, approves each step |
| Runtime | Deterministic product controller | Selects current step, persists facts, gates transitions, recovers failures, creates child-safe projection | Invents semantic judgment beyond configured rules/model outputs |
| Internal learning agents | Hidden semantic specialists | Analyze answers, suggest teaching, evaluate mastery, propose next step, generate/review question content under bounded inputs | Directly mutate authoritative state, expose raw analysis to child, bypass runtime gates |
| Codex/operator | Inspection and improvement surface | Reads records/reports, diagnoses system issues, changes product/code after review | Participates in normal child session loop |

## Module Inventory

| Module | Purpose | User value | Priority | Dependencies | Non-goals |
|---|---|---|---|---|---|
| Child Learning Surface | One page where the child always sees the next appropriate action | Low friction, no parent required | P0 | Current-step projection, submission handling | Parent dashboard, internal debug UI |
| Daily Flow Runtime | Own the daily state machine and one-current-step invariant | Stable session flow with honest waiting/recovery | P0 | Graph targets, step records, analysis/evaluation state | Letting model decide raw state transitions |
| Graph Targeting | Choose review/new-learning targets from graph node states and prerequisites | Work on what matters, skip stable nodes | P0 | Knowledge graph, mastery evidence, due/weak/untested state | Full-grade blanket review |
| Question Bank and Candidate Gate | Provide reviewed graph-bound candidates and reject weak items before use | Respectful difficulty and diagnostic value | P0 | Graph nodes, item metadata, production/review rubric | Low-age filler, full-bank prompt selection |
| Evidence Capture | Save text/photo/stuck evidence before analysis | Child can continue safely; no lost answers | P0 | Current step, child-safe handles, attachment policy | Treating OCR guesses as confirmed evidence |
| Answer Analysis | Judge final answer, method, reasoning, process, alternate valid methods, and gaps | Feedback reflects thinking, not string matching | P0 | Attempt evidence, question rubric, model adapter | Pure reference-answer matching |
| Evaluation Reducer | Update node mastery dimensions from usable evidence | Decisions reflect actual understanding | P0 | Answer analysis, graph state, prior evidence | One right answer equals durable mastery |
| Teaching Package | Produce child-facing explanation, hint, worked example, or micro-check | Repair the first cognitive break | P0 | Analysis gap, node teaching content, current step type | Dump backend diagnosis to child |
| Next-Step Planner | Decide retest, near transfer, prerequisite probe, micro-teach, new knowledge, stretch, or summary | Session keeps moving intelligently | P0 | Evaluation update, candidate metadata, budget, pending evidence | Endless same-type repetition |
| Learning Record and Report | Persist what happened, why, and what is next for Codex query | Parent can trust progress and issues later | P0 | Flow, steps, attempts, analysis, decisions, summaries | Conversational memory as source of truth |
| Model Adapter Boundary | Normalize provider output and failure states at product-contract level | Provider changes do not corrupt product state | P0 | Runtime gates, structured output contracts | Provider-specific logic leaking into child flow |
| QA/Review Evidence Surface | Make acceptance paths inspectable by tests and Codex | False pass risk is visible | P1 | Product records, status labels, report freshness | QA based only on happy path screenshots |

## Feature Inventory

| Feature | Module | Actor | User value | Entry surface | Core action | Priority |
|---|---|---|---|---|---|---|
| Start or resume daily flow | Child Learning Surface | Son | Continue without knowing system internals | Child page | Load current day and show one action | P0 |
| Start/resume today's learning | Daily Flow Runtime | Son | Begin or continue the system-selected daily path | Child page | Create/resume daily flow; review starts first by system rule | P0 |
| One current step display | Child Learning Surface | Son | Focus on one question/teaching step | Child page | Render current step only | P0 |
| Text answer submission | Evidence Capture | Son | Answer freely | Child page | Save answer and enqueue analysis | P0 |
| Photo answer upload | Evidence Capture | Son | Submit written work | Child page | Save attachment and route OCR/vision evidence | P0 |
| Stuck signal | Evidence Capture | Son | Get help without guessing | Child page | Save stuck evidence and trigger hint/repair | P0 |
| Answer analysis | Answer Analysis | Runtime/Internal agents | Know what was understood | Background process | Compare answer, process, reasoning, alternatives | P0 |
| Mastery update | Evaluation Reducer | Runtime | Avoid false mastery | Background process | Update node dimensions from usable evidence | P0 |
| Targeted explanation | Teaching Package | Son | Understand the first break | Child page | Show explanation/hint/worked example/micro-check | P0 |
| Similar retest | Next-Step Planner | Son | Confirm unstable skill | Child page | Select same-structure but not identical task | P0 |
| Near-transfer retest | Next-Step Planner | Son | Check real transfer | Child page | Select representation/context variation | P0 |
| Prerequisite rollback | Graph Targeting | Son | Fix root cause before more advanced work | Child page | Probe/teach prerequisite node | P0 |
| New knowledge lesson | Teaching Package | Son | Learn next graph node | Child page | Essence -> model -> example -> interaction -> practice | P0 |
| Stretch transfer | Next-Step Planner | Son | Controlled challenge after stability | Child page | Select higher-transfer task | P1 |
| Daily summary | Learning Record and Report | Son/Parent via Codex | Know what was confirmed/weak/pending | Child page/Codex | Summarize with evidence labels | P0 |
| Codex progress query | Learning Record and Report | Parent | Inspect progress and system issues | Codex | Read persisted facts and reports | P0 |
| Model failure honesty | Model Adapter Boundary | Son/Parent | Do not hide configuration/analysis failure | Child page/Codex | Persist blocked reason and show safe message | P0 |
| Report freshness guard | QA/Review Evidence Surface | Parent/QA | Avoid stale confidence | Codex/report | Mark stale/mock/pending scope | P1 |

## Page / Surface Map

| Page/surface | Purpose | Entry | Main actions | Required states | Empty/loading/error/success behavior |
|---|---|---|---|---|---|
| Child page `/` | Single learner surface | Child opens local URL | Start/resume, answer text, upload photo, mark stuck, continue after feedback | `choose_or_resume`, `current_step`, `submitting`, `analyzing`, `feedback`, `teaching`, `clarify_evidence`, `ready_for_new_knowledge`, `new_knowledge`, `blocked`, `summary` | Empty: no active day -> start review. Loading: brief and honest. Error: child-safe message plus retry. Success: next step or summary. |
| Codex query surface | Parent/operator inspection | Parent asks Codex | Read records, summarize progress, identify issues, plan system changes | evidence trust labels: `confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`, `missing_lineage`; mastery condition labels such as `weak` are separate | No dashboard. If evidence is missing/stale, Codex reports scope instead of filling gaps. |
| Internal records/report surface | Machine-readable evidence for roles/tests | Runtime writes records | Store step, reason, answer, analysis, evaluation, decision, summary | `created`, `pending`, `processed`, `applied`, `invalidated`, `blocked` | Not child-facing. Must support audit and replay. |

## Child Step Interaction Contract

The child never chooses from internal planning modes. The child only sees the
current step, the allowed response controls for that step, and the next
child-safe action.

| Step type | Child sees | Allowed controls | Validation | Exit states |
|---|---|---|---|---|
| `review_question` | One review question with space for reasoning | Text answer, photo upload, stuck | Require nonblank text/photo/stuck; photo usability is untrusted until validated | analysis pending, clarify evidence, feedback, teaching, next step |
| `new_knowledge_explanation` | Essence, core model, and one worked example chunk | Continue, ask for smaller hint, mark stuck | No mastery update from continue alone | micro interaction or worked-example follow-up |
| `worked_example` | A complete example with a visible check point | Continue, answer a small check, stuck | Check response if requested; otherwise records exposure only | micro-check, standard question, or repair |
| `micro_check` | One small understanding check | Text answer, optional photo, stuck | Same semantic analysis rule as questions, but lower mastery weight | feedback, micro-teach, standard question, prerequisite probe |
| `clarify_evidence` | Request for clearer work or explanation | Add text, replace/add photo, mark cannot provide | Existing attempt remains pending until usable evidence exists or flow safely stops | analysis pending, blocked, summary |
| `feedback` | Result on the latest usable step and what it means | Continue, review explanation, stop for today | Must not expose backend labels as diagnosis | teaching, retest, next step, summary |
| `teaching_repair` | Targeted explanation/hint for first break | Try smaller step, continue to retest, stuck | Teaching view itself does not prove mastery | micro-check, same-structure retest, prerequisite probe |
| `ready_for_new_knowledge` | Checkpoint: review is stable enough to learn next concept | Continue to new knowledge, finish with summary | Runtime owns readiness; child chooses only continue vs finish | `start_new_knowledge` or summary |
| `blocked` | Honest child-safe message that the system cannot judge/continue safely | Retry load/status, add evidence if relevant, finish summary if safe | No mastery update from blocked evidence | waiting, clarify evidence, summary, operator-visible block |
| `summary` | Today's confirmed/weak/pending/blocked result | Finish | Summary links to source facts internally | closed |

## Pending / Clarify / Blocked Action Boundaries

| State | Child-visible action | Runtime boundary |
|---|---|---|
| Dependent analysis pending | Wait with honest status or finish with pending summary | Do not choose a dependent next step from pending evidence. |
| Independent safe step available | Continue to independent step only if it does not consume pending evidence | Decision must record why the step is independent and safe. |
| Blank answer | Ask for text, photo, or stuck signal | No attempt analysis or mastery update until evidence exists. |
| Low-confidence photo/OCR | Ask for clearer photo or written explanation | OCR/vision text remains untrusted until validated. |
| Model not configured/failing | Show safe blocked/wait message; Codex/operator sees reason | No fake grade, no mastery update, no hidden "rest and wait" cover. |
| Repeated stuck | Offer smaller step, prerequisite probe, or safe early summary | Do not repeat same-type questions without teaching or rollback. |
| Double submit/reload | Preserve the same current-step outcome | No duplicate attempts, jobs, decisions, or summaries. |

## Canonical Learning Actions And Labels

Canonical next-step actions:

- `continue_review`
- `same_structure_retest`
- `near_transfer_retest`
- `prerequisite_probe`
- `micro_teach`
- `worked_example`
- `ask_for_clearer_evidence`
- `ready_for_new_knowledge`
- `start_new_knowledge`
- `stretch_transfer`
- `daily_summary`
- `blocked_operator_attention`

Technical plans may map older implementation names such as `new_knowledge_entry`
or `enter_new_knowledge` to the canonical product actions above, but child and
report behavior must preserve the product meaning.

Canonical evidence trust labels:

- `confirmed`: current usable evidence supports the claim.
- `pending`: evidence is saved but not yet analyzed or validated.
- `blocked`: system cannot analyze or decide safely.
- `inferred`: plausible, but not directly proven by current evidence.
- `stale`: evidence belongs to an old graph, bank, runtime, or report version.
- `mock_only`: only deterministic/mock evidence exists.
- `missing_lineage`: source graph/question/step/attempt chain is incomplete.

Mastery condition labels such as `weak`, `unstable`, `partial`, or `due` are not
evidence trust labels. Codex reports must keep those categories separate.

## User Flows

| Flow | Actor | Start | Steps | Success end | Failure/recovery |
|---|---|---|---|---|---|
| Daily old-knowledge review | Son | Opens page and starts/resumes review | Runtime builds target pool -> selects current step -> child answers -> save evidence -> analyze -> evaluate -> teach/repair/advance -> repeat within budget | Summary or ready-for-new-knowledge transition | Pending analysis shows honest wait/safe independent step; model failure blocks with operator reason |
| Text answer loop | Son | Current question visible | Type answer/process -> submit -> immediate save -> async analysis -> child sees feedback or next step | Step resolved and next action shown | Blank evidence asks for clarification; double submit does not duplicate |
| Photo answer loop | Son | Current question visible | Upload photo -> optional text -> submit -> save attachment -> OCR/vision analysis -> validate confidence -> feedback/clarification | Photo evidence becomes usable or asks for clearer evidence | Low confidence stays pending/clarify; no guessed mastery |
| Stuck repair | Son | Cannot start | Mark stuck -> runtime saves stuck evidence -> teaching package gives first hint/smaller step -> micro-check/retest | Child can attempt a smaller or related step | Repeated stuck triggers prerequisite probe or safe stop |
| Prerequisite rollback | Runtime/Son | Advanced node fails with prerequisite pattern | Identify prerequisite chain -> choose probe/teach prerequisite -> retest current or prerequisite | Root break repaired or marked weak | If evidence insufficient, ask for clearer process or summary with pending state |
| New knowledge learning | Son | Review readiness is sufficient | Essence explanation -> core model -> worked example -> micro interaction -> standard question -> variant -> feedback | Node has initial learning evidence and next review hook | If micro-check fails, teach first break before more practice |
| Daily summary | Runtime/Son/Codex | Budget reached, safe stop, or child exits | Collect confirmed/weak/pending/blocked evidence -> child-safe summary -> Codex-readable facts | Summary visible and queryable | Stale/pending/model-failed facts are labeled, not hidden |

Day-level outcome scenarios that must remain valid product paths:

| Scenario | Product expectation |
|---|---|
| All wrong | Session does not keep drilling blindly; it teaches, probes prerequisites, and may stop early with weak/pending evidence. |
| All partial | System records partial dimensions and chooses micro-teach, near-transfer, or prerequisite probe instead of calling mastery. |
| Mixed correct/partial/wrong | Summary separates confirmed, weak, pending, and blocked evidence by node/action, not only last question. |
| Repeated stuck | System reduces step size, teaches, probes prerequisites, or summarizes safely; it does not shame the child or loop. |
| Repeated photo uncertainty | System asks for clearer evidence/text explanation or summarizes pending/blocked; it does not infer mastery from guessed OCR. |

## State Model

| Object | States | Transitions | Triggered by | User-visible meaning |
|---|---|---|---|---|
| `daily_flow` | `not_started`, `review_active`, `new_learning_active`, `waiting_analysis`, `blocked`, `summarized`, `closed` | start, resume, step created, analysis pending, safe stop, summary generated | Child start, runtime planner, job status, child exit | Whether today has a learning session and what phase it is in |
| `flow_step` | `drafted`, `visible`, `answered`, `analysis_pending`, `feedback_ready`, `teaching_ready`, `superseded`, `blocked`, `completed` | select, project to child, submit, analyze, teach, decide next | Runtime, child submission, analysis result | The one thing currently shown or just completed |
| `attempt` | `created`, `saved`, `analysis_pending`, `analyzed`, `invalidated`, `blocked` | submit, save, model result, validation, operator invalidation | Child, runtime, model adapter, Codex/operator | Whether the child's evidence is usable |
| `answer_analysis` | `not_started`, `pending`, `complete`, `low_confidence`, `failed`, `not_configured` | job enqueue, model return, validation | Background analysis | Whether AI judgment exists and can be trusted |
| `evaluation_update` | `not_applied`, `applied`, `deferred`, `rejected` | analysis validated, evidence insufficient | Runtime reducer | Whether mastery changed |
| `next_step_decision` | `candidate`, `selected`, `shown`, `rejected`, `blocked` | planner recommendation, runtime gate, child projection | Runtime/planner | Why the next step appeared or did not appear |
| `daily_summary` | `not_ready`, `drafted`, `published`, `stale` | budget/safe stop, report generation, later data changes | Runtime/reporting | What today proved, left pending, or blocked |

## Permission / Boundary

| Actor/role | Can do | Cannot do | Source rule |
|---|---|---|---|
| Son | Use child page, answer text/photo, mark stuck, continue, see child-safe feedback and summary | See internal ids, raw rubrics, provider/model status, graph internals, Codex instructions, parent evidence reports | PRD v4 UX/security constraints |
| Parent | Ask Codex for progress, weak points, evidence, system issues, and next engineering/product changes | Grade each answer in normal flow, use parent dashboard, manually approve every step | User-confirmed product boundary |
| Runtime | Persist evidence, enforce state transitions, gate model outputs, decide authoritative next step, recover jobs | Trust model text without validation, fake grading, mutate state from pending/failed evidence | Runtime product boundary |
| Internal learning agents | Produce bounded semantic analysis/teaching/planning suggestions | Directly write authoritative mastery/plan state, expand scope, expose backend analysis to child | PRD v4 internal-agent boundary |
| Codex/operator | Inspect internal records, run review/QA, change system after proper gates | Publish/external-write/destructively reset real data without explicit authorization | AGENTS.md and PRD v4 side-effect policy |

## Data Objects / Domain Terms

| Object/term | User meaning | Key fields product must preserve | Source | Consumers |
|---|---|---|---|---|
| Graph node | Knowledge point with prerequisites and teaching/diagnosis meaning | node id, prerequisites, mode, teaching contract, diagnosis/error tags | Graph docs | Targeting, questions, evaluation, reports |
| Learner node state | Current evidence-backed understanding of a node | dimensions, stability, due status, weak reasons, evidence ids | PRD v4 | Targeting, planner, Codex report |
| Question bank item | Reviewed task bound to a graph node and evidence goal | node, family, difficulty dimensions, evidence target, rubric, active-use status, version | Bank audit/domain index | Candidate gate, child step, answer analysis |
| Candidate packet | Compact selection context for planner/model | small candidate set, metadata, reasons, exclusions | PRD v4 efficiency rule | Planner/internal agents |
| Current step | One child-visible action | type, child prompt, allowed response modes, hidden source refs, handle | PRD v4 | Child page, attempts, runtime |
| Attempt | Child's evidence for a step | response mode, text/photo/stuck, timestamp, validation state | PRD v4 | Analysis, evaluation, report |
| Answer analysis | AI semantic judgment | final answer judgment, method validity, reasoning, steps, symbols/units, alternative methods, gaps, confidence, child feedback seed | Domain index | Evaluation, teaching, QA |
| Teaching package | Child-facing repair or lesson content | explanation, hint, worked example, micro-check, tone constraints | PRD v4 | Child page, next-step planner |
| Next-step decision | Why the next action is chosen | action, source evidence, graph node, candidate reason, blockers | PRD v4/inbox TODO | Runtime, child page, report |
| Learning record | Durable trace of one session | steps, attempts, analyses, evaluations, decisions, summaries, evidence labels | Inbox TODO | Codex, QA, future planning |
| Daily summary | End-of-day product result | confirmed, weak, pending, blocked, next suggestions, source refs | PRD v4 | Son, Codex/parent |

Daily summary minimum oracle:

- Include every answered step whose usable evidence is wrong, partial, pending,
  blocked, invalidated, or low-confidence.
- Include all confirmed strengths only at graph-node/action granularity; do not
  overstate durable mastery from one answer.
- Include teaching actions shown, prerequisite rollback reasons, and retest
  decisions.
- Include pending model/OCR/config failures with trust labels.
- Include source lineage internally for Codex: graph node, question/step,
  attempt, analysis, evaluation, next decision, and report freshness.
- Child-facing summary may be shorter, but it must not contradict the
  Codex-readable evidence facts.

## External Side Effects

- Allowed in product scope:
  - Local learning records and report writes.
  - Local photo/evidence storage.
  - Configured model calls through a model boundary.
- Forbidden without explicit authorization:
  - Cloud deployment.
  - External account writes.
  - External content import.
  - Destructive reset of real learning data.
  - Exposing secrets in docs, reports, screenshots, DB rows, or model payload logs.

## Model / Content Behavior

- Model outputs are advisory until runtime validation/gates accept them.
- Answer Analysis must cover final answer, relation/model, steps, process,
  symbols/units, explanation/check, alternative valid methods, process gap,
  confidence, and child-facing feedback seed.
- Evaluation must map usable evidence to concept, model, procedure,
  calculation, expression, transfer, and stability dimensions.
- Planner may receive a compact candidate packet only. Deterministic prefiltering
  must remove inactive, stale, too-easy, wrong-node, wrong-purpose, or
  already-overused candidates before any model choice.
- Question quality must reject:
  - low-age mechanical filler without narrow repair evidence
  - answer-only prompts
  - prompts that do not require reasoning/process evidence
  - child-facing meta language about agents or generation
  - untraceable graph-node lineage
  - fake "because you previously said..." claims without valid evidence
- Teaching content must identify the first cognitive break and give the next
  small action. It must not expose backend labels as child-facing diagnosis.
- New knowledge content follows: essence explanation -> core model -> worked
  example -> micro interaction -> standard question -> variant -> review/repair.
- Self-evolution is disabled as an automatic state mutator. Model-generated
  improvement proposals may be recorded for later human/Codex review only.

## Acceptance Paths

| Scenario | Given | When | Then | Evidence required |
|---|---|---|---|---|
| Start daily review | No active day exists | Son opens page and starts | One child-safe current step appears | Browser trace, current-step payload |
| Resume daily review | A step is pending/visible | Son reloads page | Same safe state resumes without duplicate step | Runtime record before/after reload |
| Text answer | Current question visible | Son submits text | Attempt saved quickly; analysis starts; no lost answer | Attempt and job/analysis status |
| Photo answer | Current question visible | Son uploads photo | Attachment saved; OCR/vision confidence gates usability | Attachment and evidence validation facts |
| Stuck signal | Current step visible | Son says stuck | Teaching hint/micro-step or prerequisite probe appears | Step decision and teaching package |
| Correct process | Answer and reasoning are sound | Analysis/evaluation run | Node improves with evidence; durable mastery only if prior evidence supports it | Analysis dimensions and mastery update |
| Answer-only | Final answer is right but process missing | Analysis/evaluation run | Process gap recorded; no full mastery from this alone | Analysis, evaluation, next decision |
| Wrong-reason right-answer | Final answer right but method invalid | Analysis/evaluation run | Partial/wrong according to rubric; repair selected | Semantic oracle sample |
| Alternative valid method | Child uses a different valid method | Analysis runs | Accepted if mathematically valid and explained | Analysis comparison |
| Prerequisite gap | Advanced node fails due to prerequisite | Planner runs | Prerequisite probe/teach chosen, not blind same-type drill | Graph chain and decision record |
| Low-age candidate | Too-easy mechanical item enters candidate pool | Gate runs | Rejected unless evidence justifies narrow repair | Candidate exclusion reason |
| New knowledge readiness | Review prerequisites stable enough | Planner evaluates next phase | New-knowledge lesson step can start | Readiness summary |
| Slow analysis | Last attempt pending | Child flow asks for next step | Runtime waits if dependent or uses independent safe step excluding pending evidence | Decision reason with pending label |
| Model missing/failing | Evaluator config fails | Attempt submitted | No fake grade; child sees safe blocked/wait state; Codex sees reason | Error state and report label |
| Daily summary | Budget/safe stop reached | Runtime summarizes | Child sees concise summary; Codex can inspect evidence details | Summary and source ids |
| Parent asks Codex | Records exist | Parent asks progress | Codex separates confirmed, weak, pending, blocked, stale, mock-only, missing-lineage | Report/query evidence |
| Restart recovery | Server restarts with pending/running/completed-unapplied work | Runtime resumes | No duplicate attempts, jobs, decisions, mastery updates, or summaries | Before/after runtime records |
| Child-safe projection | Child route/payload renders | UI/API payload is inspected | No graph ids, question ids, attempt ids, model/provider names, rubrics, queue internals, or Codex instructions leak | DOM/API scan |
| Report freshness | Report or Codex query reads prior facts | Underlying flow/graph/bank/runtime version changed | Stale reports cannot be used as current pass evidence | Timestamp/version/source comparison |

Required QA fixture families:

- Semantic answer fixtures: correct-with-reasoning, correct-answer-only,
  wrong-reason-right-answer, alternative valid method, blank, stuck,
  symbol/unit/procedure error.
- Photo fixtures: readable photo, unclear photo, low-confidence OCR,
  photo/text mismatch, OCR guessed but untrusted.
- Graph rollback fixtures: at least one chain for nearest prerequisite probe,
  same-structure retest, and near-transfer retest.
  Exact node ids are chosen in `TEST_CASE_SPEC v4` from the active graph.
- Teaching negative fixtures: generic explanation, backend-label dumping, and
  "just do more practice" after first cognitive break must fail.

## Open Product Decisions

- Final child-facing visual style and exact copy belong to `UX_FLOW_SPEC v4`.
- Initial conservative mastery thresholds belong to technical/product-rule design
  after review; they must stay evidence-backed and adjustable.
- Learning record storage split belongs to technical planning, constrained by the
  requirement that every step and decision be queryable/replayable.
- Live versus recorded model sample policy for QA belongs to 观止's test-case
  design and QA audit plan.

## Required Downstream Artifacts

- `UX_FLOW_SPEC v4` from 清秋.
- `TECHNICAL_PLAN v4` from 听云.
- `ENGINEERING_CONTRACT` from 听云.
- `IMPLEMENTATION_BLUEPRINT` from 听云.
- `TEST_CASE_SPEC v4` from 观止.
- Architecture/product-structure review from 镜花.
- QA audit plan/report from 观止 after implementation evidence exists.

## Required Gates

- 若命 product-structure self-check: ready for review.
- 清秋 UX flow review: child surface can be specified without guessing.
- 听云 source readiness: technical plan can be written without inventing product
  behavior.
- 镜花 product/architecture review: state machine, async/recovery,
  model-boundary, evidence-chain, and child-safe boundary are coherent.
- 观止 test-case source readiness: acceptance paths are deep enough for
  child-perspective QA, semantic/model false-pass checks, and browser flows.

## Product Structure Readiness Gate

- verdict: `PRODUCT_STRUCTURE_READY_FOR_REVIEW`
- modules_defined: pass
- features_defined: pass
- page_surface_map_defined: pass
- user_flows_defined: pass
- state_model_defined: pass
- permissions_defined: pass
- data_objects_defined: pass
- model_content_behavior_defined: pass
- acceptance_paths_defined: pass
- downstream_artifacts_defined: pass
- implementation_authorized: no
- blocking_product_questions: none
- allowed_forward_assumptions:
  - technical storage/queue/model-provider choices are downstream.
  - exact child visual style and copy are downstream UX work.
  - mastery thresholds start conservative and must be reviewed after real data.

Stop condition:

This product structure is ready for multi-role review. It authorizes UX,
technical planning, engineering contract, and test-case design after review; it
does not authorize implementation by itself.
