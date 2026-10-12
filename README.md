# Player Contact Triage Automation

A deterministic, rules-based engine that classifies, prioritises and routes player support messages for gaming and betting operators.

Author: **Jordan Trpeski** — [trpeski.mk](https://trpeski.mk) · [GitHub](https://github.com/JordanTrpeski)

## What it does

- **Ingestion** — accepts CSV and XLSX batches and validates headers, enumerations, timestamps and player-ID formats. Invalid rows are isolated and reported; the rest of the batch still runs.
- **Classification** — assigns each message a category and priority from a fixed taxonomy (8 categories, 4 priorities). Deterministic rules catch high-risk cases (self-exclusion, underage play, account takeover, exposed payment data) and send them straight to specialist handling.
- **Routing** — sends every accepted message to a named team. Escalation to a human or specialist is a normal routing outcome. Responsible-gambling, payment, KYC, fraud and account actions always stay with people.
- **Audit trail** — logs every decision as structured JSONL with the rules and policy version that produced it, so any outcome can be traced and reproduced.

## Tech Stack

- Python 3.12
- Streamlit — local control console
- Pydantic — typed configuration models
- JSON Schema — policy and output contracts
- pytest
- mypy

## Architecture highlights

- **Data-driven policy** — taxonomy, teams, intent rules, routing, market overlays and redaction patterns are defined in versioned JSON under `policy/` and validated against `schemas/`.
- **No hardcoded business rules** — the engine reads its rules from policy files, so rules and thresholds change through reviewed, versioned policy updates rather than code changes.
- **Immutable records** — decisions and intermediate records are frozen dataclasses and cannot be modified once created.
- **Deterministic `rules_only` runtime** — identical input and policy always produce identical output, checked by a decision digest. A local-model adapter was benchmarked and rejected because it gave no material accuracy gain; the shipped runtime never loads a model.
- **Structured JSONL audit trail** — append-only, schema-validated events record each decision, the rules triggered and every configuration change.

## Key outputs

| Output | Description |
| --- | --- |
| Decision CSV | One row per message: category, priority, route, team and rationale |
| Audit trail | Structured JSONL record of every decision and the rules applied |
| Validation report | Rows rejected at ingestion, with the reason for each |
| Processing summary | Run-level counts, run manifest and decision digest |

## Running locally

Requires Python 3.12.

**macOS / Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install --editable ".[dev]"
```

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install --editable ".[dev]"
```

Then, on any platform:

```bash
python -m player_triage.cli validate-policy                          # check the policy bundle
python -m player_triage.cli run --output-dir output                  # process the benchmark dataset
python -m player_triage.cli evaluate --output-dir output --performance  # metrics, safety gates, performance
python -m player_triage.cli demo                                     # launch the control console
```

The raw benchmark input contains player message content and is not included in the repository. Place it at `input/dataset_player_messages.csv` before running `run`.

The console only listens on `127.0.0.1`. Once dependencies are installed, nothing needs network access.

### Console walkthrough

1. **Walkthrough** — system overview.
2. **Dashboard** — results for the 40-message benchmark.
3. **Evaluation** — benchmark agreement and known differences.
4. **Import** — process a CSV or XLSX batch. Imported runs are stored separately and never reported as accuracy figures.
5. **Policy Studio** — change rules and thresholds through draft, validate, preview, activate and rollback steps.

## Testing

```bash
pytest -q                                   # 354 tests across 34 files
mypy                                        # type checking (disallow_untyped_defs, strict_optional)
python tools/validate_policy_package.py     # policy bundle integrity
python tools/validate_application_spec.py   # application spec consistency
```

The suite covers ingestion, normalisation, detection, redaction, the rules engine, the operational pipeline, evaluation and the control console.

## Further reading

- [Architecture](docs/ARCHITECTURE.md) — system architecture and design rationale
- [Decision log](docs/DECISION_LOG.md) — key design decisions and trade-offs
- [Case study brief](docs/Case_Study__Player_Contact_Triage_Automation.pdf) — original case study brief

## Prototype status

This is a case-study prototype, not a production service. Benchmark results reflect agreement on a 40-message demonstration set and synthetic holdouts, not guaranteed accuracy. Production deployment would require approved integrations, authentication and authorisation, monitoring, operational ownership, privacy and security review, and validation against a larger representative labelled dataset.
