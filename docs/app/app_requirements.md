# Application Requirements — Frozen v3.0

## Required user outcomes
1. Load the supplied XLSX or canonical CSV and show a 40-record intake summary.
2. Process every message to one of eight fixed categories, one of four priorities, one route, and an assigned team.
3. Detect/redact prohibited values locally before any model call; raw attachments never enter the model path.
4. Execute deterministic safety rules before semantic classification and prohibit model downgrade of safety outcomes.
5. Optionally use a local model only for eligible ambiguous text; rules-only mode remains fully functional.
6. Apply market overlays without replacing the underlying support category.
7. Link repeat contacts locally and preserve first-contact context.
8. Produce a readable CSV, structured JSONL audit events, evaluation summary, mismatch report, and configuration-change history.
9. Permit human correction without overwriting the original decision.
10. Permit safe configuration changes through the UI with draft, validation, impact preview, activation, audit, and rollback.

## Required application modes
- `rules_only`: mandatory and deterministic baseline.
- `local_model`: optional adapter, never required for safe operation.
- `model_disabled`: kill-switch mode; deterministic processing and manual fallback continue.

## Required failure behavior
Input validation, redaction uncertainty, schema failure, semantic failure, model timeout/unavailability, and unsupported language must create an explicit fallback event and route to human/specialist review. No failure may default to low priority or auto-response.

## Required privacy behavior
Operational outputs and UI default views must not contain raw body text, player IDs, PAN/CVV, authentication secrets, full transaction references, identity-document values, or attachment content. The UI may show a redacted preview only.

## Out of scope
No account actions, payments, refunds, self-exclusion execution, fraud determination, identity verification, regulator reporting, email sending, attachment OCR, malware scanning, or external hosted LLM calls.
