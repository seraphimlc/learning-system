# Child UX Flow v5.1 Amendment: Dual Knowledge Views

Status: `UX_FLOW_READY_FOR_TECHNICAL_PLANNING`

Owner: 清秋 (`qingqiu`)

Decision date: 2026-07-14 CST

This amendment supersedes only the single-view knowledge-home and first-viewport
clauses in `docs/product/child_ux_flow_spec_v5.md` and the earlier single-canvas
presentation assumptions in the knowledge-map design and implementation specs.
All other v5 child-only learning-loop, evidence, current-step, pending, blocked,
summary, and child-safe boundaries remain in force.

This is a planned UX contract. It is not rendered UX evidence, implementation
approval, QA approval, or permission to activate the feature.

## Entry Lock

- request_type: `ux_flow_spec`
- current_role_authority: owned by 清秋 (`qingqiu`)
- selected_playbook_or_contract:
  - `docs/collaboration/playbooks/ux-review.md`
  - `ui-ux-pro-max` accessibility, interaction, responsive, and motion guidance
- source_artifacts:
  - `docs/product/child_ux_flow_spec_v5.md`
  - `docs/product/ai_native_math_learning_prd_v5_1_dual_knowledge_views_amendment.md`
  - `docs/design/specs/2026-07-14-child-knowledge-map-home-design.md`
  - `.agents/superpowers/specs/2026-07-14-child-knowledge-map-implementation.md`
  - `docs/design/specs/2026-07-14-answer-assessment-storage-design.md`
  - `.agents/superpowers/specs/2026-07-14-answer-assessment-feedback-implementation.md`
  - `docs/architecture/answer_assessment_engineering_contract_v5_1.md`
  - `tests/test_answer_assessment_v51.py`, including
    `AnswerAssessmentRuntimeV51Tests`
  - read-only current child shell:
    - `app/local_learning_system/index.html`
    - `app/local_learning_system/app.js`
    - `app/local_learning_system/styles.css`
  - user-confirmed v5.1 dual-view decisions from 2026-07-14
- project_boundary_overlay:
  - `AGENTS.md`
  - one child, one child Web page, no parent Web surface
  - child-safe language and data projection
  - latest user decisions take precedence over older presentation clauses
- output_target:
  - `docs/product/child_ux_flow_v5_1_dual_knowledge_views_amendment.md`
- validation_required_next:
  - terminology and state-contract consistency checks
  - rendered desktop and 390x844 browser evidence
  - keyboard, focus, ARIA, touch-target, and reduced-motion checks
  - dual-view switching, shared selection, and independent viewport checks
  - child payload and DOM leakage scan
- stop_condition: publish and self-review this UX amendment only; do not modify production code or other files

## Objective

Define one child knowledge home with two manual display modes over the same
authoritative mathematics graph:

```text
open / -> map_home -> 导图 or 图谱 -> select one node -> shared node detail
         -> preview or start a safe action -> existing focused learning_step
         -> analyzing -> question_feedback or clarify / blocked
         -> runtime action -> next question / teaching / new knowledge / summary
         -> return to map_home at a safe boundary
```

The dual views help the child answer two different orientation questions:

- `导图`: “这些知识怎样分成容易理解的层级？”
- `图谱`: “哪些知识是前置、汇聚、桥梁和后续影响？”

The two modes do not create two knowledge models, two learning runtimes, or two
sets of learning state. They are two projections of the same node, relationship,
progress, mastery, recommendation, selection, and action eligibility data.

## Source Product Structure

The v5.1 product decision is sufficient for UX drafting because it fixes:

- one page with a segmented `导图 / 图谱` view switch;
- first visit opens `导图`, later visits restore the last valid local choice;
- the two views share all 56 real nodes, nine reviewed modules, child-safe node
  state, progress, mastery, selection, node detail, and allowed actions;
- the mind map uses a virtual root, nine module branches, and one reviewed display
  parent per real node;
- extra real prerequisites remain available as on-demand cross-links;
- the graph uses directed prerequisite topology, arrowheads, convergence, and
  cross-module bridges instead of nine dominant closed module boxes;
- the graph source remains authoritative and is not rewritten for either view;
- browsing, expanding, switching, panning, zooming, or previewing produces no
  learning evidence and changes no mastery state;
- the existing focused current-step runtime remains the only learning workspace.

## Scope

- Amend the child `/` first viewport from a single knowledge-map canvas to a
  dual-view `map_home`.
- Define the shared toolbar, view switch, search, filters, module navigation,
  current-learning status, selected-node detail, and node actions.
- Define mind-map hierarchy, collapse behavior, and on-demand cross-prerequisite
  disclosure.
- Define directed graph topology, overview backbone, arrow direction,
  convergence, bridge visibility, and selected-node relationship expansion.
- Define first-use and remembered view preference.
- Define shared selected-node state and independent per-view viewport state.
- Define loading, local empty, unavailable, no-action, pending analysis, blocked,
  stale-version, fallback, and recovery behavior.
- Define desktop and 390px mobile composition.
- Define keyboard, focus, ARIA, touch, contrast, and reduced-motion behavior.
- Preserve every relevant v5 focused learning state after a node action starts.
- Define a separate finalized `question_feedback` state with exactly five
  child-usable assessment fields and one separate runtime action.
- Define scored, unclear, explicit-stuck, photo-uncertain, mobile, focus, and
  next-step behavior without requiring downstream model calls.

## Forbidden Scope

- No parent Web page, parent approval, parent grading, or operator dashboard.
- No second route or second learning runtime for the alternate view.
- No graph editor, child-authored relationship, or draggable node repositioning
  that changes saved graph facts.
- No force simulation that changes layout on reload.
- No mastery or learning-progress mutation from browsing or local preferences.
- No automatic selection merely because a node is recommended.
- No conversion of `未测试` into `不会`.
- No unexplained hard lock when prerequisites need preparation.
- No visible canonical graph/node/question/attempt/flow identifiers, graph-version
  codes, provider/model/agent names, prompts, rubrics, thresholds, confidence
  numbers, queues, jobs, retries, lineage, or raw error tags.
- No criterion, assessment, answer-contract, provider, prompt, confidence, job,
  or queue fields in per-question feedback payloads, DOM, ARIA, or copy.
- No teaching explanation disguised as a sixth feedback field or hidden inside
  the feedback state.
- No implementation architecture, DB schema, or production code changes in this
  document.
- No rendered `UX_REVIEW_PASS` claim without real browser evidence.

## Project Boundary Overlay

- This is a private learning system for one incoming Grade 7 child, not a generic
  educational product.
- The first phase supports summer prerequisite repair and Grade 7 mathematics
  preview.
- Every learning action remains graph-bound internally, but the child sees only
  child-readable names and explanations.
- A Grade 7 error first checks prerequisite gaps rather than starting a same-type
  drill list.
- The child page stays simple and age-respectful; complex teaching, assessment,
  model, queue, and evidence logic stays outside the child surface.
- The child may intentionally choose any visible node. Weak or uncertain
  prerequisites preserve the target and offer preparation rather than hiding the
  target.
- Visual quality must later be verified in a real browser on desktop and 390px.

## Target Users / Tasks

| User | Task | UX requirement |
|---|---|---|
| Child | Open the page and understand the mathematics territory | First visit opens the readable mind-map projection with one clear mode switch and no automatic task launch |
| Child | Scan knowledge by module and hierarchy | The mind map shows one virtual root, nine modules, and every real node exactly once |
| Child | Understand prerequisite direction and downstream impact | The graph uses arrowheads, directed depth, convergence, and visible cross-module bridges |
| Child | Move between the two explanations of the same knowledge | Switching preserves selected node and detail while each mode preserves its own viewport |
| Child | Choose a node intentionally | Selection opens one shared child-safe detail surface and never mutates learning state by itself |
| Child | Resume unfinished learning or inspect pending work | `map_home` shows one clear current-learning status and a focused resume action |
| Child | Start learning, diagnosis, review, preview, or challenge | The detail surface exposes only currently safe, asset-backed actions |
| Child | Use phone, keyboard, touch, or reduced motion | The same core tasks remain reachable without hover, precision dragging, color-only meaning, or animation dependence |
| Parent | Inspect evidence later through Codex | No parent/operator facts or controls appear in the child UI |

## Design Read

- Surface type: child learning navigation and progress projection, followed by
  the existing focused learning workspace.
- Audience/task: one Grade 7 learner who needs quick orientation, understandable
  choices, and a calm path into one current action.
- Aesthetic family: quiet, contemporary learning tool. Structured and spatial,
  but not a dashboard, marketing page, worksheet, game board, or technical graph
  inspector.
- Visual density: balanced. The canvas may contain all 56 nodes, while controls,
  labels, and detail content remain compact and scannable.
- Motion: feedback-only and spatially explanatory. Pan, zoom, focus, sheet, and
  mode transitions may use short transform/opacity motion; all nonessential
  movement is removed under reduced motion.
- Hard constraints: one page, one authoritative graph, one selected node, one
  focused learning step after action start, child-safe copy, 44px controls,
  stable layout, desktop and 390px support, no internal data leakage.

## Visual / Interaction Quality Bar

- The first viewport identifies the page purpose, active view, and current
  learning status without explanatory onboarding text.
- The segmented view control is visible without dominating the page and has a
  clear selected state that does not rely on color alone.
- `导图` reads as a hierarchy; `图谱` reads as a directed network. The two modes
  must not look like the same module-card grid with different line styles.
- The graph must not restore nine large closed module frames. Module identity may
  appear through labels, lanes, subtle guides, or node metadata, while the
  prerequisite topology remains visually primary.
- Arrowheads and labels make relationship direction understandable. Line color
  is supplementary, never the only direction or relation cue.
- A selected node, its detail, and its relevant relations are visually obvious
  without hiding the surrounding knowledge context.
- Primary action is singular in each detail state; secondary actions are
  subordinate and never visually compete.
- Node labels, toolbar controls, status copy, and bottom-sheet actions do not
  overlap or clip at 390px.
- Interactive controls provide visible focus and pressed/disabled feedback
  without changing layout bounds.
- All touch targets are at least 44x44px with at least 8px separation where
  adjacent taps could be confused.
- View switching, fit, focus, search, and filter feedback begins within 100ms
  after projection load on the local target machine.

### 56-Node Readability and Semantic Zoom

`represented`, `labeled`, and `directly interactive` are separate acceptance
concepts. Both projections represent all 56 real nodes at fit-all, but the UI
must not shrink 56 full labels and touch targets until they become unreadable or
overlap.

Required presentation levels:

| Level | Mind map | Directed graph | Readability / interaction contract |
|---|---|---|---|
| `fit_all` | Show virtual root and all nine module branches. On a first visit, all module branches start collapsed unless restoring a selected/current node requires one minimum ancestor path to open. | Show all 56 node markers, all lane/module orientation labels, and the reviewed overview backbone. | This is an orientation level. Full labels appear only where they meet the minimum type and collision rules. Overview-only markers that cannot provide a nonoverlapping 44px target are not direct node controls; search, module focus, and the accessible grouped list remain available for every node. |
| `module_focus` | Expand the chosen module, fit its branch, and show every node in that module once with full labels. Other modules remain collapsed or de-emphasized. | Fit the chosen module lane plus immediately connected bridge context and show full labels for its nodes and visible bridge neighbors. | The focused module occupies roughly 70-85% of the usable viewport without covering toolbar or detail surfaces. All visible labeled nodes are direct controls with at least 44x44px hit areas. |
| `node_focus` | Expand the minimum ancestor path, center the selected node, and reveal its primary path plus requested cross-prerequisites. | Center the selected node and reveal complete one-hop incoming/outgoing relations; optional two-hop expansion remains secondary. | Selected node and every shown one-hop label are readable, nonoverlapping, and keyboard reachable. Detail opening must not move the selected node fully behind the desktop panel or mobile sheet. |

Type and label rules:

- Desktop full node labels render at no less than 14px with line-height at least
  1.3; module/root labels render at no less than 16px.
- At 390px, full node labels render at no less than 15px with line-height at least
  1.35; detail/action text remains at least 16px; module/root labels render at no
  less than 17px.
- Full node names wrap to at most two lines. Do not use mid-word clipping,
  horizontal marquee, or font-size reduction below the minimum.
- When semantic zoom would push a label below the minimum or cause collision, the
  label changes to an overview marker rather than shrinking further. Selected,
  current-learning, and system-recommended nodes retain a readable short label
  or callout at fit-all.
- Overview markers use shape/state cues and an accessible text alternative, but
  they do not masquerade as 44px node buttons when their screen-space hit areas
  overlap.
- A visible `聚焦模块`, search result, grouped list item, or node relation action
  must take the child from an overview marker to a readable direct node control.
- `fit_all`, `module_focus`, and `node_focus` require desktop and 390px screenshot
  evidence in both modes. Tests must assert no label/control overlap and must
  distinguish all 56 represented nodes from the currently labeled controls.

## Superseded Clauses

| Earlier clause | v5.1 authority |
|---|---|
| Knowledge home is one full graph canvas | Knowledge home is one page with manual `导图 / 图谱` projections |
| Nine module regions are dominant visual containers | Mind map has nine module branches; graph has no nine dominant closed boxes |
| One stable layout serves all map behavior | Each projection has its own deterministic layout and local viewport |
| First visit opens the graph canvas | First visit opens `导图`; later visits restore the last valid local choice |
| Node selection belongs to one view | Selected node and shared detail persist across view switches |
| All relationship comprehension comes from graph edges | Mind map uses one display-parent tree plus on-demand extra prerequisite cross-links; graph shows directed prerequisite topology |

All underlying graph facts, child-safe state labels, learning activity projection,
mastery projection, target-intent safety, current-step authority, and action asset
eligibility clauses remain unchanged.

## Current Assessment Dependency Snapshot

As verified on 2026-07-14 for this UX source repair:

- `docs/architecture/answer_assessment_engineering_contract_v5_1.md` exists;
- `learning_system/assessment_policy.py` and
  `learning_system/assessment_store.py` exist;
- `tests/test_answer_assessment_v51.py` exists;
- `.env.local` does not currently set `ANSWER_ASSESSMENT_POLICY` or
  `KNOWLEDGE_MAP_HOME_POLICY`.

These facts mean implementation sources now exist. They do not prove that answer
contracts are complete, assessment policy is active, audits pass, or any node's
diagnostic/learning action is eligible. Until activation evidence exists, the
knowledge home may be implemented and reviewed with honest disabled/no-action
states, but no mutating node action may be presented as production-ready.

## Terminology Contract

The following names are fixed for downstream product, UX, engineering, review,
and QA artifacts. Engineering names in this table are not child-visible copy.

| Meaning | Contract name | Child-visible label / rule |
|---|---|---|
| Knowledge navigation home | `map_home` | `我的数学知识地图` or equivalent page title |
| Hierarchy projection mode | `mind_map` | `导图` |
| Directed prerequisite projection mode | `graph` | `图谱` |
| Focused learning workspace | `learning_step` | Current child-readable question/teaching/state heading |
| Finalized per-question result | `question_feedback` | `本题反馈`; exactly five feedback sections followed by one separate runtime action |
| Read-only content look | `preview` | `先看看这个知识点`; creates no intent or evidence |
| Diagnostic target action | `diagnostic` | `先检测一下` or state-appropriate diagnostic copy |
| Learning target action | `learn` | `开始学习`, `继续学习`, or `针对性学习` by state |
| Review target action | `review` | `复习这个点` or allowed recheck copy |
| Challenge target action | `challenge` | `挑战一下` |
| Map projection source | `GET /api/knowledge-map` | Never displayed as text |
| Mutating target selection | `POST /api/knowledge-map/select` | Never displayed as text; preview does not use this mutation path |
| Atomic activation policy | `KNOWLEDGE_MAP_HOME_POLICY` with v5.1 dual-view behavior | Never displayed or stored as child-readable UI preference |

Do not use `knowledge-map`, `mind map`, `tree`, `network`, `canvas`, or module-grid
phrases as competing child mode labels. The visible segmented labels remain
exactly `导图` and `图谱`.

## Information Architecture

The child `/` route contains two mutually exclusive top-level surfaces. Hidden
surfaces must not retain tabbable descendants.

1. `map_home`
   - page title and compact current-learning summary;
   - segmented `导图 / 图谱` control;
   - search and child-safe filters;
   - shared module navigation;
   - active projection viewport;
   - projection-specific controls and legend;
   - shared selected-node detail;
   - local fallback list when spatial rendering is unavailable.
2. `learning_step`
   - the existing focused v5 current-step surface;
   - exactly one current question, teaching, clarification, feedback, blocked,
     or summary action at a time;
   - no knowledge canvas rendered behind or around the focused task.

`map_home` is navigation and progress projection. It is not a learning step, an
assessment, or evidence.

## State Authority Bridge

The amendment adds map-home presentation states and preserves the v5 focused
learning states. It does not merge them into one visual surface.

| UX state | Owning surface | Required visible meaning | Exit |
|---|---|---|---|
| `map_home_loading` | `map_home` | Knowledge projections are loading; no fake nodes or learning claims | ready, unavailable, fallback |
| `map_home_ready` | `map_home` | One active projection, shared controls, current-learning summary, and selectable nodes | detail, preview, target action, focused learning |
| `map_home_no_results` | `map_home` | Search/filter has no local matches; graph data is not claimed empty | clear query/filter |
| `map_home_unavailable` | `map_home` | Projection cannot be loaded safely; current learning is preserved | retry, continue current learning, fallback |
| `map_home_stale` | `map_home` | Projection has changed and must refresh before mutation | refreshed ready or unavailable |
| `node_detail_open` | `map_home` | One shared selected-node detail in desktop panel or mobile bottom sheet | close, preview, target action |
| `node_no_available_action` | `map_home` detail | Node remains inspectable, but no safe mutating action can start | preview if eligible, relation navigation, close |
| `target_waiting_for_safe_boundary` | `map_home` status | The child-selected target is remembered while current save/analysis finishes | applied target, cancelled/replaced target, blocked |
| `current_analysis_pending` | `map_home` summary or focused `learning_step` after resume | Submitted work is saved and still being checked | question feedback, clarify, blocked, summary |
| `current_learning_blocked` | `map_home` summary or focused `learning_step` after resume | Saved work cannot yet be judged safely | real retry, summary, later recovery |
| `current_step` | focused `learning_step` | Existing v5 question or micro-check with one current action | analyzing, clarify, question feedback, blocked, summary |
| `question_feedback` | focused `learning_step` | One accepted assessment projected as exactly five child feedback sections plus one separate runtime action | next question, teaching, clarify, new knowledge, summary, retry, safe stop |
| `preparing_new_knowledge` | focused `learning_step` | Existing v5 honest preparation state | worked example, blocked, summary |
| `teaching` | focused `learning_step` | A separate worked example or teaching repair entered only after the feedback action selects teaching | micro-check, prerequisite repair, blocked, summary |
| `clarify_evidence` | focused `learning_step` | Existing v5 request for clearer evidence or cannot-provide closeout | analyzing, blocked, summary, safe switch |
| `ready_for_new_knowledge` | focused `learning_step` | Existing v5 checkpoint to continue or finish | teaching or summary |
| `summary` | focused `learning_step` | Existing terminal child-safe summary; no answer or next-question controls | stable terminal or safe return to map home |
| `load_error` / `save_error` / `upload_error` | interrupted owning surface | Existing v5 child-safe recovery with saved-work honesty | retry or restored prior state |

When `map_home` shows a summary of a focused state, it is a child-safe status and
resume entry, not a second rendering of the question, clarification, teaching,
blocked panel, or summary content.

## Page / Route Spec

| Page/route/surface | Purpose | Entry | Primary action | Secondary actions | Data needed | Exit states |
|---|---|---|---|---|---|---|
| `/` `map_home` | Orient, browse, select, and resume | Initial open, safe return from learning, cold reload | Select a node or continue current learning | Switch view, search, filter, module focus, fit, zoom, open detail | child-safe graph projection, local UI preference, current-learning summary, allowed node actions | selected detail, preview, focused learning step, pending/blocked status, unavailable/fallback |
| `导图` projection | Explain the full node set as one readable hierarchy | Active view is `导图` | Select a node | Expand/collapse branch, show extra prerequisites, focus module, pan/zoom | virtual root, module branches, display parent/order, cross-links, shared node data | shared detail or another projection |
| `图谱` projection | Explain strict prerequisite direction, convergence, and bridges | Active view is `图谱` | Select a node | Show one-hop/two-hop path, focus module, pan/zoom, fit all | stable directed layout, reviewed hard prerequisites, overview visibility, shared node data | shared detail or another projection |
| Shared node detail | Explain one selected node and offer safe actions | Node selection in either projection or fallback list | One state-appropriate action | One subordinate action, relation navigation, close | selected node, progress, mastery summary, prerequisite/downstream names and states, allowed actions | preview, target selection, focused learning step, restored projection focus |
| Focused `learning_step` | Run the existing v5 learning loop | An allowed mutating node action is safely applied, child resumes current learning, or accepted assessment feedback is ready | Do the one current action | Only the response modes allowed by the current v5 step | existing child-safe current-step projection plus exact v5.1 assessment feedback | analyzing, question feedback, clarify, teaching, blocked, summary, safe return to map home |

## Per-Question Finalized Feedback Contract

### Authority and Separation From Teaching

This section supersedes any v5 wording that visually merges answer feedback and
teaching into one `feedback_teaching` state.

- `question_feedback` is produced only from one accepted, finalized v5.1
  assessment and its deterministic score.
- The feedback object contains exactly five fields and renders exactly five
  content sections.
- A runtime-selected action follows the feedback object but is not a sixth
  feedback field.
- `teaching_explanation` is not rendered, serialized into the child feedback
  object, placed in a hidden panel, or announced by assistive technology while
  `question_feedback` is active.
- If the runtime action is `看讲解` or another teaching action, activating it
  leaves `question_feedback` and enters a separate `teaching` or
  `teaching_repair` step.
- The accepted-assessment reducer chooses the next runtime action without waiting
  for evaluation, planner, or teaching model calls. Feedback and its action must
  be available together as soon as the accepted assessment is committed.

Recommended child projection boundary:

```json
{
  "child_state": "question_feedback",
  "feedback": {
    "score_label": "10/10",
    "reference_answer": "...",
    "answer_gap": "...",
    "improvement_direction": ["..."],
    "expression_judgment": "..."
  },
  "action": {
    "label": "继续下一步",
    "target": "runtime-selected child state"
  }
}
```

The exact action transport may differ, but it remains outside `feedback` and
must not cause a second model wait before the child can act.

### Exact Five Sections

The child-visible order and labels are fixed:

| Order | Visible label | Field | Content rule |
|---|---|---|---|
| 1 | `得分` | `score_label` | Deterministic score on a 10-point scale, formatted as `x/10`; show one decimal only when needed |
| 2 | `标准答案` | `reference_answer` | Concise approved answer with only the steps necessary for this question |
| 3 | `与标准答案的差距` | `answer_gap` | What matched, valid alternative expression/method, missing evidence, and incorrect or contradictory evidence |
| 4 | `改进方向` | `improvement_direction` | One or two concrete actions the child can use on a later attempt or related question |
| 5 | `表达判定` | `expression_judgment` | Short confirmation of equivalent intent or the real ambiguity/contradiction that affected judgment |

Rules applying to all scores:

- Do not invent a weakness merely to fill `改进方向`. For a fully correct answer,
  use a maintenance/checking suggestion or state that no repair is required.
- `与标准答案的差距` must recognize valid alternative methods and equivalent
  notation; it is not a string-difference report.
- `表达判定` discusses whether the submitted expression is mathematically clear.
  It must not grade handwriting neatness, sentence style, capitalization, or
  omitted routine prose unless expression is an approved scoring target.
- Reference answer and gap text preserve mathematical symbols and line breaks,
  while remaining concise enough for one child question.
- The renderer creates semantic DOM with safe text nodes. Model-produced text is
  never interpolated into `innerHTML`.

### Score-Specific Presentation

| Case | Required child experience | Forbidden behavior |
|---|---|---|
| `10/10` | Calm confirmation of the correct mathematical result/method; gap names equivalence or no score-affecting gap; improvement may suggest one optional check or clearer future expression | Invented criticism, fireworks/gamified spectacle, durable mastery claim from one question |
| Partial score | Score remains prominent but not punitive; gap identifies supported and missing/incorrect parts; improvement gives one or two repairable actions | Reducing the result to only `部分正确`, hiding the standard answer, or overwhelming the child with every criterion |
| `0/10` | Neutral result, concise standard answer, first important mathematical gap, and one small restart direction | Shame language, giant red failure treatment, assuming the child learned nothing, or immediately dumping a teaching essay |

Score color may support hierarchy, but score meaning must remain available in
text. Do not add pass/fail, rank, mastery percentage, or criterion-level point
tables to the five-field surface.

### Unfinalized and Unscored Paths

The following paths do not render a scored five-field feedback surface because
there is no accepted finalized assessment:

| Path | Visible state | Required next action |
|---|---|---|
| Unclear or contradictory evidence | `clarify_evidence` | Ask for the one missing clarification; after accepted reanalysis, render the five fields for the original question |
| Photo uncertainty, unreadable work, or text/photo conflict | `clarify_evidence` or honest blocked state | Ask for clearer photo/text or allow cannot-provide; never show a provisional score |
| Explicit `我不会` / stuck | `support_requested` child acknowledgement | Record that the child is stuck with zero answer-analysis model calls, then offer the deterministic support/teaching/prerequisite/safe-stop action |
| Cannot provide clarification | Existing unscored pending/blocked summary path | Close without score or mastery update |
| Model/runtime failure | Existing blocked state | Preserve answer and offer real retry or safe summary; do not fabricate feedback |

An explicit stuck response is useful learning evidence about support need, but it
is not a completed scored answer. If the next action is teaching, teaching opens
as its own current step and remains distinct from the five-field contract.

### Feedback-to-Next-Step Interaction

- The answer form, photo controls, stuck choices, and previous submit button are
  hidden and inert while `question_feedback` is active.
- The child is never auto-advanced by timer. One runtime-selected action appears
  after the five sections.
- The action may continue to another question, open a separate teaching step,
  request clarification, start new knowledge, finish summary, retry, or safely
  stop. Its label describes the actual next state; do not use a generic
  `下一题` when the next state is teaching or summary.
- Activating the action is idempotent. While in flight, disable it with stable
  layout and state-specific pending copy.
- Refresh/back/reconnect returns the same current accepted feedback and action
  until that action is consumed or superseded by a newer accepted assessment.
- Moving to the next step does not delete or rewrite the accepted assessment;
  historical feedback remains available outside the current child action only
  when a later product surface explicitly provides that history.

### Feedback Focus and ARIA

- The feedback surface is a normal focused page state, not a modal or alert.
- Use one `h2` heading such as `本题反馈`, followed by five labeled semantic
  sections using the fixed order above.
- When feedback first replaces analyzing, send one short polite live announcement
  such as `本题反馈已准备好，得分 7/10`, then move focus once to the feedback
  heading. Do not place the entire feedback body in an assertive live region.
- Each field label is programmatically associated with its content. A list is
  used for one or two improvement directions.
- The runtime action is the final interactive control in DOM and Tab order.
- Visible focus remains on the action after activation fails; the error appears
  adjacent to the action with a retry path.
- No hidden teaching content, internal metadata, or inactive answer controls may
  remain in the accessibility tree.

### 390px Feedback Layout

- Render one single-column, full-width result flow or one modest result panel;
  do not nest five cards inside a parent card.
- `得分` is clear but not hero-scale. Recommended rendered size is 24-32px, with
  all section labels at least 16px and body text at least 16px/1.5 line-height.
- Keep the five-section order. Long reference answers, gap explanations, and
  mathematical expressions wrap without document-level horizontal scrolling or
  overlap.
- `改进方向` contains at most two short items.
- The runtime action is at least 44px high and full-width when that improves touch
  clarity. It follows the fifth section and respects the bottom safe area.
- The action may become a noncovering sticky footer only if the final section can
  still scroll fully above it and focus is never hidden behind it.

## Shared Dual-View Contract

### One Page, One Data Set, Two Projections

- Both modes render the same real node set and child-safe state at the same data
  freshness point.
- A state change received while one mode is active updates both projections; a
  later switch must not show an older local state.
- The active mode changes only presentation. It does not create a flow, step,
  target intent, attempt, assessment, progress event, or mastery decision.
- Search, filters, selected node, current-learning summary, and detail content are
  shared UI state.
- Pan/zoom and projection-specific disclosure are separate UI state.

### View Switch

- Use a compact segmented control labeled `导图` and `图谱`.
- First visit with no valid local preference selects `导图`.
- Later visits restore the last valid local mode from browser-local UI
  preference. Unknown, malformed, or obsolete values fall back to `导图`.
- Switching keeps the selected node, keeps the detail surface open, and recenters
  the same node in the destination projection when necessary.
- Switching does not reset search or filters.
- Each mode restores its own last viewport rather than copying the source mode's
  scale and position.
- The mode switch itself retains keyboard focus. A polite live announcement says
  which mode opened and whether a node remains selected; focus is not stolen by
  the recentered node.

### Independent Viewports

The browser may remember presentation preferences only:

- active mode, scoped to the v5.1 UI policy and intentionally independent of
  `projection_version`;
- mind-map scale and translation;
- graph scale and translation;
- optional mind-map branch collapse state;
- optional projection-specific relation-expansion state for the current browser
  session.

Active-mode storage uses one stable policy-scoped preference such as
`son-ai-knowledge-views:v5.1:active-view`. Viewport and collapse storage is scoped
by child-safe `projection_version`, because positions and branches may change.

On a projection-version change:

- keep the valid active mode (`mind_map` or `graph`);
- discard only incompatible viewport, collapse, and temporary path state;
- fit the active destination view safely;
- restore the selected node only when the refreshed projection supplies a safe
  continuity mapping; otherwise close detail and explain that the map updated;
- never fall back to `mind_map` merely because coordinates changed.

Viewport state is clamped against the current projection bounds before restore.
Invalid or incompatible viewport values fall back to fit-all for that mode only.
Local UI preferences are not sent as learning evidence and are not used for
planning, assessment, mastery, or reports.

## Mind-Map Projection Contract

### Primary Hierarchy

- The non-learning virtual root is labeled `我的数学知识体系`.
- The root has exactly nine reviewed module branches.
- Every real graph node appears exactly once in the primary display hierarchy.
- Each real node has one reviewed display parent for this projection.
- The display parent is a view configuration choice, not a new or stronger graph
  relationship.
- The virtual root and module labels are navigation/grouping controls, not
  learnable nodes and not included in the 56-node count.

### Multiple Prerequisites and Cross-Links

- When a node has multiple strict prerequisites, one appears in the primary tree
  path and every additional prerequisite remains available as a cross-link.
- Cross-links are not permanently drawn across the whole mind map.
- Selecting a node reveals its extra prerequisites in the shared detail and may
  draw only the currently relevant cross-link paths.
- An explicit child-readable action such as `查看其他前置知识` may expand those
  links. Closing or changing selection removes the temporary line field.
- If a linked node is inside a collapsed branch, the detail still names it and
  offers `定位到这个知识点`; activation expands only the minimum required
  ancestor path and focuses that node.
- Cross-link arrows preserve prerequisite direction and never imply that the
  chosen display parent is the only real prerequisite.

### Branch Interaction

- Module and non-leaf branch controls may collapse or expand descendants.
- Collapse changes visibility only; it never changes filters, node state,
  progress, mastery, recommendation, or action eligibility.
- Collapsed descendants are removed from visual and accessibility navigation,
  while the branch control announces `aria-expanded`.
- Search or direct relation navigation may temporarily expand the minimum path to
  a matching node. Clearing search restores the child's explicit collapse state.

## Directed Graph Projection Contract

### Topology

- The graph uses a deterministic directed layered topology based on reviewed
  prerequisite depth, learning stage, module lane, convergence, and reviewed
  bridge placement.
- Direction is visually stable from prerequisite toward downstream knowledge.
  Desktop and mobile keep the same logical direction even when viewport scale
  and visible area differ.
- Nine large closed module rectangles are forbidden.
- Module identity may use quiet lane labels, background guides, or small node
  metadata, but module decoration must not overpower edges, arrowheads, or
  convergence.
- Convergence nodes must visibly receive multiple incoming arrows.
- Cross-module bridges must remain legible through placement plus a non-color
  cue such as a bridge label, boundary marker, or relation summary in detail.

### Edge Visibility

- Only reviewed strict prerequisites are eligible for the initial child graph.
- The 35 unlock-only candidates remain hidden until a separate reviewed policy
  approves them.
- Fit-all overview shows a reviewed directional backbone rather than an equally
  strong 95-line field.
- Module focus may reveal more hard prerequisites within and immediately across
  the focused lane.
- Selecting a node always reveals its complete one-hop incoming prerequisites
  and outgoing continuations with arrowheads.
- `查看完整路径` may reveal two hops when it remains readable; it must not turn
  the full canvas into an undifferentiated line field.
- Unrelated nodes and edges fade but remain orienting context. Fading must not
  make text or controls fail contrast requirements.
- Reciprocal unlock-only candidates never appear as opposing child arrows.

### Graph Legend

The legend uses child language and visible shapes:

- arrow direction: `从要先会的知识，指向后面会用到的知识`;
- solid arrow: `需要先会`;
- optional future dashed relation appears only when approved support edges exist;
- selected path and bridge cues include text or shape, not color alone.

## Search, Filters, and Module Navigation

- Search matches child-readable node and module names only.
- Filters are shared across views: `全部`, `有学习记录`, `待巩固`, `未测试`.
- Search and filter results do not rewrite hierarchy or graph relationships.
- Nonmatching nodes may fade or hide according to readability, but the UI must
  preserve enough ancestors/context to explain where matches sit.
- A local no-result state appears inside the viewport with the query/filter
  summary and a clear `清除筛选` action; it is not treated as missing graph data.
- The module index focuses the same module in either projection. In `导图`, it
  expands and fits the module branch. In `图谱`, it fits the relevant lane and
  adjacent bridge context.
- Search, filter, and module controls remain usable without drag, wheel, hover,
  or precision pointing.

## Shared Node Selection and Detail Contract

### Selection

- A real node is selected by pointer, touch, Enter, or Space.
- Selection updates one shared selected-node state, `aria-selected`, relevant
  path emphasis, and the shared detail surface.
- Selection alone creates no target intent or evidence.
- Changing selection updates detail in place and returns focus according to the
  current input method; it must not unexpectedly launch learning.
- Switching view preserves the selected node even when that node is currently
  hidden by a collapsed branch or filter. The destination view minimally reveals
  and recenters it, while preserving the filter label and explaining the reveal.

### Detail Content

The detail surface contains:

- child-readable node name and state label;
- one-sentence essence when reviewed content exists;
- `学习历程` as completed activities, not understanding;
- mastery/evidence summary in child language without percentages or thresholds;
- prerequisite names and child-safe states;
- immediately downstream names and child-safe states;
- currently allowed primary and secondary actions;
- child-safe reason and recovery when an action is unavailable.

Node evidence and action readiness are shown separately:

- `evidence_state_label`: one of `未测试`, `学习中`, `待巩固`, or `暂时掌握`;
- `action_readiness_notice`: optional child-safe notice such as `需要先准备`,
  `当前答案批阅后可以开始`, or `学习内容暂时还没准备好`.

`需要先准备` must not replace or contradict the evidence state. For example, a
node may remain `未测试` while its action readiness says `需要先准备`.

### Action Descriptor Semantics

The detail renderer must receive ordered child-safe action descriptors rather
than infer primary/secondary/disabled behavior from an unordered action-code
list. Each candidate action carries the following UX meaning:

| Field | UX requirement |
|---|---|
| action | One of `diagnostic`, `learn`, `review`, `challenge`, or read-only `preview` |
| label | Final child-visible command for the current state |
| role | `primary` or `secondary`; at most one enabled primary and one command secondary |
| enabled | Native actionable/disabled state; disabled activation produces no mutation |
| disabled_reason | Required child-safe explanation whenever a visible action is disabled |
| pending_label | Child-safe in-flight text used after activation, such as `正在准备` or `批阅完成后切换` |
| result_behavior | Child-safe presentation meaning: enter now, wait for safe boundary, or open read-only preview |

Allowed disabled-reason meanings include:

- prerequisite preparation is needed;
- reviewed teaching content is not ready;
- a contract-backed question/assessment action is not ready;
- the current answer must finish saving or being assessed;
- the knowledge projection changed and must refresh;
- the learning service is temporarily unavailable.

The child sees only the explanation, never asset, contract, assessment-policy,
job, queue, handle, or status-code terminology. If all mutating descriptors are
disabled, keep one reason block, relation navigation, close, and an enabled
preview only when reviewed preview content exists.

### State-Appropriate Actions

| Child-safe state | Primary action | Secondary action |
|---|---|---|
| `未测试` | `先检测一下` | `开始学习` |
| `学习中` | `继续学习` | `回到当前学习` when this node owns the current safe step |
| `待巩固` | `针对性学习` | `再检测一次` only when current assets and runtime allow it |
| `暂时掌握` | `挑战一下` | `复习这个点` |
| `需要先准备` | `先补准备知识` | `先看看这个知识点` |

- `先看看这个知识点` is preview only and creates no learning activity,
  attempt, target intent, score, or mastery evidence.
- If the preferred action lacks a complete reviewed asset chain, it is disabled
  and the detail explains what is currently possible in child language.
- A disabled action is not silently hidden when its absence would confuse the
  child; it remains visibly unavailable with a short reason.
- The detail never offers more than one primary action.

## Current Learning and Runtime Boundary

- An unfinished safe current step appears on `map_home` as one clear
  `继续当前学习` action with the current child-readable topic and phase.
- Browsing or switching views never destroys an unfinished step.
- Starting or resuming a node enters the existing focused `learning_step` surface;
  the map and detail are then hidden and have no tabbable descendants.
- Submission, save, analyzing, finalized question feedback, clarification,
  separate teaching, blocked, and summary retain focused behavior. They do not
  render on top of the map.
- At a safe stop or explicit return point, the child may return to `map_home` or
  follow the runtime-selected continuation.

### Surface Precedence State Machine

Surface selection is deterministic and is not inferred from whichever API
returns first:

| Entry/event | Required surface | Required behavior |
|---|---|---|
| Policy off, unset, unknown, or dependency audit unavailable | Existing focused entry | Preserve the pre-v5.1 child page behavior; do not show a partial map-home shell |
| Policy enabled, cold initial open or browser reload | `map_home` | Open map home regardless of whether current learning is a question, analyzing, clarification, blocked, or summary; project that state as a child-safe resume/status banner |
| Child selects `继续当前学习` or `查看当前进度` | `learning_step` | Enter the existing focused state and move focus to its heading/current action |
| Child starts an eligible node action that applies immediately | `learning_step` | Hide/inert map home and show exactly one materialized current learning action |
| Child submits or continues from `learning_step` | Remain in `learning_step` | Keep the in-page save, analyzing, question-feedback, separate-teaching, clarify, blocked, or summary sequence focused; do not jump back to map home automatically |
| Child selects a target that must wait for a safe boundary | `map_home` until applied | Show the named waiting target and preserve current evidence; when applied after the child's explicit choice, enter `learning_step` exactly once |
| Child explicitly chooses return at a safe boundary | `map_home` | Refresh common node/current-learning projection, restore active view and its viewport, and keep current target context when relevant |
| Terminal summary reload | `map_home` | Show a concise completed-current-learning status and allow node browsing; opening the full summary is an explicit focused action if retained |
| Map projection fails while policy is enabled | `map_home_unavailable` | Preserve `继续当前学习` when a focused state exists; do not silently reinterpret this as policy-off |

`/api/child-bootstrap` remains the focused learning authority and
`/api/knowledge-map` remains the map projection authority. The frontend composes
them through this precedence table; response timing cannot decide the surface.

### Choosing Another Node During an Active Flow

- With an unanswered current step, choosing a new mutating action asks one
  low-input question: `继续当前学习` or `保存当前进度，切换到这里`.
- During submission, analysis, or reducer commit, the current transaction cannot
  be interrupted. The child may choose `批阅完成后切换到这里` or cancel.
- After that choice, `map_home` shows child-safe status such as
  `已经记住这个目标，当前批阅完成后会切换`.
- Submitted attempts and accepted assessments are never deleted by switching.
- Clarification is a stable boundary: choosing another node may preserve the
  unresolved clarification and switch immediately after the explicit child
  choice.
- After prerequisite probe or repair, the selected target remains named and the
  runtime returns to it unless the child selects a different target.

## Interaction Flows

| Flow | Trigger | Steps | Feedback | Recovery | Open UX decision |
|---|---|---|---|---|---|
| First visit | No valid local view preference | Load projection -> select `导图` -> fit root and nine modules -> announce ready | Active segment and map heading identify `导图` | Projection failure shows unavailable/fallback without inventing nodes | exact visual styling after rendered review |
| Returning visit | Valid local preference exists | Load projection -> restore mode -> validate that mode's viewport -> show current-learning status | Restored mode is visibly selected | Invalid mode falls back to `导图`; invalid viewport fits that mode only | none blocking |
| Switch view | Child activates inactive segment | Preserve selection/search/filter -> restore destination viewport -> reveal/recenter selected node -> retain detail | Polite announcement names mode and selected node | Render failure keeps source mode usable and offers list fallback | transition styling after rendered review |
| Select node | Pointer/touch/Enter/Space on node | Mark selected -> emphasize relevant relations -> open shared detail | Node name/state/detail visible | Missing reviewed detail content shows available child-safe fields and unavailable actions | none blocking |
| Mind-map branch | Expand/collapse control | Toggle descendants -> maintain selected node visibility -> update expanded state | Branch count/state is understandable without animation | Search/relation navigation temporarily expands minimum path | exact branch-count wording |
| Extra prerequisite | Selected node has more than one prerequisite | Open `查看其他前置知识` -> reveal cross-links/list -> optionally locate related node | Direction and relation named in child language | Hidden/collapsed target expands minimal path | none blocking |
| Graph path | Select node or choose `查看完整路径` | Show one-hop -> optionally two-hop -> fade unrelated context | Arrowheads and relation legend explain direction | If density exceeds readability, keep one-hop and relation list | two-hop visual threshold is implementation-tuned |
| Search/filter | Child enters query or selects filter | Update both projections' shared result set -> preserve graph truth/context | Match count and active filters announced politely | No results offers `清除筛选` | debounce timing is technical |
| Open detail on mobile | Select node at 390px | Open bottom sheet -> move focus to heading -> expose actions in order | Selected node remains visible or represented behind sheet | Escape/close restores focus and canvas position | sheet height after rendered review |
| Start node action | Child chooses enabled action | Confirm active-flow switch only when required -> create safe target choice -> enter focused learning when applied | Saved/waiting/applied state uses child language | Missing/stale eligibility returns to refreshed detail without dead-end | none blocking |
| Preview | Child chooses preview | Show reviewed teaching content -> no flow/evidence mutation -> return to same detail | Copy states that preview is only a look | Missing content disables preview with reason | exact preview layout after screenshots |
| Finalized question feedback | Accepted assessment is committed | Hide answer controls -> render exactly 得分/标准答案/与标准答案的差距/改进方向/表达判定 -> show one separate runtime action | Short polite ready announcement, then focus feedback heading | Action failure preserves feedback and offers adjacent retry; no planner/evaluation/teaching wait before feedback | exact visual tokens after rendered review |
| Feedback to teaching | Runtime action selects teaching | Leave feedback -> enter separate teaching step -> continue/stuck as that step allows | Child sees that teaching is the next step, not another feedback field | Teaching unavailable becomes honest blocked/summary; accepted feedback remains authoritative | none blocking |
| Unclear/photo uncertainty | Assessment cannot finalize safely | Keep original answer saved -> enter clarify state -> collect one missing piece -> reanalyze original question | No provisional score or five-field feedback | Cannot-provide closes unscored; model/runtime failure blocks honestly | none blocking |
| Explicit stuck | Child submits `我不会` or stuck | Record support request with zero answer-analysis calls -> show acknowledgement -> deterministic support/teaching/prerequisite/safe-stop action | Stuck is treated as useful support evidence, not 0/10 | No scored feedback or mastery update | exact acknowledgement copy after rendered review |
| Current analysis on cold reload | Previously submitted evidence is still being analyzed | Open `map_home` -> show `当前答案正在批阅` and `查看当前进度`/resume action | Copy begins with saved-work reassurance | Bounded result becomes current step, clarify, blocked, or summary | none blocking |
| Select target during analysis | Child chooses another node action | Explain non-interruption -> confirm `批阅完成后切换` -> show remembered target | Current answer remains saved; target remains named | Child may cancel or replace target before safe boundary | exact compact status placement |
| Blocked current learning | Runtime cannot judge safely | `map_home` stays browsable -> current-learning banner offers real retry or finish summary -> detail actions reflect runtime availability | Saved-work reassurance and pending label | Recovery enters focused analyzing or returns blocked/summary | none blocking |
| Stale projection | Action uses an old graph projection | Stop mutation -> preserve current learning -> refresh graph -> restore valid local mode/selection when possible | Child sees `知识地图有更新，正在重新载入` | If selected node cannot be restored, clear selection and explain | none blocking |
| Close detail | Close button or Escape | Close panel/sheet -> remove temporary relation expansion -> restore focus to originating node | Selected styling may remain until another selection or explicit clear | If originating node is hidden, minimally reveal it or focus active view heading | none blocking |
| Spatial render failure | Mind-map or graph initialization fails | Keep page controls/status -> show module-grouped accessible node list with same selection/detail/actions | Honest fallback copy | Retry spatial view without losing selection or current learning | none blocking |

## State Coverage

| Surface/action | Loading | Empty | Error | Success | Disabled/stale/permission |
|---|---|---|---|---|---|
| Page boot | Stable map-home skeleton; no fake node labels | No graph data becomes unavailable, not `未测试` nodes | Retry and continue-current action when available | Active mode, current-learning status, and projection appear | Old projection cannot mutate learning |
| View preference | Default `导图` until valid preference is read | Missing preference is normal first-use state | Malformed value ignored | Last valid mode restored | Obsolete value falls back to `导图` |
| Mind map | Root/module placeholders preserve viewport dimensions | Search/filter no-result message with `清除筛选` | Spatial failure opens accessible list fallback | Primary tree represents every real node exactly once; expanded/focused branches meet full-label rules | Collapsed descendants are non-tabbable; stale display config falls back safely |
| Graph | Stable viewport placeholder; no force-motion preview | Search/filter no-result message with `清除筛选` | Spatial failure opens accessible list fallback | All 56 nodes are represented at fit-all; readable direct controls appear at valid focus/zoom levels with directed backbone, arrows, convergence, and bridges | Unlock-only candidates stay hidden; stale layout cannot change graph truth |
| View switch | Inactive until destination projection is ready enough to render | n/a | Keep current mode and announce destination failure | Selection/detail retained; destination viewport restored | Disabled while bootstrap cannot supply either projection; no repeated activation |
| Search/filter | Local progress indicator only when computation exceeds 300ms | Clear no-result state | Preserve query and allow retry/clear | Matches and count update in both views | Controls disabled only while projection unavailable |
| Node selection | Pressed/focus feedback within 100ms | n/a | Keep originating focus and show retryable detail error | Shared detail and path emphasis appear | Hidden/filtered selected node is minimally revealed on switch |
| Node detail | Content skeleton with stable dimensions | Missing optional essence is omitted honestly | Child-safe unavailable message | State, activity, mastery, relations, actions shown | No available action: explain why, keep browsing/close available |
| Mutating node action | Disable repeated activation and show local pending feedback | No eligible asset chain means no action starts | Refresh eligibility; preserve selected target and current learning | Enters focused learning now or at safe boundary exactly once | Stale/old projection, analysis transaction, or missing assets prevent immediate start |
| Preview | Brief loading state with close path | Missing reviewed content disables preview | Return to detail with child-safe message | Read-only content shown | Never creates progress, evidence, target intent, or mastery |
| Question feedback | Stable five-section skeleton only after accepted assessment is known | n/a; unfinalized evidence stays analyzing/clarify/blocked | Preserve all five fields and runtime action; retry action only | Exactly five child fields plus one separate action | No criterion/provider/assessment/contract/job fields; no hidden teaching sixth field |
| Current learning banner | Skeleton does not invent topic/state | Hidden only when no active or pending current learning exists | Child-safe blocked/unavailable copy | Continue, pending, blocked, or summary status matches runtime | No internal phase/job labels |
| Analysis pending | Copy begins with `刚才的答案已经保存` | n/a | Bounded failure becomes blocked or summary | Accepted assessment produces question feedback; unclear evidence produces clarify | Dependent next step and interrupting switch are unavailable |
| Blocked | n/a | n/a | Real retry or finish summary; saved work preserved | Recovery resumes focused analyzing/current step | Retry disabled while in flight; no generic refresh disguised as recovery |
| Stale graph version | Refreshing state preserves current learning | n/a | Safe unavailable state if refresh fails | New projection loads and valid local preferences restore | Old handles/actions create no learning change |
| Mobile bottom sheet | Stable placeholder height if detail is loading | n/a | Error remains inside sheet with close action | Scrollable detail and sticky action area fit safe area | Background map is inert while modal sheet is open |
| Fallback list | Loading shares page skeleton | Module with no visible matches explains filter state | Retry spatial view | Same node selection/detail/actions as spatial views | No duplicate tabbable map controls while fallback is active |

## Loading, Empty, Unavailable, Pending, and Blocked Copy

Child-facing copy should be short, calm, and specific:

| Situation | Child-safe pattern |
|---|---|
| Initial load | `正在打开你的数学知识地图。` |
| Current analysis on map home | `刚才的答案已经保存，正在批阅。你可以查看进度，也可以先浏览知识地图。` |
| Target waiting for analysis | `已经记住“{知识点名称}”。当前批阅完成后会切换到这里。` |
| Local no search results | `没有找到符合这些条件的知识点。可以清除筛选再看看。` |
| No available learning action | `这个知识点现在还不能安全开始。你可以先看看相关知识，或选择别的知识点。` |
| Missing reviewed content | `这个知识点的学习内容还在准备，暂时不能开始。` |
| Stale projection | `知识地图有更新，正在重新载入。刚才的学习不会丢失。` |
| Graph unavailable | `知识地图暂时打不开。当前学习还在，可以重试或继续当前学习。` |
| Blocked current learning | `刚才的学习已经保存，但现在还不能安全判断。可以再试一次，或先完成今天的总结。` |
| Spatial fallback | `图形暂时没有显示出来，先用知识点列表继续查看。` |

Copy must never mention internal identifiers, graph versions, HMAC/handles,
provider/model/agent names, OCR confidence, prompts, rubrics, thresholds, queue,
job, reducer, idempotency, lineage, stack traces, or configuration keys.

## Desktop Responsive Contract

- `map_home` uses the available viewport as a work surface, with stable toolbar
  and canvas dimensions rather than floating page-section cards.
- The title/current-learning summary, segmented view switch, search, filters, and
  zoom controls form a compact, predictable toolbar that does not wrap into
  incoherent rows at supported desktop widths.
- The active projection remains the primary full-width surface.
- Shared detail appears as a right-side complementary panel without nesting one
  card inside another.
- The detail panel has a constrained width and independent content scroll only
  when necessary; primary actions remain reachable without covering node labels.
- A minimap may appear in graph view on desktop. It is secondary, keyboard
  skippable, labeled, and hidden when it would duplicate or obscure the main
  projection. Mind map does not require a minimap if module navigation and fit
  controls provide equivalent orientation.
- Zoom in, zoom out, and fit controls use familiar icons with accessible labels
  and tooltips. Gesture-only zoom is insufficient.

## 390px Mobile Contract

- Required acceptance viewport: 390x844 CSS pixels, with additional checks for
  browser text enlargement and safe-area insets.
- Page layout uses `min-height: 100dvh`; the document itself has no horizontal
  scrolling. Pan and zoom occur only inside the bounded projection viewport.
- The top area stacks into compact rows: title/current status, segmented view
  control, then search/filter access. The active view remains visible without a
  hero-scale heading.
- The segmented control remains fully visible and each segment has a 44px touch
  target.
- Module index and secondary filters may use a menu or sheet rather than a long
  row of narrow pills.
- Minimap is hidden on mobile. Visible fit, zoom, search, and module-focus
  controls provide equivalent navigation.
- Selecting a node opens a bottom sheet with a visible heading, close control,
  child state, activity/mastery summaries, relations, and actions.
- The mobile bottom sheet behaves as a modal dialog: focus moves into it, the
  background projection becomes inert, Escape/close dismisses it, and focus
  returns to the originating node.
- The sheet respects bottom safe area, keeps a 44px close target, and may scroll
  internally. Its primary action area stays reachable without hiding final text.
- At least a clear strip of the active projection remains visible behind the
  sheet so spatial context is not lost, unless accessibility text enlargement
  requires a full-height sheet.
- Long Chinese node names and action labels wrap to a second line rather than
  clipping, shrinking below readable size, or overlapping neighboring controls.

## Pointer, Touch, Pan, and Zoom Contract

- The projection viewport is a bounded spatial work surface. Document-level
  horizontal scrolling is forbidden; panning changes only the active view's
  local viewport.
- Desktop pointer drag begins only from empty viewport space or an explicit pan
  surface. Pressing a node remains a node action until movement exceeds an 8px
  drag threshold.
- If movement exceeds 8px, cancel the pending node activation and pan. Releasing
  after a pan must never open a node detail accidentally.
- Touch uses one-finger drag inside the viewport for pan and two-finger pinch for
  zoom. A node tap opens detail only when movement remains within the threshold.
- Browser/system edge gestures remain available. Do not start canvas pan from the
  protected screen-edge gesture area.
- On 390px, vertical movement that begins inside the projection pans the bounded
  view; vertical movement that begins in the page toolbar, current-learning
  banner, or outside the viewport scrolls the document normally.
- When the modal bottom sheet is open, its content owns vertical scrolling and
  the background viewport is inert; drag must not leak through to pan the map.
- Desktop wheel input zooms around the pointer only while the viewport is focused
  or the user holds Ctrl/Meta. Otherwise normal page scrolling is preserved.
- Pinch/wheel zoom is clamped to the projection's validated min/max scale. The
  child always has visible zoom-in, zoom-out, and fit controls; gestures and
  keyboard shortcuts are supplementary.
- Fit, module focus, node focus, and view switching preserve the focused control
  rules defined below. Reduced motion makes camera changes immediate.

## Keyboard, Focus, and ARIA Contract

### Page and View Switching

- Use one `main` landmark and clear headings for `map_home` and focused learning.
- Implement the segmented control as a native radio group or equivalent
  `radiogroup` with accessible label `知识展示方式`.
- The active segment exposes selected/checked state. Arrow keys move within the
  group; Space selects; Tab leaves the group.
- Switching keeps focus on the chosen segment and announces the new active view
  through a polite live region.
- The active projection has an accessible name:
  - `我的数学知识导图`;
  - `我的数学知识图谱`.
- Only the active projection is exposed to the accessibility tree and keyboard.

### Nodes and Spatial Navigation

- At `module_focus` and `node_focus`, every visible labeled real node has one
  uniquely named programmatically focusable control.
- The accessible name includes node name and child-safe state, but excludes raw
  ids and internal codes.
- The active projection is one named composite keyboard region with roving
  tabindex. Exactly one visible node control has `tabindex="0"`; other visible
  node controls have `tabindex="-1"`. Tab enters at the current/selected/first
  visible node and the next Tab leaves the projection.
- In the mind map, Left/Right moves parent/first child or collapses/expands the
  current branch; Up/Down moves to the previous/next visible tree item.
- In the graph, arrow keys move to the nearest visible node in that spatial
  direction, with deterministic tie-breaking by rank, lane, and order.
- `Enter` or `Space` selects the focused node and opens detail. Home focuses the
  first visible node in the focused module; End focuses the last.
- Visible focus is at least 2px and remains distinguishable at all node states.
- Search results, module navigation, relation `定位` actions, and fallback-list
  items move the camera first and then move focus to the resulting readable node
  control. Under reduced motion this happens immediately.
- At fit-all, overview-only markers are not inserted into the Tab sequence.
  Search, module navigation, and the accessible grouped node list provide direct
  access to every one of the 56 nodes.
- Mind-map branch controls expose `aria-expanded`; collapsed descendants are not
  focusable or announced as visible.
- Graph arrow paths are not separate focus stops unless they provide an explicit
  relation action. Their meaning is summarized in selected-node detail and the
  accessible legend.

### Detail and Focus Restoration

- Desktop detail is a labeled complementary region. When opened by keyboard,
  focus moves to its heading or first available action according to the existing
  page pattern.
- Mobile detail is a modal dialog with `aria-labelledby` pointing to the node
  heading and a clearly named close control.
- Escape closes detail in both layouts.
- Closing restores focus to the originating node without resetting viewport,
  search, filter, mode, or selection.
- If the node became hidden, the UI minimally reveals it before restoring focus;
  if that is impossible, focus moves to the active projection heading and a
  polite message explains the change.

### Dynamic State and Errors

- A polite live region announces projection ready, view switched, search result
  count, target remembered, analysis pending, and stale projection refresh.
- Blocking load/action errors use a focusable error region or `role="alert"`
  only when immediate attention is required.
- Disabled controls use native disabled semantics and a visible explanation;
  they do not rely on reduced opacity alone.
- Loading indicators have accessible names and do not spin indefinitely.
- Color is never the only indicator for selected, recommended, untested,
  learning, weak, mastered-for-now, pending, blocked, bridge, or direction state.

## Motion and Reduced Motion

- Default transitions use transform and opacity only and generally complete in
  150-300ms.
- Pan and pinch/wheel zoom track direct input without decorative easing.
- View switching may crossfade the projection and animate recentering only when
  it helps spatial continuity.
- Node focus may emphasize the selected path, but unrelated nodes must not pulse,
  orbit, or continuously move.
- Under `prefers-reduced-motion: reduce`:
  - view changes are immediate;
  - recentering and fit operations jump without animated travel;
  - bottom sheet appears without sliding motion;
  - loading uses a static or minimally changing indicator;
  - no information depends on animation sequence.

## Child-Safe Data and DOM Boundary

The child payload, rendered text, accessible names/descriptions, DOM attributes,
URLs, error messages, analytics labels, and local preference values must not
expose:

- canonical graph or node ids;
- question, attempt, assessment, flow, step, packet, or lineage ids;
- provider, model, agent, prompt, contract, rubric, threshold, confidence,
  queue, job, reducer, or retry internals;
- raw stack traces, database keys, filesystem paths, or configuration names.

Opaque transport values may exist only where required for safe interaction. They
must not be rendered as child-readable text, accessible labels, CSS classes,
test ids derived from canonical ids, or learning history stored by the browser.

## Implementation Handoff

听云 should consume this amendment with the v5 base UX spec, v5.1 PRD amendment,
knowledge-map design, and engineering plan. The engineering contract must define:

- one shared child-safe projection feeding both views;
- separate deterministic mind-map and graph layout/view configuration;
- the three semantic-zoom levels and viewport-specific first-load collapse rules;
- reviewed display-parent and branch-order configuration with graph-valid
  cross-link preservation;
- directed graph rank/lane/backbone/bridge visibility without nine closed boxes;
- one shared selection/detail/action state;
- ordered child-safe action descriptors with primary/secondary, disabled reason,
  pending label, and result behavior;
- separate evidence-state and action-readiness presentation;
- policy-scoped active-mode preference independent of projection version;
- projection-scoped independent clamped viewport and collapse persistence;
- stale preference and stale graph projection recovery;
- deterministic boot/resume/submit/safe-return/policy-off surface precedence;
- roving-tabindex spatial keyboard navigation and touch/pan/pinch boundaries;
- focus, inert/hidden surface, ARIA, live-region, and reduced-motion behavior;
- mobile bottom-sheet state and focus restoration;
- fallback list parity with both spatial views;
- current-learning, analysis-pending, blocked, safe-boundary switch, preview, and
  no-action projections;
- a distinct `question_feedback` focused state sourced only from one accepted
  assessment;
- an exact five-key child feedback object in fixed visible order, with the
  runtime-selected action outside that object;
- safe text-node rendering for reference answer, gap, improvement, and expression
  judgment; no model text interpolation through `innerHTML`;
- immediate feedback/action projection after the accepted reducer, with no
  evaluation, planner, or teaching model wait;
- strict separation between feedback and a later teaching/teaching-repair step;
- unscored clarify, photo uncertainty, stuck, cannot-provide, and blocked paths;
- child payload and DOM forbidden-field scans.

Do not implement from the older single-canvas module-grid assumptions. Do not
change graph truth to make the mind map easier to draw.

## Review / QA Implications

Rendered review and QA must inspect real browser behavior, not code structure or
screenshots alone.

Required desktop and 390px scenarios:

- first visit opens `导图`;
- a later reload restores the last valid selected mode;
- projection-version refresh preserves active mode while resetting only
  incompatible viewport/collapse state;
- all 56 real nodes and nine modules are represented in both projections;
- fit-all, module-focus, and node-focus satisfy the defined label/type/hit-area
  rules on desktop and 390px;
- each mind-map node appears once in the primary tree;
- multi-prerequisite nodes retain every extra prerequisite as an on-demand
  cross-link;
- graph has visible arrow direction, convergence, bridges, prerequisite depth,
  and no nine dominant closed boxes;
- switch preserves selected node, detail, search, and filters;
- mind-map and graph restore different saved viewport states;
- search, filter, module focus, fit, zoom, pan, branch collapse, path expansion,
  close detail, and fallback list work;
- drag beyond 8px never opens detail; tap, pinch, wheel, page scroll, and bottom
  sheet gesture ownership match the pointer/touch contract;
- one Tab enters and one Tab exits the active projection; arrow-key roving reaches
  readable nodes without a 56-stop Tab chain;
- action descriptors render one primary, at most one command secondary, disabled
  reason, pending label, and no-action recovery without frontend inference;
- node actions cover untested, learning, weak, mastered-for-now,
  prerequisite-not-ready, preview, and no-action states;
- policy-off uses focused entry; policy-on cold reload uses map home; submit stays
  focused; explicit safe return restores map home;
- pending analysis and blocked current-learning banners preserve saved-work
  honesty;
- finalized `10/10`, partial, and `0/10` cases render exactly `得分`, `标准答案`,
  `与标准答案的差距`, `改进方向`, and `表达判定` in that order;
- the serialized `feedback` object contains exactly `score_label`,
  `reference_answer`, `answer_gap`, `improvement_direction`, and
  `expression_judgment`; the action is a sibling and teaching explanation is
  absent from payload, DOM, hidden content, and accessibility tree;
- 10/10 feedback recognizes valid equivalence without inventing a flaw; partial
  and 0/10 feedback stays specific, calm, and repairable;
- unclear/clarify and uncertain-photo cases show no provisional score, then show
  one five-field feedback state only after accepted reanalysis;
- explicit stuck uses the unscored support path and never displays `0/10` or a
  fabricated standard-answer comparison;
- feedback appears without evaluation/planner/teaching calls; choosing teaching
  enters a separate focused state;
- at 390px all five sections wrap without horizontal scroll, the action follows
  section five, and focus/live announcements match the feedback ARIA contract;
- stale projection prevents mutation and recovers without losing current flow;
- desktop complementary detail and mobile modal bottom sheet have correct focus
  entry, Escape/close, and focus restoration;
- every visible node is keyboard reachable and uniquely named;
- active/hidden surfaces have correct accessibility-tree and Tab behavior;
- `aria-live`, disabled semantics, 44px targets, text enlargement, contrast, and
  reduced motion are verified;
- API payload and DOM contain no forbidden internal fields.

## Non-Blocking Visual Decisions for Rendered Review

- Exact palette, typography tokens, node shape vocabulary, bridge marker, and
  panel dimensions may be tuned against the first faithful prototype.
- Exact two-hop density threshold and cross-link line routing may be tuned for
  readability, but one-hop completeness and relationship preservation are not
  optional.
- Exact bottom-sheet height may be tuned at 390px, but content order, safe-area
  handling, close control, action reachability, and focus restoration are fixed.

## UX_FLOW_SPEC Self-Review

- product_source_ready: pass
- same_page_same_data_two_projections_explicit: pass
- mind_map_virtual_root_nine_modules_single_display_parent_explicit: pass
- extra_prerequisite_cross_links_preserved: pass
- graph_directed_backbone_arrow_convergence_bridge_explicit: pass
- nine_closed_graph_boxes_forbidden: pass
- first_visit_mind_map_and_local_mode_memory_explicit: pass
- shared_selection_and_independent_viewports_explicit: pass
- active_view_independent_of_projection_version_explicit: pass
- fit_all_module_focus_node_focus_and_type_minimums_explicit: pass
- default_collapse_and_semantic_zoom_explicit: pass
- action_descriptor_and_disabled_reason_semantics_explicit: pass
- evidence_state_and_action_readiness_separated: pass
- roving_tabindex_and_touch_gesture_boundaries_explicit: pass
- surface_precedence_state_machine_explicit: pass
- assessment_sources_present_but_activation_not_claimed: pass
- finalized_question_feedback_exactly_five_fields_explicit: pass
- feedback_and_teaching_separated: pass
- score_10_partial_0_presentation_covered: pass
- unclear_stuck_photo_uncertainty_unscored_paths_covered: pass
- feedback_runtime_action_without_downstream_model_wait_explicit: pass
- feedback_390px_keyboard_focus_aria_covered: pass
- feedback_child_safe_forbidden_fields_explicit: pass
- loading_empty_no_action_pending_blocked_stale_fallback_covered: pass
- desktop_and_390px_bottom_sheet_covered: pass
- keyboard_focus_restoration_aria_and_reduced_motion_covered: pass
- node_detail_actions_covered: pass
- child_safe_internal_data_boundary_covered: pass
- existing_v5_focused_learning_runtime_preserved: pass
- implementation_authorized: no
- rendered_ux_pass_claimed: no
- blocking_gaps_for_technical_planning: none

## Stop Condition

This amendment is ready for technical planning and engineering-contract work as
the UX authority for the dual knowledge views and v5.1 per-question child
feedback. It changes no production code, does not activate v5.1, and still
requires independent engineering review, browser-backed UX review, and QA before
release.
