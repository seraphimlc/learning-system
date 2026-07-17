# Answer Contract v2 Batch Generation Engineering Contract

Date: 2026-07-15
Owner: 听云 (`tingyun`)
Status: design-review-ready-after-needs-fix
Depends on: `answer_contract_v2_batch_generation_technical_plan.md`

## Contract Scope

This contract defines Batch A canary and Batch B full-generation interfaces, storage, state,
preflight, exact v2 lifecycle lineage, idempotency, exclusion, budgets, recovery, receipts, and
authority handoff. It does not define or implement answer-contract activation.

## Public Module Interfaces

```python
build_v2_batch_plan(
    conn,
    project_root,
    *,
    run_kind: Literal["canary40", "full1120"],
    canary_receipt_path: Path | None = None,
) -> dict

effective_evidence_role(question: Mapping[str, Any]) -> str

preflight_v2_canary(
    conn,
    project_root,
    *,
    run_id: str,
    claim: RunClaim,
) -> dict

run_v2_canary(
    conn,
    project_root,
    *,
    designer,
    reviewer,
    checkpoint_root: Path,
    model_call_cap: int = 240,
    provider_attempt_cap: int = 840,
    max_items: int = 40,
    invocation_wall_seconds: float = 14_400,
) -> dict

run_v2_full(
    conn,
    project_root,
    *,
    designer,
    reviewer,
    checkpoint_root: Path,
    canary_receipt_path: Path,
    model_call_cap: int = 6_480,
    provider_attempt_cap: int = 22_680,
    max_items: int = 100,
    invocation_wall_seconds: float = 28_800,
) -> dict

audit_v2_generation_run(
    conn,
    project_root,
    *,
    run_id: str,
    checkpoint_root: Path,
) -> dict

verify_v2_generation_receipt(
    conn,
    project_root,
    *,
    receipt_path: Path,
    checkpoint_root: Path,
) -> dict
```

Caller dictionaries, checkpoint contents, adapter envelopes, and CLI flags never authorize
approval, question selection, counts, run ids, attempt ids, lineage, receipts, or activation.

## CLI Contract

```text
generate_answer_contracts.py --db DB --canary-v2-live \
  --checkpoint-root ROOT [--model-call-cap N] [--provider-attempt-cap N] \
  [--max-items N] [--max-wall-seconds N] --json

generate_answer_contracts.py --db DB --full-v2-live \
  --canary-receipt RECEIPT --checkpoint-root ROOT \
  [--model-call-cap N] [--provider-attempt-cap N] \
  [--max-items N] [--max-wall-seconds N] --json

generate_answer_contracts.py --db DB --audit-v2-run RUN_ID \
  --checkpoint-root ROOT --json
```

Rules:

- modes are mutually exclusive;
- `--full-v2-live` requires the exact sealed Batch A receipt;
- configured v2 designer and reviewer routes are validated before run creation;
- Batch A mandatory oracle/policy preflight still runs after DB run creation and before any attempt;
- canary limits are `model_call_cap <= 720`, `provider_attempt_cap <= 2_520`,
  `max_items == 40`, and `max_wall_seconds <= 43_200`;
- full limits are `model_call_cap <= 19_440`, `provider_attempt_cap <= 68_040`,
  `max_items <= 200`, and `max_wall_seconds <= 86_400`;
- non-positive values or values above the hard maximum fail before run mutation;
- API keys, authorization headers, and raw base credentials never appear in JSON, digests, or errors;
- v1 `--design-live`, `--repair-v2-live` single-item probe output, and v1 review flags remain
  compatibility/probe commands. Only the batch modes above can create Batch A/B receipts.

V1-compatible output must include:

```json
{
  "authority_mode": "legacy_probe_only",
  "production_authority": false,
  "activation_eligible": false,
  "blockers": ["v2_batch_generation_authority_required"]
}
```

## Canonical Lock Path Contract

The runner discovers the main DB path from `PRAGMA database_list`, requires a regular resolved
SQLite file, and computes:

```text
lock_dir  = resolved_db.parent / ".answer-contract-v2-locks"
lock_name = sha256(canonical_json({"resolved_main_db_path": str(resolved_db)})) + ".lock"
```

The path does not include `checkpoint_root`, run id, caller input, bank version, or PID. The lock
directory is created safely; symlink traversal and non-regular lock files fail closed. Two
invocations using different checkpoint roots against the same SQLite path must contend on this
same file before any DB mutation or model call.

## Additive SQLite Schema

### `answer_contract_generation_runs`

| Field | Contract |
|---|---|
| `id` | stable local `ACGR-*` primary key |
| `run_schema_version` | exact constant |
| `run_kind` | `canary40|full1120` |
| `run_identity_digest_sha256` | canonical unique identity |
| `parent_canary_run_id` / `parent_canary_receipt_sha256` | required only for full1120 |
| `ledger_id` / `bank_version` / `manifest_sha256` / `graph_version` | exact active-bank authority |
| `plan_digest_sha256` | immutable ordered plan commitment |
| `selection_policy_version` / `selection_source_digest_sha256` | exact canary selection authority |
| `effective_evidence_role_policy_version` / `effective_evidence_role_policy_digest_sha256` | exact shared normalization authority |
| `generator_policy_digest_sha256` | v2 compiler/profile/catalog commitment |
| designer/reviewer prompt/schema/route digests | exact v2 lineage |
| `expected_item_count` | exactly 40 or 1,120 |
| `new_item_count` | exactly 40 or 1,080 |
| `model_call_cap` / `provider_attempt_cap` | positive immutable run caps within hard maxima |
| `item_wall_seconds` | exact existing per-role repair wall policy, currently 180 seconds |
| `heartbeat_interval_seconds` / `stale_after_seconds` | immutable claim policy: 15 seconds and `max(300, ceil(max_route_timeout + 120 + 15))` |
| `operation_generation` | monotonic integer incremented on every successful claim/takeover |
| `claim_token` | random unguessable token for current generation; nullable when terminal |
| `claim_owner_pid` / `claim_invocation_id` | diagnostic owner identity |
| `claimed_at` / `heartbeat_at` | claim timing |
| `preflight_status` | `pending|passed|blocked|not_applicable` |
| `preflight_digest_sha256` | canonical persisted preflight result; Batch A required |
| `status` | run state enum below |
| `model_calls` / `provider_attempts` / `terminal_count` | cached projections, always recomputed for audit/receipt |
| `last_error_class` / `last_error` | bounded diagnostic, no secrets |
| timestamps | created, started, updated, interrupted, completed |

Unique index: `run_identity_digest_sha256`.

### `answer_contract_generation_run_items`

| Field | Contract |
|---|---|
| `id` | stable local item id |
| `run_id`, `ordinal` | unique deterministic position |
| `question_id`, `item_version`, `question_digest_sha256` | exact immutable question authority |
| `node_id`, `kind`, `effective_evidence_role`, `review_record_id` | exact normalized plan lineage; raw fields remain in question digest |
| `effective_evidence_role_policy_version` | exact policy used for the stored normalized value |
| `status` | item state enum below |
| `contract_id/version/digest` | nullable until an exact persisted v2 result exists |
| `designer_run_id` / `reviewer_run_id` | exact agent runs when approved |
| `designer_batch_attempt_id` / `reviewer_batch_attempt_id` | exact lifecycle seam for the final version |
| `checkpoint_digest_sha256` | reconciled file evidence commitment |
| `model_calls` / `provider_attempts` | cached projections from child rows |
| `terminal_class` / `terminal_reason_code` | structured terminal result |
| timestamps | created, started, updated, terminal |

Unique indexes: `(run_id, ordinal)` and `(run_id, question_id, item_version)`.

### `answer_contract_generation_attempts`

One row is one semantic adapter invocation, not one HTTP request.

| Field | Contract |
|---|---|
| `id` | stable `batch_attempt_id`, primary key |
| `run_id`, `run_item_id` | owning run/item |
| `claim_generation` / `claim_token_digest_sha256` | exact owner proof at reservation |
| `role` | `designer|reviewer` |
| `contract_version_index` | zero, one, or two |
| `semantic_attempt_index` | one, two, or three within role/version |
| `request_json` / `request_digest_sha256` | exact trusted request with batch id; untrusted payload remains nested |
| prompt/schema/route digests | exact pinned semantic lineage |
| `status` | semantic attempt state enum below |
| `agent_run_id` / `output_digest_sha256` | nullable until exact persisted result exists |
| `local_verdict` | `accepted|compiler_rejected|review_rejected|malformed|none` |
| `error_class` / `reason_code` | bounded structured failure evidence |
| timestamps | reserved, provider-calling, result, finished |

Unique index: `(run_item_id, role, contract_version_index, semantic_attempt_index)`.

### `answer_contract_generation_provider_attempts`

One row is one real HTTP request started by `model_router`, including endpoint/format fallback.

| Field | Contract |
|---|---|
| `id` | stable local provider-attempt id |
| `batch_attempt_id` | owning semantic attempt |
| `candidate_ordinal` | exact position in pinned candidate list |
| `endpoint` / `structured_json_mode` | exact transport lane |
| `request_digest_sha256` | exact outbound request commitment with secrets excluded |
| `status` | `reserved|calling|response_received|retryable_failure|terminal_failure|provider_result_unknown|interrupted` |
| `http_status` / `retry_after_seconds` | bounded provider evidence |
| `response_digest_sha256` | nullable canonical raw response commitment; raw secret-bearing headers are never stored |
| `error_class` / `error_message` | bounded and scrubbed |
| timestamps | reserved, call-started, response, finished |

Unique index: `(batch_attempt_id, candidate_ordinal)`.

### Existing `agent_runs` And `answer_contracts`

The additive migration introduces explicit batch lineage fields where absent:

- `agent_runs.batch_attempt_id`, also duplicated inside exact `input_refs_json` and covered by
  `input_digest_sha256`;
- `answer_contracts.generator_batch_attempt_id` and `review_batch_attempt_id`;
- design/review receipt JSON includes the same ids and their request/output digests.

An accepted activation-grade v2 contract requires equality across these columns, `agent_runs`,
batch attempts, receipt JSON, generation input, and canonical compiled contract. Fixture, recorded,
mock, fake, v1, or self-attested ids do not satisfy this contract.

### `answer_contract_generation_receipts`

| Field | Contract |
|---|---|
| `id`, `run_id` | one canonical receipt per completed-passed run |
| `receipt_schema_version`, `receipt_kind` | exact `canary40|full1120` |
| `receipt_digest_sha256` | canonical digest of exact payload |
| `payload_json` | exact receipt body |
| `completed_at` | copied from the run completion transaction; never regenerated |
| `status` | `sealed`; mutation/supersession is not allowed for a canonical run identity |

Unique index: `run_id`; unique index: `receipt_digest_sha256`.

## Effective Evidence Role Contract

Constant policy identity:

```text
effective_evidence_role_policy_version = "answer_contract_effective_evidence_role.v1"
```

The sole helper implements the current activation precedence without permissive coercion:

```python
def effective_evidence_role(question):
    normalized = {}
    for field in ("evidence_role", "evidence_goal"):
        value = question.get(field)
        if value is None:
            normalized[field] = ""
            continue
        if not isinstance(value, str):
            raise ValueError("effective evidence role source must be a string")
        normalized[field] = value.strip()
    return normalized["evidence_role"] or normalized["evidence_goal"] or "direct"
```

Contract details:

- precedence is exactly `question.evidence_role || question.evidence_goal || "direct"` after
  nonempty-string normalization;
- missing, `null`, or whitespace-only higher-precedence fields fall through;
- a present non-string value in either field is invalid even if the other field would otherwise win;
- normalization trims surrounding whitespace only; it does not lowercase, translate, alias, or
  infer a semantic role;
- the helper code/policy digest is pinned in the run identity and preflight;
- selection, pair ranking, plan digest, run-item row, design/review packet, contract/checkpoint
  commitment, canary/full receipt, audit, and activation handoff must use this exact output and
  policy version;
- consumers may not recompute from a different precedence rule or use raw `evidence_role` directly;
- raw `evidence_role` and `evidence_goal` remain covered by the authoritative question digest.

Any helper-version, normalized-value, raw-question-digest, or downstream packet/receipt mismatch is
`blocked_integrity`. Historical runs remain bound to their recorded policy version and cannot resume
under a new helper version.

## Run And Item Plan Invariants

Canary:

- exactly 40 unique question id/item-version pairs;
- exactly two per each of the 20 active kinds;
- all rows belong to the same unique active ledger and graph lineage;
- caller cannot nominate ids;
- source candidates are sorted by
  `(node_id, effective_evidence_role, question_id, item_version)`;
- all unordered pairs are ranked by descending `(different_node, different_effective_evidence_role)` and
  ascending canonical row tuple;
- the selected pair must equal the unique rank winner; a lower-diversity pair is invalid whenever
  a higher-diversity pair exists;
- plan stores the full candidate-set digest and diversity availability per kind.

Full:

- exactly 1,120 unique question id/item-version pairs;
- exact equality with authoritative active-bank rows, with no extra or missing;
- exactly 56 nodes x 20 questions;
- exact canary 40 unchanged subset;
- each canary question, contract, attempt, agent run, and receipt commitment equals the parent
  receipt and current DB.

Before Batch B reserves an attempt, it re-runs the same locally reproducible active-bank oracle,
scoring-policy, effective-evidence-role, route, prompt, schema, and plan checks against all 1,120 rows.
Any drift or blocker sets the full run `completed_blocked` with zero Batch B model/provider calls and
no full receipt.

## Mandatory Batch A Preflight Contract

Preflight runs after immutable run/item creation and before the first attempt reservation. It is
computed locally from DB and repository policy only.

Required checks:

1. one active ledger and exact manifest/graph lineage;
2. exact authoritative question-review record for every active-bank question;
3. every registered deterministic v5.1 red oracle over the full active bank, including the known
   v11 misbound ids;
4. every registered deterministic scoring-policy blocker over every authoritative active-bank row,
   not only the selected 40; this includes `v2_scoring_policy_activation_blockers` and the v11
   clock-verification gate even when the clock item is not a canary selection;
5. exact effective-evidence-role normalization for every active-bank row, with one policy version/digest;
6. exact node, kind, effective evidence role, question digest, reference input, and selection commitments;
7. exact local compiler profile/catalog, prompt, schema, route, and provider configuration;
8. no v1, mock, recorded, injected, or caller-authored eligibility source.

Canonical preflight payload:

```json
{
  "schema_version": "answer_contract_v2_batch_preflight.v1",
  "run_id": "ACGR-*",
  "plan_digest_sha256": "...",
  "active_bank_set_digest_sha256": "...",
  "oracle_policy_version": "...",
  "oracle_blockers": [],
  "deterministic_blocker_registry_digest_sha256": "...",
  "scanned_active_question_count": 1120,
  "scanned_active_question_set_digest_sha256": "...",
  "scoring_policy_digest_sha256": "...",
  "policy_blockers": [],
  "effective_evidence_role_policy_version": "answer_contract_effective_evidence_role.v1",
  "effective_evidence_role_policy_digest_sha256": "...",
  "effective_evidence_role_set_digest_sha256": "...",
  "selection_audit": [],
  "preflight_pass": true
}
```

The stored digest excludes no field. `scanned_active_question_count` and set digest must equal the
entire current active bank; selected-item equality is insufficient. If either blocker list is
nonempty, any active row was not scanned, effective-role normalization fails, or the payload is
missing, malformed, stale, or cannot be reproduced, the same transaction sets:

- run `status=completed_blocked`;
- `preflight_status=blocked`;
- `model_calls=0`, `provider_attempts=0`;
- no semantic/provider attempt rows;
- no PASS receipt row.

A blocked summary is operator evidence only and cannot be supplied to Batch B.

## Model, Route, And Batch Attempt Lineage

Both plans pin:

- generator `semantic_designer_local_compiler.v2`;
- `answer_contract_design.v2` and `answer_contract_review.v2` prompt/schema versions and digests;
- exact agent keys/phases, provider `openai`, model name/alias `gpt-5.5`;
- endpoint/format candidate list, transport timeout, retryable statuses, max semantic attempts,
  Retry-After cap, and backoff;
- compiler profile version and all 20 slot-catalog digests.

Before each semantic adapter invocation:

1. verify current CAS claim and cumulative budgets;
2. generate the stable `batch_attempt_id`;
3. render the exact request with trusted batch/run/plan/route lineage and nested untrusted question,
   parent-contract, and reviewer-advisory content; the trusted item descriptor contains only the
   preflight-bound `effective_evidence_role` and policy version, while raw role/goal remain inside
   untrusted authoritative question content;
4. insert the semantic attempt as `reserved`;
5. commit it as `provider_calling` before router transport;
6. pass a router observer carrying that exact id and the enclosing monotonic deadline.

Before each HTTP request, the observer inserts and commits a provider-attempt row as `calling`.
The router may use only the candidate list pinned by the run. A retryable 429/5xx retries according
to the existing bounded policy; it cannot silently negotiate unpinned candidates.

An exact `agent_run` must match:

- `batch_attempt_id`, request and input-ref digests;
- agent key, phase, trigger, status, provider, model name/alias, model params;
- prompt version/template digest and rendered-prompt digest;
- schema version/digest and route/candidate identity;
- canonical output JSON/digest, confidence, validation errors, and local accepted/rejected verdict.

The final contract row and both sealed design/review receipts bind the exact designer and reviewer
batch attempt ids. The model never outputs these ids or any trusted lineage field.

## Orphan And Unknown Recovery Contract

Resume handles each nonterminal semantic attempt before reserving another:

### Exact orphan `agent_run`

Query by `batch_attempt_id`. Recovery is allowed only when exactly one row matches all exact request,
prompt/schema/route, input refs, output digest, local verdict, role, and repair-version facts. The
runner attaches it, completes the attempt/item transaction, and performs zero model/provider calls.

No row means no output authority. Multiple rows, a changed digest, a different verdict, or a run
whose output cannot be locally revalidated sets `blocked_integrity`.

### `provider_result_unknown`

This state applies when at least one HTTP call was committed as started, but neither an authoritative
response boundary nor exact `agent_run` can be established. It consumes one model call and every
started provider attempt. A retry, if budget remains, receives a new `batch_attempt_id`; the unknown
row is immutable.

### `commit_unknown`

This state applies when SQLite commit raised after a deterministic mutation was attempted. The
runner does not claim rollback and does not start another provider call. On resume it queries by
deterministic run/item/attempt/agent-run/contract ids:

- exact committed facts: advance to `committed` and continue;
- exact absence with SQLite integrity proven: return to the prior pre-commit state;
- partial, duplicate, or contradictory facts: `blocked_integrity`.

`committed_unverified` applies when commit returned but immediate read-back failed. It follows the
same audit and cannot be downgraded to transport failure.

## Flock, CAS Claim, And Heartbeat Contract

1. Acquire canonical `flock(LOCK_EX|LOCK_NB)` before run lookup/create or checkpoint read.
2. If unavailable, return `run_locked`, with zero DB mutation and zero model call.
3. Under `BEGIN IMMEDIATE`, load/create the exact run and validate identity/plan/current authority.
4. Claim with `operation_generation = prior + 1` and a new token.
5. Every later mutation uses `WHERE run_id=? AND operation_generation=? AND claim_token=?`.
6. A zero-row update is `claim_lost`; stop without further writes or calls.
7. Heartbeat updates use the same CAS and occur between calls and during router wait observation.
8. Release flock in `finally`; an unfinished owned run becomes `interrupted` unless it is
   `provider_result_unknown`, `commit_unknown`, or `blocked_integrity`.

Takeover:

- fresh `running/provider_calling`: reject as owned;
- stale `running` without unresolved child attempts: seal previous invocation interrupted, then claim;
- stale `provider_calling`: reconcile provider rows and orphan `agent_run` first; exact result is
  attached, otherwise mark provider-result-unknown before claim;
- `interrupted`: revalidate current ledger/plan/eligibility/checkpoints, then claim;
- terminal or completed: audit only; no execution claim;
- `commit_unknown/committed_unverified`: audit before claim or provider work.

The heartbeat interval is 15 seconds. The persisted stale threshold is
`max(300, ceil(max_transport_timeout_seconds + 120 + 15))`, where 120 seconds is the existing maximum
bounded Retry-After. Route timeout or retry-policy changes therefore create a different run identity
and cannot make a live provider call appear stale under the old claim policy.

## Exact Resume Order

Every invocation uses this order:

1. derive and acquire the DB-wide canonical flock;
2. load/create and validate run identity and immutable plan;
3. reconcile uncertain commit/provider states;
4. acquire the DB CAS claim;
5. requery exact current DB v2 eligibility for the next planned item;
6. validate and reconcile the file checkpoint;
7. if one exact eligible DB row exists, rebuild/reuse checkpoint projection with zero calls;
8. if DB and checkpoint disagree, set `blocked_integrity` and stop;
9. reconcile any reserved/provider-calling attempt and orphan `agent_run`;
10. reserve the next `batch_attempt_id` only if run/invocation budgets and wall remain;
11. perform bounded transport, persist exact evidence, and update item projection under CAS;
12. stop at max-items, wall, signal, cap, terminal blocker, or completion.

Checkpoint missing plus exact eligible DB row is recoverable. Checkpoint approval without exact DB
authority is never accepted and never triggers silent reseeding.

## State Model

Run states:

```text
planned -> preflight_running -> running -> completed_passed
                         |            -> interrupted
                         |            -> completed_blocked
                         |            -> cap_exhausted
                         |            -> blocked_integrity
                         |            -> commit_unknown|committed_unverified
                         -> completed_blocked
```

`completed_blocked` is terminal for that immutable run identity. It includes known oracle/policy,
question-bank repair, assessment-policy repair, and terminal semantic outcomes. `cap_exhausted` is a
separate non-PASS terminal state. Neither state has a PASS receipt.

Item states:

```text
pending -> running -> approved|routed|terminal_failure
pending/running -> interrupted|blocked_integrity
approved -> reused_approved
```

Semantic attempt states:

```text
reserved -> provider_calling -> accepted|semantic_rejected|transport_failed
reserved/provider_calling -> interrupted|provider_result_unknown
any preterminal DB transition -> commit_unknown|committed_unverified
```

Provider attempt states are defined in the schema section. Terminal evidence is immutable; retries
always create new ids.

## Budget And Deadline Contract

### Counting

- `model_calls` is the count of committed semantic attempts that reached `provider_calling`.
- `provider_attempts` is the count of committed provider-attempt rows that reached `calling`.
- Each endpoint/format fallback is a separate provider attempt.
- Schema/provider preflight failure before an HTTP row reaches calling consumes no provider attempt.
- A schema-valid response rejected by local compiler/reviewer consumes both counters.
- Provider-result-unknown consumes the semantic call and all started HTTP attempts.

### Defaults And Hard Limits

| Run | Default model / hard | Default provider / hard | Default max-items / hard | Default wall / hard |
|---|---:|---:|---:|---:|
| canary40 | 240 / 720 | 840 / 2,520 | 40 / 40 | 14,400s / 43,200s |
| full1120 | 6,480 / 19,440 | 22,680 / 68,040 | 100 / 200 | 28,800s / 86,400s |

Derivation per new item:

- default model: `3 contract versions x 2 roles x 1 semantic invocation = 6`;
- hard model: `3 x 2 x 3 = 18`;
- default provider: `3 x ((1 designer x 6 candidates) + (1 reviewer x 1)) = 21`;
- hard provider: `3 x ((3 x 6) + (3 x 1)) = 63`.

Batch B limits apply only to the 1,080 newly processed items; reused canary rows produce no Batch B
calls. Receipts report parent and current-run totals separately.

Run counters are cumulative and immutable downward across resume. Invocation counters start at zero
but cannot override run caps. Before every semantic/HTTP start, one transaction checks run count,
invocation count, item count, monotonic wall deadline, signal flag, and current claim.

The router receives the enclosing deadline and sets every candidate timeout to
`min(route_timeout, remaining_deadline)`. It cannot spend six full independent route timeouts after
the outer item deadline expires.

### SIGTERM/SIGINT

The handler only sets `stop_requested`. It performs no SQLite or checkpoint write. The normal control
path then:

1. starts no new semantic/provider attempt;
2. lets the current child HTTP process finish or reach its bounded timeout;
3. persists exact result or `provider_result_unknown`;
4. marks the run interrupted with cumulative counters and timestamp;
5. writes the reconciled checkpoint projection;
6. releases flock in `finally`.

Resume follows the exact resume order and does not reset caps, counters, or operation generation.

## Deterministic Completion And Receipt No-Op

The completion transaction holds the current CAS claim and performs:

1. fresh active-ledger and plan equality audit;
2. fresh item/contract/attempt/agent-run/receipt/checkpoint eligibility audit;
3. counter recomputation from semantic/provider child rows;
4. one `completed_at = now` assignment on the run;
5. receipt construction using that stored `completed_at`;
6. receipt insertion and run transition to `completed_passed` in the same transaction;
7. claim token clearing.

If a canonical receipt already exists, no new timestamp is read. The runner reconstructs the bound
historical body from the exact rows committed by that run, using the stored run `completed_at`, and
compares exact payload JSON and digest:

- exact match: return `already_completed` and the existing receipt with zero DB writes;
- current-ledger or current-policy drift: return `not_current_authority`; keep the historical run and
  receipt immutable and forbid reuse for Batch B;
- missing receipt for completed run, duplicate receipt, bound payload drift, or digest drift: return
  an integrity-blocked audit result; never re-seal, replace, or mutate the completed run.

File receipt/checkpoint projection may be recreated from the exact DB payload when missing, but it
cannot alter `completed_at`, payload JSON, or digest.

## Canary Receipt Contract

Exact fields include:

- schema, kind, sealed status, and `completed_at`;
- `production_authority_scope=canary_generation_gate_only`;
- `activation_eligible=false`;
- run id, identity, plan, preflight, policy, selection, and checkpoint commitment digests;
- ledger, bank, manifest, graph/config lineage;
- exact ordered 40 question ids, versions, digests, nodes, kinds, normalized effective evidence roles,
  and effective-evidence-role policy version/digest;
- exact v2 contract ids/versions/digests;
- exact designer/reviewer batch attempt ids and agent run ids;
- exact design/review receipt digests;
- semantic/provider totals and terminal/routed/missing counts all consistent with PASS;
- receipt digest.

The body is rebuilt from DB and reconciled checkpoints. Caller results are ignored. Any preflight
blocker, missing item, mock/v1 lineage, routed result, terminal result, or uncertainty forbids it.

## Full Receipt Contract

The full receipt includes the canary fields plus:

- `production_authority_scope=full_generation_evidence_only`;
- exact parent canary run id/receipt digest;
- exact ordered 1,120 question/contract/attempt/run/receipt commitments;
- `reused_canary_count=40` and `generated_after_canary_count=1080`;
- current-run and parent call totals separately;
- zero missing, duplicate, routed, terminal, mock, recorded, v1, stale, policy-blocked, or uncertain items;
- `activation_eligible=false`.

The body is generated only from a fresh DB query. Run manifest totals, caller classifications, or
checkpoint counts cannot substitute.

## Authority Handoff Contract

The Batch B receipt proves generation completeness only. It does not prove independent activation
review or fingerprint readiness and cannot be consumed as an activation command.

The later activation implementation must retain the existing v5.1 gates and, in one independent
`BEGIN IMMEDIATE` transaction, revalidate:

1. unique current active ledger and exact 1,120 question set;
2. current v2 per-contract activation readiness, including batch-attempt, exact agent-run lineage,
   and the same effective-evidence-role helper policy/output used by generation and review;
3. exact current fingerprint for every item;
4. all 224 live review shard receipts;
5. all 56 node receipts;
6. one global answer-contract review receipt;
7. mandatory misbinding oracles and zero rejected/routed/missing/policy-blocked rows;
8. exact set equality between question, contract, fingerprint, shard, node, and global evidence;
9. all-or-nothing status update and activation receipt in that same transaction.

Batch A/B implementation must not modify, weaken, synthesize, or bypass these gates. The currently
unimplemented activation write remains unchanged in this scope.

## Failure Contract

Fail closed for:

- missing/multiple active ledgers or plan drift;
- known oracle or scoring-policy blocker anywhere in the active bank, selected or not;
- illegal or mismatched effective-evidence-role source, policy version, normalized value, or packet;
- lower-diversity canary selection when a higher-diversity pair exists;
- fake, mock, recorded, non-OpenAI, non-gpt-5.5, v1, or self-attested lineage;
- missing/duplicate/conflicting batch attempt or agent run;
- DB/checkpoint disagreement;
- lock contention, claim loss, unsafe path, stale owner without valid takeover;
- missing/duplicate exact question/contract/provider-attempt rows;
- terminal/routed/policy-blocked item;
- semantic/provider cap exhaustion or invocation wall/item limit;
- unresolved provider-result-unknown, commit-unknown, or committed-unverified;
- receipt drift or attempted receipt re-sealing.

No failure writes a PASS receipt, changes a contract/fingerprint to active, or claims rollback after
an uncertain commit.

## Test Hooks

Injectable implementation hooks:

- wall and monotonic clocks, sleep, and completion timestamp supplier;
- PID, invocation id, signal flag, heartbeat, and claim-token suppliers;
- canonical flock path derivation and flock acquire/release wrapper;
- before/after run, attempt, provider-attempt, agent-run, item, and receipt commits;
- router provider-attempt observer before HTTP and after response/error;
- fake exact-lineage designer/reviewer adapters;
- checkpoint read/write adapter;
- forced SQLite commit exception and post-commit read failure.

Fake adapters can exercise transport/state contracts but cannot produce a production receipt unless
the isolated test explicitly installs exact accepted `agent_runs` matching the production contract.

## Required Isolated Tests

### Preflight And Plan

1. exact 40 plan and exactly two per kind;
2. pair selection prefers cross-node and cross-effective-evidence-role candidates and is stable under
   source row order;
3. mixed rows with missing `evidence_role`, only `evidence_goal`, and explicit `evidence_role="direct"`
   normalize respectively to `direct`, the trimmed goal, and explicit `direct`; canonical sorting and
   plan digest remain stable across source key/order changes;
4. whitespace-only `evidence_role` falls through to a valid string `evidence_goal`, while a present
   number/list/object in either inspected source fails closed before plan completion;
5. caller-nominated ids are ignored/rejected;
6. known full-bank oracle blocker outside the selected 40 yields `completed_blocked`, zero
   model/provider calls, and no receipt;
7. a non-canary v11 clock-policy blocker yields the same zero-call outcome even when all selected 40
   have no local blocker;
8. an implementation scanning only selected ids fails the active-bank scanned-set/count oracle;
9. preflight or effective-evidence-role policy/output digest tamper and source drift block resume.

### Lifecycle And Recovery

10. run/item/preflight and `batch_attempt_id` commit before first provider call;
11. exact id appears in provider row, trusted request/input refs, `agent_run`, contract, and receipts;
12. design/review packets and receipts carry the same normalized effective role and policy version as
    selection/run item; raw-field reinterpretation or activation-handoff drift blocks;
13. exact orphan `agent_run` is attached with zero new calls;
14. orphan with request/output/prompt/schema/route/verdict mismatch blocks;
15. provider-result-unknown and commit-unknown follow distinct states and retry rules;
16. schema-valid local rejection persists rejected agent evidence but no approved contract.

### Exclusion And CAS

17. held canonical flock yields zero mutation/callback;
18. two different checkpoint roots against one DB contend on one lock;
19. stale running takeover increments generation and invalidates old token writes;
20. stale provider-calling reconciles exact orphan evidence or seals provider-result-unknown;
21. fresh owner and commit-unknown cannot be stolen;
22. lost CAS stops before model/receipt work.

### Budgets, Wall, And Signal

23. one semantic call expanding across six candidates counts one model call and six provider attempts;
24. cumulative counts survive restart and cannot decrease;
25. default and hard caps enforce exact Batch A/B limits;
26. outer deadline truncates candidate fallback and prevents new calls;
27. max-items stops a full invocation without terminalizing the run;
28. SIGTERM during idle and provider-calling paths persists honest interrupted/unknown state and resumes.

### Receipt And Authority

29. exact existing eligible DB row yields zero model calls;
30. checkpoint/DB disagreement blocks even after checkpoint reseal;
31. canary receipt has 40, fixed `completed_at`, and no activation authority;
32. repeated completed audit returns byte-identical receipt and performs zero DB writes/time calls;
33. changed bound verdict fails integrity; changed current authority blocks reuse while preserving the
    historical receipt; neither path re-seals;
34. full plan is exact 1,120, reuses 40, and processes only 1,080;
35. full receipt is rebuilt from DB and rejects extra/missing/duplicate rows;
36. 40 generation receipt cannot satisfy full or activation authority;
37. full receipt cannot bypass missing shard/node/global/fingerprint gates;
38. v1 CLI remains compatible but cannot write Batch A/B receipt rows;
39. multiprocessing spawn proves single ownership, safe signal recovery, and no duplicate provider calls.

All tests use temporary SQLite DBs, temporary checkpoint roots, and fake adapters. They do not call
a real model, touch the real DB/checkpoints, initialize Git, or use port 8765.

## Compatibility And Rollout

- All schema changes are additive.
- Existing v1 drafts/checkpoints remain immutable historical evidence and activation-ineligible.
- Existing single-item v2 probe remains non-authoritative and cannot seal batch receipts.
- Existing exact v2 contract rows may be reused only after DB reconstruction proves all new
  batch-attempt lineage; otherwise they remain historical and the batch fails closed.
- Batch A is implemented, tested, and reviewed before Batch B begins.
- Batch B is implemented, tested, and reviewed before any activation implementation or policy change.
- No backfill invents `batch_attempt_id` for historical runs.

## Review Remediation Checklist

- [x] Mandatory Batch A oracle/policy preflight scans the complete active bank before attempts;
  selected and non-canary blockers both complete blocked with zero calls and no PASS receipt.
- [x] Canary selection deterministically maximizes cross-node and normalized effective-evidence-role diversity.
- [x] One versioned helper implements `evidence_role || evidence_goal || "direct"` and supplies the
  exact value/policy to plan, run item, packets, receipts, audit, and activation handoff.
- [x] `batch_attempt_id` spans transport, provider rows, trusted request, `agent_run`, contract, and receipts.
- [x] Orphan recovery requires exact request/output and lineage; provider and commit uncertainty differ.
- [x] Flock is DB-wide and checkpoint-root independent; CAS generation/token and takeover are exact.
- [x] Default/hard semantic and real HTTP budgets, cumulative resume, wall, item, and signal limits are fixed.
- [x] Completion timestamp and receipt digest are deterministic no-op authority.
- [x] Batch B is generation evidence only; 224/56/global/fingerprint/oracle/atomic activation gates remain.

## ENGINEERING_CONTRACT_QUALITY_GATE

- verdict: `ENGINEERING_CONTRACT_READY_FOR_DESIGN_REVIEW`
- interfaces_complete: yes; public APIs and CLI limits are exact
- field_contracts_complete: yes; run/item/semantic/provider/receipt, effective evidence role, and existing lineage fields defined
- call_chain_complete: yes; preflight through receipt and later authority handoff traced
- sync_async_boundary: synchronous single writer with spawned bounded HTTP child already used by router
- queue_usage: not_applicable; one local operator runner does not need a queue
- storage_and_indexes: additive schema and uniqueness defined
- idempotency_and_recovery: exact DB-first resume, orphan reconciliation, CAS, unknown outcomes, no-op receipt
- model_provider_boundary: exact v2 GPT-5.5 lineage plus per-HTTP candidate accounting
- compatibility: v1 and single-item probe retained but non-authoritative; no invented historical lineage
- security_and_secrets: credentials excluded; trusted and untrusted request data remain separated
- testability: 39 focused isolated/adversarial contracts plus commit/router/signal hooks
- failure_resilience: full-bank preflight blocking, role-policy drift rejection, split-brain prevention,
  cumulative caps, SIGTERM, commit/provider uncertainty
- performance_cost: minimum/default/hard model and HTTP counts are explicitly derived from current topology
- authority_handoff: existing independent review/fingerprint/activation gates remain mandatory and unchanged
- quality_evidence: current v2 retry constants, router candidate behavior, DB-backed `agent_runs`,
  activation's `evidence_role || evidence_goal || "direct"` precedence, and current 56-node/224-shard
  activation audit were verified against source
- blocking_gate: independent 镜花 `DESIGN_REVIEW` must be non-blocking before production or test edits
