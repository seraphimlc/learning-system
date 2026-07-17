# Internal Teaching Agents Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the product-internal teaching-agent boundary so the child-only learning loop has explicit agent contracts, prompt files, audit tables, child-safe message validation, and an orchestrator-owned session close path.

**Architecture:** Keep the current Python stdlib + SQLite + vanilla JS stack. Add a thin internal-agent contract layer first, then route existing session completion through a `TeachingSessionOrchestrator` facade while preserving current runnable behavior. Model-backed outputs remain advisory; schema/business validation and orchestrator reducers decide state changes.

**Tech Stack:** Python 3 stdlib, SQLite, JSON prompt-contract files, Markdown prompt templates, existing unittest/browser smoke tests.

---

## File Structure

- Create `learning_system/internal_agents.py`: product-internal agent role definitions, enums, transition table, child-safe message validation, prompt contract hashing/loading helpers.
- Create `learning_system/orchestrator.py`: teaching-session close facade, transition validation, mastery-decision audit insertion, agent-run/handoff audit helpers.
- Modify `learning_system/db.py`: add audit tables and helper insert/read functions; seed the exact internal agent profiles from the user table.
- Modify `learning_system/server.py`: call `orchestrator.close_learning_session()` instead of embedding close/evolve/plan logic directly.
- Create `learning_system/agent_contracts/*.json`: strict contract metadata for the nine internal teaching agents.
- Create `learning_system/prompts/*.md`: model-facing prompt templates for the nine internal teaching agents.
- Modify `tests/test_learning_system.py`: add TDD coverage for contract completeness, child-safe guards, transition guards, audit persistence, and orchestrator-owned close.
- Modify `README.md` and `docs/system/local_learning_system.md`: summarize the implemented agent boundary after code lands.

## Chunk 1: Contracts And Guards

### Task 1: Internal Agent Contract Registry

**Files:**
- Create: `learning_system/internal_agents.py`
- Create: `learning_system/agent_contracts/session_orchestrator.v1.json`
- Create: `learning_system/agent_contracts/graph_binding.v1.json`
- Create: `learning_system/agent_contracts/question_candidate.v1.json`
- Create: `learning_system/agent_contracts/question_review.v1.json`
- Create: `learning_system/agent_contracts/answer_review.v1.json`
- Create: `learning_system/agent_contracts/evaluation_decision.v1.json`
- Create: `learning_system/agent_contracts/teaching_step.v1.json`
- Create: `learning_system/agent_contracts/planner_transition.v1.json`
- Create: `learning_system/agent_contracts/evolution_proposal.v1.json`
- Test: `tests/test_learning_system.py`

- [ ] **Step 1: Write failing tests**
  Add tests proving:
  - all nine product-internal agents exist with the exact `does` and `does_not` responsibilities from the user's table;
  - each agent has a contract JSON file;
  - all contract files include `agent_key`, `contract_key`, `contract_version`, `prompt_version_id`, `response_schema_version`, and `minimum_confidence_to_apply`;
  - child-safe validation rejects Codex, agent names, graph/node ids, internal error tags, audit terms, and API/model failure wording.

- [ ] **Step 2: Run targeted tests and verify RED**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_internal_agent_contract_registry -v`
  Expected: FAIL because `internal_agents` does not exist.

- [ ] **Step 3: Implement minimal registry and validators**
  Implement:
  - `INTERNAL_AGENT_ROLES`;
  - `PHASES`, `NEXT_ACTIONS`, `MASTERY_DECISIONS`, `CLOSURE_RESULTS`;
  - `TRANSITION_TABLE`;
  - `validate_child_safe_message(payload)`;
  - `load_contract(contract_key)`;
  - `contract_hash(path)`.

- [ ] **Step 4: Add contract JSON files**
  Add one contract per internal teaching agent. These are metadata contracts, not full provider schemas yet.

- [ ] **Step 5: Run tests and verify GREEN**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_internal_agent_contract_registry -v`
  Expected: PASS.

### Task 2: Model Prompt Templates

**Files:**
- Create: `learning_system/prompts/session_orchestrator.v1.md`
- Create: `learning_system/prompts/graph_binding.v1.md`
- Create: `learning_system/prompts/question_candidate.v1.md`
- Create: `learning_system/prompts/question_review.v1.md`
- Create: `learning_system/prompts/answer_review.v1.md`
- Create: `learning_system/prompts/evaluation_decision.v1.md`
- Create: `learning_system/prompts/teaching_step.v1.md`
- Create: `learning_system/prompts/planner_transition.v1.md`
- Create: `learning_system/prompts/evolution_proposal.v1.md`
- Test: `tests/test_learning_system.py`

- [ ] **Step 1: Write failing tests**
  Add tests proving every contract references an existing prompt and each prompt contains:
  - untrusted data boundary;
  - JSON-only response rule;
  - no internal leakage rule;
  - agent-specific `做什么` / `不做什么` wording.

- [ ] **Step 2: Run targeted tests and verify RED**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_internal_agent_prompt_templates_exist_and_are_model_facing -v`
  Expected: FAIL because prompt files do not exist.

- [ ] **Step 3: Add prompt templates**
  Write concise model-facing prompt templates. Do not include parent-facing explanation prose.

- [ ] **Step 4: Run targeted tests and verify GREEN**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_internal_agent_prompt_templates_exist_and_are_model_facing -v`
  Expected: PASS.

## Chunk 2: Audit Data And Orchestrator

### Task 3: Agent Audit Tables

**Files:**
- Modify: `learning_system/db.py`
- Test: `tests/test_learning_system.py`

- [ ] **Step 1: Write failing tests**
  Add tests proving `init_schema()` creates:
  - `agent_runs`;
  - `agent_handoffs`;
  - `session_steps`;
  - `mastery_decisions`;
  - `question_review_records`;
  - `evolution_audits`.
  Also test helper functions can insert/read an accepted deterministic agent run and a mastery decision.

- [ ] **Step 2: Run targeted tests and verify RED**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_internal_agent_audit_tables_and_helpers -v`
  Expected: FAIL because tables/helpers are missing.

- [ ] **Step 3: Add schema and helpers**
  Add tables with JSON text fields and timestamps. Keep migrations append-only with `_ensure_column` where existing tables are affected.

- [ ] **Step 4: Run targeted tests and verify GREEN**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_internal_agent_audit_tables_and_helpers -v`
  Expected: PASS.

### Task 4: Teaching Session Orchestrator Close Path

**Files:**
- Create: `learning_system/orchestrator.py`
- Modify: `learning_system/server.py`
- Test: `tests/test_learning_system.py`

- [ ] **Step 1: Write failing tests**
  Add tests proving:
  - invalid transitions are rejected by the transition table;
  - session completion records an orchestrator agent run;
  - session completion records at least one `mastery_decisions` row for analyzed attempts;
  - duplicate close returns the existing closed result without creating a second evolution mutation.

- [ ] **Step 2: Run targeted tests and verify RED**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_teaching_session_orchestrator_records_close_audit -v`
  Expected: FAIL because orchestrator/audits are missing.

- [ ] **Step 3: Implement orchestrator facade**
  Move close logic from `server._close_learning_session` into `orchestrator.close_learning_session(conn, session_id)`. Preserve existing response shape and current behavior while adding audit rows.

- [ ] **Step 4: Wire server**
  Replace direct close logic with a call to `orchestrator.close_learning_session`.

- [ ] **Step 5: Run targeted tests and verify GREEN**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_teaching_session_orchestrator_records_close_audit -v`
  Expected: PASS.

## Chunk 3: Integration And Regression

### Task 5: Profile Seeding And Agent Reports

**Files:**
- Modify: `learning_system/db.py`
- Modify: `learning_system/agents.py`
- Test: `tests/test_learning_system.py`

- [ ] **Step 1: Write failing tests**
  Add tests proving seeded agent profiles include:
  - `session_orchestrator_agent`;
  - `graph_agent`;
  - `question_designer_agent`;
  - `question_reviewer_agent`;
  - `answer_analysis_agent`;
  - `evaluation_agent`;
  - `teaching_agent`;
  - `planner_agent`;
  - `self_evolution_agent`.

- [ ] **Step 2: Run targeted tests and verify RED**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_internal_agent_profiles_match_runtime_roles -v`
  Expected: FAIL because profile set does not match exact runtime roles.

- [ ] **Step 3: Update seed profiles and reports**
  Preserve existing profile keys that old tests depend on, but add the exact runtime roles and capability summaries.

- [ ] **Step 4: Run targeted tests and verify GREEN**
  Run: `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_internal_agent_profiles_match_runtime_roles -v`
  Expected: PASS.

### Task 6: Full Regression And Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/system/local_learning_system.md`
- Test: full suite

- [ ] **Step 1: Update docs**
  State that v1.5 has explicit product-internal agent contracts and orchestrator-owned session close audit. Do not claim every model agent is fully live if some remain contract-backed scaffolding.

- [ ] **Step 2: Run Python unit suite**
  Run: `python3 -m unittest tests/test_learning_system.py -v`
  Expected: PASS.

- [ ] **Step 3: Run browser smoke**
  Run: `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs`
  Expected: PASS.

- [ ] **Step 4: Run syntax checks**
  Run: `python3 -m py_compile learning_system/*.py`
  Expected: PASS.

## Constraints

- The project directory is not a Git repository; skip worktree and commit steps, but keep the same small-step verification discipline.
- Preserve the current runnable child page and API response shapes.
- Do not add a parent web dashboard.
- Do not expose internal agent, graph, Codex, audit, or self-evolution language to the child page.
- Do not use fallback keyword grading.
- Do not import external textbook or commercial question-bank data.
