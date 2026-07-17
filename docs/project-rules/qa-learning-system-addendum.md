# Learning System QA Addendum

Primary role: 观止 (`guanzhi`).

This project-local addendum is mandatory when QA targets the child learning flow, question bank, answer analysis, graph/evaluation/planning agents, OCR, model routing, self-evolution, or daily learning reports.

## Core Stance

观止 must act as a QA gate for product behavior, pedagogy, model judgment, and evidence lineage. Flow completion is not enough.

For this project, QA must separate:

- chain integrity: UI/API/DB/background jobs reach the expected state
- semantic integrity: model judgment, answer analysis, tags, scores, process gaps, cause analysis, and node status match the learner evidence
- teaching integrity: questions and next plans are graph-bound, age-appropriate, diagnostic, and not mechanical
- provider integrity: mocked-model tests prove contract stability; live-model claims require live provider evidence

## Mandatory Risk Checks

- Fake-pass audit: command exit code, report verdict, issue count, coverage matrix, screenshot/artifact, and DB/API facts must agree.
- Semantic answer audit: inspect `answer_analysis.comparison`, `process_gap`, error tags, `blocking_evidence`, OCR evidence, cause analysis, and learner node status.
- Question quality audit: reject low-age mechanical drills, answer-only prompts, fake process wrappers, backend/meta wording, graph-unbound tasks, and quantity-first task generation.
- Plan quality audit: verify next tasks are evidence-linked and pedagogically coherent, not merely a changed plan key or task type.
- Scope honesty: deterministic mocks, live GPT/DeepSeek, Doubao OCR, production DB, and human visual review are different evidence levels.
- Multi-round convergence: repeated lessons should sharpen the system's picture of weak points, not rotate arbitrary tasks.

## Required Child-Learning Scenario Classes

Any claim that a multi-lesson child flow is fully tested must cover:

- correct answer with sound reasoning
- answer-only submission
- stuck / cannot start
- blank or no usable evidence
- correct final answer with wrong reasoning
- partially correct relation with wrong final answer or symbol/unit issue
- readable photo answer
- unclear photo answer
- weak evidence driving remediation, prerequisite probe, rollback, or retest
- correct-only round that advances or retests without fabricating weakness

## Verdict Rules

- Use `QA_PASS_WITH_SCOPE` when model calls are mocked and the claim involves real model intelligence.
- Use `QA_NEEDS_FIX` when a harness can falsely pass or when report verdict, issue count, and exit code disagree.
- Use `QA_NEEDS_FIX` when a correct final answer with wrong/missing reasoning is accepted as full understanding.
- Use `QA_NEEDS_FIX` when child flow requires parent/Codex intervention to complete a normal learning round.
- Use `QA_NEEDS_FIX` when next-plan evidence cannot be traced back to attempts, node status, planning signal, evolved questions, or rollback candidates.
