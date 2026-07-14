# Phase 07 — Streamlit Control Console, Change Audit and Rollback

Prerequisite: core pipeline and safety gates pass.

Build the mandatory local Streamlit control console according to `docs/app/ui_spec.md`. The UI is part of the application control surface, not optional presentation.

Required pages:
- Dashboard
- Messages
- Human Review
- Policy Studio
- Evaluation
- Audit Explorer
- Configuration Versions
- Settings

All policy edits must use the configuration manager: create draft, schema validate, semantic validate, run behavior fixtures, impact-preview all 40 records, display before/after diff, run safety regression, activate atomically, and record the configuration-change event. Active files cannot be edited directly.

Implement model kill switch, schema-constrained human override, pattern/redaction test labs, configuration version history and rollback to any prior valid configuration. Locked rules are read-only in normal UI. Guarded rules require full regression. Do not expose raw sensitive messages.
