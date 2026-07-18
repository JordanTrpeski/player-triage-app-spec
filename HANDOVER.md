# Handover — Player Contact Triage

Remote: **https://github.com/JordanTrpeski/player-triage-app-spec**

Current work: branch `feature/phase09-import-and-usability`, based on the
accepted baseline `70f3eca` (Phase 08).

> **Historical note.** Earlier revisions of this file described the Phase 02
> state (dated 2026-07-14, commit `9572e81`, "125 passed", "16 source files",
> `pip install -r requirements-lock.txt`). Those statements were accurate then
> and are preserved in `docs/phase_reports/phase_01.md` and
> `docs/phase_reports/phase_02.md`. They no longer describe this repository —
> do not follow them.

---

## 1. What this is

A local, provider-independent prototype that triages inbound player contacts.
Every decision is produced by deterministic rules.

| Property | Value |
| --- | --- |
| Runtime | `rules_only` |
| Active policy | `policy-3.3.1` |
| Model | evaluated in Phase 04 and **rejected** — disabled and unavailable |
| Expected model calls | **0** |
| Supplied-40 canonical digest | `a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b` |
| Accepted archive | `player-contact-triage-submission.zip`, SHA-256 `5f6bc727191c573336068d75621bd7f50ce684ec3a814208db3fd36008a01f0a` |

The application must run, and the full default test suite must pass, **without**
`llama-cpp-python` and **without** any GGUF artifact.

---

## 2. Clean-machine setup (Windows, PowerShell 5.1)

```powershell
git clone https://github.com/JordanTrpeski/player-triage-app-spec.git
cd player-triage-app-spec
.\setup_windows.ps1          # add -Dev for pytest + mypy
```

`setup_windows.ps1` creates `.venv`, installs the pinned rules-only lock,
installs the package with `--no-deps`, and runs a health check (runtime
imports, no local-model import, `validate-policy`, both validators).

### Line endings — read this before anything else

The configuration manifest pins SHA-256 digests over exact file bytes. A
Windows clone with `core.autocrlf=true` and no `.gitattributes` rewrites line
endings, every hashed configuration file changes hash, and you get
`configuration hash mismatch` plus hundreds of test errors.

`.gitattributes` now prevents this. If you meet the symptom on an older clone,
note that **`git reset --hard HEAD` does not fix it** — Git's stat cache treats
the files as unchanged, so the reset silently does nothing. The working repair:

```powershell
git config core.autocrlf false
git ls-files | ForEach-Object { Remove-Item -LiteralPath $_ -Force -ErrorAction SilentlyContinue }
git checkout -- .
```

Fifteen tracked files were committed with CRLF or mixed endings and several are
hash-pinned by policy-3.3.1. They are pinned `-text` and must not be
normalized. See `docs/phase_09.md` §2.

### Dependencies

| File | Use |
| --- | --- |
| `requirements-rules-only.lock` | the delivered runtime (CLI + Streamlit UI + CSV/XLSX import + validation) |
| `requirements-dev.lock` | rules-only + pytest + mypy |
| `requirements-local-model.lock` | **optional**, rejected local-model runtime — never for normal setup |
| `requirements-lock.txt` | **superseded**, comment-only, retained for audit |

The old `requirements-lock.txt` installed the rejected model runtime while
omitting Streamlit entirely; it could not reproduce the delivered application.

---

## 3. Simple launch

```powershell
.\run_console.ps1              # http://127.0.0.1:8501
.\run_console.ps1 -Port 8600 -NoBrowser
```

`run_console.bat` and `setup_windows.bat` are double-click wrappers.

The launcher switches to the repository root so `.streamlit/config.toml`
applies (local-only address, headless, XSRF protection, suppressed error
details, no usage statistics) and passes those settings explicitly as well.

---

## 4. Application entry points

| Entry point | Purpose |
| --- | --- |
| `python -m player_triage.cli` / `player-triage` | Typer CLI |
| `python -m player_triage` | same, via `__main__` |
| `src/player_triage/ui/app.py` | Streamlit console (launch via `run_console.ps1`) |

CLI commands: `validate-policy`, `ingest`, `run`, `override`, `evaluate`,
`evaluate-semantic`, `demo`, `kill-switch`.

Console pages: Walkthrough, Dashboard, Import, Messages, Human Review, Policy
Studio, Evaluation, Audit Explorer, Configuration Versions, Settings.

---

## 5. Identifier model

Two deliberately separate contracts.

**Supplied-40 benchmark — unchanged.** `msg_id` matching `^M\d{2}$` (M01–M40),
its own ground truth, its own policy validators, its own canonical digest.

**Imported datasets.** `source_message_id` matching `^M[0-9]{1,9}$`, plus
`case_ref` (per accepted row) and `run_id` (per batch). The supplied text is
preserved exactly — `M1`, `M01` and `M001` are three distinct identifiers and
are never re-padded.

Ordering is numeric-aware: numeric value first, then exact text as a stable
tie-break. `M2` sorts before `M10`; `M001` sorts before `M01` before `M1`. That
tie-break is **deterministic ordering, not semantic precedence**.

Within one batch:

| Situation | Outcome |
| --- | --- |
| `M99` then `M99` | `duplicate_source_message_id` (always an error) |
| `M99` then `M099`, default mode | `ambiguous_padded_id_collision` |
| `M99` then `M099`, `collision_mode=allow` | both accepted |
| `M1`, `M01`, `M001`, default mode | first accepted, other two rejected |

`collision_mode=allow` is opt-in; the console defaults to strict.

---

## 6. Import workflow

Console → **Import** → upload CSV or XLSX → optionally allow padded variants →
**Process batch**.

Invalid rows are **reported, never silently discarded**. Structural failures
(bad headers, empty workbook) fail the run rather than reporting per row.

Copies leave the machine via browser downloads. The operator never selects a
server-side destination.

### Fixed column contract

There is **no column mapping UI**. The importer requires exactly these nine
columns, by name, in the header row. Missing columns, duplicated columns and
unexpected extra columns are all rejected as structural failures.

| Column | Rule |
| --- | --- |
| `msg_id` | `^M[0-9]{1,9}$` for imports; preserved exactly |
| `received_utc` | ISO-8601; `Z` accepted; naive values treated as UTC |
| `channel` | `email` or `chat` |
| `market` | `Ontario`, `Malta`, `Ireland`, `India`, `New Zealand` |
| `player_id` | `^P-\d{5}$` |
| `vip_tier` | free text |
| `language` | non-empty, at most 12 characters |
| `subject` | at most 300 characters; subject and body cannot both be empty |
| `body` | at most 8,000 characters |

`input/dataset_player_messages.csv` is a valid example of this layout and can be
used as a reference template. **No downloadable template is offered in the UI.**

### Batch size limit

The configured maximum is **`MAX_IMPORT_ROWS = 100,000`** rows per file, defined
in `src/player_triage/import_ingestion.py`. Input above the limit fails during
loading, before any row is classified: the run is recorded as `failed`, no rows
are processed, and the manifest carries the sanitized reason
`imported file exceeds 100000 rows`.

Verified sizes: 1, 40, 99, 100, 101, 900, 1,000 and 10,000 rows all complete
with correct accounting and zero model calls; 100,001 rows fails before
processing. Approximate wall-clock on the development machine: 900 rows ≈ 11 s,
10,000 rows ≈ 121 s. Engineering evidence only — not a throughput guarantee.

---

## 7. Run isolation

```
output/imported_runs/<run_id>/
    decisions.csv
    audit.jsonl
    validation_errors.csv
    run_manifest.json
    processing_summary.json
```

The directory name is the internally generated `run_id` only — never the
uploaded filename, a source identifier, a player identifier or message content.
Work happens in an exclusive `.<run_id>.tmp` directory renamed atomically into
place; an existing destination aborts the run. **Runs are never overwritten.**

The manifest is written before processing and finalized after the output files
close, so an interrupted run leaves `started` rather than a false success.

Status: `started` → `completed` | `completed_with_errors` | `failed`.

Guaranteed before publication:

```
rows_accepted + rows_rejected == rows_seen
rows_processed + rows_failed  == rows_accepted
```

The imported decision digest covers substantive decision fields only —
timestamps, `run_id`, `case_ref`, paths and durations are excluded — so
repeating a run over identical input reproduces the digest.

### CLI output paths

`run --output-dir` still accepts an explicit external path; that behaviour is
unchanged and remains supported. The application-owned root is the default and
the UI boundary, not a new restriction on the CLI.

---

## 8. Validation commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q                                 # default rules-only suite
.\.venv\Scripts\python.exe -m pytest -q -m local_model -o addopts="-ra" # optional; skips without an artifact
.\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml
.\.venv\Scripts\python.exe tools\validate_policy_package.py
.\.venv\Scripts\python.exe tools\validate_application_spec.py
.\.venv\Scripts\python.exe -m player_triage.cli validate-policy
.\.venv\Scripts\python.exe -m player_triage.cli run --mode rules_only   # must print the canonical digest
.\.venv\Scripts\python.exe -m player_triage.cli evaluate
```

Expected: **450 passed, 1 deselected**; mypy clean across 55 source files;
`POLICY PACKAGE VALID`; `APPLICATION SPEC VALID`; 19 schemas registered;
supplied-40 `40/40 processed`, `category 40/40`, `intent 39/40` with M22 the
documented mismatch; safety gates `15/15` and locked `26/26`.

The one `local_model` test is **skipped**, not passed, when no artifact is
staged. That is the expected clean-machine result.

---

## 9. Known gaps

**Missing external artifacts — packaging prerequisites, not blockers.** Not
recreated; to be transferred before final packaging:

- `Player_Contact_Triage_Decision_Log_Simple_2_Page.pdf` / `.docx`
- `Player_Contact_Triage_Audit_Decision_Log.pdf` / `.docx`

`docs/decision_log_outline.md` and `submission/DECISION_LOG.md` are different
artifacts and are not substitutes.

**Synthetic-consistency v2 — descoped.** The corrected v2 artifacts
(`synthetic_consistency_expectations_v2.json` / `.csv`,
`synthetic_fixture_audit.json`, `synthetic_comparison_v2.json`,
`compare_synthetic_results_v2.py`) are not present in the accepted repository
or any available remote branch. Phase 09 did not use or recreate them. The
supplied-40 baseline, official safety gates, existing holdouts and the full
regression suite remain the release gates.

**Not rebuilt.** The accepted submission archive is untouched and must stay
that way until packaging is authorized.

---

## 10. Phase 09 status

Complete: `.gitattributes` hardening, model-governance test portability fix,
lock restructure, imported identifier model, CSV/XLSX import with reported
validation errors, batches over 99 rows, run isolation and manifests, Windows
setup and launcher, console Import and Walkthrough pages, documentation.

Deliberately not done: merge to `main`, submission archive rebuild.

Full detail, including incident records and the reasoning behind each decision,
is in `docs/phase_09.md`.
