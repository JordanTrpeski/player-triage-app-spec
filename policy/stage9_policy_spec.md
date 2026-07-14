# Stage 9 Application Policy Specification — Version 3.0

## Frozen decisions
- Exactly eight primary categories and four priorities.
- One normalized primary intent; security, attachment, language and market characteristics remain overlays or risk flags.
- Deterministic high-risk rules run before any model and cannot be downgraded.
- Prompt-injection detection bypasses the model in the prototype.
- The model is optional and may propose only semantic classification fields.
- Deterministic policy owns priority, route, team, auto-response and human-review decisions.
- Raw attachments are excluded; references to attachments are distinct from received files.
- Market overlays never replace the underlying support category.
- Human changes and policy changes are append-only, versioned and reversible.
- Short rationale is rendered from approved reason-code templates, not model prose.

See `docs/app/` for the complete application, UI, schema, export and change-management contracts.
