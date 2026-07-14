# Handover — Player Triage App Spec v3 (Phase 02 complete)

Last updated: **2026-07-14**
Remote: **https://github.com/JordanTrpeski/player-triage-app-spec**
Branch: **main**
Most recent commit: **9572e81** — "Complete phase 02 ingestion, normalization, detection, redaction, linkage"

## Where the work stands

Three phases are done. Phase 03 is the next prompt to paste.

| Phase | Status | Commit | Report |
| --- | --- | --- | --- |
| 00 — Repository & policy audit | complete | `df38616` | [docs/phase_reports/phase_00.md](docs/phase_reports/phase_00.md) |
| 01 — Scaffold, config loaders, CLI skeleton | complete | `e003ccf` | [docs/phase_reports/phase_01.md](docs/phase_reports/phase_01.md) |
| 02 — Ingestion, normalization, detection, redaction, linkage | complete | `9572e81` | [docs/phase_reports/phase_02.md](docs/phase_reports/phase_02.md) |
| 03 — Deterministic policy engine & rules-only baseline | **not started** | — | prompt: [coding_runbook/prompts/03_rules_engine.md](coding_runbook/prompts/03_rules_engine.md) |
| 04–08 | not started | — | prompts under [coding_runbook/prompts/](coding_runbook/prompts/) |

## Setup on the new device

Prerequisites:

- **Python 3.12.x** (pinned; the project requires `>=3.12,<3.13`). Verify with `python --version`.
- `git`.
- Any OS. Development so far has been on Windows 11 with Git Bash + PowerShell; the code is portable.

Clone and bootstrap:

```bash
git clone https://github.com/JordanTrpeski/player-triage-app-spec.git
cd player-triage-app-spec

python -m venv .venv
# Windows:
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install --editable ".[dev]"
# macOS/Linux:
# .venv/bin/python -m pip install --upgrade pip
# .venv/bin/python -m pip install --editable ".[dev]"
```

If you need identical transitive versions to the ones I've been running, use the lock file:

```bash
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
.venv/Scripts/python.exe -m pip install --editable . --no-deps
```

## Verify the environment (should all pass on a clean clone)

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy --config-file pyproject.toml
.venv/Scripts/python.exe tools/validate_policy_package.py
.venv/Scripts/python.exe tools/validate_application_spec.py
.venv/Scripts/python.exe -m player_triage.cli validate-policy
.venv/Scripts/python.exe -m player_triage.cli ingest
```

Expected:

- `pytest`: **125 passed**.
- `mypy`: **Success: no issues found in 16 source files**.
- `tools/validate_policy_package.py`: `POLICY PACKAGE VALID`.
- `tools/validate_application_spec.py`: `APPLICATION SPEC VALID — NO MATERIAL CONTRACT GAPS DETECTED`.
- `validate-policy` CLI: reports 17 policy components + 14 schemas, ends `POLICY LOAD COMPLETE`.
- `ingest` CLI: 40 sanitized lines, ends `INGEST COMPLETE`; no player IDs and no fixture PAN/CVV strings in stdout.

If any of these fail on a fresh clone, treat it as a blocker before starting Phase 03 — regressions this early usually point at an environment mismatch (Python version, line endings, or a package that resolved to a different transitive version).

## Repository map

```
policy/           Frozen Stage-9 policy contract (immutable — see rules below)
schemas/          JSON Schemas (immutable)
input/            Authoritative dataset (CSV + XLSX, both 40 rows)
tools/            Pre-existing validators
coding_runbook/   Phase prompts + operating rules
docs/
  app/            Application requirements / architecture / UI / schema / export contracts
  phase_reports/  One report per completed phase
src/player_triage/
  __init__.py     Package version marker
  __main__.py     Enables `python -m player_triage`
  cli.py          Typer app: validate-policy, ingest, run/evaluate/demo/kill-switch (last four exit 2 until later phases wire them up)
  config.py       Typed loaders, ControlledVocabularies, AppConfig
  errors.py       Sanitized error hierarchy
  paths.py        App-root discovery (never uses os.getcwd)
  schema.py       Draft 2020-12 registry with cross-ref support
  records.py      Frozen dataclasses; only RawMessage carries player_id
  ingestion.py    CSV + XLSX loaders with strict validation
  normalization.py NFC + whitespace + line-ending; norm-1.0.0
  detection.py    Policy-driven detector engine (Luhn on PAN, prompt injection, etc.)
  redaction.py    Idempotent placeholder substitution + reference flags
  eligibility.py  Ingestion-level 6-state gate
  linkage.py      Same-player follow-up + shared-reference linkage
  overlays.py     Market overlay lookup
  pipeline.py     Phase 02 orchestrator → tuple[IngestedMessage, ...]
tests/            125 tests covering Phase 01 + Phase 02
pyproject.toml    Python >=3.12,<3.13; pinned direct deps; dev + local_model extras
requirements-lock.txt  Full transitive lock snapshot
.gitignore        Excludes .venv/, __pycache__/, .mypy_cache/, .pytest_cache/
```

## Operating rules that must be preserved

These live in [coding_runbook/agent_operating_rules.md](coding_runbook/agent_operating_rules.md). Summary of what has been most load-bearing in Phases 00–02:

1. **`policy/` and `schemas/` are immutable.** No implementation phase changes them. If a validator flags an objective serialization/reference defect, document a proposed minimal fix and stop for user approval instead of editing.
2. **Never echo raw player messages, PAN/CVV, identity numbers, OTPs, or player IDs** in chat output, logs, tests, or documentation. Tests that need positive coverage of a detector use synthetic content (e.g. the industry test PAN `4111 1111 1111 1111`), not dataset values.
3. **No external LLM APIs, no dataset upload.** Runtime is local/provider-independent. Internet is only for dependency install and official docs.
4. **Never implement real account/payment/KYC/self-exclusion/regulator/communication integrations.**
5. **One phase at a time.** Stop after each phase report; wait for the user to paste the next prompt.
6. **Fail closed.** Invalid input, redaction uncertainty, schema failure, or model outage routes to human/specialist fallback.

## Design invariants worth knowing on day 1

- **Enum single-source rule** — `policy/controlled_vocabularies.json` is the only place classification-decision catalogues (categories, intents, routes, priorities, teams, auto-response policies, template IDs) may be spelled out. `tests/test_no_enum_duplication.py` enforces this by scanning `src/player_triage/*.py`. Output catalogues that mechanically surface in ingestion/detection code (risk flags, eligibility states, bypass reasons, overlay codes) are exempted — see the docstring at the top of that test.
- **`player_id` boundary** — only `RawMessage` carries it. Every downstream type (`NormalizedMessage`, `DetectionResult`, `IngestedMessage`, `LinkageResult`, etc.) is player-ID-free by construction. If you add code that needs `player_id`, keep it inside `ingestion.py` or `linkage.py`.
- **Detection results carry counts and placeholders, never matched values.** Assertions and CLI output check ID + boolean + count only.
- **Redaction is idempotent** — `redact(redact(text)) == redact(text)`. A test enforces this on synthetic content and on every one of the 40 real records.
- **App root discovery is independent of cwd** — `resolve_app_root()` in `paths.py` walks up from the package directory or reads `PLAYER_TRIAGE_APP_ROOT`. Tests confirm the pipeline runs from a foreign cwd.
- **No network during ingestion** — `tests/test_no_network_and_sanitized.py` patches `socket.socket` and `socket.create_connection` to raise and asserts the full pipeline still completes.

## What Phase 03 is going to touch

Read [coding_runbook/prompts/03_rules_engine.md](coding_runbook/prompts/03_rules_engine.md) before starting. Expected additions (do **not** implement yet):

- A deterministic policy engine that consumes `policy/policy_rules.json` and `policy/baseline_intent_rules.json`.
- Applies the pre-model, terminal, locked rules (self-harm, PCI, prompt injection, underage, self-exclusion, …) that are already validated by Phase 02's detectors.
- Emits every field of `schemas/output_schema.json` — categories, intents, priorities, routes, teams, template IDs, reason codes, model_eligibility, bypass reasons, risk_flags, market overlays, related_message_ids, first_contact_message_id, previous_contact_count, market_applicability_note, short_rationale.
- Passes the 40 terminal outputs and all safety assertions in `policy/safety_assertions.json` (S01–S15).
- Runs in `rules_only` mode without any model. Adds `run` / `evaluate` behind those CLI commands.

The 125 existing tests must stay green. Phase 03 additions should extend the suite.

## Everyday commands

```bash
# From the repo root, with .venv activated (or using .venv/Scripts/python.exe explicitly):

# Configuration sanity
.venv/Scripts/python.exe -m player_triage.cli validate-policy

# Full Phase 02 pipeline preview (sanitized output)
.venv/Scripts/python.exe -m player_triage.cli ingest

# Full test suite
.venv/Scripts/python.exe -m pytest -q

# Static type check
.venv/Scripts/python.exe -m mypy --config-file pyproject.toml

# Existing package/application validators (pre-Phase-01)
.venv/Scripts/python.exe tools/validate_policy_package.py
.venv/Scripts/python.exe tools/validate_application_spec.py
```

## What to do if something looks off

- **`pytest` fails on a fresh clone** — the environment is probably not what the project targets. Check `python --version` is 3.12.x, delete `.venv`, and reinstall with `pip install --editable ".[dev]"`. If it still fails, use `pip install -r requirements-lock.txt` to force the exact transitive graph and reinstall the project with `--no-deps`.
- **`tools/validate_policy_package.py` fails** — treat this as a Phase 00 regression, not something to work around. Something in `policy/`, `schemas/`, or `input/` has been touched. Restore from git (`git status`, `git checkout -- <path>`) before doing anything else.
- **A new test wants to reference a real message** — do so by `msg_id` and boolean/enum/count only. Never paste subject/body/player_id/PAN/CVV values into test source.
- **You need to install a new package** — add it to `pyproject.toml` (runtime deps or `[project.optional-dependencies].dev`), reinstall, refresh `requirements-lock.txt` via `pip freeze --exclude-editable > requirements-lock.txt`, commit both files.

## Contact / provenance

- Frozen spec bundle version: **policy-3.0.0** (from `policy/configuration_manifest.json`).
- Assistant used to build Phases 00–02: Claude Code (Opus 4.7).
- All prior conversation context is captured in the phase reports; you don't need the chat transcript to continue.
