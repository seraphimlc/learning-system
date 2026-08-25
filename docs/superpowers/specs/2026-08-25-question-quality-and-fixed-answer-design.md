# Question Quality and Fixed-Answer Assessment Design

Status: draft for user review
Date: 2026-08-25

## 1. Purpose

The current semester bank contains questions that are formally valid but have
little diagnostic value, such as `-8 + 3`, `2^4`, and `-7 ○ -3`. The problem is
not only wording. The current production matrix treats short routine
calculation as a valid question and the current quality gate does not require a
question to expose a meaningful solution entry point.

This design changes the active question contract so that difficulty is based
primarily on discovery depth, with execution effort as a secondary modifier.
It also routes fixed-answer questions through deterministic grading and adds a
first-class fill-in-the-blank child card.

## 2. Product Boundaries

- This is a private Grade 7 bridge system, not an olympiad product.
- Olympiad-style structure is used as a reference for non-obvious insight, not
  as the default difficulty or topic set.
- Teaching examples may remain simple. Simple examples do not become active
  diagnostic or practice questions merely because they are graph-bound.
- Active questions must produce interpretable evidence about a graph node.
- A correct fixed answer is processed immediately, but does not by itself prove
  complete mastery when the node requires process or explanation evidence.

## 3. Difficulty Model

### 3.1 Two dimensions

Every active question records:

- `discovery_depth`: how much of the solution entry point is left for the
  child to discover.
- `execution_steps`: the number of meaningful steps after the entry point is
  found.
- `key_insight`: the concrete relation, representation change, or strategy
  choice the child must discover.

Arithmetic micro-operations do not become separate steps. For example,
`32 + 17 = 49` is one execution step. Reading an instruction is not a
decision. A decision exists only when the child must choose between plausible
rules, representations, models, or orders of attack.

### 3.2 Discovery levels

- `E0 mechanical`: the method is explicit and one direct operation produces the
  answer. Examples: `2^4`, `-8 + 3`, or `4x + 6x` followed by `4 + 6`.
  These belong in teaching material only and are not schedulable.
- `E1 familiar_model`: the child identifies and applies a learned model, with
  no new insight. The item may be used as a limited foundation check when the
  graph node needs that evidence, but it must not be used to pad a bank.
- `E2 single_insight`: the child must discover one non-obvious relation,
  representation change, or error distinction, then execute it. This is the
  normal active-question level.
- `E3 composed_insight`: the child must discover two dependent relationships,
  or choose a valid route among multiple plausible routes. This is a limited
  transfer level.
- `E4 exploratory`: the item needs construction, classification, counterexample,
  invariant, or another open-ended strategy. This is controlled extension only,
  never the main bank filler.

### 3.3 Execution modifier

Execution steps distinguish questions within the same discovery level:

- `E1` with 1-2 meaningful steps: foundation application.
- `E1` with 3-4 meaningful steps: standard consolidation.
- `E2` with 2-4 meaningful steps: high-value variation or transfer.
- `E3` and `E4`: explicitly capped and scheduled only when the plan calls for
  transfer or controlled extension.

More arithmetic, larger numbers, extra parentheses, or longer wording do not
raise discovery depth on their own.

### 3.4 Operational assignment and graph mapping

`discovery_depth` is not accepted as an unsupported generator claim. The
versioned `discovery_derivation.v1` compiler consumes immutable prompt,
interaction-schema, graph-node, and solution-step data and produces a
reviewable derivation receipt. The generator may propose a `solution_entry`,
but cannot make it authoritative. Every candidate must provide a bounded
proposal:

```json
{
  "entry_point": "classify_structure",
  "entry_point_visibility": "implicit",
  "alternative_entries": 1,
  "required_decisions": ["separate_x_terms_from_constants"],
  "required_steps": ["group_terms", "combine_coefficients", "write_complete_expression"]
}
```

The proposal is an untrusted hint. `decision_points`, `depends_on`,
`solution_families`, and the authoritative `key_insight_evidence_keys` are
compiler outputs from the independent review packet, not candidate-controlled
fields. Each reviewed decision must reference at least one canonical solution
step and a prompt-evidence span; each family must reference its actual ordered
first step and prompt-evidence span. The compiler derives `depends_on` from
the reviewed step input graph and rejects a receipt when the candidate's
proposal disagrees. A dependency that is merely listed in a proposal, without
the corresponding step input, prompt evidence, or graph prerequisite edge,
does not count toward E3. This keeps extra declared alternatives or routes
from manufacturing difficulty.

The independent packet is `review_packet.v1`. Its canonical envelope contains
the reviewed step graph, the prompt span locations, the instance span hashes,
the structural span hashes, and the reviewer run id. The packet digest is
`sha256(UTF-8(canonical_json(packet)))`; it is included in the derivation input
and cannot be supplied by the generator. A reviewed solution step has the
only shape `{"id", "action", "evidence_key", "input_step_ids",
"input_evidence_keys", "prompt_span_ids"}`; span hashes exist only in the
referenced `prompt_spans` records. Step input ids must exist and be acyclic. A
prompt span hash is computed from the exact canonical span for the instance
hash. The structural span hash first replaces
numeric literals, variable names, choice/field labels, and cosmetic story
entities with typed placeholders, then applies the common operator and
whitespace normalization. Structural hashes therefore preserve the tested
mathematical relation and evidence structure without importing instance
numbers or story names.

The complete packet envelope is:

```json
{
  "schema_version": "review_packet.v1",
  "reviewer_run_id": "<independent run id>",
  "prompt_spans": [
    {
      "id": "p1",
      "start_token": 4,
      "end_token": 9,
      "instance_hash": "<sha256>",
      "structural_hash": "<sha256>"
    }
  ],
  "solution_steps": [
    {
      "id": "s1",
      "action": "classify_structure",
      "evidence_key": "concept",
      "input_step_ids": [],
      "input_evidence_keys": ["concept"],
      "prompt_span_ids": ["p1"]
    }
  ],
  "cross_node_prerequisite_relations": []
}
```

`start_token` is inclusive and `end_token` exclusive in the canonical prompt
token stream; tokenization and the Unicode/operator normalization are the
versioned rules used by the prompt digest. The packet validator checks that
span ids, step ids, and relation ids are unique, all references exist, the
instance/structural hashes equal the canonical span projections, and the step
graph is acyclic. A cross-node relation has the shape
`{"id", "prerequisite_node_id", "evidence_key", "target_step_id"}` and must
be present in the graph contract. Its evidence key must occur in the target
step's `input_evidence_keys`; otherwise it cannot trigger E3. The packet is
bounded to 8 steps, 8 spans, and 4 graph relations. The derivation input copies
these canonical step input/evidence fields and relation ids, and rejects any
packet or candidate proposal whose digest or copied fields do not match.

The canonical `discovery_derivation.v1` input is:

```json
{
  "schema_version": "discovery_derivation.v1",
  "graph_lineage": "<exact graph lineage>",
  "node_id": "<node id>",
  "node_contract_sha256": "<sha256 of the canonical graph-node contract>",
  "graph_mode": "core",
  "prompt_sha256": "<sha256 of canonical prompt>",
  "interaction_schema_sha256": "<sha256 or empty>",
  "review_packet_version": "review_packet.v1",
  "review_packet_sha256": "<sha256 of the canonical review packet>",
  "cross_node_prerequisite_relations": [],
  "solution_steps": [
    {
      "id": "s1",
      "action": "classify_structure",
      "evidence_key": "concept",
      "input_step_ids": [],
      "input_evidence_keys": ["concept"],
      "prompt_span_ids": ["p1"]
    }
  ],
  "proposal": {"entry_point": "classify_structure", "required_decisions": []}
}
```

The canonical output is:

```json
{
  "schema_version": "discovery_derivation.v1",
  "discovery_depth": "E2",
  "entry_point_visibility": "implicit",
  "decision_points": [
    {"id": "d1", "taxonomy": "classify_structure", "alternatives": ["combine", "do_not_combine"], "misconception_key": "concept", "step_ids": ["s1"], "structural_prompt_span_hashes": ["<structural span hash>"], "depends_on": []}
  ],
  "solution_families": [
    {"id": "f1", "first_action": "classify_structure", "step_ids": ["s1"], "structural_prompt_span_hashes": ["<structural span hash>"]}
  ],
  "execution_steps": 3,
  "key_insight_evidence_keys": ["concept"]
}
```

Both schemas reject unknown keys, duplicate ids, empty action names, missing
or mismatched review-packet hashes, more than
8 solution steps, more than 4 decision points, more than 3 solution families,
cycles or unknown ids in `depends_on`, missing step/span references, or values
outside the versioned enums.
Canonical JSON uses UTF-8,
lexicographically sorted object keys, no insignificant whitespace, and a
SHA-256 digest over the canonical bytes. The independent
`question_reviewer_agent` validates the proposal against the
compiler output and the node's `diagnosis_contract` (the graph field name is
`diagnosis_contract`, not `diagnostic_contract`). The following
`decision_taxonomy.v1` is the only vocabulary accepted for non-trivial
decisions: `classify_structure`, `choose_representation`, `select_model`,
`select_operation_order`, `resolve_sign_scope`, `choose_case_split`,
`identify_invariant`, and `construct_counterexample`.

`graph_lineage` is the exact graph version identifier, and
`node_contract_sha256` is the SHA-256 of the canonical JSON for the node's
identity, prerequisites, `diagnosis_contract`, and `question_generation`
contract. The prompt digest is computed from a canonical prompt envelope
containing the stem, ordered choice options, and ordered fill-in field
definitions. Text in that envelope is Unicode NFKC-normalized, CRLF is
converted to LF, Unicode math operators are mapped to the versioned ASCII
operator tokens, and surrounding whitespace is trimmed without reordering
tokens. The interaction-schema digest uses the same rules and canonical JSON;
an empty schema is represented by the empty string. These rules prevent a
contract change from reusing an old derivation receipt.

The compiler derives `entry_point_visibility` from prompt cues and solution
steps. `explicit` means the prompt names the rule/model or gives the first
transformation; `cued` names the objects but not the operation; `implicit`
requires a decision-taxonomy action absent from the prompt; `exploratory`
allows more than one viable first action or an open search. “Non-trivial
decision” means one of the accepted taxonomy actions with at least two
plausible alternatives, one of which is a known node-level misconception.
“Genuine route choice” means two accepted solution families with different
first actions, both represented in the review receipt. Arithmetic operand
choice never counts.

The derivation precedence is deterministic: E4 if `entry_point_visibility` is
`exploratory`; otherwise E3 if there are at least two dependent decision
points, at least two solution families with different first actions, or a
solution action explicitly dependent on a required cross-node prerequisite
relation; otherwise E2 if there is a non-trivial taxonomy decision or a
representation/error distinction that is not fully resolved by the prompt;
otherwise E1 if the entry point is `explicit` or `cued` and there is no
non-trivial decision; otherwise E0. A candidate whose proposed level differs
from this derived level is rejected, not downgraded silently. A prompt may
explicitly name a model and still derive E2 when the child must choose an
operation order, resolve a sign scope, or distinguish a known misconception.

`cross_node_prerequisite_relations` contains only graph-declared prerequisite
edges and is bounded to four entries. A relation is eligible to trigger E3
only when a solution step names its prerequisite evidence key as an input;
listing a prerequisite without using it does not raise the level.

Meaningful execution steps are counted after derivation and are bounded by
level: E1/E2 allow 1-6, E3 allows 2-6, and E4 allows 2-8. The existing maximum
of 8 solution-step records is a parser bound, not a difficulty score. A
candidate exceeding its level bound is rejected as over-scoped; it is not
silently reclassified by step count.

The reviewer derives the level from the compiler receipt and graph node
contract:

- `E0`: `entry_point_visibility=explicit`, no decision, one direct operation.
- `E1`: one known entry point, `entry_point_visibility` is `explicit` or
  `cued`, and no non-trivial decision.
- `E2`: one non-trivial decision, or one representation change/error
  distinction that is not stated in the prompt, even when the prompt gives a
  partial or explicit model cue.
- `E3`: two dependent decision points, a genuine route choice, or a required
  cross-node prerequisite relation.
- `E4`: exploratory construction/classification/counterexample/invariant, with
  more than one viable route or an open search component.

The reviewer rejects candidates whose declared level disagrees with the
derived level. `key_insight` must name the same entry point and must resolve to
one of the node's `diagnosis_contract`, `question_generation`, or prerequisite
evidence requirements.

Graph mode limits are explicit:

- `core`: E1-E2 only. E3 is never scheduled from a core-mode item.
- `selective_core`: E1-E3 when the node contract names the prerequisite or
  representation change.
- `controlled_extension`: E2-E4; E4 remains non-mainline.
- `diagnose_only`: E1-E2 and never a mastery-confirming item.

The active scheduler may select E1 only when the node's current evidence packet
explicitly requests a foundation check. Otherwise the active minimum is E2.

Scheduling is executable by mode and purpose:

- `core` accepts E1-E2 for `learn`, `diagnostic`, `mastery_check`, and `retest`;
  E1 requires an explicit `foundation_check` signal in the plan packet.
- `selective_core` accepts E1-E3 only when
  `candidate.evidence_pattern_keys ∩ node_contract.selective_core_evidence_keys`
  is non-empty; that node-contract set contains only prerequisite or
  representation-change keys explicitly approved for the node. E3 additionally
  requires `plan_action=transfer` or
  `plan_action=prerequisite_coordination` and the intersecting key in the plan
  packet.
- `controlled_extension` accepts E2-E4; E4 requires
  `plan_action=controlled_extension` and is never selected to fill a daily
  minimum.
- `diagnose_only` accepts E1-E2 but its assessment receipt is never
  `mastery_update_eligible`.

When no candidate satisfies these predicates, the planner returns an explicit
`no_eligible_candidate` decision and materializes a blocked/summary or a
graph-bound recovery step according to the node contract. It may not lower the
discovery level, exceed the extension quota, or fall back to an E0 item. These
predicates and no-candidate outcomes are part of the activation test contract.

## 4. Quality Gates

An active question must:

1. Bind to a graph node and identify a concrete `key_insight`.
2. Have `discovery_depth` in `E1`-`E4`; `E0` is rejected from active use.
3. Have at least one meaningful step that is not just final arithmetic.
4. Avoid asking for an intermediate arithmetic fragment that is disconnected
   from the mathematical claim being tested.
5. Declare whether its answer is fixed or requires process interpretation.
6. State the evidence it can and cannot support for mastery.

The gate also performs the following derived checks:

- `node_evidence_alignment`: the item must cover at least one evidence key
  named by the graph node, and its `key_insight` must not be generic wording
  such as "calculate carefully".
- `discovery_consistency`: the reviewer derives E0-E4 from
  `solution_entry`; a self-declared level cannot raise eligibility.
- `template_collision`: `question_fingerprint.v2` produces two separate
  digests. `exact_instance_fingerprint` retains normalized concrete numbers,
  labels, and surface values to reject duplicate instances. `family_fingerprint`
  replaces numeric literals, variable names, and cosmetic entities with typed
  placeholders while retaining node id, structural discovery derivation, decision
  taxonomy, solution actions, and evidence keys. Both forms canonicalize
  Unicode math operators, whitespace, choice labels, and field ids. Exact
  fingerprints are rejected. A family fingerprint may appear at most twice per
  node, and the second item must have a distinct evidence key and distinct
  misconception mapping. A changed number or surface story does not create a
  new family.
- `low_information`: a bare numeric/algebraic operation, a single comparison
  with no competing interpretation, or an isolated intermediate calculation
  is rejected even when wrapped in extra prose.
- `coverage_balance`: each node must retain at least one E1 foundation item
  when its contract requires one, at least two distinct E2 evidence patterns,
  and no more than the configured E3/E4 extension quota.

Both fingerprints, their canonicalization version, and the
`discovery_derivation.v1` digest are stored in the review receipt. Exact
uniqueness and family quotas are enforced by indexed staging rows in one
activation transaction, so concurrent candidates cannot both consume a
per-node family quota. Activation requires an independent reviewer receipt
whose digests match the candidate; self-declared `key_insight`, family, or
level cannot raise eligibility. Adversarial fixtures cover numeric-only
wrappers, renamed variables, changed stories, false E2 claims, and invalid
decision taxonomy values.

The fingerprint payloads are versioned canonical envelopes. Both include
`graph_lineage`, `node_id`, the ordered question type, the structural
interaction schema, decision taxonomies, solution actions, and evidence keys.
`exact_instance_fingerprint` additionally retains concrete numeric literals,
variable names, choice labels, field ids, surface entities, the full
interaction schema, and the full discovery receipt digest.
`family_fingerprint` replaces those values with typed placeholders such as
`NUMBER`, `VARIABLE`, `CHOICE_LABEL`, `FIELD_ID`, and `ENTITY`, while retaining
mathematical operators and all diagnostic structure. Its
`structural_derivation_digest` contains only the derivation output and
review-evidence structure; it excludes `prompt_sha256`,
`interaction_schema_sha256`, concrete literals, labels, and cosmetic story
entities, and instance prompt span hashes; it retains structural prompt span
hashes. Its `structural_interaction_schema` retains field count, required
versus optional status, input modes, and answer grammar, but excludes labels,
field ids, and surface text. A changed number or surface story therefore
stays in the same family, while a changed mathematical answer grammar or
decision structure creates a new family.
Object keys are sorted lexicographically; arrays whose order is semantic
(prompt tokens, choice order, field order, solution-step order) keep their
order, while set-like arrays (evidence keys, taxonomy alternatives, and
misconception keys) are sorted after normalization. Unicode NFKC, the same
math-operator map, whitespace policy, and exact rational lexical policy used
by `discovery_derivation.v1` apply before serialization. Each digest is
`sha256(UTF-8(canonical_json(payload)))`, and the payload plus
canonicalization version is stored in the receipt. Implementations may not
hash a free-form JSON blob or use a different array-order policy.

Examples:

- `-7 ○ -3` is rejected as E0/E1 low-information comparison.
- `-3/4`, `-0.7`, `-2/3`, and `0` ordered from least to greatest can qualify as
  E2 when the child must choose a common representation and handle negative
  order.
- `4x + 6x` followed only by `4 + 6` is rejected because it does not test
  complete like-term recognition or expression preservation.
- `4x + 6 - 2x + 3` with a structured result can qualify as E1/E2 depending on
  whether the grouping and sign decisions are explicit or must be discovered.
- `(-2)^4` versus `-2^4` can qualify as E2 because the entry point is parsing
  the scope of the exponent and sign, not merely calculating a power.

The bank no longer has a fixed requirement of 15 items per node. A node may
have fewer active questions when rejected items cannot be replaced with equal
quality. Coverage is more important than quota completion.

## 5. Fixed-Answer Assessment

### 5.1 Choice questions

`choice` questions declare `single_choice` or `multi_choice` in the authoritative
contract. The child submits option ids only:

- unknown option ids, duplicate ids, or missing required selection are
  `invalid_input` and do not update mastery;
- `single_choice` accepts exactly one id;
- `multi_choice` compares the canonical set, with no order significance;
- a valid but incorrect selection is `wrong`; a valid correct selection is
  `correct`.

Choice questions are graded locally by exact option identity and never enqueue a
model review job. The server ignores any client-supplied score, result,
expected answer, or rubric fields.

The wire payload is versioned and closed:

```json
{
  "schema_version": "2026-08-25.fixed-answer-response.v1",
  "type": "single_choice",
  "choice_id": "B"
}
```

The parser rejects non-object payloads, nulls, wrong field types, unknown
fields, and a `choice_id` on `multi_choice` (which must instead use a unique
`choice_ids` array). Schema choice ids must be unique and the declared choice
mode is immutable after contract activation.

The multi-choice payload is:

```json
{
  "schema_version": "2026-08-25.fixed-answer-response.v1",
  "type": "multi_choice",
  "choice_ids": ["A", "C"]
}
```

The fill-in response payload is:

```json
{
  "schema_version": "2026-08-25.fixed-answer-response.v1",
  "type": "fill_blank",
  "fields": [
    {"id": "x_coefficient", "value": "10"},
    {"id": "constant", "value": "-1"}
  ]
}
```

All modes reject duplicate JSON object keys using a duplicate-detecting
parser, mode-incompatible fields, duplicate choice ids, duplicate field ids,
more than 8 choices/fields, values longer than 128 Unicode characters, and
payloads larger than 16 KiB. A field value must be a string or an explicitly
contracted scalar; null is never a valid answer value.

### 5.2 Fill-in-the-blank questions

Fill-in questions use a child-safe `interaction_schema` with stable field ids:

```json
{
  "type": "fill_blank",
  "fields": [
    {"id": "x_coefficient", "label": "x 的系数", "input_mode": "numeric", "required": true},
    {"id": "constant", "label": "常数项", "input_mode": "numeric", "required": true}
  ]
}
```

The authoritative answer contract, not the child payload, defines each field's
answer rule:

- `numeric`: exact rational/decimal parsing after Unicode sign and whitespace
  normalization;
- `fraction`: exact rational equivalence, with decimal equivalence allowed only
  when the field contract says so;
- `algebraic`: restricted expression grammar, declared variables only, no
  functions/relations/assignments, exact symbolic equivalence, and malformed or
  domain-invalid input rejected;
- `text`: exact or explicitly declared normalized matching, including units
  when units are part of the answer.

The accepted algebraic grammar is versioned: integer literals, decimal
literals with at least one digit after the decimal point, rational literals of
the form `integer/integer`, declared variables, binary `+ - * /`, one leading
unary `+` or `-` per primary, parentheses, and `^` followed by a non-negative
integer exponent. Standard precedence is parentheses, power, unary sign,
multiplication/division, addition/subtraction; implicit multiplication is
rejected. Functions, comparisons, assignments, undeclared variables, division
by zero, exponent overflow, and parser extensions are rejected. Numeric
normalization uses exact rational parsing; fraction equivalence is exact;
decimal equivalence is only enabled per field. Text normalization uses Unicode
NFKC, trims/collapses whitespace, and applies only the explicitly declared
case/unit policy.

Unknown field ids are rejected. Missing required fields are `incomplete`, not
wrong. Each field receives a deterministic result and the aggregate result is
derived from the contract's required/optional field policy: malformed or
unknown data wins as `invalid_input`; otherwise missing required fields win as
`incomplete`; otherwise any required mismatch is `wrong`; optional fields are
ignored when omitted and may only lower the result when the contract explicitly
sets `optional_field_policy=penalize_if_supplied_wrong`. Client-provided scores,
expected answers, and rubrics are ignored. Malformed input never updates
mastery.

The child page renders all fields as one coherent question card. The card must
support prefix/suffix text, math rendering, empty/invalid/submitted states, and
stable layout for one or multiple blanks.

### 5.3 Short answers

Only `short_text` or equivalent process-answer questions invoke
`answer_analysis_agent`. The model judges the child's reasoning, process gap,
and explanation. It does not grade choice or fill-in responses.

Fixed-answer correctness and mastery eligibility remain separate: a correct
choice/fill answer can be strong local evidence, but the planner must respect
the node's required evidence profile before declaring mastery.

### 5.4 Evidence profile and mastery ceiling

Every question contract declares:

```json
{
  "evidence_profile": {
    "supports": ["concept_recognition", "answer_correctness"],
    "requires_for_mastery": ["process_explanation"],
    "mastery_update_mode": "observation_only",
    "mastery_state_ceiling": "B"
  }
}
```

The graph node's contract is authoritative for `requires_for_mastery`. The
activation compiler derives the effective profile by intersecting the
question's declared `supports` with the graph node's normalized evidence-key
catalog. The profile digest is stored on the active answer contract; child
payloads and generators cannot set `mastery_update_mode` or
`mastery_state_ceiling`.

The normalized graph evidence contract is `graph_evidence_contract.v1` and is
materialized before a node can activate in the new bank. Its required fields
are `evidence_keys`, `requires_for_mastery`,
`selective_core_evidence_keys`, `fixed_answer_mastery_policy`, and
`fixed_answer_state_ceiling`; all values
must come from the versioned catalog. For the current graph's Chinese
`evidence_required` values, the explicit migration mapping is:
`结果正确 -> answer_correctness`, `过程可复盘 -> process_explanation`,
`能口头解释 -> verbal_explanation`, and `能做一道小变式 -> transfer`.
The mapping is configuration under review, not an inferred string match; a
node with an unmapped value is blocked from activation. The migration also
records which keys are required for `A_mastered`; it does not infer that list
from a question's declared evidence.

The graph-derived ceiling is deterministic: if
`process_explanation`, `verbal_explanation`, or `transfer` is in
`requires_for_mastery`, fixed-answer evidence has a ceiling of `B`; otherwise
the node's explicit `fixed_answer_state_ceiling` applies. The default policy
is `observation_only` with ceiling `B`. Only a graph contract explicitly
setting `fixed_answer_mastery_policy=confirmation_eligible` may allow a
multi-field fill-in to request the normal mastery transition, and its ceiling
may not exceed the graph ceiling. A single choice or single-answer fill-in is
always `observation_only`, even when its answer is correct. Thus a node that
requires process evidence can only reach `A` after short-answer process
evidence passes the existing analysis gates; no fixed-answer payload can
override this ceiling.

A choice or single-answer fill-in normally supports correctness and the
specific declared concept only; it cannot supply process explanation. Such
evidence uses reducer mode `observation_only`: it is stored and available to
planning, but cannot by itself change mastery state. A node policy may permit a
multi-field fill-in to use `confirmation_eligible` only when every required
field maps to a different normalized evidence key and all required fields are
correct. Even then, when the graph requires process evidence, the reducer
clamps the state at `B`; fixed-answer evidence cannot produce `A`.
Short-answer analysis may provide process evidence, subject to the existing
answer-analysis and evidence gates.

Mastery ordering is `D < C < B < A`. `observation_only` writes evidence and
does not change `learner_node_status`; `confirmation_eligible` asks the
mastery reducer for its normal transition and then clamps the proposed state
to the effective ceiling. Profile conflicts, unknown evidence keys, or a
question-declared ceiling above the graph-derived ceiling fail activation.
For a multi-field fill-in, confirmation eligibility is derived only when at
least two required fields map to distinct graph evidence keys and all required
fields are correct. Every reducer effect uses the unique key
`fixed_assessment:{attempt_id}:{attempt_version}:{contract_digest}`; a retry
reuses the committed effect or records a digest conflict without applying a
second transition.

The reducer persists both the deterministic result and the effective profile;
it applies the mode and ceiling in the same transaction. Downstream planning
must not infer mastery eligibility from `result=correct` alone. Tests cover a
correct fixed answer, a multi-field answer, conflicting profile claims, exact
state clamping, duplicate reducer effects, and the impossible-A-without-process
case.

## 6. Bank Migration

The existing `2026-08-20.v1` bank is retained for historical attempts but is
not edited in place. A new version is generated from the revised matrix and
quality gates. The new version is staged, audited, and activated only after:

- every retained item has a valid discovery level, step count, and key insight;
- all choice/fill-in contracts pass deterministic grading tests;
- all short-answer contracts pass the model-analysis contract tests;
- node coverage reports contain no E0 active items or disconnected intermediate
  prompts;
- browser tests cover choice, fill-in, short-answer, and child-safe projection;
- the active ledger and the runtime database point to the same bank version.

Cutover is version-pinned:

- open flows and queued jobs continue using the bank version recorded on their
  flow/step; they are never silently rebound to the new bank;
- new flows use the new version only after the ledger cutover transaction;
- fixed-answer retries are idempotent on `(flow_step_id, attempt_version,
  client_idempotency_key)` and reuse the canonical assessment;
- model-backed short-answer jobs retain their pinned contract and may finish,
  retry, or enter an auditable pending state across a restart;
- stale submissions, unknown question versions, and cross-version scheduling
  are rejected without writes;
- rollback restores the previous active ledger and leaves new-version
  attempts auditable but unschedulable; it does not rewrite historical rows;
- the cutover transaction rechecks active jobs, open flows, ledger uniqueness,
  and manifest digests immediately before activation.

New fields are additive and backfilled only for staged new-version rows. Old
question contracts remain readable for historical evidence and are not
retrofit with guessed discovery or evidence metadata.

### 6.1 Cutover state machine

The ledger uses `staged -> active -> superseded` or
`active -> rolled_back`. A rollback from active version `v_new` requires its
recorded predecessor `v_old` to be `superseded`; one IMMEDIATE transaction
changes `v_new` to `rolled_back` and `v_old` back to `active`, preserving both
audit timestamps. A cutover takes an IMMEDIATE SQLite transaction and must
recheck the active-row uniqueness, manifest digest, open-flow pins, queued-job
pins, and bank item counts before changing status.

Every flow step and background job stores its immutable `question_bank_version`,
`contract_digest`, and source flow/step id. Jobs use the existing lease states
`queued`, `claimed`, `retryable`, `waiting`, `succeeded`, `blocked`, and
`dead_letter`; a lease expiry returns a claimed job to `retryable` exactly once.
Each claim carries `(lease_owner, lease_generation, lease_expires_at)` and all
completion/retry writes require the owner and generation in the guarded
`WHERE` clause; an old worker cannot fence a newer claim. The worker validates
the pin and digest before every write. A retry with the
same idempotency key and input digest reuses the canonical result; the same key
with a different digest becomes `blocked` with a conflict record.

On rollback, existing old-version flows continue normally. New-version flows
may finish already-pinned steps, but cannot create new steps after their next
transition; they materialize an auditable blocked/summary state if the rollback
removes their active bank. Accepted assessments are historical and are never
rewritten. Restart recovery reclaims expired jobs and preserves fixed-answer
results and model checkpoints without duplicate reducer effects.

## 7. Acceptance Criteria

- The three cited low-information question patterns are rejected by the active
  bank gate.
- The bank generator can produce meaningful E1/E2 items without padding each
  node to a fixed count.
- Choice and fill-in answers complete without model calls.
- Short-answer submissions still use the model path and preserve answer
  analysis evidence.
- Fill-in cards render and submit field-level answers in the child UI.
- A correct fixed answer cannot silently be promoted to complete mastery when
  the graph node requires process evidence.
- The new bank can be activated without mutating historical question lineage.
- Cutover, restart, duplicate submission, stale-version, malformed fixed-answer,
  and rollback tests pass in isolated databases.
- Every active item has a reviewer-derived discovery level and a node-aligned
  evidence profile; generator self-declarations alone cannot activate an item.
