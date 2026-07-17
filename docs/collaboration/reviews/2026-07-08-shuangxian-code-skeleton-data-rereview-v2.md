### DATA_REVIEW / PASS_WITH_SCOPE - 霜弦（agentKey: `shuangxian`）- 2026-07-08 12:21 CST

Verdict:
`DATA_REVIEW_PASS_WITH_SCOPE`. Targeted re-review finds the prior DATA_REVIEW_NEEDS_FIX findings fixed for the named current code/data/tests: schema-valid but thin `answer_analysis` is no longer usable evidence; child active-use/session/attempt gates now converge on the reviewer-record schedulable predicate; current graph and question-bank lineage remains clean. This is not a QA PASS and not a live-model semantic/content-naturalness pass.

independence_required:
yes

context_mode:
fresh

context_origin:
Targeted data/content re-review after 听云 evidence-gate DONE_CLAIMED and 若命 local verification. 若命 verification was treated as context, not as substitute evidence.

diff_pin:
no git diff; reviewed current files and named tests.

Scope:
Only rechecked whether prior findings are fixed:
1. `answer_analysis` validity/usability rejects schema-valid but thin analysis and requires the five comparison dimensions plus either meaningful `process_gap` or explicit `no_gap_observed`.
2. Child active-use/session/attempt gates uniformly use reviewer-record schedulable predicate, with no low-quality/unreviewed diagnostic bypass into usable evidence.
3. Current graph/question-bank lineage remains clean.

Forbidden scope honored:
No implementation/data edits, no DB/upload reset, no external model calls, no QA PASS.

Project boundary overlay:
Applied from `AGENTS.md`, `docs/product/ai_native_math_learning_prd_v2.md`, `docs/architecture/data_contract_spec_v2.md`, `docs/domain-index/math-learning.md`, and `docs/collaboration/playbooks/data-learning-system-addendum.md`: evidence usable only if active + graded + valid answer_analysis + current active reviewer-approved child schedulable question; evolved/spec-loaded questions must pass reviewer gate before active use; low-quality question bypass is not allowed.

Data ops risk:
Medium, scoped down from previous medium-high for these three findings. The executable gates now block the two prior bypass paths, but live-model semantic quality, human教研 naturalness, and long-run threshold behavior remain outside this re-review.

Fact sources:
- Identity/startup: `AGENTS.md`, `docs/collaboration.md`, `docs/collaboration/agent-registry.json`, `docs/collaboration/roles/shuangxian.md`, `docs/collaboration/playbooks/data-learning-system-addendum.md`, current `docs/collaboration/inbox.md`.
- Prior finding and fix claim: `docs/collaboration/reviews/2026-07-08-shuangxian-code-skeleton-data-review-v2.md`, `docs/architecture/code_skeleton_pass_v2.md`.
- PRD/data contract/domain: `docs/product/ai_native_math_learning_prd_v2.md`, `docs/architecture/data_contract_spec_v2.md`, `docs/domain-index/math-learning.md`.
- Code/tests/data: `learning_system/db.py`, `learning_system/evolution.py`, `learning_system/question_bank.py`, `learning_system/planner.py`, `learning_system/server.py`, `learning_system/orchestrator.py`, `learning_system/flow_nodes.py`, `learning_system/reports.py`, `learning_system/agents.py`, `tests/test_learning_system.py`, `tests/browser_smoke_learning_system.mjs`, `docs/system/qa/question_bank_grade_level_latest.md`, `data/knowledge_graphs/math/math_knowledge_graph_v2.json`.

Lineage checked:
- Graph asset: 56 nodes, 225 graph edges, 0 unknown prerequisites, 0 unknown unlocks, 0 nodes missing diagnosis/teaching/question/error contracts.
- Question bank DB: 1120 current `graph_generated` items for version `2026-07-07.bank.v9`; 1120 approved active reviewer records; per-node approved min/max/count = 20/20/56.
- Legacy diagnostics: 48 diagnostic rows remain, but 0 active approved diagnostic reviewer records; `is_child_schedulable_question` rejects them.
- Current plan: latest generated plan has 10 tasks, 0 unknown question refs, 0 unapproved question refs.
- Attempts/evidence: current DB has 0 active attempts, 0 active attempts on unreviewed questions, 0 active attempts on invalidated-source evolved questions, 0 graded active attempts missing analysis JSON.
- `db.lineage_integrity_audit` read-only result: issue_count 0 across learner status refs, stale review records, invalidated-source attempts, superseded reviews, superseded bank attempts, and superseded bank review records.

Samples/artifacts:
- `docs/system/qa/question_bank_grade_level_latest.md`: PASS_WITH_SCOPE, 1120 items, 56 nodes, active round picture-level tasks 9/10, live DB lineage issues 0.
- Read-only `sqlite3 -readonly data/local_learning_system.sqlite` audits:
  - `graph_nodes|56`, `graph_edges|225`
  - `current_graph_generated|1120`, `approved_current_reviews|1120`
  - `legacy_diagnostic_items|48`, `diagnostic_active_review_records|0`
  - `unknown_question_node_refs|0`
  - `current_unapproved_or_missing_reviews|0`
  - `active_attempts_total|0`, `active_attempts_unreviewed_questions|0`
  - `approved_per_node_min_max_nodes|20|20|56`
  - `latest_plan_unknown_questions|0`, `latest_plan_unapproved_questions|0`
- Focused tests run in this re-review:
  - `test_thin_answer_analysis_is_not_usable_evidence`
  - `test_session_close_blocks_when_review_record_no_longer_schedulable`
  - `test_evolution_rejects_attempt_when_review_record_no_longer_schedulable`
  - `test_unreviewed_diagnostic_question_cannot_enter_child_active_use`
  - `test_child_text_submission_caps_overconfident_answer_only_full_credit`
  - `test_child_text_submission_keeps_pending_when_ai_omits_answer_analysis`
  - `test_child_learning_semantic_scenario_matrix_covers_multi_state_answers`
  All passed locally in this re-review.

Findings:
1. Prior P1 fixed - thin `answer_analysis` is rejected before evidence use. `learning_system/db.py` now defines `REQUIRED_ANALYSIS_DIMENSIONS` and requires coverage of `final_answer`, `model_or_relation`, `steps`, `symbols_units`, and `check_or_explanation`; weak dimensions require non-empty `process_gap`; all-matched/no-gap cases require explicit boolean `no_gap_observed`. `is_current_usable_attempt_evidence` and `EvidenceUsePolicy` depend on `is_valid_answer_analysis`. The focused tests prove thin/malformed analysis blocks usable evidence, session close, mastery decision, and downstream evolution/planning.

2. Prior P1 fixed - reviewer-record active-use gate is now the child evidence authority. `is_child_schedulable_question` requires graph node binding, current active item semantics, no invalidated evolved source, and an approved active `question_review_records` row. `create_learning_session_for_plan`, server learning-session creation, child/operator submissions, `record_attempt`, stale session retirement, planner validation, and evolution source checks route through this predicate or through `EvidenceUsePolicy`. The unreviewed diagnostic regression confirms legacy diagnostic rows cannot become child active-use attempts.

3. Prior lineage concern remains clean in current assets. Current graph/question-bank references are internally consistent for this targeted audit, the latest plan points only at reviewer-approved current questions, and the live lineage audit reports 0 issues. No evidence was found that evolved/spec-loaded questions or low-quality/unreviewed questions can become usable evidence through current named paths.

Not covered:
- No live GPT/Doubao/external model call and no judgment that live model semantic grading is production-quality.
- No destructive DB reset or upload mutation.
- No exhaustive human教研 review of all 1120 prompts; relied on existing audit plus targeted DB/code/test evidence.
- No UX review, code architecture review, or QA PASS.
- Did not validate future `data/question_specs/` activation beyond the current disabled/parity-gated seam.

Residual risk:
- `db.create_session` remains a generic low-level helper and can be used to create an empty session with arbitrary expected ids, but current evidence-producing paths (`create_learning_session_for_plan`, server submission routes, and `record_attempt`) block unreviewed/stale questions before active evidence is accepted. Treat direct use of `create_session` for child learning groups as an implementation discipline risk for future work, not an active evidence bypass in the reviewed paths.
- Reports and agent summaries now use usable-evidence predicates for analyzed counts, but future report claims still need claim-by-claim evidence labels before parent-facing overstatement risk is fully closed.
- Live-model output may still be semantically bad while structurally valid; this re-review only verifies structural/no-gap/evidence-gate behavior and existing semantic guardrail samples.

Required next action:
No further fix required for the three prior DATA_REVIEW_NEEDS_FIX findings. Proceed only within scope to the next independent gate/QA step; keep this result as `PASS_WITH_SCOPE`, not QA PASS. Before activating any future question-spec loader or accepting live-model grading as production evidence, require reviewer gate parity tests and live semantic QA samples.
