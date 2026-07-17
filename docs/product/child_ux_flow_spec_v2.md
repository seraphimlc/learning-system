### UX_FLOW_SPEC - 清秋（agentKey: `qingqiu`）- 2026-07-08 03:29 CST

Objective:
Define the planned UX/page/route/interaction-state contract for the single child-facing math learning page. The page must let the child independently complete diagnosis/remediation and new-knowledge loops: understand the current task, answer openly, upload a photo when useful, save and advance without waiting for grading, see all-question review after a 10-task round, and know the next action.

Source product structure:
- `docs/product/ai_native_math_learning_prd_v2.md` `PRD_SPEC`, `PRODUCT_STRUCTURE_SPEC`, and `PROJECT_BOUNDARY_OVERLAY`.
- Fact sources checked: `AGENTS.md`, `docs/domain-index/math-learning.md`, `docs/system/local_learning_system.md`, `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`.
- Current implementation evidence was used only to understand existing route/state vocabulary; this spec is the planned contract, not an implementation review.

Scope:
- One child-facing Web page at `/`, serving both active learning and end-of-round review.
- Child states: loading, no active group, active task, answer draft, saving, saved/advance, all 10 submitted, reviewing, review ready, next action ready, retryable error, blocked/wait-later.
- Supported input: open text answer and optional PNG/JPG/WebP photo upload.
- Supported learning loops: diagnostic/remediation round and new-knowledge round, both child-safe and free of parent intervention.
- Page/page-state/copy/accessibility/responsive contract for 听云 to design the route shell and page skeleton.

Forbidden scope:
- No production implementation code changes in this artifact.
- No parent dashboard, manual grading page, graph/debug panel, model config page, rubric viewer, agent report UI, or copy-to-Codex instruction.
- Do not expose graph node ids, question ids, attempt ids, session ids, model names, agent names, rubrics, reviewer records, OCR confidence, queue internals, or operator actions to the child.
- Do not expand beyond the PRD: math only, single child only, local/private next cycle only.

Project boundary overlay:
- Source: `docs/product/ai_native_math_learning_prd_v2.md` `PROJECT_BOUNDARY_OVERLAY`.
- Stable: single-child AI-native math learning system for summer bridge; child uses one Web child端; parent uses Codex, not a dashboard; normal learning requires no parent intervention; each teaching/diagnosis/question/attempt/evaluation/plan/evolution event is graph-bound internally; active round size target is 10 tasks; answer photos are supported and treated as untrusted evidence; child copy hides internal graph/model/agent concepts.
- Provisional: final visual taste and exact child copy need rendered review.

Target users / tasks:
- User: incoming Grade 7 child, capable of focused reasoning tasks; UI should feel capable, calm, and age-respectful, not幼儿化.
- Primary tasks:
  - Start or continue the current math group.
  - Read one current prompt and any concise concept/model support.
  - Type reasoning/steps in an open answer field.
  - Optionally upload or remove a paper-work photo.
  - Save the answer and move on immediately.
  - After all 10 tasks are submitted, understand that review is happening without needing the parent.
  - When review is ready, read a summary that covers all relevant questions and take the next action.

Design read:
- Surface type: focused single-task learning workspace, not dashboard, landing page, or game.
- Audience/task: incoming Grade 7 learner doing cognitively demanding math; interface must reduce uncertainty and preserve momentum.
- Aesthetic family: quiet study tool with polished editorial clarity; neutral background, high-contrast text, restrained accent colors, stable grid, no mascot/childish illustration, no decorative blobs or marketing hero.
- Visual density: medium. The current task, progress, answer tools, and primary CTA should be visible without scrolling on desktop for typical prompts; mobile may scroll but must keep task/progress/action ordering predictable.
- Motion: minimal and purposeful only: save feedback, progress change, review polling status. Must respect reduced-motion.
- Hard constraints: one page; no backend workflow language; no internal ids; no parent action; no feature-explanation blocks; all controls readable and touch-friendly.

Visual quality bar:
- Hierarchy: the child can identify "where I am", "what problem I am doing", "where to answer", and "what button to press" within 3 seconds.
- Layout rhythm: one un-nested main panel or equivalent focused surface; task text and answer area have stable dimensions; photo preview, errors, and review cards must not shift controls unpredictably.
- CTA/readability: one primary CTA per state. Button labels must match the action: `保存，下一题`, `保存，完成这一组`, `再看一次结果`, `开始下一组`, or equivalent child-safe copy.
- State completeness: every listed state must have visible feedback and a recovery path. End-of-round review must summarize all relevant questions, not only the last one.
- Copy tone: calm, direct, capable. Use "系统正在看你的步骤" level wording, not "AI/model/agent/OCR/graph is running"; no blame language, no gamified pressure, no parent-dependency language.
- Responsive behavior: desktop centered max-width learning surface; mobile single column with 44px+ touch targets, full-width primary CTA, photo preview contained, no clipped text.
- Accessibility: semantic headings, form labels, focus-visible states, keyboard reachable file picker/remove/submit/retry actions, status messages via polite live region, sufficient contrast, no color-only result meaning.
- Evidence expected later: rendered desktop and mobile screenshots for active, photo-preview, saving/error, reviewing, review-ready, and no-group states; keyboard/focus check; text-overflow check.

Information architecture:
- Persistent top area:
  - Page title: current group framing such as `今天先完成这一组`.
  - Readiness/status chip: only child-safe page readiness such as `准备好了`, `连接失败`, `正在保存`; no provider/DB/model labels.
  - Progress: `第 N / 10 题` and `已保存 M` with a simple progress bar.
- Main task area:
  - Task type label: child-safe kind such as `新知识`, `小检测`, `再稳一下`, `先补一步`, `练习`.
  - Current prompt block: concise concept/model support if needed, then the problem.
  - Optional support tabs/actions are allowed only if they directly help answering: `看例子`, `我来试`, `卡住了`. They must not become a tutorial about the system.
- Answer area:
  - Labeled open textarea for answer and steps.
  - Photo upload affordance with preview and remove action.
  - Primary save-and-advance action.
- Handoff/review area:
  - Replaces the answer form once all tasks are submitted or review is ready.
  - Contains one short state message, all-question review summary when ready, coaching/next-step points, and one primary next action.

Page / route spec:

| Page/route/surface | Purpose | Entry | Primary action | Secondary actions | Data needed | Exit states |
|---|---|---|---|---|---|---|
| `/` child learning page | Single child learning surface for current group | Browser open or refresh | Continue current task | Retry load when failed | child-safe bootstrap: plan title, 10 task positions, task kind labels, prompt, answer format, submitted positions, closure status/message | active task, no group, reviewing, review ready, blocked |
| `/` active task state | Let child answer one task | Loaded group has at least one unsubmitted task | Save text/photo and advance | Upload/remove photo, use stuck prompt, switch answer support tab | current task position, child-safe prompt/support, submitted positions | next task, all-submitted reviewing, retryable save error |
| `/` all-submitted reviewing state | Explain that the round is saved and being reviewed | 10/10 submitted and review pending | Refresh/retry review status | Leave page and return later | closure status, pending message, safe retry interval | review ready, blocked/wait-later |
| `/` all-question review summary state | Show round results and next action | closure status planned/review ready | Start next planned group or next recommended action | Re-read review points | child message, review points for all relevant tasks, coach points, next action label | next group active, no group |
| `/` no active group state | Avoid confusion when there is nothing to do | bootstrap has no tasks | None or retry load if transient | Refresh page | empty child-safe message | active task if new group appears |

Interaction flows:

| Flow | Trigger | Steps | Feedback | Recovery | Open UX decision |
|---|---|---|---|---|---|
| Start/continue group | Child opens `/` | Load child bootstrap -> show title/progress -> select first unsubmitted task | Loading state then `第 N / 10 题`, `已保存 M` | Retry load button/message if bootstrap fails; no internal error text | Final exact title copy after rendered review |
| Answer with text | Child types in textarea | Enter steps/reasoning -> press primary CTA | Button enters saving state; on success answer clears and next task appears | If empty and no photo: prompt `先写一点步骤，或拍一张纸面答案`; if save fails, keep draft and show retry | Whether to autosave drafts is not in current PRD; do not require it for skeleton |
| Answer with photo | Child chooses/captures image | Validate type/size -> show thumbnail/name/remove -> save with text or photo-only | Preview confirms selected paper work; success clears photo and advances | Unsupported/too-large/read failure uses child-safe message and allows reselect; failed save keeps selected evidence if technically feasible | Exact accepted-file wording may adjust after visual review |
| Save and advance | Child submits a valid answer | POST submission by group handle + task position -> do not wait for grading -> move to next unsubmitted task | Toast/status `已保存，继续下一题` or equivalent; progress increments | Duplicate/stale group errors say refresh/continue safely, not internal conflict details | None |
| Finish 10th task | Child saves task 10 | Save answer -> call/enter completion check -> replace form with reviewing state | `这一组已保存` and short message that steps/photos are being reviewed | Poll/retry review status; child can leave and return later | Poll cadence and exact timeout owned by engineering/QA |
| Review pending | Closure status waiting | Show reviewing state with primary `再看一次结果` or passive auto-refresh | Message says no need to wait on page; no parent action | Retry button; blocked state if review cannot continue | Copy can be tightened after real latency evidence |
| All-question review ready | Closure status planned/review ready | Show title -> review points grouped by task -> coach/next-step points -> primary next action | Summary covers each relevant question/gap; next action is explicit | If starting next group fails, keep review visible and show retry | Exact result labels should be data-contract aligned |
| Blocked/retry later | Closure status blocked or unrecoverable request failure | Show saved-state assurance and retry-later action | Child understands work is saved and can rest/return | `稍后再看` / refresh status; no instruction to ask parent | Whether a non-child operator alert exists is outside child UI |
| New-knowledge loop | Planner serves a learn/check/consolidate task | Show concise concept/model -> child answers -> review later gives explanation/next check | Task label `新知识` or `小检查`; answer prompt asks for reasoning | Wrong/partial review leads to explanation/retry/repair next action | Exact lesson copy belongs to teaching/content contracts |
| Diagnostic/remediation loop | Planner serves diagnostic/remediate/rollback task | Child answers 10 graph-bound tasks -> review identifies gaps -> next action repairs/prereq/variant | Task labels signal purpose without exposing graph | Same reviewing/retry behavior as above | None |

State coverage:

| Surface/action | Loading | Empty | Error | Success | Disabled/stale/permission |
|---|---|---|---|---|---|
| Bootstrap/page load | Skeleton or concise `准备中` with no fake task | `今天先休息一下；暂时没有新的数学任务` | `连接失败，请再试一次` with retry; no stack/API text | Shows current task/progress | If group expired, say `这一组状态变了，请刷新后继续` |
| Active task | Prompt area stable while rendering | Not applicable if task exists | Missing prompt uses safe fallback and should be QA-blocking later | Task type, prompt, answer area visible | Submitted tasks are skipped; child cannot resubmit hidden answered task |
| Text answer | Textarea ready and labeled | Empty allowed only if photo exists | Empty submit says write steps or photo | Text included in saved answer | During saving textarea/CTA may disable but draft remains visible |
| Photo upload | File picker ready | No photo selected shows optional hint | Unsupported type, too large, unreadable photo get specific child-safe messages | Thumbnail/name/remove visible | Remove action always reachable; upload disabled only during save if necessary |
| Save CTA | Button label reflects next/finish | Not applicable | Save failure keeps child on same task with draft and retry | Advances immediately after saved, not after grading | Button disabled while saving; stale/duplicate message is child-safe |
| All 10 submitted | `正在整理这一组` | Not applicable | Completion-check failure shows retry status, not parent ask | Reviewing state appears | Form hidden to prevent extra submissions |
| Reviewing | `正在看你的步骤和照片` / progress-safe message | Not applicable | Blocked state says saved and can return later | Review-ready state replaces pending | Retry button throttled/disabled during request; no internal queue details |
| Review summary | Review points loading only while pending | If no review points but planned, show next action and a QA-visible gap | Failed next-group start keeps summary and shows retry | All relevant per-question review points plus next action | Internal ids/rubrics/model notes never visible |
| Toast/status | Brief polite live update | Not applicable | Short actionable error | Saved/review-ready confirmation | Avoid persistent overlays that block reading |

Copy/content constraints:
- Child-facing copy may say: `这一组`, `第 N / 10 题`, `已保存`, `正在看你的步骤和照片`, `复盘`, `下一组`, `先休息一下`, `再看一次结果`.
- Child-facing copy must not say: `graph/node/node_id`, `agent`, `model`, `OCR confidence`, `rubric`, `queue`, `session id`, `attempt id`, `operator`, `Codex`, `database`, `API key`, `manual grading`.
- Feedback should name observable learning actions: `看等量关系`, `补一步`, `换一种表示`, `检查符号/单位/括号`, `再做一个小检查`.
- Avoid child-blaming labels such as `粗心`, `太简单`, `失败`. Prefer `这一步还不稳`, `这个关系需要再说明`.
- Avoid feature explanations like "本系统会..." or backend workflow copy. State only what the child needs now.
- Exact final copy is adjustable after rendered review, but the copy boundary above is not optional.

Accessibility / responsive:
- HTML structure: one `main`, one page `h1`, current task `h2`, labeled textarea, labeled file input, buttons with text labels, review region with headings.
- Live regions: save/error/review-ready messages should be announced politely; avoid assertive interruptions except destructive errors, which are not expected in child flow.
- Keyboard: tab order must follow title/progress -> support mode -> answer -> photo -> remove -> primary CTA -> review retry/next action. No keyboard trap in hidden file input pattern.
- Focus: after successful save, focus moves to the next task heading or answer textarea; after review-ready, focus moves to review heading.
- Contrast/touch: meet WCAG AA contrast for text; primary and secondary buttons at least 44px high; focus ring visible on all controls.
- Reduced motion: progress and toast transitions must disable or simplify with `prefers-reduced-motion`.
- Desktop: max-width focused learning surface around current implementation scale (roughly 900-1000px), with progress and task content readable in one column.
- Mobile: single column; topbar stacks; primary CTA full width; support tabs fit without clipping; photo preview becomes full width; no horizontal scrolling; long Chinese/math text wraps.
- Text overflow: long task names, filenames, and review points must wrap or truncate gracefully without covering controls.

Implementation handoff:
- Route shell should model child-visible states explicitly: `loading`, `empty`, `active_task`, `saving`, `all_submitted_reviewing`, `review_ready`, `blocked`, `load_error`, `save_error`.
- Child API consumption should remain by `current-learning-group` handle and task `position`; route skeleton must not require raw ids in child state.
- The active task state needs slots/components for:
  - page status/progress,
  - task label and heading,
  - prompt/support content,
  - answer textarea,
  - photo picker/preview/remove,
  - primary save CTA,
  - toast/live status.
- The review state needs slots/components for:
  - child-safe completion title/message,
  - all-question review list,
  - coach/next-step list,
  - primary next-action CTA,
  - retry/refresh status when pending or blocked.
- The skeleton should include deterministic fixture states for review/QA screenshots: active text-only, active with photo preview, saving disabled, upload error, 10/10 reviewing, review ready with 10 review points, blocked, no group, mobile viewport.

Review / QA implications:
- 清秋 UX skeleton review should verify that every state above has a visible child-safe state and that no internal ids/workflow words leak into the page.
- 镜花 design review should verify frontend fidelity to the design read and visual quality bar, including responsive layout and state-machine clarity.
- 观止 QA should include false-pass checks for: save advancing before grading, all 10 submitted pending state, all-question review summary coverage, photo validation/error recovery, mobile clipping, keyboard/focus order, and blocked/model-disabled child-safe behavior.
- Rendered quality cannot be claimed from this document alone; it needs screenshots/browser evidence and human taste review for final style/copy.

Open UX decisions:
- Final visual taste: provisional until rendered desktop/mobile review with the user.
- Exact child copy: may be tightened after seeing real prompts, review points, and latency.
- Whether to autosave local answer drafts is not required by this PRD slice; if added later, it needs product approval and QA.
- Exact review result labels and icons should align with 霜弦 data/content contract and avoid grade-like stigma.

Stop condition:
This UX_FLOW_SPEC is concrete enough for 听云 to design the `/` route shell/page skeleton without guessing child-visible states, answer/photo interactions, all-10-submitted behavior, all-question review summary structure, next-action behavior, responsive/accessibility expectations, or child-copy boundaries.
