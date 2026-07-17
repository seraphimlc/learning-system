# AI Native Math Learning System PRD v5

Status: PRD_READY_FOR_PRODUCT_STRUCTURE; not ENGINEERING_SOURCE_READY for technical plan
Owner: 若命 (`ruoming`)
Created: 2026-07-11 CST
Source policy: clean-slate PRD based on recent product discussion only.

Historical PRDs are intentionally excluded as source material for this document.
They may remain in the repository as history, but they do not define v5 product
scope, acceptance, user roles, or downstream implementation authority.

## Entry Routing Snapshot

- request_type: `prd_spec`
- maturity: `product_decided`
- risk: `high_risk`
- missing_source: none blocking PRD; `PRODUCT_STRUCTURE_SPEC v5`, `UX_FLOW_SPEC v5`,
  codebase reconnaissance, engineering contracts, QA fixtures, and model/runtime
  targets still block a full technical plan or implementation
- next_owner: 若命, then 清秋 / 听云 / 观止 / 镜花
- next_artifact_or_action: `PRODUCT_STRUCTURE_SPEC v5`

## Entry Lock

- selected_playbook_or_contract:
  - `docs/collaboration/playbooks/prd-authoring.md`
  - `docs/collaboration/playbooks/artifact-contracts.md`
- source inputs:
  - recent user decisions in this Codex thread
  - `AGENTS.md`
  - `data/knowledge_graphs/math/math_knowledge_graph_v2.md`
  - `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
  - `docs/collaboration/inbox.md` messages:
    - `MSG-20260710-001` learning process record/replay TODO
    - `MSG-20260711-001` next-question decision rule TODO
- explicitly excluded sources:
  - prior PRDs
  - prior product structures
  - prior technical plans
  - prior review reports
- project_boundary_overlay: stable for product direction; provisional for exact
  UX copy, mastery thresholds, model fixture set, and storage split
- output target: durable doc `docs/product/ai_native_math_learning_prd_v5.md`
- persistence reason: this is the clean product contract for the next design,
  architecture, implementation, and test cycle
- downstream artifact expectation:
  - `PRODUCT_STRUCTURE_SPEC v5`
  - `UX_FLOW_SPEC v5`
  - `TECHNICAL_PLAN v5`
  - `ENGINEERING_CONTRACT`
  - `IMPLEMENTATION_BLUEPRINT`
  - `TEST_CASE_SPEC v5`
  - review and QA gates
- stop condition: `PRD_READY_FOR_MULTI_ROLE_REVIEW`

## PRD Result Summary

- decision: Build a single-child, child-only Web learning system for math that
  runs a stable adaptive loop: choose the next learning step, collect the
  child's answer, use AI to judge reasoning, teach or repair the first break,
  choose the next step, and summarize the session with evidence.
- target_actor_and_value:
  - Son: can independently review old knowledge, learn new knowledge, answer in
    text or photo, say he is stuck, receive feedback and teaching, and continue
    without parent intervention.
  - Parent: uses Codex to inspect learning progress, evidence, weak points, and
    system design problems. Parent does not grade answers or operate a parent
    dashboard.
  - System: reliably runs the loop, records evidence, calls internal AI roles
    through bounded contracts, and never hides missing or failed analysis behind
    friendly waiting copy.
- in_scope_capability_set:
  - one child Web surface
  - daily old-knowledge review
  - graph-guided new-knowledge learning
  - one current step visible at a time
  - text answer, photo answer, and stuck signal
  - AI answer analysis of answer, process, reasoning, and valid alternatives
  - teaching and repair after wrong, partial, unclear, answer-only, stuck, or
    low-confidence evidence
  - dynamic next-step selection after each usable evidence package
  - structured session records for later Codex query
  - question bank and question-generation rules suitable for an incoming Grade 7
    learner, with controlled stretch and no insulting filler drills
  - runtime-owned state machine, async model work, recovery, and evidence gates
- out_of_scope:
  - parent Web dashboard
  - multi-user product system
  - generic education SaaS features
  - fixed worksheet generated before answers are known
  - parent/manual answer grading as normal flow
  - rote low-age arithmetic unless evidence proves a narrow repair need
  - Olympiad track as the main path
  - automatic self-evolution mutating active graph, bank, mastery, or plan
  - external textbook/commercial question import without explicit source
- acceptance_evidence:
  - child browser path for one-current-step learning
  - persisted records for step, question reason, child answer, analysis,
    teaching, evaluation, next-step decision, and summary
  - semantic answer-analysis samples for answer-only, wrong-reason-right-answer,
    alternative valid method, blank, stuck, photo, and low-confidence cases
  - adaptive day simulation covering all-wrong, all-partial, mixed, repeated
    stuck, pending analysis, and photo uncertainty
  - QA labels for live model, recorded model, mock-only, pending, blocked, stale,
    and missing-lineage evidence
- confidence: product direction confirmed; exact UX copy, mastery thresholds,
  storage split, and model/OCR fixture policy need downstream artifacts
- critical_unknowns:
  - exact child-facing visual/copy tone
  - first conservative mastery thresholds
  - storage split between DB facts, logs, model snapshots, and Markdown reports
  - exact live/recorded model QA policy
  - initial semantic oracle fixture set
- downstream_route:
  1. 若命 writes `PRODUCT_STRUCTURE_SPEC v5`.
  2. 清秋 writes `UX_FLOW_SPEC v5`.
  3. 听云 runs strict `ENGINEERING_SOURCE_READINESS`, performs codebase
     reconnaissance, then writes `TECHNICAL_PLAN v5`, `ENGINEERING_CONTRACT`,
     and `IMPLEMENTATION_BLUEPRINT` only if the gate passes.
  4. 观止 writes `TEST_CASE_SPEC v5` after source-ready product, UX,
     engineering, skeleton/code targets exist.
  5. 镜花 reviews technical plan, contracts, skeleton, and implementation gates.

## Objective

Create a usable AI-native math learning system for one real child during the
summer bridge period from primary-school prerequisites to Grade 7 mathematics.
The product must be small enough to operate reliably and strong enough to judge
reasoning, teach weak points, and choose what to do next without the parent
manually controlling the learning session.

## User / Actor

| Actor | Role in product | Product boundary |
|---|---|---|
| Son | Primary learner | Uses Web page only. Sees one current learning step, answers, receives feedback, and continues. |
| Parent | System owner and observer | Uses Codex only. Asks for progress, evidence, weak points, and system-improvement direction. |
| Runtime | Deterministic controller | Owns state transitions, persistence, queue/recovery, child-safe projection, and evidence gates. |
| Internal learning agents | Hidden AI functions | Analyze answers, generate teaching, evaluate mastery, propose next actions, and generate/review questions under bounded contracts. |
| Codex / 若命 team | Product and engineering improvement surface | Reads records, discusses direction with parent, changes system through reviewed artifacts and gates. |

## Scenario

The son opens the learning page. The system either resumes today's active step
or starts the day with old-knowledge review. He sees exactly one thing to do:
a question, a micro-check, a short teaching step, a clarification request, a
ready-for-new-knowledge checkpoint, or a summary.

After he submits text, photo, or a stuck signal, the system saves the evidence
first. AI then analyzes the answer and process asynchronously when possible.
Runtime validates the result, updates graph-node learning evidence only when the
evidence is usable, generates teaching or repair if needed, and chooses the next
step. The parent does not intervene during the loop.

## Problem

The system must avoid three failure modes:

1. It must not become a fixed worksheet or drill app.
2. It must not pretend AI/agent output is reliable without runtime gates,
   evidence records, recovery, and QA.
3. It must not ask the parent to grade, approve, or manually move the child
   through each step.

The real problem is not "generate questions". The real problem is to maintain a
trustworthy teaching loop where every next action follows evidence.

## Desired Outcome

By the end of one normal session:

- the son knows what he did, where he improved, and what still needs work;
- the system knows which graph nodes gained evidence, which remain weak, which
  need prerequisites, and which evidence is pending or blocked;
- the parent can ask Codex and receive a truthful account with source evidence;
- the next session can start from recorded evidence rather than memory or guess.

## Scope

- Math only.
- Single child.
- Local child Web surface.
- Parent interaction through Codex.
- Knowledge-graph-bound review and learning.
- Question selection one step at a time.
- Open answer text.
- Photo upload for handwritten work.
- Stuck signal.
- AI answer analysis.
- Teaching explanation for wrong/partial/stuck/unclear evidence.
- Evaluation across concept, model, procedure, calculation, expression,
  transfer, and stability.
- Next-step decision: same-structure retest, near-transfer retest,
  prerequisite probe, micro-teach, worked example, new knowledge, stretch, or
  summary.
- Session records and daily summary.

## Non-Goals

- No parent dashboard.
- No multi-child or class management.
- No login/productized user system beyond what is necessary locally.
- No generic analytics cockpit.
- No full小学知识按年级复习.
- No fixed daily list of 10-20 preselected questions.
- No answer matching as grading.
- No parent review workflow.
- No automatic self-evolution that changes active content or mastery state.
- No external copyrighted/private question bank import without source.

## Project Boundary Overlay

Known project facts:

- This is for one child, not a general product.
- Current first phase is summer bridge: primary critical gaps plus Grade 7 math
  preview.
- Math is first; English is out of scope for this cycle.
- Every teaching, diagnosis, question, answer analysis, evaluation, plan, and
  report must bind to graph nodes.
- The math graph has 56 nodes and is designed for prerequisite repair, bridge
  models, Grade 7 mainline, and controlled extension.
- Grade 7 failure should check prerequisite chains before same-type drilling.
- The child page must be simple and age-respectful.
- Complex teaching logic belongs inside runtime, internal agents, records, and
  Codex-readable reports.

Assumptions:

- Local DB/file storage is acceptable for the next technical design unless
  听云 proves a blocker.
- Text answer analysis can use a GPT-compatible model route.
- Photo/OCR may use a vision-capable model route, but photo evidence remains
  untrusted until validated.
- A normal session targets roughly 10-20 interactions, but the system may stop
  early when repeated stuck, blocked evidence, or teaching repair makes that
  safer.

Missing decisions:

- Exact UX tone and copy.
- Exact initial mastery thresholds.
- Exact storage and report snapshot policy.
- Exact model fixture and live-provider QA policy.

## Role-Specific Project Rules

| Role | Must do | Must not do |
|---|---|---|
| 若命 | Own product scope, PRD, product structure, acceptance, stage order, and gate routing. | Let old PRDs or historical implementation drift define v5 product meaning. |
| 清秋 | Define child-only UX flow, state clarity, interaction boundaries, copy tone, and responsive/accessibility expectations. | Add parent dashboard or internal-agent UI. |
| 听云 | Design technical plan, state machine, model adapter, storage contracts, async recovery, blueprint, and implementation. | Start implementation before source readiness, UX flow, contracts, and required test design. |
| 观止 | Design child-perspective tests, semantic oracles, model/OCR false-pass cases, browser flows, and QA evidence. | Treat green scripts, mock models, or happy-path browser flow as semantic PASS. |
| 镜花 | Review architecture, state machines, evidence chain, model adapter isolation, child-safe boundary, and maintainability. | Replace missing product/UX/QA sources with reviewer assumptions. |

## Source Decisions And Evidence

| Claim | Tag | Source |
|---|---|---|
| Users are son and parent only. | user_confirmed | Recent discussion |
| Son uses Web page only. | user_confirmed | Recent discussion |
| Parent uses Codex only. | user_confirmed | Recent discussion |
| Parent does not grade or intervene in normal session. | user_confirmed | Recent discussion |
| System is essentially select question, answer, AI judge, feedback/teach, next question, summary/report. | user_confirmed | Recent discussion |
| Daily work includes old-knowledge review and new-knowledge learning. | user_confirmed | Recent discussion |
| Questions are selected one at a time, not generated as a fixed list up front. | user_confirmed | Recent discussion |
| A normal day has about 10-20 interactions, adapted by evidence. | user_confirmed | Recent discussion |
| Answer analysis must judge reasoning/process and valid alternative methods. | user_confirmed | Recent discussion |
| Correct final answer with wrong/missing reasoning is not mastery. | user_confirmed | Recent discussion |
| If a child is weak on a type, system should teach, probe, or retest intelligently rather than repeating drills. | user_confirmed | Recent discussion |
| Runtime framework must guarantee stable execution beyond model/agent cooperation. | user_confirmed | Recent discussion |
| Self-evolution is paused as an automatic mutator. | user_confirmed | Recent discussion |
| Every learning object must bind to graph nodes. | user_confirmed | `AGENTS.md`, graph doc |
| Graph has 56 nodes. | existing_system_observed | `math_knowledge_graph_v2.json` |
| Learning records/replay and next-question rules are explicit TODOs. | existing_system_observed | `docs/collaboration/inbox.md` |

## PRD Question TODO

| Question class | Answer / assumption | Status | Blocks downstream? |
|---|---|---|---|
| Actor | Son uses Web; parent uses Codex; runtime/internal agents hidden | answered | no |
| Trigger | Child opens page and starts or resumes today's learning | answered | no |
| Main flow | Select step -> answer -> AI judge -> teach/repair -> select next step -> summary | answered | no |
| Surfaces | One child Web page; Codex query/report surface for parent | answered | no |
| States | start/resume, current step, submitting, analyzing, feedback, teaching, clarify evidence, ready for new knowledge, blocked, summary | answered | no |
| Permissions | Child sees only child-safe actions; parent/Codex can inspect evidence; runtime owns state | answered | no |
| Data objects | graph node, learner node state, question, current step, attempt, photo, analysis, evaluation, teaching, decision, record, summary | answered | no |
| Side effects | local records, local uploads, configured model calls only | answered | no |
| Quality bar | Grade 7 bridge, graph-bound, reasoning-aware, no low-age filler, no fake grading | answered | no |
| Acceptance | browser + record + semantic oracle + adaptive-day + report evidence | answered | no |
| Non-goals | parent dashboard, fixed worksheet, multi-user, parent grading, auto-mutating self-evolution | answered | no |
| UX tone | child-friendly but age-respectful final copy | assumed | no; route to UX |
| Mastery thresholds | conservative initial thresholds | assumed | no; route to technical/product structure |
| Storage split | DB/log/snapshot/report split | assumed | no; route to technical plan |
| Model fixture policy | live/recorded/mock labels required | assumed | no; route to QA |

## User Stories / Flows

| ID | Story |
|---|---|
| US-01 | As the son, I open the page and immediately know the next thing to do. |
| US-02 | As the son, I can answer with text, upload a photo of written work, or say I am stuck. |
| US-03 | As the son, I receive feedback on my thinking, not only whether the final answer matches. |
| US-04 | As the son, if I am stuck or unclear, I get a smaller step or explanation rather than another random question. |
| US-05 | As the son, after old review is stable enough, I can learn a new graph-bound concept. |
| US-06 | As the system, I select each next step from evidence and graph state, not a fixed worksheet. |
| US-07 | As the system, I skip stable nodes unless spaced confirmation is due. |
| US-08 | As the system, when Grade 7 content fails due to prerequisites, I roll back along the graph. |
| US-09 | As the parent, I ask Codex what happened and receive confirmed, weak, pending, blocked, stale, and mock-only facts clearly separated. |
| US-10 | As the system owner, I can improve the system later because each session is recorded and replayable. |

Core daily review flow:

```text
open page
-> resume or create today's flow
-> build target pool from untested / weak / failed / due / prerequisite nodes
-> select one current step
-> child answers by text/photo/stuck
-> save evidence immediately
-> analyze answer with AI
-> validate analysis and evidence
-> update graph-node learner state only from usable evidence
-> teach, retest, probe prerequisite, continue, start new knowledge, stretch, or summarize
```

New knowledge flow:

```text
prerequisite readiness check
-> essence explanation
-> core model
-> worked example
-> micro interaction
-> standard question
-> variant / near transfer
-> review or repair
-> summary or next review hook
```

## Acceptance Criteria

| ID | Scenario | Given | When | Then | Evidence required |
|---|---|---|---|---|---|
| AC-01 | Start/resume | Child opens page | No active step or a resumable step exists | Page shows one child-safe current action | Browser trace, API payload |
| AC-02 | One current step | Runtime has candidate steps | It selects next step | Child sees exactly one step, not a worksheet | DOM/API evidence |
| AC-03 | Text answer | Current step accepts text | Child submits text/process | Attempt is saved before model analysis | Attempt record, timestamp, job/analysis record |
| AC-04 | Photo answer | Current step accepts photo | Child uploads work | Photo is saved; OCR/vision remains untrusted until validated | Attachment record, confidence/validation status |
| AC-05 | Stuck | Child cannot start | Child marks stuck | System offers hint, smaller step, micro-teach, prerequisite probe, or safe stop | Step record, teaching/decision record |
| AC-06 | Correct with reasoning | Answer and reasoning are sound | AI analyzes | Node evidence improves without overclaiming durable mastery from one answer | Analysis and evaluation dimensions |
| AC-07 | Correct answer only | Final answer is right but process missing | AI analyzes | Process gap is recorded; no full mastery from answer alone | Analysis gap, next-step decision |
| AC-08 | Wrong reason, right answer | Final answer happens to be right | AI analyzes invalid method | Result is partial/wrong and repair is chosen | Semantic oracle sample |
| AC-09 | Alternative valid method | Child uses a different valid method | AI analyzes | Valid method is accepted when reasoning is sound | Analysis comparison |
| AC-10 | Blank/invalid evidence | Child submits no usable text/photo/stuck | Runtime validates | System asks for evidence or blocks; no mastery update | Validation result |
| AC-11 | Low-confidence photo | OCR/vision confidence is low | Analysis would be uncertain | System asks for clearer evidence or text explanation | OCR/vision confidence, clarify step |
| AC-12 | Prerequisite gap | Advanced content fails due to prerequisite | Planner decides next | System probes/teaches prerequisite, not blind same-type drill | Graph chain, decision reason |
| AC-13 | Similar retest | Evidence is unstable but not broken | Planner selects retest | Child gets similar-structure, non-identical task | Candidate metadata |
| AC-14 | Near transfer | Evidence seems stable enough for transfer | Planner selects variant | Child gets representation/context variation | Candidate metadata, decision reason |
| AC-15 | New knowledge gate | Review prerequisites are stable enough | Runtime reaches checkpoint | Child can continue to new knowledge or finish summary | Readiness record |
| AC-16 | Teaching quality | Wrong/partial/stuck evidence exists | Teaching package generated | Explanation targets first cognitive break and next small action | Teaching record, semantic review sample |
| AC-17 | Low-age question rejection | Candidate is insulting mechanical filler | Candidate gate runs | Candidate is rejected unless narrow weakness evidence justifies it | Candidate exclusion reason |
| AC-18 | Slow model | Analysis is pending | Child asks to continue | Runtime waits if dependent or chooses independent safe step excluding pending evidence | Pending label, decision reason |
| AC-19 | Model not configured/failing | Model route is missing/failing | Child submits | No fake grade; child sees safe state; Codex sees reason | Error status, report label |
| AC-20 | All wrong day | Multiple wrong attempts occur | Session progresses | System teaches/probes/early-stops instead of drilling blindly | Flow trace and summary |
| AC-21 | All partial day | Multiple partial attempts occur | Session progresses | System records partial dimensions and chooses repair/transfer/probe | Evaluation and decisions |
| AC-22 | Mixed day | Correct, partial, wrong, pending evidence coexist | Summary generated | Summary separates confirmed, weak, pending, blocked by node/action | Summary source ids |
| AC-23 | Restart recovery | Service restarts with pending/running work | Runtime recovers | No duplicate attempts/jobs/decisions/summary | Before/after records |
| AC-24 | Child-safe projection | Child route/API returns data | Payload/DOM inspected | No graph ids, question ids, attempt ids, provider names, rubrics, or queue internals leak | DOM/API scan |
| AC-25 | Parent Codex query | Parent asks progress | Codex reads records | Answer separates confirmed, weak, pending, blocked, inferred, stale, mock-only, missing-lineage | Report/query evidence |
| AC-26 | Report freshness | Records change after report | Codex or QA reads report | Stale report cannot be treated as current pass evidence | Timestamp/version/source comparison |

## Data / State Meaning

| Object | Product meaning |
|---|---|
| `graph_node` | Knowledge point and prerequisite anchor. |
| `learner_node_state` | Current evidence-backed state for a graph node. |
| `question_item` | Graph-bound task with evidence goal, difficulty, and quality metadata. |
| `current_step` | One child-visible action: question, teaching, micro-check, clarification, checkpoint, or summary. |
| `attempt` | Child evidence for one step: text, photo, stuck, or clarification. |
| `answer_analysis` | AI semantic judgment of final answer, method, reasoning, process, alternatives, and gaps. |
| `evaluation_update` | Runtime-approved mastery/evidence update. |
| `teaching_package` | Child-facing explanation, hint, worked example, contrast, or micro-check. |
| `next_step_decision` | Runtime-selected next action with source evidence and reason. |
| `learning_record` | Durable trace of step, answer, analysis, teaching, decision, and summary. |
| `daily_summary` | Child-safe finish plus Codex-readable evidence facts. |

Canonical evidence trust labels:

- `confirmed`
- `pending`
- `blocked`
- `inferred`
- `stale`
- `mock_only`
- `missing_lineage`

Mastery condition labels such as `weak`, `partial`, `unstable`, or `due` must
not be mixed with evidence trust labels.

## Minimum Semantic Oracle Fixtures

`TEST_CASE_SPEC v5` must start from a small but concrete oracle set. The exact
question text can be chosen later from the active graph/question bank, but each
fixture must be graph-node-bound and must define expected answer-analysis fields:

- final answer judgment
- method validity
- reasoning/process quality
- process gap
- confidence
- error tag
- expected teaching or next action

Required semantic fixtures:

| Fixture | Required graph area | Child evidence pattern | Expected result |
|---|---|---|---|
| Correct with reasoning | any current review node | correct final answer plus valid steps/explanation | `confirmed` evidence may improve node state, but one answer alone does not prove durable mastery |
| Correct answer only | algebra or equation node | final answer present, reasoning missing | process gap recorded; no full mastery |
| Wrong reason, right answer | algebra simplification or equation node | final result right by coincidence, invalid transformation | partial/wrong; teach first invalid step |
| Alternative valid method | equation or word problem node | different valid setup or method | accept if reasoning and constraints are sound |
| Symbol/unit/procedure error | geometry, unit, or signed-number node | method mostly right, sign/unit/bracket/procedure wrong | partial with targeted repair |
| Blank/unclear | any node | empty text/photo and no stuck signal | ask for evidence; no mastery update |
| Stuck | prerequisite-sensitive node | child says cannot start | micro-teach, smaller step, or prerequisite probe |

## Required Graph Rollback Fixtures

`TEST_CASE_SPEC v5` must include graph rollback fixtures from real dependency
chains. These fixtures test whether the system chooses prerequisite repair,
same-structure retest, or near transfer for the right reason.

Minimum chains:

| Chain purpose | Graph chain | Failure pattern | Expected next action |
|---|---|---|---|
| 去括号到整式 | `M-PRE-DISTRIBUTIVE` -> `M-G7-PARENTHESIS` -> `M-G7-COMBINE-LIKE` -> `M-G7-POLY-ADD-SUB` | signs flip incorrectly after parentheses | prerequisite probe or micro-teach on `M-G7-PARENTHESIS`, not random整式 drill |
| 等量关系到方程应用 | `M-PRE-QUANTITY-RELATION` -> `M-PRE-EQUATION-BASIC` -> `M-G7-EQUALITY-PROP` -> `M-G7-EQ-SOLVE` -> `M-G7-EQ-WORD` | equation application fails because relationship is not modeled | rollback to relation/equation setup, not arithmetic drill |
| 数轴到有理数运算 | `M-G7-NUMBER-LINE` -> `M-G7-OPPOSITE` -> `M-G7-ABSOLUTE` -> `M-G7-COMPARE` -> `M-G7-RATIONAL-ADD-SUB` | signed-number operation uses wrong direction or absolute-value comparison | probe number-line/opposite/absolute-value break |
| 单位到几何度量 | `M-PRE-UNIT-CONVERSION` -> `M-G7-LINE-RAY-SEGMENT` -> `M-G7-SEGMENT-MEASURE` -> `M-G7-ANGLE` | relation is right but unit/measure meaning breaks result | repair unit or segment/angle representation |

Rollback depth rule:

- If the current step fails but immediate prerequisite evidence is unknown, probe
  the nearest prerequisite first.
- If immediate prerequisite also fails, continue one edge backward until the
  first teachable break is found or the session safely summarizes.
- If prerequisite evidence is stable and current structure is unstable, choose
  same-structure or near-transfer retest instead of rollback.

## Required Photo / OCR Fixtures

Photo support is a first-class answer mode, but photo-derived text is not
trusted until validated.

`TEST_CASE_SPEC v5` must include:

| Fixture | Evidence | Expected result |
|---|---|---|
| Readable photo | clear handwritten work with enough steps | eligible for analysis after vision/OCR validation |
| Unclear photo | blurry/cropped/low contrast | ask for clearer photo or text explanation; no mastery update |
| Photo/text conflict | photo work and typed answer disagree | analysis must flag conflict and ask/choose evidence according to runtime contract |
| No usable work | photo contains only final answer or unrelated content | process gap or clarify evidence; no full mastery |
| OCR hallucination/guess | OCR proposes unsupported symbols/steps | keep low confidence; do not use guessed content for mastery |

## Day-Level Outcome Oracle

Daily summary and next-session records must be testable. The child-facing
summary may be brief, but the Codex-readable record must preserve source facts.

| Day pattern | Minimum expected outcome |
|---|---|
| All wrong | Do not continue drilling. Record wrong evidence by node, teach/probe the earliest useful break, and either retest once or stop with weak/blocked summary. |
| All partial | Record partial dimensions, choose repair/near-transfer/prerequisite probe by error type, and avoid calling mastery. |
| Mixed | Separate confirmed, weak, pending, and blocked evidence by node and action. Do not summarize only the last question. |
| Repeated stuck | Reduce step size, teach, probe prerequisite, or stop safely. Do not shame or loop. |
| Repeated photo uncertainty | Ask for clearer evidence/text or summarize pending/blocked. Do not infer mastery from guessed OCR. |

Minimum Codex-readable summary fields:

- session id or day handle
- graph nodes touched
- steps shown and why they were chosen
- child evidence ids and response modes
- answer-analysis status and trust label
- teaching actions shown
- evaluation updates applied or rejected
- next-step decisions and reasons
- pending/blocked/stale/mock-only/missing-lineage flags

## Live / Recorded / Mock Evidence Policy

QA and reports must never blur model scope.

- `live_model`: real provider call executed in current environment.
- `recorded_model`: stored provider input/output sample replayed for deterministic QA.
- `mock_only`: deterministic fake response; valid for state-machine tests only,
  not semantic judgment PASS.
- `pending`: evidence saved but analysis not complete.
- `blocked`: model/OCR/config/runtime cannot safely analyze or decide.

Semantic PASS requires either `live_model` evidence or an explicitly accepted
recorded oracle sample. `mock_only` can support runtime tests but cannot prove
answer-analysis intelligence, teaching quality, question quality, or planning
reasonability.

## External Side Effects

Allowed:

- local DB/file writes
- local uploaded-answer storage
- configured model API calls through model adapter

Forbidden without explicit authorization:

- cloud deployment
- external account writes
- external content import
- destructive reset of real learning data
- exposing API keys/secrets in docs, DB rows, screenshots, reports, or model logs

## Model / Content Quality Bar

- AI answer analysis must evaluate final answer, method, reasoning, steps,
  symbols/units, check/explanation, alternative valid methods, process gap,
  confidence, and child-facing feedback seed.
- Reference answers are rubric context, not string-match grading.
- The planner must not receive the full question bank. It receives a compact
  candidate packet after deterministic prefiltering.
- Question quality must reject low-age filler, answer-only prompts, prompts that
  do not expose reasoning, untraceable graph lineage, fake prior-error claims,
  and child-facing generator/agent language.
- Controlled stretch and competition-style questions are allowed only after
  prerequisite stability and must serve transfer, not ego or spectacle.
- Teaching output must identify the first cognitive break and provide a small
  next action.
- Internal agents may suggest; runtime decides and persists.
- Self-evolution may record proposals only. It cannot mutate active graph,
  question bank, mastery, or plan in this cycle.

## UX Constraints

- One child surface.
- One current step visible.
- No parent dashboard.
- No visible internal agent names.
- No graph ids, question ids, attempt ids, provider names, rubrics, queue
  internals, or Codex instructions on child surface.
- Child copy must respect an incoming Grade 7 learner.
- Waiting states must be honest and short.
- Feedback must cover the relevant session evidence, not only the last question.
- Photo and stuck flows must feel normal, not like error states.

## Permissions / Security

- Child can answer, upload, say stuck, continue, and finish.
- Parent can inspect through Codex and request system changes.
- Runtime can persist local data and call configured models.
- Internal agents cannot directly mutate authoritative state.
- Codex/operator can inspect internal evidence and modify system only through
  reviewed work.

## Failure / Recovery

- Save child evidence before analysis.
- Analysis may be async.
- Pending evidence cannot drive mastery or dependent next steps.
- Model failure creates honest blocked/pending state, not fake grading.
- Low-confidence photo/OCR requests clearer evidence.
- Restart recovers pending/running/completed-unapplied work.
- Double submit and refresh must not duplicate attempts, jobs, decisions,
  mastery updates, or summaries.
- Stale reports are labeled and cannot be used as current truth.

## Rollout / Rollback

- This PRD defines the next clean product baseline.
- Implementation must preserve existing real learning data unless the user
  explicitly authorizes a test reset.
- A v5 implementation slice may start with the old-knowledge review path, but
  it must preserve hooks for new-knowledge learning, photo, stuck, summary, and
  evidence records.
- If v5 runtime cannot judge safely, child sees a safe blocked/retry/summary
  state and Codex sees the cause.

## Assumptions Allowed Forward

- Initial implementation can be local-first.
- Exact mastery thresholds can start conservative and be revised after real
  sessions.
- UX copy and visual tone are delegated to `UX_FLOW_SPEC v5`.
- Storage/log/report split is delegated to `TECHNICAL_PLAN v5`.
- Semantic QA can start with recorded/model-oracle fixtures and clearly label
  live-provider coverage.

## Open Questions

- What exact child-facing tone should 清秋 use?
- Which graph nodes become the first 7-day review/new-learning seed set?
- What minimum semantic oracle fixture set should 观止 require before QA?
- How much model input/output should be snapshotted for later audit?
- What conservative mastery thresholds should 听云 encode first?

## Required Artifacts

- `PRODUCT_STRUCTURE_SPEC v5`
- `UX_FLOW_SPEC v5`
- `TECHNICAL_PLAN v5`
- `ENGINEERING_CONTRACT`
- `IMPLEMENTATION_BLUEPRINT`
- `TEST_CASE_SPEC v5`
- 镜花 architecture/design review
- 观止 QA audit plan/report

## Required Gates

- 若命 PRD/product-structure gate
- 清秋 UX flow gate
- 听云 engineering source readiness, technical plan, engineering contract,
  blueprint, skeleton, and implementation gates
- 镜花 design/code review gates
- 观止 test-case source readiness, test case spec, QA audit plan, and QA gate

## PRD_QUALITY_GATE

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
  - user roles and surfaces -> recent user decisions
  - graph-bound requirement -> `AGENTS.md`, math graph docs
  - graph size and node structure -> `math_knowledge_graph_v2.md/json`
  - record/replay TODO -> `docs/collaboration/inbox.md`
  - next-question decision TODO -> `docs/collaboration/inbox.md`
  - collaboration/gate sequence -> 若命 runtime contract and PRD playbook
- blocking_quality_gaps: none for PRD
- REFUSAL_FEEDBACK: not required

## PRD_READINESS_GATE

- verdict: `PRD_READY`
- can_tingyun_plan_without_guessing: no from PRD alone; yes only after
  `PRODUCT_STRUCTURE_SPEC v5`, required `UX_FLOW_SPEC v5`, data/project
  boundary details, codebase reconnaissance, architecture context, validation
  targets, and technical-plan authorization are present
- can_qingqiu_spec_ux_without_guessing: yes, after `PRODUCT_STRUCTURE_SPEC v5`
  enumerates step types and visible states
- can_data_rules_be_handled_without_guessing: no for implementation from PRD
  alone; product data meaning is started here and must be detailed in product
  structure and engineering contract
- can_guanzhi_write_tests_without_guessing: no for full `TEST_CASE_SPEC` from
  PRD alone; yes only for semantic fixture seed planning until product/UX/
  engineering/skeleton targets exist
- can_jinghua_review_scope_without_guessing: yes
- required_next_artifact: `PRODUCT_STRUCTURE_SPEC v5`
- blocking_questions: none
- REFUSAL_FEEDBACK: not required

## Stop Condition

This clean-slate PRD is ready for 若命 to produce `PRODUCT_STRUCTURE_SPEC v5`.
It does not authorize `TECHNICAL_PLAN`, `ENGINEERING_CONTRACT`,
`IMPLEMENTATION_BLUEPRINT`, tests, or implementation by itself.
