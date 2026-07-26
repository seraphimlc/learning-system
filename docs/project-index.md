# Project Runtime Index

Status: route map, not source of truth
Updated: 2026-07-11

Use this file to route investigation. Do not treat it as proof. Verify facts in code, commands, APIs, DB read-only evidence, pages, artifacts, or explicit user decisions.

## Read Contract

Before broad code search, read this file and then the smallest relevant `docs/domain-index/*.md`.

If this file is stale, update it only for the routes affected by the current task.

## Domain Map

| Domain | Domain index | Main roots | Validation |
|---|---|---|---|
| Math learning system | `docs/domain-index/math-learning.md` | `learning_system/`, `app/local_learning_system/`, `data/knowledge_graphs/math/`, `data/knowledge_cards/`, `docs/product/ai_native_math_learning_prd_v5.md`, `docs/architecture/daily_learning_runtime_contract_v1.md` | targeted unit tests plus browser smoke when server is running |
| Codex admin module / content management | `docs/product/admin_console_prd_v1.md`, `docs/architecture/codex_admin_module_technical_plan_v1.md` | `data/knowledge_graphs/math/`, `data/question_banks/v18/`, `data/knowledge_cards/`, `docs/design/specs/2026-07-23-question-bank-production-spec-v18.1.md` | v18 admin/gate tests |

## Main Entrypoints

Fill with stable routes only:

- Backend: `learning_system/server.py`, `learning_system/db.py`
- Frontend: `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`
- Workers/tasks: `learning_system/auto_review.py`, `learning_system/orchestrator.py`, `learning_system/model_router.py`, `learning_system/job_queue.py`
- Teaching agents: `learning_system/internal_agents.py`, `learning_system/prompts/`, `learning_system/agent_contracts/`
- v5 runtime/gates: `learning_system/daily_runtime.py`, `learning_system/graph_runtime.py`, `learning_system/evidence_gate.py`
- Planning/question bank: `learning_system/planner.py`, `learning_system/question_bank.py`
- Data/migrations: `scripts/init_learning_system_db.py`, `data/local_learning_system.sqlite`
- Reports: `learning_system/reports.py`, generated from current SQLite evidence when needed
- Tests: `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`
- Product baseline: `docs/product/ai_native_math_learning_prd_v5.md`
- Product amendment: `docs/product/ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md`
- Codex admin module product baseline: `docs/product/admin_console_prd_v1.md`
- Codex admin module technical baseline: `docs/architecture/codex_admin_module_technical_plan_v1.md`
- Product structure: `docs/product/ai_native_math_learning_product_structure_v5.md`
- Runtime contract: `docs/architecture/daily_learning_runtime_contract_v1.md`
- Technical plan: `docs/architecture/technical_plan_v5.md`
- Implementation blueprint: `docs/architecture/implementation_blueprint_v5.md`
- v18 question-bank production: `docs/design/specs/2026-07-23-question-bank-production-spec-v18.1.md`

## Validation Entrypoints

Fill with commands that agents may run locally:

```bash
python3 -m unittest tests/test_learning_system.py tests/test_knowledge_views_v51.py -v
python3 -m unittest tests/test_question_bank_v18_activation_gate.py tests/test_admin_console_inventory.py tests/test_admin_console_production_loop.py tests/test_question_bank_v18_blueprints.py tests/test_admin_full_bank_runner_priority.py -v
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
```

## Hard Boundaries

Agents must not:

- overwrite real product data, manual categories, true ASINs, generated assets, exports, or templates unless the task explicitly requires it
- run irreversible external-platform actions without explicit authorization
- use this index as a substitute for code or runtime evidence

## Maintenance Contract

Update this index when adding or changing:

- major page or route
- API endpoint
- task/worker type
- state machine
- DB table or important field contract
- export/import path
- external integration
- primary validation command
- generated artifact location

Keep entries short and path-oriented.
