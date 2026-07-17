# Child UX Flow Spec v5

Status: UX_FLOW_READY_FOR_TECHNICAL_PLANNING
Owner: 清秋 (`qingqiu`)
Created: 2026-07-11 CST
Source PRD: `docs/product/ai_native_math_learning_prd_v5.md`
Source product structure: `docs/product/ai_native_math_learning_product_structure_v5.md`

This UX spec defines the child-only learning surface for v5. It is a planned UX
contract, not rendered UX evidence and not implementation approval.

## Entry Lock

- request_type: `ux_flow_spec`
- current_role_authority: owned by 清秋 (`qingqiu`)
- selected_playbook_or_contract: `UX_FLOW_SPEC`
- source_artifacts:
  - `docs/product/ai_native_math_learning_prd_v5.md`
  - `docs/product/ai_native_math_learning_product_structure_v5.md`
  - `docs/collaboration/inbox.md#MSG-20260711-003`
  - `AGENTS.md`
  - current child UI files inspected for runtime-state evidence and
    legacy-disposition guidance:
    - `app/local_learning_system/index.html`
    - `app/local_learning_system/app.js`
    - `app/local_learning_system/styles.css`
- project_boundary_overlay: PRD v5 and product structure v5 stable rules
- output_target: durable doc `docs/product/child_ux_flow_spec_v5.md`
- validation/evidence_required_next:
  - browser trace and screenshots for all child states
  - DOM/API child-safe scan for internal id/provider/rubric/queue leakage
  - responsive checks on mobile and desktop
  - keyboard/focus checks for answer, photo, stuck, cannot-provide, retry, and
    finish controls
  - QA semantic/model scope labels from 观止 before PASS-like QA
- stop_condition: UX flow is ready for 听云 technical planning and later rendered UX review

## Objective

Define the child-only page, visible states, interaction flows, child-safe copy
boundaries, responsive/accessibility expectations, and legacy UI disposition for
the v5 single-child math learning loop:

```text
select current step -> child answer -> AI analysis -> teach/repair ->
select next step -> summary
```

## Source Product Structure

`docs/product/ai_native_math_learning_product_structure_v5.md` is sufficient for
UX drafting because it defines:

- one child Web surface and no parent Web dashboard
- step taxonomy: `question`, `micro_check`, `teaching_repair`,
  `worked_example`, `clarify_evidence`, `ready_for_new_knowledge`, `blocked`,
  and `summary`
- visible state model from `loading` through `summary`
- response mode matrix for text, photo, text+photo, stuck, clarification, and
  continue
- summary split between child-safe and Codex-readable facts
- legacy implementation is not product authority for v5

## Scope

- Single child page at the local learning surface.
- One current step visible at a time.
- Text, photo, text+photo, stuck, clarification, cannot-provide, continue,
  retry, and finish interactions.
- Honest pending/analyzing and blocked states.
- Targeted feedback and teaching repair.
- Ready-for-new-knowledge checkpoint.
- New-knowledge teaching flow: preparing state, structured teaching content,
  worked example, micro-check, standard question, variant/repair, and summary.
- Child-safe daily summary.
- Responsive and accessibility expectations.
- Old UI disposition for the current local child page/shell.

## Forbidden Scope

- No parent Web dashboard.
- No parent grading or parent approval path.
- No fixed worksheet, group list, or "next N questions" UX.
- No visible graph ids, question ids, attempt ids, provider/model names, rubrics,
  queue/job internals, internal agent names, or Codex instructions.
- No implementation architecture, DB schema, model provider choice, or code
  changes in this document.
- No rendered UX PASS without browser evidence.

## Project Boundary Overlay

- The system serves one incoming Grade 7 child during the summer bridge from
  primary prerequisite repair to Grade 7 math preview.
- Every teaching, question, answer analysis, evaluation, next-step decision, and
  summary must bind to math graph nodes internally.
- Grade 7 failure first checks prerequisite chains before same-type drilling.
- Child-facing UI stays simple and age-respectful; complex teaching logic stays
  in runtime, internal agents, records, and Codex-readable reports.
- Photo evidence is first-class, but OCR/vision text is untrusted until validated.
- Pending, blocked, mock-only, stale, and missing-lineage facts must not be
  presented as mastery.

## Target Users / Tasks

| User | Task | UX requirement |
|---|---|---|
| Son | Open the page and know the next thing to do | First viewport shows one clear current action, not a dashboard |
| Son | Answer with text/photo/stuck | Controls are visible, normal, and non-punitive |
| Son | Wait while analysis runs | Copy says evidence is saved and what can happen next |
| Son | Repair a misunderstanding | Feedback names the thinking break and offers one small next action |
| Son | Move into new knowledge | Checkpoint offers continue or finish summary |
| Son | Finish safely | Summary distinguishes confirmed, weak, pending, and blocked without backend detail |
| Parent | Inspect later through Codex | Child page does not expose parent/operator evidence surfaces |

## Design Read

- Surface type: focused learning workspace, not dashboard, not worksheet, not
  marketing page.
- Audience/task: one incoming Grade 7 learner doing math independently for about
  one hour.
- Visual density: calm and compact; one main prompt/teaching card, one answer
  area, one primary action. No multi-column parent/diagnostic panels.
- Aesthetic family: quiet local study tool. Use clear hierarchy, restrained color,
  and plain language. Avoid gamified noise, shame, childish praise, and internal
  system ceremony.
- Motion: minimal. Use motion only for state changes such as saving/analyzing,
  and support reduced motion.
- Hard constraints: one current step, no internal ids, no model/provider/rubric
  names, no parent dashboard, no fixed list.

## Visual Quality Bar

- The first viewport must identify the current learning state and primary action.
- The page must remain usable on phone and desktop without overlapping text or
  clipped controls.
- Primary actions must be singular and state-specific: save, continue, retry,
  add evidence, or finish.
- Photo and stuck controls must be visibly normal answer modes, not hidden error
  escapes.
- Feedback must distinguish answer correctness from thinking/process evidence.
- Pending and blocked states must be honest; "rest" language may appear only with
  a reason or a safe summary path.
- Child-safe copy must respect a Grade 7 learner: direct, calm, not babyish, not
  scolding.
- Every rendered state must have a screenshot/trace target for QA.

## Information Architecture

The v5 child page has one route/surface. It may contain internal components, but
they must render as one coherent current-step workspace:

1. Top status: today's learning, current phase label, connection/saving status.
2. Current step card: prompt, teaching, clarification request, checkpoint, blocked
   message, or summary.
3. Response area: text, photo, stuck, clarification, continue, retry, or finish
   controls depending on step type.
4. Feedback/teaching area: shown only after analysis or for teaching steps.
5. Summary area: shown only at safe stop/close.

Do not show a side navigation, question list, parent panel, export controls, or
operator diagnostics on the child surface.

## Page / Route Spec

| Page/route/surface | Purpose | Entry | Primary action | Secondary actions | Data needed | Exit states |
|---|---|---|---|---|---|---|
| `/` child current-step page | The only child Web surface for v5 learning | Child opens local learning URL | Do the one current action | Add photo, say stuck, retry, finish when state permits | child-safe daily projection, current step, allowed response modes, message, summary when closed | current step, analyzing, teaching, clarify, ready for new knowledge, blocked, summary |
| Codex query/report surface | Parent/operator inspection outside child UI | Parent asks Codex | Read evidence and system facts | Request improvements through Codex | Codex-readable records/reports | Not child-facing |

## Current Step Display Contract

| Step type | Child sees | Allowed controls | Primary CTA | Exit states |
|---|---|---|---|---|
| `question` | One graph-bound problem and a short instruction to show thinking | text, photo, stuck | Save answer | analyzing, clarify, teaching, next question, ready checkpoint, blocked, summary |
| `micro_check` | One small check after teaching | text, stuck; photo/text+photo only when runtime projection explicitly allows it | Save check | analyzing, teaching, next question, prerequisite probe, summary, blocked |
| `teaching_repair` | Short explanation of first break and one small next action | continue, stuck | Try small step | micro_check, clarify, summary, blocked |
| `worked_example` | Structured essence, core model, worked example, and next check for a new concept | continue, stuck | Continue to micro-check | micro_check, teaching repair, prerequisite probe, summary, blocked |
| `clarify_evidence` | A request for clearer work or explanation | text, photo, text+photo, cannot_provide/stuck | Add evidence; cannot provide is secondary | analyzing, blocked, summary |
| `ready_for_new_knowledge` | Checkpoint that review is stable enough | continue_new, finish | Continue to new knowledge | worked_example or summary |
| `blocked` | Honest safe message that the system cannot decide safely | retry_recovery, finish; add evidence only when runtime says relevant | Retry once through real recovery, or finish | analyzing, current step, clarify, blocked, summary |
| `summary` | Today's short child-safe result | finish/no-op only | Finish today, or no visible action | terminal idempotent |

## Runtime Child State / Response Mode Map

This section is the implementation-facing UX bridge. Product structure v5 defines
the state taxonomy and response matrix; current app files show partial runtime
skeletons and legacy names. v5 implementation must project the child page through
the mappings below instead of deriving UX from old worksheet/group labels.

| UX state / visible step | Runtime `child_state` | `current_step.step_type` when present | Allowed response mode(s) | Current app evidence / migration note |
|---|---|---|---|---|
| `loading` | none yet, client `loading` only | none | none | Existing client has `CHILD_UI_STATES.LOADING`; keep connection copy short and do not fabricate a step before `/api/child-bootstrap` returns. |
| `start_resume` | `start_resume`; compatibility alias may be current `choose_review` only for "start old review" | none | `continue` / start | Current app maps `choose_review` and calls `/api/daily-flow/review/start`; v5 copy must say start/resume today's learning, not "choose review mode". |
| `current_step` question | `current_step` | `question` | `text`, `photo`, `text_photo`, `stuck` | Current app renders `child_state=current_step`, has text/photo/stuck submit payloads, and can reuse this shell after removing group/count wording. |
| `micro_check` | `current_step` | `micro_check` | `text`, `stuck`; `photo`/`text_photo` only if `allowed_response_modes` includes them | Product step taxonomy keeps micro-check small. UX must not show a full worksheet progress model for micro-checks. |
| text answer mode | same as active step | `question`, `micro_check`, or `clarify_evidence` | `text` | Text field asks for answer plus key steps. Blank text with no photo/stuck is not a gradeable submission and should route to clarify or inline guidance. |
| photo answer mode | same as active step | `question`, `clarify_evidence`, or explicit photo-enabled `micro_check` | `photo` or `text_photo` | Existing app validates image type/size, previews, removes/replaces, and submits photo data; v5 must add unclear/photo-text conflict paths to `clarify_evidence`. |
| stuck mode | same as active step or teaching/example step | `question`, `micro_check`, `teaching_repair`, or `worked_example` | `stuck` | Existing app has stuck prompt buttons and `stuck` submit flag. v5 treats stuck as evidence, not failure or hidden escape. |
| `submitting` | previous `child_state` remains authoritative until save returns; client `saving` only | same as active step | none; controls disabled | Existing app disables submit while saving and uses an idempotency key for v3 current-step submit. Preserve draft/photo until save succeeds. |
| `analyzing_pending` | `analyzing` | none or last submitted step reference outside child prompt | wait/refresh only; recovery analyzing after accepted blocked retry | Existing app renders `child_state=analyzing` with auto-refresh. v5 copy must say work is saved and analysis is bounded; no mastery or dependent next step may appear from pending evidence. |
| `clarify_evidence` | `clarify_evidence` | `clarify_evidence` | `clarification`, implemented as allowed `text`, `photo`, `text_photo`, or `cannot_provide`/`stuck` | Current app has no explicit v3 mapping for clarify. Engineering must add/render this state, or the UX skeleton cannot cover low-confidence photo, blank evidence, text/photo conflict, or cannot-provide closeout honestly. |
| `teaching_repair` / feedback teaching | `teaching` | `teaching_repair` | `continue`, `stuck` | Current app maps `child_state=teaching` through the current-step renderer. v5 must show first thinking break plus one small next action, then micro-check/retest/summary. |
| `new_knowledge_preparing` | `preparing_new_knowledge` preferred, or `analyzing` with `preparing_new_knowledge` phase metadata | none | none; optional retry only after failure | If the new teaching package is generated asynchronously, show "正在准备一个新知识的小讲解和小检查。" Do not say an answer is saved unless the child just submitted evidence. Do not expose model/provider/job terms. |
| `worked_example` | `teaching` | `worked_example` | `continue`, `stuck` | Product structure treats worked example as exposure, not mastery. New knowledge requires structured child-safe sections: essence, core model, worked example, why it works, and next micro-check; it must not be an ordinary review question wrapped as an example. |
| `ready_for_new_knowledge` | `ready_for_new_knowledge` | `ready_for_new_knowledge` or checkpoint payload | `continue_new`, `finish` | Current app maps and renders this state. v5 must offer continue to new knowledge or finish summary, without exposing thresholds. |
| `blocked` | `blocked` | `blocked` or no active step | `retry_recovery`, `finish`, optional add evidence when runtime says relevant | Current app maps `blocked` and shows a safe waiting shell. v5 retry must perform explicit recovery, not generic refresh; still-blocked returns to blocked with honest copy; child-safe reason stays separate from Codex-readable cause. |
| `summary` | `summary` | `summary` | `finish` as terminal no-op, or no visible button | Current app maps `summary`, but v5 summary must separate confirmed, weak, pending, and blocked instead of only showing last-step or group-completion copy; it must never expose answer or next-question actions. |
| `load_error` / `save_error` / `upload_error` | client-only error overlay, not authoritative learning state | same as interrupted state | retry/reselect/resubmit | Existing app has focused error panel, photo validation, and retry actions. Error copy must preserve saved-work honesty and never expose provider/queue/config details. |

## Interaction Flows

| Flow | Trigger | Steps | Feedback | Recovery | Open UX decision |
|---|---|---|---|---|---|
| Start/resume | Child opens page | Load projection -> show active step or start state -> primary CTA starts/resumes | "Today is ready; do this one step" | Load error offers retry; no active data offers blocked/summary if runtime cannot create flow | exact route label |
| Text answer | `question` or `micro_check` accepts text | Type answer/process -> save -> clear local draft only after saved -> analyzing | Saved confirmation and pending analysis status | Blank text with no photo/stuck routes to clarify; save error preserves draft | exact placeholder copy |
| Photo answer | Current step accepts photo | Pick/capture image -> preview -> save with optional text -> analyzing | Photo is saved; analysis may ask for clearer work | Unsupported/too-large photo preserves text; low-confidence OCR routes to clarify | max file size display from engineering |
| Text+photo conflict | Both modes present and disagree | Save both -> analysis flags conflict -> clarify request | Child sees "help me choose the version to use" style copy | Add explanation or replace photo; no mastery until resolved | exact conflict copy |
| Stuck | Child cannot start or continue | Choose stuck reason or write own -> save -> teaching/probe decision | Stuck is treated as useful evidence | Repeated stuck reduces step size, probes prerequisite, or summarizes safely | exact stuck reason set can evolve |
| Clarify evidence | Runtime needs more evidence | Show what is missing -> child adds text/photo or chooses cannot provide | Existing evidence remains saved but not usable | Cannot provide records pending evidence, does not rejudge or update mastery, then exits to summary | exact cannot-provide label can be tuned |
| Analyzing pending | Evidence saved; AI/runtime not done | Show saved status -> poll/refresh -> wait, independent safe step, clarify, blocked, or summary | Must not imply grade exists; must say the answer is saved | Bounded attempts stop analyzing and project blocked or summary if no safe result exists | polling cadence is technical |
| Teaching repair | Analysis finds first break | Show short explanation -> one small action -> micro_check/retest | Explain thinking break without backend labels | Stuck goes to smaller step/prerequisite/safe summary | exact tone examples after rendered review |
| Ready for new knowledge | Review readiness reached | Show checkpoint -> continue new concept or finish summary | Child controls whether to keep going now | Finish creates summary; continue starts preparing/structured worked example | exact checkpoint copy |
| New knowledge teaching | Child chooses continue_new | Optional preparing state -> structured worked example -> continue -> micro_check -> standard question -> variant or repair -> summary | Child sees one concept in small sections, not a fixed worksheet | Stuck on example/check records evidence and routes to smaller teaching, prerequisite probe, or safe summary | exact section copy and visuals after rendered review |
| Blocked | Model/OCR/config/runtime cannot decide safely | Show child-safe reason category -> retry recovery or finish | No fake grading or hidden failure | Retry enters recovery analyzing or returns still-blocked; finish creates summary with pending/blocked labels | how much reason detail is child-safe |
| Summary | Budget done, safe stop, cannot provide, or child finishes | Show concise result -> finish/no-op | Confirmed, weak, pending, blocked separated | Repeated finish/refresh returns same summary and never opens answer/next-question UI | exact visual layout |

## State Coverage

| Surface/action | Loading | Empty | Error | Success | Disabled/stale/permission |
|---|---|---|---|---|---|
| Page boot | "Connecting to today's learning" | Start/resume if no active flow | Retry with saved-work reassurance | Current step shown | No parent/operator fallback on child page |
| Current step | Placeholder skeleton only, no fake task | Summary or start state | Child-safe blocked/retry | One actionable step | No internal ids; no hidden second task |
| Text answer | Save button disabled while saving | Ask for text/photo/stuck if blank | Preserve draft and retry | Evidence saved then analyzing | Double submit idempotent |
| Photo | Preview while chosen | Photo optional unless clarify requires it | Preserve text, ask new photo | Attachment saved, analysis pending | Unsupported/large photo rejected locally |
| Stuck | n/a | Available as answer mode on allowed steps | Save failure preserves input | Stuck evidence saved | Repeated stuck cannot loop same question |
| Clarify | State explains missing evidence | n/a | Can finish summary if cannot clarify | Evidence re-submitted or cannot-provide summary created | No mastery update from unclear or cannot-provide evidence |
| Analyzing | Polling/refresh state | n/a | Bounded attempts end in blocked/summary if model/config fails | Next step/teaching/summary appears | Pending cannot drive dependent next step |
| Teaching repair | Load repair content | n/a | Blocked/summary if teaching unavailable | Micro-check/retest ready | Reading alone is not mastery |
| Ready checkpoint | n/a | n/a | Summary fallback | Continue new knowledge or finish | Runtime owns readiness, child sees no thresholds |
| New knowledge package | Preparing copy if async | n/a | Blocked/summary if package cannot be prepared safely | Structured example then micro-check | Reading example alone is not mastery; ordinary review question cannot be re-labeled as new knowledge |
| Blocked | n/a | n/a | Retry recovery, still-blocked message, or finish summary | Resume if recovered | Codex sees cause; child sees safe message; retry disabled while in flight |
| Summary | Generate summary | No evidence summary if no work | Include blocked/pending note | Finish/no-op terminal | Stale/report freshness not child-inferred; no answer or next-step controls |

## Recovery / Cannot-Provide Delta

This section is authoritative for MSG-20260711-003 and overrides older ambiguous
wording in this spec.

| Case | Child action | Required visible state | Required runtime meaning | Forbidden UX |
|---|---|---|---|---|
| Blocked retry | Primary button labeled like "再试一次" | Immediately disable retry/finish and show "正在重新检查，刚才的答案还在。" | Runtime performs real recovery against the recent recoverable terminal job; it is not a cosmetic page refresh | Spinning forever, silently copying old terminal result, exposing queue/job/model details |
| Recovery accepted | No new child input | `analyzing_pending` with copy like "答案已经保存，正在重新检查。" | Recovery can only converge to current step, clarify, blocked, or summary | Showing a dependent next step from pending evidence or implying a grade exists |
| Still blocked | Recovery cannot produce safe result | Return to `blocked` with copy like "还是不能安全判断；可以稍后再试，或今天到这里。" | Saved evidence remains pending/blocked; child can retry later or finish summary | Asking parent to grade, hiding the failure as generic rest copy |
| Cannot provide | Secondary action in `clarify_evidence`, label like "没法补清楚，先记为待判断" | Save in-flight state, then terminal summary | Records `cannot_provide`/stuck evidence linked to the original attempt; no rejudge, no mastery update, no new clarify loop | Treating it as correctness, reopening another answer form, or creating a parent task |
| Terminal summary | Optional "完成今天学习" button, or no visible action | Summary remains visible and stable | Finish is idempotent no-op; refresh/click returns the same summary | Showing save/submit/retry/next-question/continue-new actions from summary |

Bounded analyzing copy must always include "saved" before "checking". The child
should never be left wondering whether the answer/photo/stuck/cannot-provide
choice was lost.

## New Knowledge Delta

This section is authoritative for the v5 new-knowledge ambiguity found during
清秋 UX review. It refines the `ready_for_new_knowledge` path in Product
Structure v5 without adding a parent Web flow or exposing internal runtime data.

### Required Child-Visible Sequence

The child must experience new knowledge as one current step at a time:

1. `ready_for_new_knowledge`: "复习暂时稳了。可以学一个新知识，或者今天到这里。"
   Primary action: learn one new concept. Secondary action: finish summary.
2. `new_knowledge_preparing`, only if needed: "正在准备一个新知识的小讲解和小检查。"
   Controls are disabled except a safe retry if preparation fails. This state is
   not answer analysis, so it must not say "your answer is saved" unless it
   follows a child submission.
3. `worked_example`: a structured, child-safe teaching package for one concept:
   essence, core model, worked example, why the model works, and the next
   micro-check. Actions: continue to micro-check; still stuck.
4. `micro_check`: one tiny check tied to the just-shown model. Default allowed
   modes: text and stuck. Photo appears only when runtime explicitly includes
   `photo` or `text_photo`.
5. `standard_question`: one regular `question` using the same concept after the
   micro-check is usable. Text/photo/stuck follow the question's allowed modes.
6. `variant_question`: one transfer/variant `question` only after the standard
   question is usable, or `teaching_repair`/prerequisite probe if the evidence
   shows a gap.
7. `summary`: confirmed, weak, pending, and blocked facts remain separated.

The sequence must never be implemented as: select an ordinary review question,
wrap its expected answer as a worked example, then call that new knowledge.

### Structured Teaching Payload

The child projection for `worked_example` must include a renderable child-safe
teaching package. The exact JSON names may be adapted by engineering, but the
visible meaning must be preserved:

| Section | Child label | Required content | Forbidden content |
|---|---|---|---|
| `essence` | 本质 | One short sentence naming the mathematical idea in child language | graph ids, node ids, curriculum database labels |
| `core_model` | 核心模型 | The representation or invariant the child should use | model/provider/agent/rubric names |
| `worked_example` | 例题 | One example with a small number of readable steps and final check | raw expected-answer dumps or unreviewed model text |
| `why_it_works` | 为什么这样做 | One or two sentences connecting the model to the steps | proof-heavy or adult/operator language |
| `next_micro_check` | 下一步 | What the child will do in the micro-check | hidden thresholds, mastery claims, next-question ids |

Recommended child projection shape:

```json
{
  "child_state": "teaching",
  "current_step": {
    "step_type": "worked_example",
    "topic_label": "child-safe topic",
    "teaching_sections": [
      {"kind": "essence", "label": "本质", "body": "..."},
      {"kind": "core_model", "label": "核心模型", "body": "..."},
      {"kind": "worked_example", "label": "例题", "body": "...", "steps": ["...", "..."]},
      {"kind": "why_it_works", "label": "为什么这样做", "body": "..."},
      {"kind": "next_micro_check", "label": "下一步", "body": "..."}
    ],
    "answer_input_mode": "none",
    "allowed_response_modes": ["continue", "stuck"],
    "support": {
      "continue_label": "继续小检查",
      "stuck_label": "这里没看懂"
    }
  }
}
```

The child UI may also receive a legacy `prompt` string for compatibility, but
the UX acceptance target is the structured section rendering. If only `prompt`
is present, it must already contain all five visible sections with child-safe
labels, and the browser review must verify that it remains readable at 390px.

### Continue / Stuck Semantics

- Continue from `worked_example` records exposure only and creates the
  `micro_check`; it must not update mastery by itself.
- Stuck from `worked_example` records useful evidence and routes to one of:
  smaller `teaching_repair`, prerequisite probe, or safe summary. It must not ask
  the child or parent to grade the example.
- Micro-check success can lead to a standard question. Micro-check weakness
  leads to teaching repair or prerequisite probe before any variant.
- Standard-question usable evidence can lead to variant/transfer. Weak,
  low-confidence, stuck, or unclear evidence routes through the same honest
  teaching/clarify/blocked/summary boundaries as review.

### Photo Visibility

- No photo control on `ready_for_new_knowledge`, `new_knowledge_preparing`,
  `worked_example`, or `teaching_repair`.
- `micro_check` defaults to text and stuck only; photo may appear only when the
  runtime explicitly includes `photo` or `text_photo` for that check.
- Standard and variant `question` steps may show photo/text+photo as normal
  answer modes when allowed by runtime projection.
- `clarify_evidence` may show photo/text+photo when the missing evidence is a
  clearer written process.

### New-Knowledge Child-Safe Boundary

The child page and child bootstrap must not expose:

- graph ids, node ids, question ids, attempt ids, flow ids, packet ids, lineage
  ids, provider/model names, agent names, prompt names, rubrics, queue/job ids,
  confidence numbers, route names, thresholds, or raw contract keys
- "teaching_agent", "planner", "candidate packet", "OCR confidence", "graph
  node", or "mastery threshold" wording
- raw extracted photo text as authoritative truth

Child-visible language may say "这一步", "这个想法", "这个模型",
"小检查", "例题", "变式", and "还不能安全判断".

## Copy / Content Constraints

Child-facing copy should:

- use "your work is saved" before any analyzing/waiting message
- ask for thinking/process, not just a final answer
- treat stuck/photo/clarify as normal learning modes
- say "I need clearer evidence" instead of "you failed to upload correctly"
- say "I cannot safely judge this yet" instead of pretending a model grade exists
- avoid raw labels like `node_id`, `attempt_id`, `rubric`, `queue`, `model`,
  `provider`, `OCR confidence`, `planner`, or internal agent names
- avoid babyish praise and blame; prefer specific, respectful feedback
- avoid "just rest" as a cover for configuration failure

Recommended copy patterns:

| Situation | Child-safe pattern |
|---|---|
| Normal answer | "Write the answer and the key steps you used." |
| Stuck | "If you are stuck, choose where it broke. That still helps the system pick a better next step." |
| Photo | "You can upload your paper work. If the photo is unclear, I may ask for a clearer one or a short explanation." |
| Analyzing | "Your work is saved. I am checking the method and steps before choosing what comes next." |
| Recovery analyzing | "Your work is saved. I am checking this step again." |
| Clarify | "I need one more piece of evidence before judging this safely." |
| Cannot provide | "If you cannot make it clearer now, I will mark this step as still pending and finish the summary." |
| Teaching repair | "The first break seems to be here. Try this smaller step." |
| Preparing new knowledge | "I am preparing one short explanation and a small check." |
| Worked example | "First look at the idea, the model, and one example. Reading it does not count as mastery yet." |
| Micro-check | "Try this tiny check using the model you just saw." |
| Standard/variant question | "Now use the same idea on one problem. Write the key steps." |
| Blocked | "Your work is saved, but the system cannot judge this safely right now. You can retry or finish with this marked pending." |
| Still blocked | "It still cannot be judged safely. You can try again later, or finish today with this marked pending." |
| Summary | "Today we confirmed..., still need work on..., and left ... pending." |

## Feedback Boundary

Feedback shown to the child must be derived from accepted analysis/teaching
records and must not expose backend diagnosis. It should contain:

- what part of the thinking was sound
- the first important break or uncertainty
- one next small action
- whether the next step is a retest, transfer, prerequisite probe, repair, new
  knowledge, or summary in child-safe terms

Feedback must not:

- grade by final answer alone
- claim durable mastery from one answer
- claim new-knowledge mastery from reading an example or tapping continue
- wrap an ordinary review question's expected answer as new-knowledge teaching
- say pending/blocked/mock/stale evidence is confirmed
- summarize only the last question when the session has multiple relevant
  wrong/partial/pending steps
- use "粗心" as a standalone diagnosis

New-knowledge feedback must come from an accepted teaching package or a
graph-bound runtime teaching contract. It must name the visible step type in
child language: example, small check, standard problem, variant, repair, or
summary.

## Photo / OCR Experience

- Photo upload is available wherever product structure allows `photo` or
  `text_photo`.
- The photo picker should be near the text answer area and labeled as a normal
  way to submit written work.
- A thumbnail preview and remove/replace action are required.
- Text typed beside a photo should be encouraged but not always required.
- Low-confidence, unclear, cropped, unrelated, or hallucinated OCR content routes
  to `clarify_evidence` or pending/blocked summary.
- Photo/text conflict routes to clarification unless runtime defines a safe
  conflict-resolution rule.
- The child never sees OCR confidence numbers, provider names, or raw extracted
  text as authoritative truth.
- Photo controls must be hidden on `ready_for_new_knowledge`,
  `new_knowledge_preparing`, `worked_example`, and `teaching_repair`; these are
  reading/continue states, not answer evidence states.
- Photo controls on new-knowledge `micro_check`, `standard_question`, or
  `variant_question` depend only on `allowed_response_modes`, not on the fact
  that the flow is new knowledge.

## Stuck Experience

- Stuck is a first-class response mode, not a failure.
- Default stuck reasons should be short and age-respectful:
  - "I do not understand the question."
  - "I do not know the first step."
  - "I got stuck halfway."
  - "My answer and method do not match."
- Stuck submission saves evidence and can lead to teaching repair, worked example,
  micro-check, prerequisite probe, or safe summary.
- Stuck on a worked example means "this explanation did not land yet"; it should
  route to smaller teaching, prerequisite probe, or safe summary, not ask for a
  written answer to the example.
- Repeated stuck must not repeat the same question type without teaching or
  rollback.

## Analyzing Pending Experience

The pending state must communicate four facts:

1. The child's evidence is saved.
2. The system is checking reasoning/process, not only the answer.
3. Pending evidence will not be used as mastery.
4. The next visible action depends on whether the runtime can choose a safe
   independent step, needs clarification, blocks, or summarizes.

The UI may show a refresh/poll action. It must not show a dependent next step
unless runtime marks it independent from pending evidence.

Analyzing is bounded. After saved evidence or accepted blocked recovery, the
child page may wait or poll, but runtime must eventually project current step,
clarify, blocked, or summary. If model attempts are exhausted, the UI stops
analyzing and shows blocked or summary while preserving the saved answer.

## Blocked Experience

Blocked state appears when runtime/model/OCR/config cannot safely analyze or
decide. The child page should show:

- a calm title
- a short child-safe reason category, such as "I cannot check this safely yet"
- allowed next actions: retry, add evidence when relevant, or finish with pending
  summary
- reassurance that saved work is not lost

Retry is a real recovery action. While retry is in flight, keep the child on a
blocked/recovery-pending surface with controls disabled and saved-work copy. If
runtime accepts a recovery job, transition to `analyzing_pending`. If recovery
still cannot judge safely, return to `blocked` with a still-blocked message and
the same safe choices: retry later or finish today.

The child page must not show stack traces, route names, provider names, config
keys, queue/job ids, raw model errors, or "ask your parent to grade this".

## Summary Experience

Child-safe summary minimum:

- title for today's stop point
- one or two confirmed strengths
- one or two current weak/repair areas
- pending or blocked note if present
- next child action, such as finish today or continue later

Codex-readable details remain outside the child UI. The child summary may be
shorter, but it must not contradict Codex-readable facts or hide pending/blocked
evidence.

Terminal summary is the end of the child flow for that session state. It must
not render an answer form, retry, continue-new, next-question, or save action.
If a finish button is shown, it is a local completion/no-op action; repeated
clicks and page refreshes return the same summary. A cannot-provide closeout
must summarize the unclear evidence as pending/blocked and must not claim
mastery.

## Responsive / Accessibility

- Layout must be single-column on mobile and can use a centered max-width column
  on desktop.
- The 390px mobile viewport is a required acceptance size. All new-knowledge
  sections must stack vertically and remain readable without horizontal scroll.
- Minimum tap target: 44px for primary buttons, photo picker, stuck choices,
  cannot-provide, retry, continue, and finish.
- Textareas and photo controls must remain visible without horizontal scrolling.
- State changes must update `aria-live` regions for save errors, analyzing,
  recovery analyzing, new-knowledge preparing, worked example arrival,
  still-blocked, cannot-provide summary, blocked, and summary messages.
- Error/blocked panels should be focusable and receive focus after failed save,
  failed load, blocked transition, or still-blocked retry result.
- The worked-example container should receive focus or move screen-reader focus
  to its heading when it replaces the ready checkpoint.
- Keyboard path must cover: text input -> photo picker/remove -> stuck reason ->
  save -> cannot-provide when shown -> retry/continue/finish.
- New-knowledge keyboard path must cover: ready primary -> preparing state when
  present -> worked-example sections -> continue micro-check -> stuck from
  example -> micro-check text/stuck -> standard/variant answer controls.
- On mobile, blocked and clarify action groups stack in logical order: primary
  recovery/add-evidence first, cannot-provide or finish second. Tab order must
  match that order.
- Buttons disabled during save/retry/finish keep stable accessible names and
  expose disabled state; there must be no hover-only recovery or finish control.
- The photo preview must have non-sensitive alt text such as "uploaded work
  preview".
- Color cannot be the only indicator for pending, blocked, or confirmed states.
- Reduced-motion preference must disable non-essential transitions/spinners.
- Copy must fit on narrow screens; no hero-scale headings inside the learning
  panel.
- Structured teaching section labels must be text, not color-only badges; if
  icons are later added, they need accessible labels and must not replace the
  text labels.

## Legacy UI Disposition

Current implementation files are not v5 product authority, but they reveal
migration risks.

| Existing surface/copy | Risk against v5 | Required disposition |
|---|---|---|
| `app/local_learning_system/index.html` title/copy such as "今天先完成这一组", "继续下一组", "保存，下一题" | Implies fixed group/list workflow instead of one adaptive current step | Replace with current-step language: "今天的数学学习", "保存", "继续下一步", "完成今天总结" |
| `app/local_learning_system/app.js` fixture/group language and `第 N / total 题` progress | Reinforces worksheet progress and pre-known task count | Use current-step/phase progress; do not show total fixed question count unless it is a safe budget hint, not a list |
| `app/local_learning_system/app.js` v3 state rendering | Useful skeleton for `current_step`, `analyzing`, `ready_for_new_knowledge`, `summary`, and `blocked` | Keep conceptually, but align copy/actions to v5 taxonomy and response matrix |
| Wrapping a normal question/expected answer as `worked_example` | Makes new knowledge look valid while skipping essence/model teaching | Runtime must provide a structured teaching package before micro-check; browser smoke must assert section content, not only `kind_label=例题` |
| `app/local_learning_system/app.js` forbidden key scan list | Useful child-safe boundary | Extend/verify against v5 forbidden surface terms during QA |
| `app/local_learning_system/styles.css` responsive/touch/focus skeleton | Useful baseline for 44px controls, mobile collapse, focus rings, and reduced motion | Keep the accessibility skeleton, but validate every v5 state after implementation with rendered screenshots and keyboard checks |
| Existing "可以先休息" copy | Fine only as safe stop language | Must not hide model/config/OCR failure; blocked/pending reason must exist in Codex-readable record |

## Implementation Handoff

听云 should consume this UX spec with product structure v5 and produce technical
contracts for:

- child-safe projection payload for each visible state
- allowed response modes per step
- idempotent submit/retry behavior
- blocked retry recovery and while-still-blocked projection
- cannot-provide clarification submission and pending/blocked summary closeout
- photo validation and attachment handling
- pending/analyzing polling or refresh behavior
- new-knowledge preparing state and failure fallback
- structured worked-example payload with essence, core model, example, why, and
  next micro-check sections
- new-knowledge sequence enforcement: worked example -> micro-check -> standard
  question -> variant or repair -> summary
- rejection of ordinary review-question-as-worked-example shortcuts
- terminal summary finish/no-op behavior
- blocked reason separation between child-safe message and Codex-readable cause
- summary freshness and trust labels
- DOM/API leakage scan for forbidden internal fields

Do not implement from old UI names alone. Map old state names to v5 product
states only where meaning matches.

## Review / QA Implications

清秋 later rendered UX review should inspect:

- one-current-step invariant on desktop and mobile
- child-safe copy and no internal field leakage
- photo flow preview, validation, error recovery, and clarify route
- stuck flow as normal response mode
- analyzing pending honesty
- bounded analyzing after normal save and recovery retry
- blocked retry/finish/still-blocked boundaries
- clarify cannot-provide closeout with no mastery update
- ready-for-new-knowledge checkpoint with continue/finish options
- new-knowledge preparing state, structured teaching sections, continue/stuck,
  micro-check, standard question, variant/repair, and summary sequence
- new-knowledge photo visibility: hidden on ready/preparing/example/repair,
  shown only on allowed answer steps
- summary separation of confirmed, weak, pending, and blocked, with terminal
  no answer/next-question controls
- 390px mobile readability for structured teaching sections
- keyboard/focus behavior and `aria-live` updates

观止 should include visual/interaction regression cases for every visible state,
including blank evidence, low-confidence photo, photo/text conflict, repeated
stuck, slow model, model/config failure, refresh/double-submit, stale summary,
and the full new-knowledge sequence. New-knowledge browser acceptance must check:

- ready checkpoint shows learn-new and finish only
- async preparing copy is honest and has no answer-saved claim unless applicable
- worked example shows visible 本质, 核心模型, 例题, 为什么这样做, 下一步 sections
- continue creates `micro_check`, not a standard/variant question first
- micro-check weakness routes to repair/prerequisite before variant
- standard question precedes variant
- summary remains terminal
- no child-visible internal ids, provider/model/agent/rubric/job/queue fields,
  confidence numbers, or graph labels
- 390px viewport has no horizontal scroll, clipped buttons, or unreadable section
  labels

## Open UX Decisions

- Exact final microcopy can be tuned after first rendered prototype.
- Exact section layout for structured teaching can be tuned after screenshots;
  the five section meanings and sequence are not optional.
- Exact visual style may be reviewed with the user after screenshots; default is
  calm, simple, age-respectful learning tool.
- Exact polling interval, image-size limit display, and "independent safe step"
  availability depend on 听云's runtime contract.
- Exact first 7-day node seed is product/planning scope, not UX scope.

## UX_FLOW_SPEC_QUALITY_GATE

- verdict: `UX_FLOW_READY_FOR_TECHNICAL_PLANNING`
- product_structure_source_ready: pass
- child_only_surface_preserved: pass
- one_current_step_defined: pass
- runtime_child_state_response_mode_mapping_defined: pass
- text_photo_stuck_clarify_covered: pass
- pending_blocked_summary_boundaries_defined: pass
- new_knowledge_structured_flow_defined: pass
- child_safe_copy_boundary_defined: pass
- responsive_accessibility_defined: pass
- legacy_ui_disposition_defined: pass
- implementation_authorized: no
- rendered_ux_pass_claimed: no
- blocking_gaps: none for technical planning; rendered prototype review still required

## Stop Condition

This UX spec is ready for 听云 to use as a source artifact for technical planning,
engineering contracts, and implementation blueprint. It does not authorize code
changes by itself and does not replace rendered UX review after a prototype or
implementation exists.
