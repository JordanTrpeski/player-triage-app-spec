# Phase 08 — Documentation and Final Submission Package

Prerequisite: Phase 07 walkthrough succeeds.

Read:
- all phase reports;
- `docs/decision_log_outline.md`;
- final outputs and evaluation report;
- `policy/research_traceability.json`.

Create:
- `README.md` with one-command setup/run/evaluate/demo instructions and platform limitations.
- Architecture and data-flow diagram using text/Mermaid.
- Final maximum-two-page decision log in Markdown and PDF or DOCX only if the environment already supports reliable export.
- Walkthrough script for a 45-minute interview, including live rule change and rollback.
- Limitations and production-readiness checklist.
- AI transcript index telling the reviewer where research and coding-agent transcripts are stored; do not fabricate transcripts.
- Final file manifest and SHA-256 checksums for non-sensitive artifacts.
- Clean submission ZIP excluding model weights, caches, virtual environments, raw logs and secrets.

Run from a clean environment or clean virtual environment where feasible.
Final checks:
- One-command processing of 40 rows.
- CSV/JSONL/evaluation outputs exist and validate.
- Safety gates pass.
- No secrets or raw sensitive values in generated artifacts.
- Decision log is at most two pages.

Write `docs/phase_reports/phase_08.md` and stop with the final manifest.
