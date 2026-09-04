# Question Production Cleanup Manifest

Date: 2026-08-14

The v18/v19 question-production implementation is retired. The new system starts from an empty question bank and must not import, resume or read the retired production path.

## Retired assets

- v18/v19 question-bank JSON, visual registries and generated bank data.
- v18/v19 generation, audit, reconciliation, withdrawal and full-bank runner scripts.
- v18/v19 production tests and browser fixtures.
- v18/v19 admin prompts, agent contracts and historical reports.
- v18/v19 admin-console production specifications and code maps.
- batch atomic, historical migration, calibration-campaign and whole-bank orchestration modules.

## Preserved assets

- `data/knowledge_graphs/`.
- `data/knowledge_cards/`.
- `data/uploads/answers/`.
- child runtime code and UI.
- general model routing and non-question application infrastructure.

## New-path rule

The replacement implementation must use new v20 slot-job contracts and must not add compatibility flags for the retired batch workflow.
