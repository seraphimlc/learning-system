# Dual Knowledge Views Home Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the complete 56-node mathematics knowledge system the child home page with two manual display modes, `导图` and `图谱`, over one unchanged authoritative graph and one unchanged target-selection runtime.

**Architecture:** Keep `math_knowledge_graph_v2.json` as graph truth and add one separately versioned view config for mind-map display parents/order/collapse and graph rank/lane/overview-edge visibility. A shared `KnowledgeMapService` returns common child-safe nodes and both projections through one GET; the static child page renders two accessible layouts with one selected node, one opaque handle per node, independent local viewports, and the existing focused learning workspace.

**Tech Stack:** Python 3.13, SQLite, existing graph JSON/runtime, static HTML/CSS/JavaScript, SVG, `unittest`, isolated browser acceptance.

**Authoritative engineering contract:** `docs/architecture/dual_knowledge_views_engineering_contract_v5_1.md`

**Product source:** `docs/product/ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md`

**Read-only UX source required before skeleton work:** `docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md`. Qingqiu owns this file. Do not create or modify it from the 听云 workline.

**Hard dependency:** Answer-assessment v5.1 must be implemented, audited, and active before dual-view activation or enabled diagnostic/learning actions. Dual-view config and code may be built against isolated data first, but production activation must fail closed when `ANSWER_ASSESSMENT_POLICY` is not `v5.1`.

**Repository rule:** This directory has no `.git`. Do not initialize Git. Replace commit steps with source/DB backups, SHA-256 manifests, verification checkpoints, and a changed-file receipt.

---

## Blueprint Delta

### Files to Create

- `data/knowledge_graphs/math/math_knowledge_views_v5_1.json`: reviewed display metadata only; no learner data and no replacement graph.
- `learning_system/knowledge_view_config.py`: config parsing, canonical digest, validation, and activation audit.
- `learning_system/knowledge_map.py`: graph/config join, opaque handles, common child projection, dual view projections, activity/mastery projection, asset eligibility, target-intent CRUD, and safe-boundary helpers.
- `tests/test_knowledge_views_v51.py`: focused config/schema/API/runtime/UI contract tests.
- `scripts/activate_knowledge_views.py`: config dry-run, receipt activation, and audit.
- `scripts/browser_dual_knowledge_views_v51.mjs`: isolated desktop/mobile browser acceptance and screenshots.
- `app/local_learning_system/knowledge_views.js`: shared dual-view controller, mind-map renderer, graph renderer, local presentation state, selection/detail behavior.
- `app/local_learning_system/knowledge_views.css`: dual-view-only layout and responsive styling.
- `docs/system/qa/dual_knowledge_views_v51_latest.md`: generated implementation evidence report.

### Files to Modify During Implementation

- `learning_system/db.py`: additive `learning_target_intents` schema/indexes only.
- `learning_system/graph_runtime.py`: internal complete graph snapshot helpers.
- `learning_system/daily_runtime.py`: feature/dependency gate, target-intent safe-boundary precedence, map-home current-learning summary, resume, and recovery.
- `learning_system/server.py`: `GET /api/knowledge-map`, `GET /api/knowledge-map/preview`, `POST /api/knowledge-map/select`, map-specific child-safe projection boundary.
- `app/local_learning_system/index.html`: sibling knowledge-home and focused-learning surfaces; load dual-view assets.
- `app/local_learning_system/app.js`: compose map and focused bootstrap, switch surfaces, dispatch shared node actions, preserve current-step behavior.
- `app/local_learning_system/styles.css`: shared shell dimensions/visibility only; no view layout duplication.
- `scripts/set_learning_policy.py`: add `--knowledge-map-home v5.1|off` after the answer-assessment plan creates this script.
- `scripts/live_child_acceptance.py`: isolated dual-view scenario orchestration.
- `scripts/generate_daily_report.py`: config/target-intent/activation evidence.
- `tests/test_learning_system.py`: cross-feature compatibility assertions only.
- `.env.local`: activation step only, after every gate passes.

### Files That Must Not Change

- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- `docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md`
- `docs/superpowers/specs/2026-07-14-answer-assessment-storage-design.md`
- `.agents/superpowers/specs/2026-07-14-answer-assessment-feedback-implementation.md`

---

## Chunk 0: Readiness, UX Alignment, and No-Git Safety

### Task 1: Verify Source Gates and Capture a Reversible Baseline

**Files:**
- Read: `docs/architecture/dual_knowledge_views_engineering_contract_v5_1.md`
- Read: `docs/product/ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md`
- Read only: `docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md`
- Read: answer-assessment authority and implementation evidence
- Create during execution: `logs/dual-knowledge-views-v51-backup-path.txt`

- [ ] **Step 1: Verify the Qingqiu amendment exists before any skeleton or production-code edit**

  Run:

  ```bash
  test -f docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md
  ```

  Expected: exit 0. If missing, stop with `REQUEST`; planning may remain valid, code may not start.

- [ ] **Step 2: Assert source names and states agree**

  Add a focused test that reads the PRD amendment, UX amendment, engineering contract, and this plan and asserts identical use of:

  ```text
  mind_map
  graph
  map_home
  /api/knowledge-map
  /api/knowledge-map/preview
  /api/knowledge-map/select
  KNOWLEDGE_MAP_HOME_POLICY
  ```

  Also assert the UX source keeps map home and focused learning as sibling surfaces and does not add a second learning runtime.

- [ ] **Step 3: Verify answer-assessment activation dependency without mutating it**

  Run:

  ```bash
  test -f docs/architecture/answer_assessment_engineering_contract_v5_1.md
  test -f tests/test_answer_assessment_v51.py
  python3 -m unittest tests.test_answer_assessment_v51 -v
  ```

  Expected before dual-view activation: PASS. If implementation work begins earlier, record `activation_blocked_by_answer_assessment` and keep all production flags off.

- [ ] **Step 4: Create a source and SQLite backup before production-code edits**

  Run exactly:

  ```bash
  STAMP="$(date +%Y%m%d-%H%M%S)-$(python3 -c 'import time; print(time.time_ns())')"
  BACKUP_DIR="data/backups/dual-knowledge-views-v51.${STAMP}"
  mkdir -p "${BACKUP_DIR}"
  tar -czf "${BACKUP_DIR}/source-before.tgz" \
    docs/architecture \
    docs/product \
    .agents/superpowers/specs/2026-07-14-child-knowledge-map-implementation.md \
    learning_system \
    app/local_learning_system \
    tests \
    scripts \
    .env.local
  sqlite3 data/local_learning_system.sqlite ".backup '${BACKUP_DIR}/local_learning_system.sqlite'"
  sqlite3 "${BACKUP_DIR}/local_learning_system.sqlite" "pragma integrity_check;"
  shasum -a 256 "${BACKUP_DIR}/source-before.tgz" "${BACKUP_DIR}/local_learning_system.sqlite" > "${BACKUP_DIR}/manifest.sha256"
  printf '%s\n' "${BACKUP_DIR}" > logs/dual-knowledge-views-v51-backup-path.txt
  ```

  Expected: integrity output `ok`; no Git command is run.

- [ ] **Step 5: Record the baseline checkpoint**

  Record graph lineage, 56/9/95 counts, current policy values, backup path, source archive digest, and DB backup digest in the engineering report.

---

## Chunk 1: Versioned View Config and Graph Snapshot

### Task 2: Add Failing View-Config Contract Tests

**Files:**
- Create: `tests/test_knowledge_views_v51.py`
- Reference: `data/knowledge_graphs/math/math_knowledge_graph_v2.json`

- [ ] **Step 1: Write failing config identity and exact-set tests**

  Assert the planned config has:

  ```python
  assert config["schema_version"] == "knowledge-views.v1"
  assert config["config_version"] == "2026-07-14.v5.1"
  assert config["graph_lineage"] == graph_runtime.current_graph_version()
  assert len(config["root"]["module_order"]) == 9
  assert set(config["mind_map"]["nodes"]) == graph_node_ids
  assert set(config["graph"]["nodes"]) == graph_node_ids
  assert set(config["graph"]["overview_edge_visibility"]) == hard_edge_keys
  ```

- [ ] **Step 2: Write failing mind-map invariants**

  Assert every real node has exactly one primary placement, parent type is `module|node`, module parents match taxonomy, node parents are strict prerequisites, sibling orders are unique, node-parent links are acyclic, and all 56 nodes reach the virtual root.

  Derive cross-links:

  ```python
  cross_links = hard_edges - represented_primary_prerequisite_edges
  assert represented_primary_prerequisite_edges | cross_links == hard_edges
  assert represented_primary_prerequisite_edges & cross_links == set()
  ```

- [ ] **Step 3: Write failing graph-layout invariants**

  Assert every node has `rank`, `lane`, and `order`; every lane exists; orders are unique within a lane/rank bucket; every hard edge satisfies `source.rank < target.rank`; all 95 hard edges have one boolean overview decision; unlock-only candidates are absent.

- [ ] **Step 4: Run tests and verify failure**

  Run:

  ```bash
  python3 -m unittest tests.test_knowledge_views_v51.KnowledgeViewConfigTests -v
  ```

  Expected: FAIL because the config and loader do not exist.

### Task 3: Create and Validate the Independent View Config

**Files:**
- Create: `data/knowledge_graphs/math/math_knowledge_views_v5_1.json`
- Create: `learning_system/knowledge_view_config.py`
- Create: `scripts/activate_knowledge_views.py`
- Test: `tests/test_knowledge_views_v51.py`

- [ ] **Step 1: Implement `KnowledgeViewConfig` with no learner-state dependency**

  Required API:

  ```python
  class KnowledgeViewConfig:
      @classmethod
      def load(cls, path: Path) -> "KnowledgeViewConfig": ...
      def validate_against(self, snapshot: dict) -> dict: ...
      def canonical_sha256(self) -> str: ...
      def projection_version(self) -> str: ...
      def mind_map_cross_links(self, hard_edges: set[tuple[str, str]]) -> list[tuple[str, str]]: ...
  ```

  Validation must return exact counts and concrete failures; it must not repair or infer missing parent/rank/visibility values.

- [ ] **Step 2: Author the reviewed v5.1 config**

  Include:

  - virtual root label and all nine module orders;
  - 56 mind-map node placements with primary parent, sibling order, and collapse default;
  - graph lanes that guide topology but are not module boxes;
  - 56 graph node rank/lane/order placements;
  - explicit boolean overview visibility for all 95 strict prerequisite edges.

  Do not copy learning status, mastery, question, answer, or attempt data into this file.

- [ ] **Step 3: Implement dry-run/activate/audit receipts**

  `scripts/activate_knowledge_views.py` supports:

  ```bash
  --dry-run
  --activate
  --audit
  --db <path>
  --config <path>
  ```

  `--activate` writes only `system_meta.knowledge_views_active.v1` after a complete validation. It never edits graph rows or `.env.local`.

- [ ] **Step 4: Run JSON, config, and receipt tests**

  Run:

  ```bash
  python3 -m json.tool data/knowledge_graphs/math/math_knowledge_views_v5_1.json >/dev/null
  python3 scripts/activate_knowledge_views.py --db data/local_learning_system.sqlite --config data/knowledge_graphs/math/math_knowledge_views_v5_1.json --dry-run
  python3 -m unittest tests.test_knowledge_views_v51.KnowledgeViewConfigTests -v
  ```

  Expected: 56 nodes, nine modules, 95 hard-edge visibility decisions, one primary placement per node, exact cross-link preservation, zero invalid rows.

- [ ] **Step 5: Prove the core graph did not change**

  Compare the current graph SHA-256 against the baseline checkpoint. Any change is a hard failure.

### Task 4: Add the Internal Graph Snapshot and Shared Handle Policy

**Files:**
- Modify: `learning_system/graph_runtime.py`
- Create/Modify: `learning_system/knowledge_map.py`
- Test: `tests/test_knowledge_views_v51.py`

- [ ] **Step 1: Write failing graph-snapshot and handle tests**

  Assert the internal snapshot contains exact graph lineage, nine modules, 56 nodes, 95 strict prerequisites, 35 unlock-only candidates, and no child-safe transformation.

  Assert one canonical node produces the same opaque handle in:

  ```text
  common nodes
  mind_map placement
  graph placement
  relationship endpoints
  detail selection
  POST select resolution
  ```

- [ ] **Step 2: Implement `GraphRuntimeService.graph_snapshot()`**

  Return internal canonical ids, taxonomy, nodes, strict prerequisites, and unlock-only audit candidates. Keep child projection concerns out of `graph_runtime.py`.

- [ ] **Step 3: Implement versioned HMAC handles**

  Store the installation secret in `system_meta`. Use distinct prefixes for node, module, and lane handles. Never return or persist canonical ids in child payloads/target intents through transport handles.

- [ ] **Step 4: Run snapshot/handle tests**

  Expected: exact counts, stable same-lineage handles, stale/tampered rejection, and no raw-id return.

---

## Chunk 2: Shared Child Projection and Dual-View API

### Task 5: Derive Activity, Mastery, and Action Eligibility Once

**Files:**
- Modify: `learning_system/knowledge_map.py`
- Test: `tests/test_knowledge_views_v51.py`

- [ ] **Step 1: Write failing shared-node projection tests**

  Cover untested, teaching exposure, worked-example completion, standard attempt, transfer attempt, invalidated attempt, corrected accepted assessment, stale graph version, and current target intent.

  Assert the common node projection is the only source for both view renderers.

- [ ] **Step 2: Implement four activity segments from existing records**

  Derive:

  1. reviewed essence completed;
  2. reviewed core-model/worked-example interaction completed;
  3. standard evidence question submitted;
  4. variant/transfer evidence question submitted.

  Do not create a progress table and do not treat opening, collapsing, switching, or previewing as activity.

- [ ] **Step 3: Implement child-safe mastery labels from accepted evidence only**

  Project `未测试`, `学习中`, `待巩固`, `暂时掌握`, and `需要先准备` without raw A/B/C/D codes or thresholds.

- [ ] **Step 4: Implement action eligibility with answer-assessment dependency**

  - `diagnostic`: active reviewed question plus active approved answer contract;
  - `learn`: reviewed teaching chain plus contract-backed micro-check, standard, variant, repair, and summary fallback;
  - `review`: active reviewed question/contract matching current evidence need;
  - `challenge`: reviewed transfer/stretch contract and prerequisite policy;
  - `preview`: reviewed content only, no evidence.

  If answer assessment is not active, return read-only nodes with mutating actions disabled and child-safe dependency wording.

- [ ] **Step 5: Run projection tests**

  Expected: no false weak/mastered state, no invalidated evidence, and identical actions in both views.

### Task 6: Build One Bounded Child-Safe Dual Projection

**Files:**
- Modify: `learning_system/knowledge_map.py`
- Modify: `learning_system/server.py`
- Test: `tests/test_knowledge_views_v51.py`

- [ ] **Step 1: Write failing API shape tests**

  Assert `GET /api/knowledge-map` returns:

  ```python
  expected_top_level = {
      "schema_version", "projection_version", "default_view",
      "modules", "nodes", "relationships", "views",
      "current_learning", "recommended_handles",
  }
  assert set(payload) == expected_top_level
  assert set(payload["views"]) == {"mind_map", "graph"}
  ```

  Assert 56 common nodes, nine modules, 95 relationships, 56 placements in each view, and payload below 250 KB uncompressed.

- [ ] **Step 2: Add a map-specific allowlist validator**

  Do not weaken model-generated current-step sanitization. The knowledge endpoint may use fixed product words such as `导图` and `图谱`, but must reject raw ids, graph lineage, config paths, HMAC material, thresholds, rubrics, model/provider data, queue/job state, and internal status codes.

- [ ] **Step 3: Implement `KnowledgeMapService.child_projection()`**

  Build common modules/nodes/relationships once, then attach:

  - mind-map placements and derived cross-links;
  - graph lanes, placements, and overview visibility;
  - child-safe current learning and recommendations.

  Both views reference the same opaque node handles.

- [ ] **Step 4: Add `GET /api/knowledge-map`**

  Behavior:

  - `404` when map policy is off;
  - `409` when answer assessment or projection version is not ready;
  - `503` for invalid/missing config;
  - `200` for valid child-safe projection.

- [ ] **Step 5: Add `GET /api/knowledge-map/preview`**

  Read-only reviewed content by opaque handle and projection version. Assert no intent, flow, activity, attempt, assessment, or mastery mutation.

- [ ] **Step 6: Run API, leakage, and payload tests**

  Expected: exact counts, no forbidden internals, and serialization target met over at least 20 warm runs.

---

## Chunk 3: Target Intent and Runtime Handoff

### Task 7: Add Failing Target-Intent Schema and State-Machine Tests

**Files:**
- Modify: `learning_system/db.py`
- Test: `tests/test_knowledge_views_v51.py`

- [ ] **Step 1: Write failing additive-schema tests**

  Assert `learning_target_intents` contains:

  ```text
  id, child_key, graph_version, node_id, action, status,
  source_flow_id, source_flow_revision, source_step_id,
  client_idempotency_key, payload_digest_sha256,
  applied_flow_id, applied_step_id, reason, created_at, updated_at
  ```

  Assert unique `(child_key, graph_version, client_idempotency_key)` and an enforceable at-most-one nonterminal mutating intent per child/graph version.

- [ ] **Step 2: Run tests and verify failure**

  Run:

  ```bash
  python3 -m unittest tests.test_knowledge_views_v51.TargetIntentSchemaTests -v
  ```

  Expected: FAIL because the table is missing.

- [ ] **Step 3: Add only the approved additive table and indexes**

  Do not add view mode, viewport, collapse, rank, lane, display parent, opaque handle, or progress fields to SQLite.

- [ ] **Step 4: Run schema tests**

  Expected: PASS with existing DB initialization tests unchanged.

### Task 8: Implement View-Neutral Selection and Safe-Boundary Precedence

**Files:**
- Modify: `learning_system/knowledge_map.py`
- Modify: `learning_system/daily_runtime.py`
- Modify: `learning_system/server.py`
- Test: `tests/test_knowledge_views_v51.py`

- [ ] **Step 1: Write failing state-machine tests**

  Cover:

  - map-home selection without a source flow;
  - retry idempotency;
  - one key reused for another node/action;
  - atomic cancellation of older pending/waiting intents;
  - stale/tampered handle and projection version;
  - immediate switch from unanswered step;
  - wait during submission/analysis/reducer commit;
  - apply after accepted assessment/mastery persistence;
  - switch from clarification safe boundary;
  - restart recovery;
  - no indefinite waiting;
  - view mode absent from request, row, digest, and report.

- [ ] **Step 2: Implement target-intent CRUD**

  Required API:

  ```python
  create_target_intent(...)
  newest_pending_intent(...)
  mark_waiting(...)
  apply_intent_at_safe_boundary(...)
  block_or_stale_intent(...)
  recover_target_intents(...)
  ```

- [ ] **Step 3: Add `POST /api/knowledge-map/select` without a view field**

  Request fields remain exactly:

  ```text
  handle
  projection_version
  action
  client_idempotency_key
  ```

  Response reports `applied|waiting_for_safe_boundary|blocked` and child-safe current-learning state.

- [ ] **Step 4: Integrate reducer precedence**

  In the accepted-answer reducer transaction, finish assessment/mastery first, then apply the newest valid pending/waiting target before normal next-step materialization.

- [ ] **Step 5: Reuse existing learning paths**

  Diagnostic selects a reviewed contract-backed question. Learn enters the existing new-knowledge path with explicit target, prerequisite probe/repair, and return-to-target intent. No second runtime or per-view action path is added.

- [ ] **Step 6: Run race, restart, and idempotency tests**

  Expected: one intent, one applied step, no lost assessment, no duplicate target, and no view-dependent behavior.

---

## Chunk 4: Dual-View Child UI

### Task 9: Add Sibling Home and Focused-Learning Surfaces

**Files:**
- Create: `app/local_learning_system/knowledge_views.js`
- Create: `app/local_learning_system/knowledge_views.css`
- Modify: `app/local_learning_system/index.html`
- Modify: `app/local_learning_system/app.js`
- Modify: `app/local_learning_system/styles.css`
- Test: `tests/test_knowledge_views_v51.py`

- [ ] **Step 1: Write failing static-contract tests**

  Assert:

  - one `map_home` region and one focused learning region are siblings;
  - one segmented `导图 / 图谱` control exists;
  - one shared node detail region exists;
  - hidden surfaces have no tabbable descendants;
  - no parent/operator UI and no nested focused question panel inside either view.

- [ ] **Step 2: Add stable markup shells**

  Include:

  - shared title/current-learning summary;
  - search and child-state filters;
  - segmented view control;
  - shared fit/zoom controls;
  - mind-map viewport;
  - graph viewport;
  - shared detail panel/mobile bottom sheet;
  - list fallback;
  - continue-current action.

- [ ] **Step 3: Define frontend module boundary**

  `app.js` owns API calls and global surface switching. `knowledge_views.js` exposes a single controller:

  ```javascript
  window.KnowledgeViews = Object.freeze({
    initialize,
    setProjection,
    show,
    hide,
    focusNode,
    currentView,
    destroy,
  });
  ```

  It emits node-action callbacks and never writes learning data directly.

- [ ] **Step 4: Add isolated styling**

  Use stable responsive dimensions, no card nesting, no decorative gradient/orbs, 8px-or-less radii, readable node labels, and no overlap at 390px.

- [ ] **Step 5: Run static and syntax checks**

  ```bash
  node --check app/local_learning_system/knowledge_views.js
  node --check app/local_learning_system/app.js
  python3 -m unittest tests.test_knowledge_views_v51.DualViewStaticContractTests -v
  ```

### Task 10: Implement the Accessible Mind-Map View

**Files:**
- Modify: `app/local_learning_system/knowledge_views.js`
- Modify: `app/local_learning_system/knowledge_views.css`
- Test: `tests/test_knowledge_views_v51.py`
- Browser: `scripts/browser_dual_knowledge_views_v51.mjs`

- [ ] **Step 1: Write failing mind-map browser-contract tests**

  Assert virtual root, nine module branches, 56 unique real node buttons, config order, collapse defaults, branch collapse/expand, search/filter, selected-node detail, cross-link disclosure, keyboard selection, focus restoration, and list fallback.

- [ ] **Step 2: Render every real node exactly once**

  Use one HTML button per node in the primary tree. Do not clone node buttons for cross-links. Cross-links reference existing handles and appear only for selection/explicit relation expansion.

- [ ] **Step 3: Implement collapse accessibly**

  Collapse buttons expose `aria-expanded`; hidden descendants are not tabbable. Collapse state is presentation-only.

- [ ] **Step 4: Implement transform and focus behavior**

  Pan/continuous zoom/fit-all operate on the mind-map viewport. Selecting a node recenters it, highlights its primary path and cross-links, and opens the shared detail surface.

- [ ] **Step 5: Run mind-map browser tests**

  Expected: 56 unique nodes, all prerequisites preserved through primary edges plus cross-links, no overlap desktop/mobile, and keyboard support.

### Task 11: Implement the Directed Layered Graph View

**Files:**
- Modify: `app/local_learning_system/knowledge_views.js`
- Modify: `app/local_learning_system/knowledge_views.css`
- Test: `tests/test_knowledge_views_v51.py`
- Browser: `scripts/browser_dual_knowledge_views_v51.mjs`

- [ ] **Step 1: Write failing topology browser-contract tests**

  Assert:

  - positions follow rank/lane/order;
  - every visible edge has an arrowhead and non-color direction cue;
  - overview renders only configured backbone edges;
  - selection renders complete one-hop incoming/outgoing relationships;
  - explicit expansion renders at most two hops;
  - convergence and at least one cross-module bridge are visible;
  - no nine dominant closed module boxes or module card grids exist.

- [ ] **Step 2: Render server-provided layered positions**

  Use HTML node buttons and SVG edges inside one transformed viewport. Do not use a force simulation or recompute authoritative ranks/lanes in the browser.

- [ ] **Step 3: Implement overview and selected-path visibility**

  Overview uses `overview_visible`. Selection overrides overview for full one-hop context; `查看完整路径` expands to two hops. Unrelated nodes/edges fade but remain discoverable.

- [ ] **Step 4: Implement graph accessibility**

  Each node remains a uniquely named focusable button. Edge direction and selected relationships have text/legend support rather than color-only meaning.

- [ ] **Step 5: Run graph browser tests**

  Expected: directed layered topology, arrowheads, bridges, convergence, selected 1-2 hop, no module boxes, no overlap.

### Task 12: Share Selection, Detail, Local Preference, and Runtime Actions

**Files:**
- Modify: `app/local_learning_system/knowledge_views.js`
- Modify: `app/local_learning_system/app.js`
- Test: `tests/test_knowledge_views_v51.py`
- Browser: `scripts/browser_dual_knowledge_views_v51.mjs`

- [ ] **Step 1: Write failing mode/persistence tests**

  Assert first visit opens `mind_map`; valid later choice restores; selection survives mode switch; each mode restores a separate viewport; invalid localStorage falls back safely; no view field reaches API or DB.

- [ ] **Step 2: Implement projection-scoped localStorage**

  Use:

  ```text
  son-ai-knowledge-views:v5.1:<projection>:active-view
  son-ai-knowledge-views:v5.1:<projection>:mind_map:viewport
  son-ai-knowledge-views:v5.1:<projection>:graph:viewport
  son-ai-knowledge-views:v5.1:<projection>:mind_map:collapsed
  ```

  Validate JSON shape and clamp transforms before applying.

- [ ] **Step 3: Keep one selected node and one shared detail surface**

  Switching modes keeps the handle selected and recenters it in the destination view when needed. Escape closes detail and restores focus to the originating node in the active view.

- [ ] **Step 4: Connect actions through `app.js`**

  - preview calls the read-only preview endpoint;
  - mutating actions call one view-neutral select endpoint with one idempotency key;
  - applied selection refreshes `/api/child-bootstrap` and enters focused learning;
  - waiting selection stays on map home with honest pending status;
  - continue current learning enters the already-fetched focused state.

- [ ] **Step 5: Preserve cold-reload and active-analysis behavior**

  Initial load composes `/api/child-bootstrap` with `/api/knowledge-map`. During analysis, map home shows `当前答案正在批阅` and queues a new target without interrupting the transaction.

- [ ] **Step 6: Run dual-view interaction tests**

  Expected: shared selection/actions, independent viewports, no evidence mutation from presentation, and focused workspace remains one-current-action.

---

## Chunk 5: Recovery, Reporting, Regression, and Activation

### Task 13: Integrate Recovery and Codex-Readable Evidence

**Files:**
- Modify: `learning_system/daily_runtime.py`
- Modify: `scripts/generate_daily_report.py`
- Modify: `scripts/live_child_acceptance.py`
- Create: `docs/system/qa/dual_knowledge_views_v51_latest.md`
- Test: `tests/test_knowledge_views_v51.py`

- [ ] **Step 1: Write failing recovery/report tests**

  Assert restart restores active flow and waiting target intent; stale graph/config projections explicitly stale/block the intent; report distinguishes child target, system recommendation, prerequisite detour, final applied node, config version/digest, and answer-assessment dependency.

- [ ] **Step 2: Implement startup recovery**

  Recover pending/waiting intents only at a verified safe boundary. Recheck graph lineage, active config receipt, action assets, and answer-assessment activation.

- [ ] **Step 3: Implement Codex-readable reporting**

  Reports may include canonical ids and audit lineage; child APIs/DOM may not. View mode and viewport must not appear as learning evidence.

- [ ] **Step 4: Extend isolated live acceptance orchestration**

  Add:

  ```bash
  python3 scripts/live_child_acceptance.py --scenario dual-knowledge-views-v51 --start-isolated --policy v5.1
  ```

  The script copies the DB, allocates a free port, launches the server with both assessment and map policies, prints the URL, runs acceptance, and terminates the server.

- [ ] **Step 5: Run report/recovery tests**

  Expected: no stale intent accepted, no child leakage, and report evidence pinned to config/graph/assessment lineage.

### Task 14: Full Regression, Browser Evidence, Backup Receipt, and Atomic Activation

**Files:**
- Create/Modify: `scripts/browser_dual_knowledge_views_v51.mjs`
- Modify: `scripts/set_learning_policy.py`
- Modify: `tests/test_learning_system.py` only for cross-feature assertions
- Modify: `.env.local` only after every gate passes
- Create: `logs/dual-knowledge-views-v51-changed-files.txt`

- [ ] **Step 1: Run static and focused validation**

  ```bash
  python3 -m json.tool data/knowledge_graphs/math/math_knowledge_views_v5_1.json >/dev/null
  python3 scripts/activate_knowledge_views.py --db data/local_learning_system.sqlite --config data/knowledge_graphs/math/math_knowledge_views_v5_1.json --dry-run
  python3 -m py_compile learning_system/knowledge_view_config.py learning_system/knowledge_map.py learning_system/graph_runtime.py learning_system/daily_runtime.py learning_system/server.py scripts/activate_knowledge_views.py scripts/live_child_acceptance.py
  node --check app/local_learning_system/knowledge_views.js
  node --check app/local_learning_system/app.js
  python3 -m unittest tests.test_knowledge_views_v51 -v
  ```

  Expected: all PASS; graph JSON SHA unchanged.

- [ ] **Step 2: Run dependency and full regressions**

  ```bash
  python3 -m unittest tests.test_answer_assessment_v51 -v
  python3 -m unittest tests/test_learning_system.py -v
  ```

  Expected: all PASS. Legacy flows remain readable and do not mix assessment policies.

- [ ] **Step 3: Run isolated dual-view browser acceptance**

  ```bash
  node scripts/browser_dual_knowledge_views_v51.mjs --scenario all --start-isolated
  python3 scripts/live_child_acceptance.py --scenario dual-knowledge-views-v51 --start-isolated --policy v5.1
  ```

  Cover desktop and 390x844:

  - 56 nodes and nine modules in both modes;
  - first-use mind map and remembered last mode;
  - independent viewports;
  - mind-map unique primary tree, collapse, and cross-links;
  - graph rank/lane topology, arrows, bridge, convergence, selected one-/two-hop;
  - no nine closed module boxes;
  - search/filter/focus/detail/escape/focus restoration;
  - autonomous nonrecommended choice;
  - prerequisite detour and return;
  - current-step resume, analyzing switch queue, clarification switch, restart;
  - tampered/stale handle/config, missing asset, dependency off, and list fallback;
  - no hidden tabbables, overlap, raw ids, model/provider/rubric/job leakage.

- [ ] **Step 4: Measure payload and interaction budgets**

  Measure at least 20 warm server serializations and 20 post-load fit/search/filter/focus/mode-switch actions per viewport. Report median and worst values against 250 KB payload and 100 ms post-load interaction targets.

- [ ] **Step 5: Audit the single feature-flag read boundary**

  Add tests for `unset/off/unknown -> false` and `v5.1 -> true only with assessment + config receipt`.

  Run:

  ```bash
  rg -n "KNOWLEDGE_MAP_HOME_POLICY" learning_system
  ```

  Expected: the only environment read is inside `daily_runtime.knowledge_map_home_enabled()`.

- [ ] **Step 6: Activate the view-config receipt while the feature remains off**

  ```bash
  python3 scripts/activate_knowledge_views.py --db data/local_learning_system.sqlite --config data/knowledge_graphs/math/math_knowledge_views_v5_1.json --activate
  python3 scripts/activate_knowledge_views.py --db data/local_learning_system.sqlite --config data/knowledge_graphs/math/math_knowledge_views_v5_1.json --audit
  ```

  Expected: exact active config digest/graph lineage and zero invalid rows. This is inert until the policy flag is enabled.

- [ ] **Step 7: Activate the dual-view home atomically**

  Only after answer assessment is active and all gates pass:

  ```bash
  python3 scripts/set_learning_policy.py --knowledge-map-home v5.1
  ```

  Restart the normal service, then verify:

  ```bash
  curl -fsS http://127.0.0.1:8765/api/child-bootstrap
  curl -fsS http://127.0.0.1:8765/api/knowledge-map
  ```

  Expected: child bootstrap remains the focused-state source; knowledge-map returns one common node set plus both projections; first page opens mind map.

- [ ] **Step 8: Write the changed-file receipt**

  `logs/dual-knowledge-views-v51-changed-files.txt` contains:

  - one project-relative created/modified path per line;
  - source archive and SQLite backup paths/digests;
  - graph/config/activation receipt digests;
  - every validation command and result;
  - browser screenshot paths;
  - unresolved or unverified paths;
  - explicit statement: `git_initialized=false`.

- [ ] **Step 9: Verify the copyable normal rollback**

  Normal rollback disables the UI/runtime path and preserves learning data:

  ```bash
  python3 scripts/set_learning_policy.py --knowledge-map-home off
  if [[ -f logs/server-8765.pid ]]; then
    PID="$(cat logs/server-8765.pid)"
    kill "${PID}"
    while kill -0 "${PID}" 2>/dev/null; do sleep 0.2; done
  fi
  test -z "$(lsof -tiTCP:8765 -sTCP:LISTEN)"
  scripts/run_local_learning_server_8765.sh
  curl -fsS http://127.0.0.1:8765/api/child-bootstrap
  ```

  Do not restore or reset the live DB during normal rollback. Additive config receipts and target-intent rows remain inert and auditable.

- [ ] **Step 10: Record final implementation checkpoint**

  Generate `docs/system/qa/dual_knowledge_views_v51_latest.md` with config counts, graph counts, tree/cross-link proof, topology evidence, API/schema/runtime results, screenshots, performance, answer-assessment dependency, changed-file receipt, backup, feature flag, rollback, and residual risks.

---

## Required Gates and Stop Conditions

1. **Before skeleton/code:** Qingqiu UX amendment exists and matches source names/states/focus/responsive contracts.
2. **After skeleton:** return `SKELETON_PASS`; stop for 镜花 design review, 清秋 UX review, and 观止 `TEST_CASE_SOURCE_READINESS` / `TEST_CASE_SPEC`.
3. **Before business logic:** required skeleton/design/UX/test-design gates pass or are explicitly waived by 若命/user.
4. **Before activation:** answer assessment active; config/graph/asset/API/runtime/browser audits pass; backups and changed-file receipt exist.
5. **On deviation:** stop and revise the engineering contract/plan if code would modify graph JSON, persist view state, add per-view target semantics, add a second runtime, weaken assessment authority, or require a different activation boundary.
6. **Completion output:** 听云 returns `DONE_CLAIMED` with implementation quality evidence only. It is not review or QA PASS.

