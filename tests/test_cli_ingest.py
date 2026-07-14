"""CLI smoke test for the Phase 02 `ingest` command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from player_triage.cli import app


runner = CliRunner()


def test_ingest_command_prints_sanitized_summary(app_root: Path) -> None:
    result = runner.invoke(app, ["ingest", "--app-root", str(app_root)])
    assert result.exit_code == 0, result.output
    assert "INGEST COMPLETE" in result.output
    # Sanity: known forbidden fixtures never appear in CLI output.
    for forbidden in ["4539 1488 0343 6467", "4539148803436467", "CVV 441"]:
        assert forbidden not in result.output
    # No P- player identifier survives to the output.
    import re

    assert not re.search(r"\bP-\d{5}\b", result.output)


def test_ingest_command_reports_m11_bypass_sensitive(app_root: Path) -> None:
    result = runner.invoke(app, ["ingest", "--app-root", str(app_root)])
    assert "M11" in result.output
    line = next(line for line in result.output.splitlines() if line.startswith("OK M11"))
    assert "eligibility=bypass_sensitive" in line
    assert "reason=pan_and_cvv_detected" in line


def test_ingest_command_reports_m18_prompt_injection(app_root: Path) -> None:
    result = runner.invoke(app, ["ingest", "--app-root", str(app_root)])
    line = next(line for line in result.output.splitlines() if line.startswith("OK M18"))
    assert "eligibility=bypass_untrusted_input" in line
    assert "reason=prompt_injection_detected" in line


def test_ingest_command_reports_m31_linkage_to_m09(app_root: Path) -> None:
    result = runner.invoke(app, ["ingest", "--app-root", str(app_root)])
    line = next(line for line in result.output.splitlines() if line.startswith("OK M31"))
    assert "linkage=prev=1,first=M09" in line
