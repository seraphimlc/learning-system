# Local Learning System

Status: runnable local system v1.6 + durable background learning pipeline  
Updated: 2026-07-06

## Purpose

This is the local, single-child math learning loop for the summer bridge phase.

It is not a generic education product and has no account system. SQLite is used as a local evidence ledger and question-bank index.

## Run

```bash
python3 scripts/init_learning_system_db.py
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
```

For this local machine, put runtime model credentials in `.env.local`. The file
is intentionally gitignored and is loaded automatically by `python3 -m
learning_system.server` and by the 8765 helper scripts:

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.amux.xyb2b.com/v1
AI_EVALUATOR_MODEL=gpt-5.5
AI_QUESTION_MODEL=gpt-5.5
AI_VISION_MODEL=doubao-seed-2-0-pro-260215
AI_ANSWER_ANALYSIS_AGENT_VISION_OCR_API_KEY=...
AI_BACKGROUND_REVIEW_CONCURRENCY=4
AI_BACKGROUND_REVIEW_MAX_PASSES=3
```

Equivalent shell exports also work:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://api.amux.xyb2b.com/v1
export AI_EVALUATOR_MODEL=gpt-5.5  # answer_analysis_agent
export AI_QUESTION_MODEL=gpt-5.5  # question_designer_agent; omit to use the GPT default
export AI_VISION_MODEL=doubao-seed-2-0-pro-260215  # answer photo OCR/transcription
export AI_BACKGROUND_REVIEW_CONCURRENCY=4  # optional parallel answer-review workers, capped at 8
export AI_BACKGROUND_REVIEW_MAX_PASSES=3  # optional transient retry count
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
```

If `OPENAI_API_KEY` is absent, submissions are saved but remain pending for
system AI analysis; the system intentionally does not fall back to keyword
matching. Startup logs print whether each AI route is enabled, but never print
API key values.

Open:

```text
http://127.0.0.1:8765
```

Codex-side progress reports are generated from the current SQLite evidence when
needed. Report files are not treated as durable source data; stale or incomplete
lineage must be labeled as such instead of reused as proof.

## Data Contract

- Source graph: `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- Knowledge view config: `data/knowledge_graphs/math/math_knowledge_views_v5_1.json`
- Knowledge cards: `data/knowledge_cards/`
- v18 question-bank source assets: `data/question_banks/v18/`
- Local DB: `data/local_learning_system.sqlite`
- Current pinned graph hash:
  `1067b9c318efb116f6463fb7dd3db1a3888b440b6d33384c81313f79711a2971`
- Graph nodes seeded: 56
- Active question bank: only the currently released v18 bank is child-schedulable.
  `data/question_banks/v18/staged_candidates_v18.json` is a staging file and is
  not active until it passes the v18 activation gate.
- Child learning flow is adaptive. The page shows the current step or a small
  batch for the selected node; planning chooses the next step from graph-bound
  evidence instead of exposing a fixed worksheet.
- Question production contract: expert design board defines node coverage and
  item requirements, the generation agent creates candidates, expert review
  accepts or rejects them, and the staging gate prevents rejected or incomplete
  candidates from becoming schedulable.
- Model-backed question production: when weak analyzed evidence is available and
  `OPENAI_API_KEY` is configured, `question_designer_agent` asks the per-agent
  routed model for one graph-bound retest candidate using `AI_QUESTION_MODEL`
  (or the evaluator model). The model has candidate-only authority: it cannot mark its
  own question approved, write mastery state, or bypass the reviewer. The code
  normalizes the candidate, recomputes the review gate, records designer/reviewer
  agent runs with provider/model/alias metadata, and activates only approved
  questions. If the model times out, returns malformed JSON, has low confidence,
  references unknown graph nodes, includes prompt-injection wording, or produces
  a low-signal/mechanical item, the bad candidate is not inserted; the event
  records the rejection and a deterministic graph-bound fallback retest is
  generated so the session can still close.
- Model routing: `learning_system/model_router.py` is the single OpenAI-compatible
  route resolver. By default, answer analysis and question design use GPT
  (`gpt-5.5` unless overridden), and answer-photo transcription uses
  `AI_VISION_MODEL` with the Doubao model id. All routes can share
  `OPENAI_BASE_URL`; API keys remain environment variables and are never written
  to source or audit output. Structured model calls go through the compatibility
  adapter in `model_router.call_structured_json`: GPT/OpenAI routes try
  `json_schema` first, then compatible JSON fallbacks; optional DeepSeek and
  Doubao routes skip `json_schema` by default and try `json_object`, then plain
  JSON text if the gateway/model rejects `response_format`. The returned JSON is
  always parsed and validated locally before grading, OCR use, or question
  activation. For a new model, override the sequence with comma-separated
  `AI_JSON_MODE`, `AI_DEEPSEEK_JSON_MODE`, or route-specific variables such as
  `AI_QUESTION_DESIGNER_AGENT_QUESTION_CANDIDATE_JSON_MODE` using values
  `json_schema,json_object,plain_json`.
- Child API: `/api/child-bootstrap` is the only bootstrap endpoint used by the
  child page. It contains the current plan, child-safe question prompt/answer
  format, and minimal submission progress only. It exposes task `position`,
  task kind label, and a stable `current-learning-group` handle rather than
  internal question, attempt, or session ids. It intentionally excludes
  `agent_profiles`, `agent_reports`, `evolution_events`, graph audit data,
  reference answers, rubrics, solution steps, error tags, model details, and
  internal workflow metadata. Child session completion via
  `/api/learning-sessions/current-learning-group/complete` returns only
  child-safe closure status and child message. Full internal closure
  evidence is available to Codex/operator tooling through
  `/api/operator/learning-sessions/{id}/complete`. `/api/bootstrap` remains the
  Codex/operator API surface.
- Learning sessions: the child page submits answers with task position and the
  `current-learning-group` handle, so a group of answers is reviewed together
  instead of interrupting after every question. `/api/learning-sessions/.../complete` enters the
  Teaching Session Orchestrator facade: it checks whether the group is complete,
  whether AI review and answer analysis are ready, and returns immediately for
  the child. If pending answers remain, the server starts a background session
  processor: every child submission also creates a durable `background_jobs`
  row for answer review. The worker retries answer analysis when a model is
  configured, runs pending model reviews in parallel according to
  `AI_BACKGROUND_REVIEW_CONCURRENCY`, serializes database writes on the
  background session thread, grades valid responses, then calls the orchestrator
  again to trigger internal evolution and next-plan generation once the whole
  group is submitted. Transient evaluator failures are retried up to
  `AI_BACKGROUND_REVIEW_MAX_PASSES`; unrecoverable background exceptions are
  written back to the session closure result and `agent_runs` instead of being
  swallowed. If the server restarts, startup scans `background_jobs` and active
  pending attempts and resumes queued review work when a model is configured. If
  no model/API key is available, the session stays in `waiting_ai` with an
  auditable pending reason instead of falling back to fake grading.
- Internal agent chain: a completed analyzed child learning group now writes a
  full internal agent chain for the same `session_id`: `graph_agent` binds
  attempts/questions/nodes, `answer_analysis_agent` supplies structured answer
  evidence, `self_evolution_agent` updates evidence-driven rules/status,
  `question_designer_agent` and `question_reviewer_agent` create and gate evolved
  questions when weak evidence exists, `evaluation_agent` records node-level
  decisions, `planner_agent` records the next plan transition, `teaching_agent`
  records child-safe completion feedback, and `session_orchestrator_agent` closes
  the round. The close path also writes `agent_handoffs` and `session_steps` for
  graph binding, evaluation, planning, teaching handoff, and final closure.
- Codex/API maintenance paths also record agent evidence: manual grading and
  answer-analysis backfill write `answer_analysis_agent` runs, and
  `/api/plans/generate` writes a `planner_agent` run. These are operator
  maintenance hooks, not parent-facing UI workflows.
- Child submissions: `/api/child-submissions` records written answers and optional
  answer photos by task position and `current-learning-group` handle only; it
  rejects internal question/session ids. The child endpoint never waits for a
  model call: it stores the attempt as `pending_review`, returns immediately so
  the page can advance to the next task, and queues the session for background
  answer analysis. Codex/operator maintenance flows that need raw ids use
  `/api/operator/child-submissions`, which may still run synchronous review for
  controlled maintenance tests. Answer judgment is AI-first: the reference
  answer and solution steps are rubric context, not exact string-match truth.
  When `OPENAI_API_KEY` is configured, the background reviewer first sends a
  photo answer through the vision route as untrusted OCR/transcription evidence.
  The evaluator then receives the question, rubric, written answer, optional OCR
  transcript, and optional original answer image, and only grades when confidence
  is sufficient. If photo OCR is missing or low-confidence and there is no usable
  written answer, the evidence remains pending. A correct final answer is not
  enough for full credit: if the reasoning/model/check evidence is missing,
  circular, lucky, or conceptually wrong, the normalized result is at most
  `partial`.
- Answer analysis contract: successful AI/system grading stores
  `answer_analysis_json` on the attempt. The structure is produced by
  `answer_analysis_agent` and includes the optimal answer, recommended solution
  steps, child-answer summary, comparison against the optimal and alternate
  valid approaches, process gap, detailed explanation, and next child prompt.
  This is separate from `parent_note`; it is durable evidence for internal
  planning and parent-side Codex direction discussions. If the AI response lacks this structured
  analysis, the submission stays pending instead of being treated as graded.
  Without a configured AI evaluator, photo evidence, or low-confidence output,
  the submission stays pending (`pending_review` in the DB) for system AI/API
  processing and is not consumed by self-evolution. The child-facing response is
  sanitized and does not return `auto_review`, model/provider status, internal
  agent keys, graph node ids, rubrics, or operator notes.
- API evidence processing: `/api/attempts/{attempt_id}/grade` promotes one pending
  submission to processed evidence (`graded` in the DB) with result, rubric
  points, error tags, explanation level, and review note. Only this processed
  evidence can update node state or agent profiles. The endpoint is intentionally
  kept as an API operation for Codex-side maintenance when needed, not exposed
  as a parent-facing form or child interruption.
- API answer-analysis backfill: `/api/attempts/{attempt_id}/analysis`
  attaches a non-empty `answer_analysis` object to an already graded attempt
  without changing its result or score. This is for historical/legacy processed
  evidence that predates v1.3, and remains a Codex-side API operation rather than a
  parent-facing grading workflow.
- API evidence invalidation: `/api/attempts/{attempt_id}/invalidate`
  marks a mistakenly recorded attempt as `evidence_status=invalidated` with an
  evidence note. Invalidated attempts stay in the DB for audit, but are excluded
  from recent evidence, agent reports, future evolution, and plan generation.
  Evolved questions whose source evidence is invalidated are also rejected by
  the active question gate and cannot be scheduled.
- Attempt answer photo attachments: child submissions and API-created
  processed attempts accept optional `answer_photo_data_url` and
  `answer_photo_name`. The data URL must
  be `image/png`, `image/jpeg`, or `image/webp`, base64 encoded, magic-byte valid,
  and no more than 8 MB after decoding. Stored files live under
  `data/uploads/answers/`; DB metadata lives in `attempt_attachments` with original
  filename, stored filename, content type, byte size, SHA-256, source, and path.
- Attachment viewing uses `/api/attachments/{attachment_id}`. The server reads the
  DB row first, then serves only the matching local answer-photo file with
  `X-Content-Type-Options: nosniff`.

Every question, attempt, node state, plan task, and evolution event carries graph node evidence.

## Self-Evolution

Self-evolution is evidence-driven:

1. A system/API-processed attempt with non-empty `answer_analysis_json` is recorded.
2. Normal child learning groups enter self-evolution only through
   `/api/learning-sessions/{session_id}/complete`, which calls the orchestrator.
   `/api/evolve` remains a Codex/operator maintenance endpoint and now goes
   through `session_orchestrator_agent` audit before running the evolution reducer.
3. The learner node status is updated from processed evidence, including recovery
   evidence. One correct answer with good reasoning is strong evidence but remains
   `B`; repeated strong evidence is required before a node can become `A`.
4. For weak processed evidence, evolved retest questions are generated from the real
   node/error evidence. A model candidate is attempted first when configured, but
   deterministic fallback keeps the workflow moving if the model candidate is
   unavailable or rejected.
5. When weak evidence exists and the generated retest passes review, the built-in
   `self_evolution_agent` and `question_designer_agent` profile revisions increment
   with learned rules. If the reviewer rejects a candidate, the item is not
   inserted or scheduled; learner node status still updates from the real
   evidence.
6. Each evolution event writes an `evolution_audits` row that links evidence
   attempts, before/after state, created question ids, and question review record
   ids.
7. A new plan reads the changed DB state and prioritizes remediation, prerequisite
   probing, due retests, or the next unmastered core node. For a node with
   multiple approved evolved questions, the scheduler prefers the newest inserted
   approved evolved item, so a just-created evidence-driven retest is not hidden
   behind an older question id or lower variant label.

Without analyzed processed evidence, including when there are only pending child submissions or
answer photos, evolution records `no_action` and does not create questions or change
agent profiles. With processed correct-only evidence, evolution records `state_updated`.

## Built-In Agent Reports

The local backend exposes deterministic built-in agent reports through `/api/bootstrap`
and `/api/agent-reports`.

- `session_orchestrator_agent` reports the current learning-group boundary and
  close/idempotency state.
- `graph_agent` checks graph references, question rollback references, minimum
  practice coverage, diagnostic node coverage, and real processed weak-evidence
  hotspots. It recommends graph repair only from concrete broken references,
  thin coverage, or repeated processed weak evidence.
- `question_designer_agent` reports candidate-generation readiness and profile
  revision state.
- `question_reviewer_agent` reports durable review records and active eligibility
  gate health.
- `answer_analysis_agent` checks whether processed attempts carry structured
  answer analysis, and keeps the invariant that final-answer matching is not
  enough: the system must compare optimal solution, child reasoning, valid
  alternatives, process gaps, and next prompt.
- `evaluation_agent` checks whether the current session is at baseline, pending
  system review, missing answer analysis, ready to evolve, in prerequisite repair, or in remediation.
  It explicitly treats pending evidence as unprocessed and never as mastery.
- `teaching_agent` reports child-safe feedback invariants and analyzed evidence
  available for explanation.
- `planner_agent` reports next-plan task types and planning invariants.
- `self_evolution_agent` reports recent evolution events and audit availability.

`question_production_agent` and `session_closure_agent` remain as compatibility
aliases for older Codex maintenance checks, but the formal product-internal
agent surface is the nine-agent list above.

These reports are exposed for Codex through the local API. They are local audit
helpers, not separate model calls and not a task for the parent.

## Internal Teaching-Agent Contracts

The product runtime now defines nine hidden internal teaching agents:

- `session_orchestrator_agent`: controls the learning-round state machine; does not directly write questions or grade answers.
- `graph_agent`: binds questions, error evidence, and prerequisites to graph nodes; does not label vague "carelessness".
- `question_designer_agent`: creates graph-bound question candidates; does not create low-age mechanical drills.
- `question_reviewer_agent`: blocks weak, answer-only, or no-reasoning questions; does not pursue quantity.
- `answer_analysis_agent`: compares answer, reasoning, valid alternatives, and process gaps; does not string-match answers.
- `evaluation_agent`: proposes mastery/error dimensions; does not treat one correct answer as mastery.
- `teaching_agent`: creates child-safe explanations and next prompts; does not expose backend analysis.
- `planner_agent`: proposes consolidation, rollback, stretch, or next learning; does not follow a calendar mechanically.
- `self_evolution_agent`: proposes evidence-driven rule/profile/question evolution; does not fake evolution for tests.

Contract metadata lives in `learning_system/agent_contracts/`; model-facing prompt
templates live in `learning_system/prompts/`. These files are for the system and
models, not for the child page. The child page may render only child-safe fields
such as title, explanation, feedback, action, input hint, photo hint, retry
prompt, and pending message.

The current implementation has the contract layer, prompt templates, child-safe
validation, child/operator API separation, audit tables, seeded agent profiles,
review/evolution audit writes, and orchestrator-owned session close path. Some
agents still use deterministic or existing code paths until the next implementation
slice wires every model call through the shared runtime.

## Tomorrow Session Checklist

Before the child starts:

```bash
python3 scripts/init_learning_system_db.py
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
```

- If the port is occupied, use another port such as `8766`.
- Open `/api/bootstrap` once and confirm the current schema, 56 graph nodes, and
  no stale active learning group. Also open `/api/child-bootstrap` and confirm
  the child-facing state is either the knowledge home or a current v5.1 learning
  step. If a port returns an older schema, stop that stale local server or use a
  clean port before the child starts.
- Do not rerun seeding during the child session unless you intend to keep the DB
  clean and have not recorded real evidence yet.
- For real evidence, keep `data/local_learning_system.sqlite` and
  `data/uploads/answers/` together. Back them up together if you want to preserve
  a session.

Quick sanity check:

```bash
python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8765/api/bootstrap', timeout=5) as resp:
    data = json.load(resp)
print(data['schema_version'], data['readiness'])
with urllib.request.urlopen('http://127.0.0.1:8765/api/child-bootstrap', timeout=5) as resp:
    child = json.load(resp)
print(len(child['today_plan']['tasks']), child['learning_group']['state'])
PY
```

Backup after a real session:

```bash
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M%S)
cp data/local_learning_system.sqlite "backups/local_learning_system-$stamp.sqlite"
tar -czf "backups/answer-uploads-$stamp.tgz" data/uploads/answers 2>/dev/null || true
```

During the session:

1. Child opens the child task page.
2. Child writes steps or uploads a paper-answer photo.
3. Child submits and continues to the next task; the page shows saved progress.
4. After the group is complete, internal agents batch-check review status,
   answer analysis, error causes, evolution, and the next plan. This runs in the
   background when pending AI work remains; the child does not wait on the page.
5. Parent uses Codex to ask about progress, evidence, and system redesign; the
   child page does not expose a parent dashboard or manual grading console.
6. Pending-only submissions do not evolve. Only graded attempts with structured
   answer analysis can update node status, agent profiles, or evolved questions.

Manual checks not covered by automation:

- Real phone camera and browser behavior, especially iOS Safari/WeChat browser.
- HEIC images are not accepted in this version; use PNG/JPG/WebP.
- Photo clarity still needs Codex/vision or human inspection; the system only
  validates file type and size.
- Final visual/taste review still belongs to the parent/child during real use.
- Current automated visual smoke screenshots are under `artifacts/visual-smoke/`.

## Verification

```bash
python3 -m unittest tests/test_learning_system.py -v
python3 -m unittest tests/test_answer_assessment_v51.py tests/test_knowledge_views_v51.py -v
python3 -m unittest tests/test_question_bank_v18_activation_gate.py tests/test_admin_console_inventory.py tests/test_admin_console_production_loop.py tests/test_question_bank_v18_blueprints.py tests/test_admin_full_bank_runner_priority.py -v
/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs
jq empty data/knowledge_graphs/math/math_knowledge_graph_v2.json
jq empty data/knowledge_graphs/math/math_knowledge_views_v5_1.json
```

## Boundaries

- Do not import private textbook, workbook, or commercial question-bank content.
- Released diagnostic/question records should be append-only after real attempts.
- Superseded question rows that already have attempts should remain as historical
  evidence; active scheduling must go through version-aware lookup instead of
  directly picking an old row.
- Do not bypass the question reviewer gate. A question that is only arithmetic,
  only answer-format, child-facing meta text, or missing process evidence is not
  eligible for active scheduling even if it has a graph node.
- Do not infer A/B/C/D from unprocessed answer-only records.
- `D` requires explicit blocking evidence or verified prerequisite-chain failure.
- The child-facing view should stay simple and child-only; complex graph and
  agent evidence should stay in Codex/API surfaces rather than page operations.
- Review notes and all graph/question/user text are treated as untrusted at the UI
  boundary and must render as inert text.
