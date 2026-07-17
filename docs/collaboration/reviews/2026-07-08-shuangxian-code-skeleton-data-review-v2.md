### DATA_REVIEW / NEEDS_FIX - 霜弦（agentKey: `shuangxian`）- 2026-07-08 12:36 CST

Verdict:
`DATA_REVIEW_NEEDS_FIX`. Current data assets and current generated bank look clean, but the v2 code skeleton is not yet data/content/evidence-contract ready because two executable seams can still admit weak evidence or unreviewed question active use before business logic implementation.

independence_required:
yes

context_mode:
fresh

context_origin:
independent data/content review context spawned after 听云 DONE_CLAIMED

diff_pin:
no git diff available; reviewed current files listed in `docs/architecture/code_skeleton_pass_v2.md`

Scope:
Data/content skeleton review only: graph/question/evidence contracts, active-use gate, 20-per-node and 10-task assumptions, answer_analysis validity gate, invalidated evidence exclusion, question-spec migration seam, report/evolution lineage, and low-quality question bypass risk.

Project boundary overlay:
Applied from `AGENTS.md`, `docs/product/ai_native_math_learning_prd_v2.md`, `docs/architecture/data_contract_spec_v2.md`, and `docs/collaboration/playbooks/data-learning-system-addendum.md`.

Data ops risk:
Medium-high before business logic fill. The current seeded DB has no observed lineage issue and the generated question bank passes the current audit, but the skeleton gates are not uniformly enforced across all active-use entry points.

Fact sources:
- Identity/startup: `AGENTS.md`, `docs/collaboration.md`, `docs/collaboration/agent-registry.json`, `docs/collaboration/roles/shuangxian.md`, `docs/collaboration/playbooks/data-learning-system-addendum.md`, current `docs/collaboration/inbox.md`.
- Product/data contracts: `docs/product/ai_native_math_learning_prd_v2.md`, `docs/architecture/data_contract_spec_v2.md`, `docs/architecture/project_skeleton_v2.md`, `docs/architecture/code_skeleton_pass_v2.md`, `docs/domain-index/math-learning.md`.
- Domain oracle: `data/knowledge_graphs/math/math_knowledge_graph_v2.json`, `data/knowledge_graphs/math/math_knowledge_graph_v2.md`, `docs/system/qa/question_bank_grade_level_latest.md`.
- Code reviewed: `learning_system/db.py`, `learning_system/planner.py`, `learning_system/question_bank.py`, `learning_system/evolution.py`, `learning_system/reports.py`, `learning_system/auto_review.py`, `learning_system/agents.py`, `learning_system/server.py`, `tests/test_learning_system.py`.
- Read-only audits: `jq` graph integrity checks; `sqlite3 -readonly data/local_learning_system.sqlite` coverage/lineage/source-type checks; scoped `rg`/`sed`/`nl` inspection.

Lineage checked:
- Graph asset -> graph node/edge refs: 56 unique nodes, 225 edges, 95 prerequisite edges, 0 unknown prerequisites, 0 unknown unlocks, 0 nodes missing diagnosis/teaching/question/error contracts.
- Graph node -> question bank -> review gate: current `graph_generated` bank has 1120 items, 56 nodes, min/max 20 per node, 1120 approved active review records, 0 current approved low-quality flag mismatches in read-only DB query.
- Active round assumption: latest generated plan has 10 tasks; planner validation requires exactly 10 unique current active schedulable questions and at least 8 picture-level tasks.
- Attempt/evidence -> planner/evolution/report: planner and evolution mostly consume `db.is_current_usable_attempt_evidence`; report uses current active attempts and lineage audit.
- Invalidated evidence exclusion: current DB read-only checks show 0 active attempts on invalidated-source evolved questions, 0 active attempts total, 0 pending attempts, 0 graded missing analysis attempts.
- Question-spec migration seam: `QuestionSpecLoader.status()` is disabled, `python_gate_authoritative=True`, and `parity_required_before_activation=True`; no `data/question_specs/` activation observed.

Samples/artifacts:
- `docs/system/qa/question_bank_grade_level_latest.md`: PASS_WITH_SCOPE, 1120 items, 56 nodes, 9/10 active-round picture-level tasks, 0 live DB lineage issues.
- `sqlite3 -readonly` samples:
  - `graph_nodes|56`
  - `current_graph_generated|1120`
  - `approved_current_reviews|1120`
  - `min_per_node|20|max_per_node|20|nodes|56`
  - `active_lineage_issues|0`
  - `pending_attempts|0`
  - `graded_missing_analysis|0`
  - `latest_plan_tasks|10`

Findings:
1. P1 - `answer_analysis` validity gate is too weak for evidence use. `db.validate_answer_analysis` only requires a non-empty comparison list with allowed dimensions/statuses; it does not require the PRD/data-contract dimensions `final_answer`, `model_or_relation`, `steps`, `symbols_units`, and `check_or_explanation`, nor does it reject an empty `process_gap` when the comparison is incomplete. `db.is_current_usable_attempt_evidence` then treats this as usable evidence for evaluation/planner/evolution/reports. The skeleton test also locks a weak sample as valid: `tests/test_learning_system.py` `sample_answer_analysis()` defaults to `process_gap=""` and includes only `final_answer` and `model_or_relation`, then `test_v2_code_skeleton_contract_symbols_are_exposed_fail_safe` expects it to be valid. This violates the project rule that schema-valid but vague/untraceable model output must not drive learner status, evolution, plans, or reports. Evidence: `learning_system/db.py:63`, `learning_system/db.py:93`, `learning_system/db.py:2024`, `tests/test_learning_system.py:22`, `tests/test_learning_system.py:264`.

2. P1 - Active-use question review gate is not uniformly enforced at session/attempt boundaries. The planner's latest-plan validator correctly calls `db.is_child_schedulable_question`, but `db.is_current_active_question` returns `True` for non-`graph_generated`/`evolved` source types, `_has_active_question_review_record` also returns `True` for those source types, and `create_learning_session_for_plan` / `record_attempt` validate only `is_current_active_question`. The current DB has 48 legacy `diagnostic` items without `question_review_records`. They are not selected in the current generated plan because the 1120 current generated items cover all nodes, but the skeleton still has an active-use compatibility path that can schedule or record active attempts for non-reviewed source types if a plan/session is constructed outside the planner's validated path. This is a low-quality question bypass risk under the v2 contract. Evidence: `learning_system/db.py:1972`, `learning_system/db.py:1987`, `learning_system/db.py:2118`, `learning_system/db.py:2175`, `learning_system/db.py:2359`, `learning_system/planner.py:600`.

3. Positive check - Current generated question bank, round size, invalidated evidence exclusion, question-spec migration seam, and report lineage shell are directionally aligned. `question_bank.validate_active_item_quality` recomputes the quality gate for current generated/evolved items; `QuestionSpecLoader` is disabled and parity-gated; planner validates 10 unique current schedulable tasks; reports include `evidence_label` and lineage integrity counts. These positives do not remove findings 1-2 because active evidence and question gates still have bypassable seams.

Not covered:
- No external model calls; live GPT/Doubao semantic quality not judged.
- No destructive DB reset, upload mutation, or report regeneration command run.
- No UX taste review and no QA PASS.
- No exhaustive human教研 review of all 1120 prompts; relied on existing audit plus sampled/static contract checks.
- Final question-spec format and mastery thresholds are missing project decisions and were not treated as blockers while the seam remains disabled/parity-gated.

Residual risk:
- Current seeded data looks clean, but downstream business logic could accidentally call the weaker `is_current_active_question` or weak `validate_answer_analysis` path and produce false mastery/planning/evolution/report claims.
- Existing tests prove symbol exposure and several regressions, but the skeleton-specific test currently blesses the too-weak answer-analysis sample instead of rejecting it.
- Report evidence labels are summary-level; later business logic still needs claim-by-claim evidence lineage.

Required next action:
听云 should fix the skeleton before business logic fill:
1. Strengthen `answer_analysis` validity for usable evidence: require the contract dimensions or an explicit locally validated exception, require process-gap semantics when any required dimension is missing/incorrect/unclear, and update tests so vague/schema-only analysis remains pending/unusable.
2. Make all child active-use/session/attempt gates use the same schedulable-question predicate or an explicit reviewed legacy diagnostic allowlist; unknown/non-current source types must be inactive until reviewed.
3. Add/adjust tests proving unreviewed diagnostic/unknown-source questions cannot be scheduled or receive active usable attempts, and weak answer_analysis cannot enter evaluation/planner/evolution/report evidence.
