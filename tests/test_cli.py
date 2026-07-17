"""CLI skeleton smoke tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from player_triage.cli import app


runner = CliRunner()


def test_validate_policy_command(app_root: Path) -> None:
    result = runner.invoke(app, ["validate-policy", "--app-root", str(app_root)])
    assert result.exit_code == 0, result.output
    assert "POLICY LOAD COMPLETE" in result.output


def test_run_command_classifies(app_root: Path) -> None:
    result = runner.invoke(app, ["run", "--app-root", str(app_root)])
    assert result.exit_code == 0, result.output
    assert "RUN COMPLETE (rules_only)" in result.output
    assert "mode: rules_only" in result.output
    # Output must be sanitized: no player identifier pattern.
    assert not __import__("re").search(r"\bP-\d{5}\b", result.output)


def test_evaluate_command_reports_gates(app_root: Path) -> None:
    result = runner.invoke(app, ["evaluate", "--app-root", str(app_root)])
    assert result.exit_code == 0, result.output
    assert "SAFETY GATES: 15/15 passed" in result.output
    assert "EVALUATE COMPLETE (all safety gates passed)" in result.output


def test_demo_command_preflight_is_local_and_rules_only(app_root: Path) -> None:
    result = runner.invoke(
        app, ["demo", "--dry-run", "--app-root", str(app_root)]
    )
    assert result.exit_code == 0, result.output
    assert "rules_only; model unavailable" in result.output
    assert "http://127.0.0.1:8501" in result.output
    assert "DEMO DRY RUN COMPLETE" in result.output


def test_kill_switch_command_not_yet_implemented() -> None:
    result = runner.invoke(app, ["kill-switch"])
    assert result.exit_code == 2
