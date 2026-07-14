# Phase 05 — End-to-End Pipeline, Outputs, Audit and Overrides

Prerequisite: Phase 03 passes; Phase 04 may be enabled or deferred.

Read:
- `schemas/output_schema.json`
- `schemas/audit_event_schema.json`
- `policy/ground_truth_40.jsonl`
- `policy/controlled_vocabularies.json`
- `policy/auto_response_templates.json`

Implement:
- End-to-end batch orchestration with modes `rules_only`, `local_model`, and `mock_model`.
- One bounded retry for transient/model schema failure, then safe fallback.
- CSV operational output containing readable final fields only; no raw/redacted message text.
- JSONL audit events for decision, fallback, human override, configuration change and run summary.
- Human override command that appends an event and never overwrites the original decision.
- Sanitized exception handling; no request/body echo.
- Run IDs, event IDs and configuration versions.
- Model kill switch that leaves ingestion, redaction, deterministic rules, output and manual routing active.

Validation:
- Every result validates.
- Every audit line validates.
- Search CSV/JSONL for known M11 PAN/CVV fragments and fail if found.
- Verify M11/M23 model call counts are zero.
- Verify no raw message column is present.
- Generate outputs under `output/`.

Write `docs/phase_reports/phase_05.md` and stop.
