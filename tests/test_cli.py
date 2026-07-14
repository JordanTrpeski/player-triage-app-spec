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


def test_run_command_not_yet_implemented() -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 2
    assert "not implemented in Phase 01" in result.output


def test_evaluate_command_not_yet_implemented() -> None:
    result = runner.invoke(app, ["evaluate"])
    assert result.exit_code == 2


def test_demo_command_not_yet_implemented() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 2


def test_kill_switch_command_not_yet_implemented() -> None:
    result = runner.invoke(app, ["kill-switch"])
    assert result.exit_code == 2
