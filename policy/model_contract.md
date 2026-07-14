# Local Semantic Classifier Contract

The local model is optional. It receives only locally redacted, model-eligible text and returns an object valid against `schemas/model_candidate_schema.json`.

It may propose:
- category
- primary intent
- secondary intents
- semantic signals
- complaint indicator
- ambiguity

It may not determine:
- priority, route, team, auto-response, market overlay, account action, payment action, fraud, age, identity or self-exclusion execution.

Prompt-injection flagged messages, sensitive-authentication cases, explicit high-risk deterministic cases and attachment-blocked cases never reach the model.

No chain-of-thought or free-form rationale is requested or stored. The application renders `short_rationale` from approved reason-code templates after deterministic policy finalization.
