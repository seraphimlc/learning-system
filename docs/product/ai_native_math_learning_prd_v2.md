# AI Native Math Learning System PRD v2

Status: draft for multi-agent review
Owner: 若命 (agentKey: `ruoming`)
Created: 2026-07-08 00:48 CST
Updated: 2026-07-08 17:30 CST for QB11 controlled-challenge contract and evolved-source evidence gate.

This file is the product contract for restarting the work from PRD first. It replaces implementation-first assumptions for the next delivery cycle. It does not claim the current system already satisfies every requirement.

## Evidence Sources

- User decisions in this Codex thread through 2026-07-08.
- `AGENTS.md`
- `docs/00_PROJECT_BLUEPRINT.md`
- `docs/domain-index/math-learning.md`
- `docs/system/local_learning_system.md`
- `docs/system/qa/question_bank_grade_level_latest.md`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- `app/local_learning_system/*`
- `learning_system/*`
- User-provided photo sample: difficulty calibration only, not a source to copy.

## PROJECT_BOUNDARY_OVERLAY - 若命 (agentKey: `ruoming`) - 2026-07-08 00:48 CST

Scope:
Single-child AI-native math learning system for summer bridge from primary-school gaps to incoming Grade 7 math preview.

Status:
Stable for product direction; provisional for final UI taste and live-model semantic quality until review and QA run against rendered pages and real model outputs.

Known facts:
- The system has exactly two human users: the son and the parent.
- The son interacts with one Web child端 only.
- The parent interacts with Codex, not with a parent dashboard.
- The parent mainly does two things: ask Codex about learning progress/results, and discuss/authorize system improvements.
- Codex is a query/operator surface, not a runtime result container. The learning system must not create or rely on separate Codex sessions/threads to deliver generated results; internal agent outputs are persisted to DB/report artifacts and Codex reads them on demand.
- Normal learning must not require parent intervention.
- Every teaching, diagnosis, question, attempt, evaluation, plan, and self-evolution event must bind to the math knowledge graph.
- Current graph has 56 nodes and includes primary prerequisites, bridge nodes, and Grade 7 mainline nodes.
- Current active round size target is 10 tasks.
- Current question-bank target is at least 20 active high-quality question slots per graph node, with versioned releases, reviewer records, distinct core evidence, and live active-use gates.
- Current code/audit baseline is `2026-07-08.bank.v11` / `QB11`: 1120 generated items for 56 nodes in the controlled test/audit path, with per-node 20-slot coverage, node-local mainline floors, controlled picture-level extension caps, and lineage audit checks.
- A normal 10-task round should primarily collect node-local mainline evidence. Controlled picture-level / competition-style tasks are stretch probes, normally 1-2 per round, not broad coverage filler.
- Reference answers are rubric context; grading must be AI-first and reasoning-aware.
- A correct final answer with missing, lucky, circular, or wrong reasoning is not full mastery.
- Answer photos are supported and must be treated as untrusted OCR/vision evidence.
- Low-age mechanical drills are forbidden unless real evidence shows a narrow repair need.

Assumptions:
- Math remains the first phase; English is out of scope for this PRD.
- Local SQLite remains acceptable for the next implementation cycle as the evidence ledger unless 听云 proves it blocks required reliability.
- GPT-compatible text models are the default for answer analysis and question generation. Doubao-compatible vision is allowed for photo transcription. DeepSeek may be reintroduced only through the compatibility adapter and tests.
- The product is local/private; no production auth, payments, multi-tenant admin, or cloud deployment is required in this cycle.

Missing decisions:
- Final visual style needs human taste review after rendered UX evidence.
- Exact daily time split between new knowledge and remediation may be adjusted from real evidence.
- External textbook or commercial question-bank use is not authorized.

Role-specific project rules:

| Role | Rules | Source | Missing boundary | Applies to |
|---|---|---|---|---|
| 听云 | Do not choose architecture before consuming this PRD and product structure. Keep child API separate from operator/Codex API. Preserve old evidence compatibility and recovery paths. | user decisions, `AGENTS.md`, `docs/system/local_learning_system.md` | final production deployment target | technical plan, contracts, skeleton |
| 清秋 | Design one child-facing learning surface, not a dashboard. The page must help a soon-to-be Grade 7 student work independently without seeing backend agent concepts. | user decisions, `AGENTS.md` | final aesthetic taste | UX flow, design read, rendered review |
| 霜弦 | Data/content must be graph-bound, versioned, evidence-gated, and traceable. Do not treat generated question metadata as proof of quality without reviewer records. | `docs/domain-index/math-learning.md`, QA report | external content sources | data contract, content review |
| 镜花 | Review state machines, async recovery, model adapter behavior, evidence gates, child-safe boundaries, and whether implementation follows skeleton/test gates. | collaboration protocol, project docs | none for design review | technical and code review |
| 观止 | Test cases must cover false-pass risk, semantic grading, async waiting, visual/interaction regression, photo/OCR, and multi-round convergence. Happy-path smoke is not enough. | `AGENTS.md`, QA addendum, collaboration protocol | real child answers for long-run oracle | TEST_CASE_SPEC and QA |

Protected data / side effects:
- Do not delete real attempts, uploads, or evidence without explicit authorization.
- During tests, database reset is allowed only when the test environment is explicit.
- Never print API keys or write them into source, docs, reports, or QA artifacts.

Domain rubric / oracle:
- Target level is incoming Grade 7 with appropriate stretch.
- Valid tasks require observable reasoning: model, relation, step, check, counterexample, proof, or error diagnosis.
- The photo sample sets difficulty style: digit/place-value modeling, square-layer coordinate patterns, divisibility existence proof, and similar reasoning-heavy tasks.
- Olympiad-style problems are controlled extension, not the mainline.
- Picture-level challenges may appear only when semantically anchored to an allowed graph node and marked as `picture_level_extension`; they cannot substitute for node-local evidence on unrelated nodes.
- Questions that only test easy arithmetic, final-answer recall, or "multiply both numbers by 100" level mechanics fail the product bar unless targeted by recent evidence.

Model/provider policy:
- Model calls must go through route/adaptation code, not direct ad hoc HTTP.
- Unsupported structured-output formats must degrade to compatible JSON modes and local validation.
- If no evaluator model is configured, attempts remain pending and must not drive mastery, planning, reports, or evolution.
- No deterministic fake grading may be treated as live semantic model evidence.

UX/product constraints:
- Child page must support open written answers and photo upload.
- Child submission must save and advance without waiting for model grading.
- End-of-round waiting must explain what is happening and recover from pending/error states without asking the parent to intervene.
- The page must show all relevant per-question review points when a 10-task round completes, not only the last question.
- Child-facing copy must not expose graph node ids, model names, agent internals, rubric internals, or operator actions.

Persistence target:
- This PRD is durable at `docs/product/ai_native_math_learning_prd_v2.md`.
- Downstream technical plan, skeleton, and test specs should link to this file.

Invalidation trigger:
- Update this PRD if user roles change, parent dashboard becomes in scope, external content is authorized, non-local deployment becomes required, or real child usage changes the teaching loop.

Next action:
Dispatch 清秋, 霜弦, 听云, 镜花, and 观止 in the formal gate order.

## PRD_SPEC - 若命 (agentKey: `ruoming`) - 2026-07-08 00:48 CST

Objective:
Define the next implementation cycle for a usable single-child AI-native math learning system, with a PRD-first, architecture-first, skeleton-first, test-first process.

User / actor:
- Son: uses the Web child端 to learn, answer, upload photos, receive feedback, and continue to the next learning action.
- Parent: uses Codex to ask about progress/results and to discuss system direction or improvements.
- Internal teaching agents: hidden system roles that orchestrate, bind graph evidence, generate/review questions, analyze answers, evaluate mastery, explain, plan, and self-evolve.
- Codex collaboration roles: 若命 coordinates product/gates; 听云 designs/builds; 清秋 defines UX; 霜弦 defines data/content contract; 镜花 reviews engineering; 观止 designs tests and QA.

Problem:
The current system was built too implementation-first. Some useful mechanisms exist, but prior instability came from weak PRD, unclear technical contract, weak test definitions, and insufficient product flow alignment. The child flow also risked waiting without useful next action, and early questions were below the target learner level.

Desired outcome:
The son can complete an entire learning round without parent intervention. After submission, the system automatically grades by AI, analyzes reasoning, updates graph-bound mastery, evolves question/profile rules from real evidence, plans the next round, and gives child-safe feedback. The parent can ask Codex for progress and system design changes using durable evidence/reports.

Scope:
- One child Web端: learning task page, answer entry, photo upload, saved progress, end-of-round review, next-round entry.
- Two supported learning modes:
  - Diagnostic/remediation mode: child does 10 graph-bound tasks, system analyzes weak nodes and prerequisite chain, then explains/repairs/plans.
  - New-knowledge mode: child learns one graph-bound concept, does checks, receives targeted explanation, consolidation, and stretch tasks until evidence supports understanding.
- Internal teaching agent workflow:
  - `session_orchestrator_agent`: controls the round state machine.
  - `graph_agent`: binds questions, evidence, mistakes, and prerequisites to graph nodes.
  - `question_designer_agent`: produces graph-bound candidate questions from node, goal, and evidence.
  - `question_reviewer_agent`: blocks low-signal or age-inappropriate questions.
  - `answer_analysis_agent`: grades answer, reasoning, alternatives, process gap, and next prompt.
  - `evaluation_agent`: updates mastery dimensions without treating one success as full mastery.
  - `teaching_agent`: produces child-safe explanation and next-step feedback.
  - `planner_agent`: selects remediation, rollback, consolidation, stretch, or next learning point.
  - `self_evolution_agent`: changes rules/profiles/questions only from real analyzed evidence.
- Content/data:
  - Knowledge graph remains the source of teaching structure.
  - Question specs should be data-driven where possible: standards, families, seed examples, rubrics, and forbidden patterns should not live only inside Python code.
  - Each graph node needs at least 20 active high-quality question slots, but those slots must contain enough node-local mainline core stems and cannot be inflated by wrapper variants or transplanted picture-level puzzles.
  - A round should select by evidence and recent history, not cycle fixed tasks. The round target is 10 tasks, with at least 7 node-local mainline tasks and normally 1-2 controlled picture-level stretch probes when the planner can justify them.
- Model integration:
  - GPT-compatible text model is default for answer analysis and question generation.
  - Vision route may use Doubao-compatible model for answer photos.
  - Model compatibility adapter is required for different JSON modes and endpoints.
- Reporting:
  - Daily/progress report for Codex must summarize progress, evidence, pending jobs, weak nodes, next plan, and system issues.
  - Generated teaching, review, planning, evolution, and QA results must be stored in the evidence ledger/report artifacts first. Parent-visible Codex answers are derived queries over those stored facts, not separate result-feedback sessions.
- Review/testing process:
  - PRD -> product structure -> UX/data contracts -> technical plan/contract/blueprint -> skeleton -> review -> TEST_CASE_SPEC -> implementation -> review/QA.

Non-goals:
- No parent Web dashboard in this cycle.
- No multi-user account system.
- No generic education SaaS features.
- No commercial/private textbook question import.
- No full English-learning implementation.
- No production cloud deployment, billing, analytics productization, or external publishing.
- No manual parent grading workflow as a normal product path.
- No Olympiad track as the mainline.

User stories / flows:
- As the son, I open the page and immediately know what to do next: learn a small concept, answer task 1 of 10, or continue a saved group.
- As the son, I can type steps or upload a photo of paper work, save the answer, and move to the next question without waiting for AI.
- As the son, after all 10 tasks, I see a clear review of every relevant task once analysis is ready, then a next action: review explanation, retry consolidation, stretch, or start the next group.
- As the parent, I ask Codex "progress?" and receive a report based on DB/API evidence, not a page requiring copy-paste.
- As the system, I do not call a node mastered from a single correct answer. I separate concept, model, calculation, expression, and transfer evidence.
- As the system, I do not create or schedule a weak evolved question unless it passes the reviewer gate and links to valid source evidence.

Acceptance criteria:

| ID | Scenario | Given | When | Then | Evidence required |
|---|---|---|---|---|---|
| AC-01 | Child starts a round | Local DB initialized and child opens `/` | `/api/child-bootstrap` loads | Child sees exactly one active learning group with 10 child-safe tasks and no internal ids | Browser screenshot, `/api/child-bootstrap`, DB session/plan rows |
| AC-02 | Async submission | A child submits a written answer or photo for task N | `/api/child-submissions` receives task position and group handle | Answer is saved, attempt is queued/pending or graded, page advances to task N+1 without blocking on model latency | API response timing, DB attempt row, background job row, browser flow |
| AC-03 | End-of-round wait | All 10 tasks are submitted and at least one review is pending | Child completes the group | Page shows child-safe reviewing state with retry/poll behavior and no parent action instruction | Browser state, `/api/learning-sessions/current-learning-group/complete`, background job state |
| AC-04 | Round closure | All 10 tasks are submitted and structured answer analysis exists | Session complete is called | Internal agent chain runs; child sees per-question review points and next action | `agent_runs`, `session_steps`, closure payload, child UI |
| AC-05 | Reasoning-aware grading | Final answer is right but reasoning is absent/wrong | AI review runs | Result is partial or wrong, with process gap and next child prompt | `answer_analysis_json`, model audit metadata, QA semantic sample |
| AC-06 | Photo answer | Child uploads PNG/JPG/WebP paper answer | Submission saves | Attachment is validated, stored, OCR/vision evidence is used as untrusted input, low-confidence remains pending | upload file, attachment row, review meta |
| AC-07 | Question quality | A round is generated for incoming Grade 7 | Scheduler selects tasks | 10 graph-bound tasks appear; at least 7 are node-local mainline evidence tasks; 1-2 may be controlled picture-level stretch probes only when semantically anchored; no low-age mechanical filler appears | question-bank audit, sampled prompts, reviewer records |
| AC-08 | Graph rollback | A Grade 7 task exposes a prerequisite weakness | Evaluation/planner runs | Planner checks prerequisite chain before same-topic drilling | node status, planner transition, graph binding |
| AC-09 | Self-evolution | Real graded weak evidence with structured analysis exists | Session closes | Self-evolution updates profile/rules/status or creates approved evolved retest; pending/fake evidence does nothing | evolution audit, question review record, agent profile revision |
| AC-10 | Parent via Codex | Parent asks for progress | Report command/API reads evidence | Parent receives progress, results, weak points, pending blockers, and next plan without using a parent dashboard | daily report and command/API evidence |
| AC-13 | No Codex session result channel | Internal agents finish grading/planning/evolution/report work | Parent later asks Codex for progress | Codex answers by reading DB/API/report artifacts; no new Codex thread/session is required as product output | DB rows, report artifact, no user-visible copy-to-session workflow |
| AC-11 | Model config failure | API key/model route missing or incompatible | Child submits answers | Attempts remain pending/waiting with explicit auditable reason; no fake grading or false mastery | startup route status, attempt review_meta, closure status |
| AC-12 | Regression testing | Implementation claims completion | 观止 runs QA matrix | Tests cover child flow, API, DB state, model semantics, async recovery, photo/OCR, visual/interaction states, and multi-round convergence | TEST_CASE_SPEC, QA report, commands, screenshots |

Data / state meaning:
- `question_item`: graph-bound question candidate or released item. Must carry version, source, reviewer eligibility, node id, rubric, and reasoning requirements.
- `learning_plan`: selected task group for the next child round, not a static calendar.
- `learning_session`: one child learning group, normally 10 tasks, with expected question ids and closure state.
- `attempt`: child evidence for one task. Pending attempts are not mastery evidence.
- `answer_analysis_json`: structured model/system analysis required before evaluation/planning/evolution.
- `background_job`: durable async review work item with retry/recovery state.
- `learner_node_status`: graph node mastery summary derived from valid graded evidence.
- `evolution_event`: auditable evidence-driven change, not a test-only mutation.
- `agent_run`: internal agent evidence/audit trace.
- `daily_report`: Codex-readable parent progress surface.
- `codex_query`: an on-demand operator read of persisted evidence. It is not a persisted learning result by itself and must not replace DB/report writes.

External side effects:
- Local filesystem and SQLite writes only.
- Model API calls are allowed through configured environment variables.
- No external publishing, account writes, or irreversible platform operations.

Model/content quality bar:
- All question and teaching output must be graph-bound.
- Answer analysis must compare final answer, model/relation, steps, symbols/units, and check/explanation.
- Alternative valid solutions must be recognized.
- Child-facing feedback must be actionable and not expose backend analysis.
- Question generation must target the child's level: incoming Grade 7, with controlled stretch, not primary-school arithmetic drills.
- Content must avoid copying private/commercial materials; user samples are calibration only.

UX constraints:
- One child-facing page/app.
- No parent dashboard, manual grading console, graph/debug panel, model config panel, or copy-to-Codex instruction in the child product.
- The child page should be simple but not childish: clear task focus, stable progress, open answer area, photo affordance, saved feedback, and end-of-round review.
- Waiting states must say what the system is doing and what the child can do now.
- All text must fit in mobile and desktop layouts; no overlapping controls or giant marketing hero.

Permissions / security:
- Child APIs accept task position and `current-learning-group` handle, not raw internal ids.
- Operator APIs may expose internal ids and reports for Codex maintenance only.
- Uploaded answer photos are local evidence and must not be served outside attachment API validation.
- API keys stay in `.env.local` or shell environment only.

Rollout / rollback:
- Next cycle should be built behind explicit docs and tests.
- DB reset is allowed in test stage but must be clearly named as test-only.
- Existing real evidence should be backed up before destructive test setup.
- Question-bank versions should be append/versioned; old attempted items remain audit evidence but are not active candidates.

Open questions:
- Final visual taste and exact child copy need rendered review with the parent/child.
- Long-run mastery thresholds may be tuned after real multi-day evidence.
- Whether to move question specifications fully to JSON/JSONL/Markdown in this cycle or stage it behind a loader depends on 听云's plan.

Required artifacts:
- `PRODUCT_STRUCTURE_SPEC` in this file.
- `UX_FLOW_SPEC` from 清秋.
- `DATA_CONTRACT_SPEC` from 霜弦.
- `TECHNICAL_PLAN`, `ENGINEERING_CONTRACT`, `IMPLEMENTATION_BLUEPRINT`, and `SKELETON_PASS` from 听云.
- `DESIGN_REVIEW` from 镜花 before implementation.
- `TEST_CASE_SPEC` from 观止 after skeleton.
- QA plan/report after implementation.

Required gates:
- 镜花 design review for technical plan/contract/blueprint/skeleton.
- 清秋 UX review for child page skeleton.
- 霜弦 data/content review for graph, question-bank, model-output, and evidence contracts.
- 观止 test case design before business logic, then QA after implementation.

Stop condition:
This PRD is ready for downstream planning when child flow, internal agents, data states, model/content quality, UX constraints, and acceptance criteria are concrete enough that 听云 does not need to invent product behavior.

## PRODUCT_STRUCTURE_SPEC - 若命 (agentKey: `ruoming`) - 2026-07-08 00:48 CST

Objective:
Turn the PRD into executable product structure for downstream UX, data, architecture, skeleton, and test design.

Source PRD / decisions:
`docs/product/ai_native_math_learning_prd_v2.md`, user decisions through 2026-07-08, `AGENTS.md`, project blueprint, current local system docs.

Scope:
Single-child math learning loop for diagnosis/remediation and new-knowledge learning, with Codex as parent/operator conversation surface.

Non-goals:
Parent web dashboard, generic LMS features, multi-user auth, production cloud deployment, English implementation, commercial question import.

Project boundary overlay:
See `PROJECT_BOUNDARY_OVERLAY` above.

Actors / user roles:
- Son: child learner.
- Parent: Codex collaborator, not a web-app operator.
- Internal teaching agents: hidden runtime roles.
- Codex collaboration agents: project delivery roles.

Module inventory:

| Module | Purpose | User value | Priority | Dependencies | Non-goals |
|---|---|---|---|---|---|
| Child Learning Surface | Let the son learn, answer, upload photo, see review, and continue | Independent learning without parent interruption | P0 | child APIs, plan/session state | parent dashboard |
| Session Orchestration | Own round state machine and closure | A full group can finish and move forward | P0 | sessions, attempts, background jobs | direct grading or question generation |
| Knowledge Graph Binding | Bind content and evidence to graph nodes/prereqs | Weaknesses and next steps are explainable | P0 | math graph, question metadata, attempts | vague "careless" labels |
| Question Production | Generate/select high-quality graph-bound tasks | Useful diagnosis and stretch | P0 | graph, evidence, review gate | low-age filler, fixed drill cycles |
| Question Review Gate | Reject weak questions before active use | Protects child from insulting or useless tasks | P0 | question specs, reviewer rules | maximizing quantity |
| Answer Analysis | Evaluate answer, reasoning, alternatives, process gap | Fair grading for open answers/photos | P0 | model router, OCR, rubric, attempt evidence | exact string matching |
| Evaluation and Planning | Update node status and choose next action | Learning adapts after every round | P0 | analyzed attempts, graph prereqs, plans | one-right-answer mastery |
| Teaching Feedback | Give child-safe explanation and next prompt | The child knows what to fix or try next | P0 | answer analysis, evaluation | backend report dumping |
| Self-Evolution | Improve rules/questions/profiles from evidence | System gets better from real use | P1 | valid graded evidence, audits | fake/test-only evolution |
| Evidence Ledger | Persist questions, attempts, jobs, agent runs, reports | Codex can inspect truth | P0 | SQLite/schema | hidden in-memory state |
| Model Routing | Route GPT/Doubao/other models safely | Stable model calls and future provider changes | P0 | env config, adapter, schemas | direct provider-specific calls in agents |
| Codex Reports | Parent progress and system state via Codex | Parent sees progress without dashboard | P0 | DB/API/report scripts | copy-paste prompts from UI |
| QA Harness | Validate product, model, UI, and async behavior | Prevent false pass | P0 | tests, browser automation, fixtures | smoke-only QA |

Feature inventory:

| Feature | Module | Actor | User value | Entry surface | Core action | Priority |
|---|---|---|---|---|---|---|
| Start/continue group | Child Learning Surface | Son | Resume safely | `/` | Load current group and tasks | P0 |
| Open answer | Child Learning Surface | Son | Show reasoning | answer textarea | Type steps/explanation | P0 |
| Photo upload | Child Learning Surface | Son | Submit paper work | file input/camera | Attach answer image | P0 |
| Save and advance | Child Learning Surface | Son | No model waiting per task | submit button | Save attempt and move next | P0 |
| End-of-round review | Child Learning Surface | Son | Understand all task results | completion state | Show per-question review and next action | P0 |
| Diagnostic round | Orchestration/Planner | System | Find weak nodes | plan/session | Select 10 diagnostic/remediation tasks | P0 |
| New knowledge round | Orchestration/Teaching | System | Learn then verify | plan/session | Explain, check, consolidate, stretch | P0 |
| Background review | Answer Analysis | System | Async model grading | background job queue | Process pending attempts | P0 |
| Graph rollback | Evaluation/Planner | System | Fix prerequisites first | session closure | Plan prerequisite repair | P0 |
| Evolved retest | Self-Evolution/Question Production | System | Test a real weak point | session closure | Generate/review retest question | P1 |
| Daily report | Codex Reports | Parent via Codex | Progress and issues | Codex command/doc | Summarize evidence | P0 |
| Question-bank audit | QA/Data | Codex/agents | Content quality guard | script/report | Check per-node coverage and difficulty | P0 |
| Model compatibility | Model Routing | System | Provider changes do not break flow | model_router | Try compatible JSON modes and validate | P0 |

Page / surface map:

| Page/surface | Purpose | Entry | Main actions | Required states | Empty/loading/error/success behavior |
|---|---|---|---|---|---|
| Child learning page `/` | One place for child to learn and answer | Browser at 8765 | read prompt, type answer, upload photo, save, complete group | loading, no group, active task, answered task, all submitted, reviewing, reviewed, error | loading skeleton; no group starts/loads plan; errors are child-safe with retry; reviewed shows all relevant task feedback |
| Codex report surface | Parent progress via Codex/docs/API | parent asks Codex | inspect report/API/DB and discuss direction | current report, pending, blocked, stale | no child-facing copy; report must distinguish evidence vs inference |
| Operator API surface | Codex maintenance only | local API | inspect bootstrap, session close, grading backfill, invalidation, reports | success/error/pending | no normal parent UI |

User flows:

| Flow | Actor | Start | Steps | Success end | Failure/recovery |
|---|---|---|---|---|---|
| Diagnostic/remediation round | Son + system | Child opens page | Load group -> answer 10 tasks with text/photo -> save each -> complete group -> background AI analyzes -> internal agents close -> child sees review/next action | Next plan is generated from graph-bound evidence | pending AI shows waiting/retry; low-confidence photo stays pending; config failure is explicit and does not update mastery |
| New knowledge round | Son + system | Planner selects new node | Child reads concise concept/model -> solves checks -> AI reviews reasoning -> teaching agent explains gap -> planner gives consolidation/stretch/retry | Node has evidence-backed updated status and next action | wrong answer triggers explanation and prerequisite or variant selection |
| Parent progress inquiry | Parent + Codex | Parent asks "做到什么程度" | Codex reads latest report/API/DB -> summarizes progress, results, pending blockers, next plan, system issues | Parent can discuss direction without touching child UI | report marks unknown/stale/pending instead of inventing |
| Evidence-driven evolution | System | Weak graded evidence exists | Graph binds -> evaluation identifies dimension -> evolution proposes rule/question/profile change -> reviewer gates question -> planner schedules appropriately | Auditable evolution event with valid source evidence | pending/malformed/invalidated evidence produces no action |
| Model route failure | System | Missing key or unsupported format | Attempt remains pending or adapter falls back -> closure reports waiting/blocker | No fake grade enters evaluation | startup/attempt/session records show reason |

State model:

| Object | States | Transitions | Triggered by | User-visible meaning |
|---|---|---|---|---|
| Learning session | planned, active, all_submitted, waiting_ai, closed, blocked | created -> active -> waiting/closed/blocked | child bootstrap, submissions, complete endpoint, background worker | child sees active/reviewing/reviewed/error only |
| Task | not_started, answered, current, reviewed | selected -> answered -> reviewed | page progress and closure | task progress and review points |
| Attempt | pending_review, graded, invalidated | submit -> queued/graded -> analyzed -> invalidated if wrong evidence | child submission, background model, operator maintenance | not directly exposed except saved/reviewed feedback |
| Background job | queued, running, retry, succeeded, failed, cancelled | create -> claim -> result/retry/fail | child submission, recovery worker | reviewing state |
| Node status | unknown, weak/D, partial/C, building/B, mastered/A | evidence reducer updates after analyzed attempts | evaluation agent | summarized only through child-safe next action and Codex report |
| Question item | draft, reviewed_rejected, active_eligible, superseded, retired | generation -> review -> schedule/retire | question designer/reviewer, release migration | hidden from child |
| Agent run | pending, accepted, rejected, blocked, complete | internal workflow steps | orchestrator and maintenance APIs | hidden; visible to Codex/report |
| Evolution event | no_action, state_updated, question_review_rejected, evolved | session closure after valid evidence | self-evolution agent | hidden from child; summarized to Codex |

Permission / boundary:

| Actor/role | Can do | Cannot do | Source rule |
|---|---|---|---|
| Son | Use child page, submit text/photo, complete group, read child-safe feedback | See internal ids, agent reports, rubrics, model config, graph debug, parent dashboard | user decisions, `AGENTS.md` |
| Parent | Ask Codex for progress and system redesign, authorize resets/external model config | Manually grade normal child flow through product UI | user decisions |
| Codex/operator | Inspect DB/API/reports, run scripts, discuss direction, maintain system | Pretend pending/fake evidence is mastery; expose secrets | project rules |
| Internal agents | Act inside assigned runtime contract | Bypass graph/reviewer/evidence gates | PRD and internal agent contracts |
| QA/review roles | Review/test within scoped artifacts | Modify production code unless authorized role allows | collaboration protocol |

Data objects / domain terms:

| Object/term | User meaning | Key fields | Source | Consumers |
|---|---|---|---|---|
| Knowledge graph node | A teachable math capability | id, name, prerequisites, teaching/evaluation contracts | math graph JSON | planner, question generation, evaluation |
| Question family/spec | A reusable task pattern and rubric | node, target evidence, difficulty, forbidden patterns | future data specs + current bank | question designer/reviewer |
| Question item | One concrete task | id, node_id, prompt, rubric, version, review status | DB/question bank | child plan, answer analysis |
| Attempt | Child's submitted evidence | answer text, photo, status, analysis, tags | child API/DB | answer/evaluation/planner |
| Answer analysis | AI reasoning judgment | optimal path, comparison, process gap, next prompt | answer_analysis_agent | teaching/evaluation/planning/report |
| Plan task | What child sees next | position, kind, question reference, child-safe prompt | planner | child page |
| Review point | Child-safe per-question feedback | task index, result, key gap, next prompt | teaching/closure | child page |
| Daily report | Parent/Codex progress surface | progress, evidence, blockers, next plan | report script/API | parent via Codex |

External side effects:
Local DB/files and configured model API calls only.

Model/content behavior:
- AI evaluator must grade open reasoning, not match strings.
- Question designer output is candidate-only; reviewer gate determines active eligibility.
- Planner consumes only active, current, graded, structured evidence.
- Child-facing feedback is sanitized.

Acceptance paths:

| Scenario | Given | When | Then | Evidence required |
|---|---|---|---|---|
| 10-task round works end to end | DB clean and model configured | Child completes 10 tasks | All attempts are analyzed, review points show, next plan is generated | browser, API, DB, agent runs |
| All wrong round | Child gives wrong or blank answers | AI review completes | Review includes each wrong task, gap categories, rollback/consolidation plan | answer_analysis_json, closure message, planner transition |
| Correct answer wrong reasoning | Child submits right final answer with invalid method | AI review completes | Not full correct; process gap and next prompt appear | model sample and local guardrail evidence |
| Photo-only answer | Child uploads clear/unclear photo | Review runs | Clear photo can grade with OCR evidence; unclear remains pending | attachment, review_meta, pending reason |
| Model disabled | `.env.local` lacks key | Child submits | Pending state is explicit and no evolution occurs | startup status, DB, session closure |
| Evolved question validity | Weak structured evidence exists | Evolution proposes question | Reviewer accepts or rejects; only accepted active items with valid non-cyclic source attempt evidence schedule | evolution audit, source attempt audit, and question_review_records |
| Progress report | Parent asks Codex | Report generated | Report separates confirmed, pending, inferred, and blocked facts | latest report with source commands |

Open product decisions:
- Final visual tone after rendered review.
- Exact threshold policy for A/B/C/D after several real sessions.
- Whether to fully migrate question specs out of Python in the first implementation slice or stage it.

Required downstream artifacts:
`UX_FLOW_SPEC`, `DATA_CONTRACT_SPEC`, `TECHNICAL_PLAN`, `ENGINEERING_CONTRACT`, `IMPLEMENTATION_BLUEPRINT`, `SKELETON_PASS`, `DESIGN_REVIEW`, `TEST_CASE_SPEC`, `QA_AUDIT_PLAN`.

Required gates:
清秋 UX design/spec, 霜弦 data/content contract, 听云 architecture/skeleton, 镜花 design review, 观止 test case spec, later QA.

Stop condition:
Downstream agents can plan without inventing product users, surfaces, states, data meanings, model/content rules, or acceptance paths.
