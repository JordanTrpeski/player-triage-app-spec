# Schema and Logic Contract

## Schemas
- `detection_result_schema.json`: local detection/redaction output.
- `model_candidate_schema.json`: narrow semantic candidate; no route, priority, team or free-text rationale.
- `output_schema.json`: authoritative final triage decision.
- `audit_event_schema.json`: append-only lifecycle events using `$ref` to the authoritative decision schema.
- `config_bundle_schema.json`: immutable configuration version metadata.
- `evaluation_summary_schema.json`: run and regression results.

## Authority boundaries
- Model may propose only category, intent, secondary intents, signals, complaint indicator and ambiguity.
- Deterministic policy owns priority, route, teams, auto-response eligibility, market overlays, model bypass, and final human-review requirement.
- Rationale is generated from approved reason-code templates.
- JSON Schema checks structure; the semantic validator checks cross-field policy invariants.

## Invariants
See `policy/semantic_constraints.json`. Both the pipeline and UI activation workflow must call the same semantic validator.
