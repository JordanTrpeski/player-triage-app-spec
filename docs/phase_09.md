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

## 6. Status

Completed: baseline reproduction, `.gitattributes` hardening with fresh-clone
proof, and the model-governance test correction. Remaining Phase 09 items
(dependency path, imported identifiers, CSV/XLSX import, batches over 99 rows,
run isolation, Windows setup and launch, UI and walkthrough, documentation)
are in progress.
