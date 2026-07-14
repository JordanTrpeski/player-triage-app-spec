# Phase 01 — Project Scaffold and Contract Loaders

Prerequisite: Phase 00 passes.

Read:
- `coding_runbook/agent_operating_rules.md`
- `policy/stage9_policy_spec.md`
- `policy/controlled_vocabularies.json`
- `policy/policy_rules.json`
- `policy/baseline_intent_rules.json`
- `schemas/*.json`

Build:
- A Python 3.11+ package under `src/player_triage/`.
- `pyproject.toml` with pinned direct dependencies.
- Typed configuration models/loaders for every policy JSON.
- JSON Schema validators for model candidate, final result, ground truth and audit events.
- CLI skeleton with commands: `validate-policy`, `run`, `evaluate`, `demo`, `kill-switch`.
- A central immutable `AppConfig` exposing policy/rule/redaction/schema versions.
- Unit tests that load all files, reject unknown enums and verify configuration versions.

Constraints:
- No message classification yet.
- No local model dependency yet.
- No Streamlit/UI yet.
- Do not duplicate policy enums in source code where they can be loaded from policy files.

Validation:
- `python -m player_triage.cli validate-policy`
- `pytest -q`
- Static type check if configured.

Write `docs/phase_reports/phase_01.md` and stop.
