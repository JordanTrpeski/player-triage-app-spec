# Phase 07 Report

## Objective completed

Implemented the local Streamlit demonstration console, typed console services,
versioned configuration drafts, complete pre-activation impact analysis, atomic
activation, gate-checked rollback, append-only human corrections, audited model
kill switch and ephemeral synthetic Pattern Lab for the accepted rules-only
application.

Phase 07 stops at the local control-console boundary. No Phase 08 work, hosted
provider, n8n workflow, external integration, production authentication or
production deployment was added.

Final runtime state:

- active configuration: `policy-3.3.1`;
- active component-bundle digest:
  `7e1fb9067e3cb3ebf55be65a7e5f496d0f1a47d61e8ebca6a811a823c0d056ea`;
- runtime mode: `rules_only`;
- effective model calls: 0;
- model conclusion: rejected and unavailable for normal activation;
- canonical supplied-run digest:
  `a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b`.

## Local console

`player-triage demo` performs a fail-closed preflight and starts Streamlit on
`http://127.0.0.1:8501`. It requires a valid policy, a verified operational run,
evaluation safety evidence and effective `rules_only` settings. The command
does not import or initialize the optional model runtime. `--dry-run` validates
the same prerequisites without launching a server.

Streamlit analytics are disabled, headless mode is enabled, the bind address is
loopback-only, file watching is disabled and detailed error display is disabled.
The console has eight pages:

1. Dashboard: active provenance, run counts, rules-only status, official and
   locked gates, distributions and clearly labelled local benchmark figures.
2. Messages: structured decisions, complete approved filters, core mismatch and
   diagnostic-difference separation, triggered rules and audit provenance.
3. Human Review: required before/after preview and append-only structured human
   correction; machine decisions and ground truth remain immutable.
4. Policy Studio: read-only component inspection, governed draft workflow,
   complete impact evidence and Pattern Lab.
5. Evaluation: separate dataset results, M22 core mismatch, 52 diagnostic
   differences, gates, workload, audit reconstruction and safe downloads.
6. Audit Explorer: structured operational and control-event search.
7. Configuration Versions: active, superseded and draft records plus confirmed
   rollback to valid targets.
8. Settings: sanitized logical paths, rejected-model evidence and audited
   kill-switch control while deterministic processing remains active.

The console does not display raw subject/body text, player identifiers, detected
secret values, prompts, local model paths or model hashes. Application and output
locations are rendered as logical placeholders rather than absolute host paths.

## Service and control-plane boundaries

The UI consumes typed dataclasses and protocols in `console_contracts.py` through
the `ConsoleService` facade. UI code does not parse raw input or own evaluation,
activation, rollback or override semantics.

`ConfigurationManager` owns control state under ignored `output/control_console/`:

- immutable draft directories copied from the active configuration;
- per-draft metadata, validation evidence and impact evidence;
- immutable activated version directories;
- an atomically replaced active pointer;
- exclusive local operation locks;
- a schema-valid append-only control audit;
- rules-only kill-switch settings.

The repository `policy/` and `schemas/` trees were not modified. Active policy
files are never edited in place.

## Draft validation and impact analysis

Normal UI edits are limited to the declared editability contract. Static
rationale and approved template changes are supported; dynamic placeholders are
rejected. Guarded derived-rule and market-overlay fields use allowlists. Locked
rules, semantic constraints, critical redaction detectors and model configuration
cannot be changed through normal activation.

Every draft validation verifies schemas, component digests, semantic policy
loading, rejected-model safety and locked-component equality. Any edit invalidates
previous validation and impact evidence.

Impact analysis runs the active and candidate configurations independently on:

- `supplied-40`;
- `holdout-v1`;
- `holdout-v2`.

It reports field-level decision changes, priority and route/team movement,
auto-response, bypass and review changes, schema/semantic validity, introduced or
resolved mismatches, diagnostic changes, canonical digests, all 26 official and
locked gates and six candidate invariants. Candidate invariants are activation-
blocking rather than informational.

## Activation and rollback safety

Activation requires the literal confirmation `ACTIVATE`, current impact evidence,
matching draft identity, matching parent version/digest, unchanged candidate
digest, all locked gates, all candidate invariants and an allowed activation
recommendation. Stale drafts and stale or cross-draft evidence are rejected
without changing the active pointer. The final version is copied and renamed
before the pointer is atomically replaced.

Rollback requires the literal confirmation `ROLLBACK`. Before pointer replacement,
the target is loaded and all supplied/holdout regression datasets and 26 gates
are rerun. A target with any validation or regression failure is rejected and
audited. Successful rollback is atomic and audited.

The model/AI kill switch is a separate audited setting. Changing it never stops
deterministic processing and never changes effective mode from `rules_only`.

## Human corrections

Human Review accepts only controlled-vocabulary structured fields and an approved
override reason. Before append, the proposed complete decision is output-schema
validated, semantic-invariant validated and safety scanned. A successful
correction appends a `human_override` event and a new structured decision view,
updates SQLite and manifest metadata, and leaves the original decision and ground
truth intact.

## Pattern and redaction lab

Pattern Lab provides permanent synthetic fixtures for explicit and negated
self-exclusion, OTP disclosure and delivery failure, synthetic payment secrets,
prompt injection, benign instruction wording and German explicit/negated cases.
Ad hoc input is explicitly synthetic, limited to 1,000 characters and processed
through a temporary CSV that is deleted after the call. Results show detector
counts and placeholders, never matched sensitive values. They are not appended
to the operational audit. All cases use `rules_only` and make zero model calls.

## Required safe-change walkthrough

The final walkthrough started and ended on `policy-3.3.1`:

1. Created an immutable draft and changed only the static
   `BALANCE_RECONCILIATION` rationale.
2. Validation passed with zero locked changes.
3. Impact analysis passed 26/26 official+locked gates and 6/6 candidate
   invariants.
4. The preview reported exactly one decision change: M32 `short_rationale`.
5. Route, priority, bypass, auto-response and human-review changes were all zero;
   no mismatch or diagnostic regression was introduced.
6. Activated immutable version
   `policy-ui-20260717T115547528Z-f5ec1aab` and verified the active pointer and
   activation audit event.
7. Reran the supplied evaluation under the activated configuration and verified
   M32 contained the new static rationale.
8. Rolled back with full validation/regression checks and verified the original
   component-bundle digest exactly.

The live control audit contains the draft, validation, impact, activation and
rollback evidence. The final rollback event records `validation_passed=true`
and `regression_passed=true`. Separate isolated-state tests prove that a stale
draft is rejected and cannot change the active pointer.

## Validation record

Commands and checks executed:

```text
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy src
.venv/Scripts/player-triage.exe validate-policy
.venv/Scripts/python.exe tools/validate_policy_package.py
.venv/Scripts/python.exe tools/validate_application_spec.py
.venv/Scripts/player-triage.exe run --mode rules_only
.venv/Scripts/player-triage.exe evaluate --mode rules_only --safety-only
.venv/Scripts/player-triage.exe demo --dry-run
```

Results:

- complete suite: 354 passed;
- mypy: success across 52 source files;
- policy package: valid;
- application specification: valid with no material contract gaps;
- final replay: 40/40 successful, nine bypasses, zero model calls;
- canonical digest: unchanged;
- safety evaluation: 15/15 official and 26/26 official+locked gates;
- Streamlit application test: all eight pages rendered without exception;
- real startup smoke: loopback HTTP returned 200 and the process terminated
  cleanly;
- no-network, foreign-CWD, empty/corrupt-artifact and sensitive-output tests:
  passed;
- controlled-vocabulary duplication guard: passed;
- active configuration after walkthrough: accepted version and digest restored.

## Files added or changed for Phase 07

- Added `.streamlit/config.toml`.
- Added `console_contracts.py`, `console_service.py`,
  `configuration_manager.py` and `pattern_lab.py`.
- Added the `player_triage.ui` package with the eight-page Streamlit console.
- Implemented the `player-triage demo` preflight and local launcher.
- Added append-only structured override support to the operational service.
- Added `tests/test_phase07_console.py` and updated the CLI smoke test.
- Added this report.

Phase 06 files remain part of the same uncommitted working tree checkpoint.

## Known limitations

- This is a single-user local demonstration without authentication, RBAC,
  authorization separation or immutable external audit storage.
- The supplied messages and holdouts are synthetic assurance evidence, not
  production representativeness or production accuracy evidence.
- M22 remains the accepted core mismatch and 52 diagnostic set-valued
  differences remain visible.
- Streamlit session state is not a durable multi-user transaction system; all
  durable control state is instead owned by the configuration manager.
- Local file locks and atomic rename semantics are appropriate for this local
  prototype, not a distributed deployment.
- Backup/restore operations, disaster recovery, production monitoring, secrets
  management, enterprise identity and deployment hardening remain absent.
- The model remains rejected. No hosted-provider configuration or recommendation
  was introduced.

## Stop statement

Phase 07 is complete. The application remains local and rules-only. Phase 08 and
all external integrations were not started.
