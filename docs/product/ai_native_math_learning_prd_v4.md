# AI Native Math Learning System PRD v4

Status: HISTORICAL_ARCHIVE_DO_NOT_USE_FOR_CURRENT_PRODUCT_BASELINE
Owner: 若命 (`ruoming`)
Created: 2026-07-11 CST
Archived by: `docs/product/ai_native_math_learning_prd_v5.md`

This file is retained as historical context only. Do not use it as the current
product source for v5 planning, UX, implementation, QA, or review.

At the time it was written, this PRD described a proposed implementation cycle
for the single-child AI-native math learning system. It is now archived. Its
old product contract was:

```text
select step -> answer -> AI judge -> teach/repair -> select next step -> summary
```

The system is not an agent showcase. The child uses one Web surface. The parent
uses Codex. Runtime code guarantees stable execution. Internal teaching agents
provide semantic judgment and generation only through gated contracts.

## Entry Lock

- request_type: `prd_spec`
- selected_playbook_or_contract:
  - `docs/collaboration/playbooks/prd-authoring.md`
  - `docs/collaboration/playbooks/artifact-contracts.md`
- source inputs:
  - latest user decisions in this Codex thread through 2026-07-11
  - `AGENTS.md`
  - `docs/00_PROJECT_BLUEPRINT.md`
  - `docs/domain-index/math-learning.md`
  - `docs/product/ai_native_math_learning_prd_v3.md`
  - `docs/architecture/ai_native_learning_system_architecture_v3.md`
  - `docs/architecture/daily_learning_runtime_contract_v1.md`
  - `docs/system/qa/latest.md`
  - `docs/system/qa/question_bank_grade_level_latest.md`
  - `data/knowledge_graphs/math/math_knowledge_graph_v2.md`
- project_boundary_overlay: stable for this PRD, provisional for exact technical
  storage and mastery thresholds
- output target: durable doc `docs/product/ai_native_math_learning_prd_v4.md`
- persistence reason: this PRD is the upstream contract for product structure,
  UX flow, technical plan, implementation blueprint, test-case design, and
  review gates
- downstream artifact expectation:
  - `PRODUCT_STRUCTURE_SPEC v4`
  - `UX_FLOW_SPEC v4`
  - `TECHNICAL_PLAN v4`
  - `ENGINEERING_CONTRACT`
  - `IMPLEMENTATION_BLUEPRINT`
  - `TEST_CASE_SPEC v4`
  - review and QA gates
- stop condition: `PRD_READY` or explicit blocking questions

## PRD Result Summary

- decision: Build a simple child-only adaptive math learning loop backed by a
  deterministic runtime and AI semantic judgment. Remove parent-web/dashboard
  thinking, fixed worksheets, manual parent grading, and hidden agent ceremony
  from the main product.
- target_actor_and_value:
  - Son: can independently review old knowledge, learn new graph-bound concepts,
    answer with text or photo, receive useful feedback, and continue without
    parent intervention.
  - Parent: can ask Codex what happened and receive evidence-backed progress,
    weak points, and system-improvement direction from persisted records.
- in_scope_capability_set:
  - daily review of old knowledge
  - graph-guided new knowledge learning
  - one current child step at a time
  - dynamic next-step selection after evidence
  - open answer and photo upload
  - AI answer analysis by reasoning, not string matching
  - targeted explanation, repair, and retest
  - 10-20 daily interactions as a budget, not a pre-generated list
  - question bank with at least 20 reviewed items per active graph node
  - structured learning records and daily summary
- out_of_scope:
  - parent Web dashboard
  - multi-user system
  - generic education SaaS/admin features
  - fixed daily worksheet generated up front
  - low-age arithmetic drills unless a narrow weakness is proven
  - Olympiad/competition track as mainline
  - automatic self-evolution that mutates graph, bank, mastery, or plan
  - external textbook/commercial question import without explicit source
- acceptance_evidence:
  - browser evidence for one-current-step child flow
  - DB/API evidence for saved attempts, jobs, analyses, decisions, and summary
  - semantic oracle samples for answer-only, wrong-reason-right-answer, stuck,
    blank, photo, and alternative-method cases
  - 10-20 interaction adaptive-day simulation with mixed outcomes
  - QA report that labels mock/recorded/live model scope
- confidence: confirmed for product direction; assumption-backed for exact
  mastery thresholds, storage split, and final copy/style
- critical_unknowns:
  - exact long-run mastery thresholds need real multi-day evidence
  - final record/log storage split between SQLite, report files, and model-output
    snapshots belongs to technical plan
  - live OCR quality on real handwritten photos must be tested
- downstream_route:
  1. 若命 writes `PRODUCT_STRUCTURE_SPEC v4`.
  2. 清秋 writes `UX_FLOW_SPEC v4`.
  3. 听云 writes `TECHNICAL_PLAN v4` and engineering contracts.
  4. 观止 upgrades test cases from the child-use perspective.
  5. 镜花 reviews runtime architecture and implementation fidelity.

## Project Boundary Overlay

Scope:

Single-child AI-native math learning system for summer bridge: primary-school
critical prerequisite repair plus Grade 7 math preview. Math only in this phase.

Status:

Stable for PRD v4 and downstream planning. Exact technical storage, model route
fallback policy, and mastery thresholds remain downstream design questions.

Sources:

- Current user decisions through 2026-07-11.
- `AGENTS.md`
- `docs/00_PROJECT_BLUEPRINT.md`
- `docs/domain-index/math-learning.md`
- `docs/system/qa/latest.md`
- `docs/system/qa/question_bank_grade_level_latest.md`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.md`

Known facts:

- Human users are exactly two: son and parent.
- Son interacts with a Web page only.
- Parent interacts with Codex only.
- The system and internal agents must finish a normal teaching loop without
  parent grading or parent intervention.
- Every diagnosis, teaching step, question, answer analysis, evaluation,
  planner decision, and report must bind to math graph nodes.
- The graph has 56 math nodes and is designed for Grade 7 bridge readiness:
  critical primary prerequisites, bridge models, Grade 7 mainline, and controlled
  extension.
- The active question bank currently has 1120 questions, 20 per audited node, and
  passed a scoped grade-level/content regression audit.
- Child answers are not unique-format. Correctness must be judged by answer,
  method, reasoning, process evidence, and alternate valid methods.
- Correct final answer with wrong or missing reasoning is not full mastery.
- Question selection must be efficient. Planner must not receive the full bank.
- Runtime owns state, persistence, async queue, idempotency, recovery, evidence
  gates, child-safe projection, and summaries.
- Internal agents own semantic analysis, teaching generation, and planning
  suggestions only after runtime supplies bounded inputs.
- Self-evolution is paused as an automatic mutator. It may propose changes, but
  cannot directly alter active graph, question bank, mastery, or next plan.

Assumptions:

- Local SQLite remains acceptable for the next cycle unless technical planning
  proves a measured blocker.
- The main model route for text judgment is GPT-compatible; photo/OCR may use a
  vision route through the model adapter. API keys stay out of docs and DB rows.
- The child normally studies about one hour per day.

Missing decisions:

- Exact final child copy and visual tone.
- Exact mastery thresholds after multiple real sessions.
- Exact persistence split for runtime facts, audit logs, model input/output
  snapshots, Markdown reports, and future query helpers.
- Whether every QA cycle uses live provider calls or recorded provider samples.

## PRD_SPEC - 若命（agentKey: `ruoming`）- 2026-07-11 CST

Objective:

Define the product contract for a usable daily adaptive math learning system in
which the son can complete old-knowledge review and new-knowledge learning with
AI-assisted judgment, targeted teaching, and automatic next-step decisions.

User / actor:

- Son: opens the Web page, reads one current step, answers with text/photo/stuck
  signal, receives feedback or next step, and finishes with a child-safe summary.
- Parent: asks Codex for learning progress, weak spots, evidence, and system
  improvement direction. The parent does not operate a Web dashboard or grade
  normal answers.
- Internal learning agents: hidden system components for question design/review,
  answer analysis, evaluation, planning, and teaching. They are not collaboration
  agents and are never visible to the child.
- Runtime/services: deterministic code that guarantees state transitions,
  persistence, recovery, child-safe projection, and evidence gates.

Scenario:

Each day the son opens the page. The system first handles old-knowledge review.
After enough prerequisite evidence is stable, the system can move to a graph-
guided new-knowledge step. Each visible step is selected only after considering
current evidence and graph state.

Problem:

The previous implementation drifted toward fixed batches, shallow or overly
mechanical questions, unclear waiting states, partial summaries, and too much
implicit reliance on model/agent behavior. A useful learning product must be
small but real: save evidence, judge reasoning, teach the weak point, pick the
next step, and report truthfully.

Desired outcome:

The son can complete a daily learning session without parent intervention. The
system identifies what he knows, what is unstable, what prerequisite broke, what
to teach next, and whether to retest, repair, continue, enter new knowledge, or
stop. The parent can later ask Codex and see an evidence-backed account.

Scope:

- One child Web surface.
- Daily old-knowledge review.
- Graph-guided new-knowledge learning.
- One current step visible at a time.
- 10-20 daily interactions as an adaptive budget.
- Dynamic next-step decision after each usable evidence package.
- Open answer text input.
- Photo upload for handwritten answers.
- Stuck/cannot-start signal.
- AI answer analysis that evaluates final answer, method, reasoning, process,
  alternative paths, units/symbols, and confidence.
- Evaluation of graph-node mastery across concept, model, procedure,
  calculation, expression, transfer, and stability.
- Teaching interventions for wrong, partial, answer-only, stuck, unclear, or
  prerequisite-broken evidence.
- Question bank active-use rules with at least 20 reviewed items per active
  graph node.
- Structured learning record and daily summary.
- Codex-readable progress/report facts.

Non-goals:

- No parent Web dashboard.
- No multi-user account system.
- No generic SaaS/admin analytics.
- No English in this cycle.
- No external textbook or commercial question import.
- No fixed paper/worksheet generated before answers are seen.
- No low-age arithmetic drills unless a narrow repair need is proven by evidence.
- No Olympiad/competition track as mainline. Controlled stretch is allowed only
  after prerequisite stability.
- No manual parent grading as normal flow.
- No automatic self-evolution that mutates active graph, bank, mastery, or plan.

Role-specific project rules:

- 若命 owns PRD, product structure, acceptance, and gate routing.
- 听云 owns technical architecture, engineering contract, implementation
  blueprint, skeleton, and implementation.
- 清秋 owns child-only UX flow, child-safe state design, copy/state clarity, and
  rendered UX review.
- 镜花 owns engineering review: runtime state machine, async/recovery,
  child-safe boundary, model adapter isolation, data/state contracts, and
  maintainability.
- 观止 owns test-case design and QA: child-flow continuity, semantic/model
  false-pass risk, browser evidence, and report truthfulness.

Source decisions and evidence:

| Claim | Tag | Source |
|---|---|---|
| Single child, math first, summer bridge | user_confirmed | `AGENTS.md`, blueprint |
| Parent uses Codex, no parent Web dashboard | user_confirmed | user decisions and v3 docs |
| Child flow must work without parent intervention | user_confirmed | user corrections in current thread |
| Daily work is old review plus new learning | user_confirmed | user latest product discussion |
| 10-20 daily interactions are adaptive, not fixed list | user_confirmed | user latest product discussion |
| Every item binds to graph node | user_confirmed | `AGENTS.md`, graph docs |
| Question bank needs 20 items per knowledge point | user_confirmed | user latest product discussion; current audit shows 20/node |
| Answer judgment must evaluate reasoning, not final string | user_confirmed | user corrections and domain index |
| Question selection must not feed full bank to model | user_confirmed | user efficiency concern and v3 PRD |
| Runtime must guarantee stable execution | user_confirmed | user correction: not only model/agent collaboration |
| Storage/log split is still TODO | assumption | inbox `MSG-20260710-001` |
| Next-question decision rules need a dedicated draft | assumption | inbox `MSG-20260711-001` |
| Live OCR quality is unproven | needs_validation | QA latest report |

PRD Question TODO:

| Question class | Answer / assumption | Status | Blocks downstream? |
|---|---|---|---|
| Actor | Son uses Web; parent uses Codex; internal agents hidden | answered | no |
| Trigger | Child opens page and continues or starts daily learning | answered | no |
| Main flow | review old knowledge -> answer -> analyze -> teach/repair -> next step -> optional new learning -> summary | answered | no |
| Surfaces | one child Web surface; Codex parent surface through persisted reports | answered | no |
| States | choose/continue, current_step, submitting, analyzing, feedback, teaching, blocked, summary, ready_for_new_knowledge | answered | no |
| Permissions | child sees child-safe handles only; parent/Codex can inspect internal evidence | answered | no |
| Data objects | graph node, question, step, attempt, photo, analysis, evaluation, decision, teaching package, summary | answered | no |
| Side effects | local DB/file writes and configured model calls only | answered | no |
| Quality bar | Grade 7 bridge, reasoning evidence, graph lineage, no low-age filler, no fake grading | answered | no |
| Acceptance | browser/API/DB/model-oracle/QA evidence listed below | answered | no |
| Non-goals | parent dashboard, fixed worksheets, multi-user, automatic self-evolution, external content import | answered | no |
| Storage split | SQLite vs logs vs snapshots to be decided by technical plan | assumed | no |
| Mastery thresholds | exact long-run thresholds after real data | assumed | no |

User stories / flows:

| ID | Story |
|---|---|
| US-01 | As the son, I open the page and see one clear next thing to do. |
| US-02 | As the son, I can answer in my own words or upload a photo of written work. |
| US-03 | As the son, if I am stuck, I can say so and receive a first useful hint or smaller step. |
| US-04 | As the son, I do not need my parent to approve or grade each answer. |
| US-05 | As the son, I get feedback on my thinking, not only whether the final number matches. |
| US-06 | As the son, after review is stable enough, I can learn a new graph-bound concept through explanation, interaction, and practice. |
| US-07 | As the system, I skip mastered nodes unless spaced confirmation is due. |
| US-08 | As the system, I return to prerequisites when a Grade 7 problem fails because the prerequisite chain is weak. |
| US-09 | As the parent, I ask Codex what happened and get confirmed, pending, blocked, and weak evidence clearly separated. |
| US-10 | As the system, I never call a pending, mock-only, stale, or missing-lineage result mastery. |

Core product flow:

```text
open child page
-> load or create daily flow
-> select one current graph-bound step
-> child answers with text/photo/stuck
-> save evidence immediately
-> run AI answer analysis asynchronously
-> validate evidence
-> update mastery/evaluation state
-> teaching/planner decides next action
-> show feedback, repair, retest, new knowledge, or summary
```

Old-knowledge review flow:

```text
build target pool from untested / unpassed / weak / prerequisite / due nodes
-> prefilter question candidates
-> show one current step
-> analyze answer
-> if mastered: skip or advance
-> if unstable: micro-teach or near-transfer retest
-> if prerequisite broken: rollback to prerequisite probe
-> if budget or safe stop reached: summarize
```

New-knowledge learning flow:

```text
prerequisite readiness check
-> select next graph node
-> essence explanation
-> core model
-> worked example
-> micro interaction
-> standard question
-> variant question
-> review/repair
-> near-transfer or stop
```

Next-step action set:

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

Acceptance criteria:

| ID | Scenario | Given | When | Then | Evidence required |
|---|---|---|---|---|---|
| AC-01 | Child opens page | No active step or resumable flow exists | Child loads `/` | Page shows a child-safe choose/continue state | Browser screenshot, API payload |
| AC-02 | One current step | Target pool has candidates | Planner selects next item | Child sees exactly one step, not a fixed worksheet | API payload, screenshot, `flow_step` |
| AC-03 | Question candidate efficiency | Planner needs a question | Service builds candidate packet | Planner receives compact metadata, not full bank | candidate count/context metadata |
| AC-04 | Text answer save | Current step is visible | Child submits text | Attempt is saved quickly and review job starts | attempt row, job row, response |
| AC-05 | Photo answer save | Child uploads work photo | System saves submission | Photo is stored; OCR/vision is untrusted until validated | attachment row, OCR confidence |
| AC-06 | Stuck signal | Child cannot start | Child clicks/writes stuck | System gives hint, micro-teach, or prerequisite probe | child response, teaching package |
| AC-07 | Correct with reasoning | Answer and process are sound | Analysis/evaluation run | Node may improve but one answer alone is not durable mastery unless prior evidence supports it | answer analysis, mastery decision |
| AC-08 | Correct answer only | Final answer present, reasoning missing | Analysis runs | Process gap is recorded; no full mastery | analysis comparison, next decision |
| AC-09 | Wrong reason right answer | Final answer happens to be right with invalid reasoning | Analysis runs | Result is partial/wrong according to rubric; planner repairs | semantic oracle, decision |
| AC-10 | Alternative valid method | Child uses a different valid solution | Analysis runs | Method is accepted when mathematically valid | answer analysis status |
| AC-11 | Prerequisite gap | Grade 7 step fails due to prior node | Planner runs | System probes or teaches prerequisite, not blind same-type drill | graph chain, next decision |
| AC-12 | Low-age drill risk | Candidate is mechanical arithmetic below level | Review/selection runs | Candidate rejected unless narrow repair evidence exists | question review metadata |
| AC-13 | Mastered node skip | Node is stable and not due | Target pool builds | Node skipped with auditable reason | target pool audit |
| AC-14 | New knowledge gate | Review prerequisites are stable enough | Planner considers next node | System shows ready/new-learning transition | prerequisite summary |
| AC-15 | New knowledge misunderstanding | Micro-check fails | Teaching check runs | System teaches the first break before more practice | teaching package |
| AC-16 | Slow model | Analysis is pending | Next step requested | Runtime waits if dependent or chooses independent safe step excluding pending evidence | pending status, decision reason |
| AC-17 | Model not configured | Evaluator config missing | Child submits | Attempt remains pending/blocked with operator-visible reason; no fake grade | route status, job/error row |
| AC-18 | Blank evidence | Child submits blank/no photo/no stuck | Submission/validation runs | System asks for evidence or blocks; no mastery update | validation result |
| AC-19 | Symbol/unit/procedure issue | Model is right but sign/unit/bracket/procedure wrong | Analysis runs | Partial understanding preserved; smallest repair selected | analysis dimensions |
| AC-20 | Daily summary | Budget reached or safe stop | Summary generated | Child sees confirmed/weak/pending next direction; Codex sees evidence details | summary artifact, source ids |
| AC-21 | Parent progress query | Parent asks Codex | Codex reads persisted records | Response distinguishes confirmed, pending, blocked, inferred, stale, mock-only, missing-lineage | report/DB evidence |
| AC-22 | Full adaptive day | QA runs 10-20 mixed interactions | Flow completes | No fixed-list regression; all next steps trace to evidence/decision | browser trace, DB/API facts |
| AC-23 | Recovery | Server restarts with pending jobs/attempts | Bootstrap/recovery runs | No duplicate attempts/jobs/decisions; blocked states are honest | DB before/after |
| AC-24 | Child-safe projection | Any child route returns payload | Payload/DOM inspected | No graph ids, question ids, attempt ids, model/provider names, rubrics, queue internals | API scan, DOM scan |
| AC-25 | Report freshness | Report exists | QA or Codex uses it | Stale reports cannot be used as current pass evidence | report timestamp vs DB state |

Data / state meaning:

| Object | User/product meaning |
|---|---|
| `math_graph_node` | A teachable/diagnosable knowledge point and prerequisite relation. |
| `question_bank_item` | A graph-bound reviewed question that can expose reasoning evidence. |
| `daily_flow` | Today's learning container and state machine. |
| `flow_step` | One visible child step: question, teaching, micro-check, clarification, or summary. |
| `attempt` | Child evidence for one visible step, including text/photo/stuck. |
| `answer_analysis` | AI semantic judgment of answer, method, reasoning, process gap, and feedback seed. |
| `evaluation_update` | Mastery-state update from usable evidence only. |
| `next_step_decision` | Planner decision with reason and source evidence. |
| `teaching_package` | Child-safe explanation, hint, contrast, worked example, or micro-check. |
| `learning_record` | Queryable trace of what happened and why. |
| `daily_summary` | Child-safe finish plus Codex-readable evidence facts. |

Evidence vocabulary:

- `confirmed`: current usable evidence supports the claim.
- `pending`: needed evidence is saved but not yet analyzed or validated.
- `blocked`: system could not analyze or decide safely.
- `inferred`: plausible, but not directly proven by current evidence.
- `stale`: evidence belongs to old graph/bank/runtime version.
- `mock_only`: only deterministic/mock evidence exists.
- `missing_lineage`: source graph/question/step/attempt chain is incomplete.

External side effects:

- Allowed: local DB/file writes, local uploaded-answer storage, configured model
  API calls through model router.
- Forbidden without explicit authorization: external publishing, cloud
  deployment, account writes, external content import, destructive reset of real
  learning data, exposing API keys/secrets.

Model/content quality bar:

- Questions must match an incoming Grade 7 learner, not insult him with low-age
  mechanical filler.
- Calculation repair is allowed only when evidence identifies a calculation
  weakness, and even then the task must expose rule/process/transfer evidence.
- Each active graph node should have at least 20 reviewed question items with
  varied families and evidence goals; the daily flow selects dynamically.
- Question difficulty is defined by concept load, model abstraction, step-chain
  length, transfer distance, representation transfer, distractor strength,
  prerequisite load, expression/check requirement, and wrong-model risk.
- Answer Analysis must judge final answer, relation/model, steps, units/symbols,
  check/explanation, alternative methods, process gap, confidence, and error
  tags.
- Evaluation must distinguish concept, model, procedure, calculation,
  expression, transfer, and stability.
- Teaching must identify the first cognitive break and then give a small,
  actionable next step.
- Planner must not receive full question bank content. It receives a compact
  candidate packet after deterministic prefiltering.

UX constraints:

- One child surface.
- One current step visible.
- No parent-facing dashboard.
- No visible internal agent names, graph ids, question ids, attempt ids,
  model/provider names, rubrics, queue internals, or Codex instructions.
- Child copy must be age-respectful for an incoming Grade 7 student.
- Waiting states must be honest and short. Do not say "rest and wait" while a
  configuration failure is hidden.
- Feedback must cover all relevant wrong/partial steps in a session, not only
  the last submitted question.

Permissions / security:

- Child routes use current-step handles/positions, not raw internal ids.
- Codex/operator surfaces may inspect internal ids and evidence.
- API keys and secrets remain outside docs, DB rows, reports, screenshots, and
  model audit payloads.
- Uploaded answer photos stay local unless explicitly authorized otherwise.

Failure / recovery:

- Save answer before model analysis.
- Analysis runs async when possible.
- If analysis is slow, runtime either waits for dependent evidence or chooses an
  independent safe step while excluding pending evidence.
- If model route is missing or fails, persist operator-visible failure and show
  child-safe message. Do not fake grading.
- If OCR/vision confidence is low, ask for clearer evidence or written
  explanation. Do not infer mastery from guessed photo content.
- On restart, recover queued/running/stale jobs, pending attempts, completed but
  unapplied model outputs, and flows waiting for summary.
- Repeated polling or double submit must not duplicate attempts, jobs, mastery
  updates, next-step decisions, or summaries.

Rollout / rollback:

- v4 is the next product baseline.
- Implementation should be staged behind feature flag or equivalent runtime
  guard if legacy flow still exists.
- Preserve existing real learning data.
- Test DB reset is allowed only in explicit test scope.
- If v4 runtime fails, child page should show safe blocked/retry state and
  operator/Codex should see the reason.

Assumptions allowed forward:

- SQLite/local file storage is acceptable for next technical planning.
- Exact mastery thresholds can start conservative and be revised after real
  multi-day evidence.
- The next implementation slice may prioritize old-knowledge review hot path
  before full new-knowledge teaching intelligence, as long as the PRD states are
  represented and test hooks exist.
- Daily 10-20 is a normal budget, not a hard promise when evidence is blocked,
  the child stops, or a teaching repair requires a safe early summary.

Open questions:

- What exact visual/copy tone should the child page use after 清秋 drafts UX v4?
- How much model input/output should be snapshotted for later Codex query versus
  stored as compact structured facts?
- What are the first conservative mastery thresholds before real multi-day data?
- Which recorded/live model samples become the semantic QA oracle set?

Required artifacts:

- `PRODUCT_STRUCTURE_SPEC v4`
- `UX_FLOW_SPEC v4`
- `TECHNICAL_PLAN v4`
- `ENGINEERING_CONTRACT`
- `IMPLEMENTATION_BLUEPRINT`
- `TEST_CASE_SPEC v4`
- Review reports from 镜花 and QA reports from 观止

Required gates:

- 若命 PRD/product structure review
- 清秋 UX flow/review for child surface
- 听云 technical plan, engineering contract, blueprint, skeleton, implementation
- 镜花 architecture/code review
- 观止 test-case source readiness, test case spec, and QA

PRD_QUALITY_GATE:

- verdict: `PRD_QUALITY_READY`
- conclusion_summary_precise: pass
- user_problem_value_specific: pass
- scope_and_non_goals_bounded: pass
- functional_surface_state_routed: pass
- acceptance_verifiable: pass
- evidence_traceability_complete: pass
- assumptions_unknowns_visible: pass
- downstream_handoff_complete: pass
- risks_side_effects_recovery_covered: pass
- project_boundary_fit_checked: pass
- product_quality_evidence:
  - scope -> user decisions + `AGENTS.md`
  - graph requirement -> `math_knowledge_graph_v2.md`
  - current system risk -> `docs/system/qa/latest.md`
  - question bank coverage -> `question_bank_grade_level_latest.md`
  - runtime simplification -> user decision + v3 architecture/runtime contract
  - downstream gates -> collaboration role contracts and PRD playbook
- blocking_quality_gaps: none for PRD. Exact UX copy, storage split, mastery
  thresholds, and live model/OCR quality are routed downstream and do not block
  product readiness.
- REFUSAL_FEEDBACK: not required

PRD_READINESS_GATE:

- verdict: `PRD_READY`
- can_tingyun_plan_without_guessing: yes
- can_qingqiu_spec_ux_without_guessing: yes
- can_data_rules_be_handled_without_guessing: yes
- can_guanzhi_write_tests_without_guessing: yes
- can_jinghua_review_scope_without_guessing: yes
- required_next_artifact: `PRODUCT_STRUCTURE_SPEC v4`
- blocking_questions: none
- assumptions_allowed_forward:
  - SQLite acceptable unless technical plan proves blocker.
  - Exact mastery thresholds start conservative and are updated after evidence.
  - Storage/log split is a technical design decision constrained by this PRD's
    learning-record requirements.
  - New-knowledge intelligence may be staged after review hot path if UX/API/test
    hooks preserve the full product contract.
- REFUSAL_FEEDBACK: not required

Stop condition:

This PRD is ready for multi-role review and then `PRODUCT_STRUCTURE_SPEC v4`.
It does not authorize implementation by itself. Implementation starts only after
the required downstream artifacts and gates are complete or explicitly waived.
