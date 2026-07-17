# QA_HARNESS_DONE - v5 10-Lesson Browser Harness P1 Hardening

Role: 观止 (`agentKey=guanzhi`)

Date: 2026-07-11

## Verdict

`QA_PASS_WITH_SCOPE`

- Workflow: `PASS`
- Semantic quality: `PASS_WITH_MIXED_TRUST_SCOPE`
- Teaching quality: `PASS_WITH_MIXED_TRUST_SCOPE`
- Live GPT/Doubao semantic quality: not executed
- Production implementation changes: none

The old `scripts/live_child_ui_10x.py` remains `legacy_fixed_group_only` and is not eligible for a v5 PASS.

## Entry Lock

- Request type: test/harness correction and read-only QA execution
- Role authority: owned by 观止; writes limited to tests, fixtures, harness, and QA evidence
- Playbooks: `qa.md`, `qa-case-library.md`, mandatory `qa-learning-system-addendum.md`
- Project boundary overlay: `AGENTS.md`, `MSG-20260711-002`, `MSG-20260711-003`, v5 product/UX/engineering/test contracts
- Forbidden scope: production runtime edits, real DB mutation, unrequested external model calls, fake live labels
- Evidence target: ten independent recorded browser lessons plus focused contract tests and browser smoke

## Changed Files

- `scripts/live_child_v5_10_lessons.py`
  - strict graph rollback audit
  - four-source trust audit
  - truthful photo fixture generation and trace
  - L09-only live fault-injection seam
  - bounded post-worker browser refresh/recovery
- `tests/fixtures/v5_10_lesson_harness_contract.json`
  - rollback depth/safe-stop contracts
  - mixed-trust verdicts
  - photo fixture contract
  - live fault workflow-versus-semantic evidence contract
- `tests/test_learning_system.py`
  - rollback, trust, photo, live fault, and bounded refresh regressions
- `docs/qa/v5_10_lesson_browser_harness_qa.md`
  - this evidence update

`tests/browser_smoke_learning_system.mjs` was verified in this run; no new P1 edit was needed.

## P1-1 Rollback Audit

The old oracle passed when any prerequisite target appeared anywhere in `chain[1:]`. The new audit checks every `prerequisite_probe` in order:

- exactly one source attempt
- source attempt exists and is `wrong` with blocking evidence
- source node and target node differ
- target is a graph-legal direct prerequisite from `math_knowledge_graph_v2.json`
- transition matches the next edge of the ordered contract prefix
- duplicate, chain-external, same-node, out-of-order, and non-direct transitions fail
- required depth is met
- a short prefix passes only when `safe_stop_allowed=true` and the child reaches terminal summary

Recorded proof:

| Contract | Required | Proven | Safe-stop | Result |
|---|---:|---:|---|---|
| rollback 1 | 4 | 4 | no | PASS |
| rollback 2 | 4 | 4 | yes, at summary | PASS |
| rollback 3 | 4 | 4 | yes, at summary | PASS |
| rollback 4 | 3 | 3 | no | PASS |

## P1-2 Trust Audit

Trust evidence now scans:

- `background_jobs`
- v5 model-stage `agent_runs`
- `next_step_decisions`
- `daily_summaries`, including source decision IDs

Accepted v5 model stages require a live/recorded provider or an explicit deterministic/inferred/pending classification. Historical non-v5 session-close runs are still reported as `non_v5_runtime`, but are not treated as v5 semantic-stage evidence.

L03 and L05 contain recorded model stages plus deterministic runtime decisions. Their summaries are derived as `mixed_recorded_deterministic` even though `phase_lineage.provider_modes` lists only durable model jobs. The aggregate semantic and teaching verdicts are therefore `PASS_WITH_MIXED_TRUST_SCOPE`, not pure recorded PASS.

Final trust audit issues: 0.

## Photo Oracle

Generated photos now carry content and image lineage hashes plus file hash/size:

- `readable_photo`: clear real expected answer, at least one solution step, and a check
- `text_photo_conflict`: typed text keeps the expected answer while the clear photo says `PHOTO ANSWER: 999`
- `unclear_photo`: a meaningful expected-answer source image is rendered first, then blurred
- `ocr_hallucination`: the same meaningful source construction is blurred; it is not an empty or generic image

L08 uses a photo-specific counter, so clarify submissions no longer prevent the OCR hallucination case from appearing. Final classes observed:

- L06: `readable_photo`
- L07: `unclear_photo`
- L08: `text_photo_conflict`, `ocr_hallucination`

Photo audit failures: 0.

## Live Fault Seam

The old `state.route_fault` affected only `RecordedOracle.answer_route`, so it did not inject any fault under `--live-model`.

The new contract and seam are limited to L09 live mode:

1. After the first attempt and answer job are durably saved, inject `not_configured`; expected job outcome is `blocked`.
2. After the second attempt and answer job are durably saved, inject one controlled retryable `HTTP 503`; expected job outcome is `retry`.
3. Persist `fault_injected` metadata in the temporary job payload.
4. Mark injected events `workflow_evidence_only` and `semantic_evidence_eligible=false`.
5. Require a later accepted real-provider `answer_analysis` run for each faulted attempt before recovery is eligible as live semantic evidence.
6. Keep all other live lessons on unpatched external model calls.

The seam and negative recorded-provider recovery case pass focused tests. No live external model call was made in this QA run, so the seam has no release-level live semantic verdict yet.

## Browser Harness Result

Artifact root: `artifacts/v5-10-lesson-harness/recorded-full-10-p1-photo-fault-fixed`

- 10 independent lessons and local dates
- 111 counted child interactions, all within 10-20 per lesson
- 218 browser checkpoints/screenshots
- 93 attempts
- 266 durable jobs
- 292 agent runs
- 95 evidence validations
- 86 mastery decisions
- 98 next-step decisions
- 10 terminal summaries
- rollback failures: 0
- photo audit failures: 0
- trust audit issues: 0
- recorded-run fault-injection workflow events: 0
- recorded-run live semantic agent runs: 0

Lesson verdicts:

| Lesson | Interactions | Trust scope | Workflow |
|---|---:|---|---|
| L01 all correct | 10 | recorded | PASS |
| L02 all wrong rollback | 10 | recorded | PASS |
| L03 all partial | 10 | mixed recorded/deterministic | PASS |
| L04 mixed reasoning rollback | 13 | recorded | PASS |
| L05 answer only/repeated stuck | 16 | mixed recorded/deterministic | PASS |
| L06 readable photo | 10 | recorded | PASS |
| L07 unclear photo | 11 | recorded | PASS |
| L08 conflict/OCR hallucination | 11 | recorded | PASS |
| L09 model recovery | 10 | recorded | PASS |
| L10 restart/double submit | 10 | recorded | PASS |

## Red-to-Green Evidence

Initial focused red tests:

- rollback helper missing: `AttributeError: no audit_prerequisite_rollback`
- trust helper missing: `AttributeError: no audit_trust_labels`
- semantic photo helper missing: `_write_photo() got an unexpected keyword argument 'answer_class'`
- live fault contract helper missing: `AttributeError: no live_fault_injection_spec_for_lesson`

The focused harness tests now pass, including adversarial shallow/same-node/out-of-order/illegal rollback, missing-provider trust, truthful photos, L09-only live fault injection, and bounded reload-based conclusion polling.

## Command Evidence

```text
python3 scripts/live_child_v5_10_lessons.py \
  --output-dir artifacts/v5-10-lesson-harness/recorded-full-10-p1-photo-fault-fixed
QA_HARNESS_DONE
workflow=PASS
semantic_quality=PASS_WITH_MIXED_TRUST_SCOPE
teaching_quality=PASS_WITH_MIXED_TRUST_SCOPE

node tests/browser_smoke_learning_system.mjs
PASS browser smoke: v5 current-step child flow -> save/photo/stuck -> async blocked evidence

python3 -m unittest tests.test_learning_system -k v5 -v
Ran 58 tests in 89.788s
OK
```

## Browser Regression

The browser smoke confirms:

- analyzing says the answer is saved
- blocked fallback without backend body says evidence is saved and offers retry or finish
- two immediate finish clicks send exactly one request
- finish is disabled while in flight
- terminal summary exposes no answer, retry, or next-question action

## Remaining Scope

- Recorded fixtures prove the browser/state machine, strict schema handling, expected-oracle replay, graph rollback lineage, and report integrity.
- Deterministic runtime decisions reduce the aggregate semantic/teaching verdict to mixed trust.
- No real GPT/Doubao calls were made. `--live-model` must still run all ten lessons before any live semantic or teaching PASS.
- L09 live fault injection is contract/unit tested but not externally executed; release evidence must show two workflow-only fault events followed by real-provider recovery runs.
- Human review is still required for teaching taste and whether live model feedback is age-appropriate and pedagogically strong.
