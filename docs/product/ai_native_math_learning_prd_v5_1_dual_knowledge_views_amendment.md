# PRD v5.1 Amendment: Dual Knowledge Views

Status: `PRD_READY`

Decision source: user-confirmed discussion on 2026-07-14. This amendment supersedes only the single-view knowledge-map clauses in the v5 product artifacts. All other v5 child-only learning-loop boundaries remain in force.

## PRD Result Summary

- Actor: the single child using the Web learning surface.
- Product decision: the mathematics knowledge home provides two manual display modes over one authoritative knowledge graph.
- Default behavior: first visit opens the mind-map view; later visits remember the last local UI choice.
- Product value: the mind map makes the scope of knowledge easy to scan, while the graph makes prerequisites, convergence, bridges, and downstream impact visible.
- Authority boundary: display mode never changes graph facts, mastery, evidence, question selection, or learning-target semantics.
- Delivery order: answer-contract assessment must be active before a node can start contract-backed diagnosis or learning.

## User Experience Contract

### Shared Surface

- The child remains on one page and switches with a segmented `导图 / 图谱` control.
- Both modes use the same node set, child-safe labels, progress, mastery state, selection, detail actions, and opaque transport handles.
- Switching keeps the selected node and recenters it in the destination layout.
- Each mode keeps its own pan and zoom state for the current browser.
- Display preference is local UI state and is not learning evidence.

### Mind-Map View

- The view has one virtual root, `我的数学知识体系`, followed by the nine reviewed mathematics modules.
- Every real graph node appears exactly once in the primary display tree.
- A node with multiple prerequisites has one reviewed display parent; all remaining real prerequisites remain available as cross-links.
- Modules and branches can be collapsed without changing learning state.
- Cross-links are disclosed on selection or explicit relation expansion rather than drawn as a permanent line field.

### Graph View

- The graph is a directed layered topology, not nine closed module boxes containing card grids.
- Position follows prerequisite depth, learning stage, module lane, and reviewed bridge placement.
- Arrowheads make direction unambiguous.
- Overview shows the reviewed backbone. Selecting a node reveals its complete one-hop and optional two-hop prerequisite/downstream neighborhood.
- Convergence nodes and cross-module bridges must be visually legible without relying on color alone.

## Data Boundary

- `data/knowledge_graphs/math/math_knowledge_graph_v2.json` remains the sole knowledge-relationship source of truth and is not rewritten for either view.
- A separate versioned view configuration may contain display-parent choice, branch order, collapse defaults, graph rank/lane, and overview-edge visibility.
- View metadata has no authority to add, remove, or reinterpret graph prerequisites.
- Learning history, mastery, questions, answer contracts, attempts, and assessments remain separate data concerns.

## Child Actions

- Selecting a node opens one shared detail surface in either mode.
- Available actions are derived from current reviewed assets and may include learn, diagnose, review, preview, or challenge.
- Preview remains read-only and creates no target intent or evidence.
- A learning action persists one target intent and hands it to the existing runtime at a safe boundary.
- Choosing an advanced target preserves the child's target while the runtime probes or repairs prerequisites.

## Acceptance Criteria

- All 56 current nodes and nine modules are represented in both views.
- The mind-map primary tree contains every node exactly once and retains every extra prerequisite as a cross-link.
- The graph projects the 95 reviewed strict prerequisites and hides the 35 unlock-only candidates from the child release.
- First visit opens the mind map; a later reload restores the last selected mode.
- Selection survives a mode switch, and the two modes keep independent viewport state.
- The graph has visible direction, convergence, bridges, and learning depth and does not present nine dominant closed boxes.
- Desktop and 390px mobile experiences support keyboard/touch navigation, focus restoration, reduced motion, and child-safe pending/blocked states.
- No child response exposes canonical graph ids, question ids, attempt ids, model/provider, rubric, queue, or job internals.

## Non-Goals

- No second knowledge data model.
- No free-form graph editor.
- No child-authored relationship changes.
- No parent Web surface.
- No automatic mastery changes caused by browsing, expanding, switching, or previewing.
- No display of unlock-only candidate edges before review.

## Product Quality Gate

`PRD_QUALITY_READY`

Product quality evidence:

- `user_confirmed`: manual dual-view switching, graph-backed data, first-use mind map, and freedom to replace the current prototype.
- `code_verified`: the current prototype is module-grid positioned and does not visually express the graph topology.
- `data_verified`: the current graph contains 56 nodes, 95 strict prerequisite edges, and 35 nodes with multiple strict prerequisites.
- `design_decision`: a separate view projection preserves graph truth while allowing a readable tree representation.

## PRD Readiness Gate

`PRD_READY`

Downstream roles do not need to guess the actor, default mode, view authority, graph-versus-view data boundary, node-selection behavior, activation dependency, or child-safe acceptance criteria. Qingqiu owns the exact UX flow amendment; Tingyun owns the engineering contract and implementation blueprint delta; Jinghua and Guanzhi retain independent review and QA gates.
