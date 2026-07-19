## Reviewer quick start

This repository contains the Player Contact Triage Automation case-study prototype.

### Run on Windows

1. Download or clone the repository.
2. Double-click `SETUP_PLAYER_TRIAGE.bat` once.
3. Double-click `START_PLAYER_TRIAGE.bat`.
4. Open the local Streamlit URL shown in the terminal.

### Suggested walkthrough

1. Open **Walkthrough** for the system overview.
2. Open **Dashboard** to review the supplied 40-message benchmark.
3. Open **Evaluation** to inspect benchmark agreement and the documented M22 intent difference.
4. Open **Import** to process a CSV or XLSX operational batch.
5. Review routing decisions, audit records and downloadable outputs.
6. Open **Policy Studio** to demonstrate controlled rule and threshold changes.

### Important design boundaries

- Every accepted message is automatically classified, prioritised and routed.
- Human or specialist routing is an automated routing result, not a processing failure.
- Consequential responsible-gambling, payment, KYC, fraud and account actions remain human-controlled.
- The submitted runtime is deterministic `rules_only`.
- The evaluated local model is not called.
- Imported operational runs are isolated from the accepted benchmark.
- Imported runs without ground-truth labels are not presented as accuracy evaluations.

### Principal outputs

- Readable decision CSV
- Structured JSONL audit trail
- Validation-error report
- Processing summary
- Run manifest and decision digest

### Prototype status

This is a case-study prototype, not a production service. Production deployment would require approved integrations, authentication and authorisation, monitoring, operational ownership, privacy and security review, and validation against a larger representative labelled dataset.
