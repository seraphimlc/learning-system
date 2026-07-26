# Codex Admin Module Technical Plan v1

Status: `TECHNICAL_DESIGN_READY_FOR_REVIEW`

Owner: 听云

Created: 2026-07-23

Scope: Codex-only 管理模块。覆盖科目、知识资产、题源、题库库存、答案合同、审核 receipt、激活门禁、学习聚合信号到题库治理。不做 Web UI，不管理孩子个人进度，不写 mastery。

## 结论

管理端第一版不建页面，落成一组可由 Codex 调用的本地管理命令和结构化 Markdown/JSON/SQLite 资产。

最小充分架构：

```text
Codex request
-> scripts/admin_console.py <command>
-> learning_system/admin/
   -> repositories over SQLite + JSON + Markdown receipts
   -> inventory analyzers
   -> source receipt writer
   -> activation/readiness gate adapters
-> docs/system/admin_reports/*.md
-> optional JSON stdout for Codex consumption
```

这个设计故意不让管理端进入孩子 runtime 热路径。孩子端仍只读 active 题库和 runtime 投影；管理端只生产、审核、查询和治理内容资产。

## Source Readiness

Ready for implementation with scoped review.

Product source:

- `docs/product/admin_console_prd_v1.md`
- `docs/design/specs/2026-07-23-question-bank-production-spec-v18.1.md`
- `AGENTS.md`

Current implementation evidence:

- `data/knowledge_graphs/math/math_knowledge_graph_v2.json` is the math graph fact source.
- `data/question_banks/v18/question_type_taxonomy_v18.json` defines v18 question families.
- `data/question_banks/v18/node_question_blueprints_v18.json` defines node production blueprints.
- `data/question_banks/v18/math_v18_sample_60.json` is sample-only and not active.
- `scripts/question_bank_v18_activation_gate.py` already implements fail-closed sample/activation gate semantics.
- `scripts/build_question_bank_v18_sample_gate_manifest.py` already uses input digests and receipt-like manifest structure.
- `learning_system/question_bank.py` still contains v12/v17 runtime constants and should not become the admin source of truth for v18 activation.
- `learning_system/db.py` owns runtime evidence/mastery validation and must remain separate from admin content governance.

Open but non-blocking:

- Existing DB schema has grown around runtime and assessments; admin tables should be additive and not reuse runtime mastery tables.
- Current v18 assets live as JSON files; first implementation should support JSON-backed inventory before requiring full DB migration.
- Model compatibility evidence is tracked in `docs/system/qa/model_compatibility_probe_2026-07-23.md`.

## Architecture Decisions

| Decision | Contract |
|---|---|
| Delivery shape | CLI + Python service modules + Markdown/JSON receipts. No Web UI. |
| Entrypoint | `scripts/admin_console.py` is the single Codex-facing command entry. |
| Owning package | `learning_system/admin/` owns admin repositories, analyzers, source receipts, inventory reports, and gates. |
| Data strategy | Additive SQLite tables for mutable admin state; existing graph/question-bank JSON remains canonical until imported/staged. |
| Receipts | Markdown for human/expert communication plus adjacent JSON front matter or sidecar for deterministic validation. |
| Writes | Write operations require `--apply`; destructive or activation-affecting commands require `--confirm <operation_id>`. |
| Runtime boundary | Admin may read learning aggregates but never writes `mastery`, current step, attempt, or session flow. |
| Commercial source handling | Default `capture_policy=no_capture`; only metadata/structure notes until explicit license evidence exists. |
| Activation | Active state is derived from gates/receipts, never from item JSON. Existing v18 activation gate remains fail-closed. |
| Reports | Codex-readable Markdown reports under `docs/system/admin_reports/`; no child-facing output. |

## Command Surface

All commands support:

- `--format text|json`
- `--db data/local_learning_system.sqlite`
- `--root <project-root>`
- `--dry-run` by default for write-capable commands
- `--apply` for writes

### Inventory

```bash
python3 scripts/admin_console.py inventory subject --subject math
python3 scripts/admin_console.py inventory graph --subject math
python3 scripts/admin_console.py inventory question-bank --version v18 --subject math
python3 scripts/admin_console.py inventory node --node-id M-G7-NUMBER-LINE
```

Output fields:

- subject/stage;
- graph node count;
- question counts by node/family/difficulty/status;
- answer contract coverage;
- active/staged/draft/rejected counts;
- duplicate structure-fingerprint risk;
- missing candidate budgets against node blueprints;
- unsupported nodes/families;
- next recommended admin actions.

### Source Discovery And Analysis

```bash
python3 scripts/admin_console.py source add-candidate --name ... --url ... --source-type ...
python3 scripts/admin_console.py source analyze --source-id ... --apply
python3 scripts/admin_console.py source list --status candidate
python3 scripts/admin_console.py source show --source-id ...
```

`source analyze` creates:

- `question_sources` row;
- Markdown receipt under `docs/system/admin_reports/source_receipts/`;
- optional JSON sidecar under `data/admin/source_receipts/`;
- `source_pattern_note` when direct use is not allowed.

No command may save commercial题干/答案/解析 unless `capture_policy=full_content_with_license` and a license receipt exists.

### Review And Receipts

```bash
python3 scripts/admin_console.py review import --receipt docs/system/admin_reports/reviews/...
python3 scripts/admin_console.py review status --item-id ...
python3 scripts/admin_console.py gate readiness --manifest ...
python3 scripts/admin_console.py review candidate --candidate data/admin/candidates/CAND-....json
```

Review receipt types:

- `source_analysis`;
- `ai_question_review`;
- `education_expert_review`;
- `qa_review`;
- `architecture_review`;
- `answer_contract_review`;
- `browser_child_flow`;
- `live_model_grading`.

`review candidate` is the production-line single-item expert receipt. It runs deterministic expert profiles against one candidate artifact and produces a receipt consumable by `production loop-decision`. It does not stage or activate the candidate.

Model-assisted expert review uses:

- contract: `learning_system/agent_contracts/admin_question_expert_review.v1.json`
- prompt: `learning_system/prompts/admin_question_expert_review.v1.md`
- authority: review receipt only; it cannot activate questions, mutate mastery, or choose child next steps.

### Expert Design Ideas

```bash
python3 scripts/admin_console.py design expert-ideas --node-id M-G7-NUMBER-LINE
```

This creates a generation brief, not final questions. It combines node blueprint, current inventory, family plan, and five expert design perspectives. The brief must include ordered `question_requirements`; those slots are the source of truth for what each generated question should test.

Model-assisted design uses:

- contract: `learning_system/agent_contracts/admin_question_type_design_board.v1.json`
- prompt: `learning_system/prompts/admin_question_type_design_board.v1.md`
- authority: generation brief only; it cannot generate final active questions, mutate mastery, or choose child next steps.

### Question Production Loop

```bash
python3 scripts/admin_console.py production requirement-plan --node-id M-G7-NUMBER-LINE
python3 scripts/admin_console.py production plan --node-id M-G7-NUMBER-LINE --family-id number_line_position_distance
python3 scripts/admin_console.py production plan-batch --node-id M-G7-NUMBER-LINE --family-id number_line_position_distance --requirements-plan data/admin/production/PROD-....json --limit 20 --apply
python3 scripts/admin_console.py production generate-candidate --generation-plan data/admin/production/PROD-....json
python3 scripts/admin_console.py production validate-candidate --candidate candidate.json --design-brief data/admin/design_ideas/EXPERT-IDEAS-....json
python3 scripts/admin_console.py production loop-decision --machine-report data/admin/production/PROD-....json --expert-report expert-review.json
python3 scripts/admin_console.py production staging-decision --machine-report data/admin/production/PROD-....json --expert-report expert-review.json --qa-report qa-review.json
python3 scripts/admin_console.py production stage-candidate --candidate data/admin/candidates/CAND-....json --staging-decision data/admin/production/PROD-....json --apply
python3 scripts/admin_console.py production run-slot --generation-plan data/admin/production/PROD-....json --max-attempts 3 --apply
python3 scripts/admin_console.py production run-batch --generation-plan data/admin/production/PROD-A.json --generation-plan data/admin/production/PROD-B.json --workers 3 --max-slots 20 --max-runtime-seconds 1800 --apply
python3 scripts/admin_console.py production run-batch --generation-plan data/admin/production/PROD-A.json --generation-plan data/admin/production/PROD-B.json --generation-batch-size 2 --max-slots 20 --max-runtime-seconds 1800 --apply
```

Production loop contract:

- `design expert-ideas` is the only first-version command that creates ordered per-question requirement slots. Expert design owns slot meaning.
- `production requirement-plan` validates and extracts ordered per-question requirement slots from the expert design brief. It must fail closed when the brief has no `question_requirements`; it must not invent slots.
- `production plan` creates the bounded packet for `question_designer_agent`; when a slot is supplied, the packet is exactly one-question scoped. It never generates, reviews, stages, or activates questions.
- `production plan-batch` creates one bounded generation packet per selected requirement slot, writes unique plan files, and writes a summary with `generation_plan_paths` for `run-batch`. It does not call the model or stage questions.
- `production generate-candidate` calls `question_designer_agent` for one slot-scoped production plan, writes a candidate artifact, and immediately runs the deterministic machine check. If the model route is missing or fails, it writes a blocked production report instead of fabricating a mock question.
- Generated candidate artifact paths include the candidate payload hash, not only the candidate id. Re-running the same slot preserves old failed/pass evidence instead of overwriting previous candidate JSON.
- `validate-candidate` is the deterministic program gate after generation. It checks required fields, production lineage, graph node, family plan, slot binding, required evidence, answer scoring sum, structure fingerprint, source boundary and illegal self-declared staged/active/activation state.
- `loop-decision` is the workflow router after machine/expert review. Blocking findings return to `question_designer_agent` with previous rejection codes; exhausted attempts escalate to human design review.
- `review qa-candidate` is the production-line Guanzhi QA receipt. It checks child-surface safety, self-contained prompt shape, observable reasoning evidence, scoring contract presence and structure fingerprint.
- `staging-decision` combines machine report, expert receipt and Guanzhi QA receipt. It can allow staged readiness only when all three pass; it never grants active use.
- `stage-candidate` appends a `STAGED_READY` candidate to `data/question_banks/v18/staged_candidates_v18.json`. It is idempotent for the same candidate payload, blocks duplicate structure fingerprints, writes staging receipt evidence, and explicitly keeps `activation_eligible=false`.
- `run-slot` is the programmatic slot workflow. It executes generation, deterministic machine check, expert review, Guanzhi QA, staging decision and staged-bank write in order, carries structured rejection receipts into retries, caps attempts, and stops fail-closed. It uses project assets for validation and can write artifacts separately when needed for tests or dry production sandboxes.
- `run-batch` is the bounded batch workflow. It writes one slot workflow receipt per plan plus one batch summary receipt, honors `max-slots` and `max-runtime-seconds`, and never grants activation. The default production efficiency path is `--workers N` with `--generation-batch-size 1`: each plan still runs as a complete single-question workflow, while several small model calls run concurrently. Staged-bank writes are serialized by resolved bank path, so concurrent workflows cannot overwrite each other's accepted candidates.
- `--generation-batch-size 2..5` remains an explicit experimental path. It can call `question_designer_agent` once for a small group of slots, then split outputs back into per-item machine/expert/QA/staging receipts. It is intentionally not combined with parallel workers, and failed batch outputs fall back to single-slot regeneration rather than silently passing.
- A candidate without a matching expert design brief is `NEEDS_REGENERATION`.
- A candidate without a matching `slot_id` / `question_requirement_id` is `NEEDS_REGENERATION` when produced from a slot.
- A candidate outside the selected family is `NEEDS_REGENERATION`.
- A candidate with P0/P1 findings, expert `needs_revision`, expert `reject`, or missing expert status is `NEEDS_REGENERATION`.
- Missing Guanzhi QA receipt blocks staged readiness even when machine and expert checks pass.
- Staged storage is not active storage. Child runtime must not read staged candidates until a later activation manifest and activation gate pass.
- Regenerated candidates must carry previous blocking rejection codes so the next attempt is not a cosmetic rewrite.
- Production reports are written under `docs/system/admin_reports/production/` and `data/admin/production/` only when `--apply` is present.

New implementation surface:

- `learning_system/admin/production_loop.py`
- `tests/test_admin_console_production_loop.py`
- `learning_system/agent_contracts/question_candidate.v1.json`
- `learning_system/prompts/question_candidate.v1.md`

### Learning Signal To Bank Governance

```bash
python3 scripts/admin_console.py learning-signal summarize --subject math
python3 scripts/admin_console.py learning-signal propose-bank-actions --subject math --since 2026-07-01
```

Allowed inputs:

- node-level weak evidence counts;
- question-family failure/misgrade frequency;
- single-item disputed assessment events;
- stuck/photo uncertainty aggregates;
- repeated duplicate exposure signals.

Outputs are proposals only:

- `add_questions`;
- `retire_questions`;
- `repair_answer_contract`;
- `revise_knowledge_card`;
- `revise_node_blueprint`;
- `request_expert_review`.

Forbidden outputs:

- direct mastery update;
- direct next-question selection;
- active activation;
- child-facing feedback.

## Data Contracts

### SQLite Additive Tables

Do not modify runtime tables for admin state. Add a migration script later, likely `scripts/init_admin_console_db.py`, with idempotent `CREATE TABLE IF NOT EXISTS`.

#### `admin_subjects`

- `subject_key TEXT PRIMARY KEY`
- `display_name TEXT NOT NULL`
- `current_stage TEXT NOT NULL`
- `graph_version TEXT`
- `default_question_bank_version TEXT`
- `default_knowledge_card_version TEXT`
- `enabled INTEGER NOT NULL DEFAULT 1`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

#### `question_sources`

- `source_id TEXT PRIMARY KEY`
- `source_name TEXT NOT NULL`
- `source_type TEXT NOT NULL`
- `source_url_or_file TEXT`
- `license_type TEXT`
- `direct_use_allowed INTEGER NOT NULL DEFAULT 0`
- `adaptation_allowed INTEGER NOT NULL DEFAULT 0`
- `ai_ingestion_allowed INTEGER NOT NULL DEFAULT 0`
- `commercial_use_allowed INTEGER NOT NULL DEFAULT 0`
- `attribution_required INTEGER NOT NULL DEFAULT 0`
- `attribution_text TEXT`
- `usage_mode TEXT NOT NULL`
- `capture_policy TEXT NOT NULL`
- `review_status TEXT NOT NULL`
- `source_analysis_receipt_path TEXT`
- `source_analysis_receipt_sha256 TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Allowed enums:

- `source_type`: `user_owned`, `open_license`, `commercial_reference`, `public_web_reference`, `publisher_catalog_reference`, `ai_original`, `teacher_original`
- `usage_mode`: `direct_import`, `adapted_import`, `structure_reference_only`, `scope_reference_only`, `rejected`
- `capture_policy`: `metadata_only`, `excerpt_with_permission`, `full_content_with_license`, `no_capture`
- `review_status`: `candidate`, `needs_license_review`, `reviewed_scope_only`, `approved_for_direct_import`, `approved_for_adaptation`, `rejected`

#### `admin_review_receipts`

- `receipt_id TEXT PRIMARY KEY`
- `receipt_type TEXT NOT NULL`
- `subject_key TEXT`
- `source_id TEXT`
- `question_bank_version TEXT`
- `item_id TEXT`
- `node_id TEXT`
- `reviewer_role TEXT NOT NULL`
- `reviewer_name TEXT`
- `status TEXT NOT NULL`
- `scope TEXT NOT NULL`
- `receipt_path TEXT NOT NULL`
- `receipt_sha256 TEXT NOT NULL`
- `input_digest_json TEXT NOT NULL`
- `created_at TEXT NOT NULL`

#### `question_inventory_snapshots`

- `snapshot_id TEXT PRIMARY KEY`
- `subject_key TEXT NOT NULL`
- `question_bank_version TEXT NOT NULL`
- `source_digest_json TEXT NOT NULL`
- `summary_json TEXT NOT NULL`
- `report_path TEXT`
- `report_sha256 TEXT`
- `created_at TEXT NOT NULL`

#### `bank_governance_proposals`

- `proposal_id TEXT PRIMARY KEY`
- `subject_key TEXT NOT NULL`
- `source_signal_type TEXT NOT NULL`
- `node_id TEXT`
- `question_family_id TEXT`
- `item_id TEXT`
- `proposal_type TEXT NOT NULL`
- `status TEXT NOT NULL DEFAULT 'proposed'`
- `evidence_summary_json TEXT NOT NULL`
- `proposal_path TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Allowed `proposal_type`:

- `add_questions`
- `retire_questions`
- `repair_answer_contract`
- `revise_knowledge_card`
- `revise_node_blueprint`
- `request_expert_review`

### Markdown Receipt Template

Template path:

- `docs/system/admin_reports/templates/source_analysis_receipt_template.md`

Receipt instances:

- `docs/system/admin_reports/source_receipts/YYYY-MM-DD-<source-id>.md`

Required sections:

- identity;
- source access facts;
- license/terms observation;
- allowed use;
- forbidden use;
- graph mapping;
- question-family mapping;
- risk;
- recommended usage mode;
- reviewer signoff.

### JSON Sidecar

Optional machine-readable sidecar:

- `data/admin/source_receipts/<source-id>.json`

Fields:

- `schema_version`
- `source_id`
- `source_name`
- `source_type`
- `source_url_or_file`
- `accessed_at`
- `license_observation`
- `usage_mode`
- `capture_policy`
- `allowed_use`
- `forbidden_use`
- `mapped_node_ids`
- `mapped_question_family_ids`
- `risk_level`
- `receipt_markdown_path`
- `receipt_markdown_sha256`

## Call Chains

### Inventory Query

```text
Codex
-> scripts/admin_console.py inventory question-bank
-> learning_system.admin.inventory.QuestionBankInventoryService
-> load graph JSON, v18 taxonomy, v18 blueprints, question bank JSON/manifest
-> compute counts/coverage/duplicates/missing budgets
-> write optional report
-> stdout summary
```

Failure behavior:

- missing graph/taxonomy/blueprint: fail closed with `ADMIN_SOURCE_MISSING`;
- malformed JSON: fail closed with path and parser error;
- sample-only manifest passed to activation query: report `not_activation_ready`, not error for inventory;
- no active bank: return inventory gap, not fake zero quality.

### Source Analysis

```text
Codex
-> source add-candidate/analyze
-> SourceRepository
-> SourceAnalysisService
-> optional web/manual metadata fetch
-> write Markdown receipt
-> write JSON sidecar
-> update question_sources row
```

Failure behavior:

- inaccessible URL: create candidate row only if `--apply`; receipt status `needs_manual_access`;
- unclear license: `usage_mode=scope_reference_only`, `capture_policy=no_capture`;
- commercial source: default `structure_reference_only`, never direct import.

### Learning Signal Governance

```text
Codex
-> learning-signal propose-bank-actions
-> read runtime aggregate tables/read-only reports
-> summarize by node/family/item dispute
-> join current inventory gaps
-> create bank_governance_proposals when --apply
```

Failure behavior:

- no learning data: return `NO_SIGNAL`;
- stale reports only: return `STALE_SIGNAL_NO_WRITE`;
- pending/blocked model evidence: allowed as risk signal, not mastery evidence;
- no active question mapping: create `request_expert_review` proposal, not content mutation.

## Safety And Permissions

Write policy:

- Read commands never require confirmation.
- Additive writes require `--apply`.
- Activation-affecting operations require `--apply --confirm <operation_id>`.
- Deletes are out of MVP; use `retired` / `rejected` state transitions.

Operation ids:

- Deterministic digest over command name, target ids, input digests, actor label, timestamp bucket, and dry-run report digest.
- A command first returns `requires_confirmation` with operation id.
- The second call with matching `--confirm` performs the write if inputs are unchanged.

Privacy:

- Source and inventory reports may contain internal ids.
- They must never be projected to child pages.
- Learning signal reports must not include raw child personal narrative unless explicitly needed for a disputed single item; prefer attempt id and sanitized answer summary.

Commercial/copyright boundary:

- No login bypass, paywall bypass, anti-bot circumvention, bulk crawling, or copied commercial content storage.
- Public目录/样章 can inform structure notes.
- Direct import requires explicit license evidence in receipt.

## Implementation Blueprint

### Phase 1: Documentation And Templates

Files:

- `docs/architecture/codex_admin_module_technical_plan_v1.md`
- `docs/system/admin_reports/templates/source_analysis_receipt_template.md`
- `docs/system/admin_reports/README.md`

Validation:

- static doc check for required sections.

### Phase 2: Core Admin Package

Files:

- `learning_system/admin/__init__.py`
- `learning_system/admin/models.py`
- `learning_system/admin/paths.py`
- `learning_system/admin/repositories.py`
- `learning_system/admin/inventory.py`
- `learning_system/admin/source_receipts.py`
- `learning_system/admin/learning_signals.py`
- `learning_system/admin/gates.py`

Key functions:

```python
build_question_bank_inventory(root: Path, version: str, subject: str) -> InventoryReport
create_source_analysis_receipt(source: QuestionSource, observations: SourceObservation) -> Receipt
propose_bank_governance_actions(db_path: Path, root: Path, subject: str, since: str | None) -> list[GovernanceProposal]
validate_admin_activation_readiness(manifest_path: Path) -> GateReport
```

### Phase 3: CLI

File:

- `scripts/admin_console.py`

Subcommands:

- `inventory subject|graph|question-bank|node`
- `source add-candidate|analyze|list|show`
- `review import|status`
- `gate readiness`
- `learning-signal summarize|propose-bank-actions`

### Phase 4: DB Migration

File:

- `scripts/init_admin_console_db.py`

Rules:

- idempotent;
- additive only;
- no reset of runtime tables;
- tests use temp DB.

### Phase 5: Tests

Files:

- `tests/test_admin_console_inventory.py`
- `tests/test_admin_console_source_receipts.py`
- `tests/test_admin_console_learning_signals.py`
- `tests/test_admin_console_gates.py`

Minimum tests:

- v18 sample inventory reports sample-only and not active;
- source receipt for commercial source defaults to `no_capture`;
- unclear license cannot become `direct_import`;
- Markdown receipt digest changes when content changes;
- learning signal proposal does not write mastery;
- activation readiness still fails closed without required receipts;
- destructive command requires confirmation.

## Release Sequence

1. Land docs and templates.
2. Land read-only inventory CLI.
3. Land source candidate/receipt writer.
4. Land admin DB migration.
5. Land learning-signal proposal generator.
6. Land review import and readiness gate adapter.
7. Only after tests pass, use it to build the first candidate source list.

## Review Targets

镜花 should review:

- runtime/mastery write boundary;
- activation state derivation;
- receipt digest and stale evidence behavior;
- commercial source capture policy.

观止 should test:

- fail-closed activation;
- source license ambiguity;
- commercial source no-capture;
- inventory gap reporting;
- learning-signal-to-proposal without child-state mutation.

若命 should validate:

- Codex output is enough to manage inventory;
- no Web UI assumption remains;
- topic-source-review-production loop matches product intent.
