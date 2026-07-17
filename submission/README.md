# Player Contact Triage — Submission

A local, provider-independent prototype that triages player-support messages into
a fixed taxonomy (8 categories, 4 priorities, 3 routes, named teams) using a
**deterministic rules-only engine**. An optional local LLM adapter was built and
evaluated, then **rejected** (`model_rejected_no_material_improvement`); the
shipped runtime is `rules_only` and never loads a model.

- **Active policy bundle:** `policy-3.3.1`
- **Runtime mode:** `rules_only` (model disabled; `model_called = false`)
- **Canonical decision digest (supplied 40):** `a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b`
- **Python:** 3.12.x
- **Supplied dataset:** 40/40 schema-valid decisions, 0 failures, 9 deterministic/privacy bypasses
- **Safety:** 15/15 official gates, 26/26 locked activation gates

This package is a **demonstration prototype**, not a production-proven, regulator-
approved, or fully-compliant system. Metrics below are *demonstration-set
agreement*, *synthetic-holdout* results and *local benchmarks* — not accuracy
guarantees.

---

## Fastest verified start (Windows PowerShell)

From a clean checkout, with Python 3.12 available:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --editable ".[dev]"

# 1. Validate the frozen configuration bundle (policy-3.3.1)
.\.venv\Scripts\python.exe -m player_triage.cli validate-policy

# 2. Process the supplied 40-message dataset -> CSV / JSONL / SQLite / audit
.\.venv\Scripts\python.exe -m player_triage.cli run --output-dir output

# 3. Run evaluation (metrics, safety gates, holdouts, performance)
.\.venv\Scripts\python.exe -m player_triage.cli evaluate --output-dir output --performance

# 4. Start the local-only control console (localhost, rules-only)
.\.venv\Scripts\python.exe -m player_triage.cli demo

# 5. Run the test suite
.\.venv\Scripts\python.exe -m pytest -q
```

Platform-neutral equivalents (macOS/Linux): replace `py -3.12 -m venv .venv` with
`python3.12 -m venv .venv` and `.\.venv\Scripts\python.exe` with
`.venv/bin/python`.

The optional local model is **not** required: rules-only works without
`llama-cpp-python` and without any GGUF file. No network is required after the
dependencies are installed. The console binds to `127.0.0.1` only.

> **Supplied dataset:** the raw 40-message input (`input/dataset_player_messages.csv`)
> is **not** included in this package because it contains raw player content. Place
> the reviewer-supplied dataset at `input/dataset_player_messages.csv`; its expected
> SHA-256 is recorded in `outputs/run_manifest.json → input_file_sha256`
> (`27e7fce351477dcf25d146706e5826de003278cc154171627e7bf3575e34ec73`). The
> sanitized decision outputs in `outputs/` require no raw data to review.

---

## Problem statement

Player-support messages must be triaged consistently and safely: routed to the
right team at the right priority, with high-risk cases (self-harm, self-exclusion,
underage, account takeover, exposed payment/authentication data, prompt injection)
handled deterministically and never auto-resolved, and with no raw sensitive data
leaving the local boundary. Target volume is ~900 messages/day.

## Architecture (selected)

Deterministic pipeline; the optional model is a *proposer only*, never the
authority. See `ARCHITECTURE.md` for the full data-flow diagram.

```
input CSV/XLSX
  -> validation (strict headers, enums, timestamps, player-id format)
  -> normalization + repeat-contact linkage (message-id only; no player-id in output)
  -> sensitive-data detection + redaction (PAN/CVV/auth-secret/OTP/identity/...)
  -> model-eligibility gate (bypass_sensitive / bypass_untrusted_input / bypass_attachment / redaction_uncertain / invalid)
  -> deterministic pre-model safety rules (terminal, locked)
  -> rules-only classification (scored baseline + derived refinements)   [optional model proposer sits here, currently DISABLED]
  -> deterministic final policy + market overlays
  -> output JSON Schema + semantic cross-field validation (fail closed)
  -> decisions.csv / decisions.jsonl / audit_events.jsonl / audit.sqlite3 / run_manifest.json
  -> local control console (Streamlit, localhost only)
```

### Why rules-only was selected
The deterministic engine already meets every official safety gate (15/15) and
produces 40/40 schema-valid decisions with stable, auditable behaviour (a fixed
canonical digest). It is fast (~22 messages/second locally), fully reproducible,
requires no model download, and its decisions are explainable from policy rule
IDs. Safety-critical outcomes (priority, route, team, human review, bypasses,
market overlays) are never delegated to a model.

### Why the local model was evaluated and rejected
Phase 04 built a provider-independent adapter and benchmarked a small permissive
local model (Qwen2.5-0.5B-Instruct GGUF q4_k_m, apache-2.0, CPU via
llama-cpp-python). On the independent semantic holdout the model did not
**meaningfully** improve intent classification over rules-only, added latency and
an install/provenance burden, and could not be allowed to change any safety
outcome. Conclusion: **`model_rejected_no_material_improvement`**. The adapter,
gate, governance and tests remain in the tree as evidence; the model is disabled
and never invoked (proven by no-call safety tests). See
`../docs/phase_reports/phase_04.md`.

## Application capabilities
- One-command processing of the supplied dataset to CSV/JSONL/SQLite + a signed
  run manifest with component and artifact digests.
- Evaluation: per-field agreement, mismatch report, 15 official safety gates, 26
  locked activation gates, holdout-v1/v2, performance and capacity estimates.
- Local operator console (8 pages): dashboard, messages, human review, Policy
  Studio (governed draft/validate/impact/activate/rollback), evaluation, audit
  explorer, configuration versions, settings.
- Governed configuration lifecycle: versioned bundles, hash-verified components,
  atomic activation and rollback, append-only human overrides, kill switch.

## Safety boundaries (what this system does NOT do)
- No hosted LLM API; the rejected local model is disabled and never initialized.
- No tools, browsing, retrieval, code execution, or attachment/OCR processing.
- No account, payment, KYC, fraud-confirmation, age/identity-verification,
  regulator, or self-exclusion **actions** — humans perform all operational
  actions.
- No raw message body, player identifier, or sensitive value (PAN/CVV/OTP/
  password/identity) is written to CSV, JSONL, SQLite, audit events, or the UI.
- Deterministic high-risk rules are terminal and locked; a model can never lower
  priority, human-review requirement, specialist routing, safety flags, or
  market restrictions.

## Outputs
A fresh accepted run is in `outputs/` (regenerate with the `run` command above):
- `decisions.csv`, `decisions.jsonl` — sanitized decisions (no raw/sensitive data)
- `audit_events.jsonl`, `audit.sqlite3` — append-only audit trail
- `run_manifest.json` — run id, policy version, component + artifact digests,
  input digest, canonical decision digest, counts, mode, `model_enabled=false`

Evaluation evidence is in `evaluation/` (see `evaluation/evaluation_summary.json`).

## Known limitations
- **M22 intent** is the one supplied-set core mismatch (a short multilingual
  delay-vs-first-contact distinction) and remains a semantic target; category,
  priority, route and team for M22 are correct. There are also **52 set-valued
  diagnostic differences** (secondary intents / risk-flag sets) that do not
  affect the scored fields or any safety gate.
- 40 supplied cases and synthetic holdouts do **not** establish production
  accuracy; a representative labelled evaluation is required before production.
- Non-English coverage is limited to added German/Spanish safety handling.
- Detection is conservative and is not complete DLP; injection detection is not
  claimed to be exhaustive.
- No persistence beyond the local SQLite audit, no delivery/integration, no
  authentication, no deployment infrastructure.

## Repository structure (source of truth)
This package documents and snapshots the repository. Source lives in the repo:
```
policy/            frozen policy bundle (policy-3.3.1) + config_versions archive
schemas/           JSON Schemas (output, candidate, component, audit, ...)
src/player_triage/ engine, detection, redaction, derived rules, evaluation, model adapter, UI
tests/             354 tests incl. safety no-call, holdouts, governance
docs/phase_reports phase_00 .. phase_08 reports
tools/             pre-existing policy-package and application-spec validators
```

## Troubleshooting
- **`llama-cpp-python` fails to build** — it is optional and not needed for
  rules-only. Skip it; install only `.[dev]`.
- **`validate-policy` reports a hash mismatch after a fresh Windows clone** — set
  `git config core.autocrlf false` then re-checkout; the policy component hashes
  are computed on LF bytes.
- **Streamlit not installed / cannot launch** — use the CLI `run` and `evaluate`
  commands and the artifacts in `outputs/`/`evaluation/`; see
  `walkthrough/WALKTHROUGH.md` for the non-UI fallback path.
- **One test fails on `test_missing_policy_directory`-style temp cleanup** — a
  Windows antivirus temp-dir lock artifact, not a code defect.
