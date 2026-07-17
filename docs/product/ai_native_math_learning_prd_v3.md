# AI Native Math Learning System PRD v3

Status: reviewed baseline, ready for technical planning
Owner: 若命 (`ruoming`)
Created: 2026-07-10 CST
Supersedes: `docs/product/ai_native_math_learning_prd_v2.md`
Review log: 清秋 `UX_REVIEW_PASS_WITH_SCOPE`; 镜花 `DESIGN_REVIEW_PASS_WITH_SCOPE`; initial 霜弦 `DATA_REVIEW_NEEDS_FIX` fixed; focused 霜弦 `DATA_REVIEW_PASS_WITH_SCOPE`; focused 观止 `QA_REVIEW_PASS`; focused 听云 `TECH_PLAN_READY`.

This PRD defines the next product baseline for the single-child AI-native math
learning system. It corrects the older "fixed 10-task round" direction and
replaces it with a graph-driven daily adaptive learning flow:

```text
old-knowledge review -> new-knowledge learning
```

The child sees one current step at a time. The system analyzes each meaningful
response, updates graph-bound evidence, and then decides the next step.

## Evidence Sources

- Current user decisions in this Codex thread through 2026-07-10.
- `AGENTS.md`
- `docs/00_PROJECT_BLUEPRINT.md`
- `docs/domain-index/math-learning.md`
- `docs/architecture/ai_native_learning_system_architecture_v3.md`
- `docs/architecture/daily_learning_runtime_contract_v1.md`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.md`
- Existing v2 docs under `docs/product/` and `docs/architecture/`.

## PROJECT_BOUNDARY_OVERLAY - 若命 (`ruoming`) - 2026-07-10 CST

Scope:

Single-child AI-native math learning system for summer bridge: primary-school
critical prerequisite repair plus Grade 7 math preview. Math only in this phase.

Status:

Stable for v3 product and technical planning after first multi-role review
fixes. Not implementation-ready until updated `UX_FLOW_SPEC`,
`DATA_CONTRACT_SPEC`, `TECHNICAL_PLAN`, `ENGINEERING_CONTRACT`, and
`TEST_CASE_SPEC` are produced and reviewed.

Sources:

- User decisions through 2026-07-10.
- `AGENTS.md`
- `docs/architecture/ai_native_learning_system_architecture_v3.md`
- `docs/architecture/daily_learning_runtime_contract_v1.md`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- Review feedback from 清秋、霜弦、镜花、观止、听云.

Assumptions:

- One child, local/private phase, math first.
- SQLite/local evidence ledger remains acceptable unless technical planning
  proves a measured blocker.
- Model providers are available through a router/adapter, not direct agent calls.
- New-learning default path follows the math graph core/selective-core path and
  can be adjusted by Codex/operator discussion when evidence suggests a better
  path.

Missing decisions:

- Final child visual style and copy.
- Exact long-run mastery thresholds after real multi-day evidence.
- Final storage shape for question specs and agent knowledge packs.
- Whether every QA cycle uses live provider calls or recorded provider samples.

Stable product facts:

- Human users are exactly two: the son and the parent.
- The son uses one Web child surface.
- The parent uses Codex only.
- There is no parent Web dashboard.
- Normal learning must not require parent intervention.
- Parent/Codex can inspect progress, ask what happened, discuss system
  direction, and authorize product/technical changes.
- Codex is not a runtime result container. Runtime outputs must be persisted to
  DB/report artifacts before Codex summarizes them.
- Every teaching, diagnosis, question, answer, evaluation, plan, report, and
  future improvement proposal must bind to math graph nodes.
- The daily learning order is:
  `old-knowledge review -> new-knowledge learning`.
- Daily review has a 10-20 question/interaction budget, but this is not a fixed
  pre-generated list.
- The child sees one current step at a time.
- The next step is selected after reading the latest usable evidence.
- New knowledge is not a homepage peer action by default. It appears as a gated
  transition after review/precondition checks, or as a resume action when a
  valid new-knowledge flow is already in progress.
- Mastered graph nodes are skipped unless spaced confirmation is due.
- Low-age mechanical drills are forbidden unless recent evidence proves a narrow
  repair need.
- Answer photos are supported, but OCR/vision output is untrusted evidence until
  confidence and transcript are validated.
- Correct final answer without sound reasoning is not full mastery.
- Self-evolution is paused as an automatic mainline mutator. It may archive
  evidence and propose changes, but cannot directly alter active bank, graph,
  mastery, or next plan.

Runtime/product constraints:

- Runtime owns state, persistence, idempotency, recovery, child-safe projection,
  evidence gates, and fail-closed behavior.
- Agents own semantic judgment and teaching generation only.
- Question selection must be efficient. Planner must not receive or search the
  full question bank in the hot path.
- Question Bank Service must pre-filter candidates and pass only a compact
  candidate packet, normally 5-8 question metadata rows for the current target.
- Model calls must record context size, latency, timeout, retry, fallback mode,
  and validation result.

Protected data and side effects:

- Do not delete real attempts, uploads, model outputs, review records, or reports
  without explicit authorization.
- Test DB reset is allowed only in explicit test scope.
- API keys and secrets must never be written into docs, DB, reports, screenshots,
  or model audit rows.
- No external textbook or commercial question-bank ingestion is authorized.

Role-specific project rules:

| Role | Product responsibility in this cycle |
|---|---|
| 若命 | Own PRD, product boundaries, acceptance, and product structure. |
| 听云 | Convert PRD/runtime contract into technical plan, engineering contract, skeleton, and implementation. |
| 清秋 | Define child-only UX flow and review child-facing states. |
| 霜弦 | Review graph, question bank, answer-analysis evidence, rubric, lineage, and reports. |
| 镜花 | Review runtime architecture, state machine, async/recovery, child-safe boundary, and model adapter isolation. |
| 观止 | Produce test cases and QA evidence from real child-use paths, including false-pass defenses. |

Invalidation trigger:

Update this PRD if user roles change, parent Web dashboard becomes in scope,
external content is authorized, daily learning order changes, or implementation
evidence proves the adaptive flow needs product-level revision.

## PRD_SPEC - 若命 (`ruoming`) - 2026-07-10 CST

Objective:

Define the product contract for a usable daily adaptive math learning system that
lets the son independently review old knowledge, learn new graph-bound concepts,
answer openly or with photos, receive AI-assisted review, and continue to the
next appropriate step without parent intervention.

User / actor:

- Son: opens the Web page, continues the current step, chooses old-knowledge
  review when offered, and enters new-knowledge learning only when the system
  exposes it as a gated next action.
- Parent: asks Codex about progress, evidence, problems, and system improvement
  direction.
- Internal agents: hidden system agents for planning, answer analysis,
  evaluation, teaching, question design/review, and proposal-only evolution.
- Runtime/services/gates: deterministic framework that makes the agent system
  stable, auditable, child-safe, and recoverable.

Problem:

The prior system mixed product logic, runtime behavior, agent judgment, and QA
evidence. It drifted toward fixed batches, shallow questions, unclear waiting
states, parent-dependent recovery, and model calls that risked being slow or
over-broad. The product must become a real teaching flow, not a demo or a
question-list batch processor.

Desired outcome:

Each day, the son can:

1. Open the child page.
2. Review old knowledge through adaptive, graph-bound steps.
3. Skip graph nodes already mastered.
4. Repair weak or untested prerequisites before learning new nodes.
5. Learn a new graph node through explanation, interaction, practice, review,
   and targeted repair.
6. Stop with a clear summary of confirmed knowledge, weak spots, pending
   evidence, and next direction.

The parent can ask Codex for progress and get a truthful evidence-backed answer.

Scope:

- One child Web page.
- Daily adaptive learning flow:
  - old-knowledge review first;
  - new-knowledge learning second when prerequisites are stable enough.
- Review mode:
  - 10-20 question/interaction budget;
  - one visible current step;
  - next step selected after latest evidence;
  - candidate sources: untested nodes, unpassed nodes, weak-confirmation nodes,
    prerequisites for upcoming new learning, newly taught nodes, spaced checks.
- New-knowledge mode:
  - graph node selected by prerequisite readiness;
  - teaching follows node contract: essence, core model, rule derivation,
    examples, variation boundary, micro-check;
  - system reacts to the micro-check before continuing.
- Open answer input and photo upload.
- AI-assisted answer analysis, including final answer, method, process,
  alternative solution, units/symbols, check/explanation, error tags, confidence,
  and process gap.
- Evaluation of graph-node mastery across dimensions:
  concept, model, procedure, calculation, expression, transfer, stability.
- Planner next-step decision:
  continue review, same-structure retest, near-transfer retest, prerequisite
  probe, micro-teach, enter new knowledge, ask clarification, or summarize.
- Teaching intervention:
  wrong-attempt repair, concept teaching, contrast cases, worked example,
  scaffold, micro-check.
- Codex-readable reports based on persisted DB/report evidence.
- Question bank active-use workflow:
  normal hot path selects from reviewed active bank;
  question design/review agents run as async bank maintenance, not per-step
  child-blocking generation.

Default new-learning path policy:

- The first v3 planning path starts from graph nodes marked core/selective-core
  for Grade 7 bridge readiness.
- The planner selects the next learnable node only after checking prerequisite
  stability.
- If multiple graph paths are available, priority goes to the path whose
  prerequisites are most stable and whose next node best supports Grade 7
  preview.
- Codex/operator may discuss and adjust the preferred path, but the child does
  not freely choose arbitrary graph branches from the Web page.
- Path changes must be auditable and must not reinterpret old attempts without
  graph-version handling.

First implementation slice:

- Technical planning covers full v3 product direction.
- First implementation slice must deliver the v3 core runtime skeleton and
  old-knowledge review hot path:
  `daily_flow`, `flow_step`, current-step child API, review target pool,
  compact candidate packet, answer persistence, answer analysis hook, evidence
  gate, node-state update hook, planner next-step decision, child-safe summary,
  idempotency, and recovery hooks.
- New-knowledge learning in the first slice must at least include
  `ready_for_new_knowledge` state, teaching-step shell, and test hooks. Full
  concept-teaching intelligence can be a later slice after UX/DATA/TECH
  contracts are reviewed.
- Bank maintenance, Codex skills, and proposal-only self-evolution are not P0
  completion criteria for the first implementation slice.

Non-goals:

- No parent Web dashboard.
- No multi-user account system.
- No SaaS/admin/productized analytics.
- No English implementation in this cycle.
- No external textbook/commercial question import.
- No fixed daily worksheet generated up front.
- No Olympiad track as mainline; controlled stretch only.
- No manual parent grading as normal product flow.
- No automatic self-evolution mutating production behavior.

Project boundary overlay:

Use the overlay above as product law for downstream work.

Role-specific project rules:

- 听云 must consume this PRD and the runtime contract before writing the technical
  plan.
- 清秋 must design one child surface, not a dashboard or product landing page.
- 霜弦 must reject untraceable questions, weak rubrics, missing graph lineage,
  fake active-use claims, and overclaimed reports.
- 镜花 must reject runtime designs where agents directly mutate state or where
  pending/invalid/stale evidence can drive planning.
- 观止 must reject QA that only proves the UI can click through.

User stories / flows:

| ID | Story |
|---|---|
| US-01 | As the son, I open the page and see whether to continue a current step, start old-knowledge review, or enter a system-approved new-knowledge step. |
| US-02 | As the son, when I choose review, I see one current question or interaction, not a long fixed paper. |
| US-03 | As the son, after I submit an answer/photo, my work is saved and the system chooses the next appropriate step. |
| US-04 | As the son, if I am stuck, I can express that and receive a small useful hint or repair step. |
| US-05 | As the son, if I already know a graph node well, the system does not force me to repeat it. |
| US-06 | As the son, when I learn new knowledge, I first get a short explanation, then an interaction, then practice and review. |
| US-07 | As the parent, I ask Codex what happened today and get evidence-backed progress, not a vague summary. |
| US-08 | As the system, I do not treat a correct final answer without reasoning as full mastery. |
| US-09 | As the system, I do not plan from pending, invalidated, stale, malformed, or mock-only evidence. |
| US-10 | As the system, I keep model calls small and fast by pre-filtering candidate questions before planner selection. |

Main child flow:

```text
open page
-> load or create daily flow
-> choose/continue old-knowledge review
-> build graph-bound target pool
-> select one current step
-> child responds
-> answer analysis / teaching check
-> evidence gate
-> update affected graph-node mastery
-> planner chooses next step
-> repeat, teach, enter new knowledge, or summarize
```

Late evidence reconciliation:

- If a model/OCR result arrives after runtime already moved the child to an
  independent safe step, the late result is recorded immediately but applied to
  mastery/planning only at a safe transition point.
- A safe transition point is: current step submitted, current teaching
  interaction completed, child returns to summary, or runtime explicitly pauses.
- Late evidence must not rewrite the prompt or expected answer of a step the
  child is currently answering.
- If late evidence makes the current plan stale, runtime writes an auditable
  reconsideration and chooses the next safe step after the current step ends.
- Reports must label whether a plan/summary included or excluded late evidence.

New-knowledge flow:

```text
prerequisite readiness check
-> select next learnable graph node
-> essence explanation
-> core model
-> rule derived from model
-> quick interaction
-> standard question
-> variant question
-> review/repair
-> near-transfer or stop
```

Acceptance criteria:

| ID | Scenario | Given | When | Then | Evidence required |
|---|---|---|---|---|---|
| AC-01 | Child starts today | No active visible step or an existing daily flow | Child opens `/` | Page shows choose/continue state without internal ids or parent action | Browser screenshot, API payload, DB `daily_flow` |
| AC-02 | Child starts review | Daily flow exists | Child selects "复习旧知识" | Runtime creates/resumes review mode and builds graph-bound targets | DB flow/target rows, graph version |
| AC-03 | One-step display | Review target pool exists | Planner selects next step | Child sees exactly one current step, not a full fixed list | Child payload, `flow_step`, screenshot |
| AC-04 | Candidate efficiency | Planner needs a question | Question Bank Service prepares candidates | Planner receives a compact packet, not full bank content | agent run metadata: candidate count/context size |
| AC-05 | Submit text answer | Current step is visible | Child submits answer with reasoning | Response is saved idempotently and analysis starts | attempt row, receipt, job/agent run |
| AC-06 | Submit photo answer | Child uploads paper work | System processes response | Photo is stored; OCR/vision is treated as untrusted evidence with confidence | attachment row, OCR package, analysis metadata |
| AC-07 | Correct with reasoning | Child answer is correct and process sound | Analysis/evaluation runs | Node may improve but one answer alone cannot mark stable mastery unless prior evidence supports it | answer analysis, mastery decision |
| AC-08 | Correct answer only | Child gives final answer without process where process is required | Analysis runs | System flags process gap and asks for explanation/retest; no full mastery | answer analysis comparison, planner decision |
| AC-09 | Wrong model | Child uses wrong relation/model | Analysis/evaluation/planner run | Planner chooses contrast, reteach, prerequisite probe, or rollback, not blind same-type drill | process gap, graph chain, next-step decision |
| AC-10 | Pending evidence | Model/OCR is slow or uncertain | Next step is needed | Runtime waits only if dependent; otherwise chooses independent safe step without using pending evidence | pending status, selected step reason |
| AC-11 | New knowledge entry | Review targets are sufficiently handled | Planner considers new node | System enters new knowledge only if prerequisite chain is stable enough or repair plan exists | prerequisite summary, planner decision |
| AC-12 | New knowledge interaction fails | Child misses quick interaction | Teaching check runs | System repairs with micro-teach/contrast/prerequisite probe, not more practice as if taught | teaching package, next-step decision |
| AC-13 | Mastered node skip | A node is stable and not due | Target pool builds | Node is skipped and skip reason is auditable | target pool audit |
| AC-14 | Model route failure | Evaluator config missing or incompatible | Child submits answer | Attempt remains pending/blocked with clear operator reason; no fake grading | review meta, route status, child-safe message |
| AC-15 | Daily summary | Daily budget satisfied or safe stop reached | Summary generated | Child sees confirmed points, weak points, pending items, and next move; Codex can inspect details | summary artifact, source step ids |
| AC-16 | Parent progress query | Parent asks Codex for progress | Codex reads DB/report | Response labels confirmed/pending/blocked/inferred/stale/mock_only/missing_lineage facts and cites evidence scope | report artifact, DB facts |
| AC-17 | QA false-pass defense | QA claims full pass | 观止 runs tests | Report must include browser evidence, DB/API facts, semantic checks, provider mode, and no stale report mismatch | QA report, screenshots, DB samples |
| AC-18 | Late evidence reconciliation | Runtime chose an independent safe step while a prior analysis was pending | Prior analysis arrives later | Late evidence is recorded and can affect mastery/planning only at a safe transition point; it cannot rewrite the child’s current visible step mid-answer | job completion, reconciliation audit, next-step decision |
| AC-19 | Correct final answer with wrong reasoning | Child reaches right answer through wrong/circular reasoning | Analysis runs | Result is partial or wrong according to rubric, process gap is recorded, and planner selects repair/retest instead of mastery | answer_analysis comparison, planner decision |
| AC-20 | Stuck or cannot start | Child indicates stuck or gives no meaningful start | Runtime/analysis handles response | System gives a first-step hint, micro-teach, or prerequisite probe without inventing mastery | child response, teaching package, planner branch |
| AC-21 | Blank or unusable evidence | Child submits blank text and no usable photo | Submission/analysis runs | System asks for evidence or marks pending/blocked; no mastery/planning conclusion is derived | validation verdict, child-safe message |
| AC-22 | Symbol/unit/procedure issue | Child has sound model but wrong symbol, unit, sign, bracket, or local procedure | Analysis/evaluation runs | Partial understanding is preserved and the smallest repair target is selected | answer_analysis dimensions, mastery decision |
| AC-23 | Readable photo | Child submits a clear paper-work photo | OCR/vision and answer analysis run | OCR transcript/math objects are stored with confidence and may support analysis when usable | attachment, OCR package, analysis |
| AC-24 | Unclear photo | Child submits unclear photo-only evidence | OCR/vision is low confidence | System asks for clearer photo or written explanation; evidence does not drive mastery | OCR usability, pending reason, child prompt |
| AC-25 | Continuous adaptive day | QA runs a 10-20 step day | Mixed correct, wrong, stuck, photo, and slow-model cases occur | Flow remains one-current-step adaptive, skips mastered nodes, avoids fixed-list regression, and produces evidence-scoped summary | browser trace, DB/API facts, planner decisions |
| AC-26 | Review to new knowledge bridge | Old-review high-priority targets are cleared enough | Planner considers next node | `ready_for_new_knowledge` is reached before `learning_new`; child sees a gated transition, not an unrestricted homepage choice | flow status transition, prerequisite summary |

Data / state meaning:

| Object | User/product meaning |
|---|---|
| `daily_flow` | Today's learning container. It controls current mode and one visible current step. |
| `flow_step` | One visible child step: question, teaching, interaction, clarification, or summary. |
| `review_target` | A graph node candidate selected for old-knowledge review. |
| `question_candidate_package` | Designer-produced candidate; never child-schedulable by itself. |
| `question_review_record` | Durable reviewer verdict and active-use evidence for a candidate/current question. |
| `active_question_slot` | Current, reviewed, graph-bound, schedulable question slot. |
| `attempt` | Child response evidence for a visible step. |
| `answer_analysis` | Structured judgment of one response. |
| `mastery_decision` | Evaluation of affected graph-node state from valid evidence. |
| `next_step_decision` | Planner decision explaining what happens next and why. |
| `teaching_package` | Child-safe explanation or micro-interaction from Teaching Agent. |
| `daily_summary` | Child-safe summary plus Codex-readable evidence facts. |

Canonical evidence/status vocabulary:

`usable` is a predicate, not a stored status. An attempt is usable for
mastery/planning/report-confirmed claims only when all required status fields and
gates pass.

| Layer | Field | Allowed values | Can drive mastery/planning? |
|---|---|---|---|
| Attempt evidence | `evidence_status` | `active`, `invalidated`, `stale` | only `active` |
| Attempt grading | `grading_status` | `pending_review`, `graded`, `blocked` | only `graded` |
| Analysis validation | `analysis_status` | `missing`, `valid`, `invalid_analysis`, `low_confidence`, `mock_only`, `operator_attention_required` | only `valid` with non-mock evidence |
| Evidence validation | `evidence_validation` | `usable`, `pending`, `rejected`, `blocked` | only `usable` |
| Daily flow | `daily_flow.status` | `new`, `reviewing`, `ready_for_new_knowledge`, `learning_new`, `paused`, `completed`, `blocked`, `superseded` | n/a |
| Flow step | `flow_step.status` | `selected`, `displayed`, `responded`, `analyzing`, `evaluated`, `superseded`, `blocked` | only through validated evidence |
| Report claim | `report_label` | `confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`, `missing_lineage` | only `confirmed` |

Pending, invalidated, stale, mock-only, missing-lineage, low-confidence, or
operator-attention evidence can trigger waiting, clarification, repair, blocked
state, or an independent safe step. It cannot update mastery or produce a
confirmed planning conclusion.

Graph version and lineage:

- `graph_version` is the graph asset version plus a content hash computed from
  the active math graph file.
- Every graph-bound product/evidence artifact must carry `graph_node_id` and
  `graph_version`: question candidate, review record, active question slot,
  review target, flow step, attempt, answer analysis, mastery decision,
  next-step decision, teaching package, daily summary, and report claim.
- If graph version changes, old attempts/questions remain auditable but are
  `stale` for current planning until a migration/compatibility rule revalidates
  them.
- Report claims must name whether they are based on current graph evidence,
  migrated evidence, inferred evidence, or missing lineage.

Question active-use objects:

| Object | Required proof |
|---|---|
| `question_candidate_package` | `node_id`, `graph_version`, evidence goal, difficulty vector, rubric, valid solution paths, common wrong paths, target error tags, rollback candidates |
| `question_review_record` | reviewer agent key/version, candidate id, item version, verdict, rejection reasons if any, active-use rule version |
| `active_question_slot` | current `item_version`, `source_type`, `graph_version`, `review_record_id`, `active_eligible=true`, `question_family`, `variant_signature`, cooldown group, duplicate group, rubric, solution evidence |

Candidate packet contract:

The planner hot path receives only a compact packet produced by Question Bank
Service after active-use filtering.

Required candidate packet fields:

- `question_id`
- `node_id`
- `graph_version`
- `item_version`
- `review_record_id`
- `question_family`
- `variant_signature`
- `difficulty_vector`
- `evidence_goal`
- `target_error_tags`
- `requires_reasoning`
- `last_used_at`
- `why_candidate`
- `filter_summary`

The packet must exclude stale, inactive, duplicate/cooldown-violating, and
metadata-only-approved questions before the planner sees them.

Answer analysis contract:

Required dimensions:

- `final_answer`
- `model_or_relation`
- `steps`
- `symbols_units`
- `check_or_explanation`
- `alternative_validity`

Allowed comparison statuses:

- `matched`
- `missing`
- `incorrect`
- `unclear`
- `alternative_valid`

Required analysis fields:

- `process_gap`
- canonical `error_tags` from the project taxonomy
- `blocking_evidence`
- OCR usability package when a photo is present
- `confidence`
- provider/model route metadata
- prompt/schema version
- child feedback seed

This output is the minimum input for evaluation and planning. Missing or invalid
fields keep the evidence out of mastery/planning.

Report labels:

All child summaries and Codex reports must separate:

- `confirmed`
- `pending`
- `blocked`
- `inferred`
- `stale`
- `mock_only`
- `missing_lineage`

External side effects:

- Local DB/file writes and configured model API calls are allowed.
- Uploaded answer photos stay local.
- No external platform publishing, cloud deployment, account write, or content
  import is in scope.

Model/content quality bar:

- Questions must expose reasoning, not only final answer.
- Difficulty is defined by concept load, model abstraction, step-chain length,
  transfer distance, representation transfer, distractor strength, prerequisite
  load, expression/check requirement, and common wrong-model risk.
- `question_designer_agent` creates candidate packages only.
- `question_reviewer_agent` is active-use gate.
- Planner hot path receives a small candidate packet only.
- Answer Analysis must handle alternative valid methods and wrong-reason-right
  answer cases.
- Evaluation must not call one correct answer stable mastery.
- Teaching must identify the first cognitive break and provide a micro-check.

UX constraints:

- One child Web surface.
- One current step visible.
- Child-safe text only.
- Open answer textarea and photo upload supported.
- No graph ids, question ids, attempt ids, model/provider names, agent names,
  rubric internals, queue internals, Codex instructions, or parent action.
- Waiting states must be honest and useful.
- UI should feel age-respectful for an incoming Grade 7 student, not childish.

Permissions / security:

- Child APIs use current step handles/positions, not raw internal ids.
- Operator/Codex APIs may expose internal ids for maintenance and reporting.
- Secrets remain in environment/local ignored config only.
- Reports must not include API keys, raw secrets, or private upload paths beyond
  controlled local evidence references.

Rollout / rollback:

- This PRD is the product baseline for v3 technical planning.
- Implementation should be staged behind runtime skeleton, contracts, and tests.
- Existing real evidence must be preserved.
- Old fixed-round behavior may be inspected as legacy but must not define v3
  acceptance.
- DB destructive reset requires explicit test scope or user authorization.

Open questions:

- Final child visual style and exact wording need rendered review.
- Exact long-run mastery thresholds require real multi-day evidence.
- Full question-bank data migration format should be proposed by 听云/霜弦.
- Whether live model calls are enabled in every QA run depends on configured
  provider availability; QA must label mock vs live evidence.

Required artifacts:

- This PRD v3.
- `PRODUCT_STRUCTURE_SPEC` in this file.
- Updated UX flow spec from 清秋, replacing fixed-round v2 copy.
- Updated data contract from 霜弦.
- Technical plan, engineering contract, implementation blueprint, and skeleton
  from 听云.
- Test case spec and QA audit plan from 观止.
- Architecture/data/code reviews from 镜花 and 霜弦 where applicable.

Required gates:

- 若命 PRD review.
- 清秋 UX review for child flow.
- 霜弦 data/content review for graph/question/evidence/report.
- 镜花 architecture review for runtime/state/model boundary.
- 观止 test-case review before implementation completion and QA after.

Stop condition:

This PRD is ready for downstream planning when 听云 can write the technical plan
without inventing product behavior, and 观止 can derive tests for the child daily
adaptive flow without asking what the system is supposed to do next.

## PRODUCT_STRUCTURE_SPEC - 若命 (`ruoming`) - 2026-07-10 CST

Objective:

Turn PRD v3 into executable product structure for UX, data, technical planning,
skeleton, and QA.

Source PRD / decisions:

- PRD v3 in this file.
- `docs/architecture/ai_native_learning_system_architecture_v3.md`
- `docs/architecture/daily_learning_runtime_contract_v1.md`

Scope:

- Child daily adaptive learning.
- Old-knowledge review.
- New-knowledge learning.
- Graph-bound question selection.
- Answer/photo submission.
- AI answer analysis.
- Evidence validation and mastery update.
- Planner next-step decision.
- Teaching intervention.
- Child-safe summary.
- Codex parent/operator reporting.

Non-goals:

Same as PRD_SPEC non-goals.

Project boundary overlay:

Use the PRD overlay above.

Actors / user roles:

| Actor | Product role |
|---|---|
| Son | Completes one current learning step at a time. |
| Parent | Uses Codex to inspect evidence and guide system changes. |
| Runtime | Controls stable state and child-safe flow. |
| Services | Provide graph, question bank, model route, reports, and deterministic filters. |
| Agents | Provide semantic judgment and teaching content under runtime gates. |

Module inventory:

| Module | Purpose | User value | Priority | Dependencies | Non-goals |
|---|---|---|---|---|---|
| Child Learning Surface | Show current step, answer input, photo upload, feedback, summary | Son knows what to do now | P0 | Runtime projection | Parent dashboard |
| Daily Learning Runtime | Own daily flow state and step transitions | Flow does not get stuck or fake progress | P0 | DB, graph, planner, gates | Semantic teaching judgment |
| Graph Runtime Service | Lookup nodes, prerequisites, graph version | Learning follows knowledge dependencies | P0 | Math graph | Free-form graph mutation |
| Question Bank Service | Pre-filter active eligible candidate packet | Fast, relevant next question | P0 | Active bank, review records | Full-bank model search |
| Planner Agent | Choose next step from compact evidence/candidates | Adaptive learning rather than fixed worksheet | P0 | Runtime packet, graph, bank | Direct DB mutation |
| Answer Analysis Agent | Analyze answer, method, process, OCR evidence | Reasoning-aware review | P0 | Model router, rubric | String matching |
| Evidence Gate | Decide whether analysis can drive learning | Prevent false mastery | P0 | Attempt, analysis, graph, question version | Teaching judgment |
| Evaluation Agent | Update graph-node state from valid evidence | Accurate mastery picture | P0 | Valid evidence | Choosing next question |
| Teaching Agent | Explain, repair, and ask micro-checks | Child can learn from mistakes/new concepts | P0 | Diagnosis, graph teaching contract | Long lectures |
| Model Router | Normalize model/provider calls and compatibility | Stable model interaction | P0 | Provider config | Business logic |
| Report/Codex Surface | Persist and summarize progress | Parent sees truth through Codex | P1 | DB/report artifacts | Parent Web dashboard |
| Question Design/Review Maintenance | Produce and approve bank candidates | Bank grows without blocking child | P1 | Graph, rubrics, review gate | Hot-path ad hoc generation |

Feature inventory:

| Feature | Module | Actor | User value | Entry surface | Core action | Priority |
|---|---|---|---|---|---|---|
| Start/continue today | Child Learning Surface | Son | Resume safely | `/` | load current step, start review, or enter gated new-knowledge action | P0 |
| Choose review old knowledge | Daily Runtime | Son | Begin prerequisite-aware review | `/` | start review mode | P0 |
| Build review targets | Runtime/Graph | System | Focus on useful nodes | internal | prioritize graph nodes | P0 |
| Select current step | Planner/Bank | System | Adaptive next action | internal | choose one step | P0 |
| Answer with text | Child Surface | Son | Express process | current step | submit text | P0 |
| Upload photo | Child Surface | Son | Use paper work | current step | upload image | P0 |
| Analyze answer | Answer Analysis | System | Understand reasoning | internal | produce structured analysis | P0 |
| Validate evidence | Gate | System | Avoid false conclusions | internal | accept/pending/reject evidence | P0 |
| Update node mastery | Evaluation | System | Track graph knowledge | internal | update A/B/C/D dimensions | P0 |
| Decide next move | Planner | System | Continue, teach, rollback, new, or stop | internal | write next-step decision | P0 |
| Teach/repair | Teaching | Son/System | Learn from gap | current step | explanation + micro-check | P0 |
| Enter new knowledge | Planner/Teaching | Son/System | Learn next graph node | current step | teach + interact + verify | P0 |
| Daily summary | Runtime/Report | Son/Parent | Know what happened | child page/Codex | summarize evidence | P1 |
| Bank maintenance | Designer/Reviewer | System/Codex | Keep high-quality candidates | operator/async | generate/review candidates | P1 |

Page / surface map:

| Page/surface | Purpose | Entry | Main actions | Required states | Empty/loading/error/success behavior |
|---|---|---|---|---|---|
| Child page `/` | One child learning surface | Browser open | continue, choose review, enter gated new-knowledge action, answer, upload, read summary | loading, choose mode, current step, saving, analyzing, ready for new knowledge, teaching, summary, blocked | safe messages; no internals |
| Current step | Show one question/interaction/teaching step | planner selected step | answer, upload, ask stuck/clarify, submit | ready, draft, saving, saved, validation error | preserve draft on errors |
| Teaching step | Explain/repair/new concept | planner teaching action | read, answer micro-check | explanation, micro-check, submitted | short actionable copy |
| Daily summary | End/transition state | budget/stop reached | continue new knowledge, stop, review summary | ready, pending labels, blocked labels | label evidence scope |
| Codex report | Parent/operator query | parent asks Codex | summarize progress/issues/next | confirmed, pending, blocked, inferred, stale, mock_only, missing_lineage | evidence-backed only |

User flows:

| Flow | Actor | Start | Steps | Success end | Failure/recovery |
|---|---|---|---|---|---|
| Old review | Son | choose review | target pool -> current step -> answer -> analysis -> evaluation -> next | summary or new knowledge ready | pending/blocked labeled; safe retry/independent step |
| New knowledge | Son | planner reaches gated transition | ready_for_new_knowledge -> explanation -> interaction -> practice -> review -> repair/confirm | node confirmed, next step selected | rollback or micro-teach |
| Answer photo | Son | current step | select photo -> preview -> submit -> OCR/analysis | usable or pending evidence | unclear photo asks clarification |
| Parent progress | Parent | asks Codex | read DB/report -> summarize | evidence-scoped answer | unknown/stale clearly labeled |
| Bank gap | System/Codex | no candidate for needed node | mark bank gap -> async design/review | candidate enters active bank after gate | fallback teach/clarify or alternate target |

State model:

| Object | States | Transitions | Triggered by | User-visible meaning |
|---|---|---|---|---|
| `daily_flow` | `new`, `reviewing`, `ready_for_new_knowledge`, `learning_new`, `paused`, `completed`, `blocked`, `superseded` | load/start/review-cleared/new-entry/summary/block | runtime | what today's page should show |
| `flow_step` | `selected`, `displayed`, `responded`, `analyzing`, `evaluated`, `superseded`, `blocked` | planner/display/submit/analyze | runtime/agents/gates | one current task or message |
| `attempt` | `active`, `invalidated`, `stale` evidence status plus `pending_review`, `graded`, `blocked` grading status | submit/analyze/invalidate/stale migration | runtime/answer analysis | whether answer can be used |
| `review_target` | `candidate`, `active`, `skipped`, `completed`, `blocked`, `pending` | target build/planner/evaluation | runtime/planner | why a node is or is not practiced |
| `learner_node_status` | `A`, `B`, `C`, `D`, `untested` | evaluation from valid evidence | evaluation/runtime | internal mastery only |
| `next_step_decision` | `accepted`, `rejected`, `fallback`, `blocked` | planner/gate | runtime | why next step happened |

Permission / boundary:

| Actor/role | Can do | Cannot do | Source rule |
|---|---|---|---|
| Son | answer, upload, continue, read feedback | see internals, grade manually, manage model config | child-safe boundary |
| Parent/Codex | inspect progress, request changes, run reports/tests | be required for normal learning step | product boundary |
| Runtime | persist state, enforce gates, recover, project child UI | invent semantic judgment | runtime boundary |
| Agents | judge/generate under contract | directly mutate source evidence or expose child internals | agent boundary |
| Services | lookup/filter/precompute | overrule evidence semantics | service boundary |

Data objects / domain terms:

| Object/term | User meaning | Key fields | Source | Consumers |
|---|---|---|---|---|
| graph node | teachable knowledge point | id, prerequisites, teaching contract, graph version | math graph | planner, teaching, evaluation |
| question candidate package | unscheduled generated candidate | node, graph version, rubric, solution paths, wrong paths, evidence goal | designer | reviewer |
| question review record | active-use verdict | review id, item version, verdict, active_eligible, rule version | reviewer | bank service |
| active question slot | approved child task | node, graph version, item version, review id, rubric, family, cooldown group | bank/reviewer | planner, child page |
| candidate packet | small model selection context | 5-8 metadata rows plus active-use proof and filter summary | bank service | planner |
| current step | what child sees now | step type, node, prompt/package, expected evidence | runtime/planner | child page |
| usable evidence | evidence that can drive learning | active, graded, analyzed, graph-bound, current | gate | evaluation/planner/report |
| process gap | smallest teachable gap from answer | dimension, explanation, next prompt | answer analysis | teaching/planner |
| daily summary | end-of-day or transition summary | confirmed, pending, blocked, inferred, stale, mock_only, missing_lineage, next | runtime/report | child/Codex |

External side effects:

- Local DB/file writes.
- Local answer upload storage.
- Configured model calls through router only.
- Report artifact writes.

Model/content behavior:

- Hot path planner uses compact candidate packet, not full question bank.
- Answer analysis can be async but must not be replaced by deterministic fake
  grading.
- Model failure creates pending/blocked evidence, not invented progress.
- Content must be age-respectful and graph-bound.

Acceptance paths:

| Scenario | Given | When | Then | Evidence required |
|---|---|---|---|---|
| Start review | child opens page | selects review | one current step appears | screenshot/API/DB |
| Adaptive next | child submits answer | analysis finishes | next step reason reflects evidence | attempt/analysis/planner rows |
| Skip mastered | target pool builds | node A stable not due | node skipped | target audit |
| Process gap | answer-only response | analysis runs | process retest/clarification selected | analysis/planner |
| New learning | prerequisites stable | review target done | concept teaching starts | planner/teaching package |
| Slow model | model delayed | next step needed | wait only if dependent, else safe independent step | job state/decision |
| Parent query | Codex asks progress | reads reports | scoped truthful answer | report/DB facts |
| Late evidence | pending analysis arrives after an independent step is shown | runtime reconciles | current visible step is not rewritten; update happens at safe transition | reconciliation audit |
| Continuous day | 10-20 adaptive steps include mixed evidence | QA runs trace | no fixed-list regression; summary labels evidence scope | browser trace + DB/API |

Open product decisions:

- Final visual style and exact child copy.
- Exact mastery threshold tuning after real multi-day evidence.
- Final question-spec storage shape.

Required downstream artifacts:

- Updated `UX_FLOW_SPEC`
- Updated `DATA_CONTRACT_SPEC`
- `TECHNICAL_PLAN`
- `ENGINEERING_CONTRACT`
- `IMPLEMENTATION_BLUEPRINT`
- `SKELETON_PASS`
- `TEST_CASE_SPEC`
- `QA_AUDIT_PLAN`

Required gates:

- 若命 product review.
- 清秋 UX review.
- 霜弦 data/content review.
- 镜花 architecture/code review.
- 观止 QA/test review.

Stop condition:

Product structure is ready when downstream roles can implement and test the
daily adaptive flow without reverting to a fixed pre-generated question list or
asking the parent to complete normal learning operations.
