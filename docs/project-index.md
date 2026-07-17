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
| Math learning system | `docs/domain-index/math-learning.md` | `learning_system/`, `app/local_learning_system/`, `data/knowledge_graphs/math/`, `data/questions/`, `docs/product/ai_native_math_learning_prd_v5.md`, `docs/architecture/daily_learning_runtime_contract_v1.md` | `python3 -m unittest tests/test_learning_system.py -v`; browser smoke when server is running |

## Main Entrypoints

Fill with stable routes only:

- Backend: `learning_system/server.py`, `learning_system/db.py`
- Frontend: `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`
- Workers/tasks: `learning_system/auto_review.py`, `learning_system/orchestrator.py`, `learning_system/model_router.py`, `learning_system/job_queue.py`
- Teaching agents: `learning_system/internal_agents.py`, `learning_system/prompts/`, `learning_system/agent_contracts/`
- v3 runtime/gates: `learning_system/daily_runtime.py`, `learning_system/graph_runtime.py`, `learning_system/evidence_gate.py`
- Planning/question bank: `learning_system/planner.py`, `learning_system/question_bank.py`
- Data/migrations: `scripts/init_learning_system_db.py`, `data/local_learning_system.sqlite`
- Reports: `scripts/generate_daily_report.py`, `docs/system/daily_reports/latest.md`
- Tests: `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`
- Product baseline: `docs/product/ai_native_math_learning_prd_v5.md`
- Product review: `docs/collaboration/reviews/prd_v5_clean_slate_review_2026-07-11.md`
- Historical product docs: `docs/product/ai_native_math_learning_prd_v2.md`,
  `docs/product/ai_native_math_learning_prd_v3.md`,
  `docs/product/ai_native_math_learning_prd_v4.md`,
  `docs/product/ai_native_math_learning_product_structure_v4.md`
- Architecture baseline: `docs/architecture/ai_native_learning_system_architecture_v3.md`
- Runtime contract: `docs/architecture/daily_learning_runtime_contract_v1.md`
- Technical plan v3: `docs/architecture/technical_plan_v3.md`
- Code skeleton pass v3: `docs/architecture/code_skeleton_pass_v3.md`
- Technical plan v3 reviews:
  `docs/collaboration/reviews/2026-07-10-jinghua-technical-plan-v3-rereview.md`,
  `docs/collaboration/reviews/2026-07-10-guanzhi-technical-plan-v3-qa-rereview.md`

## Validation Entrypoints

Fill with commands that agents may run locally:

```bash
python3 -m unittest tests/test_learning_system.py -v
python3 - <<'PY'
import re, subprocess, sys
from pathlib import Path
text = Path("tests/test_learning_system.py").read_text()
names = [
    "tests.test_learning_system.LearningSystemTest." + name
    for name in re.findall(r"def (test_v3_[^(]+)\(", text)
]
raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", *names, "-v"]))
PY
python3 scripts/generate_daily_report.py --db data/local_learning_system.sqlite
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
