# AI Native Math Learning Product Structure v5

Status: PRODUCT_STRUCTURE_READY_FOR_UX_AND_ENGINEERING_SOURCE_CHALLENGE
Owner: 若命 (`ruoming`)
Created: 2026-07-11 CST
Source PRD: `docs/product/ai_native_math_learning_prd_v5.md`

Historical product structures are not sources for this document.

## Objective

Turn PRD v5 into executable product structure for the single-child math learning
loop: one current step, child answer, AI analysis, evidence gate, teaching or
repair, next-step decision, and evidence-backed summary.

## Scope

- One child Web surface.
- Parent/Codex evidence query only; no parent Web dashboard.
- Math review and new-knowledge learning bound to graph nodes.
- Adaptive step-by-step selection; no fixed worksheet.
- Text, photo, stuck, and clarification evidence.
- Child-safe projection plus Codex-readable evidence record.

## Non-Goals

- No multi-user product shell.
- No parent grading or parent approval step.
- No automatic active self-evolution mutation.
- No external textbook/private question import.
- No implementation architecture choice in this document.

## Project Boundary Overlay

Known stable rules:

- Single child, math first, summer bridge from critical primary gaps to Grade 7.
- Every question, teaching action, evaluation, plan, and report must bind to
  graph nodes.
- Grade 7 failure checks prerequisite chains before same-type drilling.
- Child page must be simple, age-respectful, and free of internal ids, rubrics,
  provider names, queue states, or Codex instructions.
- Runtime owns authoritative transitions; internal agents provide structured
  suggestions and evidence, not direct state mutation.

Assumptions for downstream planning:

- SQLite local-first remains acceptable unless 听云 proves a blocker.
- Text AI uses GPT-compatible route; photo/OCR uses configured vision route.
- A normal day targets 10-20 interactions, but runtime may stop early for
  repeated stuck, pending/blocked evidence, or intensive repair.

## Actors / User Roles

| Actor | Product role | Can do | Cannot do |
|---|---|---|---|
| Son | Learner | Start/resume, answer text, upload photo, mark stuck, clarify, continue, finish | See graph ids, question ids, attempts, provider/model, rubrics, queue/job state, parent/operator controls |
| Parent | System owner via Codex | Ask progress, evidence, weak points, system problems, improvement direction | Grade answers, approve steps, operate child flow in a Web dashboard |
| Runtime | Deterministic controller | Select step, persist evidence, queue work, apply gates, update state, project child-safe data | Guess mastery from pending/mock/stale evidence |
| Internal learning agents | AI functions | Analyze answers, teach, evaluate, plan, generate/review questions under contracts | Mutate authoritative state directly |
| Codex / agent team | Improvement surface | Inspect records, change system through artifacts/review/QA | Replace normal child learning loop with manual intervention |

## Module Inventory

| Module | Purpose | User value | Priority | Dependencies | Non-goals |
|---|---|---|---|---|---|
| Child Current Step Surface | Show exactly one current action | Child always knows what to do next | P0 | Runtime projection, UX spec | Fixed worksheet, parent view |
| Daily Runtime | Own flow/step state and transitions | Stable independent learning session | P0 | Product states, DB contract, queue | Model-driven orchestration |
| Evidence Capture | Save text/photo/stuck/clarification first | No lost work; async-safe | P0 | Attempt/attachment records | Synchronous grading wait |
| Answer Analysis | Judge answer and reasoning semantically | Feedback respects multiple methods | P0 | Model adapter, answer-analysis contract | String matching |
| Evidence Gate / Evaluation | Decide usable evidence and mastery deltas | No fake mastery | P0 | Analysis, graph, trust labels | One answer = durable mastery |
| Teaching Package | Explain first cognitive break and next small action | Child can repair without parent | P0 | Analysis/evaluation | Backend diagnostic dump |
| Next-Step Planner | Select next step from evidence and graph | Adaptive, not worksheet | P0 | Graph target pool, candidate packet | Feeding full bank to model |
| Question Bank / Quality Gate | Provide high-quality graph-bound candidates | Respect Grade 7 level | P0 | Graph, reviewer records | Low-age filler drills |
| Session Record / Report | Persist replayable evidence and summaries | Parent can query truthful progress | P0 | All records, trust labels | Stale report as current truth |
| Model Router | Isolate provider/model differences | Configurable AI without protocol leaks | P1 | Routes, envelopes | Provider logic in product flow |

## Feature Inventory

| Feature | Module | Actor | User value | Entry surface | Core action | Priority |
|---|---|---|---|---|---|---|
| Start or resume today | Child Current Step Surface | Son | Continue without setup | `/` child page | Load current child projection | P0 |
| Start old review | Daily Runtime | Son | Begin from useful review | child page | Runtime selects first review step | P0 |
| Submit text answer | Evidence Capture | Son | Explain thinking naturally | current step | Save attempt and enqueue analysis | P0 |
| Upload answer photo | Evidence Capture | Son | Use handwritten work | current step | Save attachment and enqueue vision/analysis | P0 |
| Mark stuck | Evidence Capture | Son | Get help without guessing | current step | Save stuck evidence and plan teach/probe | P0 |
| Clarify evidence | Evidence Capture | Son | Repair unclear input | clarify step | Add text/photo clarification | P0 |
| View targeted feedback | Teaching Package | Son | Understand first break | teaching step | Read explanation and do micro-check | P0 |
| Continue to retest/transfer | Next-Step Planner | Son | Prove stability | current step | Runtime chooses next question type | P0 |
| Learn new knowledge | Daily Runtime | Son | Preview Grade 7 content | ready checkpoint | Essence -> model -> example -> check | P1 |
| Finish with summary | Session Record / Report | Son | Know what happened today | summary step | Show short child-safe result | P0 |
| Query evidence | Session Record / Report | Parent via Codex | See progress and weak points | Codex/API/report | Read Codex-readable record | P0 |

## Step Taxonomy

| `current_step.step_type` | Child sees | Allowed responses | Runtime exit states | Evidence rule |
|---|---|---|---|---|
| `question` | A graph-bound problem requiring reasoning | text, photo, text+photo, stuck | analyzing, clarify_evidence, teaching_repair, question, ready_for_new_knowledge, summary, blocked | Attempt required; pending analysis cannot update mastery |
| `micro_check` | One small check after teaching | text, stuck | analyzing, teaching_repair, question, summary, blocked | Confirms local repair only; not durable mastery alone |
| `teaching_repair` | Short explanation and next small action | continue, stuck | micro_check, clarify_evidence, summary, blocked | Teaching shown; no mastery update by reading alone |
| `worked_example` | One worked example for new concept | continue, stuck | micro_check, question, summary, blocked | Example exposure recorded, not mastery |
| `clarify_evidence` | Request for clearer text/photo or conflict resolution | text, photo, text+photo, stuck | analyzing, blocked, summary | Original evidence stays pending/blocked until clarified |
| `ready_for_new_knowledge` | Checkpoint after review | continue_new, finish | worked_example, summary | Requires stable-enough review evidence or safe early stop |
| `blocked` | Honest safe stop/retry state | retry, finish | current step, summary | No hidden grading; Codex record must show cause |
| `summary` | Child-safe finish | finish | terminal | Summary cannot claim pending/mock/stale as mastered |

## Child Visible State Model

| State | Trigger | Child-visible meaning | Main action | Recovery |
|---|---|---|---|---|
| `loading` | Page boot | Connecting | none | load_error if API fails |
| `start_resume` | No active visible step | Today is ready to begin/resume | start/continue | blocked if graph/bank unavailable |
| `current_step` | Runtime selected an actionable step | Do this one thing | submit text/photo/stuck | save_error/upload_error on client/server issue |
| `submitting` | Client sending evidence | Saving work | none | retry idempotently |
| `analyzing_pending` | Evidence saved; analysis incomplete | Work is saved; system is analyzing | wait/refresh | clarify, blocked, next step, or summary |
| `feedback_teaching` | Analysis/evaluation calls for repair | Read targeted help | continue/stuck | micro_check or summary |
| `clarify_evidence` | Evidence unclear/conflicting | Need clearer answer | submit clarification | blocked/summary if repeated |
| `ready_for_new_knowledge` | Review stable enough | Can learn new content or finish | continue/finish | summary |
| `blocked` | Runtime/model/OCR/config cannot decide safely | Cannot continue safely now | retry/finish | Codex report carries cause |
| `summary` | Day/session closed or safely stopped | Today’s short result | finish | stale if records change later |

## Flow Contracts

| Flow | Actor | Start | Steps | Success end | Failure/recovery |
|---|---|---|---|---|---|
| Daily old review | Son | Open page/start review | target pool -> one step -> answer -> analyze -> gate -> teach/retest/transfer | ready_for_new_knowledge or summary | blocked/pending summary when analysis cannot complete |
| New knowledge | Son | ready_for_new_knowledge | essence -> model -> worked example -> micro_check -> standard question -> variant | summary with evidence | rollback to prerequisite or teaching_repair |
| Photo answer | Son | current step accepts photo | validate image -> save attachment -> vision/OCR -> answer analysis | usable analysis or clarify | unclear/conflict/hallucination -> clarify_evidence |
| Stuck | Son | current step | save stuck evidence -> micro-teach or prerequisite probe | micro_check/question | repeated stuck -> safe summary |
| Codex progress query | Parent via Codex | Parent asks | read latest records/report | confirmed/weak/pending/blocked separated | stale/missing-lineage explicitly labeled |

## Authoritative Data Objects

| Object | User meaning | Required product fields | Source | Consumers |
|---|---|---|---|---|
| `daily_flow` | One day/session learning thread | id, child_key, local_date, mode, status, current_step, revision, summary, graph_version | Runtime | Child projection, reports |
| `flow_step` | One child-visible action | step_type, status, position, node_id, question_id, prompt_package, selection_reason, attempt_id | Runtime/planner | Child projection, evidence gate |
| `attempt` | Child response evidence | response mode, raw text, stuck flag, attachment refs, analysis status, trust label | Evidence capture | Analysis, evaluation, report |
| `attachment` | Uploaded written work | kind, content type, path, hash, OCR/vision refs | Evidence capture | Vision/OCR, audit |
| `answer_analysis` | Semantic judgment | final answer, method, steps, symbols/units, check, alternatives, process gap, confidence, next prompt | Answer analysis agent | Evidence gate, teaching, evaluation |
| `evidence_validation` | Whether analysis can be used | trust label, usability, rejection reason, lineage refs | Runtime gate | Evaluation, planner, report |
| `evaluation_update` | Node mastery evidence delta | node, dimensions, before/after, applied/rejected, source evidence | Runtime/evaluation | Planner, report |
| `teaching_package` | Child-facing repair/new concept content | first break, explanation, worked example/micro-check prompt, next action | Teaching agent/runtime | Child projection |
| `next_step_decision` | Why the next action was chosen | action, target node, source evidence, candidate packet id, reason, blocked/pending flags | Runtime/planner | Flow step, report |
| `daily_summary` | End-of-session truth | child-safe result, Codex evidence facts, trust labels, freshness/version | Runtime/report | Child page, Codex |

## Response Mode Matrix

| Mode | Valid on | Required handling | Mastery effect |
|---|---|---|---|
| `text` | question, micro_check, clarify_evidence | Save text before analysis | Only after valid analysis and evidence gate |
| `photo` | question, micro_check, clarify_evidence | Save image, verify bytes/hash, run vision/OCR as untrusted evidence | No mastery if OCR low-confidence or unsupported |
| `text_photo` | question, micro_check, clarify_evidence | Analyze text and photo; flag conflicts | Conflict requires clarification unless contract resolves it safely |
| `stuck` | question, micro_check, worked_example, teaching_repair | Save stuck evidence | No mastery; drives micro-teach/prerequisite probe/safe stop |
| `clarification` | clarify_evidence | Link to original attempt/evidence | Can unblock original evidence only after analysis |
| `continue` | teaching_repair, worked_example, ready_for_new_knowledge | Record exposure/transition | No mastery by itself |

## Planner Action Taxonomy

| `next_action` | Use when | Child-visible next step |
|---|---|---|
| `same_structure_retest` | Reasoning mostly right but unstable | Similar, non-identical question |
| `near_transfer_retest` | Current structure stable enough | Variant representation/context |
| `prerequisite_probe` | Current failure may come from prerequisite | Smaller prerequisite question |
| `micro_teach` | First break is known and teachable | Short explanation then micro_check |
| `worked_example` | New concept or severe stuck | Worked example then check |
| `clarify_evidence` | Evidence unclear, photo low-confidence, conflict, blank | Ask for clearer text/photo |
| `continue_new_knowledge` | Review stable enough and budget remains | New concept teaching step |
| `stretch` | Prerequisites stable and transfer goal exists | Controlled extension problem |
| `summary` | Budget done, repeated stuck, blocked, or enough evidence | Child-safe summary |
| `blocked` | Runtime/model/config cannot decide safely | Honest blocked state |

## Evidence Trust Labels

Trust labels describe source reliability, not mastery:

- `confirmed`
- `pending`
- `blocked`
- `inferred`
- `stale`
- `mock_only`
- `missing_lineage`

Mastery labels describe learning condition and must stay separate:

- `untested`
- `weak`
- `partial`
- `unstable`
- `stable_for_now`
- `due_for_spacing`
- `ready_for_transfer`

## Candidate / Question Selection Rules

- Runtime prefilters graph targets from untested, weak, failed, due,
  prerequisite, and new-learning nodes.
- Runtime builds a bounded candidate packet; planner/model never receives the
  full question bank.
- Candidate packet must include graph node, question family, difficulty/age
  floor, evidence goal, reasoning requirement, recent-use exclusion, review
  lineage, and rejection summary.
- Low-age mechanical drills, answer-only prompts, no-reasoning prompts,
  fake prior-error claims, missing graph lineage, and child-facing agent/meta
  wording are rejected before active use.
- Controlled stretch is allowed only after prerequisite stability and must be
  labeled as transfer/extension, not mainline repair.

## Summary Contract

Child-safe summary fields:

- short title
- what went well
- one or two things to keep working on
- pending/blocked note if any
- next child action

Codex-readable summary fields:

- flow/session handle and freshness version
- graph nodes touched
- steps shown and selection reasons
- child evidence ids and response modes
- answer-analysis status and trust label
- teaching actions shown
- evaluation updates applied/rejected with reasons
- next-step decisions and source evidence
- pending/blocked/stale/mock-only/missing-lineage flags
- report generation timestamp and source record versions

## External Side Effects

Allowed:

- local SQLite writes
- local answer-photo files
- configured model API calls through model adapter
- local reports under `docs/system/daily_reports/`

Forbidden without explicit authorization:

- destructive reset of real learning data
- cloud deployment or external account writes
- storing API keys/secrets in DB/docs/logs/reports/screenshots
- importing private/copyrighted external question banks

## Acceptance Paths

| Scenario | Given | When | Then | Evidence required |
|---|---|---|---|---|
| Start/resume | Child opens page | Active flow exists or must be created | One current child-safe action appears | Browser trace and child API payload |
| Text answer | Current step accepts text | Child submits | Attempt saved before model call; job queued | DB attempt/job and page analyzing state |
| Photo answer | Current step accepts photo | Child uploads work | Attachment saved; OCR untrusted until validated | Attachment hash, analysis/clarify record |
| Stuck | Child cannot start | Child marks stuck | Teaching/probe/safe summary, not random next drill | Stuck attempt and decision reason |
| Correct reasoning | Answer and method are sound | Analysis completes | Evidence may improve node state without overclaim | Analysis + evaluation update |
| Right answer wrong reasoning | Final answer right by luck | Analysis detects invalid process | No mastery; targeted repair selected | Oracle fixture and next decision |
| Prerequisite gap | Current node fails | Planner decides next | Nearest prerequisite probe/teach selected | Graph chain and decision record |
| Pending model | Analysis not ready | Page refreshes | No fake grade; pending or independent safe action only | Trust label and child state |
| Model/config failure | Route missing/failing | Evidence submitted | Blocked/pending state with Codex-readable cause | Job/route metadata, no mastery update |
| Summary | Day closes | Records exist | Summary includes all evidence, not last question only | Daily summary and freshness label |
| Child-safe API | Child route payload returned | Payload/DOM scanned | No ids/provider/rubric/queue internals leak | Automated scan |
| Restart/double submit | Service restarts or child retries | Runtime recovers | No duplicate attempts/jobs/decisions/summaries | DB uniqueness and recovery evidence |

## Required Downstream Artifacts

- `UX_FLOW_SPEC v5` by 清秋.
- `TECHNICAL_REVERSE_SPEC` by 听云 before planning.
- `TECHNICAL_PLAN v5`, `ENGINEERING_CONTRACT`, `IMPLEMENTATION_BLUEPRINT` by 听云.
- `TEST_CASE_SPEC v5` and `QA_AUDIT_PLAN` by 观止.
- 镜花 design/code review for architecture, skeleton, and implementation.

## Product Structure Quality Gate

- verdict: `PRODUCT_STRUCTURE_READY_FOR_UX_AND_ENGINEERING_SOURCE_CHALLENGE`
- product_scope_preserved: pass
- fixed_worksheet_removed_from_v5_scope: pass
- child_surface_boundary_clear: pass
- state_and_step_taxonomy_defined: pass
- response_modes_defined: pass
- data_objects_and_summary_split_defined: pass
- evidence_trust_vs_mastery_labels_separated: pass
- downstream_guessing_risk: reduced but not eliminated; UX and engineering
  must still run their own source-readiness challenges
- blocking_gaps: none for UX/technical reverse/spec drafting

## Stop Condition

若命 product structure is ready for 清秋 `UX_FLOW_SPEC v5` and 听云
`TECHNICAL_REVERSE_SPEC` / source-readiness challenge. It does not authorize
implementation by itself.
