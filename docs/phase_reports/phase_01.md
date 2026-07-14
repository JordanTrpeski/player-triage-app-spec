# Phase 01 Report

## Objective completed
Delivered the project scaffold and typed configuration loaders required by `coding_runbook/prompts/01_scaffold_and_config.md`, plus every additional requirement in the phase brief (Python 3.12 pin, reproducible dependency spec, runtime/optional-model separation, no local model, no policy edits, no cwd-relative loading, negative-path tests, sanitized errors). All Phase 01 unit tests, the pre-existing package/application validators, the `validate-policy` CLI, and mypy pass. No Phase 02 functionality was started.

## Files created or modified
Created:

- [pyproject.toml](pyproject.toml) — package metadata, Python `>=3.12,<3.13` pin, pinned runtime dependencies, `dev` and `local_model` optional-dependency groups, pytest and mypy config.
- [requirements-lock.txt](requirements-lock.txt) — resolved-transitive lockfile snapshot from the project virtualenv for auditability.
- [.gitignore](.gitignore) — excludes `.venv/`, `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`, build artefacts.
- [src/player_triage/__init__.py](src/player_triage/__init__.py) — package marker, exposes `__version__`.
- [src/player_triage/__main__.py](src/player_triage/__main__.py) — enables `python -m player_triage …`.
- [src/player_triage/paths.py](src/player_triage/paths.py) — deterministic app-root discovery (explicit arg → `PLAYER_TRIAGE_APP_ROOT` → walk up from the package directory; never `os.getcwd()`).
- [src/player_triage/errors.py](src/player_triage/errors.py) — `ConfigurationError` hierarchy with sanitized messages (component name + path hint only).
- [src/player_triage/schema.py](src/player_triage/schema.py) — Draft 2020-12 schema registry keyed by `$id`, cross-schema `$ref` resolvable through `referencing`.
- [src/player_triage/config.py](src/player_triage/config.py) — typed Pydantic models for `ConfigurationManifest` and `ControlledVocabularies`, generic per-component loaders, cross-component consistency checks, and the immutable `AppConfig` handle exposing every component's `version`, the manifest `version_id`, and the schema registry.
- [src/player_triage/cli.py](src/player_triage/cli.py) — Typer application with `validate-policy` (real work), `run`, `evaluate`, `demo`, `kill-switch` (all exit 2 with a "not implemented in Phase 01" message so downstream phases can wire them in without changing the surface).
- [tests/conftest.py](tests/conftest.py) — `app_root` fixture plus a `mutated_app_root` factory that copies `policy/`, `schemas/`, `input/` into a temp dir so negative-path tests never touch the authoritative bundle.
- [tests/test_happy_path.py](tests/test_happy_path.py) — every policy JSON loads via `AppConfig`; `AppConfig` is frozen; every shipped schema is registered.
- [tests/test_missing_files.py](tests/test_missing_files.py) — parametrised removal of each of the 18 mandatory policy files plus the whole `policy/` directory; each case must raise `MissingConfigurationError`.
- [tests/test_invalid_json.py](tests/test_invalid_json.py) — malformed JSON in `controlled_vocabularies.json` and `policy_rules.json` must raise `InvalidConfigurationError`.
- [tests/test_schema_invalid.py](tests/test_schema_invalid.py) — three schema-invalidating mutations (bad intent value in `policy_rules.json`, missing `overlays[]` in `market_overlays.json`, non-SHA256 component hash in `configuration_manifest.json`) must raise `SchemaValidationError`.
- [tests/test_unknown_version.py](tests/test_unknown_version.py) — an unrecognised `version_id` raises `UnknownVersionError`; `strict_version=False` permits it as an explicit debug affordance.
- [tests/test_controlled_vocabulary.py](tests/test_controlled_vocabulary.py) — vocabulary duplicates raise `ControlledVocabularyError`; cross-component drift (vocab omitting a template ID or reason code still used by a component) also raises `ControlledVocabularyError`.
- [tests/test_no_enum_duplication.py](tests/test_no_enum_duplication.py) — scans `src/player_triage/*.py` and fails if any string literal matches a controlled-vocabulary value; enforces the "no second source of truth" rule.
- [tests/test_error_sanitization.py](tests/test_error_sanitization.py) — plants a synthetic sensitive marker in `configuration_manifest.change_reason`, triggers a validation error, and asserts the marker never appears in the rendered exception.
- [tests/test_paths.py](tests/test_paths.py) — proves `resolve_app_root` is independent of `os.getcwd()` and honours the `PLAYER_TRIAGE_APP_ROOT` env override.
- [tests/test_cli.py](tests/test_cli.py) — `validate-policy` returns 0; every unimplemented command returns exit code 2.

Modified: none of `policy/`, `schemas/`, `input/`, `tools/`, `coding_runbook/`, or `docs/app/`.

## Dependency and Python-version decisions
- **Python `>=3.12,<3.13`** in `pyproject.toml` (requirement 1). Ambient interpreter is `3.12.10`.
- **Reproducible spec** (requirement 2): pinned direct deps in `pyproject.toml`, plus `requirements-lock.txt` for the whole transitive set. The project is installed in editable mode into a dedicated `.venv/` — no packages are added to the user's global environment.
- **Minimum runtime deps** (requirement 3): `jsonschema==4.23.0` (JSON Schema Draft 2020-12), `referencing==0.35.1` (cross-schema `$ref` resolution), `openpyxl==3.1.5` (XLSX reading; Phase 02 already relies on it and the audit installed it), `typer==0.12.5` + `click==8.1.7` (CLI), `pydantic==2.9.2` (typed config models). No Streamlit; the Phase 01 prompt explicitly says "No Streamlit/UI yet".
- **Runtime vs. optional local-model** (requirement 4): the `[project.optional-dependencies].local_model` extra exists but is deliberately empty; it becomes the single place to add adapter deps in Phase 04. Dev/test deps live under `[project.optional-dependencies].dev` (`pytest==8.3.3`, `mypy==1.11.2`).
- **No local model integrated** (requirement 5): the `local_model` extra is empty, no adapter code exists, no model files are downloaded or referenced.

## Commands executed
1. `python -m venv .venv` — created the project-local virtualenv (Python 3.12.10).
2. `.venv/Scripts/python.exe -m pip install --upgrade --quiet pip` — refreshed pip.
3. `.venv/Scripts/python.exe -m pip install --quiet --editable ".[dev]"` — installed the package in editable mode plus dev extras.
4. `.venv/Scripts/python.exe -m pip freeze --exclude-editable > requirements-lock.txt` — snapshot the resolved dependency graph.
5. `.venv/Scripts/python.exe -m player_triage.cli validate-policy` — required Phase 01 CLI check.
6. `.venv/Scripts/python.exe -m pytest -q` — Phase 01 unit-test suite.
7. `.venv/Scripts/python.exe -m mypy --config-file pyproject.toml` — static type check ("Static type check if configured").
8. `.venv/Scripts/python.exe tools/validate_policy_package.py` — pre-existing policy-package validator (Phase 00 gate).
9. `.venv/Scripts/python.exe tools/validate_application_spec.py` — pre-existing application-spec validator.
10. `cd <scratchpad> && .venv/Scripts/python.exe -m player_triage.cli validate-policy` — evidence that the loader resolves the application root independently of `os.getcwd()`.

## Test results
- **`pytest -q`**: `46 passed in 17.14s`. Zero failures, zero errors.
- **`validate-policy` CLI**: exits 0. Reports `app_root`, `configuration_version=policy-3.0.0`, `controlled_vocabularies version=3.0`, `14` schemas registered, and the individual `version` string of each of the 17 versioned policy components. Prints `POLICY LOAD COMPLETE (expected policy-3.0.0)`.
- **`mypy`**: `Success: no issues found in 7 source files`.
- **`tools/validate_policy_package.py`**: `POLICY PACKAGE VALID` (all 12 checks OK).
- **`tools/validate_application_spec.py`**: `APPLICATION SPEC VALID — NO MATERIAL CONTRACT GAPS DETECTED` (all 13 checks OK).
- **cwd-independence**: running `validate-policy` from the scratchpad directory produces the same output; app-root discovery is not sensitive to the caller's working directory.

The Phase 01 unit-test suite covers every case listed in the phase brief:

| Requirement (from prompt) | Test file(s) |
| --- | --- |
| Successful loading of every authoritative configuration file | `tests/test_happy_path.py::test_load_all_components`, `::test_component_versions_match_manifest_children`, `::test_schema_registry_registers_all_shipped_schemas`, `tests/test_cli.py::test_validate_policy_command` |
| Missing files | `tests/test_missing_files.py::test_missing_component_file[…]` (18 parametrisations), `::test_missing_policy_directory` |
| Invalid JSON | `tests/test_invalid_json.py::test_invalid_json_in_controlled_vocabularies`, `::test_invalid_json_in_policy_rules` |
| Schema-invalid policy files | `tests/test_schema_invalid.py::test_schema_invalid_policy_rule_intent`, `::test_schema_invalid_market_overlays_structure`, `::test_schema_invalid_configuration_manifest_hash` |
| Unknown configuration versions | `tests/test_unknown_version.py::test_unknown_configuration_version`, `::test_relaxed_mode_permits_alternate_version` |
| Duplicate or inconsistent controlled vocabulary entries | `tests/test_controlled_vocabulary.py::test_duplicate_intent_in_vocab`, `::test_vocab_missing_template_id_referenced_by_templates`, `::test_vocab_missing_reason_code_used_by_rationale_templates` |
| No duplicated enums / second source of truth | `tests/test_no_enum_duplication.py::test_no_controlled_vocabulary_string_in_source` |
| Sanitized errors that don't echo raw content | `tests/test_error_sanitization.py::test_error_does_not_leak_synthetic_payload` |
| App-root independent of cwd | `tests/test_paths.py::test_resolve_app_root_ignores_cwd`, `::test_resolve_app_root_env_override`, `::test_resolve_app_root_explicit_argument`, and the two negative variants |
| CLI skeleton exists but refuses to run un-built commands | `tests/test_cli.py::test_run_command_not_yet_implemented`, `::test_evaluate_command_not_yet_implemented`, `::test_demo_command_not_yet_implemented`, `::test_kill_switch_command_not_yet_implemented` |

## Deviations or unresolved issues
- **Policy/schema changes**: none. Requirement 6 (no policy simplification) is satisfied. No file under `policy/`, `schemas/`, `input/`, `tools/`, `coding_runbook/`, or `docs/app/` was modified in this phase.
- **Cross-component consistency vs. schema enums**: the shipped JSON Schemas already embed vocabulary values as `enum` constraints (a policy-side belt-and-suspenders), so if the reverse-direction test tried to inject an unknown template ID into `auto_response_templates.json`, schema validation caught it before the loader's cross-component check ran. This is the correct behaviour, but it meant the tests for that class of drift had to be rescoped to the direction the cross-check is uniquely responsible for: the vocabulary itself omits an entry that a still-schema-valid component references. Recorded here for transparency; not a deviation from the phase's intent.
- **Dependency ambient install from Phase 00**: Phase 00 installed `jsonschema` and `openpyxl` into the ambient Python environment to run the audit. Phase 01 now installs everything into `.venv/`; ambient installs are no longer necessary. Left in place because removing packages the user did not install is out of scope for this phase.
- **Pre-existing `tools/__pycache__/`**: not touched. Will remain out of the git repository via the new `.gitignore` unless the user prefers otherwise.

## Confirmation that no Phase 02 functionality was started
- No ingestion, tokenization, normalisation, linkage, sensitive-data detection, redaction, prompt-injection detection, classification, model integration, pipeline processing, evaluation runner, UI, or SQLite integration exists.
- The `run`, `evaluate`, `demo`, and `kill-switch` commands explicitly return exit code 2 with a "not implemented in Phase 01" message; there is no code path in the repository that classifies messages or writes to `sqlite`, CSV, or JSONL outputs.
- The `local_model` optional-dependency group is empty; no local-model adapter code was added.

## Stop statement
This phase is complete. No work from the next phase was started.
