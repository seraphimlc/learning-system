# Project Skeleton Definition v2

Status: ready for TEST_CASE_SPEC draft and later code SKELETON_PASS
Owner: 若命 (agentKey: `ruoming`)
Created: 2026-07-08 CST

This file defines the project skeleton boundaries after PRD, UX, data contract, technical plan, and design reviews. It is not a code `SKELETON_PASS` and does not claim implementation is complete. It is the handoff document that tells 听云 what the later code skeleton must expose and tells 观止 what test cases must be designed before business logic is filled.

## Source Artifacts

- PRD and product structure: `docs/product/ai_native_math_learning_prd_v2.md`
- UX flow spec: `docs/product/child_ux_flow_spec_v2.md`
- Data contract spec: `docs/architecture/data_contract_spec_v2.md`
- Technical plan / engineering contract / implementation blueprint: `docs/architecture/technical_plan_v2.md`
- Engineering review: `docs/collaboration/reviews/2026-07-08-jinghua-design-review-v2.md`
- Engineering review addendum: `docs/collaboration/reviews/2026-07-08-jinghua-design-review-v2-addendum.md`
- Data review: `docs/collaboration/reviews/2026-07-08-shuangxian-data-review-technical-plan-v2.md`
- UX review: `docs/collaboration/reviews/2026-07-08-qingqiu-ux-review-technical-plan-v2.md`

## Review Gate Status

| Gate | Verdict | Scope Meaning |
|---|---|---|
| 镜花 design review | `DESIGN_REVIEW_PASS_WITH_SCOPE` after scoped fix | The plan can proceed to skeleton planning; no runtime/API/DB/model evidence has passed yet. |
| 霜弦 data review | `DATA_REVIEW_PASS_WITH_SCOPE` | Data/content contract is preserved at document level; executable skeleton must still prove shared evidence predicates and lineage gates. |
| 清秋 UX review | `UX_REVIEW_PASS_WITH_SCOPE` | UX planning is sufficient; rendered visual, mobile, focus, copy, and taste remain unproven. |

## Skeleton Objective

Create a reviewable v2 skeleton for the single-child math learning system that exposes page states, API projections, state-machine boundaries, model-route seams, evidence predicates, question-spec migration seams, report labels, and test hooks before non-trivial business logic is filled.

The skeleton must make the system shape visible enough that:

- 镜花 can review state machine, async recovery, model adapter, child/operator separation, and implementation fidelity.
- 清秋 can review child page states, copy boundaries, accessibility hooks, and responsive structure.
- 霜弦 can review graph/question/evidence/report lineage and data gates.
- 观止 can write `TEST_CASE_SPEC` and later QA without guessing file/symbol targets.

## Non-Goals

- Do not build a parent web dashboard.
- Do not fill non-trivial business logic before skeleton review and `TEST_CASE_SPEC`.
- Do not replace the working question bank gates while adding the question-spec migration seam.
- Do not run destructive DB resets or evidence cleanup unless the environment is explicitly test-only.
- Do not expose graph ids, node ids, question ids, attempt ids, session ids, model/provider names, agent names, rubrics, OCR confidence, queue internals, or operator workflow to the child page.

## Human Roles And Runtime Boundaries

| Actor | Surface | Can See / Do | Cannot See / Do |
|---|---|---|---|
| Son | Web child page `/` | Current task, progress, open answer, photo upload, save/advance, reviewing state, all-question feedback, next action | Internal ids, graph/debug fields, model details, agent reports, rubrics, parent workflow |
| Parent | Codex | Progress/results discussion, system direction, approval for resets/external changes | Normal manual grading through product UI |
| Codex/operator | Operator APIs, DB/report scripts | Evidence inspection, maintenance endpoints, reports, on-demand summaries from persisted facts | Pretend pending/fake evidence is mastery; expose secrets; use separate Codex sessions/threads as runtime result containers |
| Internal agents | Hidden system workflow | Orchestrate, bind graph, design/review questions, analyze answers, evaluate, teach, plan, evolve | Bypass graph/reviewer/evidence gates |

## Skeleton Layers

| Layer | Files / Paths | Skeleton Boundary | Required Visible Contract |
|---|---|---|---|
| Child page shell | `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css` | One focused child page with explicit state enum and deterministic fixture renderer | loading, empty, active task, saving, upload error, all-submitted reviewing, review ready, blocked, load/save errors |
| Child API projection | `learning_system/server.py` | Child-safe DTO serializers and route handlers | handle/position only; no raw ids; no graph-shaped field names |
| Operator API projection | `learning_system/server.py` | Id-rich maintenance DTO serializers and route handlers | internal ids and audit evidence only on operator routes |
| Evidence ledger | `learning_system/db.py` | Schema constants/helpers and shared evidence usability predicate | `active + graded + valid answer_analysis + current active question` gate |
| Async review worker | `learning_system/server.py`, `learning_system/db.py` | Background job claim/process/retry/recover shell | durable job states and restart recovery |
| Model routing | `learning_system/model_router.py` | Provider/endpoint/JSON-mode adapter seam | GPT text default, Doubao vision default, DeepSeek/future provider compatibility through adapter only |
| Answer analysis | `learning_system/auto_review.py`, `learning_system/agent_contracts/answer_review.v1.json`, `learning_system/prompts/answer_review.v1.md` | Structured answer-analysis adapter and local guardrails | final answer, model/relation, steps, symbols/units, check/explanation, process gap |
| Internal agent chain | `learning_system/internal_agents.py`, `learning_system/orchestrator.py`, `learning_system/agent_contracts/*.json`, `learning_system/prompts/*.md` | Nine-agent workflow boundaries and prompt/schema metadata | orchestrator, graph, question designer, question reviewer, answer analysis, evaluation, teaching, planner, self-evolution |
| Planner/evaluation | `learning_system/planner.py`, `learning_system/orchestrator.py`, `learning_system/flow_nodes.py` | Evidence-driven next-plan shell | 10-task group, prerequisite rollback, no pending evidence |
| Evolution | `learning_system/evolution.py` | Evidence-driven no_action/state/evolved shell | self-evolution only from real active graded analyzed evidence |
| Question-spec migration seam | `learning_system/question_bank.py`, planned `data/question_specs/` | Loader interface/stub while Python gates stay authoritative | staged migration, parity tests, reviewer-record gate preserved |
| Reports | `learning_system/reports.py`, `scripts/generate_daily_report.py` | Evidence-labeled report sections | confirmed, pending, inferred, stale, blocked, missing |
| Codex query bridge | Operator API/report scripts | On-demand query path from Codex to stored DB/report evidence | no child UI; no new result-feedback thread/session; stale/unknown remains explicit |
| Tests and QA hooks | `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`, `scripts/*.py` | Contract test shells and deterministic scenario fixtures | API, DB, model, async, semantic, visual, report, evolution, migration-parity coverage |

## Child Page State Enum

The child page skeleton must expose these states as explicit constants, not scattered string checks:

| State | Meaning | Required UI Slots | Recovery |
|---|---|---|---|
| `loading` | Bootstrap or refresh in progress | title/status skeleton, progress placeholder | retry if load fails |
| `empty` | No active child group | child-safe no-task message | refresh/retry |
| `active_task` | Current unsubmitted task | progress, task label, display topic, prompt, answer textarea, photo tool, primary CTA | save, upload/remove, stuck prompt |
| `saving` | Submission request in progress | disabled primary CTA, draft visible, status live region | returns to active task on failure |
| `save_error` | Save failed without losing draft | child-safe error, retry CTA | retry save or refresh if stale |
| `upload_error` | Photo rejected or unreadable before save | child-safe upload error, reselect/remove | choose another image |
| `all_submitted_reviewing` | 10/10 saved, analysis pending | saved assurance, reviewing message, retry/status CTA | poll/retry/leave and return |
| `review_ready` | Closure has child-safe review and next action | all-question review list, coach/next-step, primary next CTA | retry next group start if needed |
| `blocked` | System cannot continue automatically right now | saved assurance, reason without backend internals, later/retry action | refresh later; Codex/operator can inspect outside child UI |
| `load_error` | Bootstrap failed | child-safe error and retry | retry load |

## Child DTO Skeleton

Child DTO names must be presentation-oriented:

```text
ChildBootstrapDTO
- schema_version
- today_plan
  - title
  - display_key?                 # optional opaque UI continuity text, never an internal plan id
  - tasks[]
    - position
    - kind_label
    - display_topic              # child-safe learning topic, not graph field name
    - estimated_minutes?
    - question
      - prompt
      - answer_format
    - support
      - essence_or_hint?
- learning_group
  - handle                       # current-learning-group only
  - state
  - submitted_task_positions[]
- completion?
  - closure_status
  - child_message
  - review_points[]
  - next_action?
```

Forbidden in child DTOs:

```text
node_id, node_name, graph, question_id, attempt_id, session_id,
plan_id, plan_key, model, provider, agent, rubric, OCR confidence,
queue/job internals, operator action text
```

Operator DTOs may expose ids and audit evidence, but only under operator routes.

## Backend State Skeleton

The backend skeleton must make these shared predicates and states visible:

| Predicate / State | Required Meaning | Consumers |
|---|---|---|
| `is_current_usable_attempt_evidence` | true only for active, graded, valid answer_analysis, current active question evidence | evaluation, planner, evolution, reports |
| `is_child_schedulable_question` | true only for graph-bound, current-version, reviewer-approved, active eligible question | planner, QA audit |
| `is_evolution_source_valid` | true only for real active graded analyzed evidence not invalidated/stale/fake, with valid non-cyclic evolved-source lineage | self-evolution |
| `background_job_state` | queued/running/succeeded/waiting/error with retry metadata | async worker, session close, report |
| `closure_status` | not_started/waiting_ai/blocked/evolving/planned/closed projection | child UI, operator API, report |
| `report_claim_label` | confirmed/pending/inferred/stale/blocked/missing | parent Codex report |
| `runtime_result_storage` | every generated answer-analysis, evaluation, teaching, planning, evolution, and report result is stored in SQLite/report artifacts before Codex summarizes it | Codex query/operator workflow |

## Question-Spec Skeleton

The next code skeleton should add a seam, not a full migration:

```text
data/question_specs/
- math_question_standards_v1.md       # human-readable quality standard and forbidden patterns
- question_families_v1.json           # machine-readable family/spec shell
- seed_problem_calibration_v1.jsonl   # original seed/calibration examples, not copied private content
```

Required boundary:

- Python quality gates remain authoritative until parity tests pass.
- Reviewer records remain required for active use.
- User photo samples calibrate difficulty only and must not be copied.
- A future loader must prove it preserves age floor, reasoning demand, forbidden-pattern rejection, graph binding, expected answer/rubric presence, and old-attempt compatibility.

## Validation Classification

Read-only inspection:

```bash
jq empty data/knowledge_graphs/math/math_knowledge_graph_v2.json
jq '.nodes | length' data/knowledge_graphs/math/math_knowledge_graph_v2.json
python3 scripts/audit_question_bank_grade_level.py --db data/local_learning_system.sqlite
```

Test-environment mutating validation:

```bash
python3 scripts/init_learning_system_db.py
python3 scripts/generate_daily_report.py --db data/local_learning_system.sqlite
python3 -m unittest tests/test_learning_system.py -v
/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs
```

Service/manual validation:

```bash
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
```

Mutating commands require explicit test scope or backup when real learning evidence exists.

## Required Later SKELETON_PASS Evidence

When 听云 creates the code skeleton, the `SKELETON_PASS` must show:

- Page prototype / route shells for every child state.
- Child API projection helpers with forbidden-field scans.
- Operator API projection helpers separated from child routes.
- Shared evidence usability predicate and consumer list.
- Background worker claim/process/retry/recover shell.
- Model route status helper with no secrets.
- Answer-analysis schema/pending guard shell.
- Orchestrator state-machine transition shell.
- Planner/evolution/report seams that consume shared evidence predicates.
- Codex-facing result summaries are query views over DB/report artifacts, not separate user-visible Codex sessions.
- Question-spec loader seam with Python gate still authoritative.
- Test hooks/fixtures for API, DB, semantic, async, visual, report, evolution, and migration parity cases.

## Required TEST_CASE_SPEC Scope

观止 should design tests for these classes now, with exact file/symbol targets refined after code `SKELETON_PASS`:

- Method/unit cases for shared evidence predicates, child DTO projection, model-router fallback, answer-analysis normalization, background job state, session close, planner, evolution, report labels.
- API/service contract cases for child bootstrap, child submission, child complete, attachment fetch, operator bootstrap, operator close, manual grade/backfill, invalidation, evolution, plan generation.
- UI/flow cases for all child states and save/advance behavior.
- Visual/interaction regression cases for desktop/mobile, text overflow, photo preview, focus order, live regions, disabled states, and no internal leakage.
- State/async/recovery cases for 10/10 reviewing, pending model, model disabled, retry, restart recovery, duplicate submit, concurrent close.
- Data/artifact cases for graph integrity, question active-use gate, 20 slots/node, node-local mainline floor, controlled picture-level caps, 10-task round, invalidated/source-attempt evidence exclusion, report labels, question-spec loader parity.
- Semantic/model-risk cases for answer-only, right answer wrong reasoning, alternative valid method, blank/stuck, readable photo, unclear photo, low-confidence model, malformed model JSON.
- Scenario/e2e cases for diagnostic/remediation round, new-knowledge round, all-wrong round, correct-only round, weak evidence -> rollback/retest, self-evolution no_action/evolved paths.

## Stop Condition

This project skeleton definition is ready when 观止 can write a `TEST_CASE_SPEC` without inventing product users, UX states, API surfaces, data meanings, async boundaries, model routing policy, or evidence gates.

Status:
Ready for 观止 `TEST_CASE_SPEC` draft from approved project skeleton definition. Final executable `TEST_CASE_SPEC` must be refined after 听云 produces an actual code `SKELETON_PASS`.
