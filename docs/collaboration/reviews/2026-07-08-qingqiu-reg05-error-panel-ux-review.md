### UX_REVIEW / NEEDS_FIX - 清秋（agentKey: `qingqiu`）- 2026-07-08 21:20 CST

Verdict:
`NEEDS_FIX` for REG-05 child-facing durable error panels.

The durable panel implementation itself is substantially ready: `load_error`, `save_error`, and `upload_error` now render a persistent, focusable, child-safe panel with a recovery action. However, the `load_error` path still shows a transient toast saying `没保存成功，请再试一次` during an initial page-load failure. That mismatches the state and can make the child think an answer failed to save before any task loaded.

This is a UX gate only. This is not QA PASS, not backend evidence review, and not final visual/taste approval.

independence_required:
yes. Reviewed current files and browser evidence independently after 听云 DONE_CLAIMED / 若命 local validation; did not rely on the implementation claim alone.

context_mode:
fresh.

context_origin:
after 听云 DONE_CLAIMED and 若命 local validation.

diff_pin:
current frontend/test files by path. `git status` / `git diff` could not be used because this workspace directory is not currently inside a Git repository.

Scope:
- Reviewed child-facing UX/state/copy/accessibility readiness for `load_error`, `save_error`, and `upload_error`.
- Inspected `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`, `tests/browser_smoke_learning_system.mjs`.
- Read source artifacts: `docs/product/child_ux_flow_spec_v2.md`, `docs/qa/test_case_spec_v2.md` REG-05, prior 清秋 UX skeleton review.
- Read-only implementation review. No implementation files edited.

Project boundary overlay:
Single child Web端, incoming Grade 7, calm and age-respectful. No parent intervention, no parent/operator dashboard, and no internal graph/model/agent/rubric/Codex language in child-facing states.

User task:
When loading, saving, or selecting a photo fails, the child should understand what happened, keep their work when relevant, and have a clear next action without seeing internal system language or needing a parent.

UX risk:
Medium. These states sit on recovery paths for the core child learning loop. The risk is mostly confusion or lost momentum, not irreversible data loss from the panel itself.

Design read:
Focused child learning workspace. Recovery copy should be calm, concrete, and state-specific: page connection problems should say connection/retry; save problems should say answer content remains; upload problems should say photo can be reselected. Motion/feedback should be minimal and not depend on a transient toast.

Visual / interaction quality bar:
- Persistent panel must remain visible long enough for screenshot, keyboard, and screen-reader checks.
- Copy must be child-safe and state-specific.
- Recovery action must be visible and keyboard reachable.
- Focus should move to the panel when the error interrupts the child.
- Draft/photo evidence should remain visible where feasible.
- No parent/internal leakage.

Evidence:
- Identity binding validated against `docs/collaboration/agent-registry.json`.
- Required startup/context files read: `AGENTS.md`, `docs/collaboration.md`, `docs/collaboration/agent-registry.json`, `docs/collaboration/roles/qingqiu.md`, `docs/collaboration/inbox.md`, `docs/project-index.md`, `docs/domain-index/math-learning.md`.
- `app/local_learning_system/index.html:41` defines `#childErrorPanel` with `role="status"`, `aria-live="polite"`, `aria-atomic="true"`, labels/descriptions, `tabindex="-1"`, and a recovery button.
- `app/local_learning_system/app.js:164` defines state-specific panel copy for load/save/upload errors.
- `app/local_learning_system/app.js:189` and `app/local_learning_system/app.js:196` focus and render the error panel.
- `app/local_learning_system/app.js:430` renders a durable `load_error` page state and hides the fake task form.
- `app/local_learning_system/app.js:674` renders `upload_error` and clears invalid preview without losing typed text.
- `app/local_learning_system/app.js:721` renders `save_error` while keeping draft/photo state.
- `app/local_learning_system/app.js:795` wires recovery actions: reload, resubmit, or reopen photo picker.
- `app/local_learning_system/styles.css:183` styles the error panel; `styles.css:193` adds visible focus; `styles.css:206` and mobile CSS make the recovery action usable.
- Browser smoke run passed: `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs` -> `PASS browser smoke: child-only flow -> pending guard -> analyzed evidence evolution`.
- Targeted browser probe for intercepted `GET /api/child-bootstrap` 503 at 390x844 observed:
  - panel title: `页面刚才没有连上`
  - panel body: `请再试一次。已经保存过的答案不会因为刷新而改变。`
  - panel action: `重新连接`
  - active element: `childErrorPanel`
  - form hidden: `true`
  - toast text: `没保存成功，请再试一次`

States inspected:
- `load_error`: durable page-level panel, retry action, focused panel, form hidden, child-safe panel copy. Blocking copy mismatch remains in transient toast.
- `save_error`: durable panel, retry-save action, typed draft retained, photo preview retained in smoke, child-safe copy.
- `upload_error`: durable panel, reselect-photo action, typed draft retained, invalid preview cleared, child-safe copy.

Findings:
1. `load_error` shows a save-specific toast during initial load failure.
   - Evidence: targeted browser probe with bootstrap 503 observed panel copy correctly saying page connection failed, but toast text was `没保存成功，请再试一次`.
   - Impact: the child can receive contradictory recovery language before any answer exists. This weakens child-facing state clarity for REG-05 even though the durable panel is correct.
   - Recommendation: map load failures to load-specific toast copy such as `页面刚才没有连上，请重新连接`, or suppress the toast and let the durable panel be the only feedback for `load_error`.
   - Validation: repeat the bootstrap-failure browser probe and assert both panel and toast avoid save-specific language.

Positive checks:
- Persistent panel exists for all three error states and exposes `data-error-kind`.
- Panel receives focus after load/save/upload errors in browser evidence.
- Recovery actions are state-specific: reconnect, save again, choose photo again.
- Save error preserves typed draft and selected photo preview in smoke.
- Upload error preserves typed text and clears invalid photo preview.
- Load error does not show a fake task form.
- Panel copy avoids graph/model/agent/rubric/Codex/parent language.
- Mobile action width is handled for the error button.

Not covered:
- Full desktop/mobile screenshot matrix and final human visual taste review.
- Manual screen-reader announcement quality beyond DOM/ARIA inspection.
- Full keyboard traversal through every state beyond the focused panel checks in browser smoke.
- Backend evidence logic, model/OCR behavior, semantic grading, DB reset/upload reset, or QA PASS.

Residual risk:
- The panel visual treatment looks structurally sound from CSS/DOM, but final responsive readability and contrast should still be screenshot-reviewed by QA/human taste before release.
- If future errors reuse `childSafeErrorMessage` without state-specific context, another state may inherit mismatched copy.

Required next action:
Route a small frontend fix to 听云: make `load_error` transient feedback state-specific or remove the load-error toast. Then rerun the focused browser smoke/probe for `load_error`, `save_error`, and `upload_error`; after that, 清秋 can re-review as `PASS_WITH_SCOPE` if no new UX issue appears.
