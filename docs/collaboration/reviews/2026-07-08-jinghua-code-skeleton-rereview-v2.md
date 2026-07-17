### CODE_REVIEW / PASS_WITH_SCOPE - 镜花（agentKey: `jinghua`）- 2026-07-08 12:19 CST

Verdict:
`CODE_REVIEW_PASS_WITH_SCOPE`. The two prior P1 findings from `docs/collaboration/reviews/2026-07-08-jinghua-code-skeleton-review-v2.md` are fixed in the current files. This is a targeted re-review only: I verified the evidence-gate wiring and spot-checked child/operator and model side-effect boundaries touched by these fixes; I did not broaden into full implementation QA or semantic model/OCR quality.

independence_required:
Yes. Reviewed independently in a fresh 镜花 context. I did not participate in the fixes and did not edit production code.

context_mode:
fresh

context_origin:
re-review after 听云 DONE_CLAIMED evidence-gate fixes and 若命 local verification.

diff_pin:
no git diff; reviewed current files and named tests.

Scope:
Only verified whether the two prior P1 findings are fixed:
1. session close/evaluation uses shared usable evidence and blocks unusable evidence before answer/evaluation/evolution/planning;
2. self-evolution candidate path filters through `db.is_evolution_source_valid` final authority.

Also spot-checked no new obvious regression in child/operator boundary or model external side effects from these changes.

Project boundary overlay:
Applied `AGENTS.md`, `docs/domain-index/math-learning.md`, and the user-provided overlay: evidence usable for evaluation/planning/evolution only if active + graded + valid_answer_analysis + current_child_schedulable_question; child-only Web; parent via Codex/operator surfaces; model provider via `model_router`; no external model calls.

Source artifacts:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/agent-registry.json`
- `docs/collaboration/roles/jinghua.md`
- `docs/project-rules/system-architecture-learning-addendum.md`
- `docs/collaboration/inbox.md`
- `docs/project-index.md`
- `docs/domain-index/math-learning.md`
- `docs/collaboration/reviews/2026-07-08-jinghua-code-skeleton-review-v2.md`
- `docs/architecture/code_skeleton_pass_v2.md`
- `learning_system/db.py`
- `learning_system/orchestrator.py`
- `learning_system/flow_nodes.py`
- `learning_system/evolution.py`
- `learning_system/planner.py`
- `learning_system/server.py`
- `tests/test_learning_system.py`
- `tests/browser_smoke_learning_system.mjs`

Evidence:
- Identity binding: `jinghua` role YAML header matches `docs/collaboration/agent-registry.json` for display, role type, identity file, permissions, output contracts, and required init files.
- Code-path proof for P1 #1:
  - `learning_system/db.py:23-40` defines the shared `EvidenceUsePolicy` as `active_graded_valid_analysis_current_question`.
  - `learning_system/db.py:2037-2067` makes usable/evolution evidence require `is_child_schedulable_question`, valid answer analysis, active evidence, and graded status.
  - `learning_system/db.py:2140-2160` routes stale session question checks through `is_child_schedulable_question`.
  - `learning_system/db.py:2286-2318` separates `structurally_analyzed_attempt_ids`, `usable_attempt_ids`, and `unusable_evidence_attempt_ids`; `analyzed_attempt_ids` now aliases usable ids.
  - `learning_system/orchestrator.py:716-794` blocks `missing_analysis` and `unusable_evidence` before `build_answer_analysis_package`, graph binding, mastery evaluation, `evolution.run_evolution`, and `planner.generate_next_plan`.
  - `learning_system/flow_nodes.py:62-67` builds downstream answer/graph/mastery packages only from `usable_attempt_ids`.
  - `learning_system/planner.py:169-227` filters planning signals through `db.is_current_usable_attempt_evidence`.
- Code-path proof for P1 #2:
  - `learning_system/evolution.py:474-517` filters `_candidate_attempts` through `db.is_evolution_source_valid(conn, attempt)` as the final authority.
  - `learning_system/evolution.py:609-657` returns `no_action` without profile/status/question updates when no valid candidate remains.
  - `learning_system/evolution.py:764-859` performs profile updates, node status writes, question creation, and processed-event marking only after the filtered candidate list exists.
- Child/operator/model spot-check:
  - `learning_system/server.py:70-87` keeps child projection routed through `ChildAPIProjection`; `server.py:933-947` rejects child submissions using internal ids and checks child schedulability.
  - `learning_system/server.py:1320-1328` projects child close responses through `_child_close_projection`.
  - `tests/browser_smoke_learning_system.mjs:61-70` clears model API env vars during smoke; `tests/browser_smoke_learning_system.mjs:99-151` and `319-323` assert no parent/operator/model internals leak into child page/bootstrap/completion.
- Tests run by 镜花:
  - `python3 -m compileall learning_system` -> passed.
  - `python3 -m unittest tests.test_learning_system.LearningSystemTest.test_thin_answer_analysis_is_not_usable_evidence tests.test_learning_system.LearningSystemTest.test_session_close_blocks_when_review_record_no_longer_schedulable tests.test_learning_system.LearningSystemTest.test_evolution_rejects_attempt_when_review_record_no_longer_schedulable tests.test_learning_system.LearningSystemTest.test_unreviewed_diagnostic_question_cannot_enter_child_active_use tests.test_learning_system.LearningSystemTest.test_reports_and_planner_reject_current_pending_or_malformed_analysis_evidence -v` -> 5 tests passed.
  - `/Users/liuchang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/browser_smoke_learning_system.mjs` -> passed: `PASS browser smoke: child-only flow -> pending guard -> analyzed evidence evolution`.

Implementation fidelity:
Within the targeted scope, fidelity is satisfactory. The shared usable-evidence predicate is now wired into session readiness, flow-node package construction, planner evidence signals, attempt recording, session creation, and evolution candidate selection. The closure chain blocks unusable evidence before answer analysis packaging, graph binding, mastery evaluation, self-evolution, next planning, and child review-ready projection.

Findings:
None in targeted scope. The two prior P1s are resolved.

Residual risk:
- `PASS_WITH_SCOPE` because this was not a full architecture/QA pass and did not re-review all v2 skeleton behavior.
- I did not call external models and did not validate live GPT/Doubao answer-analysis/OCR semantic quality.
- Browser smoke gives useful child/operator boundary evidence, but final child UX/taste/accessibility review remains 清秋/观止/user scope.
- The session close path now blocks unusable evidence after recording an evidence package audit. This is acceptable for the reviewed P1 because answer/evaluation/evolution/planning are blocked before use; later QA can decide whether the evidence-package audit should also carry a more explicit unusable-evidence label for operator diagnostics.

Required next action:
No code fix required for the two prior P1 findings. Proceed to the next scoped review/QA gates; do not treat this as full release QA.
