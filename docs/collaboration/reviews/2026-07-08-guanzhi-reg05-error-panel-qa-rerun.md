### QA / PASS_WITH_SCOPE - 观止（agentKey: `guanzhi`）- 2026-07-08 14:45 CST

Verdict:
`PASS_WITH_SCOPE` for the focused REG-05 rerun after the `load_error` toast regression fix.

Scope:
- Child-facing REG-05 durable error panels only: `load_error`, `save_error`, `upload_error`.
- Files inspected: `app/local_learning_system/index.html`, `app/local_learning_system/app.js`, `app/local_learning_system/styles.css`, `tests/browser_smoke_learning_system.mjs`.
- No production implementation edits. No backend/model/question/planner/database changes. No external model/OCR calls. No user-visible `8765` service stop.

Project boundary overlay:
Single child Web端 only; parent uses Codex; child can complete normal flow without parent. Child-facing recovery copy must be state-specific and avoid internal graph/model/agent/Codex/parent language.

Source artifacts:
- `docs/product/child_ux_flow_spec_v2.md`
- `docs/qa/test_case_spec_v2.md` REG-05
- `docs/collaboration/reviews/2026-07-08-qingqiu-reg05-error-panel-ux-review.md`
- `docs/project-rules/qa-learning-system-addendum.md`

Environment:
- Workspace: `/Users/liuchang/Documents/gitproject/son-ai-learning-system`
- Browser smoke used a temporary free local port, temporary SQLite DB, and temporary upload directory.
- No live model/OCR provider keys were used by the smoke script.

Test matrix:
| Case | Evidence | Result |
|---|---|---|
| Identity binding | `docs/collaboration/roles/guanzhi.md` header matched `docs/collaboration/agent-registry.json` for `agentKey=guanzhi`, display `观止`, role type, permissions, lifecycle, and contracts | Pass |
| REG-05 oracle | `docs/qa/test_case_spec_v2.md` requires durable page-level `load_error` panel and persistent/inspectable `save_error` / `upload_error`; 清秋 previous finding specifically required load-error transient feedback not to mention saving | Pass |
| Durable DOM panel | `index.html` has `#childErrorPanel` with `role="status"`, polite live region, labels, action button, and focus target; `styles.css` keeps panel visible/actionable and full-width action on mobile | Pass |
| State-specific implementation | `app.js` has `childSafeLoadErrorMessage()` and `enterLoadError()` uses it for the toast; `save_error` still uses save copy; `upload_error` uses photo copy | Pass |
| Persisted regression assertion | `tests/browser_smoke_learning_system.mjs` asserts `!actualLoadErrorPanel.toast.includes("保存")` and also requires connection-language toast copy | Pass |
| Browser load error | Smoke intercepts `GET /api/child-bootstrap` with 503, enters `load_error`, shows focused durable panel, hides fake task form, and verifies toast does not mention saving | Pass |
| Browser fixture panels | Smoke renders `load_error`, `save_error`, and `upload_error` fixtures and checks durable DOM panel kind/title/body/action plus panel focus | Pass |
| Browser upload error | Smoke uploads an invalid file, verifies `upload_error`, panel focus, photo-specific action, typed draft retained, stale preview hidden | Pass |
| Browser save error | Smoke forces first child submission 503, verifies `save_error`, panel focus, save retry action, typed draft retained, selected photo preview retained, retry succeeds | Pass |

Commands run:
| Command | Result |
|---|---|
| `node --check app/local_learning_system/app.js` | exit 0 |
| `node --check tests/browser_smoke_learning_system.mjs` | exit 0 |
| `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs` | exit 0; output `PASS browser smoke: child-only flow -> pending guard -> analyzed evidence evolution` |

False-pass audit:
- Command exit codes and PASS output agree: both syntax checks and the browser smoke exited 0.
- The load-error copy regression is covered by a persisted assertion, not just manual inspection.
- The browser smoke includes DOM/focus/actionability assertions for all three REG-05 states.
- The smoke also checks `browserErrors.length === 0` before printing PASS.
- No separate screenshot artifact or issue-count report was produced in this focused rerun; therefore this is not a final visual/taste or full product QA claim.

Not covered:
- Full product QA, backend semantic grading, graph/planner/evolution correctness, OCR/model behavior, production data, long-run convergence, or final human visual taste.
- Manual screen-reader quality beyond DOM/ARIA/focus evidence.
- Full desktop/mobile screenshot matrix and overflow/contrast audit.

Residual risk:
- REG-05 child-facing behavior is covered by local browser evidence and persisted smoke assertions.
- Final release still needs the broader planned visual/accessibility matrix before claiming full child-flow QA.

Required next action:
No REG-05 implementation fix required from this rerun. Keep the persisted browser-smoke assertion preventing `load_error` toast text from mentioning `保存`.
