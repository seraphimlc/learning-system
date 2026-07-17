### DATA_REVIEW / NEEDS_FIX - 霜弦（agentKey: `shuangxian`）- 2026-07-08 15:08 CST

Verdict:
NEEDS_FIX. The current bank passes several hard lineage checks, but it does not yet prove 20 genuinely usable, graph-bound, non-mechanical Grade 7-ready questions per node. The blocking issue is not missing rows; it is inflated quality coverage through repeated core stems and cross-node challenge transplants.

independence_required:
yes

context_mode:
fresh

context_origin:
new mainline audit after REG-05 closed

diff_pin:
not_applicable; current workspace is not a git repo

Scope:
Audit current math question bank and graph-bound production quality for the next implementation slice. No code edits, DB mutation, external model calls, or question-bank changes were performed.

Project boundary overlay:
Private AI-native math learning system for one incoming Grade 7 child. Questions must be graph-bound, diagnostic, age-respectful, process-evidence-bearing, and not low-age drills unless real evidence justifies calculation repair. Reference answers are rubric context only.

Data/content risk:
High. False content PASS could feed the child repeated or semantically off-node tasks while reports/planners claim complete Grade 7 challenge coverage.

Fact sources:
- `AGENTS.md`
- `docs/domain-index/math-learning.md`
- `docs/product/ai_native_math_learning_prd_v2.md`
- `docs/architecture/data_contract_spec_v2.md`
- `docs/collaboration/playbooks/data-learning-system-addendum.md`
- `data/knowledge_graphs/math/math_knowledge_graph_v2.json`
- `learning_system/question_bank.py`
- `learning_system/db.py`
- `scripts/audit_question_bank_grade_level.py`
- `tests/test_learning_system.py`
- read-only SQLite queries against `data/local_learning_system.sqlite`

Scoped passes:
- Identity binding validated: `docs/collaboration/roles/shuangxian.md` YAML core fields match `docs/collaboration/agent-registry.json`.
- Graph integrity hard check passed: 56 nodes, 56 unique ids, 0 unknown `prerequisites` / `unlocks` / edge refs.
- Current live DB hard counts passed: 56 graph nodes, 225 graph edges, 1120 `graph_generated` rows on `2026-07-07.bank.v9`, 48 diagnostic rows.
- Review-record existence passed as a narrow ledger check: 1120 `question_review_records`, all `approved` and `active_eligible=1`.
- Explicit weak sample fragments were absent from the live bank: no prompts matching `4086`, `2.5m/cm`, `2.5 米/厘米`, `4.56/0.12`, or `3平方米/平方分米`.
- Expected-answer/rubric/solution-step presence passed for current graph-generated rows: 0 empty expected answers, 0 empty rubrics, 0 empty solution-step arrays.
- Live lineage audit from the provided script reported 0 stale active attempts/review records.

Findings:

1. [P0] The 20-per-node slot target is inflated by prompt wrappers around repeated core stems.

Evidence:
- Read-only anchor scan found repeated stems inside current active rows:
  - `M-G7-RATIONAL-MIXED`: 15/20 rows contain `定义一种新运算：a※b=a+b-ab`.
  - `M-G7-RATIONAL-MUL-DIV`: 16/20 rows contain `(1-1/2)(1-1/3)`.
  - `M-G7-RATIONAL-ADD-SUB`: 15/20 rows contain `1/(1×2)+1/(2×3)`.
  - `M-G7-COMPARE`: 16/20 rows contain `0<a<1`.
  - `M-G7-ABSOLUTE`: 16/20 rows contain `|x-3|+|x+2|≤9`.
  - `M-PRE-UNIT-CONVERSION`: 11 rows reuse the same square-area unit stem, 5 reuse the same 2h30min travel stem.
- This violates the data contract's "20 active high-quality slots/node" meaning: historical duplicates or wrapper variants do not count as distinct diagnostic slots.
- It also violates the graph document's own warning against repeating the same routine until the child forms template reflexes.

Why blocking:
The bank can show 1120 rows while offering far fewer than 20 meaningful diagnostic opportunities on many nodes. A child could learn the repeated shell instead of exposing transferable understanding.

Fix boundary:
- Content/data production slice, not runtime DB mutation.
- Supersede current bank with a new version after rewriting the affected node families.
- Count `core_stem_id`, not child-facing prompt string. Require at least 12 truly distinct node-local core stems per node before wrapper variants may fill to 20.
- Cap any one core stem at 3-4 active variants per node unless real child evidence explicitly requests a narrow repair.

2. [P0] Picture-level challenge markers are being transplanted across graph nodes, so graph binding is often metadata-level rather than semantic.

Evidence:
- `learning_system/question_bank.py` routes the same advanced challenge contexts to broad node sets:
  - digit reverse challenge to `M-BRIDGE-SOLUTION-HABIT` and `M-PRE-INTEGER-OPS`;
  - coordinate square-layer challenge to `M-PRE-NUMBER-SENSE` and `M-G7-NUMBER-LINE`;
  - pigeonhole/prefix-sum proof to word-model, ratio, percent, and proportion families;
  - single advanced stems for `M-G7-ABSOLUTE`, `M-G7-OPPOSITE`, `M-G7-COMPARE`, `M-G7-RATIONAL-ADD-SUB`, `M-G7-RATIONAL-MUL-DIV`, and `M-G7-RATIONAL-MIXED`.
- Live DB anchor counts show `pigeonhole_prefix_sum` appears 72 times across seven nodes, including `M-BRIDGE-PERCENT-MODEL:8`, `M-BRIDGE-PROPORTION-MODEL:8`, `M-BRIDGE-SUM-DIFF-MULTIPLE:8`, `M-PRE-PERCENT:8`, and `M-PRE-RATIO-PROP:8`.
- The graph says those nodes are about percentage/proportion/sum-difference-multiple/question-reading models, with seed types like 折扣、增长率、正确率、利润率、比例尺、按比例分配、和差、和倍、差倍, not prefix-sum divisibility proof.

Why blocking:
The PRD allows picture-sample-like stretch, but controlled extension cannot substitute for node-local mainline evidence. A prompt can have a valid `node_id` and still fail the graph-bound semantic contract.

Fix boundary:
- Keep picture-level difficulty, but re-anchor it to each node's own `teaching_contract` / `question_generation.seed_question_types`.
- For prerequisite or bridge nodes, challenge should test the node's own model at Grade 7 respect level, not import olympiad/proof stems as a quota filler.
- Add a semantic alignment oracle: each active item must state the node-local capability it measures and why its core stem belongs to that node.

3. [P1] Existing audit/test gates can false-pass this content defect.

Evidence:
- `scripts/audit_question_bank_grade_level.py` normalizes a fixed list of generic wrappers, then hashes the remaining prompt/answer. It did not catch repeated mathematical cores because many wrappers and "变式/反向/条件/表达" shells remain in the hashed text.
- The script-generated report initially returned `PASS_WITH_SCOPE`, 1120 audited items, 56 nodes, 0 P0/P1/P2 issues, and 20 unique core signatures for every weakest node.
- `tests/test_learning_system.py` asserts only prompt uniqueness, kind/type variety, review metadata, and the script's weak core-signature counts. It does not test same-stem anchor reuse or semantic off-node challenge transplants.

Why blocking:
The current gate proves "rows exist and prompts differ", not "20 usable graph-bound diagnostic questions exist." The next implementation slice should not rely on this audit as a release-quality data gate.

Fix boundary:
- Extend the audit contract before accepting the next bank:
  - canonical `core_stem_id` / `problem_family_id`;
  - max-repeat threshold per node and cross-node;
  - off-node challenge detector against graph seed types / teaching contracts;
  - stored `node_alignment_reason` reviewed by the question reviewer gate.
- Keep the existing hard checks, but downgrade their meaning to ledger/regression checks, not content PASS.

Not covered:
- No external model calls; live answer-analysis semantic quality was not tested.
- No human/parent/child taste review of final wording or cognitive load.
- No implementation edit or DB mutation.
- Not a full expert proofread of all 1120 prompts; findings are anchored to deterministic DB/code evidence and targeted samples.

Residual risk:
- Some repeated stems may be acceptable as 1-3 variants for consolidation, but not as the main evidence for "20 usable questions per node."
- Some picture-level tasks are mathematically valuable; the problem is their current role as broad coverage filler across unrelated nodes.

Required next action:
Block a content-quality PASS for the current active question bank. Route the next implementation slice to rewrite the affected question production data/families and strengthen the audit gate. Do not count current `2026-07-07.bank.v9` as satisfying "20 usable questions per graph node" until repeated-core and semantic graph-alignment gates pass.
