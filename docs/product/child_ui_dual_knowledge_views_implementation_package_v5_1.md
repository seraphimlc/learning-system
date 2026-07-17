# Child UI Dual Knowledge Views Implementation Package v5.1

Status: `UX_FLOW_READY_FOR_IMPLEMENTATION`

Owner: 清秋 (`qingqiu`)

Date: 2026-07-15 CST

Delivery repair overlay: for resume materialization, server-owned node action
descriptors, and readable 390px graph overview behavior, implementation must
follow `docs/product/child_knowledge_home_delivery_repair_contract_v5_1.md`.
That overlay takes precedence for those three topics.

This durable package translates the approved v5.1 child UX into concrete
frontend component, DOM/ARIA, visual-token, layout, interaction, performance,
and screenshot acceptance contracts. It is implementation guidance, not
production code, rendered evidence, QA approval, or activation permission.

## Entry Lock

- request_type: `ux_flow_spec` implementation visual package
- current_role_authority: owned by 清秋 (`qingqiu`)
- selected_playbook_or_skill:
  - `docs/collaboration/playbooks/ux-review.md`
  - `ui-ux-pro-max`
- source_pins:
  - `AGENTS.md`: `84c38b14`
  - `docs/collaboration/roles/qingqiu.md`: `a30b4184`
  - `docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md`: `81fb3bd9`
  - `docs/architecture/dual_knowledge_views_engineering_contract_v5_1.md`: `45efa394`
  - `app/local_learning_system/index.html`: `911c792e`
  - `app/local_learning_system/app.js`: `6c69e3eb`
  - `app/local_learning_system/styles.css`: `6dfc1e90`
  - `.superpowers/brainstorm/2026-07-14-knowledge-map/knowledge-map-full-canvas-v2.html`: `63c90e42`
  - `.superpowers/brainstorm/2026-07-14-knowledge-map/knowledge-map-layouts.html`: `bce15682`
- project_boundary_overlay:
  - one child, mathematics first, child-safe single Web page;
  - no parent Web, no graph editor, no internal ids or model/runtime data;
  - answer assessment activation precedes enabled diagnostic/learning actions;
  - real browser desktop/390px evidence remains mandatory.
- output_target:
  - `docs/product/child_ui_dual_knowledge_views_implementation_package_v5_1.md`
- forbidden_scope:
  - no HTML, JavaScript, CSS, Python, DB, config, test, or production edits;
  - no graph-source rewrite;
  - no new product behavior beyond the approved UX amendment.
- stop_condition: publish and self-check this package, then return to 若命 for engineering consumption

## Objective

Give 听云 a decision-complete frontend package for one child page with:

- a mind-map projection for hierarchy and scope;
- a directed graph projection for prerequisite depth, convergence, and bridges;
- shared node selection, detail, search, filters, current-learning state, and
  target actions;
- separate focused learning and exact five-field per-question feedback states;
- deterministic desktop and 390px behavior;
- accessible keyboard, touch, focus, reduced-motion, and fallback paths;
- bounded performance for all 56 nodes and 95 strict prerequisite relations.

## Implementation Decision Lock

This section is the authoritative UI acceptance freeze for implementation. If a
later section gives a range or illustrative option, this section wins. Listening
engineer 听云 must not choose a different layout, collapse rule, visual encoding,
or interaction model without a new UX decision.

### Exact Responsive Geometry

The map home is a full-width work surface, not a centered card. The existing
focused learning surface keeps its current readable width and appears only after
a node action starts.

| Dimension | 1280x800 desktop | 390x844 mobile |
|---|---:|---:|
| Page inset | 16px horizontal, 12px vertical | 12px plus safe-area insets |
| Header | 56px | 52px |
| Current-learning banner | 48px when present; remove the row when absent | 48px when present; remove the row when absent |
| Vertical gap between chrome rows | 8px | 8px |
| View switch | 176x44px; two 88px segments | 366x44px; two equal segments |
| Search | 280px minimum, 360px preferred, 44px high | Search fills remaining width beside one 44px filter button |
| Desktop filter group | 332x44px for four equal exclusive controls | Opens from the 44px filter button; no four-pill row |
| Viewport toolbar | Five 44px buttons, 4px internal gaps | Four 44px buttons with 8px gaps: zoom out, zoom in, fit, focus selected |
| Module index | One 48px row, nine equal columns, 4px gaps | One 44px `选择知识模块` menu button; no nine-tab grid |
| Projection viewport | Remaining height; at least 520px with banner and 568px without | At least 420px; at 390x844 target 520-548px when detail is closed |
| Detail | In-flow right column, 320px wide, 12px gap | Modal bottom sheet, full width, max `min(68dvh, 100dvh - 112px)` |
| Detail/map relationship | Detail never covers the projection | At least 112px of map remains visible unless text enlargement requires full-height sheet |

Desktop chrome order is fixed:

1. `AppHeader`.
2. Optional `CurrentLearningBanner`.
3. One primary control row: view switch, search, exclusive filter group, viewport toolbar.
4. One nine-module index row.
5. Projection workspace with optional in-flow detail column.

Mobile chrome order is fixed:

1. `AppHeader`.
2. Optional `CurrentLearningBanner`.
3. Full-width `导图 / 图谱` switch.
4. Search plus filter button.
5. Module menu plus viewport toolbar.
6. Projection viewport.
7. Modal detail sheet only after selection.

No control row wraps. When text enlargement prevents the exact row from fitting,
the filter and module controls remain menu buttons and toolbar overflow moves into
one labeled `更多视图工具` menu; node labels and primary actions never shrink.

### Stable Component Sizes

| Element | Desktop | 390px | Contract |
|---|---:|---:|---|
| Virtual root | 184x48px | 156x48px | Full label, one hierarchy icon, never a learning action |
| Module control | 168x48px | 156x48px | Maximum two lines; branch state shown with chevron and `aria-expanded` |
| Full node control | 176px wide, 64px minimum height | 164px wide, 64px minimum height | Maximum two name lines; height may grow, width may not |
| Overview marker | 18x18px screen-space | 14x14px screen-space | Noninteractive; selected/current marker may grow to 28x28px with one label callout |
| Detail close | 44x44px | 44x44px | Familiar X icon, accessible name `关闭知识点详情` |
| Primary action | 44px minimum height | 48px minimum height, full width | One primary only |
| Secondary command | 44px minimum height | 44px minimum height, full width when shown | At most one command secondary |

Full node controls keep fixed screen-space typography and hit areas. Camera zoom
must not make 14px/15px labels or 44px hit areas smaller. At overview zoom the
renderer swaps full controls for fixed-size markers instead of shrinking text.

### Mind-Map Tree and Collapse Contract

The mind map is a deterministic left-to-right hierarchy. It is not radial and it
does not use module frames.

| Level | Content | Layout and collapse rule |
|---|---|---|
| `L0` | Virtual root `我的数学知识体系` | Always present and expanded |
| `L1` | Nine reviewed modules | One vertical column in reviewed order; all collapsed on first visit |
| `L2+` | Real knowledge nodes | Each real node appears exactly once under its reviewed display parent |

Tree geometry at readable focus:

- root-to-module horizontal gap: 48px desktop, 32px mobile;
- parent-to-child horizontal gap: 72px desktop, 56px mobile;
- sibling vertical gap: 16px desktop, 12px mobile;
- primary tree edges are 1.5px solid lines and never arrows when nesting is clear;
- cross prerequisites never change display parent or create a second node copy.

Mind-map focus states are fixed:

- `fit_all`: root and nine module controls only; every module is collapsed;
- `module_focus`: selected module and every node in that module are expanded and
  readable once; other modules stay collapsed and de-emphasized;
- `node_focus`: selected path, direct children, and visible siblings remain full;
  unrelated branches in the focused module remain present at 35% emphasis;
- activating a module chevron collapses or expands that module without selecting
  a learning node;
- activating a node branch chevron hides/shows descendants but never hides the
  selected node, current-learning node, or their ancestor path;
- selecting `查看其他前置知识` temporarily reveals dashed 2px arrowed cross-links
  and a text relation list; closing the disclosure removes only those paths.

Collapse state is stored only for the mind-map projection and compatible
projection version. First visit and invalid state always return to root plus nine
collapsed modules.

### Directed Graph Panorama and Focus Contract

The graph is a deterministic left-to-right prerequisite topology:

- horizontal rank means `需要先会 -> 后面会用到`;
- vertical lane groups related modules using quiet labels and guide lines only;
- lane labels are 13px muted text; no lane has a surrounding rectangle, tinted
  module block, or closed nine-box boundary;
- rank gap is 96px between full node controls; lane gap is at least 72px;
- crossing minimization and bridge placement come from reviewed layout config,
  never a live force simulation.

Graph focus states are fixed:

| Focus state | Nodes | Edges | Interaction |
|---|---|---|---|
| `fit_all` | All 56 nodes as fixed-size overview markers; only selected/current/recommended may have labels | Reviewed overview backbone at 28% emphasis plus every cross-module bridge at 45%; arrowheads remain visible | Markers are not buttons; search, module menu, and fallback list provide direct access |
| `module_focus` | Every node in the module plus immediate bridge neighbors as full controls; unrelated nodes remain markers | Every strict edge with at least one endpoint in the focused module; unrelated edges hidden | Full controls use roving tabindex |
| `node_focus` | Selected node and complete one-hop neighbors as full controls; other module nodes remain quiet controls/markers | All incoming one-hop paths at 3px selected blue and all outgoing one-hop paths at 3px primary green | Optional `查看两步关系` is explicit; never opens automatically |

The initial graph camera fits all 56 markers with 24px internal viewport padding.
Zoom range is `0.35-1.60` desktop and `0.28-1.60` mobile; toolbar steps are 0.15.
At no zoom level may all 56 full labels be rendered simultaneously.

### Node State Visual Precedence

Node body stays neutral. Meaning is applied in this exact order from inner to
outer so states never overwrite one another:

1. Evidence icon, evidence text, and one border treatment: `未测试`, `学习中`,
   `待巩固`, or `暂时掌握`.
2. Optional readiness row: `需要先准备`; readiness never recolors mastery.
3. Optional `系统建议` compass cue.
4. Optional 4px `当前学习` left rail and text.
5. Selected 2px dark-blue outline and selected marker.
6. Keyboard focus 3px blue ring with 2px offset, always outermost.

Pending analysis and blocked runtime state appear in the current-learning banner
and detail notice, not as replacement mastery states. A disabled learning action
does not disable node selection: the child can always open detail and read the
child-safe reason.

No state uses color alone. State dots without text/icon/border are forbidden.
Activity uses four segments plus `x/4`; mastery never uses a percentage or a
second progress bar.

### Shared Node Detail Freeze

Desktop detail is a 320px in-flow panel; mobile detail is the same DOM instance
presented as a modal bottom sheet. Content order is fixed:

1. 52px sticky header: node name, evidence state, 44px close button.
2. Optional readiness/current/recommendation notice.
3. One-sentence essence.
4. `学习历程` four segments plus `x/4`.
5. `需要先会` relation list.
6. `后面会用到` relation list.
7. Optional read-only preview.
8. Disabled reason or pending notice when applicable.
9. Sticky action area with one primary and at most one command secondary.

Panel padding is 16px and section gap is 16px. Relations are text buttons with a
direction label and locate icon; they are not chips. An empty relation group says
`这里没有必须先学的知识` or `这里暂时没有后续关系`, and is never represented by
an empty frame.

On mobile, the header and action area stay visible while only the body scrolls.
Opening moves focus to the detail heading; close/Escape returns focus to the exact
originating node without changing camera, collapse, mode, search, or filter.

### View Switch and Local Memory

- The switch contains exactly `导图` and `图谱` and is 44px high.
- First visit selects `导图`.
- `active_view` is a local UI preference independent of projection version.
- Selection, search, filter, current-learning context, and open detail are shared.
- Mind-map camera/collapse and graph camera/path expansion are saved separately.
- Switching restores the destination camera. If the shared selected node would
  be offscreen, apply a temporary ensure-visible camera adjustment without
  overwriting the saved viewport until the child pans, zooms, or chooses focus.
- View switching never changes evidence, readiness, action eligibility, learning
  state, graph truth, or server data.
- Arrow keys change the selected radio; pointer/touch activation changes on one
  deliberate press. No swipe gesture switches modes.

### Search, Filter, Module, and Empty-State Contract

Search matches child-readable node and module names only. It does not search ids,
internal tags, model data, or hidden teaching metadata.

- debounce: 120ms;
- result popover: maximum six visible rows, each at least 44px high;
- exact Enter selection: focus and select the node, then open detail;
- multiple results: Up/Down moves through results, Enter chooses, Escape closes;
- clear control: 44px icon button with accessible name `清除搜索`;
- query and exclusive filter survive view switching but reset on a new child
  session only when product policy says so.

Filters are exactly `全部`, `有学习记录`, `待巩固`, and `未测试`. Matching nodes
remain full; nonmatches become noninteractive 24% orientation markers so topology
does not jump. The selected and current-learning nodes remain readable even when
they do not match, with notice `当前选中的知识不在筛选结果中`.

The nine-module index focuses a module; it does not filter out other modules or
change graph data. Search result, module focus, relation locate, and grouped-list
locate all perform camera movement first, then DOM focus, then one polite node-name
announcement.

Exact empty/disabled states:

| State | Visible result | Required action |
|---|---|---|
| Loading | Stable reserved viewport and neutral skeleton; no fake node labels | None until data is valid |
| No search/filter result | In-viewport message naming query/filter | `清除筛选` or `清除搜索` |
| No available learning action | Detail stays readable with `这个知识点现在还不能安全开始。` | Close, relation navigation, or preview when available |
| Missing reviewed content | `这个知识点的学习内容还在准备，暂时不能开始。` | Disabled primary plus child-safe reason |
| Pending analysis | Saved-work reassurance in banner; map remains browsable | `查看当前进度` or state-valid resume action |
| Blocked | Saved-work reassurance and concrete recovery | Retry, finish summary, or return to browsing |
| Projection unavailable | Controls/status remain; grouped node list replaces spatial view | Retry projection; continue current learning when available |
| Stale projection | Old view becomes read-only while refreshing | Retry; no old action may mutate learning |

Disabled controls use native `disabled` or `aria-disabled` according to semantics,
retain a 44px target, and expose the reason adjacent to the control or through its
described-by text. Reduced opacity alone is not an explanation.

### Keyboard and Touch Acceptance

Desktop Tab order is fixed:

1. Skip link.
2. Current-learning action when present.
3. View switch.
4. Search and clear.
5. Filter group.
6. Module index.
7. Viewport toolbar.
8. One roving projection node.
9. Open detail content/actions.

Mind-map arrows: Left moves to parent/collapses, Right expands/moves to first
child, Up/Down moves among visible siblings. Graph arrows choose the nearest
readable node in that physical direction; ties resolve by rank, lane, then stable
reviewed order. Home/End moves to first/last readable node in the focused module.
Enter/Space selects and opens detail.

Pointer/touch contract:

- node press is a tap until movement exceeds 8px;
- movement beyond 8px cancels activation and begins pan;
- one finger pans only inside the bounded viewport;
- two fingers pinch zoom around the midpoint;
- vertical movement started on page chrome, banner, detail, or outside viewport
  scrolls the document normally;
- desktop wheel zooms only while viewport is focused or Ctrl/Meta is held;
- sheet scroll owns touch while open and the background viewport is inert;
- visible zoom, fit, selected focus, module menu, search, and grouped list are
  required alternatives to gestures.

Under reduced motion, camera, mode, path, and sheet transitions jump to the final
state; no information depends on animation.

### Forbidden Visual and Interaction Modes

Implementation is rejected if any of the following appears:

- nine closed/tinted module boxes in graph view;
- all 56 full labels visible at fit-all or labels below the specified type size;
- canvas-only nodes, canvas-only hit testing, or inaccessible duplicate node DOM;
- permanent edge hairball with all 95 relations at equal emphasis;
- live force layout, drifting nodes, pulsing status, path-drawing spectacle, or
  staggered 56-node entrance;
- state communicated by colored dots or tinted node bodies alone;
- mastery percentage, mastery progress bar, fake precision, or completion styled
  as understanding;
- oversized hero title, marketing intro, three-option comparison cards, daily
  route as the primary home, nested cards, floating section cards, gradients,
  decorative orbs, bokeh, glass blur, or radius above 8px;
- 9-11px node/detail text, 28-34px touch targets, emoji icons, or manually drawn
  interface icons where a Lucide icon exists;
- permanent visible usage instructions such as `拖动浏览 / 滚轮缩放`; use
  familiar controls, accessible names, and tooltips instead;
- desktop detail overlaying the selected node or mobile sheet leaking pan gestures;
- hidden/removed focus rings, hover-only meaning, gesture-only commands, or
  automatic mode switching;
- internal ids, provider/model/agent, queue/job, rubric/criterion, confidence,
  contract, prompt, or raw error language in visible text, accessible names, DOM
  attributes, screenshots, or child DTOs.

### Prototype Problem Evidence

The two historical prototypes are problem references only:

- `knowledge-map-full-canvas-v2.html` demonstrates the rejected nine framed
  modules, tiny all-node labels, equal-emphasis edge mesh, canvas-only nodes,
  color-dot states, permanent gesture instructions, and desktop-first side index;
- `knowledge-map-layouts.html` is a design-comparison page rather than the child
  application; its 9-10px nodes, 128px detail rail, progress/mastery bars, three
  marketing cards, and route-first option must not be implemented;
- browser inspection at desktop confirmed the graph reads as an engineering
  overview rather than a child learning entrance; the 390px comparison prototype
  becomes a long card page rather than a spatial work surface.

## Existing Child Shell Disposition

The current child page provides useful focused-learning foundations but is not a
dual-view skeleton:

| Existing asset | Reuse | Required change during implementation |
|---|---|---|
| `index.html` one `main`, topbar, error panel, focused task form, live toast | Keep one child page, one `main`, existing focused learning controls and error semantics | Add `map_home` and `learning_step` as sibling surfaces; do not place the map inside `.child-panel` |
| `app.js` bootstrap, current-step states, save/photo/stuck, blocked recovery, focus helpers | Keep focused learning authority and child-safe error patterns | Move global surface orchestration above focused rendering; put dual-view presentation in a dedicated module; split `question_feedback` from teaching |
| `styles.css` 44px buttons, 8px radii, focus ring, 620px breakpoint, reduced-motion baseline | Reuse tokens where compatible | Keep map styles isolated; replace the 960px centered panel assumption with a full-width spatial workspace only for `map_home` |
| Current child DTO forbidden list includes `graph` | Keep strict sanitizer for model-produced learning text | Use a separate allowlisted map DTO validator; do not weaken the focused-learning sanitizer |

Implementation must not remove working save/error/focus behavior while adding the
map surface.

## Surface Architecture

`map_home` and `learning_step` are mutually exclusive sibling surfaces. Only the
active surface is visible, exposed to the accessibility tree, and tabbable.

Illustrative semantic outline, not copy-paste production markup:

```html
<main aria-labelledby="page-title">
  <header><!-- page title + connection state --></header>

  <section aria-labelledby="knowledge-home-title">
    <section><!-- current learning status --></section>
    <fieldset><!-- 导图 / 图谱 native radios --></fieldset>
    <form role="search"><!-- search --></form>
    <fieldset><!-- exclusive child-safe filter --></fieldset>
    <div role="toolbar"><!-- zoom / fit / focus --></div>
    <nav aria-label="知识模块"><!-- nine module controls --></nav>

    <section role="region" aria-labelledby="active-view-heading">
      <svg aria-hidden="true"><!-- relationship paths --></svg>
      <div><!-- active node/module controls --></div>
    </section>

    <aside aria-labelledby="node-detail-heading"><!-- desktop detail --></aside>
    <div role="dialog" aria-modal="true"><!-- same detail on mobile --></div>
    <section><!-- accessible grouped list fallback --></section>
    <div aria-live="polite" aria-atomic="true"></div>
  </section>

  <section aria-labelledby="learning-step-title">
    <!-- existing question / analyzing / feedback / teaching / clarify / blocked / summary -->
  </section>
</main>
```

Use one detail DOM instance whose semantic role changes by responsive mode. Do
not duplicate desktop and mobile detail content in two simultaneously mounted,
focusable trees.

## Component Inventory

### Global and Surface Components

| Component | DOM responsibility | ARIA / focus responsibility | State owner |
|---|---|---|---|
| `ChildAppShell` | One `main`, page title, connection state, global polite live region | Sequential headings; no outline removal from the actual programmatic focus target | `app.js` |
| `SurfaceRouter` | Toggle sibling `map_home` and `learning_step` surfaces | Inactive surface gets `hidden` and `inert`; verify zero tabbable descendants | `app.js` |
| `CurrentLearningBanner` | Compact current topic/status and one resume/retry/summary action | Labeled status region; pending updates polite, blocking recovery focusable only when action is required | shared projection controller |
| `KnowledgeHomeSurface` | Own toolbar, projection viewport, detail, fallback, and local states | Heading receives focus only on route/surface entry, not every data refresh | `knowledge_views.js` |
| `LearningStepSurface` | Existing focused question/analyzing/feedback/teaching/clarify/blocked/summary flow | Preserve current v5 focus and error behavior | existing focused renderer |
| `MapLiveRegion` | Short announcements only | Announce view switch, result count, target waiting, stale refresh; never read the full graph/detail | shared projection controller |

### Navigation and Control Components

| Component | DOM responsibility | ARIA / focus responsibility | Visual responsibility |
|---|---|---|---|
| `ViewModeSegmentedControl` | Native radio inputs styled as two equal segments: `导图`, `图谱` | `fieldset`/legend or `radiogroup` labeled `知识展示方式`; arrow keys switch, focus remains on selected segment | 44px height, selected check/indicator plus contrast, not color alone |
| `KnowledgeSearch` | Child-readable node/module query and clear control | `role="search"`, visible label, Escape clears only when input owns focus, result count announced politely | 44px input, search icon and clear icon from one local Lucide subset |
| `KnowledgeFilter` | Exclusive filters: 全部/有学习记录/待巩固/未测试 | Native radios on desktop; labeled select/menu on mobile; preserve selected value across view switch | Compact, no long row of narrow pills at 390px |
| `ModuleIndex` | Nine module-focus controls in reviewed order | `nav aria-label="知识模块"`; current focused module uses `aria-current="true"` or pressed state | Desktop quiet horizontal/wrapped index; mobile one menu button plus sheet/menu |
| `ViewportToolbar` | Zoom out, zoom in, fit all, focus module, focus selected | `role="toolbar"`; icon-only buttons require accessible names and tooltips | Familiar Lucide icons, 44px targets, stable dimensions |
| `ViewLegend` | Explain activity/mastery and relation line/shape meanings | Labeled complementary text; not a focus stop unless collapsible | Compact two-column desktop, disclosure on mobile |

### Shared Projection Components

| Component | DOM responsibility | ARIA / focus responsibility | Notes |
|---|---|---|---|
| `ProjectionViewport` | One bounded transform surface with SVG relationship layer and HTML control layer | Named region `我的数学知识导图` or `我的数学知识图谱`; one roving node tab stop | Never use canvas-only hit targets |
| `RelationshipLayer` | SVG paths, arrow markers, bridge markers, selected relation emphasis | `aria-hidden="true"`; selected relation meaning is repeated in detail/legend | Paths use `vector-effect="non-scaling-stroke"` |
| `NodeLayer` | Real node controls and module/root controls for active view | Roving tabindex; no raw ids in labels, DOM ids, test ids, or accessible names | Store opaque handle in controller state/closure, not child text |
| `OverviewMarker` | Noninteractive fit-all representation when a full label/hit area cannot fit | `aria-hidden`; every node remains reachable through search/module/fallback list | Must not masquerade as a tiny button |
| `KnowledgeNodeButton` | Full readable node name, evidence state, activity indicator, optional readiness/current/recommendation cues | `button`, unique accessible name, `aria-selected`, roving tabindex; Enter/Space opens detail | Minimum 44x44 screen-space hit area at readable focus levels |
| `ActivityProgress` | Four visual activity segments plus `x/4` text | Accessible label `学习历程，完成 x/4`; segments decorative | Never implies correctness |
| `EvidenceState` | Categorical mastery/evidence icon and text | Text and icon available; no percentage | Separate from action readiness |
| `ReadinessNotice` | Optional `需要先准备` or unavailable explanation | Included in node/detail accessible description | Must not replace evidence state |
| `RecommendationCue` | Small `系统建议` compass cue | Text label; no sparkle-only meaning | Never auto-selects |

### Mind-Map Components

| Component | DOM responsibility | ARIA / focus responsibility | Layout responsibility |
|---|---|---|---|
| `MindMapRoot` | Virtual root `我的数学知识体系`; not a learning node | Branch control may expose `aria-expanded`; never appears as node action | Center/start of primary hierarchy |
| `ModuleBranch` | One of nine module grouping branches | Button with `aria-expanded`; collapsed descendants hidden/inert | First visit collapsed except minimum restored path |
| `PrimaryTreeEdge` | One reviewed display-parent line per real node | Decorative path; hierarchy repeated through DOM grouping | Solid thin line, no arrow required when tree nesting is clear |
| `CrossPrerequisiteDisclosure` | `查看其他前置知识` action and temporary relation list/paths | Button announces expanded state; relation locate action focuses target node | Dashed arrow plus `其他前置` label when expanded |

### Directed Graph Components

| Component | DOM responsibility | ARIA / focus responsibility | Layout responsibility |
|---|---|---|---|
| `GraphLaneGuide` | Quiet lane/module labels and guide lines | Nonfocusable text; included in viewport description only when useful | No closed module frames |
| `HardPrerequisiteEdge` | Directed source-to-target path | SVG hidden; detail lists `需要先会` and `后面会用到` relations | Solid 2px line plus arrowhead |
| `SelectedIncomingEdge` | Selected node's complete one-hop prerequisites | Meaning repeated in relation list | 3px line, arrowhead, `先会` midpoint tag when space permits |
| `SelectedOutgoingEdge` | Selected node's immediate continuations | Meaning repeated in relation list | 3px line, arrowhead, `后面会用` tag when space permits |
| `BridgeMarker` | Cross-module bridge cue at lane boundary or edge midpoint | Not focusable; relation text available in detail | Small bridge glyph/label plus line style, not color only |
| `ConvergenceCue` | Shows multiple incoming paths visibly joining one node | Incoming count summarized in detail | Multiple arrowheads remain individually traceable |
| `GraphMinimap` | Desktop-only noninteractive orientation preview | `aria-hidden="true"`; no duplicate node focus targets | Hide at 390px and when detail width makes it illegible |

### Shared Node Detail Components

| Component | DOM responsibility | ARIA / focus responsibility | Responsive behavior |
|---|---|---|---|
| `NodeDetailSurface` | Node name, evidence state, readiness, essence, activity, relations, actions | Desktop `aside`/complementary; mobile modal dialog with `aria-labelledby` | Right panel desktop, bottom sheet mobile; one DOM instance |
| `NodeRelationList` | Prerequisites and downstream nodes as child-readable links | Locate buttons move camera then focus target node | Direction words visible, not line-color-only |
| `NodeActionGroup` | Ordered primary, optional command secondary, preview/relation actions | Native disabled states plus adjacent child-safe reason; pending label stable | One primary only; mobile commands full-width when useful |
| `DetailCloseButton` | Familiar X icon button | Accessible name `关闭知识点详情`; Escape equivalent; restore originating node focus | 44px target |

### Focused Feedback Component

| Component | DOM responsibility | ARIA / focus responsibility | Constraints |
|---|---|---|---|
| `QuestionFeedbackSurface` | `h2 本题反馈`, exactly five semantic sections, one sibling runtime action | Short polite ready announcement; move focus once to heading; action last in Tab order | Not modal, no nested cards, no hidden teaching content |
| `FeedbackScore` | Label `得分` and `score_label` | Read as one phrase; tabular numerals | 24-32px, not hero scale |
| `FeedbackReference` | `标准答案` child-safe text | Preserve meaningful line breaks | Safe text nodes only |
| `FeedbackGap` | `与标准答案的差距` | Recognize equivalent methods/notation | No criterion list |
| `FeedbackImprovement` | One or two `改进方向` list items | Semantic list | No invented criticism for 10/10 |
| `FeedbackExpression` | `表达判定` | Concise text | No style/neatness judgment unless scored |
| `FeedbackRuntimeAction` | One action outside feedback object | Final focusable control; error adjacent; no auto-advance | May enter question, teaching, clarify, new knowledge, summary, retry, or stop |

### Fallback and Status Components

| Component | DOM responsibility | ARIA / focus responsibility |
|---|---|---|
| `GroupedNodeFallback` | Nine module headings and same real node actions | Normal document Tab order; active only when spatial renderer fails or user chooses list |
| `MapUnavailableState` | Honest unavailable copy, retry, and continue-current action | Focusable status only on blocking transition |
| `NoResultsState` | Query/filter summary and clear action | Polite result announcement, no fake graph-empty claim |
| `TargetWaitingStatus` | Named target waiting for current safe boundary | Polite status, replace/cancel controls when allowed |

## Visual System

### Design Direction

- Quiet local learning workspace, not a dashboard, game, landing page, or graph
  engineering console.
- Neutral surfaces carry most of the page. Semantic colors occupy small state,
  edge, icon, and action areas rather than tinting the whole canvas.
- No decorative gradients, orbs, bokeh, glass blur, oversized hero heading,
  nested cards, or floating page-section cards.
- The graph and mind map are the primary visual assets.
- Use a locally bundled Lucide subset for familiar controls; no emoji icons and
  no manually drawn interface SVG icons.

### Semantic Color Tokens

All text/background pairs require WCAG AA contrast. Color supplements text,
icons, border styles, and shapes; it never carries meaning alone.

| Token | Value | Use |
|---|---:|---|
| `--ui-bg` | `#F4F6F3` | Page/canvas surround |
| `--ui-surface` | `#FFFFFF` | Toolbar, panel, sheet, node surface |
| `--ui-surface-subtle` | `#EEF2EF` | Quiet grouping and hover surface |
| `--ui-ink` | `#18211C` | Primary text |
| `--ui-muted` | `#56635C` | Secondary text |
| `--ui-border` | `#CAD4CE` | Default separators and node border |
| `--ui-primary` | `#176B5B` | Main child action and current learning |
| `--ui-primary-strong` | `#0F5145` | Primary hover/pressed text |
| `--ui-info` | `#2F5F86` | Learning activity and prerequisite path |
| `--ui-warning` | `#7A5200` | Consolidation and caution |
| `--ui-danger` | `#9A2F2A` | Blocked/error, used sparingly |
| `--ui-prep` | `#6B4E7A` | Preparation/readiness notice |
| `--ui-focus` | `#0B6ED0` | 3px focus ring independent of mastery state |
| `--ui-selected` | `#133F68` | Selected-node outline and selected graph path |
| `--ui-backdrop` | `rgba(18, 27, 22, .48)` | Mobile modal sheet scrim only |

State surface tokens:

| Meaning | Foreground | Background | Non-color encoding |
|---|---|---|---|
| Untested | `#56635C` | `#F0F2F1` | `CircleDashed` icon + dashed node border + `未测试` text |
| Learning | `#176B5B` | `#E7F3EF` | `CircleDot` icon + solid left rail + `学习中` text |
| Needs consolidation | `#7A5200` | `#FFF4D6` | `TriangleAlert` icon + double bottom rule + `待巩固` text |
| Mastered for now | `#2F5F86` | `#EAF1F8` | `CircleCheck` icon + solid border + `暂时掌握` text |
| Preparation needed | `#6B4E7A` | `#F3EDF6` | `Waypoints` icon + corner notch + `需要先准备` text |
| Pending analysis | `#2F5F86` | `#EAF1F8` | `Clock3` icon + `正在批阅` text |
| Blocked | `#9A2F2A` | `#FFF0EF` | `OctagonAlert` icon + left rule + recovery text |

Do not recolor the whole node by state. Keep node body neutral and apply state to
one icon, one border treatment, and one text label.

### Progress and Mastery Encoding

- `学习历程` uses four equal horizontal activity segments. Filled segments use
  `--ui-info`; empty segments use surface plus border. Always show `x/4` text.
- Mastery/evidence is categorical, not a percentage bar. Use the state icon and
  state text above; optional evidence summary is plain text in detail.
- Activity segments and evidence state must not share identical shape/color, so
  a child cannot mistake completion for understanding.

### Typography Tokens

Use the existing system sans stack; do not add a network font dependency.

| Token | Desktop | 390px | Use |
|---|---:|---:|---|
| `--type-page-title` | 28px/1.2, 700 | 24px/1.2, 700 | Page title only |
| `--type-section-title` | 20px/1.3, 700 | 18px/1.35, 700 | Detail/feedback sections |
| `--type-body` | 16px/1.55, 400 | 16px/1.55, 400 | Main copy |
| `--type-node` | 14px/1.3, 650 | 15px/1.35, 650 | Full node labels |
| `--type-module` | 16px/1.35, 700 | 17px/1.35, 700 | Root/module labels |
| `--type-label` | 13px/1.35, 650 | 13px/1.4, 650 | State/meta labels |
| `--type-score` | 30px/1.1, 750 | 28px/1.1, 750 | Per-question score |

- Letter spacing is `0`.
- Full node names wrap to two lines. Never shrink below the node token.
- Use tabular numerals for score and `x/4` progress.
- Body line length: 60-75 characters desktop, 35-60 mobile when the content is
  prose rather than mathematical notation.

### Spacing, Radius, Elevation, and Layer Tokens

| Token | Value | Use |
|---|---:|---|
| `--space-1` | 4px | Icon/text micro-gap |
| `--space-2` | 8px | Control gap and touch separation minimum |
| `--space-3` | 12px | Node/detail internal gap |
| `--space-4` | 16px | Toolbar/panel padding |
| `--space-6` | 24px | Major section separation |
| `--space-8` | 32px | Desktop outer rhythm |
| `--radius-node` | 6px | Node controls |
| `--radius-control` | 8px | Inputs, buttons, segmented control |
| `--radius-panel` | 8px | Detail/sheet/result panel |
| `--elevation-0` | none | Canvas and unselected nodes |
| `--elevation-1` | `0 2px 8px rgba(24,33,28,.08)` | Toolbar/sheet boundary |
| `--elevation-2` | `0 8px 24px rgba(24,33,28,.14)` | Mobile detail sheet only |

Layer scale:

- canvas `0`;
- nodes `10`;
- selected paths/nodes `20`;
- sticky toolbar/detail `40`;
- modal scrim `80`;
- mobile sheet `100`;
- toast `120`.

No radius above 8px except an existing compact status pill when text fit and
contrast remain correct.

### Motion Tokens

| Token | Value | Use |
|---|---:|---|
| `--motion-press` | 120ms | Press/selected feedback |
| `--motion-state` | 180ms | Hover, focus, path emphasis |
| `--motion-sheet` | 240ms | Mobile detail enter/exit |
| `--motion-camera` | 280ms | Fit/module/node focus |
| `--ease-enter` | ease-out | Enter/focus |
| `--ease-exit` | ease-in | Exit |

- Animate transform and opacity only.
- Camera movement is interruptible; pointer/touch input cancels it immediately.
- No staggered 56-node entrance, pulsing nodes, path drawing spectacle, parallax,
  bounce, or continuous ambient motion.
- Under `prefers-reduced-motion: reduce`, camera/sheet/view changes are immediate,
  no spinner rotates continuously, and information is present from the first
  rendered frame.

## Node and Edge Visual Encoding

### Node Anatomy

Readable node controls use this order:

1. State icon plus evidence-state text.
2. Child-readable knowledge name, maximum two lines.
3. Four activity segments with `x/4` text.
4. Optional small readiness/current/recommendation row.

At fit-all, overview markers may reduce to state shape plus selected/current cue.
They are noninteractive until module/node focus makes a 44px control possible.

Node interaction states:

| State | Encoding |
|---|---|
| Default | Neutral surface, 1px border, state icon/text |
| Hover | Border changes to primary; no layout or scale shift |
| Pressed | Subtle surface darkening within 100ms |
| Keyboard focus | 3px blue focus ring with 2px offset |
| Selected | 2px dark-blue outline, selected marker, `aria-selected="true"` |
| Current learning | 4px primary left rail plus `当前学习` text |
| Recommended | Compass icon plus `系统建议` text |
| Disabled action | Node remains selectable for detail; action reason appears in detail |

### Edge Anatomy

| Relation | Stroke | Marker / label | Visibility |
|---|---|---|---|
| Mind-map primary parent | 1.5px solid neutral | Tree nesting supplies direction | Expanded hierarchy only |
| Mind-map cross prerequisite | 2px dashed blue-gray | Arrowhead plus `其他前置` | Selected/expanded only |
| Graph overview prerequisite | 1.5px solid blue-gray at low emphasis | Arrowhead | Reviewed backbone only |
| Selected incoming prerequisite | 3px solid selected blue | Arrowhead plus optional `先会` tag | Complete one-hop |
| Selected outgoing continuation | 3px solid primary green | Arrowhead plus optional `后面会用` tag | Complete one-hop |
| Cross-module bridge | Base relation stroke plus bridge glyph/label | Arrowhead retained | Overview/config or selected path |

- Arrowheads remain visible at every rendered zoom through non-scaling stroke and
  marker sizing.
- Incoming and outgoing meaning is also written in the detail relation list.
- Convergence is shown by individually traceable arrows entering one node, not a
  merged color blob.
- The initial release renders no unlock-only candidates or soft-support legend.

## Layout Behavior

### 1280x800 Desktop

Stable page geometry:

- outer page inset: 16px horizontal, 12px vertical;
- compact topbar: 48-56px;
- current-learning banner when present: 44-56px;
- controls row: 52px minimum with 8-12px gaps;
- workspace uses remaining height with a target minimum of 600px;
- detail closed: projection uses full workspace width;
- detail open: grid `minmax(0, 1fr) 320px`, 12px gap;
- detail panel does not cover the selected node; camera accounts for the reduced
  viewport before node focus.

Desktop `fit_all`:

- mind map opens with virtual root and all nine module branches collapsed;
- graph shows all 56 markers, lane labels, and reviewed overview backbone;
- selected/current/recommended nodes may retain readable callouts;
- full labels that would overlap become noninteractive overview markers.

Desktop `module_focus`:

- focused branch/lane occupies 70-85% of usable projection bounds;
- all module nodes show full 14px labels and 44px hit areas;
- graph includes immediately adjacent bridge nodes/edges without showing the
  entire 95-edge field at full emphasis.

Desktop `node_focus`:

- selected node and complete one-hop labels remain readable;
- selected relation paths use the high-emphasis encoding;
- detail opens after camera calculation, not before, to avoid covering the target;
- optional two-hop expansion never obscures the primary action or toolbar.

### 390x844 Mobile

Stable page geometry:

- outer inset: 12px plus safe-area insets;
- title/current status row: 44-52px each as present;
- segmented control: 44px;
- compact search plus controls: 44-48px rows;
- projection viewport target: at least 420px high when detail is closed;
- document has no horizontal scroll; panning is internal to the viewport;
- module index and secondary filters move into a labeled menu/sheet;
- minimap is absent.

Mobile `fit_all`:

- mind map shows root plus nine collapsed modules;
- graph shows all 56 orientation markers and backbone without pretending every
  marker is a tappable full label;
- search, module menu, and grouped fallback list provide direct access to every
  node.

Mobile `module_focus`:

- one module expands/fits; other module branches remain collapsed or quiet;
- all focused module nodes use at least 15px labels and 44px hit areas;
- control rows never overlap node labels.

Mobile `node_focus` and detail:

- focus selected node before opening the sheet;
- bottom sheet max height: 68dvh, minimum visible map strip: 112px unless text
  enlargement requires full-height accessibility mode;
- sheet uses one scroll container, bottom safe-area padding, and a 44px close
  control;
- primary action follows content and remains reachable without covering the final
  line;
- background viewport is inert while the modal sheet is open;
- closing restores focus and the exact viewport to the originating node.

### Feedback Layout

Desktop feedback is a centered readable flow, max width 760px, not a map detail
panel. Mobile feedback is single-column with five unframed sections separated by
dividers/spacing. The runtime action follows section five. Do not place five
cards inside the current `.child-panel`.

## Interaction and Accessibility

### Roving Tabindex

- Active projection has one Tab entry and one Tab exit.
- Exactly one readable node control has `tabindex="0"`; the rest use `-1`.
- Mind map: Left parent/collapse, Right expand/first child, Up/Down previous/next
  visible tree item.
- Graph: arrows choose nearest readable node in that direction; ties use
  rank/lane/order.
- Home/End move to first/last readable node in the focused module.
- Enter/Space selects and opens detail.
- Search/module/relation locate moves camera, then focus, then announces the node.
- Fit-all overview markers do not enter the Tab sequence.

### Pointer and Touch

- Empty-space drag pans. Node press remains a tap until movement exceeds 8px.
- Beyond 8px, cancel node activation and pan; release after pan never opens detail.
- One-finger touch pans inside the bounded viewport; two-finger pinch zooms.
- Preserve protected browser/system edge gestures.
- When the mobile sheet is open, sheet scroll owns touch and background pan is
  disabled.
- Desktop wheel zooms around pointer only when viewport is focused or Ctrl/Meta is
  held; otherwise preserve page scroll.
- Visible zoom in/out, fit, module focus, selected focus, search, module menu, and
  grouped list are required alternatives to gestures.

### Focus and Announcements

- View switch retains focus on the selected radio and announces active view.
- Detail opened by keyboard moves focus to heading/first action according to
  responsive role; close/Escape restores node focus.
- Feedback arrival announces only `本题反馈已准备好，得分 x/10`, then focuses the
  feedback heading once.
- Search/filter announces result count, not every node.
- Pending/blocked updates use short polite messages; immediate blocking errors may
  use a focusable error region.
- Never put the full viewport, detail, or feedback body inside an assertive live
  region.

### Reduced Motion

- Disable animated camera travel, crossfade, sheet slide, path emphasis, and
  rotating indicators.
- Fit/module/node focus jumps directly to final framing.
- All relation and state information is visible without waiting for animation.

## Performance Budget

Measure against the local Python service, current 56-node graph, 95 strict
prerequisites, 1280x800, and 390x844. Use at least 20 warm runs/actions and report
median and worst observed values.

### Payload and Asset Budget

| Budget | Target |
|---|---:|
| Knowledge projection JSON before compression | <= 250KB |
| Dual-view JavaScript source, unminified | <= 80KB |
| Dual-view CSS source, unminified | <= 35KB |
| Local icon subset | <= 20 icons; no remote font/icon request |
| Local presentation preferences | <= 10KB per projection version |

### DOM and SVG Budget

- one active projection renderer exposed to accessibility at a time;
- 56 real node records, with no duplicated real node in one primary renderer;
- at most nine module controls plus one virtual root in mind-map structure;
- at most 95 strict prerequisite SVG paths allocated for graph topology;
- fit-all draws only config-approved backbone paths at normal emphasis;
- selected one-hop/two-hop changes classes/visibility instead of rebuilding the
  full layout;
- target map-home DOM: fewer than 500 elements excluding focused learning content;
- no per-frame DOM insertion during pan/zoom.

### Timing and Stability Budget

| Operation | Median target | Worst target |
|---|---:|---:|
| Parse/normalize warm map payload | <= 20ms | <= 40ms |
| Initial active projection render after payload | <= 60ms | <= 100ms |
| View switch using cached projection | <= 50ms | <= 100ms |
| Search/filter/module/node focus | <= 50ms | <= 100ms |
| Press/tap visible feedback | <= 80ms | <= 100ms |
| Pan/zoom animation frame | <= 16.7ms at p95 | No long task > 50ms |

- CLS after initial shell reservation: < 0.1.
- No force simulation, model call, API call, layout authority calculation, or
  learning-state write on view switch/pan/zoom.
- Batch DOM reads then writes; camera uses one transform on the shared world.
- Throttle pointer/wheel updates through `requestAnimationFrame`.
- Debounce search only enough to avoid repeated layout work, target 100-150ms;
  direct button/keyboard focus is not debounced.

## Screenshot Acceptance Package

All screenshots use an isolated copied DB and the exact policy/config receipt.
Each image records viewport, active mode/state, projection/config digest, and
scenario name in the evidence report, never in the child-visible UI.

### 1280x800 Required Screenshots

| File | Scenario | Exact visual checks |
|---|---|---|
| `dual-v51-1280-mind-fit.png` | First visit, mind-map fit-all | Root + nine collapsed modules; no oversized hero; toolbar stable; no node-label pileup |
| `dual-v51-1280-mind-module.png` | Module focus | Full module labels >=14px; 44px targets; all module nodes visible once; no overlap |
| `dual-v51-1280-mind-crosslink.png` | Selected multi-prerequisite node | Primary tree path distinct from dashed `其他前置`; shared detail open; direction repeated in text |
| `dual-v51-1280-graph-fit.png` | Directed graph fit-all | All 56 markers represented; arrowheads/backbone visible; convergence/bridges legible; no nine closed boxes |
| `dual-v51-1280-graph-module.png` | Graph module focus | Module lane plus bridge context; full labels readable; unrelated topology quiet |
| `dual-v51-1280-graph-node.png` | Graph node focus | Complete one-hop incoming/outgoing paths, arrowheads, selected node not covered by 320px detail |
| `dual-v51-1280-mode-memory.png` | Switch mind map to graph with selection | Same node remains selected; detail retained; destination viewport independent |
| `dual-v51-1280-feedback-partial.png` | Partial-score feedback | Exactly five sections; action after section five; teaching absent; no nested cards |
| `dual-v51-1280-pending.png` | Current answer analyzing on map home | Saved-work copy, browse still usable, queued-target action understandable |
| `dual-v51-1280-blocked.png` | Blocked current learning | Calm child-safe reason, real retry/summary actions, no internal error text |
| `dual-v51-1280-fallback.png` | Spatial renderer failure | Module-grouped node list with equivalent selection/detail/action access |
| `dual-v51-1280-keyboard-focus.png` | Keyboard-selected node/detail | 3px visible ring, one roving node tab stop, detail focus target visible |

### 390x844 Required Screenshots

| File | Scenario | Exact visual checks |
|---|---|---|
| `dual-v51-390-mind-fit.png` | First mobile visit | Root + nine collapsed modules; segmented control and search fit; no horizontal page scroll |
| `dual-v51-390-mind-module.png` | Mobile module focus | Labels >=15px, 44px targets, no clipping or toolbar collision |
| `dual-v51-390-graph-fit.png` | Mobile graph overview | 56 orientation markers/backbone visible without tiny fake buttons; visible focus alternatives |
| `dual-v51-390-graph-node-sheet.png` | Selected graph node | Modal bottom sheet <=68dvh, >=112px map strip, safe-area action, close control |
| `dual-v51-390-feedback-10.png` | 10/10 feedback | No invented flaw, exactly five sections, body >=16px, action after expression judgment |
| `dual-v51-390-feedback-0.png` | 0/10 feedback | Neutral nonshaming hierarchy, standard answer/gap/action readable, no giant red treatment |
| `dual-v51-390-pending-target.png` | Analysis plus waiting target | Saved answer and named waiting target fit without overlap; action labels wrap cleanly |
| `dual-v51-390-blocked.png` | Blocked/recovery | Full-width 44px actions, reason and saved-work copy visible, no hidden content behind safe area |
| `dual-v51-390-focus-return.png` | Close detail sheet | Originating node focus ring visible after close; viewport unchanged |
| `dual-v51-390-text-enlarged.png` | Browser text enlargement | No overlap, clipped action, inaccessible sheet content, or document horizontal scroll |

### Screenshot and DOM Assertions

Every scenario must assert:

- screenshot is nonblank and active projection contains rendered pixels;
- `document.documentElement.scrollWidth === document.documentElement.clientWidth`
  at 390px;
- no visible text/control bounding boxes overlap incoherently;
- no full node label is below its viewport minimum type token;
- all visible command targets are at least 44x44px with 8px separation where
  adjacent taps could be confused;
- active renderer has one roving `tabindex="0"`; hidden renderer and inactive
  surface have zero tabbable descendants;
- node count, module count, tree uniqueness, and edge/path counts match the
  active scenario contract;
- selected/current/recommended/mastery/progress/blocked meaning is not color-only;
- focus ring and selected outline remain distinguishable on every semantic state;
- no canonical graph/question/attempt/assessment ids, provider/model/agent,
  criterion, contract, rubric, confidence, queue, job, prompt, or internal error
  terms appear in API child fields, DOM text, accessible names, DOM attributes,
  or screenshots;
- feedback object has exactly five keys and teaching content is absent;
- reduced-motion run reaches the same final visual state without animated travel;
- human child-readability/taste review is recorded before final UX acceptance.

## Implementation Acceptance Checklist

- [ ] `map_home` and `learning_step` are sibling surfaces; inactive surface is hidden and inert.
- [ ] Current focused save/photo/stuck/error/recovery behavior still works.
- [ ] Mind map and graph use one common node/action projection and one selection.
- [ ] First visit opens mind map; active mode survives projection-version changes.
- [ ] Viewports/collapse restore only within compatible projection version.
- [ ] All 56 nodes and nine modules are represented in both modes.
- [ ] Mind map uses virtual root, nine module branches, one display parent, and on-demand cross-prerequisites.
- [ ] Graph uses directed rank/lane topology, arrowheads, convergence, bridges, and no closed nine-box layout.
- [ ] Fit-all/module-focus/node-focus match both viewport contracts.
- [ ] Overview markers never become overlapping tiny buttons.
- [ ] Node state, activity, readiness, selection, current, and recommendation use text plus shape/icon/border.
- [ ] Shared detail provides one primary action, optional secondary, disabled reason, preview, and relation navigation.
- [ ] Roving tabindex, search/module locate, focus restoration, and hidden-tab audits pass.
- [ ] 8px drag threshold, pinch/wheel behavior, visible alternatives, and sheet gesture isolation pass.
- [ ] Reduced-motion path has no camera/sheet travel or continuous spinner.
- [ ] Pending, waiting-target, blocked, stale, unavailable, no-results, and fallback states pass.
- [ ] Question feedback renders exactly five fields and one separate action; teaching is a separate state.
- [ ] Payload, DOM/SVG, timing, frame, CLS, and asset-size budgets pass.
- [ ] All required 1280x800 and 390x844 screenshot evidence is captured.
- [ ] Human review confirms the child can understand both views without instruction text.

## UX Package Self-Review

- component_inventory_complete: pass
- dom_aria_responsibilities_complete: pass
- mind_map_graph_distinction_preserved: pass
- shared_detail_and_controls_complete: pass
- exact_five_field_feedback_component_complete: pass
- semantic_multihue_visual_tokens_complete: pass
- typography_spacing_radius_elevation_motion_tokens_complete: pass
- node_edge_non_color_encoding_complete: pass
- desktop_and_390_three_focus_levels_complete: pass
- exact_desktop_and_390_geometry_frozen: pass
- mind_map_left_to_right_tree_and_collapse_frozen: pass
- graph_panorama_edge_visibility_and_focus_frozen: pass
- node_state_visual_precedence_frozen: pass
- search_filter_empty_disabled_contract_frozen: pass
- keyboard_touch_tab_order_frozen: pass
- forbidden_visual_modes_and_prototype_issues_recorded: pass
- roving_touch_pinch_wheel_visible_alternatives_complete: pass
- reduced_motion_complete: pass
- performance_budget_for_56_nodes_95_edges_complete: pass
- screenshot_package_1280_390_complete: pass
- anti_marketing_nested_card_gradient_orb_rules_applied: pass
- child_safe_internal_data_boundary_complete: pass
- production_code_changed: no
- blocking_ux_gaps_for_skeleton_implementation: none

## Stop Condition

This package is ready for 听云 to use during skeleton and frontend
implementation after required upstream gates. Rendered fidelity, browser
behavior, assessment activation, engineering review, and QA remain separate
evidence gates.
