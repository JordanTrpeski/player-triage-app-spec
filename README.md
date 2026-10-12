# Player Contact Triage Automation

A deterministic, rules-based engine that classifies, prioritises and routes player support messages for gaming and betting operators.

Author: **Jordan Trpeski** — [trpeski.mk](https://trpeski.mk) · [GitHub](https://github.com/JordanTrpeski)

## What it does

- **Ingestion** — accepts CSV and XLSX batches with strict validation of headers, enumerations, timestamps and player-ID formats. Invalid rows are isolated and reported without stopping the run.
- **Classification** — assigns each message a category and priority from a fixed taxonomy (8 categories, 4 priorities). High-risk signals such as self-exclusion, underage play, account takeover and exposed payment data are handled by deterministic bypass rules.
- **Routing** — sends every accepted message to a named team via an automated route. Escalation to human or specialist handling is a routing outcome, not a failure; consequential responsible-gambling, payment, KYC, fraud and account actions stay under human control.
- **Audit trail** — records every decision, with the rule and policy version that produced it, as structured JSONL so any outcome can be traced and reproduced.

## Tech Stack

- Python 3.12
- Streamlit (local control console)
- Pydantic (configuration models)
- JSON Schema (policy and output contracts)
- pytest
- mypy (type checking)

## Architecture highlights

- **Data-driven policy** — taxonomy, teams, intent rules, routing rules, market overlays and redaction policy are all defined in versioned JSON under `policy/` and validated against schemas in `schemas/`.
- **No hardcoded business rules** — the engine interprets policy rather than embedding it, so rules and thresholds can be changed and versioned without code changes.
- **Immutable domain objects** — decisions and intermediate records are frozen dataclasses, so a result cannot be altered after it is produced.
- **Deterministic `rules_only` runtime** — the same input and policy version always produce the same output, confirmed by a canonical decision digest. An optional local-model adapter was evaluated and rejected because it gave no material improvement; the shipped runtime never loads a model.
- **Structured JSONL audit trail** — one event per decision, written against a published audit-event schema.

## Key outputs

| Output | Description |
| --- | --- |
| Decision CSV | One readable row per message: category, priority, route, team and rationale |
| Audit trail | Structured JSONL record of every decision and the rules applied |
| Validation report | Rows rejected at ingestion and the reason for each |
| Processing summary | Run-level counts, a run manifest and a decision digest |

## Running locally

Requires Python 3.12.

```bash
# 1. Create a virtual environment and install
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install --editable ".[dev]"

# 2. Validate the policy bundle
python -m player_triage.cli validate-policy

# 3. Process the 40-message benchmark dataset
python -m player_triage.cli run --output-dir output

# 4. Run the evaluation (metrics, safety gates, performance)
python -m player_triage.cli evaluate --output-dir output --performance

# 5. Launch the local control console
python -m player_triage.cli demo
```

The console binds to `127.0.0.1` only. No network access is needed after the dependencies are installed.

The raw benchmark input is not committed because it contains player message content. Place it at `input/dataset_player_messages.csv` before running step 3.

### Suggested console walkthrough

1. **Walkthrough** — system overview.
2. **Dashboard** — results for the 40-message benchmark.
3. **Evaluation** — benchmark agreement and documented differences.
4. **Import** — process a CSV or XLSX batch. Imported runs are kept separate from the benchmark and are not presented as accuracy evaluations.
5. **Policy Studio** — controlled changes to rules and thresholds.

## Testing

```bash
pytest -q                                    # 34 test files
mypy                                         # disallow_untyped_defs, strict_optional
python tools/validate_policy_package.py      # policy bundle integrity
python tools/validate_application_spec.py    # application spec consistency
```

The suite covers ingestion, normalisation, detection, redaction, the rules engine, the operational pipeline, evaluation governance and the control console.

## Prototype status

This is a case-study prototype, not a production service. Benchmark results reflect agreement on a 40-message demonstration set and synthetic holdouts, not guaranteed accuracy. Deploying it in production would require approved integrations, authentication and authorisation, monitoring, operational ownership, privacy and security review, and validation against a larger, representative labelled dataset.
