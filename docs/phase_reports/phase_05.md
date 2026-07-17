# Phase 05 Report

## Objective completed

Implemented the complete rules-only operational pipeline from validated CSV/XLSX ingestion through normalization, linkage, sensitive detection/redaction, eligibility, deterministic classification, final policy, market overlay, rationale, output/semantic validation, CSV, audit JSONL, and SQLite indexing.

The Phase 05 production/demo mode is restricted to `rules_only`. The effective runtime model state is disabled and rejected, and every successful supplied-40 decision records `model_called=false`. `llama-cpp-python` is not imported, model weights are not checked or required, and no hosted or local fallback is available to the Phase 05 command. The Phase 04 adapter and rejection evidence remain present for audit-only controlled experiments.

The accepted model conclusion is recorded in every run manifest as:

`model_rejected_no_material_improvement`

### Pipeline architecture

1. Load and hash the active `policy-3.3.1` configuration and input file.
2. Validate and ingest CSV/XLSX through the existing input adapter.
3. Normalize, link, detect/redact, and determine model eligibility.
4. Run the authoritative `TriageEngine` in `rules_only` mode.
5. Validate every successful decision against `output_schema.json` and semantic constraints.
6. Build schema-valid decision/error/summary audit events.
7. Write CSV, audit JSONL, and SQLite inside a hidden temporary run directory.
8. Flush and sync files, re-parse them, validate schemas/counts, run safety scans, calculate digests, and perform SQLite integrity checks.
9. Write the reproducibility manifest and atomically rename the completed run directory into place.

Configuration or integrity failures fail the run closed. An isolated classification failure can emit a sanitized `error_fallback` event and allow later messages to continue; no invalid decision is written as successful.

### Runtime mode and rejected-model handling

- Phase 05 mode: `rules_only` only.
- Effective model enabled: `false`.
- Effective model approval status: `rejected`.
- Model conclusion: `model_rejected_no_material_improvement`.
- Local/model mode passed to the Phase 05 controller: rejected before engine construction.
- Model runtime import during rules-only tests: zero.
- Model calls in the supplied-40 run: zero.
- The retained `model_configuration` component remains evaluation evidence and cannot activate the Phase 05 pipeline.

### Run identity and reproducibility

Each run uses a unique timestamp/UUID run ID and records:

- start and completion timestamps;
- application version;
- exact policy bundle version;
- every loaded component version;
- every manifest-recorded component SHA-256;
- input filename and SHA-256 without an absolute path;
- processing mode and effective model state/conclusion;
- message, success, failure and bypass counts;
- output artifact digests;
- canonical decision digest excluding run timestamps and IDs;
- processing duration.

This copies the exact activated component map into the run record rather than relying only on the mutable current-configuration pointer.

### Artifact formats

The successful run contains:

- `decisions.csv`: UTF-8 operational review view, one stable row per decision;
- `audit.jsonl`: one complete schema-valid audit event per line;
- `triage_audit.sqlite3`: approved structured audit/evaluation index;
- `run_manifest.json`: run identity, provenance, counts, canonical digest and artifact digests.

Arrays in CSV are serialized as semicolon-delimited controlled values; empty arrays become empty cells. CSV formula prefixes `=`, `+`, `-`, `@`, tab and carriage return are neutralized with a leading apostrophe. The CSV contains no source/redacted text or player identifier.

The authoritative 34-column CSV order is:

```text
message_id, received_utc, channel, market, language, category, intent,
priority, route, assigned_team, secondary_teams, auto_response_policy,
auto_response_template_id, human_review_required, risk_flags, reason_codes,
model_eligibility, model_called, model_bypass_reason, decision_basis,
market_framework_status, market_overlay_codes, related_message_ids,
first_contact_message_id, previous_contact_count, attachment_received,
attachment_referenced, identity_document_referenced, sensitive_data_types,
required_context, missing_context, decision_limited_by_missing_context,
processing_status, short_rationale
```

The complete output-schema decision, including secondary intents, market applicability note, policy basis, and all other required fields, is preserved in each JSONL `decision` event and SQLite decision record even where a field is not part of the readable CSV contract.

### Audit event coverage

The immutable audit schema permits only `decision`, `human_override`, `error_fallback`, `configuration_change`, `configuration_rollback`, and `run_summary`. Phase 05 therefore does not invent illegal event types for requested lifecycle labels such as `run_started` or `output_written`.

The successful supplied-40 stream contains:

- 40 `decision` events, each containing input metadata, decision path, triggered rule IDs, the complete final decision, validation controls, processing time, and component provenance;
- one `run_summary` event with counts, metrics, mismatch list, safety-gate result, latency and rates;
- zero error or override events because the run completed without failures or manual changes.

The controller supports schema-valid `error_fallback` events for isolated message failures and an `override` command that appends a `human_override` event. An override stores before/after schema-valid decisions and never updates the original decision row.

Run start/completion/output lifecycle state is recorded in the run manifest and `runs` table because those labels are not permitted audit event types.

### SQLite tables and indexes

The database is created from `docs/app/sqlite_schema.sql`, with foreign-key enforcement enabled for each write transaction. It contains only approved structured data in:

- `configuration_versions`;
- `runs`;
- `decisions`;
- `audit_events`;
- `human_overrides`;
- `evaluation_summaries`.

No table stores source/redacted text, player ID, detected values, model prompts/responses, attachment contents, or model paths.

In addition to primary-key auto-indexes, Phase 05 creates indexes for run configuration/start time, message ID, decision category/priority/team, and audit run/message/time/configuration. All SQL values use parameters. Writes use transactions; exceptions roll back and the temporary database is deleted. `PRAGMA integrity_check` must return `ok` before publication.

### Atomic-write design

Final-looking files are never written during processing. Each file is written to a collision-safe temporary name, flushed, synced, validated, hashed and atomically renamed. The entire run remains under `.<run_id>.tmp` until cross-artifact verification succeeds; the directory is then atomically promoted to `output/<run_id>`.

On failure, the temporary run directory is removed, an existing successful run is never overwritten, and a separate sanitized failure record is written where possible. Tests cover output-write failure, invalid-SQL/database rollback, temporary cleanup and digest tampering.

### Determinism and idempotency

Two independent rules-only executions produced identical decision tuples, byte-identical substantive CSV rows, equivalent JSONL decision objects, and the same canonical digest:

`a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b`

Run IDs, event IDs, timestamps, audit digests and SQLite file digests are intentionally run-specific. SQLite primary keys and collision-safe run directories prevent accidental duplicate insertion or overwrite. Existing redaction/detector idempotency tests remain green.

## Files added or changed

- Added `src/player_triage/operational.py`: Phase 05 batch controller, serializers, artifact verifier, SQLite writer and override service.
- Updated `src/player_triage/cli.py`: production `run` command and append-only `override` command.
- Added `tests/test_phase05_operational_pipeline.py`: focused Phase 05 operational tests.
- Updated `.gitignore`: generated `output/` runs remain local artifacts.
- Added `docs/phase_reports/phase_05.md`.

No policy or schema file was changed in Phase 05. Phase 04 files and rejection evidence remain available.

## Commands run

```text
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy src
.venv/Scripts/player-triage.exe validate-policy
.venv/Scripts/python.exe tools/validate_policy_package.py
.venv/Scripts/python.exe tools/validate_application_spec.py
.venv/Scripts/player-triage.exe evaluate --mode rules_only
.venv/Scripts/player-triage.exe run --mode rules_only
.venv/Scripts/python.exe -m pytest tests/test_phase05_operational_pipeline.py tests/test_no_network_and_sanitized.py tests/test_phase03_engine.py::test_runs_from_foreign_cwd tests/test_phase03_engine.py::test_no_network_during_classification tests/test_phase04_model_contract.py::test_optional_runtime_missing_is_sanitized -q
git diff --check
```

## Tests and results

- Complete suite: **331 passed**.
- Mypy: success across **38 source files**.
- Focused Phase 05 suite: **16 passed**.
- Explicit Phase 05/no-network/foreign-CWD/runtime-absent group: **22 passed**.
- Policy CLI: `policy-3.3.1` loaded with all components.
- Policy-package validator: `POLICY PACKAGE VALID`.
- Application-spec validator: `APPLICATION SPEC VALID — NO MATERIAL CONTRACT GAPS DETECTED`.
- Supplied-40 evaluation: 40/40 schema-valid; 15/15 safety gates.
- CSV parse/count/safety scan: passed, 40 rows and 34 columns.
- JSONL parse/schema/count/safety scan: passed, 41 events.
- SQLite integrity/count/index verification: passed, integrity `ok` and 16 total indexes including primary-key auto-indexes.
- Deterministic replay: identical canonical decisions, CSV substantive rows and JSONL decision objects.
- Rules-only no-network, foreign-CWD, optional-runtime-absent and zero-runtime-import tests: passed.

### Supplied-40 result

| Metric | Result |
|---|---:|
| input rows | 40 |
| successful decisions | 40 |
| failed messages | 0 |
| schema-valid decisions | 40/40 |
| classified status | 40/40 |
| deterministic/model bypass decisions | 9 |
| model calls | 0 |
| category agreement | 40/40 |
| intent agreement | 39/40 |
| priority agreement | 40/40 |
| route agreement | 40/40 |
| assigned-team agreement | 40/40 |
| safety gates | 15/15 |

The only mismatch is unchanged from the accepted rules-only baseline:

- M22 `intent`: expected `withdrawal_delay`; actual `withdrawal_status_first_contact`.

Required safety checks passed: M11 contains only structured exposure indicators and no detected values; M18 remains `bypass_untrusted_input`; M23 remains explicit self-exclusion with zero model calls; M31 retains linkage to M09; and M38 retains identity-document reference metadata without attachment processing.

### Final output artifacts

Run ID: `run-20260717T091215441Z-4553a1c94f93`

Run directory: `output/run-20260717T091215441Z-4553a1c94f93/`

| Artifact | SHA-256 |
|---|---|
| `decisions.csv` | `17174eef01ccd65b73472cedb64aa095bfcfa81db045729030f8c54658fc08a6` |
| `audit.jsonl` | `1338f4ed0d8d43ba7e24d6146fb65376a9fcf7fc60048f71d4f744e3433ff558` |
| `triage_audit.sqlite3` | `88577aa55a999d07906952547ec1ca584f641cbf65a8a668dd0e20f559102b28` |
| `run_manifest.json` | `e6354d4f8496aaa1c7f24d1200e71de7ce6819815dc0bf6dd13bc70dee6c992f` |

Input SHA-256: `27e7fce351477dcf25d146706e5826de003278cc154171627e7bf3575e34ec73`.

Application version: `0.1.0`; policy bundle: `policy-3.3.1`; recorded processing duration: 460 ms.

### Safety scan result

Automated verification found:

- no forbidden source or redacted text fields;
- no player identifier values;
- no known sensitive fixture values or configured forbidden patterns;
- no raw attachment names/content;
- no absolute developer-machine paths;
- no model artifact path or model prompt/response;
- no unvalidated enum or malformed JSONL object;
- no decision with `model_called=true`.

## Policy/schema deviations

none

The requested granular lifecycle labels were not added as audit event types because `audit_event_schema.json` forbids them. Their required state is captured by the run manifest and approved structured records, so this is contract conformance rather than a schema deviation.

## Known limitations

- Strict malformed CSV/XLSX structure fails the batch closed at ingestion; once ingestion succeeds, isolated classification failures may continue safely.
- Audit lifecycle granularity is limited to the six immutable schema event types.
- SQLite follows the authoritative six-table definition; expanded artifact-digest and component-map provenance lives in `run_manifest.json` rather than an unapproved new table.
- Human override authorization is represented by the CLI boundary and audit actor metadata; enterprise identity/RBAC integration is intentionally absent.
- The model remains rejected. Phase 05 does not attempt model tuning, alternate model evaluation or runtime activation.
- No email delivery, ticket assignment, account/payment/KYC/self-exclusion action, external integration, UI, Streamlit or Policy Studio was implemented.

## Manual review points

- Review the unchanged M22 intent mismatch before any future policy correction; ground truth was not modified.
- Treat the nine bypass outcomes as intentional deterministic/privacy controls, not processing failures.
- Keep the Phase 05 effective model approval status rejected unless a future governed phase evaluates and accepts a different candidate against non-compensatory gates.
- Human override inputs must remain complete schema-valid sanitized decisions and must use an approved override reason.

## Exact next-phase prerequisites

1. User explicitly accepts Phase 05 and authorizes only the next runbook phase.
2. Preserve `policy-3.3.1`, the Phase 04 rejection conclusion, and rules-only production default.
3. Treat the Phase 05 run manifest, audit JSONL and SQLite index as read-only sources for any Phase 06 evaluation UI.
4. Do not enable the rejected model or add external actions/integrations without a separate governed instruction.

Recommendation for Phase 06: build only the explicitly requested evaluation/review surface over these sanitized artifacts, preserving append-only overrides and keeping raw/redacted message data outside the UI boundary.

## Stop statement

This phase is complete. No work from the next phase was started.
