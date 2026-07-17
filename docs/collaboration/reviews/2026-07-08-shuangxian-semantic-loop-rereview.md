### DATA_REVIEW / PASS_WITH_SCOPE - 霜弦（agentKey: `shuangxian`）- 2026-07-08 15:47 CST

Verdict:
PASS_WITH_SCOPE. The 10-lesson semantic loop is reasonable as deterministic/simulated evidence for structure, persistence, and graph-bound planning. It does not prove live model grading quality, and it does not close the existing question-bank content P0s around repeated core stems and metadata-only graph binding.

independence_required:
yes

context_mode:
fresh rereview

context_origin:
Direct user/若命 request to review the latest 10-lesson simulated child learning report and evidence chain.

diff_pin:
not_applicable; workspace is not a git repository in this runtime.

Scope:
Review only the semantic loop evidence for 10 simulated lessons, answer-analysis structure, next-plan lineage, and whether existing content-quality P0s should remain open. No production code edits, DB mutation, external model calls, or simulation rerun were performed.

Project boundary overlay:
Private AI-native math learning system for one incoming Grade 7 child. Every teaching, diagnosis, question, status, and plan must bind to graph nodes; 七上 wrong/weak evidence should inspect prerequisite chains before same-type drilling; few diagnostic questions are preferred over mechanical drill. Model/report claims must distinguish deterministic simulation from live model evidence.

Data ops risk:
High. A false PASS here could let simulated deterministic labels masquerade as real model quality or let a runnable loop hide content-bank defects.

Fact sources:
- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/shuangxian.md`
- `docs/collaboration/playbooks/data-learning-system-addendum.md`
- `docs/domain-index/math-learning.md`
- `docs/system/qa/simulated_child_learning_journey_latest.md`
- `scripts/child_learning_scenarios.py`
- `scripts/simulate_child_learning_journey.py`
- `learning_system/db.py`
- `learning_system/auto_review.py`
- `learning_system/evolution.py`
- `learning_system/planner.py`
- read-only SQLite sampling of `/tmp/son-learning-10lessons-sessionfix-r2.sqlite`
- prior content audit: `docs/collaboration/reviews/2026-07-08-shuangxian-question-bank-mainline-audit.md`
- scoped grade-level report: `docs/system/qa/question_bank_grade_level_latest.md`

Lineage checked:
- child answer / simulated photo OCR -> `answer_analysis` -> `error_tags` / `process_gap` / `blocking_evidence`
- `answer_analysis.comparison` -> `cause_analysis.unstable_dimensions`
- attempts -> `learner_node_status.evidence_attempt_ids_json`
- node status -> planner `planning_signal`
- planner task -> `evidence_attempt_ids`, `dominant_error_tags`, `process_gaps`, `rollback_candidates`, `source_node_ids`
- weak evidence -> rollback / prerequisite_probe / remediate / retest task types
- simulated report language -> deterministic/temp DB scope limits

Samples/artifacts:
- Report says 10 lessons, 100 attempts, 100 background jobs, verdict PASS, issues 0, DB `/tmp/son-learning-10lessons-sessionfix-r2.sqlite`.
- DB counts sampled: `learning_sessions=10`, `attempts=100`, `background_jobs=100`, `learner_node_status=14`, `generated_plans=17`, `question_items=1223`.
- Session/job status sampled: all 10 learning sessions `closed/planned`; all 100 jobs `succeeded`.
- Attempt distribution sampled: `correct=42`, `partial=46`, `wrong=12`, all `graded/active`.
- Scenario distribution sampled: `wrong_reason_right_answer=10` all partial with `concept_confusion,modeling_or_reading`; `partial_relation_wrong_final=16` all partial with `calculation_or_symbol`; `answer_only=14` all partial with `process_habit`.
- Five-dimension validation sampled: all 100 attempts have all required dimensions: `final_answer`, `model_or_relation`, `steps`, `symbols_units`, `check_or_explanation`.
- Closure next plans sampled: 100 plan tasks across 10 closure plans; follow-up tasks were `rollback=20`, `prerequisite_probe=13`, `remediate=14`, `retest=2`, and every follow-up task had evidence links.
- Linked plan attempt refs sampled: 53/53 refs resolved to active graded attempts with non-empty answer analysis.

Findings:

1. Scoped pass: five-dimension `answer_analysis` can express "answer right but reasoning wrong."
Evidence:
- `learning_system/db.py` requires all five comparison dimensions and requires `process_gap` whenever any required dimension is `missing`, `incorrect`, or `unclear`.
- `learning_system/auto_review.py` prompt policy says a correct final answer is not full credit unless final answer, relation/model, steps, symbols/units, and check/explanation are sound; the local process-evidence guard caps answer-only correct claims to partial.
- In the temp DB, all 10 `wrong_reason_right_answer` attempts were partial, with `final_answer:matched`, `model_or_relation:incorrect`, `steps:incorrect`, `symbols_units:unclear`, `check_or_explanation:missing`.
Judgment:
This is structurally adequate for the requested distinction. It remains simulated evidence, not proof that a live model will consistently produce the same judgments.

2. Scoped pass: five-dimension `answer_analysis` can express "relation partly right but final/symbol wrong."
Evidence:
- `partial_relation_wrong_final` was intentionally changed to a semantically valid relation with wrong final/symbol evidence, not a malformed structure case.
- In the temp DB, all 16 `partial_relation_wrong_final` attempts were partial, with `model_or_relation:matched`, `steps:matched`, `final_answer:incorrect`, `symbols_units:incorrect`, `check_or_explanation:missing`, and `process_gap` naming the relation/symbol gap.
Judgment:
This is the right evidence shape for partial mathematical understanding. It avoids collapsing relation-valid/final-wrong evidence into either full correctness or generic wrongness.

3. Scoped pass: the 10-lesson report does not overclaim real model quality.
Evidence:
- The report title and notes frame it as QA simulation.
- It names the temp DB path and states that child review is simulated with 180 ms latency.
- The script patches `_call_openai_evaluator`, `_review_answer_photo`, and question-candidate generation; it does not call live models in this run.
- The report notes that the simulation uses a temporary DB and does not mutate the real learning ledger.
Judgment:
The report is clear enough for deterministic pipeline evidence. Do not cite it as live model semantic quality, production OCR behavior, or real child learning validity.

4. Scoped pass: next plans are evidence-linked rather than random follow-up.
Evidence:
- `planner._latest_planning_signal` reads valid attempts from `learner_node_status.evidence_attempt_ids_json`, falls back to recent valid node attempts, and carries `dominant_error_tags`, `unstable_dimensions`, `process_gaps`, `rollback_candidates`, and created evolved question IDs.
- `planner.generate_next_plan` prioritizes D/C/B node status into rollback, prerequisite_probe, remediate, or retest before filling graph-bound learn tasks.
- `planner._plan_uses_current_active_bank` rejects follow-up tasks without evidence IDs and rejects evidence that is not current active usable attempt evidence.
- DB sampling showed every closure follow-up task had evidence links; sample rows traced `process_habit`, `calculation_or_symbol`, `concept_confusion`, and `modeling_or_reading` into matching process gaps and rollback/prerequisite/remediate task types.
Judgment:
The sampled next-plan chain is traceable to attempts, error tags, process gaps, node status, and rollback/prerequisite/evolved-question selection signals. New `learn` top-up tasks correctly have empty evidence signals because they are graph-bound progression fill, not weak-evidence remediation.

5. Must remain open: existing question-bank content P0s are not covered by this PASS.
Evidence:
- Prior霜弦 mainline audit returned `NEEDS_FIX` for repeated core stems inflating the 20-per-node slot target and for picture-level challenge contexts transplanted across graph nodes, making some graph binding metadata-level rather than semantic.
- `docs/system/qa/question_bank_grade_level_latest.md` is only `PASS_WITH_SCOPE`; the same audit line explicitly noted that its hard checks can false-pass repeated mathematical cores and off-node challenge transplants.
- This 10-lesson simulation samples flow behavior over selected tasks; it does not expert-proofread all 1120 graph-generated rows or validate per-node distinct `core_stem_id` / semantic alignment.
Judgment:
Keep the question-bank P0s open. The semantic loop PASS must not be used to claim "20 usable graph-bound diagnostic questions per node" or to close content-production quality.

Not covered:
- Live model answer-analysis quality and prompt/provider variance.
- Real OCR behavior on actual child handwriting/photos.
- Human/parent/child review of wording, age fit, and cognitive load.
- Exhaustive question-bank proofread or per-node semantic alignment audit.
- Re-running unit tests, browser smoke, or the 10-lesson script; rerunning the script would write QA artifacts outside this review file's allowed write scope.

Residual risk:
- The deterministic scenario fixture may be too clean compared with real child answers: mixed partial work, ambiguous notation, copied answers, and illegible photos still need live-model and human-sample review.
- `learning_system/db.py` validates answer-analysis structure, but semantic truth still depends on the evaluator output and reviewer-quality prompts.
- Plan evidence links are strong for follow-up tasks, but content quality of selected questions remains gated by the unresolved question-bank P0s.

Required next action:
- Accept this rereview as `PASS_WITH_SCOPE` for the deterministic semantic loop and evidence-linked next-plan chain.
- Do not upgrade to full production PASS until live model/OCR semantic samples pass and question-bank P0s are fixed or explicitly waived by 若命/user with risk accepted.
- Keep routing content work to fix repeated core stems, add semantic node-alignment proof, and strengthen the audit gate before claiming active-use content quality.
