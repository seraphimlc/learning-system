# Domain Index Runtime Template

Use domain indexes as route maps for models. They are not architecture essays and not source-of-truth facts.

## Creation Contract

Create or update a domain index when a task touches a stable area with code/API/page/task/data/export validation routes.

Use one file per domain:

```text
docs/domain-index/<domain>.md
```

## Required Shape

```markdown
# Domain Index: <Name>

## Scope
What this domain covers and excludes.

## Current Contract
Current behavior or business contract in short bullets.

## Key Entrypoints
Code/API/page/task/data paths.

## Key Flows
Producer -> state/data -> consumer routes.

## Related Docs
PRD, review, QA, runbook, mapping, or platform-rule docs.

## Validation Entrypoints
Commands, page paths, API calls, sample requirements.

## Search Hints
Stable symbols, route names, statuses, template/category keys.

## Maintenance Rules
When this index must be updated.
```

## Writing Rules

You must:

- write paths and symbols, not long explanations
- keep each domain index small enough to read during startup
- link to longer docs instead of copying them
- mark stale or unknown facts explicitly

You must not:

- paste long logs
- paste full generated data
- duplicate source code
- store secrets or credentials
- use the index as proof of behavior

## Update Triggers

Update the relevant domain index when changing:

- public route or page
- API endpoint or schema
- task state or worker behavior
- DB table or important field
- export/import/template path
- external-platform contract
- validation command
