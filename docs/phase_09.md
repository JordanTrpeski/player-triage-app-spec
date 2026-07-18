# Phase 09 — Import, Usability, Launch and Audit Infrastructure

Branch: `feature/phase09-import-and-usability`
Baseline: `70f3eca` (Phase 08: final documentation and submission package)
Runtime: `rules_only` · Policy: `policy-3.3.1` (unchanged) · Model calls: 0

This phase covers ingestion, usability, launch and audit infrastructure only. It
does not change classification outcomes, controlled vocabularies, priority
rules, routing, team assignment, redaction, sensitive-data handling,
auto-response eligibility, model eligibility, safety gates, accepted ground
truth, or policy-3.3.1.

---

## 1. Baseline reproduction on a clean machine

The accepted baseline was reproduced from the Git remote on a clean Windows 11
machine with Python 3.12.10 and a fresh virtual environment. No environment was
copied from another machine, and no local-model runtime was installed.

| Gate | Result |
| --- | --- |
| Supplied-40 processed | 40/40, 0 failures, 9 bypass |
| Canonical decision digest | `a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b` — exact match |
| Category agreement | 40/40 |
| Intent agreement | 39/40 |
| Documented mismatch | M22 `expected=withdrawal_delay actual=withdrawal_status_first_contact` |
| Safety gates | 15/15 passed, locked 26/26 |
| Policy validator | `POLICY PACKAGE VALID` |
| Application validator | `APPLICATION SPEC VALID` |
| mypy | Clean, 52 source files |
| Runtime | `rules_only`, `model_enabled: false`, `model_approval_status: rejected` |
| Local-model runtime | `llama-cpp-python` absent; no `llama*` module imported by pipeline, engine, CLI or UI |
| Accepted archive | `5f6bc727191c573336068d75621bd7f50ce684ec3a814208db3fd36008a01f0a` — unchanged |

Holdouts also reproduced: holdout-v1 category 22/25, intent 21/25;
holdout-v2 category 18/18, intent 18/18.

---

## 2. Line-ending incident (repository-hardening finding)

### 2.1 Symptom

On the first clean clone the suite reported **41 failed, 92 passed, 221 errors**,
and `tools/validate_application_spec.py` reported:

```
ERROR: configuration hash mismatch research_traceability.json
ERROR: configuration hash mismatch ui_editability.json
```

### 2.2 Cause

The cloning machine had `core.autocrlf=true` and the repository had no
`.gitattributes`. Checkout rewrote LF to CRLF in the hashed configuration
files, changing their SHA-256 values. `policy/configuration_manifest.json` pins
those digests, so hash verification failed and the dependent tests errored.

Confirmed by re-hashing `policy/research_traceability.json` with LF
normalization, which produced
`5e73896ca53855217f208659ee1ef703502db6938bac5a5eea1ef4004e98b717` — the exact
value pinned in the manifest.

### 2.3 Repair procedure (important)

`git config core.autocrlf false` followed by `git reset --hard HEAD` **did not
repair the working tree.** Git's stat cache still considered the CRLF files
unchanged, so `reset --hard` was a no-op: `git status` reported a clean tree
while the files on disk still contained CRLF and still hashed incorrectly.
`git update-index --really-refresh` also failed to dislodge the stale entries.

The index was correct throughout (the LF blob was present); only the worktree
was stale. The working repair was to delete the tracked files and check them
out again:

```powershell
git config core.autocrlf false
git ls-files | ForEach-Object { Remove-Item -LiteralPath $_ -Force -ErrorAction SilentlyContinue }
git checkout -- .
```

This is lossless when the tree has no uncommitted changes. Anyone who hits the
hash-mismatch symptom should expect `git reset --hard` alone to appear to
succeed while fixing nothing.

### 2.4 The accepted baseline is not uniformly LF

While adding `.gitattributes`, `git add --renormalize .` staged content changes
to 15 tracked files. Those files were committed with **CRLF or mixed** line
endings in the accepted baseline, and several are hash-pinned by policy-3.3.1:

| File | Endings | Pinned digest |
| --- | --- | --- |
| `policy/policy_rules.json` | mixed, 738 CRLF pairs | `9be9d0e4bd3192b1…` |
| `policy/redaction_policy.json` | CRLF, 220 pairs | `a26042459a4ff56b…` |
| `policy/baseline_intent_rules.json` | CRLF, 424 pairs | `bec1e6382f0dfe85…` |
| `policy/configuration_manifest.json` | mixed | (the manifest itself) |
| `policy/config_versions/policy-3.0.0/configuration_manifest.json` | CRLF | archived |
| `policy/config_versions/policy-3.2.0/configuration_manifest.json` | CRLF | archived |
| `policy/config_versions/policy-3.2.0/policy_rules.json` | CRLF | archived |
| `policy/config_versions/policy-3.2.0/redaction_policy.json` | CRLF | archived |
| `policy/config_versions/policy-3.2.0/baseline_intent_rules.json` | CRLF | archived |
| `submission/SUBMISSION_MANIFEST.json` | CRLF | accepted submission |
| `submission/phase_reports/phase_00.md` | CRLF | — |
| `submission/phase_reports/phase_02.md` | CRLF | — |
| `docs/phase_reports/phase_00.md` | CRLF | — |
| `docs/phase_reports/phase_02.md` | CRLF | — |
| `src/player_triage/engine.py` | CRLF | — |

The pinned digests are computed over those exact CRLF bytes. Normalizing these
files to LF would change policy-3.3.1 component digests, which is prohibited.

**Consequence for `.gitattributes`:** a blanket `* text=auto eol=lf` is unsafe
here. It leaves all 15 files permanently reported as modified (Git compares the
LF-cleaned worktree against the CRLF blob), which breaks the clean-tree gate,
and any subsequent `git add` would silently strip the CRs and change
policy-3.3.1 hashes.

These files are therefore pinned with `-text`, which disables conversion in
both directions and preserves their accepted bytes on every platform. Ordinary
tracked text is normalized to LF as intended. The `-text` rules appear **last**
in `.gitattributes`, because the last matching rule wins and they must override
the extension globs above them.

Re-verify the list at any time with:

```powershell
git ls-files --eol | Select-String "i/crlf|i/mixed"
```

### 2.5 Validation on a genuinely fresh checkout

Validated against a new clone taken with the hostile setting, not against the
already-repaired working tree:

```powershell
git -c core.autocrlf=true clone --branch feature/phase09-import-and-usability <repo> <fresh>
```

Results:

- clone reports a clean tree;
- **all 256 tracked files are byte-for-byte identical** (SHA-256) to the
  repaired baseline;
- `tools/validate_policy_package.py` → `POLICY PACKAGE VALID`;
- `tools/validate_application_spec.py` → `APPLICATION SPEC VALID`.

Windows launcher extensions (`.bat`, `.cmd`, `.ps1`, `.psm1`, `.psd1`) are
declared `text eol=crlf`. No pre-existing blobs use those extensions, so the
declaration is safe. Binary formats (`.zip`, `.xlsx`, `.docx`, `.pdf`, `.png`,
`.jpg`, `.sqlite3`, `.gguf`, `.whl`, and others) are declared `binary`.

---

## 3. Model-governance test correction

### 3.1 The original failure

The accepted commit contained one environment-dependent assertion in
`tests/test_phase04_model_governance.py`:

```python
def test_default_model_reference_resolves_outside_repository(app_root: Path) -> None:
    ...
    assert path.is_file()
```

On a clean machine this failed:

```
assert path.is_file()
+ where is_file = WindowsPath('C:/Users/<user>/.player-triage/models/qwen2.5-0.5b-instruct-q4_k_m.gguf').is_file
```

The assertion required a **rejected** evaluation artifact to be physically
staged on the workstation. It therefore contradicted the approved rules-only
runtime and the release gate that no local model is installed or imported
during ordinary setup. The accepted "354 tests passed" figure was recorded on a
machine that still had the rejected GGUF staged locally.

All runtime, policy, digest and safety gates otherwise reproduced exactly. This
was a test/handover portability defect, **not** an engine regression.

### 3.2 The correction

The test now verifies the property named in its title — governance of the model
*reference*, not the state of the workstation:

1. the reference resolves to an absolute path;
2. it carries the expected `.gguf` suffix;
3. it resolves outside the application repository (`app_root not in
   path.parents` and `not path.is_relative_to(app_root)`);
4. resolving it imports no local-model runtime module (asserted by diffing
   `sys.modules` across the call).

The unconditional `assert path.is_file()` was removed and was **not** replaced
by anything that downloads, creates or stages a model.

Artifact presence is now covered by a separate optional test,
`test_referenced_model_artifact_is_present_when_local_model_is_configured`,
marked `@pytest.mark.local_model`. It is excluded from the default suite via
`addopts = "-ra -m 'not local_model'"` in `pyproject.toml` and skips with an
explicit reason when the artifact is absent. Run it deliberately with
`pytest -m local_model`.

This is a test portability correction. It is not a policy change, not a
classifier change, not a model reactivation, and not a weakening of any safety
gate. No application behavior or policy decision changed — the canonical digest
was re-verified as identical after the correction.

### 3.3 Recorded results

| Stage | Result |
| --- | --- |
| Pre-correction (clean machine) | **353 passed, 1 failed** (environment-dependent model-artifact assertion) |
| Post-correction (default suite) | **354 passed, 1 deselected** |
| Post-correction (`-m local_model`) | **1 skipped, 354 deselected** — artifact not staged |

Post-correction: mypy clean (52 files), both validators pass, canonical digest
`a90de550…f70a62b` unchanged, `llama-cpp-python` absent, zero model calls.

---

## 4. Output-directory containment — investigation

An earlier pre-flight note suggested the engine enforced an output-containment
boundary. **That reading was incorrect and is corrected here.**

`run_operational_pipeline` in `src/player_triage/operational.py` resolves the
output root as `Path(output_dir).resolve()` when supplied, falling back to
`<app_root>/output`. There is no containment check: an arbitrary external
destination is accepted today, and a run to a path outside the repository
completes successfully with the canonical digest unchanged.

The earlier `[output_write_failure]` was an `OSError` from `mkdir` caused by the
8.3 short-name form of the supplied temporary path (`JORDAN~1.TRP`), not by any
policy or containment rule. The same run to an equivalent long-form path
succeeded.

Findings against the questions raised:

- **Is containment intentional?** No containment currently exists. Nothing in
  the repository documents one. Introducing it is a new restriction, not the
  preservation of an existing boundary.
- **Approved output root:** `<app_root>/output/`, which is git-ignored.
- **Traversal/symlink protections:** none present at the output layer.
- **Behavior when the root is unwritable:** fails closed with
  `[output_write_failure] operational run failed closed; see sanitized failure
  record`, with the underlying `OSError` sanitized out.
- **Behavior when a run directory already exists:** run directories are keyed by
  `run_id` (`run-<UTC timestamp>-<random suffix>`), so collision is not
  currently reachable in practice.

Per the Phase 09 ruling, run isolation will be implemented **inside** an
approved application-owned root (`output/imported_runs/<run_id>/`), and
path-containment validation will be added rather than weakened. Because
accepting arbitrary destinations is existing behavior rather than an existing
boundary, restricting it is a behavior change to `run --output-dir` and is
recorded here as such.

---

## 5. Descoped and pending items

### 5.1 Synthetic-consistency v2 (descoped)

> Corrected synthetic-consistency v2 artifacts were not present in the accepted
> Git repository or any available remote branch on the clean machine. Phase 09
> therefore did not use or recreate them. The supplied-40 baseline, official
> safety gates, existing holdouts and the full regression suite remain the
> release gates for this phase.

Confirmed absent from every commit reachable from `--all` and from the only
remote branch (`origin/main`):
`synthetic_consistency_expectations_v2.json`,
`synthetic_consistency_expectations_v2.csv`, `synthetic_fixture_audit.json`,
`synthetic_comparison_v2.json`, `compare_synthetic_results_v2.py`.

The only `v2` files in the repository are unrelated:
`tests/data/holdout_v2.json`, `tests/data/phase04_semantic_holdout_v2.json`,
`tests/test_phase03d_holdout_v2.py`.

If the originals are later transferred they may be validated separately. Phase
09 does not depend on them.

### 5.2 Decision-log documents (pending external artifacts)

Packaging prerequisites, not implementation blockers. Not recreated:

- `Player_Contact_Triage_Decision_Log_Simple_2_Page.pdf`
- `Player_Contact_Triage_Decision_Log_Simple_2_Page.docx`
- `Player_Contact_Triage_Audit_Decision_Log.pdf`
- `Player_Contact_Triage_Audit_Decision_Log.docx`

The repository's `docs/decision_log_outline.md` and
`submission/DECISION_LOG.md` are different artifacts and are not substitutes.
These four will be transferred separately before final submission packaging.
The accepted submission archive has not been rebuilt.

### 5.3 Dependency lock discrepancy (resolved)

**The defect.** `requirements-lock.txt` pinned `llama_cpp_python==0.3.34` — the
rejected local-model runtime — while **omitting Streamlit and its entire
transitive tree** (altair, pandas, pyarrow, tornado, pydeck, protobuf,
GitPython, requests, pillow, blinker, cachetools, narwhals, tenacity, toml,
watchdog). An environment built from it therefore had no operator console while
still carrying the rejected inference runtime — the exact inverse of the
approved delivery shape. Its `packaging==26.2` and `rich==15.0.0` pins also
differ from the versions pyproject.toml resolves (`packaging==24.2`,
`rich==13.9.4`), so it did not describe the environment that produced the
accepted results. It appears to predate the Phase 07 console work.

**The resolution.** Three explicit locks now replace it:

| File | Purpose | Contains llama-cpp-python |
| --- | --- | --- |
| `requirements-rules-only.lock` | the delivered rules_only runtime: CLI, Streamlit UI, CSV import, XLSX import, validation | No |
| `requirements-dev.lock` | rules-only runtime + pytest + mypy (release suite) | No |
| `requirements-local-model.lock` | optional, deliberate reconstruction of the rejected model environment | Yes — opt-in only |

`requirements-lock.txt` is retained for audit continuity but is now
comment-only, so installing from it cannot reintroduce the defect. Its original
contents are preserved verbatim inside it. Historical references to it in the
Phase 01 reports remain accurate for that point in history.

Approved installation path (used by `setup_windows.ps1`):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-rules-only.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --editable .
```

No package versions were changed or upgraded. Every pin was captured from the
environment that reproduced the accepted canonical digest.

**Verification in fresh virtual environments.**

`requirements-rules-only.lock` (new venv, `--no-deps` package install):
streamlit 1.41.1, openpyxl, jsonschema and typer present; `llama-cpp-python`,
pytest and mypy absent; `POLICY LOAD COMPLETE`, `POLICY PACKAGE VALID`,
`APPLICATION SPEC VALID`; supplied-40 run reproduced digest
`a90de550…f70a62b`; importing `streamlit`, `player_triage.ui.app` and
`player_triage.cli` loaded no `llama*` module.

`requirements-dev.lock` (separate new venv): **354 passed, 1 deselected**;
mypy clean, 52 source files; `llama-cpp-python` absent.

---

## 6. Identifier model

Two separate contracts.

**Supplied-40 benchmark — unchanged.** `msg_id` matching `^M\d{2}$`, its ground
truth, its policy validators, its semantic-evaluation generation and its
canonical digest. The fact that it retains two-digit identifiers is not a
defect.

**Imported datasets.** `source_message_id` matching `^M[0-9]{1,9}$`, with
`case_ref` per accepted row and `run_id` per batch. Supplied text is preserved
exactly; `M1`, `M01` and `M001` remain distinct and are never re-padded.

Ordering is numeric value first, then exact text as a stable tie-break, so `M2`
precedes `M10` and `M001` precedes `M01` precedes `M1`. That tie-break is
**deterministic ordering, not semantic precedence** — it exists so repeated
runs agree, not to rank padded forms.

| Situation | Outcome |
| --- | --- |
| `M99` then `M99` | `duplicate_source_message_id` — always an error, every mode |
| `M99` then `M099`, default | `ambiguous_padded_id_collision` |
| `M99` then `M099`, `allow` | both accepted |
| `M1`, `M01`, `M001`, default | first accepted, other two rejected |

`collision_mode=allow` is opt-in and is not the console default.

Import reuses the benchmark's field validation exactly:
`ingestion._validate_and_build` takes an injectable `message_id_error` callable
whose default preserves supplied-40 behaviour, so imported and benchmark rows
cannot diverge on channel, market, language, player-id, length or timestamp
rules.

Invalid rows are reported as sanitized `ValidationIssue`s and never silently
dropped. Structural failures (missing or duplicated headers, empty workbook,
missing file) remain fatal, since no per-row result exists to report.

---

## 7. Imported-run isolation

```
output/imported_runs/<run_id>/
    decisions.csv
    audit.jsonl
    validation_errors.csv
    run_manifest.json
    processing_summary.json
```

The directory name is the internally generated `run_id` only. No uploaded
filename, source identifier, player identifier, subject or message content ever
becomes a path component. An uploaded name is sanitized to a display value for
the manifest and is never used as a path.

Work happens in an exclusive `.<run_id>.tmp` directory created with
`mkdir(exist_ok=False)` and renamed atomically into place. An existing
destination aborts the run: **runs are never overwritten.**

The manifest is written before processing begins and finalized after the output
files are closed, so an interrupted run leaves `started` on disk rather than a
truncated success. JSON manifests are written via temporary file plus
`os.replace`.

Status lifecycle: `started` → `completed` | `completed_with_errors` | `failed`.
A structural import failure records `failed` and still publishes the evidence
directory. A per-row operational failure fails only that row; already-processed
rows are preserved and the failure is reported.

Row accounting is asserted before publication:

```
rows_accepted + rows_rejected == rows_seen
rows_processed + rows_failed  == rows_accepted
```

### Application schemas

The imported schemas were initially derived programmatically from the accepted
schemas to reduce accidental structural divergence. That derivation is now
**enforced by `tests/test_phase09_schema_compatibility.py`**, which fails if the
imported and accepted contracts diverge — see §12 for the precise scope of what
that test does and does not guarantee.

The three schemas:

| Schema | Role |
| --- | --- |
| `imported_decision_schema.json` | engine-internal; identical to `output_schema.json` but with the wider identifier pattern |
| `imported_output_schema.json` | published record: `source_message_id`, `case_ref`, `run_id`, plus the existing decision fields |
| `imported_audit_event_schema.json` | imported-run audit correlation |

`schemas/output_schema.json`, `audit_event_schema.json`, the ground-truth
schemas, the policy schemas and policy-3.3.1 are **unmodified**. These are
application/input-schema additions, not policy changes. `TriageEngine` gained an
`output_schema_file` seam defaulting to the accepted contract, and
`pipeline.ingest_raw` was extracted so import reuses detection, redaction,
overlays and linkage unchanged.

### Deterministic digest

`imported_decision_digest` covers an explicit allow-list of substantive
decision fields (`DIGEST_FIELDS`) in numeric-aware canonical order. Timestamps,
`run_id`, `case_ref`, filesystem paths and durations are excluded, so repeating
a run over identical input reproduces the digest while a changed decision does
not. The supplied-40 canonical digest is computed by the separate, unchanged
`canonical_decision_digest` and remains `a90de550…f70a62b`.

---

## 8. Output-path ruling as implemented

`run --output-dir` still accepts an explicit external path. That behaviour is
unchanged and remains supported, since it predates Phase 09 and restricting it
would break an existing workflow.

The application-owned `output/imported_runs/<run_id>/` root is the default and
the **UI** boundary. The console never offers a server-side destination
chooser; copies leave via browser downloads. `ConsoleService.read_import_artifact`
additionally restricts reads by an allow-list of filenames and a `run_id` shape
check before any path join.

---

## 9. Setup, launch and console

`setup_windows.ps1` (with `setup_windows.bat` for double-click) creates the
virtual environment, installs `requirements-rules-only.lock`, installs the
package with `--no-deps`, and health-checks runtime imports, local-model
absence, `validate-policy` and both validators. `-Dev` switches to
`requirements-dev.lock`; `-Force` recreates the environment.

Two PowerShell 5.1 specifics were found and handled: `pip show` writes to
stderr for a missing package, which surfaces as a `NativeCommandError` and
aborts the script under `$ErrorActionPreference='Stop'` — the local-model check
is therefore done in Python via `importlib.util.find_spec`.

`run_console.ps1` (with `run_console.bat`) launches the Streamlit console. It
switches to the repository root, because **Streamlit only reads
`.streamlit/config.toml` from the working directory**: launched from elsewhere
it silently discarded the hardened settings, which was observed as usage
statistics being collected despite `gatherUsageStats = false`. The privacy- and
safety-relevant settings are now also passed explicitly on the command line.
Verified by launching the console and confirming HTTP 200 with the telemetry
message suppressed.

The console gains two pages. **Import** uploads a CSV or XLSX batch, offers the
opt-in padded-identifier toggle, shows row accounting, surfaces every rejected
row with sanitized explanations, and provides downloads. **Walkthrough** is a
six-step orientation for a first-time reviewer and is the default landing page;
it states the rules-only runtime, why there is no model, the accepted
benchmark, the imported-identifier model, what a run produces, and what the
prototype is not.

---

## 10. Status

All Phase 09 implementation items are complete: `.gitattributes` hardening,
model-governance test portability fix, lock restructure, imported identifier
model, CSV/XLSX import with reported validation errors, batches over 99 rows,
run isolation and manifests, Windows setup and launcher, console Import and
Walkthrough pages, and documentation.

Deliberately not done: merge to `main`, and rebuilding the submission archive.

---

## 11. Final validation battery

| Gate | Result |
| --- | --- |
| Default rules-only suite | **450 passed, 1 deselected** |
| Optional `-m local_model` | **1 skipped** — artifact not staged (expected) |
| mypy | clean, 55 source files |
| `validate_policy_package.py` | `POLICY PACKAGE VALID` |
| `validate_application_spec.py` | `APPLICATION SPEC VALID` |
| `cli validate-policy` | `POLICY LOAD COMPLETE (expected policy-3.3.1)`, 19 schemas registered |
| Supplied-40 processed | `input=40 success=40 failure=0 bypass=9` |
| **Supplied-40 canonical digest** | **`a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b` — unchanged** |
| Category agreement | 40/40 |
| Intent agreement | 39/40, M22 the documented mismatch |
| Safety gates | 15/15 passed, locked 26/26 |
| policy-3.3.1 and accepted schemas | zero diff against `70f3eca` |
| Model calls | 0 |
| `llama-cpp-python` installed | No |
| Local-model import at startup | None — CLI, UI and imported-run modules load no `llama*` module |
| Accepted archive | `5f6bc727…a01f0a` — unchanged, not rebuilt |
| Clean Windows checkout reproduces hashes | Yes — hostile `core.autocrlf=true` clone, 256/256 files byte-identical, both validators pass |
| `M001`, `M99`, `M100` accepted on import | Yes |
| Batches over 99 rows | Yes — 120-row and 250-row batches covered |
| CSV and XLSX import | Yes, digest-equivalent |
| Invalid rows reported, not discarded | Yes — row accounting asserted before publication |
| Runs isolated, never overwritten | Yes |

### Test-count history, stated accurately

| Point | Result |
| --- | --- |
| Accepted baseline, clean machine, before correction | 353 passed, 1 environment-dependent failure |
| After the model-governance correction | 354 passed, 1 deselected |
| End of Phase 09 | 450 passed, 1 deselected |

Total collected is 451: 450 in the default rules-only suite plus one optional
`local_model` test. That optional test is **skipped**, never passed, on a
machine with no approved model artifact — which is the correct and expected
clean-machine outcome.

One pre-existing test was updated: `test_phase07_console.py` pinned the console
to exactly eight pages. Phase 09 adds Walkthrough and Import, so the expected
list was extended to ten and the test renamed. The list remains explicit rather
than counted, so any future page change stays reviewable.

### Closeout audit findings

Four items were identified during the closeout audit and corrected here. None
changed application behaviour.

1. **The earlier 256-file clone proof was stale.** It was taken at commit
   `2e13241`, when only `.gitattributes` had been added. The final branch has
   **273** tracked files. The proof was re-run against final HEAD `df2bef1`:
   hostile `core.autocrlf=true` clone, clean tree immediately after checkout,
   **273/273 files byte-identical**, both validators passing, supplied-40 digest
   reproduced, `setup_windows.ps1` completing, launcher serving HTTP 200 with
   hardened settings active.

2. **The configured row limit was 100,000, not the approved 10,000.**
   `MAX_IMPORT_ROWS` had always been `100_000` and no document stated a limit at
   all. The audit reported the discrepancy without changing the value, since
   that would have been a behaviour change. **Subsequently corrected to
   `10_000`** on the approved requirement `max_batch_rows = 10,000`: exactly
   10,000 is accepted, 10,001 fails during loading before any classification,
   with `rows_processed = 0` and `model_calls = 0`. The value is pinned by a
   test and documented in `HANDOVER.md` §6.

3. **No automated schema-compatibility test existed.** The claim that the
   imported schemas "cannot structurally drift" was not enforced by anything.
   The wording was corrected first; **an enforcing test was subsequently added**
   (`tests/test_phase09_schema_compatibility.py`). See §12.

4. **Batch-size boundaries had no automated coverage.** Only 120- and 250-row
   cases existed. `tests/test_phase09_batch_sizes.py` now pins 1, 40, 99, 100
   and 101 rows end to end, the configured limit value, and the at-limit /
   over-limit paths (via a small stand-in limit, so the real code path is
   exercised in milliseconds rather than by generating an over-limit file).

## 12. Post-audit corrective patch

Four scoped corrections applied after the closeout audit. No classification or
policy behaviour changed; policy-3.3.1 and the accepted schemas remain
untouched.

### 12.1 Maximum import size corrected to 10,000

`MAX_IMPORT_ROWS` changed from `100_000` to the approved `10_000`. Exactly
10,000 rows is accepted; 10,001 fails during loading, before classification
begins, leaving `rows_processed = 0` and `model_calls = 0` with the sanitized
reason `imported file exceeds 10000 rows`. Documentation and tests updated to
match; the value is pinned by `test_configured_limit_is_the_approved_value`.

### 12.2 Import UI completed

| Feature | Implementation |
| --- | --- |
| Downloadable CSV template | Header row plus one synthetic example (`M1`, `P-00000`, "EXAMPLE ROW"). No real or sensitive data. Verified to round-trip through the importer. |
| Input preview | Sanitized filename, detected format, row count, detected columns, missing/unexpected column report, and the first few rows — **before** processing. Bodies are never shown; subjects truncate at 48 characters; `player_id` is not surfaced. Warns when the row count exceeds the limit. |
| Processing status | `st.status` panel stepping through validating file → creating run and processing N rows → writing outputs → completed/failed, so a 10,000-row run (~2 minutes) never looks frozen. |
| Recent runs | Manifest metadata only — run_id, status, times, sanitized source name, counts, policy version, digest prefix. Any listed run can be reopened and its artifacts re-downloaded through the existing allow-listed mechanism. Corrupt manifests are skipped rather than breaking the list. |

### 12.3 Column mapping — deliberate design decision

> Phase 09 uses a fixed import contract rather than user-defined column
> mapping. This reduces ambiguity, makes validation deterministic and provides a
> reproducible template for the live demonstration.

Recorded as a decision, not an omission. The nine-column contract and its
validation rules are documented in `HANDOVER.md` §6.

### 12.4 Schema-compatibility enforcement

`tests/test_phase09_schema_compatibility.py` enforces that:

- every accepted decision property survives into `imported_output_schema.json`,
  and no extra field appears there;
- `imported_decision_schema.json` matches the accepted property and required
  sets exactly;
- shared property definitions are identical once the legitimately widened
  identifier patterns are normalized — so a retyped or re-enumerated accepted
  field fails loudly;
- `source_message_id`, `case_ref` and `run_id` carry their imported-run
  definitions and are required;
- the accepted output, audit, ground-truth, policy, baseline, redaction and
  detection schemas still constrain identifiers to `^M\d{2}$` and have **not**
  been widened with the imported pattern or gained imported-run fields.

**Scope, stated precisely.** These tests enforce structural alignment between
the imported and accepted contracts, and prevent the accepted contract being
edited to accommodate imports. They cannot prevent someone deliberately editing
both sides together. Drift is detected, not made impossible.

Nested identifier references (`related_message_ids`,
`first_contact_message_id`) are legitimately widened in the imported schemas;
the comparison normalizes those patterns so that any *other* difference is
reported as drift.

---

### Two defects found and fixed during item 8-9 verification

1. **`setup_windows.ps1` aborted on a clean machine.** `pip show` writes to
   stderr when a package is absent; under Windows PowerShell 5.1 with
   `$ErrorActionPreference='Stop'` that surfaces as a `NativeCommandError` and
   killed the script at the local-model check — that is, the check for the
   *expected* state was fatal. Replaced with `importlib.util.find_spec`.

2. **The console silently discarded its hardened Streamlit configuration.**
   Streamlit reads `.streamlit/config.toml` from the working directory only, so
   launching from anywhere else dropped the local-only address, headless mode,
   XSRF protection, suppressed error details and disabled usage statistics.
   Observed directly: telemetry was being collected despite
   `gatherUsageStats = false`. The launcher now switches to the repository root
   and passes the privacy- and safety-relevant settings explicitly. Verified by
   launching the console (HTTP 200) and confirming the telemetry message is
   gone.
