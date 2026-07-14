# Player Contact Triage — Application Specification v3.0

This package is the frozen application contract for a local, provider-independent player-message triage prototype.

Start with:
- `docs/app/app_requirements.md`
- `docs/app/application_architecture.md`
- `docs/app/ui_spec.md`
- `docs/app/schema_logic.md`
- `docs/app/change_management.md`
- `docs/app/technology_stack.md`
- `policy/application_requirements.json`
- `policy/configuration_manifest.json`

Validate:

```bash
python tools/validate_application_spec.py
```

The application must provide both a Streamlit local control console and a repeatable Typer CLI. Configuration changes are versioned, impact-tested and reversible. Raw sensitive message content is not written to operational outputs or internal SQLite state.
