### QA / PASS_WITH_SCOPE - 观止（agentKey: `guanzhi`）- 2026-07-08 14:37 CST

Verdict:
PASS_WITH_SCOPE for REG-05 durable child error panels only. Current code and browser smoke cover durable DOM panels, focus movement, retry/reselect behavior, and draft/photo preservation for `load_error`, `save_error`, and `upload_error` within deterministic local browser evidence.

independence_required:
yes

context_mode:
fresh

context_origin:
after 听云 DONE_CLAIMED and 若命 local validation facts. Prior claims were treated as context only, not QA evidence.

diff_pin:
current frontend/test files in `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`, and `tests/browser_smoke_learning_system.mjs`. Git diff could not be inspected because this workspace path is not a Git repository.

Scope:
Focused QA only for `load_error`, `save_error`, `upload_error` durable panels and associated browser smoke updates. This is not full product QA.

Project boundary overlay:
Child-only Web, no parent intervention, child-safe copy, no internal leakage, deterministic mocks/browser smoke prove contract only. Applied `AGENTS.md`, `docs/domain-index/math-learning.md`, and `docs/project-rules/qa-learning-system-addendum.md`.

Source artifacts:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/roles/guanzhi.md`
- `docs/project-rules/qa-learning-system-addendum.md`
- `docs/collaboration/inbox.md` MSG-20260708-002
- `docs/domain-index/math-learning.md`
- `docs/qa/test_case_spec_v2.md` REG-05 / VIS-05 / VIS-08
- `app/local_learning_system/index.html`
- `app/local_learning_system/app.js`
- `app/local_learning_system/styles.css`
- `tests/browser_smoke_learning_system.mjs`

Environment:
Local macOS shell, Node, Python stdlib server, Playwright Chromium via `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`; temporary SQLite DB and temporary upload directory only; model API keys blanked by smoke script; no external model calls.

Test case spec:
`docs/qa/test_case_spec_v2.md` requires REG-05 durable `load_error` panel and persistent/inspectable `save_error` / `upload_error` states; VIS-05/VIS-08 require child-safe actionable error copy, focus destination, draft/photo recovery where feasible, and no parent dependency.

Samples:
Temporary bootstrap 503, invalid text file upload, valid 1x1 PNG upload, transient 503 save route, typed draft text, selected photo preview.

Test matrix:
| Case | Risk | Evidence |
|---|---|---|
| `load_error` durable DOM | Bootstrap failure could leave only toast/no task state | Browser smoke asserts visible `#childErrorPanel`, `data-error-kind=load_error`, child-safe title/body/action, form hidden, live status |
| `load_error` focus/retry | Button could be decorative | Browser smoke asserts focus on panel; focused probe clicked retry after restoring route and reached ready child form |
| `save_error` durable DOM/draft/photo | Failed save could lose work | Browser smoke intercepts first submission with 503, asserts panel, focus, draft `-19`, photo preview still visible |
| `save_error` retry | Retry could duplicate or stay stuck | Browser smoke clicks `#childErrorActionBtn`, then confirms progress advances to `2 / 10` and panel hides |
| `upload_error` durable DOM/draft | Invalid photo could wipe answer or leave stale preview | Browser smoke asserts panel, focus, draft preserved, stale preview hidden |
| `upload_error` reselect | Button could be decorative | Focused probe clicked panel action, handled file chooser, selected valid PNG, preview appeared, error panel cleared, draft remained |
| Child-safe boundary | Error states could leak internal terms | Smoke child-only scans stayed green in the same run |

Evidence:
- Identity YAML header validated against registry: PASS for `agentKey=guanzhi`, display `观止`.
- DOM exists in `index.html:41`: one durable `#childErrorPanel` with `role=status`, `aria-live=polite`, labels/descriptions, focus target, and action button.
- Error fixtures include all three states in `app.js:72`.
- Child-safe copy/action labels are defined in `app.js:164`.
- Focus is implemented by `focusErrorPanel` and `setErrorPanel` in `app.js:189`.
- `load_error` hides fake task/form in `app.js:430`.
- `upload_error` sets durable panel and preserves answer text while clearing bad photo preview in `app.js:680`.
- `save_error` sets durable panel after failed save without clearing text/photo evidence in `app.js:769`.
- Panel actions route to load retry, save retry, and upload reselect in `app.js:784`.
- Fixture hooks preserve save/upload drafts and focus the panel in `app.js:878`.
- Browser smoke assertions for load/fixture panels are in `tests/browser_smoke_learning_system.mjs:90`.
- Browser smoke assertions for upload/save error panels, focus, draft/photo preservation, and save retry are in `tests/browser_smoke_learning_system.mjs:226`.
- `node --check app/local_learning_system/app.js`: exit 0.
- `node --check tests/browser_smoke_learning_system.mjs`: exit 0.
- `node tests/browser_smoke_learning_system.mjs`: exit 0, output `PASS browser smoke: child-only flow -> pending guard -> analyzed evidence evolution`.
- Additional focused temporary browser probe: exit 0, output `PASS REG-05 focused probe: load retry and upload reselect action preserve child flow`.

False-pass audit:
No PASS claim was accepted from 听云/若命 alone. Command exit codes and output agree. The smoke uses temp DB/uploads and blanks model keys, so it proves frontend/contract behavior only. I did not use production DB/uploads, did not reset project data, and did not call external models.

Visual/interaction regression audit:
Covered: DOM visibility, mobile `load_error` viewport in smoke, focus landing on the panel, live-region attributes, retry/reselect interactions, no fake task form on load failure, draft/photo preservation on save/upload failure.

Not fully covered: saved screenshot artifacts, axe/accessibility tree inspection, full keyboard tab-order sweep across every state, contrast measurement, reduced-motion evidence, and human visual/taste approval.

Semantic/product audit:
Only child-safe copy and no-parent/no-internal-leakage boundary were checked for this narrow frontend state scope. No learning correctness, graph binding, model judgment, OCR quality, planning, or teaching quality was audited here.

Model-risk audit:
Not applicable beyond scope. All checks were deterministic local browser/API contract checks with model keys blanked; no live provider evidence was claimed.

Adversarial/destructive cases:
Used non-destructive transient failures: bootstrap 503, invalid upload file, first-save 503. No DB reset, no real upload directory mutation, no external side effects.

Long-run behavior:
Not covered. Multi-round convergence and durable production runtime behavior remain outside this focused REG-05 QA.

Failures:
None in scoped evidence.

Defect severity:
No P0/P1/P2 defect found in the scoped REG-05 panel contract.

Not covered:
Full product QA, full visual QA, model/OCR/provider quality, real child learning semantic quality, parent/Codex reporting, production data, long-run learning loops, final human taste/business review.

Residual risk:
`tests/browser_smoke_learning_system.mjs` itself covers save retry directly and load/upload retry mostly through DOM/action labels plus later valid interactions; the separate focused probe proves load retry and upload reselect behavior but is not persisted as a regression test. A future hardening pass should persist those two click-through assertions if REG-05 becomes release-critical.

Required next action:
No REG-05 fix required before the next scoped gate. For release-level frontend QA, persist load-retry/upload-reselect click-through assertions in the smoke and add screenshot/accessibility/keyboard-tab evidence.
