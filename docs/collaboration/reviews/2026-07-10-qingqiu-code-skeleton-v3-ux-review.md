### UX_REVIEW / NEEDS_FIX - 清秋（agentKey: `qingqiu`）- 2026-07-10  CST

Verdict:

`UX_REVIEW_NEEDS_FIX`. The v3 child-only shell has the right overall direction: one child page, a feature-flagged v3 branch, choose-review entry, one-current-step rendering, open answer textarea, photo upload, blocked/ready/summary placeholders, and no visible parent dashboard or child-facing raw ids. However, the skeleton is not yet sufficient for the requested v3 UX contract because two required child interactions/states are not actually represented in the v3 path.

independence_required:

yes

context_mode:

fresh

context_origin:

spawned for UX skeleton review only

diff_pin:

no git; file list in SKELETON_PASS

Scope:

Reviewed UX skeleton readiness only for `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`, plus v3 projection route shape in `learning_system/daily_runtime.py` and `learning_system/server.py` as needed. No implementation code was changed.

Project boundary overlay:

Applied from `AGENTS.md`, `docs/product/ai_native_math_learning_prd_v3.md`, and `docs/domain-index/math-learning.md`: son uses one Web child page; parent uses Codex only; no parent dashboard; page must be simple, age-respectful, current-step based, graph/model internals hidden, and normal learning must not depend on parent action.

User task:

The son opens the page, chooses old-knowledge review when offered, works on exactly one current step, answers with text/photo or says he is stuck, sees honest saving/analyzing/blocked/ready-for-new/teaching/summary states, and never sees parent/operator internals.

UX risk:

Primary workflow + state-heavy child UI. The skeleton must be clear enough that implementation and QA do not invent missing child states later.

Design read:

Single-child learning workflow, not dashboard or product landing page. Audience is an incoming Grade 7 student. Visual density should be balanced and calm; motion feedback-only; copy should be age-respectful, direct, and child-safe. Final visual polish and exact copy remain out of this gate.

Visual / interaction quality bar:

For skeleton only: one visible child surface; one current step; visible answer/photo/stuck affordances; honest loading/saving/analyzing/blocked states; ready-for-new and summary placeholders; no child-visible graph ids, question ids, attempt ids, model/provider names, rubrics, queue/job internals, or parent action.

Evidence:

- `docs/product/ai_native_math_learning_prd_v3.md:521`-`528` defines one child Web surface, one current step, open answer/photo, honest waiting, no internals, and age-respectful UI.
- `docs/product/ai_native_math_learning_prd_v3.md:665`-`668` requires loading/choose/current/saving/analyzing/ready/teaching/summary/blocked states, ask-stuck/clarify on current step, and summary labels.
- `docs/architecture/technical_plan_v3.md:459`-`461` defines v3 child bootstrap/start/submit contracts, including optional `stuck?`.
- `docs/architecture/code_skeleton_pass_v3.md:36`-`40` claims v3 child route/page shells for choose_review, current_step, teaching, analyzing, blocked, ready_for_new_knowledge, and summary.
- `app/local_learning_system/index.html:57`-`80` provides the child answer form, textarea, photo picker, and submit button.
- `app/local_learning_system/app.js:20`-`42` defines child-forbidden DTO keys covering the main internal ids/model/agent/rubric/queue leak risks.
- `learning_system/daily_runtime.py:220`-`268` projects choose_review, ready_for_new_knowledge, summary, blocked, and current_step without raw child-visible ids beyond step handle/position.

States inspected:

loading/static shell, choose_review, current_step, local saving, save_error/upload_error/load_error, blocked, ready_for_new_knowledge, teaching branch, summary branch, and claimed analyzing branch by code inspection only. No browser/rendered viewport evidence was requested or used.

Findings:

1. [P1] v3 current-step has no real "stuck" affordance or submit path.
   Evidence: PRD requires ask stuck/clarify in the current step (`docs/product/ai_native_math_learning_prd_v3.md:666`) and the submit contract includes `stuck?` (`docs/architecture/technical_plan_v3.md:461`). The visible stuck controls exist only in the legacy support renderer (`app/local_learning_system/app.js:530`-`574`), while the v3 current-step renderer outputs only a prompt card (`app/local_learning_system/app.js:382`-`393`). The v3 submit payload sends answer/photo fields but no `stuck` flag (`app/local_learning_system/app.js:963`-`972`).
   Impact: the son can type "I am stuck" in the textarea, but the v3 shell does not expose the required stuck/cannot-start interaction as a first-class branch. QA also cannot validate the intended `stuck?` route without inventing behavior.
   Recommendation: add a v3-visible stuck action or mode on current_step/teaching steps, preserve open text/photo submission, and send `stuck: true` plus child-safe stuck text through `/api/current-step/submit`.

2. [P1] `analyzing` is declared but not rendered as an honest analyzing/waiting state.
   Evidence: v3 maps `child_state === "analyzing"` into `CHILD_UI_STATES.ANALYZING` (`app/local_learning_system/app.js:325`-`330`), but `renderV3ChildState()` has no `analyzing` branch and falls through to the generic blocked/wait shell (`app/local_learning_system/app.js:402`-`442`). This conflicts with the claimed child page state coverage in SKELETON_PASS (`docs/architecture/code_skeleton_pass_v3.md:40`) and the PRD requirement that waiting states be honest and useful (`docs/product/ai_native_math_learning_prd_v3.md:527`).
   Impact: slow answer analysis/OCR can look like "learning cannot continue" instead of "your answer is saved and being analyzed." That is a UX-state correctness issue, not visual polish.
   Recommendation: add an explicit v3 analyzing shell with saved/analyzing language, a safe refresh/poll action, and no implication that the child or parent must fix the system.

3. [P2] Summary evidence labels are not yet visible in the child summary shell.
   Evidence: PRD/product structure says daily summary should show pending/blocked labels (`docs/product/ai_native_math_learning_prd_v3.md:668`). The v3 runtime summary stub includes `summary.labels` (`learning_system/daily_runtime.py:248`-`256`), but the frontend summary branch renders only title and next action (`app/local_learning_system/app.js:427`-`434`).
   Impact: this is acceptable as an early placeholder only if kept scoped, but it is not enough for later summary QA or child-facing evidence-scope clarity.
   Recommendation: reserve visible child-safe summary rows/chips for confirmed, pending, blocked, and next-move text before business logic fills the summary.

Not covered:

No browser screenshots, mobile viewport checks, keyboard/focus audit, contrast calculation, DB/model logic review, route business correctness, final visual style, or final child copy review. I did not judge model, OCR, graph, question bank, planner, or database semantics.

Residual risk:

The static HTML and legacy fixtures still contain fixed-round wording such as "这一组" and "下一题"; I am not blocking on this in a skeleton-only gate, but final v3 UI/copy review should remove fixed-list cues from the child path.

Required next action:

Route back to 听云 for scoped v3 child-shell fixes: add the stuck affordance/payload and explicit analyzing state, and reserve summary label structure. After that, rerun 清秋 UX skeleton review before filling business logic.
