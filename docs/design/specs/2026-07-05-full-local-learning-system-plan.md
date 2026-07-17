# Full Local Learning System Implementation Plan

> **For agentic workers:** REQUIRED: Use `multi-agent-collaboration` with 若命 as controller. Use formal outputs from 听云, 镜花, 观止, 清秋, and 霜弦 as implementation, review, QA, UX, and data evidence. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tomorrow-usable local math learning system for one child, backed by a database, graph-bound question bank, daily learning flow, and evidence-driven agent self-evolution.

**Architecture:** Use Python stdlib HTTP server + SQLite to avoid external service risk. Seed the database from the existing math graph and diagnostic JSON. Keep the child UI simple and put graph/evolution complexity in the parent/Codex surfaces.

**Tech Stack:** Python 3 stdlib, SQLite, HTML/CSS/vanilla JS, existing JSON graph/diagnostic assets, unittest, browser smoke tests through system Chrome.

---

## File Structure

- `learning_system/db.py`: SQLite schema, migrations, seed orchestration, repository helpers.
- `learning_system/question_bank.py`: graph-bound question bank generation from graph contracts and diagnostic items.
- `learning_system/evolution.py`: evidence aggregation, node status updates, generated variants, agent profile revisions, audit events.
- `learning_system/planner.py`: next-session task selection using node status, graph prerequisites, and evolved agent rules.
- `learning_system/server.py`: local HTTP API and static file server.
- `app/local_learning_system/index.html`: parent/student app shell.
- `app/local_learning_system/styles.css`: quiet operational dashboard UI.
- `app/local_learning_system/app.js`: API client and interaction flow.
- `scripts/init_learning_system_db.py`: initialize/refresh `data/local_learning_system.sqlite`.
- `tests/test_learning_system.py`: unit/integration tests for seed, question bank, planning, and self-evolution.
- `tests/browser_smoke_learning_system.mjs`: browser-level smoke test for the local app.
- `docs/system/local_learning_system.md`: runbook and data contract.

## Task 1: Tests First

- [ ] Write a failing test proving DB seed creates all graph nodes and a usable question bank.
- [ ] Write a failing test proving every graph node has at least four non-diagnostic practice items.
- [ ] Write a failing test proving a weak attempt updates node status, creates an evolved question, increments an agent profile revision, and affects the next plan.
- [ ] Write a failing API smoke test for dashboard bootstrap and attempt/evolution endpoints.

## Task 2: Data Layer

- [ ] Create SQLite schema with tables for graph nodes, graph edges, question items, sessions, attempts, node status, agent profiles, evolution events, and generated plans.
- [ ] Seed graph nodes and edges from `math_knowledge_graph_v2.json`.
- [ ] Seed diagnostic items from `math_diagnostic_v1.json`.
- [ ] Seed practice items from generated graph-bound question templates.

## Task 3: Question Bank

- [ ] Generate at least four usable non-diagnostic items per graph node: essence check, standard example, variant, and transfer/retest.
- [ ] Preserve canonical error tags and rollback candidates from the graph.
- [ ] Mark all question sources as original graph-generated or evolved from evidence.
- [ ] Validate no item references unknown graph nodes or unknown error tags.

## Task 4: Self-Evolution

- [ ] Aggregate real attempts by node and error tag.
- [ ] Update node status only from graded evidence.
- [ ] Create evolved questions only when weak/unstable evidence exists.
- [ ] Update built-in agent profiles with revision and learned rule changes that future planning reads.
- [ ] Persist an audit event with before/after facts and evidence attempt ids.

## Task 5: Local App

- [ ] Build a dashboard showing readiness, graph coverage, question bank coverage, weak nodes, today plan, and evolution events.
- [ ] Build a student session view with one task at a time, answer capture, parent marking, and gentle language.
- [ ] Build parent tools for node/question browsing and evolution audit.
- [ ] Keep accessibility basics: visible labels, focus states, 44px controls, aria-live feedback, responsive layout.

## Task 6: Verification And Gates

- [ ] Run Python tests.
- [ ] Run DB initialization and summarize seeded counts.
- [ ] Run browser smoke test for dashboard, attempt submission, real evolution, and plan refresh.
- [ ] Dispatch formal review/QA agents and fix blockers.
- [ ] Start the local server and report the URL.
