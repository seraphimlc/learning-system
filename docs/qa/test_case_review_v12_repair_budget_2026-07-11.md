# TEST_CASE_REVIEW - v12 staged repair budgets

- Role: 观止 (`guanzhi`)
- Date: 2026-07-11 CST
- Scope: local item repair versus node-set semantic repair, checkpoint resume, and runner provenance
- Runtime mode: deterministic in-process fixtures; model calls patched; temporary checkpoint directories only
- Forbidden work respected: no production edits, live model calls, real DB mutation, or weakening of the existing 47 cases

## Source Defect

The real pilot can reach local reviewer round 3 for a slot before node-set review rejects its mathematical core. Current `_build_live_node` uses one `slot_rounds` counter and one `max_semantic_rounds` gate for both stages, so local exhaustion prevents any node-set repair. Incomplete checkpoints persist accepted slots and `slot_rounds`, but not node-set rejected slots, repair instructions, or stage-specific counters. Runner/completed-node receipts also omit stage and attempt provenance.

## Added Tests

| Test | Required contract | Current result |
|---|---|---|
| `test_v12_node_set_repair_budget_is_separate_from_exhausted_local_item_rounds` | A slot accepted after local round 3 still receives at least one bounded node-set semantic repair | RED: shared `slot_rounds=3` raises `cross-node repair exhausted` before repair generation |
| `test_v12_node_set_semantic_repair_budget_is_bounded` | Repeated node-set rejection terminates after the configured repair budget | PASS: current shared counter remains bounded; this is the guard against an infinite loop during the split-budget repair |
| `test_v12_failed_node_set_repair_checkpoint_persists_feedback_and_stage_counters` | Failed checkpoint stores rejected slots, pending instructions, local rounds, node-set review round, and node-set repair rounds | RED: `node_set_rejected_slots`, pending feedback, and stage counters are absent |
| `test_v12_node_set_repair_resume_reuses_feedback_without_regenerating_accepted_slots` | Resume regenerates only rejected slots and passes the saved node-set reason/instructions back to the designer | RED: slot 7 alone is regenerated, but `repair_instructions` is empty |
| `test_v12_runner_receipt_preserves_pipeline_stage_and_stage_attempt` | Item, reviewer, node-set shard, runner receipt, and completed checkpoint receipt retain `pipeline_stage` and `stage_attempt` | RED: receipt projection drops the fields |

## Evidence

- Pre-change baseline: `python3 -m unittest -v tests.test_question_bank_v12` -> `47 tests`, all PASS.
- Syntax: `python3 -m py_compile tests/test_question_bank_v12.py` -> PASS.
- Focused new cases: `5 tests`, `1 PASS`, `4 expected assertion failures`, `0 errors`.
- Full file after additions: `52 tests`, `4 failures`, `0 errors`; every pre-existing test remained PASS and only the four new implementation gates failed.

## Gate

TEST_CASE_REVIEW:

- verdict: TEST_CASE_READY_AS_RED_GATE
- production_gap: separate local/node-set budgets, durable node-set repair state, resume feedback, and stage-attempt provenance are missing
- false_pass_control: the bounded-loop case is green while all missing behaviors fail by assertion, not fixture or model-call errors
- semantic_scope: pipeline state/provenance only; no live model quality claim
- required_next_action: 听云 should split the counters, persist/reload node-set repair state, and carry stage-attempt fields into artifacts and receipts without weakening the existing 47 cases
