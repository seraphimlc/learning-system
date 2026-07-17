# Dual Knowledge Views Engineering Contract v5.1

Date: 2026-07-14
Owner: 听云 (`tingyun`)
Status: ready-for-ruoming-and-jinghua-review
Scope: engineering source readiness, technical-plan delta, engineering contract, and implementation-blueprint constraints for the child-facing dual knowledge views

## Objective

Replace the approved single large-canvas knowledge-map implementation direction with two manual child-facing views over one unchanged authoritative mathematics graph:

- `mind_map`: a readable primary display tree with reviewed display parents, ordering, collapse defaults, and prerequisite cross-links;
- `graph`: a directed layered topology with rank, lane, arrow direction, cross-module bridges, overview-edge visibility, and selected one- or two-hop neighborhoods.

Both views share the same child-safe nodes, progress, mastery, actions, selection, opaque handles, target-intent runtime, and answer-assessment dependency. Display state never becomes learning evidence.

## Entry Lock

- request type: `technical_plan` / `engineering_contract` / `implementation_blueprint` delta
- complexity: `high_risk_change`
- authorized scope:
  - create this engineering contract;
  - revise `.agents/superpowers/specs/2026-07-14-child-knowledge-map-implementation.md` from single-view map home to dual views;
  - define decision-complete API, config, schema, runtime, UI, feature-flag, activation, validation, backup, receipt, and rollback contracts.
- forbidden scope:
  - no production-code changes in this dispatch;
  - no changes to the answer-assessment design or implementation plan;
  - no changes to Qingqiu's dual-view UX amendment;
  - no graph JSON rewrite, real-data reset, Git initialization, commit, push, parent Web surface, or live model call.
- project boundary overlay:
  - `AGENTS.md`;
  - single child, mathematics first, SQLite local-first;
  - GPT-5.5 for text semantics and Doubao for OCR;
  - answer-assessment activation before dual-view activation;
  - no mock/recorded evidence presented as live semantic PASS.
- output target: this document plus the revised implementation plan
- stop condition: technical artifacts self-reviewed and held for 若命 and 镜花 review; no implementation begins.

## Sources

- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/tingyun.md`
- `docs/collaboration/playbooks/engineering-execution.md`
- `docs/product/ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md`
- `docs/design/specs/2026-07-14-child-knowledge-map-home-design.md`
- `.agents/superpowers/specs/2026-07-14-child-knowledge-map-implementation.md`
- `docs/design/specs/2026-07-14-answer-assessment-storage-design.md`
- `.agents/superpowers/specs/2026-07-14-answer-assessment-feedback-implementation.md`
- user-approved v5.1 dual-view dispatch dated 2026-07-14
- read-only UX source: `docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md`

## ENGINEERING_SOURCE_READINESS

- verdict: `ENGINEERING_SOURCE_READY`
- prd_quality_gate_checked: yes
- product_source_content_ready: yes
- downstream_guessing_risk: none for this technical delta
- product_scope_ready: yes
- product_structure_ready: yes
- ux_flow_ready: yes; Qingqiu's amendment is present with `UX_FLOW_READY_FOR_TECHNICAL_PLANNING`
- data_contract_ready: yes
- project_boundary_ready: yes
- codebase_recon_ready: yes
- architecture_context_ready: yes
- authorization_ready: yes
- validation_targets_ready: yes
- missing_or_low_quality_sources:
  - Answer-assessment v5.1 implementation and activation artifacts are not present. This blocks dual-view activation and all enabled diagnostic/learning actions, not the current documentation delta.
- impact_on_engineering_quality:
  - no missing product/UX/config/API/schema/runtime decision blocks the technical artifacts;
  - map-home activation must stop until answer-assessment audit passes.
- route_back_to_ruoming:

| Gap | Impact | Suggested owner | Required artifact or decision |
|---|---|---|---|
| Answer assessment not yet active | Blocks target actions and production activation | 听云 implementation, then 镜花/观止 gates | accepted v5.1 assessment authority, active contracts/fingerprints, policy audit |

- allowed_scoped_output: technical-plan delta, engineering contract, implementation-plan delta, risk map, validation and rollback commands
- retry condition: 若命 and 镜花 approve this contract; the source-alignment test remains green before skeleton work; answer assessment passes before activation.

## Facts Checked

### Current Graph and Storage

- `data/knowledge_graphs/math/math_knowledge_graph_v2.json` is the current graph source and has 56 nodes across nine taxonomy modules.
- The live SQLite snapshot has 56 `graph_nodes`, 95 `prerequisite` edges, and 130 `unlocks` rows.
- `system_meta.graph_ref` pins graph version `2026-07-04.v2`, SHA-256 `1067b9c318efb116f6463fb7dd3db1a3888b440b6d33384c81313f79711a2971`, and the combined lineage.
- Thirty-five nodes have more than one strict prerequisite; the maximum strict prerequisite count is five.
- `learning_system/db.py` already owns additive schema setup and `system_meta`; it has no view-config or target-intent table today.

### Current Runtime and API

- `learning_system/graph_runtime.py` owns graph version lookup, node lookup, prerequisite summaries, rollback candidates, and graph-binding validation. It does not expose a complete graph snapshot or child projection.
- `learning_system/daily_runtime.py` owns the current child flow projection and target learning state. It has one environment boundary for `V3_DAILY_RUNTIME_ENABLED` and no knowledge-home policy function.
- `learning_system/server.py` exposes `/api/child-bootstrap` and current-step actions. It does not expose knowledge-view routes.
- Current child-safe text helpers strip or reject the product word `图谱`. Dual-view payloads therefore require a separate allowlisted projection validator; model-generated current-step text must retain its existing stricter sanitizer.

### Current Frontend

- `app/local_learning_system/index.html` contains one focused task surface.
- `app/local_learning_system/app.js` owns bootstrap, current-step state, DOM rendering, submission, polling, and local session state in one non-module script.
- No `knowledge_map.py`, view-config loader, knowledge-view frontend asset, focused dual-view test file, or dual-view engineering contract currently exists.

### Current Dependency State

- `answer_assessment_engineering_contract_v5_1.md`, `assessment_policy.py`, `assessment_store.py`, and `tests/test_answer_assessment_v51.py` are not present at this checkpoint.
- `.env.local` does not currently activate `ANSWER_ASSESSMENT_POLICY` or `KNOWLEDGE_MAP_HOME_POLICY`.

## TECHNICAL_PLAN Delta

### Architecture Decision Summary

| Decision | Contract |
|---|---|
| graph truth | Keep `math_knowledge_graph_v2.json` unchanged and authoritative for nodes and strict prerequisites. |
| view truth | Add one separately versioned JSON view config; it may arrange existing graph facts but may not add, remove, or reinterpret prerequisites. |
| backend boundary | `GraphRuntimeService` returns internal graph snapshots; `KnowledgeViewConfig` loads/validates display metadata; `KnowledgeMapService` joins graph, config, learner state, assets, handles, and target intents into child-safe projections. |
| API boundary | One `GET /api/knowledge-map` returns common child-safe nodes/relationships plus both view projections. `POST /api/knowledge-map/select` keeps the approved target-intent input and semantics and never receives the active display mode. |
| frontend boundary | `app.js` owns global map-home versus focused-learning orchestration. `knowledge_views.js` owns both view renderers and presentation state. Neither renderer owns learning evidence or target-intent policy. |
| persistence | SQLite adds only `learning_target_intents`; active view-config receipt reuses `system_meta`. View mode, viewport, and collapse preference stay in browser `localStorage`. |
| layout | Server supplies deterministic display metadata. The browser applies transforms only; no force simulation and no client-derived authoritative parent/rank/edge policy. |
| handles | One opaque HMAC node handle is reused in common nodes, mind-map placements, graph placements, details, actions, and target selection. Handles are never stored as graph lineage. |
| activation | `KNOWLEDGE_MAP_HOME_POLICY=v5.1` enables the dual-view home only when `ANSWER_ASSESSMENT_POLICY=v5.1` and active config/asset audits pass. |
| rollback | Normal rollback disables the feature flag and restarts. It does not restore or reset the live learner DB. Source and DB backups remain emergency evidence only. |

### Chosen File Boundaries

- `data/knowledge_graphs/math/math_knowledge_views_v5_1.json`
  - reviewed display configuration only;
  - version, graph lineage, mind-map tree metadata, graph rank/lane metadata, and all 95 overview visibility decisions.
- `learning_system/knowledge_view_config.py`
  - parse, validate, digest, and audit the view config;
  - no learner-state or HTTP concerns.
- `learning_system/knowledge_map.py`
  - child-safe common projection, handles, progress/mastery projection, asset eligibility, target-intent CRUD, and safe-boundary helpers;
  - consumes graph and view config but does not rewrite either.
- `app/local_learning_system/knowledge_views.js`
  - shared controller plus mind-map and graph renderers;
  - no API authority beyond invoking callbacks supplied by `app.js`.
- `app/local_learning_system/knowledge_views.css`
  - dual-view layout only; no focused-answer-state styling.
- `tests/test_knowledge_views_v51.py`
  - source/config/schema/API/runtime/UI contract tests for this feature.
- `scripts/activate_knowledge_views.py`
  - dry-run, activate, and audit config receipt; does not activate the runtime flag.
- `scripts/browser_dual_knowledge_views_v51.mjs`
  - isolated desktop/mobile browser acceptance and screenshots.

### Alternatives Rejected

1. **Rewrite the graph JSON with display parents and coordinates.** Rejected because display metadata would gain authority over graph truth and historical lineage.
2. **Return separate mind-map and graph endpoints.** Rejected because duplicate node/progress/action payloads could drift and mode switching would require extra fetches.
3. **Derive the mind-map parent and layered graph entirely in the browser.** Rejected because different clients could produce different trees/topologies and review evidence would not pin the display result.
4. **Persist active mode or viewport in SQLite.** Rejected because presentation preference is not learning evidence and the system serves one local child.
5. **Create two target-selection paths.** Rejected because view mode must not change target semantics, idempotency, prerequisite handling, or evidence.

## View Configuration Contract

### File Identity

Path: `data/knowledge_graphs/math/math_knowledge_views_v5_1.json`

Required top-level shape:

```json
{
  "schema_version": "knowledge-views.v1",
  "config_version": "2026-07-14.v5.1",
  "graph_lineage": "2026-07-04.v2+sha256:...",
  "root": {
    "label": "我的数学知识体系",
    "module_order": ["A_FOUNDATION", "B_FRACTION_RATIO"]
  },
  "mind_map": {
    "modules": {
      "A_FOUNDATION": {"order": 10, "collapsed_by_default": false}
    },
    "nodes": {
      "M-EXAMPLE": {
        "primary_parent": {"type": "module", "id": "A_FOUNDATION"},
        "order": 10,
        "collapsed_by_default": false
      }
    }
  },
  "graph": {
    "lanes": [
      {"id": "foundation", "label": "基础", "order": 10}
    ],
    "nodes": {
      "M-EXAMPLE": {"rank": 0, "lane": "foundation", "order": 10}
    },
    "overview_edge_visibility": {
      "M-SOURCE->M-TARGET": true
    }
  }
}
```

### Validation Invariants

- `graph_lineage` equals the exact current graph lineage and config activation receipt.
- The root lists all and only the nine graph taxonomy modules exactly once.
- `mind_map.modules` contains all and only the nine modules.
- `mind_map.nodes` contains all and only the 56 canonical node ids exactly once.
- `primary_parent.type` is `module` or `node`.
- A module parent equals the node's taxonomy module.
- A node parent names an existing strict prerequisite of that node.
- Node-parent links are acyclic and every node resolves to the virtual root through one module branch.
- `order` is an integer and is unique within one display parent.
- `collapsed_by_default` is boolean and has presentation authority only.
- Mind-map cross-links are derived as all 95 strict prerequisites minus strict prerequisite edges already represented by a node primary parent. No prerequisite is lost.
- `graph.nodes` contains all and only the 56 nodes. Every node has integer `rank`, existing `lane`, and integer `order` unique within a lane/rank bucket.
- Every strict prerequisite satisfies `source.rank < target.rank`; invalid layered direction blocks activation.
- `overview_edge_visibility` contains all and only the 95 canonical strict prerequisite edge keys with boolean values.
- Unlock-only candidates never appear in the child config or projection in v5.1.
- Config digest is calculated from canonical JSON and stored in the activation receipt; runtime refuses a digest mismatch.

## Child API Contract

### `GET /api/knowledge-map`

Success response:

```json
{
  "schema_version": "5.1-knowledge-views",
  "projection_version": "kv51:2026-07-14.v5.1:<digest-prefix>",
  "default_view": "mind_map",
  "modules": [],
  "nodes": [],
  "relationships": [],
  "views": {
    "mind_map": {
      "root_label": "我的数学知识体系",
      "placements": [],
      "cross_links": []
    },
    "graph": {
      "lanes": [],
      "placements": [],
      "edge_visibility": []
    }
  },
  "current_learning": {},
  "recommended_handles": []
}
```

Common field rules:

- `modules`: opaque module handle, child-readable name, order only.
- `nodes`: one row per node with one opaque node handle, name, module handle, child state label, learning-stage count/total, mastery band/summary, allowed actions, and recommendation badge.
- `relationships`: all 95 strict prerequisite pairs expressed only through opaque node handles and child-safe relation `hard_prerequisite`.
- `views.mind_map.placements`: the same node handles with one parent module/node handle, order, and collapse default.
- `views.mind_map.cross_links`: strict prerequisite handle pairs not used as primary tree parents.
- `views.graph.placements`: the same node handles with rank, opaque lane handle, and order.
- `views.graph.edge_visibility`: the same 95 strict pairs with `overview_visible` boolean.
- `current_learning`: child-safe current-step/analyzing/clarification/resume summary; no flow, step, attempt, assessment, queue, or job ids.
- No raw graph/config ids, graph lineage, config path, HMAC material, model/provider data, thresholds, rubrics, or internal status codes are returned.
- Payload target is at most 250 KB uncompressed.

Error behavior:

- policy off: `404` child-safe unavailable response so the existing focused entry remains active;
- answer-assessment dependency off or unaudited: `409`, no mutating actions;
- config/graph digest mismatch: `409`, preserve current learning and request reload;
- config missing/invalid: `503`, preserve current learning and expose list-free safe fallback messaging rather than guessed layout;
- learner projection stale: `200` with last verified state and child-safe refresh label; no new mastery claim.

### `POST /api/knowledge-map/select`

Request remains view-neutral:

```json
{
  "handle": "opaque-node-handle",
  "projection_version": "kv51:...",
  "action": "diagnostic|learn|review|challenge",
  "client_idempotency_key": "client-generated-key"
}
```

Rules:

- No `view`, rank, parent, lane, viewport, or collapse field is accepted.
- Resolve the opaque handle against the active graph/config projection before creating an intent.
- Revalidate action assets inside the same transaction that creates/applies the intent.
- One idempotency key reused with another node/action is rejected.
- Response reports only `applied`, `waiting_for_safe_boundary`, or `blocked`, plus child-safe current-learning state.
- `app.js` refreshes `/api/child-bootstrap` after `applied` and enters the existing focused learning surface.

### `GET /api/knowledge-map/preview`

- Query: opaque `handle` and current `projection_version`.
- Returns reviewed child-safe essence/example content only.
- Creates no flow, target intent, activity completion, attempt, assessment, or mastery evidence.

## Handle Contract

- Node handle input is `handle_policy_version + graph_lineage + canonical_node_id` signed with versioned HMAC.
- The installation secret is stored in `system_meta` and never returned.
- One canonical node produces exactly one handle in common nodes and both views.
- Module and lane handles use separate prefixes under the same policy.
- Handles are transport projections only. SQLite target intents store canonical node id and graph version.
- Stale graph/config projection versions reject mutation before target-intent creation.

## Mind-Map Runtime Contract

- The virtual root and nine module entries are presentation nodes, not graph nodes and not selectable learning targets.
- Every real node button appears exactly once in the primary tree.
- Multiple-parent graph meaning is preserved by cross-links; a cross-link never creates a second node button.
- Cross-links are hidden in the normal tree field and shown for selected nodes or explicit relation expansion.
- Module and branch collapse changes DOM visibility only. Hidden branches contain no tabbable descendants.
- Expanding, collapsing, browsing, selecting for detail, or switching views creates no evidence.

## Graph Runtime Contract

- The graph renderer uses server-provided rank/lane/order and never a force simulation.
- Lanes guide placement but are not rendered as nine dominant closed module boxes.
- All rendered relationships have arrowheads and non-color direction cues.
- Overview draws only edges whose config value is `true`.
- Selecting a node always reveals complete incoming and outgoing one-hop strict prerequisites/continuations.
- The child may expand the selected path to two hops; unrelated nodes/edges fade without being removed from keyboard access.
- Cross-module bridges and convergence nodes receive no special evidence meaning; they are layout/readability metadata only.

## Frontend State Contract

The child page keeps `map_home` and `learning_step` as mutually exclusive sibling surfaces. Hidden surfaces are inert and contain no tabbable descendants.

Required map-home states:

| State | Meaning | Allowed transition |
|---|---|---|
| `map_home_loading` | projection is loading; no fake nodes or progress | ready, unavailable, fallback |
| `map_home_ready` | one active view, shared controls, selectable nodes | detail, preview, target action, resume |
| `map_home_no_results` | local query/filter has no match; graph is not empty | clear query/filter |
| `map_home_unavailable` | projection cannot load safely; current learning is preserved | retry, resume, fallback |
| `map_home_stale` | projection version changed and mutation is blocked | refresh to ready/unavailable |
| `node_detail_open` | one shared selected-node detail is open | close, preview, target action |
| `node_no_available_action` | node is inspectable but no safe mutation may start | preview/relation navigation/close |
| `target_waiting_for_safe_boundary` | child target is remembered while save/analysis finishes | applied, replaced/cancelled, blocked |
| `current_analysis_pending` | prior answer is saved and being assessed | current step, clarify, teaching, blocked, summary |
| `current_learning_blocked` | saved work cannot yet be judged safely | real retry, summary, later recovery |

`learning_step` retains the existing v5 focused states and does not render under either spatial view.

Shared in-memory UI state across views:

- selected node handle and open detail;
- search query and active child-safe filter;
- focused module;
- common node/progress/mastery/action projection;
- current-learning summary.

Projection-specific UI state:

- viewport transform;
- mind-map collapse state;
- temporary relation/path expansion.

The segmented control is a native radio group or equivalent `radiogroup` labeled `知识展示方式`. Switching keeps focus on the selected segment, announces the opened mode through a polite live region, preserves search/filter/detail/selection, and does not move focus to the recentered node.

## Browser Presentation State Contract

`localStorage` keys are scoped by child-safe `projection_version`:

- `son-ai-knowledge-views:v5.1:<projection>:active-view`
- `son-ai-knowledge-views:v5.1:<projection>:mind_map:viewport`
- `son-ai-knowledge-views:v5.1:<projection>:graph:viewport`
- `son-ai-knowledge-views:v5.1:<projection>:mind_map:collapsed`

Rules:

- First visit with no valid stored value opens `mind_map`.
- Valid stored active view is `mind_map` or `graph`; unknown values are discarded.
- Each view stores `{scale, x, y}` independently and clamps invalid/out-of-range values.
- Switching views preserves the selected node and recenters it only when that destination view has no usable saved viewport for the selection.
- View mode, viewport, and collapse state never enter API requests, SQLite, reports, target-intent digests, or learning evidence.

## SQLite Contract

### `learning_target_intents`

Additive table and indexes remain as defined by the approved map design:

- id, child key, graph version, canonical node id, action, status;
- nullable source flow/revision/step refs;
- client idempotency key and node/action payload digest;
- applied flow/step refs, reason, timestamps;
- unique `(child_key, graph_version, client_idempotency_key)`;
- at most one nonterminal mutating intent per child/graph version.

No active view, viewport, collapse state, rank, lane, display parent, or handle is stored.

### Active View-Config Receipt

Reuse `system_meta` key `knowledge_views_active.v1` with JSON value:

```json
{
  "config_version": "2026-07-14.v5.1",
  "config_sha256": "...",
  "graph_lineage": "...",
  "relative_path": "data/knowledge_graphs/math/math_knowledge_views_v5_1.json",
  "activated_at": "..."
}
```

Activation writes this receipt only after config validation. It does not mutate `graph_nodes`, `graph_edges`, learner state, attempts, assessments, or mastery.

## Call Chain

| Step | Caller | Callee | Boundary | Failure behavior |
|---|---|---|---|---|
| 1 | browser load | `/api/child-bootstrap` and `/api/knowledge-map` | parallel read | focused state remains recoverable if map projection fails |
| 2 | server route | `KnowledgeMapService.child_projection()` | read-only DB/config | fail closed on graph/config/receipt mismatch |
| 3 | service | `GraphRuntimeService.graph_snapshot()` | graph truth | no client-derived graph facts |
| 4 | service | `KnowledgeViewConfig.load_validated()` | display truth | invalid config blocks map projection/activation |
| 5 | service | progress/mastery/asset queries | learner truth | stale/untrusted evidence cannot create mastery/action eligibility |
| 6 | frontend | `knowledge_views.js` | presentation | mode/viewport/collapse stay local |
| 7 | child action | `POST /api/knowledge-map/select` | mutation transaction | stale/tampered handle or incomplete asset creates no intent |
| 8 | target-intent reducer | existing `DailyLearningRuntime` | safe-boundary runtime | submitted evidence finishes before target switch |
| 9 | frontend | `/api/child-bootstrap` | focused learning state | enters existing one-current-action workspace |

## Async, Retry, and Recovery

- The dual-view GET path is synchronous and performs no model calls.
- View switching and viewport changes are client-only and have no retry/idempotency contract beyond local validation.
- Target selection uses the existing durable target-intent design and client idempotency key.
- Selection during answer analysis waits for the existing reducer safe boundary; it never cancels analysis.
- Restart recovery reapplies or explicitly blocks waiting intents after verifying graph version, source flow state, projection version, and action assets.
- No new background-job type is introduced for layout, handles, or view switching.

## Feature Flag and Dependency Contract

- Keep one feature flag: `KNOWLEDGE_MAP_HOME_POLICY=v5.1`.
- `daily_runtime.knowledge_map_home_enabled()` is the only environment read for that flag.
- It returns enabled only when:
  - the map flag is exactly `v5.1`;
  - `answer_assessment_v51_enabled()` is true;
  - runtime config audit finds a matching active `knowledge_views_active.v1` receipt.
- Unknown/unset/off values keep the existing focused-entry behavior.
- `POST /api/knowledge-map/select` additionally rechecks answer-contract-backed asset eligibility transactionally.
- The display config may be activated before the feature flag because it is inert. The feature flag may not be enabled before answer assessment, config, UI, runtime, and browser gates pass.

## Activation Order

1. Answer-assessment v5.1 implementation, contract/fingerprint audit, browser tests, and policy activation pass.
2. Qingqiu UX amendment is present and aligned with this contract.
3. View config dry-run proves 56 nodes, nine modules, 95 strict edge decisions, exact tree uniqueness, cross-link preservation, and layered rank direction.
4. Dual-view unit/API/runtime/UI/browser tests pass against an isolated copied DB.
5. Create exact source archive, SQLite backup, SHA-256 manifest, and changed-file receipt.
6. Activate the view-config receipt with `scripts/activate_knowledge_views.py --activate`.
7. Enable `KNOWLEDGE_MAP_HOME_POLICY=v5.1` through `scripts/set_learning_policy.py`.
8. Restart the service and verify `/api/child-bootstrap`, `/api/knowledge-map`, both views, one selection action, and current-step resume.

## Validation Contract

Required static/config commands:

```bash
python3 -m json.tool data/knowledge_graphs/math/math_knowledge_views_v5_1.json >/dev/null
python3 scripts/activate_knowledge_views.py --db data/local_learning_system.sqlite --config data/knowledge_graphs/math/math_knowledge_views_v5_1.json --dry-run
python3 -m py_compile learning_system/knowledge_view_config.py learning_system/knowledge_map.py learning_system/graph_runtime.py learning_system/daily_runtime.py learning_system/server.py scripts/activate_knowledge_views.py scripts/live_child_acceptance.py
node --check app/local_learning_system/knowledge_views.js
node --check app/local_learning_system/app.js
```

Required tests:

```bash
python3 -m unittest tests.test_knowledge_views_v51 -v
python3 -m unittest tests.test_answer_assessment_v51 -v
python3 -m unittest tests/test_learning_system.py -v
node scripts/browser_dual_knowledge_views_v51.mjs --scenario all --start-isolated
python3 scripts/live_child_acceptance.py --scenario dual-knowledge-views-v51 --start-isolated --policy v5.1
```

Required flag audit:

```bash
rg -n "KNOWLEDGE_MAP_HOME_POLICY" learning_system
```

Expected: the only environment read is inside `daily_runtime.knowledge_map_home_enabled()`.

Required browser evidence:

- desktop and 390x844 screenshots for mind map, graph overview, selected node, collapsed branch, active-flow resume, analyzing queue, blocked state, and list fallback;
- 56 accessible node buttons in each active renderer, with hidden renderer containing no tabbable descendants;
- selected node survives mode switch;
- independent viewports survive reload;
- visible arrowheads, cross-module bridge, convergence, and one-/two-hop selected path;
- no dominant nine-box graph layout;
- no overlap, raw-id leakage, hidden tabbables, or model/provider/rubric/job terms;
- human review remains required for visual hierarchy and child readability before final acceptance.

## No-Git Backup, Receipt, and Rollback

The implementation plan must include exact copyable commands and must never initialize Git.

### Source and DB Backup Before Implementation/Activation

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

Expected integrity output: `ok`.

### Changed-File Receipt

Write `logs/dual-knowledge-views-v51-changed-files.txt` with one project-relative path per created or modified file, followed by config/DB backup paths, config digest, test commands, and results. The receipt is evidence, not a PASS.

### Normal Rollback Without Data Reset

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

This is the default rollback. Additive config receipts and target-intent rows remain inert and auditable. Do not restore the live DB or delete learning records.

### Source-Code Rollback When Explicitly Required

Run only after the service is stopped and the backup manifest verifies:

```bash
BACKUP_DIR="$(cat logs/dual-knowledge-views-v51-backup-path.txt)"
cd /Users/liuchang/Documents/gitproject/son-ai-learning-system
shasum -a 256 -c "${BACKUP_DIR}/manifest.sha256"
rm -f \
  data/knowledge_graphs/math/math_knowledge_views_v5_1.json \
  learning_system/knowledge_view_config.py \
  learning_system/knowledge_map.py \
  app/local_learning_system/knowledge_views.js \
  app/local_learning_system/knowledge_views.css \
  tests/test_knowledge_views_v51.py \
  scripts/activate_knowledge_views.py \
  scripts/browser_dual_knowledge_views_v51.mjs
tar -xzf "${BACKUP_DIR}/source-before.tgz" -C /Users/liuchang/Documents/gitproject/son-ai-learning-system
python3 scripts/set_learning_policy.py --knowledge-map-home off
```

SQLite restore is not part of normal rollback because it could erase learning recorded after the backup. Any DB restore requires explicit user authorization, a stopped service, a newly captured post-incident backup, and a documented data-loss decision.

## Risks and Controls

| Risk | Impact | Control |
|---|---|---|
| display config silently diverges from graph | false tree/topology | exact lineage/digest, 56/9/95 set equality, prerequisite and rank validation |
| mind map loses multi-parent meaning | hidden preparation dependency | derive cross-links from all strict edges minus represented primary parents |
| graph becomes nine card boxes | product regression | rank/lane topology contract, DOM/CSS assertion, screenshots, human review |
| two views drift in state/actions | inconsistent child behavior | one common node/action projection and one opaque handle per node |
| view choice becomes evidence | false learning history | localStorage-only presentation state; no view fields in POST/SQLite/reports |
| child-safe scanner strips legitimate `图谱` label | broken UI copy | fixed frontend product copy plus a separate allowlisted map DTO validator; keep model-text sanitizer strict |
| mode switch interrupts analysis | lost evidence | no runtime mutation on view switch; target-intent safe-boundary rules unchanged |
| stale config accepted after graph update | wrong handles/layout | projection version plus active receipt and graph-lineage match |
| activation before scoring authority | unscorable actions | hard answer-assessment dependency in flag and activation script |
| no Git rollback loses source changes | unrecoverable local state | source archive, SQLite backup, SHA manifest, changed-file receipt, flag-first rollback |
| localStorage corruption breaks layout | blank/shifted view | parse/shape/range validation and fit-all fallback per view |

## TECHNICAL_PLAN_QUALITY_GATE

- verdict: `TECH_PLAN_READY`
- product_fit: pass
- architecture_fit: pass
- simplest_sufficient_design: pass
- contract_risks_identified: pass
- failure_resilience_planned: pass
- testability_planned: pass
- maintainability_fit: pass
- security_privacy_checked: pass
- operability_checked: pass
- performance_cost_checked: pass
- quality_evidence:
  - product fit: user-approved dispatch and `ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md`;
  - architecture fit: current `graph_runtime.py`, `db.py`, `daily_runtime.py`, `server.py`, and static child UI boundaries;
  - simplicity: one graph, one config, one GET, one selection path, local-only presentation state;
  - failure resilience: config receipt/digest, safe-boundary intents, flag-first rollback, no default DB restore;
  - testability: exact config/unit/API/browser/static commands and expected counts.
- blocking_quality_gaps: none for review; implementation remains gated by Qingqiu alignment and answer-assessment activation.

## ENGINEERING_CONTRACT_COVERAGE

- interfaces_complete: yes
- fields_complete: yes
- call_chain_complete: yes
- async_queue_complete: yes
- storage_scale_complete: yes
- compatibility_complete: yes
- contract_tests_named: yes
- blocking_gaps: none for this artifact

## ENGINEERING_CONTRACT_QUALITY_GATE

- verdict: `CONTRACT_READY`
- no_ambiguous_shared_fields: pass
- producers_consumers_complete: pass
- errors_permissions_complete: pass
- old_data_and_compatibility_complete: pass
- failure_retry_recovery_complete: pass
- contract_tests_or_validation_named: pass
- quality_evidence:
  - view-config schema and invariants define every authoritative display field;
  - API request/response and forbidden fields keep both views on one node/action authority;
  - SQLite excludes presentation state and preserves existing learner records;
  - activation and rollback are explicit and answer-assessment-gated.
- blocking_quality_gaps: none for 若命/镜花 review

## Blueprint Stop Conditions

- Do not begin skeleton/code work until Qingqiu's amendment exists and a name/state/focus/responsive alignment check passes.
- Do not enable mutating node actions until accepted answer contracts and assessments are active.
- Stop and revise this contract if implementation requires graph JSON changes, separate per-view selection semantics, persisted view preference, a second learning runtime, or a different feature-flag boundary.
- Stop after the later `SKELETON_PASS` for required 镜花、清秋 and 观止 gates.
