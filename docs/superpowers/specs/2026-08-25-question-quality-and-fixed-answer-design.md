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

## 4. Quality Gates

An active question must:

1. Bind to a graph node and identify a concrete `key_insight`.
2. Have `discovery_depth` in `E1`-`E4`; `E0` is rejected from active use.
3. Have at least one meaningful step that is not just final arithmetic.
4. Avoid asking for an intermediate arithmetic fragment that is disconnected
   from the mathematical claim being tested.
5. Declare whether its answer is fixed or requires process interpretation.
6. State the evidence it can and cannot support for mastery.

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

`choice` questions are graded locally by exact option identity. They do not
enqueue a model review job. The system records deterministic evidence,
question/contract lineage, and the limits of the evidence.

### 5.2 Fill-in-the-blank questions

Fill-in questions use a child-safe `interaction_schema` with stable field ids:

```json
{
  "type": "fill_blank",
  "fields": [
    {"id": "x_coefficient", "label": "x 的系数", "input_mode": "math"},
    {"id": "constant", "label": "常数项", "input_mode": "math"}
  ]
}
```

The child submits field values keyed by field id. The server validates each
field using its declared normalization and answer type. Numeric, fraction, and
algebraic values use deterministic normalization/equivalence checks; text
blanks use exact or explicitly declared normalized matching. The expected
answers and internal rubric never enter the child projection.

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

