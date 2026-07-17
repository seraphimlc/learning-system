# Child Knowledge Home Delivery Repair Contract v5.1

Status: `UX_REPAIR_READY_FOR_IMPLEMENTATION`

Owner: 清秋 (`qingqiu`)

Date: 2026-07-16 CST

Implementer: 听云

## Purpose And Precedence

This contract closes three delivery gaps in the v5.1 child knowledge home:

1. `继续当前学习` can expose an unmaterialized blank learning form.
2. Node actions are rendered from unordered action codes instead of final
   child-safe state semantics.
3. The 390px graph overview contains no visible node names.

This is a repair overlay, not a new product version. For the three topics above,
this document overrides conflicting details in:

- `docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md`;
- `docs/product/child_ui_dual_knowledge_views_implementation_package_v5_1.md`.

All other v5.1 behavior remains unchanged, including graph truth, target-intent
idempotency, assessment authority, focused learning states, two-view shared
selection, local viewport memory, and child-safe data boundaries.

## Non-Goals

- No new learning mode, recommendation system, account model, or parent surface.
- No new graph relation type and no rewrite of the 56-node knowledge graph.
- No change to assessment, mastery, planning, or prerequisite business rules.
- No automatic learning launch from node selection or view switching.
- No attempt to show all 56 graph node labels at fit-all.

## Shared Delivery Invariants

- `map_home` and `learning_step` remain mutually exclusive sibling surfaces.
- A hidden surface is both `hidden` and `inert` and has zero tabbable descendants.
- The learning surface is never revealed until a valid child bootstrap payload
  has been rendered into it.
- A node selection opens detail only. It creates no target intent or evidence.
- Server projection supplies final child-visible action meaning. The frontend
  does not infer labels, priority, readiness, or result behavior from action code.
- At 390x844, every path used to choose a node by meaning exposes readable text;
  unlabeled orientation markers are not controls.

## Repair 1: Materialized Resume Before Surface Switch

### Root Decision

`继续当前学习` is an asynchronous materialization command, not a navigation
toggle. The map remains visible while the application obtains and renders the
authoritative `/api/child-bootstrap` payload. Only a successful, valid render may
switch to `learning_step`.

The existing `not_started` rule remains:

- when `current_learning.state` is `not_started`, remove the banner row and do
  not render a resume control;
- all other supported current-learning states render one status message and one
  open-current action.

### Trigger Conditions

The repair applies when any of these events requests the focused learning
surface from `map_home`:

- child activates the current-learning banner action;
- a node target POST returns `status: applied`;
- a waiting target becomes applied and the child has explicitly chosen to enter;
- a blocked/retry or summary action opens its existing focused state.

Direct use of `setPrimarySurface("learning_step")` before successful payload
rendering is forbidden.

### Minimum Map API Semantics

`GET /api/knowledge-map` keeps `current_learning`, but it must expose final
child-safe map-home semantics:

```json
{
  "current_learning": {
    "state": "not_started|start_resume|current_step|analyzing_pending|feedback_teaching|clarify_evidence|ready_for_new_knowledge|blocked|summary",
    "topic_label": "孩子可读主题；没有时为空字符串",
    "label": "地图首页状态句",
    "action_label": "按钮文案；not_started 时为空字符串",
    "pending_label": "点击后等待 child bootstrap 时的按钮文案"
  }
}
```

Rules:

- These are child-safe display fields, not internal flow, step, queue, or job
  state.
- `state` must use the canonical v5 child-state meaning above. Raw daily-flow
  status such as `new`, `reviewing`, or `learning_new` is not a map DTO value.
- `topic_label` may use `/api/child-bootstrap.current_step.topic_label` when a
  current step exists. Do not invent a topic when it does not.
- `action_label` and `pending_label` are final copy. The frontend does not map
  them from `state`.

`GET /api/child-bootstrap` remains the only authority for the focused learning
content. No second focused-learning DTO is introduced.

### Required Child Copy

| State | `label` | `action_label` | `pending_label` |
|---|---|---|---|
| `not_started` | `可以先看看自己的数学知识。` | empty | empty |
| `start_resume` | `今天的学习可以开始了。` | `开始今天学习` | `正在打开` |
| `current_step` | `“{topic_label}”还可以继续。` | `继续当前学习` | `正在打开` |
| `analyzing_pending` | `刚才的答案已经保存，正在批阅。` | `查看当前进度` | `正在打开进度` |
| `feedback_teaching` | `“{topic_label}”还有下一步。` | `继续当前学习` | `正在打开` |
| `clarify_evidence` | `刚才的答案还需要补清楚一点。` | `继续补充` | `正在打开` |
| `ready_for_new_knowledge` | `旧知识复习暂时告一段落。` | `学一个新知识` | `正在准备` |
| `blocked` | `刚才的学习已经保存，可以查看恢复方式。` | `查看恢复方式` | `正在打开` |
| `summary` | `今天的学习已经完成。` | `查看今天总结` | `正在打开` |

If `topic_label` is empty, remove the Chinese quotation marks and use
`当前学习还可以继续。` or `当前学习还有下一步。`.

### Loading State

After activation and before bootstrap success:

- keep `map_home` visible, enabled for nonmutating browsing, and in its current
  camera position;
- disable only the activated current-learning action;
- replace its label with `pending_label` and set `aria-busy="true"` on the
  current-learning status region;
- do not expose the answer field, Save button, photo control, or any static
  `准备中` learning shell;
- ignore repeated activation while the same request is in flight.

### Success State

On a successful child-bootstrap response:

1. Validate the payload against the existing child DTO contract.
2. Render the exact current focused state while `learning_step` remains hidden
   and inert.
3. Confirm that the rendered state has its required heading and state-appropriate
   controls. An answer input is allowed only when the payload permits an answer.
4. Hide and inert `map_home`.
5. Reveal and uninert `learning_step`.
6. Move focus to the focused-state heading or its one required primary action.

The transient headings `准备中` and `当前任务` are not valid success evidence.

### Failure And Recovery

If child bootstrap fails, is malformed, or cannot render:

- remain on `map_home`; do not reveal any part of `learning_step`;
- restore the action label and enabled state;
- show an adjacent focusable error:
  `当前学习暂时没有打开，刚才的内容还在。可以再试一次。`;
- provide one `再试一次` button that repeats the same bootstrap operation;
- keep search, filters, view switch, pan, zoom, and read-only node detail usable;
- disable mutating node actions until current-learning authority is known again.

If the map projection fails but child bootstrap succeeds, keep the existing map
unavailable surface and allow the current-learning action to use the same
materialize-before-switch sequence.

### Mobile Behavior

- The current-learning banner stays above the view switch and remains at least
  44px high.
- Loading and error copy may wrap to two lines; the action remains full-width
  when a side-by-side layout would make it narrower than 120px.
- The document does not jump to the hidden learning form while loading.
- On success, focus enters the rendered focused state; browser Back or the
  existing explicit return action restores map mode, selection, and viewport.

### Resume Acceptance Steps

1. `not_started`: cold-load `/`, assert no current-learning button and no blank
   banner gap.
2. `current_step`: cold-load map home, activate `继续当前学习`, assert the map
   remains visible while `/api/child-bootstrap` is pending, then assert the real
   prompt/topic is visible before the learning surface becomes interactive.
3. `analyzing_pending`: assert map copy begins with `刚才的答案已经保存`; activate
   `查看当前进度`; assert analyzing/status content appears and no answer input is
   enabled.
4. Bootstrap failure: return 500 or malformed JSON, activate the banner action,
   assert the map remains usable, `learning_step` stays hidden/inert, and
   `再试一次` is available.
5. Retry success: retry from the same map state, assert one bootstrap request is
   accepted and one focused surface is rendered; no duplicate Save action or
   duplicate current step appears.
6. At 390x844 repeat steps 2-5 and assert no document horizontal scroll, no
   focus landing in hidden content, and no visible `准备中` answer form.

## Repair 2: Server-Owned Action Descriptors And State Meaning

### Root Decision

`allowed_actions: [code]` is insufficient for child UI. Every node must provide
ordered descriptors containing the final label, role, enabled state, reason,
pending copy, and result behavior. The frontend renders these fields exactly and
does not maintain a second action-label dictionary.

### Trigger Conditions

The repair applies whenever node detail is rendered or refreshed after:

- node selection;
- view switch with a selected node;
- learner-state or asset-readiness refresh;
- current-learning state change;
- stale projection recovery;
- completion of a node-action request.

### Minimum Node API Semantics

Each `/api/knowledge-map.nodes[]` item must contain:

```json
{
  "evidence_state": {
    "code": "untested|developing|needs_support|stable",
    "label": "未测试|学习中|待巩固|暂时掌握"
  },
  "activity": {
    "completed": 0,
    "total": 4,
    "label": "学习历程，完成 0/4"
  },
  "mastery_summary": "孩子可读证据摘要",
  "action_readiness": {
    "code": "ready|needs_prerequisite|content_unavailable|assessment_unavailable|wait_for_current",
    "label": "孩子可读短标签",
    "reason": "孩子可读解释；ready 时可为空"
  },
  "action_descriptors": [
    {
      "action": "diagnostic|learn|review|challenge|preview",
      "label": "最终按钮文案",
      "role": "primary|secondary",
      "enabled": true,
      "disabled_reason": "禁用时必填，否则为空",
      "pending_label": "请求进行中的按钮文案",
      "result_behavior": "enter_now|wait_for_safe_boundary|preview"
    }
  ]
}
```

Rules:

- At most one descriptor has `role: primary`.
- At most one enabled command secondary is visible with the primary.
- Descriptor order is render order.
- A disabled visible descriptor has a nonempty `disabled_reason`.
- `action_readiness` is separate from `evidence_state`; readiness never replaces
  the evidence label.
- `preview` is emitted only when reviewed preview content and an existing safe
  preview path are available. This contract does not create a new content API.
- Existing opaque handle, projection version, and idempotency semantics remain.
- `allowed_actions` may remain temporarily for compatibility, but child UI must
  use only `action_descriptors` once this repair is enabled.

### Required State Semantics

| Evidence/readiness | Primary | Optional secondary | Required notice |
|---|---|---|---|
| `untested` + `ready` | `先检测一下` (`diagnostic`) | `开始学习` (`learn`) | none |
| `developing` + `ready` | `继续学习` (`learn`) | server may emit one valid diagnostic/review command | none |
| `needs_support` + `ready` | `针对性学习` (`learn`) | `再检测一次` only when assessment assets are ready | none |
| `stable` + `ready` | `挑战一下` (`challenge`) | `复习这个点` (`review`) | none |
| any evidence + `needs_prerequisite` | `先补准备知识` using the existing prerequisite-repair learning path | `先看看这个知识点` only when preview exists | `需要先准备` plus the child-safe reason |
| any evidence + `content_unavailable` | preferred learning command remains visible but disabled | preview only when available | `这个知识点的学习内容还在准备，暂时不能开始。` |
| any evidence + `assessment_unavailable` | preferred diagnostic command remains visible but disabled | valid learning/preview command when available | `这个知识点的小检测还在准备。` |
| any evidence + `wait_for_current` | server-selected target command | none unless an existing cancel/preview command is valid | `当前学习结束后可以切换到这里。` |

The server omits a secondary action when it cannot prove that the action is
currently safe. The frontend never fills the empty slot with another action.

### Detail Content And Control Order

The shared detail surface renders this exact order:

1. Node name and evidence-state label.
2. Optional readiness/current-learning notice.
3. One-sentence essence when reviewed content exists.
4. `学习历程` with four segments and `x/4` text.
5. `掌握情况` using `mastery_summary`, without percentages.
6. `需要先会` relation list.
7. `后面会用到` relation list.
8. Adjacent disabled, pending, blocked, or recovery message when present.
9. Sticky action area with one primary and at most one command secondary.

No action is hidden merely because it is disabled when hiding it would make the
state confusing. Show the disabled preferred action and its reason.

### Action Loading State

After an enabled mutating descriptor is activated:

- disable every mutating descriptor in the open detail;
- replace the activated button label with `pending_label`;
- keep node name, evidence, readiness, activity, mastery, and relations visible;
- set a polite adjacent status message, not a global toast alone;
- do not switch surfaces until an `enter_now` result has been materialized using
  Repair 1.

### Result States

| API result | Child surface | Required behavior |
|---|---|---|
| `applied` + `enter_now` | Remain on map during bootstrap, then focused learning | Use Repair 1; never expose blank shell |
| `waiting_for_safe_boundary` | Stay on map | Show `已经记住“{知识点名称}”，当前学习结束后会切换到这里。` |
| `blocked` | Stay in detail | Keep evidence and relations; show the returned child-safe reason and re-enable only valid descriptors |
| `preview` | Existing read-only preview | Create no target intent, progress, attempt, or mastery evidence |
| stale/conflict | Read-only map refresh state | Preserve current learning and selection when continuity is valid; old descriptor cannot be retried |
| response unknown/network loss | Stay in detail | Preserve the idempotency key and show `连接中断了，刚才的选择已经保留。再次点击会继续确认。` |

For response-unknown recovery, the button label is `再次确认`; activation reuses
the same handle, action, projection version, and client idempotency key.

### Mobile Behavior

- Detail remains the existing modal bottom sheet.
- Evidence, readiness, activity, mastery, and relation text scroll in one body.
- Header and action area remain sticky.
- Primary and secondary command buttons are full-width and at least 48px/44px.
- Long action labels wrap to two lines; they are not clipped or shrunk.
- A disabled reason appears immediately above the action area and remains visible
  when its disabled button is visible.

### Action Acceptance Steps

1. Open an `untested + ready` node; assert exactly one primary `先检测一下` and
   one secondary `开始学习`, followed in server order.
2. Open a `needs_prerequisite` node; assert evidence state remains its original
   value, readiness says `需要先准备`, primary says `先补准备知识`, and generic
   `做个小检测 / 开始学习 / 再复习一次` is not synthesized.
3. Open a node with missing reviewed content; assert the preferred action is
   visibly disabled, the exact preparation reason is adjacent, and activation
   produces zero POST requests.
4. Verify `学习历程 x/4` and `掌握情况` render from API fields and do not imply
   mastery through activity completion.
5. Return `waiting_for_safe_boundary`; assert the map remains active and the
   selected target is named in status.
6. Return `applied`; assert bootstrap finishes and real focused content renders
   before the surface switch.
7. Simulate network loss and retry; assert the same idempotency key is reused and
   no second target intent is created.
8. Repeat steps 1-7 at 390x844; assert sticky actions remain reachable, reasons
   are not covered, and the sheet does not leak pan gestures to the map.

## Repair 3: Readable 390px Graph Overview And Meaningful Entry

### Root Decision

At 390px, graph `fit_all` is an orientation surface. It may use unlabeled markers
for most nodes, but it must show a small reviewed set of visible node-name anchors
and a clear text route into `module_focus` or `node_focus`. Unlabeled markers are
not buttons and cannot be the child's only node-selection method.

### Trigger Conditions

The repair applies when:

- active view is `graph`;
- viewport width is 390px or any supported width at or below 700px;
- graph focus mode is `fit_all`;
- no detail sheet is open.

### Minimum Graph API Semantics

Each graph placement may add presentation-only metadata:

```json
{
  "handle": "opaque handle",
  "rank": 0,
  "lane_handle": "opaque lane handle",
  "order": 0,
  "overview_label_priority": 1
}
```

Rules:

- `overview_label_priority` is an integer `1..6` or absent.
- Exactly three to six placements have a priority in one valid projection.
- Priorities are unique.
- Labeled anchors lie on the reviewed overview backbone and collectively include
  an early prerequisite, a middle convergence/bridge point, and a downstream
  point.
- This metadata is presentation only. It is never learning evidence, planning
  input, recommendation, or mastery state.
- The frontend never chooses anchor nodes from array order, degree, status, or
  recommendation when reviewed priorities are absent.
- If valid anchors are absent, show the grouped/module-focus entry instead of an
  unlabeled interactive marker field; do not invent anchors locally.

For the current v5.1 graph lineage, the reviewed anchor set is fixed:

| Priority | Canonical node id | Child-visible name | Orientation purpose |
|---:|---|---|---|
| 1 | `M-PRE-NUMBER-SENSE` | `数感与估算` | earliest shared prerequisite |
| 2 | `M-PRE-QUANTITY-RELATION` | `等量关系与列式` | arithmetic-to-algebra bridge |
| 3 | `M-G7-RATIONAL-ADD-SUB` | `有理数加减` | central rational-number progression |
| 4 | `M-G7-COMBINE-LIKE` | `合并同类项` | expression progression |
| 5 | `M-G7-EQ-SOLVE` | `解一元一次方程基础` | equation-solving convergence |
| 6 | `M-G7-EQ-WORD` | `一元一次方程应用题` | downstream application convergence |

The canonical ids remain configuration/server data and must not appear in the
child DTO, DOM text, accessible name, screenshot, or browser storage. A future
graph lineage requires a reviewed replacement set; 听云 must not carry these
priorities forward by name matching or degree heuristics.

### Fit-All Visual Contract At 390x844

- Represent all 56 nodes and the existing directed overview backbone.
- Keep arrowheads visible from prerequisite toward downstream knowledge.
- Render ordinary markers at 14-22px screen-space and `aria-hidden="true"`.
- Ordinary markers are `span`/decorative elements, not buttons, and do not enter
  the Tab sequence.
- Render three to six reviewed anchor labels in priority order.
- Anchor text is the full child-readable node name, at least 14px screen-space,
  maximum two lines, with a quiet connector to its marker.
- Anchor labels are orientation text, not direct learning commands. Search,
  module focus, and readable full-node controls perform selection.
- Lane/module labels remain fixed in screen space at at least 12px; camera scale
  must not reduce them.
- Labels, arrowheads, and the active toolbar must not overlap incoherently.
- The module control's unselected text is `选择知识模块`, not only `全部模块`.
- Search remains visible with placeholder `输入知识名称`.

### Entry Interaction

| Child action | Result |
|---|---|
| Switches to `图谱` | Restore graph camera; show fit-all anchors and announce `已打开知识图谱。可以搜索或选择知识模块查看知识点。` |
| Selects a module | Enter `module_focus`; fit that lane plus immediate bridge context; render every focused module node as a readable control |
| Chooses a search result | Enter `node_focus`; center the exact node; render selected node and complete one-hop neighbors as readable controls |
| Activates Fit | Return to fit-all anchors; clear only graph focus mode, not query, filter, shared selection, or detail state |
| Activates Focus Selected | Enter `node_focus` for the shared selected node; if no selection, leave the camera unchanged and announce `还没有选择知识点` |

In `module_focus` and `node_focus`:

- full node labels are at least 15px at 390px;
- each node control is at least 44x44px;
- tapping or pressing Enter/Space opens the existing shared detail sheet;
- relation direction remains visible in arrows and repeated in detail text;
- closing detail restores the exact originating full node and camera.

### Loading, Failure, And Recovery

- While graph layout is pending, reserve the viewport and show
  `正在打开知识图谱。`; do not show fake labels.
- If anchor metadata is invalid but graph/module data is valid, open a
  module-grouped readable entry with `选择一个知识模块查看知识点。`; keep the view
  switch, search, and module control usable.
- If graph spatial rendering fails, use the existing grouped node fallback and
  copy `图形暂时没有显示出来，先用知识点列表继续查看。`.
- Retry restores the same shared selection, search, filter, and graph viewport
  when compatible.
- A graph failure never removes or corrupts current learning.

### Mobile Graph Acceptance Steps

1. At 390x844 open `图谱` in fit-all; assert 56 nodes are represented, the
   direction backbone and arrowheads are visible, and three to six full node
   names are visibly rendered at >=14px.
2. Assert ordinary markers contain no visible or accessible command name, are
   noninteractive, and have zero Tab stops.
3. Assert lane labels are >=12px screen-space and remain readable at the fitted
   camera scale.
4. Assert the visible module control says `选择知识模块`; select one module and
   verify every focused module node has a >=15px name and >=44px target.
5. Search an exact node name; choose the result; verify node focus, one-hop
   labels, direction arrows, and shared detail all refer to the same handle.
6. Open and close the mobile detail sheet; assert at least 112px map context
   remains when allowed, background is inert, and focus/camera return exactly.
7. Test malformed/missing anchor metadata; assert the readable grouped/module
   entry appears and no unlabeled marker becomes a button.
8. Repeat with browser text enlargement; assert anchor/module/node labels wrap,
   no document horizontal scroll appears, and no control overlaps the graph.

## Cross-Repair Acceptance Matrix

| Scenario | Must remain on map | May enter focused learning | Required evidence |
|---|---:|---:|---|
| Resume bootstrap loading | yes | no | pending button, hidden/inert learning surface |
| Resume bootstrap failure | yes | no | adjacent error and retry, map browsing intact |
| Resume bootstrap success | no after render | yes | real heading/content before focus enters |
| Disabled node action | yes | no | disabled reason and zero POST |
| Waiting target | yes | no | named target and saved-current reassurance |
| Applied node action | yes during bootstrap | yes after render | Repair 1 sequence |
| Mobile graph fit-all | yes | no | readable anchors plus module/search entry |
| Mobile graph node focus | yes | no | readable full node controls and shared detail |

## Forbidden Implementations

- Switching to `learning_step` and then fetching/bootstrap-rendering.
- Leaving an enabled blank answer form behind a generic `准备中` heading.
- Frontend dictionaries that turn action codes into labels or choose the primary.
- Rendering all returned action codes as enabled buttons.
- Replacing evidence state with readiness state.
- Using only toast feedback for action failure or pending state.
- Making all 56 mobile overview markers buttons with names available only through
  `title` or `aria-label`.
- Scaling lane or anchor text with the graph camera below the specified size.
- Choosing overview label anchors from incidental array order or graph degree.
- Treating graph view failure as permission to lose current learning or shared
  selection.

## Definition Of Done

This repair is implementation-complete only when all three repair acceptance
sets pass with production routes and an isolated copied database:

- no resume path exposes a blank or stale focused form;
- every visible node action is server-ordered, state-appropriate, and honestly
  enabled or disabled;
- a child at 390px can understand the graph's direction and reach a named node
  through visible text without random marker tapping;
- existing view switching, shared selection, viewport memory, target idempotency,
  and focused learning behavior remain intact;
- screenshot and DOM evidence covers 1280x800 and 390x844 success, loading,
  failure, and recovery states described above.
