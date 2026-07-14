# Configuration and Audit Change Management

Active configuration is immutable. Every component file is hashed and referenced by a configuration version.

## State machine
`draft → validated → active → superseded` or `draft → rejected`.

## Atomic activation
- Validate all component schemas and references.
- Run semantic checks and behavioural fixtures.
- Run full regression and safety gates.
- Write version bundle and audit event.
- Update the active-version pointer atomically.
- On any failure, leave the previous active configuration unchanged.

## Rollback
Rollback creates a new activation event pointing to an earlier valid bundle; it does not delete history.

## SQLite tables
- `configuration_versions`
- `runs`
- `decisions`
- `audit_events`
- `human_overrides`
- `evaluation_summaries`

No table stores raw source body text.
