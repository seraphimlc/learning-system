### DATA_REVIEW / PASS_WITH_SCOPE - 霜弦（agentKey: `shuangxian`）- 2026-07-10 18:47 CST

Verdict:
`DATA_REVIEW_PASS_WITH_SCOPE`. Focused re-review finds the four prior 霜弦 `NEEDS_FIX` findings addressed in `docs/architecture/technical_plan_v3.md`. The revised plan is now explicit enough, from a data/graph/question/evidence-contract perspective, to proceed to first-slice skeleton work under the stated stop conditions. Scope is limited to technical-plan data contract sufficiency; this is not final `DATA_CONTRACT_SPEC v3`, not implementation approval, and not QA PASS.

independence_required:
yes

context_mode:
focused rereview

context_origin:
Continuation as formal role 霜弦. This context did not author the revised technical plan.

diff_pin:
`docs/architecture/technical_plan_v3.md`

Scope:
- Re-reviewed only the prior findings from `docs/collaboration/reviews/2026-07-10-shuangxian-technical-plan-v3-data-review.md`.
- Checked whether revisions cover:
  1. `learner_node_status` / `mastery_decisions` v3 planner-usable lineage;
  2. `next_step_decisions` source evidence / status / lineage schema;
  3. candidate packet exact schema, active-use proof, v2 bank graph-version backfill or missing-lineage exclusion;
  4. report label full enum, precedence, and `stale`/`mock_only`/`missing_lineage` tests.

Project boundary overlay:
- Applied PRD v3 `PROJECT_BOUNDARY_OVERLAY`, `AGENTS.md`, and `docs/domain-index/math-learning.md`.
- Applied mandatory data/content addendum `docs/collaboration/playbooks/data-learning-system-addendum.md` from the active role contract.

Data ops risk:
high. The reviewed plan still governs graph-bound evidence, active question scheduling, AI analysis, mastery/planning decisions, old-data handling, and parent/Codex report truth labels.

Fact sources:
- `docs/architecture/technical_plan_v3.md`
- Prior review: `docs/collaboration/reviews/2026-07-10-shuangxian-technical-plan-v3-data-review.md`
- Small supporting checks against PRD/architecture/code facts already cited in the prior review were not expanded beyond the focused scope.

Lineage checked:
- `attempt` / `answer_analysis` / `evidence_validation` -> `mastery_decision` -> `learner_node_status` -> review target / planner / report.
- active question review record and graph/bank version -> candidate packet -> `next_step_decision`.
- `next_step_decision` and source evidence -> daily summary / report label.

Findings:

1. Prior P1 `learner_node_status` / `mastery_decision` lineage: fixed.
   - Evidence: the new graph lineage table requires `mastery_decisions` to carry `graph_version`, `node_id`, `question_bank_version`, `source_attempt_ids_json`, `source_evidence_validation_ids_json`, `evaluation_agent_run_id`, `decision_version`, `old_status_id`, `new_status_code`, and dimension scores; legacy decisions without graph/bank/source validation ids are explicitly not planner-usable (`docs/architecture/technical_plan_v3.md:512`).
   - Evidence: `learner_node_status` now requires `graph_version`, `question_bank_version`, `mastery_decision_id`, source attempt/validation ids, agent run id, status revision, and reason; legacy rows are status hints only and must be recomputed before driving review targets or confirmed plans (`docs/architecture/technical_plan_v3.md:513`).
   - Evidence: the dedicated planner-usable contract requires the referenced mastery decision and all source attempts/validations to pass `EvidenceUsePredicate` under the same graph and bank version; legacy rows cannot drive `confirmed`, `A` mastery skip, or `ready_for_new_knowledge` (`docs/architecture/technical_plan_v3.md:518`-`534`).

2. Prior P1 `next_step_decision` lineage/status schema: fixed.
   - Evidence: `next_step_decisions` now has required graph/bank lineage and source fields in the provenance table, and missing source ids or stale graph/bank version can only display as fallback/blocked/pending, never confirmed (`docs/architecture/technical_plan_v3.md:514`).
   - Evidence: the new `Next-step decision schema` defines `decision_status`, source attempts, evidence validations, mastery decisions, review target, candidate packet id/hash, filter summary, pending evidence, skipped nodes, branch policy, provider mode, stale/mock source ids, report label, and reason (`docs/architecture/technical_plan_v3.md:611`-`647`).
   - Evidence: contract tests now require every next-step decision to include the source lineage, candidate packet hash/filter summary, provider/fallback mode, and report label (`docs/architecture/technical_plan_v3.md:907`-`911`).

3. Prior P1 candidate packet / active question graph-version handling: fixed.
   - Evidence: the candidate packet now has a stable `packet_id`, schema version, `graph_version`, `question_bank_version`, target node, flow revision, source review target, candidate count, and filter summary (`docs/architecture/technical_plan_v3.md:550`-`576`).
   - Evidence: candidate rows now enumerate the PRD-required hot-path metadata and active-use proof, including `review_record_id`, family/signature, difficulty vector, evidence goal, target tags, reasoning flag, `active_use_proof`, bank version, and `lineage_status`; only `lineage_status=current` may be sent to the planner (`docs/architecture/technical_plan_v3.md:578`-`600`).
   - Evidence: v2 bank rows can enter v3 packets only after deterministic graph-version backfill plus current bank version and active review record proof; otherwise they are excluded before planner context and counted as `excluded_missing_lineage`. Full solution/rubric bodies are explicitly fetched only after selection, not passed to the planner model (`docs/architecture/technical_plan_v3.md:602`-`609`).

4. Prior P2 report label vocabulary/test contract: fixed.
   - Evidence: allowed report labels are exactly `confirmed`, `pending`, `blocked`, `inferred`, `stale`, `mock_only`, `missing_lineage`, with explicit precedence from `blocked` through `confirmed` (`docs/architecture/technical_plan_v3.md:771`-`795`).
   - Evidence: report tests must cover all seven labels and especially `stale`, `mock_only`, and `missing_lineage`; `confirmed` is impossible unless evidence is planner/mastery usable under current graph and bank version (`docs/architecture/technical_plan_v3.md:793`-`795`).
   - Evidence: contract tests require summaries to include all labels, prove precedence, and reject stale `latest` or v2 fixed-flow artifacts as v3 PASS evidence (`docs/architecture/technical_plan_v3.md:922`-`925`).

Positive checks:
- The revision also strengthens `usable` as predicate: `gate_status=passed` projects to API/report `usable` only after the full predicate succeeds, and the plan forbids storing a bare attempt status called `usable` (`docs/architecture/technical_plan_v3.md:536`-`548`).
- The change map now routes skeleton implementation through exact candidate packet, evidence predicate, lineage columns, and report-label tests (`docs/architecture/technical_plan_v3.md:1034`-`1039`).
- The Review Fix Log accurately names the four 霜弦 fixes and matches the substantive sections found in the plan (`docs/architecture/technical_plan_v3.md:1243`-`1273`).

Not covered:
- This re-review did not review production code, DB migrations, route implementations, tests, browser behavior, live model output, or OCR quality.
- This is not a final `DATA_CONTRACT_SPEC v3`.
- This is not a QA result and does not replace 观止 TEST_CASE_SPEC/QA.
- This is not a final engineering architecture PASS for concurrency/state-machine implementation details.

Residual risk:
- Skeleton review must verify the executable schema, DTOs, predicates, and test files actually implement these contracts rather than only naming them.
- DATA_CONTRACT_SPEC v3 should still settle final table/column names and any report-label vocabulary refinements before final release.
- Live semantic/AI evidence quality remains out of scope for this document-only re-review.

Required next action:
Proceed to first-slice skeleton only within the revised plan's stop conditions. At `SKELETON_PASS`, require focused 霜弦 review of actual schema/helper/predicate/candidate-packet/report-label skeleton fidelity before business logic fill.
