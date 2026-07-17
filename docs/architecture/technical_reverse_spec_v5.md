### TECHNICAL_REVERSE_SPEC - 听云（agentKey: `tingyun`）- 2026-07-11 10:26 CST

Objective:
Reconstruct the current technical architecture that must be considered before v5 planning. This document describes current code/runtime facts only; desired v5 changes are listed under risks/recommendations.

Scope:
`learning_system/`, `app/local_learning_system/`, `tests/`, PRD v5, Product Structure v5, UX Flow v5, project/collaboration boundary files, and current graph/domain indexes.

Project boundary overlay:
- Single-child local math learning system; parent uses Codex only; child uses one Web page.
- Every teaching, diagnosis, question, answer analysis, evaluation, plan, and report must bind to graph nodes.
- Runtime must own authoritative transitions; internal agents/model routes may suggest or analyze but must not directly mutate authoritative state.
- No fixed worksheet for v5, no parent dashboard, no fake grading, no external content import, no automatic active self-evolution mutation.
- Existing real learning data must be preserved unless explicitly authorized otherwise.

Sources:
- Product: `docs/product/ai_native_math_learning_prd_v5.md`, `docs/product/ai_native_math_learning_product_structure_v5.md`, `docs/product/child_ux_flow_spec_v5.md`
- Project/collaboration: `AGENTS.md`, `docs/collaboration.md`, `docs/collaboration/roles/tingyun.md`, `docs/collaboration/playbooks/engineering-execution.md`, `docs/project-index.md`, `docs/domain-index/math-learning.md`, `docs/collaboration/inbox.md`
- Runtime code: `learning_system/*.py`, `learning_system/agent_contracts/*.json`, `learning_system/prompts/*.md`
- Child UI: `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`
- Tests: `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`

Evidence policy:
- Clean-slate v5 product meaning comes only from PRD v5 and Product Structure v5; child-visible workflow/copy/state constraints come from UX Flow v5.
- Historical PRDs/product structures/technical plans/reviews were not used as v5 product or architecture authority.
- Current architecture facts are accepted only from current code/tests/docs listed above.
- `git status --short` could not be used because the current workspace directory is not a git repository.

System map:
| Layer | Entrypoints | Responsibility | Key dependencies | Evidence tag | Evidence |
|---|---|---|---|---|---|
| Product source | PRD v5, Product Structure v5, UX Flow v5 | Defines v5 target loop, state/data vocabulary, no-fixed-worksheet boundary, child-visible states, acceptance paths | 若命/清秋 product docs | product_source | PRD v5 says PRD alone is not enough and requires Product Structure/UX/code recon before technical plan: `docs/product/ai_native_math_learning_prd_v5.md:17`, `docs/product/ai_native_math_learning_prd_v5.md:648`; Product Structure v5 defines modules/states/data and downstream artifacts: `docs/product/ai_native_math_learning_product_structure_v5.md:63`, `docs/product/ai_native_math_learning_product_structure_v5.md:266`; UX Flow v5 is ready for technical planning: `docs/product/child_ux_flow_spec_v5.md:3`, `docs/product/child_ux_flow_spec_v5.md:407` |
| HTTP backend | `learning_system/server.py` | stdlib threaded local HTTP server for child, operator, attachments, legacy sessions, v3 daily runtime routes | `db`, `planner`, `daily_runtime`, `auto_review`, `orchestrator`, `agents` | current_code | Main handler/routes at `learning_system/server.py:821`, `learning_system/server.py:854`, `learning_system/server.py:888`; child/legacy/v3 schemas at `learning_system/server.py:36` |
| v5 daily runtime workline | `learning_system/daily_runtime.py` | Daily flow creation, first review step selection, current-step submission, child-safe projection, photo handling, one-job background reducer for answer analysis -> evidence validation -> evaluation update -> planner decision/summary | SQLite schema, question bank, job queue, graph runtime, model router, evidence gate | current_code | Runtime class and constants at `learning_system/daily_runtime.py:20`, `learning_system/daily_runtime.py:116`; submit path saves attempt and enqueues `answer_analysis` at `learning_system/daily_runtime.py:239`, `learning_system/daily_runtime.py:338`; background runner at `learning_system/daily_runtime.py:394`; answer-analysis handler and reducer calls at `learning_system/daily_runtime.py:598`, `learning_system/daily_runtime.py:674`, `learning_system/daily_runtime.py:684`, `learning_system/daily_runtime.py:689`; evaluation/decision/summary helpers at `learning_system/daily_runtime.py:1221`, `learning_system/daily_runtime.py:1358`, `learning_system/daily_runtime.py:1549`, `learning_system/daily_runtime.py:1693` |
| Legacy child learning group runtime | `learning_system/server.py`, `learning_system/planner.py`, `learning_system/orchestrator.py` | Existing runnable fixed-round learning group flow with session close, background review, next plan, evolution/reports | generated plans, learning sessions, attempts, background jobs, auto review | current_code | Legacy fixed group APIs at `learning_system/server.py:930`, `learning_system/server.py:1066`, child submissions at `learning_system/server.py:1281`; planner round size is 10 at `learning_system/planner.py:12`; close pipeline at `learning_system/orchestrator.py:906` |
| Persistence | `learning_system/db.py` | SQLite schema, graph/question/session/attempt/job/daily-flow tables, validation helpers, lineage repair | local SQLite DB | current_code | Core tables at `learning_system/db.py:289`; attempts/attachments at `learning_system/db.py:358`; v3 daily tables at `learning_system/db.py:563`; v3 uniqueness/indexes at `learning_system/db.py:774`; attempt writes at `learning_system/db.py:3397` |
| Queue/async | `learning_system/job_queue.py`, legacy `background_jobs` helpers in `db.py`/`server.py` | SQLite-backed job enqueue/claim/lease/retry/recovery; legacy in-process background review threads | `background_jobs`, model router, auto review | current_code | v3 job types at `learning_system/job_queue.py:12`; enqueue lineage requirements at `learning_system/job_queue.py:45`; lease/recovery at `learning_system/job_queue.py:130`, `learning_system/job_queue.py:227`; legacy thread processor at `learning_system/server.py:1691` |
| Model adapter | `learning_system/model_router.py`, `learning_system/auto_review.py` | Resolves route/model/provider/env, calls Responses or Chat Completions, structured JSON fallback, photo OCR, answer review | environment API keys, model endpoints | current_code | Route registry at `learning_system/model_router.py:107`; route env resolution at `learning_system/model_router.py:179`; structured JSON adapter at `learning_system/model_router.py:305`; photo OCR threshold at `learning_system/auto_review.py:20`; answer review uses model route at `learning_system/auto_review.py:69` |
| Evidence gate | `learning_system/evidence_gate.py`, `db.EvidenceUsePolicy` | Fail-closed usability predicate, evidence validation rows, trust/report labels | attempts, flow_steps, question review records, graph/bank versions | current_code | Predicate checks status/analysis/provider/lineage at `learning_system/evidence_gate.py:44`; validation rows at `learning_system/evidence_gate.py:130`; label precedence at `learning_system/evidence_gate.py:270` |
| Graph runtime | `learning_system/graph_runtime.py`, graph data | Graph version, node lookup, prerequisite/rollback candidates, graph binding validation | graph_nodes table and graph JSON fallback | current_code | Graph runtime methods at `learning_system/graph_runtime.py:24`, prerequisite/rollback at `learning_system/graph_runtime.py:61`, `learning_system/graph_runtime.py:77` |
| Question bank | `learning_system/question_bank.py` | Versioned graph-bound question rows, quality gates, active-use review records, metadata-only candidate packet | graph, DB, question review records | current_code | Current bank version at `learning_system/question_bank.py:37`; candidate packet capped at 8 from 200-row scan at `learning_system/question_bank.py:167`; active-use quality gate at `learning_system/question_bank.py:1320` |
| Planning | `learning_system/planner.py` | Existing generated 10-task round planner with quality gates, rollback/retest/top-up behavior | learner status, question bank, evaluation signals | current_code | Fixed round constant at `learning_system/planner.py:12`; gates require 10 tasks at `learning_system/planner.py:650`; `generate_next_plan` creates fixed round at `learning_system/planner.py:1256` |
| Internal agents/contracts | `learning_system/internal_agents.py`, `learning_system/agent_contracts/`, `learning_system/prompts/` | Registry of hidden AI roles, prompt/contract loading, child-safe message validation | contract JSON, prompt markdown | current_code | Role registry at `learning_system/internal_agents.py:15`; planner role still says next 10-question group at `learning_system/internal_agents.py:58`; child-safe regex guard at `learning_system/internal_agents.py:178` |
| Reports | `learning_system/reports.py`, `scripts/generate_daily_report.py` | DB-derived Markdown reports and report claim labels | legacy sessions, agent reports, lineage audit | current_code | Report labels at `learning_system/reports.py:26`; report reads `learning_sessions` mode `child_learning_group` at `learning_system/reports.py:57`; markdown writer at `learning_system/reports.py:258` |
| Child UI | `app/local_learning_system/index.html`, `app/local_learning_system/app.js` | Vanilla child-only page, dual payload support for legacy v2 and v3 daily-flow states, photo/stuck/error panel UI | `/api/child-bootstrap`, `/api/child-submissions`, `/api/current-step/submit` | current_code | HTML child form at `app/local_learning_system/index.html:9`; UI states/forbidden keys at `app/local_learning_system/app.js:1`; v3 payload branch at `app/local_learning_system/app.js:279`; v3 current step render/submit at `app/local_learning_system/app.js:365`, `app/local_learning_system/app.js:988` |
| Tests | `tests/test_learning_system.py`, browser smoke | Unit/integration coverage for schema, child routes, queue/evidence gates, planner/report/model/photo/semantic cases, and browser smoke | unittest, stdlib server, Playwright | test_evidence | 216 unittest methods observed; v3 schema/route/submit/queue/gate tests start at `tests/test_learning_system.py:713`; photo/semantic tests at `tests/test_learning_system.py:9946`; browser smoke starts local server at `tests/browser_smoke_learning_system.mjs:51` |

Frontend routes/pages:
- Single page: `app/local_learning_system/index.html` served from `learning_system/server.py` static handler.
- The visible app has one child-mode `<main>` and one task panel; no parent dashboard DOM in current page (`app/local_learning_system/index.html:9`).
- `app.js` detects v3 payloads by schema version prefix `3.` and renders v3 states; otherwise it renders legacy v2 child learning group state (`app/local_learning_system/app.js:279`, `app/local_learning_system/app.js:326`).
- Legacy UI still has fixture mode with 10 tasks and review points for screenshot/state tests (`app/local_learning_system/app.js:69`).
- v3 UI currently maps `choose_review`, `current_step`, `teaching`, `analyzing`, `ready_for_new_knowledge`, `summary`, and `blocked` to shell states (`app/local_learning_system/app.js:330`).
- v3 current-step rendering supports prompt, hint, text/photo answer form, and stuck buttons (`app/local_learning_system/app.js:365`).

API / service interfaces:
| Interface | Method/route/symbol | Request/input | Response/output | Auth/permission | Consumers | Evidence tag |
|---|---|---|---|---|---|---|
| Operator bootstrap | `GET /api/bootstrap` | none | operator schema `1.4.0`, readiness, questions, reports, events | local/no auth | Codex/operator, tests | current_code: `learning_system/server.py:856`, `learning_system/server.py:427` |
| Child bootstrap dual route | `GET /api/child-bootstrap` | none | v3 daily-flow projection when `V3_DAILY_RUNTIME_ENABLED=1`; otherwise v2 child plan/group projection | local/no auth; child-safe projection | child page | current_code: `learning_system/server.py:860`, `learning_system/server.py:1647` |
| v3 start review | `POST /api/daily-flow/review/start` | `client_day_key` | v3 `current_step` or child-safe blocked payload | feature-flag gated | child page | current_code: `learning_system/server.py:891`; runtime at `learning_system/daily_runtime.py:204` |
| v3 submit current step | `POST /api/current-step/submit` | `step_handle`, `position`, `client_idempotency_key`, `answer_text`, optional photo, `stuck` | v3 analyzing/current child projection | feature-flag gated; no raw ids required beyond step handle | child page | current_code: `learning_system/server.py:906`; runtime at `learning_system/daily_runtime.py:238`; UI at `app/local_learning_system/app.js:988` |
| v3 operator inspect | `GET /api/operator/daily-flow/today` | none | internal daily flow/jobs/attempts/validations | operator/Codex route | Codex/operator | current_code: `learning_system/server.py:864`; runtime at `learning_system/daily_runtime.py:376` |
| Legacy create session | `POST /api/learning-sessions` | optional title | child handle plus current 10-task plan | child/operator depending route | legacy child UI | current_code: `learning_system/server.py:930` |
| Legacy child submission | `POST /api/child-submissions` | `session_handle`, `task_position`, answer text/photo | child-safe submitted/pending result | rejects raw ids on child path | legacy child UI | current_code: `learning_system/server.py:920`, `learning_system/server.py:1205`, `learning_system/server.py:1281` |
| Legacy session close | `POST /api/learning-sessions/current-learning-group/complete` | child handle | child-safe close projection, waiting/blocked/planned | child route maps handle to current session | legacy child UI | current_code: `learning_system/server.py:1066`, `learning_system/server.py:355` |
| Manual/operator attempt APIs | `/api/attempts`, `/api/attempts/{id}/grade`, `/api/attempts/{id}/analysis`, `/api/attempts/{id}/invalidate` | raw IDs and grading/analysis fields | raw attempt IDs, node IDs, analysis | operator-like; not child normal flow | tests/operator maintenance | current_code: `learning_system/server.py:1076`, `learning_system/server.py:1427`, `learning_system/server.py:1499` |
| Attachment serve | `GET /api/attachments/{id}` | attachment id | image bytes only after DB hash/size/content validation | local/no auth; ID-bearing route | child/operator image preview | current_code: `learning_system/server.py:2048` |
| Agent reports | `GET /api/agent-reports` | none | internal agent reports | operator/Codex | tests/operator | current_code: `learning_system/server.py:879` |

Data model / storage:
| Store/table/model | Important fields | Producers | Consumers | Migration/backfill | Evidence tag |
|---|---|---|---|---|---|
| `graph_nodes`, `graph_edges` | node id, prerequisites/unlocks, raw JSON | DB init/seed | graph runtime, question bank, planner | existing schema | current_code: `learning_system/db.py:298` |
| `question_items` | item version, source type, node id, prompt, rubric, solution, rollback candidates, source/raw JSON | seed/evolution/question bank | planner, daily runtime, answer analysis | active-use gates reject stale/invalid lineage | current_code: `learning_system/db.py:319`; quality gates at `learning_system/question_bank.py:1320` |
| `learning_sessions` | mode, plan id, expected question ids, status, closure status/result | legacy session creation, v3 daily flow creates legacy backing session | attempts, reports, orchestrator, v3 jobs | still required by attempt foreign key and legacy runtime | current_code: `learning_system/db.py:343`; v3 creates mode `daily_flow_v3` at `learning_system/daily_runtime.py:170` |
| `attempts` | session/question/node, result/grading/evidence status, answer raw, answer analysis, flow step id, graph/bank version, analysis status, idempotency key, answer source, attachment ids, review record id | legacy/v3 submissions, manual APIs, background review | evidence gate, planner, reports, evolution, summaries | additive v3 columns exist | current_code: `learning_system/db.py:358`; write helper at `learning_system/db.py:3397` |
| `attempt_attachments` | attempt id, kind, original filename, filename, content type, byte size, sha256, relative path | photo submissions | attachment serving, photo OCR, audit | v3 upload reconciler removes unreferenced files only in guarded real project case | current_code: `learning_system/db.py:392`; serve validation at `learning_system/server.py:2048` |
| `background_jobs` | job type, status, idempotency key, flow/step/attempt lineage, provider mode, lease/retry/dead-letter fields | legacy DB helpers and v3 `JobQueue` | in-process legacy background review, future v3 workers | v3 indexes enforce active idempotency | current_code: `learning_system/db.py:563`; queue adapter at `learning_system/job_queue.py:39` |
| `daily_flows` | child key/date, mode/status, current step id, graph/bank version, legacy session id, revision, summary id | v3 daily runtime | v3 child projection, operator inspect | unique active flow per child/day | current_code: `learning_system/db.py:603`; unique index at `learning_system/db.py:774` |
| `flow_steps` | step handle, position, type/status, node/question/review ids, prompt package, selection reason, attempt id, revision | v3 daily runtime | child projection, attempt lineage, evidence gate | unique current step per flow | current_code: `learning_system/db.py:625`; first step insertion at `learning_system/daily_runtime.py:495` |
| `evidence_validations` | attempt/analysis version, graph/bank, gate status, failed fields, predicate, provider mode | evidence gate | evaluation/planner/reports | unique attempt/version/gate row | current_code: `learning_system/db.py:670`; insert at `learning_system/evidence_gate.py:171` |
| `next_step_decisions` | action, target node, source evidence, candidate packet, provider/fallback/report labels | schema only in current v3 daily runtime path | intended planner/report consumers | not populated by current v3 skeleton | current_code: `learning_system/db.py:689` |
| `late_evidence_reconciliations` | late attempt, visible step, safe transition, reconciliation status | schema only | intended async recovery/report consumers | not populated by current v3 skeleton | current_code: `learning_system/db.py:720` |
| `daily_summaries` | flow revision, touched nodes, source steps/attempts/validations/decisions, child/operator summaries, labels | schema only; v3 summary method is stub | intended child summary/Codex report | not populated by current v3 skeleton | current_code: `learning_system/db.py:739`; summary stub at `learning_system/daily_runtime.py:373` |
| `agent_runs`, `session_steps`, `mastery_decisions`, `learner_node_status`, `evolution_events` | internal agent/run/audit state and node mastery/evolution state | legacy orchestrator/agents/evolution/evaluation | reports, planner, operator API | existing v2/v3 historical path remains active | current_code: `learning_system/db.py:453`, `learning_system/db.py:497`, `learning_system/db.py:508` |

Workers / async / queues:
- Legacy path: child submissions can enqueue `answer_review` jobs through `db.enqueue_background_job`, and `server.py` starts in-process background threads to process pending attempts and close sessions (`learning_system/server.py:1354`, `learning_system/server.py:1691`, `learning_system/server.py:1820`).
- v5 path: `daily_runtime.persist_child_response()` saves attempt/attachment and enqueues an `answer_analysis` job with full flow/step/attempt/graph/bank lineage (`learning_system/daily_runtime.py:338`). `process_next_background_job()` can claim one job and, for `answer_analysis`, currently runs the full deterministic reducer chain in-process: answer analysis, evidence validation, evaluation update, next-step decision, and summary/next-step materialization (`learning_system/daily_runtime.py:394`, `learning_system/daily_runtime.py:598`, `learning_system/daily_runtime.py:674`, `learning_system/daily_runtime.py:684`, `learning_system/daily_runtime.py:689`).
- v3 `JobQueue` supports idempotent enqueue, claim, heartbeat, retry, waiting, blocked, dead-letter, dependency gating, and lease recovery (`learning_system/job_queue.py:45`, `learning_system/job_queue.py:130`, `learning_system/job_queue.py:227`).
- Current submit projection immediately enters `analyzing`; a reducer method exists, but inspected server routes do not yet expose a v5 job-run route or start a v5 daily job worker loop (`learning_system/server.py:888`, `learning_system/server.py:906`; `rg process_next_background_job` found no `server.py` caller).

External integrations:
- Configured model API calls only; no cloud deployment/external account writes in current scope.
- Model calls use `urllib` against OpenAI-compatible `/responses` and `/chat/completions` endpoints (`learning_system/model_router.py:251`, `learning_system/model_router.py:278`).
- Answer-photo files are stored locally under `data/uploads/answers` by default and served only after DB metadata and file hash/size/content checks (`learning_system/server.py:25`, `learning_system/server.py:2048`).
- `.env.local` may be loaded for direct server starts without overriding existing environment variables (`learning_system/server.py:151`).

Model/provider usage:
- Default text model is `gpt-5.5`; default vision model is `doubao-seed-2-0-pro-260215` (`learning_system/model_router.py:13`).
- Routes exist for answer analysis, evaluation, planner, teaching, question designer, and answer-photo vision (`learning_system/model_router.py:107`).
- Route status hides provider/model/base URL when not enabled and does not expose API keys (`learning_system/model_router.py:79`).
- Structured JSON calls try endpoint/mode fallbacks: GPT-style routes default to `json_schema`, `json_object`, then `plain_json`; deepseek/doubao routes default to `json_object`, then `plain_json` (`learning_system/model_router.py:455`).
- `auto_review` treats photo OCR as untrusted evidence and blocks photo-only low-confidence OCR from becoming a completed review (`learning_system/auto_review.py:76`, `learning_system/auto_review.py:637`).

Configuration / deployment:
- Local stdlib HTTP server entry is `python3 -m learning_system.server --db ... --port ...`.
- Child UI is served from `app/local_learning_system`.
- `V3_DAILY_RUNTIME_ENABLED` controls whether child bootstrap/current-step routes use the v3 daily runtime path (`learning_system/daily_runtime.py:19`, `learning_system/server.py:1647`).
- Upload root can be configured when creating the server; v3 upload reconciliation is guarded to the real project DB/upload root only (`learning_system/server.py:2088`, `learning_system/server.py:2110`).
- The current workspace path does not appear to be a git repository, so git-based change evidence is unavailable.

Validation commands:
```bash
python3 -m unittest tests/test_learning_system.py -v
python3 - <<'PY'
import re, subprocess, sys
from pathlib import Path
text = Path("tests/test_learning_system.py").read_text()
names = [
    "tests.test_learning_system.LearningSystemTest." + name
    for name in re.findall(r"def (test_v3_[^(]+)\\(", text)
]
raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", *names, "-v"]))
PY
/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs
python3 scripts/generate_daily_report.py --db data/local_learning_system.sqlite
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
jq empty data/knowledge_graphs/math/math_knowledge_graph_v2.json
jq '.nodes | length' data/knowledge_graphs/math/math_knowledge_graph_v2.json
```

Test coverage:
- `tests/test_learning_system.py` contains 216 unittest methods in one main test class from AST inspection.
- v3 coverage includes additive schema/indexes, fail-closed contracts, child route shell, first current step from active question bank, forged review skip, no-question child-safe error, submit/idempotency/photo/stuck, completed projection, UI polling, feature flag fallback, queue lease/dependency, evidence gate lineage/stale/mock/pending labels, projection scrub, upload reconciliation (`tests/test_learning_system.py:713`, `tests/test_learning_system.py:908`, `tests/test_learning_system.py:1034`, `tests/test_learning_system.py:1276`, `tests/test_learning_system.py:1391`, `tests/test_learning_system.py:1644`).
- Legacy/v2 coverage includes planner quality gates, reports, model router, answer analysis, group completion, pending review recovery, photo OCR, semantic scenario matrix, and browser smoke (`tests/test_learning_system.py:6994`, `tests/test_learning_system.py:8353`, `tests/test_learning_system.py:9946`, `tests/test_learning_system.py:10150`).
- Browser smoke starts the server with model keys blank and validates v2 child-only flow, error panels, child-safe boundary, image upload checks, pending/analyzed/evolution behavior, and operator report presence (`tests/browser_smoke_learning_system.mjs:51`, `tests/browser_smoke_learning_system.mjs:180`, `tests/browser_smoke_learning_system.mjs:460`).
- Current tests prove v3 schema, submit, queue, and evidence-gate primitives, but do not yet prove the full v5 loop: queued `answer_analysis` worker -> evidence gate -> evaluation update -> teaching/next-step decision -> daily summary. No `tests/test_learning_system.py` test currently calls `process_next_background_job`.

Old-data compatibility:
- Current v3 daily flows create a backing `learning_sessions` row with mode `daily_flow_v3`, because `attempts.session_id` still requires a learning session (`learning_system/daily_runtime.py:170`, `learning_system/db.py:358`).
- Existing legacy `child_learning_group` sessions remain supported; v3 schema tests explicitly assert legacy session creation still works (`tests/test_learning_system.py:796`).
- `record_attempt()` prevents active attempts on non-schedulable questions or evolved questions based on invalidated evidence (`learning_system/db.py:3430`).
- `invalidate_attempt()` marks evidence invalidated and propagates invalidation to evolved source questions, then runs lineage repair (`learning_system/db.py:3677`).
- `reports.py` currently reports legacy `child_learning_group` sessions, not v3 `daily_flows` or `daily_summaries` as the primary source (`learning_system/reports.py:57`).

Stale or dead code:
- `learning_system/planner.py` is a fixed 10-task round planner; this conflicts with v5 step-by-step selection unless contained or replaced for v5 (`learning_system/planner.py:12`, `learning_system/planner.py:1256`).
- `learning_system/internal_agents.py` describes `planner_agent` as selecting the next 10-question group; this conflicts with v5 next-step planning semantics (`learning_system/internal_agents.py:58`).
- `teaching_generation` is not yet a complete product branch. Current reducer can add a `support_hint` before another question and can create `clarify_evidence`, but it does not materialize a distinct `teaching_repair`/`worked_example` step from a teaching package as Product Structure v5 requires (`docs/product/ai_native_math_learning_product_structure_v5.md:96`, `learning_system/daily_runtime.py:1451`, `learning_system/daily_runtime.py:1627`).
- `next_step_decisions` and `daily_summaries` now have writer helpers, but they need focused end-to-end tests and report integration before being treated as v5 truth (`learning_system/daily_runtime.py:1549`, `learning_system/daily_runtime.py:1693`; existing report code remains legacy-session oriented at `learning_system/reports.py:57`).
- `app/local_learning_system/app.js` still contains legacy fixture/fixed 10-task behavior and legacy submission/close paths (`app/local_learning_system/app.js:69`, `app/local_learning_system/app.js:924`).
- Manual/operator grading APIs still exist and may remain useful for maintenance, but PRD v5 excludes parent/manual grading as the normal child flow (`learning_system/server.py:1076`, `docs/product/ai_native_math_learning_prd_v5.md:90`).
- Self-evolution code remains present and can mutate/propose via legacy session-close/maintenance paths; PRD v5/Product Structure v5 pause active self-evolution mutation for the v5 mainline (`learning_system/evolution.py:1003`, `docs/product/ai_native_math_learning_product_structure_v5.md:29`).

Architecture risks:
- Dual runtime risk: `/api/child-bootstrap` and UI support both legacy v2 and v3 payloads; v5 must choose a migration/compatibility boundary rather than let both product models leak into the child loop.
- Async completion risk: v5 can enqueue `answer_analysis` and has an in-runtime reducer, but server startup/routing does not yet run that reducer, and the reducer is not covered by an end-to-end v5 test.
- Evidence trust risk: evidence gate is strong, but v3 attempts default to `analysis_status='missing'` and `provider_mode='not_configured'`; without worker contracts, all such evidence remains non-usable by design.
- Report truth risk: current report generator is DB-derived but legacy-session oriented; it does not yet produce v5 daily-flow summary/freshness records.
- UX implementation risk: `UX_FLOW_SPEC v5` exists and is ready for technical planning, but current child UI still carries legacy group/fixture behavior and state names that must be aligned to v5 visible states before rendered UX review.
- Model policy risk: route abstraction exists, but v5 live/recorded/mock policy, snapshot volume, timeouts, retry/fallback, and provider-specific QA acceptance still need contract decisions.
- Storage split risk: v3 DB has many needed facts, but PRD v5 explicitly leaves DB/log/model snapshot/Markdown report split to technical planning.
- Test false-pass risk: browser smoke currently proves legacy v2 child flow, not the v5 daily current-step async loop end to end.

Unknowns:
- Which initial graph nodes seed the first v5 review/new-knowledge path.
- First conservative mastery/evaluation thresholds.
- Exact v5 provider mode names and recorded/live fixture acceptance policy.
- Whether self-evolution code should be hard-disabled for v5 mainline or only prevented from mutating active graph/bank/mastery/plan.
- Whether v5 should preserve legacy routes as maintenance-only APIs or remove them from child-reachable paths.
- Whether the first implementation slice should keep the current single `answer_analysis` job reducer or split downstream phases into separately queued `evidence_validation`, `evaluation_update`, `teaching_generation`, and `planner_decision` jobs. The technical plan should decide this explicitly.

Recommended domain indexes:
- `docs/project-index.md`
- `docs/domain-index/math-learning.md`

Next action:
Run `ENGINEERING_SOURCE_READINESS` for v5 technical planning using PRD v5, Product Structure v5, UX Flow v5, this reverse spec, and current code reconnaissance. Current sources are sufficient for a scoped v5 runtime/job-chain technical plan, engineering contract, and implementation blueprint. Implementation still requires skeleton/review/test gates before business logic is claimed complete.
