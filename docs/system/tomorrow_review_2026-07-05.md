# Tomorrow Review: Local Math Learning System

Status: ready for parent-supervised local use  
Controller: 若命 (`ruoming`)  
Date: 2026-07-05  

## What Is Ready

- Single-child local math learning loop, not a generic education product.
- SQLite-backed evidence ledger at `data/local_learning_system.sqlite`.
- Child task page with one focused graph-bound task.
- Child can submit written steps, a short answer, a paper-answer photo, or a stuck-point note.
- Child support modes: `看一眼例子`, `我来试`, `卡住了`.
- Parent report shows progress, outcomes, and Codex discussion context; it is not a grading console.
- Pending child submissions do not affect mastery or agent profiles.
- System/Codex processed evidence drives node state, evolved retest questions, and the next plan.
- Attachment viewing is DB-gated and verifies recorded byte size, SHA-256, and image magic bytes before serving.
- Built-in `graph_agent` and `evaluation_agent` now produce local audit reports
  on graph integrity, question coverage, evidence hotspots, and the next Codex
  action. The parent page only surfaces the report and discussion context.

## Current Data State

| Item | Current Evidence |
|---|---:|
| Graph nodes | 56 |
| Graph edges | 225 |
| Graph-generated practice questions | 224 |
| Diagnostic questions | 48 |
| Evolved questions in current DB | 0 |
| Real attempts in current DB | 0 |
| Pending submissions in current DB | 0 |
| Built-in agent reports | `graph_agent`, `evaluation_agent` |

Pinned assets:

- Graph: `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
  - SHA-256: `1067b9c318efb116f6463fb7dd3db1a3888b440b6d33384c81313f79711a2971`
- Diagnostic: `data/questions/math_diagnostic_v1.json`
  - SHA-256: `3fd26716db45c11b23887806a6c7bac5a3ba318a2fe088e7220d17738171a525`

## Multi-Agent Gate Summary

All project roles were used through 若命 dispatch, with formal role boundaries:

| Role | Gate Result | Scope |
|---|---|---|
| 听云 (`tingyun`) | `DONE_CLAIMED` | Child-side scaffold implementation and smoke coverage |
| 镜花 (`jinghua`) | `CODE_REVIEW_PASS_WITH_SCOPE` | Engineering contracts, plan ordering, grading validation, attachment integrity |
| 观止 (`guanzhi`) | `QA_PASS_WITH_SCOPE` | Temp DB/server QA, real self-evolution path, pending-vs-processed behavior |
| 清秋 (`qingqiu`) | `UX_REVIEW_PASS_WITH_SCOPE` | Child/parent interaction, mobile layout, handoff clarity |
| 霜弦 (`shuangxian`) | `DATA_REVIEW_PASS_WITH_SCOPE` | Graph, diagnostic, question bank, runbook readiness |

Pass-with-scope means the local system passed the named scope. It does not claim real phone camera behavior, iOS/WeChat upload behavior, child taste, or formal textbook-aligned assessment release.

## Verification Run

Latest completion audit commands passed:

```bash
python3 -m unittest tests/test_learning_system.py -v
/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs
node scripts/validate_math_diagnostic_v1.mjs
node scripts/verify_math_diagnostic_page_export.mjs
jq empty data/knowledge_graphs/math/math_knowledge_graph_v2.json
jq empty data/questions/math_diagnostic_v1.json
python3 /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/validate_collaboration.py --project .
node --check app/local_learning_system/app.js
node --check tests/browser_smoke_learning_system.mjs
python3 -m py_compile learning_system/db.py learning_system/planner.py learning_system/server.py learning_system/evolution.py learning_system/question_bank.py
```

Key automated coverage:

- 28 Python tests passed.
- Browser smoke passed: child submission -> pending no-action evolution -> Codex/API evidence processing -> real evolved question -> refreshed plan -> built-in agent reports available.
- Visual smoke artifacts exist under `artifacts/visual-smoke/`.
- Current SQLite counts match the runbook and are clean for a first real session.

## How To Start Tomorrow

From the project root:

```bash
python3 scripts/init_learning_system_db.py
python3 -m learning_system.server --db data/local_learning_system.sqlite --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

Sanity check:

```bash
python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8765/api/bootstrap', timeout=5) as resp:
    data = json.load(resp)
print(data['schema_version'], data['readiness'], len(data.get('pending_attempts', [])))
PY
```

Expected:

```text
1.1.0 {'graph_nodes': 56, 'graph_edges': 225, 'diagnostic_questions': 48, 'practice_questions': 224, 'evolved_questions': 0, 'attempts': 0} 0
```

## Session Path

1. Child opens `孩子任务`.
2. Child chooses `我来试`, `看一眼例子`, or `卡住了`.
3. Child writes steps or uploads a paper-answer photo.
4. Child submits and continues; progress shows the answer has been saved.
5. Parent opens `家长报告` to see progress, outcomes, and Codex discussion material.
6. Codex processes pending photos/low-confidence evidence through the local API when needed.
7. Codex runs evolution after real processed evidence exists.
8. Review the report and Codex context before deciding the next task.

## Boundaries To Remember

- This is ready for tomorrow's supervised local use, not a public product.
- Diagnostic data remains `draft`.
- No private textbook, workbook, or commercial question-bank content is claimed.
- HEIC photos are intentionally unsupported; use PNG, JPG, or WebP.
- Real phone camera behavior and child comprehension still need human review.
- After a real session, back up `data/local_learning_system.sqlite` together with `data/uploads/answers/`.
