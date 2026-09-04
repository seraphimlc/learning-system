# Domain Index: Math Learning System

## Scope

This domain covers the private AI-native math learning loop for one incoming Grade 7 student: knowledge graph, diagnosis, teaching design, question generation, error rollback, and dynamic planning.

It excludes generic multi-user product features, unrelated English expansion, and any claim to private textbook or commercial question-bank data.

## Current Contract

- Project purpose:小学关键漏洞补齐 + 人教版七年级上册数学预学.
- Current local system: v5.1 runnable SQLite + stdlib HTTP server + vanilla child UI.
- Every diagnosis, lesson, question, attempt, and plan item must bind to a knowledge graph node id.
- Wrong answers roll back along prerequisite chains before generating more same-type practice.
- Child-facing pages stay simple and child-only; complex teaching logic stays in
  Codex/API surfaces and internal docs.
- Questions should be few and diagnostic, not a drill bank.
- Active graph-generated/evolved questions must pass the built-in two-agent
  production gate: `question_designer_agent` creates graph-bound diagnostic
  candidates, and `question_reviewer_agent` rejects low-age mechanical drills,
  answer-only prompts, child-facing generator/meta language, and items without
  process evidence. Calculation weakness is treated through structure, rule
  explanation, wrong-method diagnosis, unit checks, or transfer variants.
- Practice-bank releases are versioned. When older question rows remain because
  attempts reference them, the planner must select the newest `item_version`
  through `db.find_question_for_node` rather than direct row reads.
- Reference answers are rubric context only; child answers must be judged by an
  AI evaluator or left pending for system AI/API processing.
- Evaluation must use process evidence, not final answer matching. A right final
  answer with missing or invalid reasoning is not mastery and should be partial
  or wrong depending on the model/step evidence.
- Processed attempts should carry `answer_analysis` from
  `answer_analysis_agent`: optimal answer, solution steps, child-answer summary,
  comparison against valid approaches, process gap, detailed explanation, and
  next child prompt. Missing structured analysis keeps AI output from being
  treated as complete.
- Child submissions with photos or low confidence stay as pending evidence;
  system/API processing promotes them to processed evidence.
- Current product baseline is clean-slate PRD v5: one child Web surface, parent
  interaction through Codex only, and a deterministic loop: select step ->
  answer -> AI judge -> teach/repair -> select next step -> summary.
- Historical PRDs v2/v3/v4 are not current product sources for v5 planning.
- The daily review budget is normally 10-20 questions/interactions, selected
  step by step from untested, unpassed, weak-confirmation, prerequisite, or
  new-learning graph nodes. Mastered nodes are skipped unless spaced
  confirmation is due.
- Child-facing APIs should use current-step handles/positions; question ids,
  attempt ids, session ids, graph ids, model/provider status, rubrics, and
  internal workflow states stay on Codex/operator surfaces.
- Mistakenly recorded evidence must be marked `invalidated`, not silently reused:
  invalidated attempts remain auditable but cannot drive reports, evolution, or
  plans. Evolved questions whose source evidence is invalidated are also
  rejected by the active scheduling gate.
- Self-evolution is paused as an automatic mainline changer. It may archive
  evidence and propose improvements, but cannot directly change active bank,
  graph, mastery, or next plan.

## Key Entrypoints

- Blueprint: `docs/00_PROJECT_BLUEPRINT.md`
- Math graph data: `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- Math graph notes: `data/knowledge_graphs/math/math_knowledge_graph_v2.md`
- Math knowledge view config: `data/knowledge_graphs/math/math_knowledge_views_v5_1.json`
- Knowledge cards: `data/knowledge_cards/`
- Question production assets are currently empty; the replacement v20 slot system is defined in `.agents/superpowers/specs/2026-08-14-independent-slot-question-production.md`.
- Local learning system backend: `learning_system/db.py`, `learning_system/question_bank.py`, `learning_system/evolution.py`, `learning_system/planner.py`, `learning_system/agents.py`, `learning_system/server.py`
- v5 daily runtime: `learning_system/daily_runtime.py`, `learning_system/graph_runtime.py`, `learning_system/evidence_gate.py`, `learning_system/job_queue.py`
- Local learning system UI: `app/local_learning_system/index.html`, `app/local_learning_system/styles.css`, `app/local_learning_system/app.js`
- Local learning system DB initializer: `scripts/init_learning_system_db.py`
- Local report generation: `learning_system/reports.py`
- Local learning system runbook: `docs/system/local_learning_system.md`
- Local DB: `data/local_learning_system.sqlite`
- Upload evidence: `data/uploads/answers/`; upload recovery lives in
  `learning_system/daily_runtime.py` `reconcile_answer_uploads()`
- Parent interaction surface: Codex. Do not add a web parent dashboard unless the
  product boundary is explicitly changed.

## Key Flows

- Knowledge graph -> learner node state -> daily adaptive targets -> current
  step selection.
- Current step -> child response -> answer analysis / teaching check -> node
  evaluation -> planner next-step decision -> next step or daily summary.
- Processed attempt -> node status reducer -> weak evidence creates evolved retest
  question; correct-only evidence can update mastery without creating a question.
- Built-in graph/evaluation/answer-analysis/session-closure reports -> graph
  coverage/reference audit, internal stage/action recommendations, and
  answer-reasoning coverage.
- Error diagnosis -> prerequisite rollback or progression -> next task generation.
- Real learning data -> graph/question/plan/agent iteration when current structure is too coarse or wrong.
- Weak real evidence ->命题 Agent candidate ->审题 Agent gate -> approved evolved
  question or status-only update when the candidate is rejected.

## Related Docs

- `AGENTS.md`
- `docs/00_PROJECT_BLUEPRINT.md`
- `docs/collaboration.md`
- `docs/product/ai_native_math_learning_prd_v5.md`
- `docs/product/ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md`
- `docs/product/ai_native_math_learning_product_structure_v5.md`
- `docs/architecture/daily_learning_runtime_contract_v1.md`
- `docs/architecture/technical_plan_v5.md`
- `docs/architecture/implementation_blueprint_v5.md`
- `docs/architecture/answer_assessment_engineering_contract_v5_1.md`
- `docs/project-rules/question-production-cleanup-manifest.md`

## Validation Entrypoints

```bash
jq empty data/knowledge_graphs/math/math_knowledge_graph_v2.json
jq '.nodes | length' data/knowledge_graphs/math/math_knowledge_graph_v2.json
python3 scripts/init_learning_system_db.py
python3 -m unittest tests/test_learning_system.py tests/test_knowledge_views_v51.py -v
python3 -m unittest tests/test_learning_system.py tests/test_knowledge_views_v51.py -v
/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
```

For generated student pages, validate with browser screenshots and human review before treating visual/taste decisions as final.

## Search Hints

- Graph node fields: `id`, `prerequisites`, `unlocks`, `diagnosis_contract`, `teaching_contract`, `question_generation`, `error_diagnosis`
- Core documents: `00_PROJECT_BLUEPRINT`, `math_knowledge_graph_v2`
- Key modes: `core`, `selective_core`, `controlled_extension`, `diagnose_only`
- Error tags: `calculation_or_symbol`, `concept_confusion`, `modeling_or_reading`, `process_habit`, `visual_spatial`
- Question production keys: `quality.review_status`, `design_intent`,
  `cognitive_level`, `age_floor`, `requires_reasoning`,
  `source.production_pipeline`, `question_designer_agent`,
  `question_reviewer_agent`
- Current/legacy API routes to inspect while migrating toward v3 current-step
  flow: `/api/bootstrap`, `/api/child-bootstrap`, `/api/learning-sessions`,
  `/api/learning-sessions/current-learning-group/complete`,
  `/api/operator/learning-sessions`, `/api/operator/learning-sessions/{id}/complete`,
  `/api/child-submissions`, `/api/operator/child-submissions`, `/api/attempts`,
  `/api/attempts/{id}/grade`, `/api/attempts/{id}/analysis`,
  `/api/attempts/{id}/invalidate`, `/api/evolve`, `/api/agent-reports`,
  `/api/attachments/{id}`
- v3 skeleton API routes: `/api/child-bootstrap` with
  `V3_DAILY_RUNTIME_ENABLED=1`, `/api/daily-flow/review/start`,
  `/api/current-step/submit`, `/api/operator/daily-flow/today`
- DB statuses: `pending_review`, `graded`, `submitted`, `correct`, `partial`, `wrong`,
  `A`, `B`, `C`, `D`, `state_updated`, `evolved`, `no_action`
- v3 DB tables: `daily_flows`, `flow_steps`, `review_targets`,
  `evidence_validations`, `next_step_decisions`,
  `late_evidence_reconciliations`, `daily_summaries`

## Maintenance Rules

Update this index when adding a student page, parent Codex workflow, generated diagnostic set, data schema, validation command, local API, self-evolution contract, or new stable domain document.
