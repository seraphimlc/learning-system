### DATA_REVIEW / NEEDS_FIX - 霜弦（agentKey: `shuangxian`）- 2026-07-10 18:37 CST

Verdict:
`DATA_REVIEW_NEEDS_FIX`. `docs/architecture/technical_plan_v3.md` has the right direction for v3: graph-bound runtime, compact candidate packets, active-use question gating, `usable` as a predicate, additive schema, and fail-closed evidence handling. It is not yet explicit enough for the v3 first implementation skeleton because the first-slice engineering contract leaves key lineage fields underspecified exactly where old v2 status rows, old graph/question rows, or mock/pending evidence could leak into `learner_node_status`, `mastery_decision`, `next_step_decision`, and reports.

independence_required:
yes

context_mode:
fresh

context_origin:
spawned only for this review; did not author `docs/architecture/technical_plan_v3.md`.

diff_pin:
`docs/architecture/technical_plan_v3.md`

Scope:
- Reviewed data/graph/question/evidence/report contract sufficiency for the v3 first implementation slice.
- Focused on `graph_version`, question candidate packet, active-use gate, `review_target`, `learner_node_status`, `answer_analysis` -> `evidence_validation` -> `mastery_decision` -> `next_step_decision` lineage, report labels, v2 old-data handling, no full question bank hot path, and `usable` as predicate.

Project boundary overlay:
- Applied PRD v3 `PROJECT_BOUNDARY_OVERLAY` from `docs/product/ai_native_math_learning_prd_v3.md`.
- Applied `AGENTS.md` and `docs/domain-index/math-learning.md`.
- Applied role addendum `docs/collaboration/playbooks/data-learning-system-addendum.md`.

Data ops risk:
high. The plan governs child learning evidence, math graph lineage, active question admission, AI answer analysis, mastery/planning decisions, async recovery, and parent/Codex reports.

Fact sources:
- Identity/startup: `AGENTS.md`, `docs/collaboration.md`, `docs/collaboration/roles/shuangxian.md`, `docs/collaboration/agent-registry.json`, `docs/collaboration/inbox.md`.
- Mandatory addendum: `docs/collaboration/playbooks/data-learning-system-addendum.md`.
- Boundary/product/architecture: `docs/product/ai_native_math_learning_prd_v3.md`, `docs/architecture/ai_native_learning_system_architecture_v3.md`, `docs/architecture/daily_learning_runtime_contract_v1.md`, `docs/domain-index/math-learning.md`.
- Reviewed plan: `docs/architecture/technical_plan_v3.md`.
- Current code facts: `learning_system/db.py`, `learning_system/question_bank.py`, `learning_system/planner.py`, `learning_system/auto_review.py`, `learning_system/reports.py`, `tests/test_learning_system.py`.
- Graph artifact: `data/knowledge_graphs/math/math_knowledge_graph_v2.json`, `data/knowledge_graphs/math/math_knowledge_graph_v2.md`.

Lineage checked:
- Graph asset -> `graph_nodes` / `graph_edges` -> planner rollback/prerequisite candidates.
- Graph node -> generated/evolved question -> reviewer record / active-use gate -> candidate packet.
- Child attempt/OCR/answer -> `answer_analysis` -> `evidence_validation` -> `mastery_decision` -> `learner_node_status` -> planner next step.
- Attempt/decision/report source -> daily summary/Codex report labels.

Samples/artifacts:
- Graph JSON check: 56 unique nodes, 225 edges, 95 prerequisite edges, no missing prerequisite/unlock/edge refs, no duplicate node ids, no nodes missing the main diagnosis/teaching/question/error contracts.
- Active graph metadata source exists: `metadata.version=2026-07-04.v2`; content hash observed as `1067b9c318efb116f6463fb7dd3db1a3888b440b6d33384c81313f79711a2971`.
- Current DB/code facts: current `graph_nodes`, `question_items`, `attempts`, `learner_node_status`, `mastery_decisions`, and reports do not have first-class v3 `graph_version` lineage; current report labels are `confirmed`, `pending`, `inferred`, `stale`, `blocked`, `missing`, not the full v3 label set.

Findings:

1. P1 - `learner_node_status` / `mastery_decision` lineage is not contracted tightly enough before skeleton.
   - Evidence: the plan says every evaluation/report claim must carry `graph_version` (`docs/architecture/technical_plan_v3.md:116`) and recognizes current attempts lack `graph_version`/`analysis_status` (`docs/architecture/technical_plan_v3.md:168`). But the first-slice field contract only specifies `evidence_validations.gate_status`, `next_step_decisions.action`, and summary labels (`docs/architecture/technical_plan_v3.md:489`-`491`); the change map adds `attempts.graph_version` but does not add v3 provenance fields to `learner_node_status` or `mastery_decisions` (`docs/architecture/technical_plan_v3.md:681`-`683`). Current code's `learner_node_status` table has only node, status, score/explain flag, attempt ids, reason, and timestamp (`learning_system/db.py:380`-`388`).
   - Risk: old v2 status rows can remain planner-visible as if current, or a newly written status can lack `graph_version`, `mastery_decision_id`, `source_evidence_validation_ids`, and question-bank lineage. That is a direct path for stale/missing-lineage evidence to influence `review_target`, planning, or reports.
   - Required fix: add an explicit v3 contract that `learner_node_status` is planner-usable only when derived from a current `mastery_decision` whose source attempts have passed `EvidenceUsePredicate` under the same `graph_version` and active question-bank version. Legacy status rows must be treated as `missing_lineage`/status hints only until recomputed. Contract fields should include equivalent provenance for `graph_version`, `mastery_decision_id`, `source_attempt_ids`, `source_evidence_validation_ids`, `agent_run_id`, `question_bank_version`, and stale/missing-lineage handling.

2. P1 - `next_step_decision` lineage/status is under-specified; only `action` is field-contracted.
   - Evidence: PRD v3 defines `next_step_decision` as accepted/rejected/fallback/blocked (`docs/product/ai_native_math_learning_prd_v3.md:690`), while the runtime contract requires `source_evidence`, reason, and branch policy. The technical plan field table only fixes `next_step_decisions.action` (`docs/architecture/technical_plan_v3.md:490`) and the call chain says the worker writes a next-step decision (`docs/architecture/technical_plan_v3.md:505`) without a durable source-evidence schema.
   - Risk: an implementation can record a plausible next action without proving whether it came from passed evidence, pending-safe fallback, a mock model path, stale graph/question lineage, or an active-use candidate packet. Reports could then claim "next" without knowing if the decision was confirmed, fallback, blocked, mock-only, or missing-lineage.
   - Required fix: define first-slice required fields for `next_step_decisions`: `decision_status`, `graph_version`, `source_attempt_ids`, `source_evidence_validation_ids`, `source_mastery_decision_ids`, `candidate_packet_hash/id`, `candidate_filter_summary_json`, `pending_evidence_ids`, `model/provider/route mode or deterministic fallback`, `reason`, `branch_policy_json`, and report label. Decisions missing those fields must be rejected for confirmed planning/report claims.

3. P1 - Candidate packet / active question slot graph-version handling is not explicit enough for v2 bank rows.
   - Evidence: PRD v3 requires candidate packet fields including `graph_version`, `item_version`, `review_record_id`, family/signature, difficulty vector, evidence goal, target tags, reasoning flag, `why_candidate`, and `filter_summary` (`docs/product/ai_native_math_learning_prd_v3.md:433`-`451`). The technical plan interface says 5-8 metadata rows plus filter summary (`docs/architecture/technical_plan_v3.md:459`) and tests say required metadata (`docs/architecture/technical_plan_v3.md:578`), but the engineering contract does not enumerate the exact packet schema or how current v2 `question_items` rows get a v3 `graph_version`. Current `question_items` has `item_version`, node, rubric, solution, source/raw JSON, but no first-class `graph_version` (`learning_system/db.py:304`-`326`).
   - Risk: current v2 graph-generated rows can be selected into v3 candidate packets as "active" based on item version/reviewer record while still missing explicit graph-version lineage. That weakens the protection against stale graph or metadata-only active-use claims.
   - Required fix: add the exact candidate packet schema from PRD into `TECHNICAL_PLAN`/`ENGINEERING_CONTRACT`, including active-use proof fields. Define how seed v2 bank rows are either backfilled to `graph_version=metadata.version+sha256` with durable reviewer-record proof, or excluded/labeled `missing_lineage` for v3 scheduling. The planner packet must never include full solution banks; solution/rubric is fetched only after selection for display/analysis.

4. P2 - Report label vocabulary is declared but not fully test-contracted.
   - Evidence: the plan field contract lists `confirmed/pending/blocked/inferred/stale/mock_only/missing_lineage` in `daily_summaries.report_label_json` (`docs/architecture/technical_plan_v3.md:491`), but the explicit tests only name `confirmed`, `pending`, and `blocked` summary labels (`docs/architecture/technical_plan_v3.md:732`). Current report code cannot emit `mock_only` or `missing_lineage` labels (`learning_system/db.py:30`, `learning_system/reports.py:26`-`35`).
   - Risk: mock-only or missing-lineage facts can be flattened into generic pending/missing labels, making parent/Codex summaries overstate evidence scope.
   - Required fix: include the full v3 report-label enum and precedence in the first-slice contract/tests. At minimum, tests must cover `stale`, `mock_only`, and `missing_lineage`, and reports must not emit `confirmed` unless the same evidence is planner/mastery usable under current `graph_version`.

Positive checks:
- The plan correctly rejects full-bank planner context and requires a compact candidate packet.
- The plan correctly states `usable` is a predicate, not a stored status.
- The plan correctly keeps pending, invalidated, stale, mock-only, missing-lineage, low-confidence, or operator-attention evidence out of mastery/planning in principle.
- The current graph asset is internally consistent in the sampled structural checks.
- Current v2 code already has useful starting points: `db.is_current_usable_attempt_evidence`, reviewer-record active-use checks, invalidated-lineage repair, structured answer-analysis validation, and model-router-only answer analysis.

Not covered:
- No production code changes were made.
- No tests, server, browser QA, or live model calls were run.
- This is not engineering architecture PASS, QA PASS, or final DATA_CONTRACT_SPEC v3.

Residual risk:
- DATA_CONTRACT_SPEC v3 remains required. After the findings above are fixed, this technical plan can proceed to skeleton with scope limited to table/service/route shells and fail-closed stubs.
- Live semantic model quality and OCR reliability remain outside this document review; they need recorded/live QA evidence later.

Required next action:
Fix `docs/architecture/technical_plan_v3.md` before first-slice skeleton by adding the missing v3 data/lineage contracts above, or produce a dedicated DATA_CONTRACT_SPEC v3 that the technical plan explicitly imports before schema/table skeleton work. Do not fill business logic until those fields and labels are reviewed.
