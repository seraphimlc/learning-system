# Child Knowledge Map Home Design

Date: 2026-07-14
Status: spec-reviewed-approved
Scope: child home page, full mathematics knowledge map, node progress, autonomous node selection, and runtime handoff

## Objective

Make the complete mathematics knowledge graph the child-facing home page. The child can see the whole learning system, zoom and pan a large map, select any node, understand current progress, and intentionally start learning or testing that node.

AI remains an advisor and safety layer. It may recommend a node, check prerequisites, or insert a prerequisite probe, but it does not become the only way to enter learning.

## Approved Product Direction

- The home page is one large, zoomable knowledge-map canvas rather than a fixed task list.
- All 56 current math graph nodes appear, grouped into the graph's nine modules.
- The child can drag, continuously zoom, search, filter, select a module, and select a node.
- Selecting a node moves the camera to that node, emphasizes its local dependency path, and opens child-readable details.
- Every node shows learning progress and mastery state as separate concepts.
- The child can choose to learn a node or take a diagnostic check.
- Weak prerequisites do not make the target invisible. The system explains the preparation gap and preserves the child's target intent while offering a prerequisite-first path.
- The current large-canvas visual prototype is the interaction reference: `.superpowers/brainstorm/2026-07-14-knowledge-map/knowledge-map-full-canvas-v2.html`.

## Authority Amendment

This design supersedes only the first-viewport/home-entry clauses in `docs/product/child_ux_flow_spec_v5.md`.

- `/` remains the single child Web surface.
- Initial page open enters `map_home`, not an automatic question workspace.
- `map_home` is navigation and progress projection, not a learning step and not evidence.
- Starting/resuming a node enters the existing focused `learning_step` surface, which still shows exactly one current action.
- Submission, analyzing, clarification, teaching, feedback, blocked, and summary states retain their existing focused behavior; they do not render underneath the map.
- At safe completion points the child can return to `map_home` or follow the runtime-selected continuation.
- An unfinished step is represented on `map_home` by one clear `继续当前学习` action.
- A cold reload while analysis is active opens `map_home` with an honest `当前答案正在批阅` status and resume action; the in-page post-submit experience remains on the focused analyzing surface.

All evidence, current-step, child-safe, queue, and runtime authority clauses from v5 remain in force. The implementation plan must publish matching PRD/UX/engineering amendments before activation.

## Non-Goals

- Do not expose backend graph ids, model/provider details, rubrics, mastery thresholds, attempt ids, or queue state.
- Do not turn the child page into a graph editor.
- Do not use a force simulation that changes positions on every page load.
- Do not claim that an untested node is weak.
- Do not make prerequisite warnings into an unexplained hard lock.
- Do not replace the one-current-step learning runtime with free navigation during an active submission or analysis transaction.

## Child Home Structure

The first viewport contains:

- product title and current learning summary;
- search by child-readable node/module name;
- filters for all, has learning record, needs consolidation, and untested;
- zoom out, zoom in, and fit-all controls;
- the full graph canvas;
- a compact module index;
- a minimap on desktop;
- a visible `继续当前学习` action when an unfinished safe current step exists.

The map is the primary surface, not a secondary drawer behind an AI-generated daily route.

## Stable Large-Canvas Layout

The runtime projects a stable layout for the current graph version:

- nine module regions use deterministic positions;
- nodes within a module use deterministic sequence and prerequisite ordering;
- the same graph version produces the same node positions across sessions;
- a graph-version change may create a new layout version but does not rewrite historical learning records;
- client pan/zoom state may be remembered locally as a presentation preference, not learning evidence.

Production rendering uses accessible HTML buttons for nodes and an SVG relationship layer inside one transformed viewport. Canvas-only hit targets are not sufficient because nodes must remain keyboard accessible and inspectable.

The current graph size of 56 nodes is small enough for one bounded child-safe payload and DOM/SVG rendering without a graph engine dependency.

## Node Surface

Each visible node shows:

- child-readable knowledge-point name;
- one child-safe state label;
- priority or stage only when it helps orientation;
- compact learning-progress segments;
- compact mastery-evidence segments.

Allowed child-safe state labels:

- `未测试`: no accepted evidence exists;
- `学习中`: teaching exposure or early evidence exists but the node has not closed;
- `待巩固`: usable evidence shows a current gap or unstable performance;
- `暂时掌握`: independent evidence is stable enough for the current learning horizon;
- `需要先准备`: target is selectable but one or more prerequisite nodes need a probe or repair.

The page never converts `未测试` into `不会`.

## Learning Activity Progress Versus Mastery Progress

The child label is `学习历程`, not `理解进度`. It records completed learning activities, not correctness or understanding:

1. read and continued past the reviewed essence explanation;
2. completed the reviewed core-model/worked-example interaction;
3. submitted one standard evidence question;
4. submitted one variant/transfer evidence question.

The child surface displays this as four activity segments or `x/4`. Merely opening or previewing a node does not complete a stage. Completed activity does not claim correctness.

The projection is recomputed from existing authoritative records:

- completed `worked_example`/teaching `flow_steps` and `teaching_step_events` for stages 1-2;
- immutable attempts joined to reviewed question evidence roles for stages 3-4.

No new learning-progress table is introduced. Replaying or invalidating an assessment does not erase that an activity occurred, while invalidating/corrupting an attempt removes it from the trusted activity projection.

Mastery progress is evidence based and categorical. It is derived only from accepted assessments and graph-valid mastery decisions. The child sees a small segmented indicator and label, not a false precision percentage.

Changing an assessment or invalidating evidence may recompute mastery while preserving the immutable learning-stage history.

## Relationship Semantics

The current graph contains 225 stored edge rows:

- 95 strict `prerequisite` relationships;
- 130 `unlocks` relationships, of which 95 duplicate the prerequisite direction and 35 represent broader enabling/support relationships.

The child map does not render all stored rows as equal lines.

Canonical child-facing edge classes:

- `hard_prerequisite`: target learning depends on the source; derived from reviewed prerequisite edges;
- `soft_support`: optional source knowledge helps the target but is not a hard gate; emitted only by an explicit reviewed edge-projection policy;
- `unlocks`: a child-facing reverse projection generated from the canonical classes, not a separately drawn duplicate.

Initial activation treats the 95 prerequisite relations as authoritative `hard_prerequisite` edges. The 35 unlock-only relations are `support_candidates`, not automatically trusted soft supports. They remain hidden unless a versioned edge-projection review policy approves their direction and meaning.

Reciprocal unlock-only pairs cannot produce two opposing directional soft-support arrows. Review must either choose one justified direction, classify the relation as nondirectional related context, or keep it hidden. The initial child release may safely show hard prerequisites only.

Display policy:

- fit-all overview shows module regions and a faint aggregated backbone, not 225 equally strong lines;
- zoomed module view may show hard prerequisite edges at low opacity;
- selected-node view always shows one-hop incoming prerequisites and outgoing continuations with arrowheads;
- hard prerequisites use solid lines;
- approved soft support uses dashed lines;
- unrelated edges fade while a node is selected;
- `查看完整路径` may expand two or three dependency hops;
- the map legend explains line meanings in child language.

## Node Selection Detail

Selecting a node opens a detail panel containing:

- knowledge-point name and current state;
- one-sentence essence from external knowledge content/graph teaching contract;
- learning progress;
- mastery state and evidence summary in child language;
- prerequisite names and states;
- immediately unlocked or supported next nodes;
- one primary action and one context-appropriate secondary action.

Actions by state:

| State | Primary | Secondary |
|---|---|---|
| untested | `先检测一下` | `开始学习` |
| learning | `继续学习` | `回到当前任务` when applicable |
| weak | `针对性学习` | `再检测一次` only when runtime allows |
| mastered_for_now | `挑战一下` | `复习这个点` |
| prerequisite_not_ready | `先补准备知识` | `先看看这个知识点` |

The secondary preview action may show reviewed teaching content but cannot produce mastery without evidence.

## Autonomous Choice and Runtime Safety

The child can select any visible node. Runtime behavior is explicit:

1. validate the transport-only opaque node handle against the current graph version, then store canonical internal node id plus graph version;
2. inspect current flow state and prerequisite evidence;
3. if prerequisites are usable, materialize learning or diagnostic entry for the chosen node;
4. if prerequisites are uncertain/weak, preserve the target intent and offer a prerequisite probe or repair path;
5. after prerequisite repair, return to the originally selected node unless the child changes the target;
6. if evidence/model/runtime is unavailable, stop honestly without inventing progress.

The system may display `系统建议` on one or more nodes, but a recommendation is not an automatic selection.

### Target Intent State Machine

`learning_target_intents` is the persistence owner for autonomous choice.

Required fields:

- id, child key, graph version, canonical node id;
- action: `diagnostic`, `learn`, `review`, or `challenge`;
- optional source flow id/revision and source visible-step id; these are null when selection starts from map home without an existing flow;
- client idempotency key;
- status: `pending`, `waiting_for_safe_boundary`, `applied`, `cancelled`, `stale`, or `blocked`;
- applied flow/step ids, reason, created/updated timestamps.

Uniqueness is enforced by child key, graph version, and client idempotency key. The idempotency row also stores a digest of node id plus action. Reusing one key with different payload is rejected.

Creating a new nonduplicate intent atomically cancels older `pending` or `waiting_for_safe_boundary` intents for the same child/graph version before the new intent becomes eligible. At most one nonterminal mutating target intent exists per child and graph version.

Precedence rules:

1. The answer reducer always finishes persisting a submitted attempt and accepted assessment.
2. Before materializing its normal next action, it checks the newest valid pending target intent in the same reducer transaction.
   The lookup includes both `pending` and `waiting_for_safe_boundary` statuses.
3. A valid target intent wins over materializing a new planner-selected step, but never cancels the just-finished assessment/mastery update.
4. Unanswered selected/displayed steps can be superseded immediately after the child's explicit switch choice.
5. Running/queued answer analysis waits for reducer completion.
6. `clarify_evidence` is a stable safe boundary: switching may pause the unresolved clarification, preserve all evidence, and apply the new target immediately.
7. A target cannot remain waiting after its source flow reaches a safe boundary; recovery applies or explicitly blocks/stales it.
8. Graph-version mismatch or tampered handle rejects the request before intent creation.

`preview` is not a target intent and never enters this state machine. It is a read-only node-content projection with no flow, step, evidence, or reducer effect.

## Active-Flow Switching

The map remains browsable while a learning flow exists.

- If there is an unanswered selected step, the child sees `继续当前学习` and may browse nodes without destroying it.
- Choosing another node creates a pending target intent and asks for one explicit low-input choice: continue current step or save current progress and switch at a safe boundary.
- During submission, model analysis, or reducer commit, switching is queued and cannot interrupt the transaction. Clarification is handled as the explicit stable-boundary case defined above.
- After the safe boundary, runtime supersedes only unconsumed steps and materializes the selected target.
- Submitted attempts and accepted assessments are never deleted by navigation.

## Child-Safe Graph Projection

The Web API returns opaque handles and child-readable fields only. Handles are transport projections, never stored as graph lineage.

Top-level projection:

```json
{
  "graph_version_label": "暑假数学衔接",
  "layout_version": "knowledge-map-layout.v1",
  "modules": [],
  "nodes": [],
  "edges": [],
  "current_learning": {},
  "recommended_handles": []
}
```

Node projection fields:

- `handle`;
- `name`;
- `module_handle`;
- `state_label`;
- `learning_stage_count` and `learning_stage_total`;
- `mastery_band` and child-safe summary;
- `position`;
- allowed actions.

Edge projection fields:

- source and target opaque handles;
- `relationship`: `hard_prerequisite` or `soft_support`;
- child-safe label;
- visibility level.

Forbidden fields include raw node ids, thresholds, status codes, assessment ids, model/provider data, rubric content, queue/job state, and internal error tags.

Handle rules:

- generated from canonical node id plus pinned graph version and handle-policy version;
- constructed with versioned HMAC using a local installation secret stored outside child payloads, rather than a reversible/plain digest;
- resolved and validated server-side before any mutation;
- stale graph-version handles return child-safe conflict/reload behavior;
- unknown/tampered handles create no target intent;
- SQLite rows store canonical node id and graph version only.

## Storage Boundaries

Knowledge content, graph structure, learning progress, and mastery remain separate:

- graph JSON/graph runtime owns nodes and canonical relationships;
- external knowledge-content storage owns explanations and examples;
- question bank and answer contracts own assessment content;
- existing `flow_steps`, `teaching_step_events`, and immutable attempts own completed learning-activity evidence;
- assessments/mastery tables own evidence and node state;
- layout projection owns coordinates only;
- local browser storage may own viewport preference only.

No progress or mastery field is written into the graph source file.

## Action Asset Eligibility

The detail panel exposes only actions that can complete safely:

- `diagnostic`: at least one active reviewed question with an approved answer contract;
- `learn`: reviewed essence/core-model/worked-example content plus active contract-backed micro-check, standard, and variant questions, with reviewed repair/summary fallback available if evidence is weak or the session stops safely;
- `review`: active reviewed question and contract appropriate to the node's current evidence need;
- `challenge`: active reviewed transfer/stretch question and contract, with prerequisite policy satisfied;
- `preview`: reviewed teaching content only; creates no learning activity completion, attempt, score, or mastery evidence.

If the complete asset chain is missing, the action is disabled with child-safe wording. The runtime never starts teaching that is guaranteed to dead-end before a valid evidence question.

Asset eligibility is checked both when projecting actions and again transactionally when applying a target intent. A stale action cannot start from an outdated map payload.

## Magic Workflow Lessons Applied

The Magic deep-research/workflow design contributes four patterns:

- explicit stage contracts before execution;
- traceable evidence for every conclusion;
- stop/fail-closed behavior when a stage cannot produce trustworthy output;
- low-input choices that let the user start with one click while retaining control.

These patterns shape target selection and runtime handoff. Magic product code is not copied and does not become a dependency.

## Failure and Recovery

- Graph unavailable or version mismatch: show honest unavailable state and preserve current learning flow.
- Node lacks reviewed content: allow diagnostic only when an active reviewed question exists; otherwise label the node temporarily unavailable.
- Node has no active question contract: do not start a diagnostic that cannot be scored safely.
- Progress projection stale: show last verified state with refresh label; do not claim new mastery.
- Selection double-click/retry: idempotently reuse the same target intent.
- Service restart: restore active flow, pending target intent, and child-safe map state from SQLite.
- Layout rendering failure: fall back to module/node list with the same selection actions.

## Acceptance Criteria

- Home page renders all 56 current graph nodes and all nine modules.
- Fit-all, continuous zoom, drag, module focus, search, filters, node focus, close detail, and minimap work on desktop.
- Mobile provides the same graph and node actions with a bottom detail sheet and no text overlap.
- Node selection visibly distinguishes learning progress from mastery.
- Nodes without evidence display `未测试`, not weak/mastered.
- Selected-node view shows directional hard-prerequisite and soft-support relationships without duplicate inverse edges.
- Selected-node view always shows directional hard prerequisites and shows any approved soft supports; zero approved soft supports is a valid initial release state and the soft-support legend is then hidden.
- Child can choose a nonrecommended node.
- Weak prerequisites preserve the chosen target and route through a probe/repair before returning.
- Switching cannot interrupt an active submission/analysis transaction or delete evidence.
- Starting a diagnostic requires an approved question and answer contract.
- Child payload/DOM contains no raw graph ids or other forbidden internal fields.
- Keyboard users can focus and select every visible node.
- Stale or tampered node handles create no intent and return child-safe recovery.
- Reducer-versus-switch races preserve the submitted assessment and apply the selected target exactly once.
- Reciprocal unlock-only candidates never render as duplicate opposing arrows.
- Learning-activity projection recomputes from existing events/attempts without claiming understanding.
- Browser tests cover 56-node rendering, node zoom/focus, autonomous selection, prerequisite repair, active-flow switching, restart, and stale projection.

## Performance and Fallback Budget

- Initial map payload target: at most 250 KB uncompressed for the current 56-node graph.
- DOM target: 56 accessible node buttons, nine module regions, and only the relationship paths allowed by the current visibility mode.
- Fit-all and node-focus interaction should respond within 100 ms after payload load on the local machine.
- At 390px, node labels, controls, and the bottom detail sheet must not overlap.
- If transformed-map rendering fails, an accessible module-grouped node list with the same actions remains usable.

Benchmark method:

- run against the local Python service on the project machine with the current pinned 56-node graph;
- measure projection byte length before HTTP compression and server serialization with a monotonic timer over at least 20 warm runs;
- measure client fit-all, node-focus, search, and filter actions after payload load through browser performance marks over at least 20 actions;
- verify desktop at the current in-app browser viewport and mobile at 390x844;
- report median and worst observed values alongside the 250 KB and 100 ms targets.

## Implementation Phases and Gates

### Phase 0: Authority Amendments

- Update PRD/UX/engineering contracts with `map_home` and target-intent ownership.
- Gate: no conflicting first-viewport or switching authority remains.

### Phase 1: Read-Only Projection

- Implement opaque handles, stable layout, activity/mastery projection, canonical hard edges, payload budget, and list fallback.
- Gate: no mutation endpoint; child-safe and exact-count tests pass.

### Phase 2: Target Intent Runtime

- Add intent persistence, idempotency, safe-boundary reducer precedence, restart recovery, and asset eligibility.
- Gate: race, stale/tampered handle, clarification switch, and open-flow tests pass.

### Phase 3: Map UI

- Make `map_home` the initial surface and connect zoom/pan/search/filter/focus/detail/actions to real projections.
- Gate: desktop, 390px, keyboard, fallback, and current-step resume tests pass.

### Phase 4: Atomic Activation

- Verify all active node actions have complete assets, all consumers use the new state contract, and preactivation flows have a migration outcome.
- Activate by one feature/policy version; do not mix first-viewport policies inside one flow revision.
- Gate: full browser regression plus answer-assessment integration passes before default activation.

## Implementation Boundary

This feature reuses the existing graph JSON, graph runtime, SQLite learner state, current-step runtime, and single child Web page. It adds a child-safe map projection, stable layout service, target-intent handoff, and map UI. It does not introduce a parent Web page, graph editor, or second learning runtime.
