"""Command-line skeleton for the player-triage application.

Only ``validate-policy`` performs real work in Phase 01. The other commands
exist so that downstream phases have stable entry points; they explicitly
refuse to run and exit non-zero, so nothing silently succeeds before its
functionality is implemented.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from .config import EXPECTED_CONFIGURATION_VERSION, load_app_config
from .engine import TriageEngine
from .errors import ConfigurationError
from .evaluation import run_evaluation
from .pipeline import ingest as run_ingest

app = typer.Typer(
    name="player-triage",
    help="Local, provider-independent player-message triage prototype.",
    no_args_is_help=True,
    add_completion=False,
)


AppRootOption = Annotated[
    Path | None,
    typer.Option(
        "--app-root",
        help="Override the application root. Defaults to auto-discovery.",
        exists=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
]


def _fail(component: str, message: str) -> "typer.Exit":
    typer.echo(f"FAIL: [{component}] {message}", err=True)
    return typer.Exit(code=1)


@app.command("validate-policy")
def validate_policy(app_root: AppRootOption = None) -> None:
    """Load and validate every authoritative policy configuration."""

    try:
        config = load_app_config(app_root)
    except ConfigurationError as exc:
        raise _fail(exc.component, str(exc)) from exc

    typer.echo(f"OK app_root: {config.app_root}")
    typer.echo(f"OK configuration_version: {config.configuration_version}")
    typer.echo(f"OK controlled_vocabularies version: {config.vocab.version}")
    for component_name, version in sorted(config.component_versions().items()):
        typer.echo(f"OK component {component_name}: {version}")
    typer.echo(f"OK schemas registered: {len(config.schema_registry.schemas)}")
    typer.echo(f"POLICY LOAD COMPLETE (expected {EXPECTED_CONFIGURATION_VERSION})")


@app.command("ingest")
def ingest_command(
    app_root: AppRootOption = None,
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input",
            help="Input CSV or XLSX. Defaults to input/dataset_player_messages.csv.",
            exists=False,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Run the Phase 02 ingestion pipeline and print a sanitized summary.

    The summary contains message IDs, detector counts, eligibility state,
    linkage metadata, and market overlay status. It never contains raw
    subject/body text, player identifiers, or sensitive detector matches.
    """

    try:
        config = load_app_config(app_root)
        ingested = run_ingest(config, input_path=input_path)
    except ConfigurationError as exc:
        raise _fail(exc.component, str(exc)) from exc

    typer.echo(f"OK app_root: {config.app_root}")
    typer.echo(f"OK ingested messages: {len(ingested)}")
    for message in ingested:
        detector_hits = ",".join(
            f"{d.detector_id}:{d.count}" for d in message.detections if d.is_detected()
        ) or "-"
        linkage = message.linkage
        linkage_summary = (
            f"prev={linkage.previous_contact_count},first={linkage.first_contact_message_id or '-'}"
        )
        overlay_codes = ",".join(message.market_overlay_codes) or "-"
        typer.echo(
            f"OK {message.msg_id} channel={message.channel} market={message.market} "
            f"lang={message.language} eligibility={message.eligibility.state} "
            f"reason={message.eligibility.reason or '-'} "
            f"attach_ref={message.eligibility.attachment_referenced} "
            f"id_doc_ref={message.eligibility.identity_document_referenced} "
            f"detectors={detector_hits} linkage={linkage_summary} overlays={overlay_codes}"
        )
    typer.echo("INGEST COMPLETE")


def _not_yet_implemented(command: str) -> "typer.Exit":
    typer.echo(
        f"{command}: not implemented in Phase 01. This command becomes available in a later phase.",
        err=True,
    )
    return typer.Exit(code=2)


@app.command("run")
def run(
    app_root: AppRootOption = None,
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input",
            help="Input CSV or XLSX. Defaults to input/dataset_player_messages.csv.",
            exists=False,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Run the deterministic rules-only triage over the input dataset.

    Output is sanitized: one line per message showing message_id, category,
    priority, route, assigned team and the stage/rule decision path. It never
    prints player identifiers, subject/body text, redacted text or detected
    sensitive values.
    """

    try:
        config = load_app_config(app_root)
        engine = TriageEngine.from_config(config)
        ingested = run_ingest(config, input_path=input_path)
    except ConfigurationError as exc:
        raise _fail(exc.component, str(exc)) from exc

    typer.echo(f"OK app_root: {config.app_root}")
    typer.echo(f"OK mode: rules_only")
    for message in ingested:
        result = engine.classify(message)
        decision = result.decision
        typer.echo(
            f"OK {decision['message_id']} category={decision['category']} "
            f"intent={decision['intent']} priority={decision['priority']} "
            f"route={decision['route']} team={decision['assigned_team']} "
            f"model_called={decision['model_called']} "
            f"status={decision['processing_status']} "
            f"path=[{result.decision_path()}]"
        )
    typer.echo("RUN COMPLETE (rules_only)")


@app.command("evaluate")
def evaluate(
    app_root: AppRootOption = None,
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input",
            help="Input CSV or XLSX. Defaults to input/dataset_player_messages.csv.",
            exists=False,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Evaluate the rules-only baseline against the frozen ground truth.

    Prints per-field agreement, a sanitized mismatch table (message_id + field
    + expected/actual enum values only) and the pass/fail status of every
    safety hard gate. It does not modify the ground truth.
    """

    try:
        config = load_app_config(app_root)
        report = run_evaluation(config, input_path=input_path)
    except ConfigurationError as exc:
        raise _fail(exc.component, str(exc)) from exc

    typer.echo(f"OK app_root: {config.app_root}")
    typer.echo(f"OK evaluated messages: {report.total}")
    typer.echo(f"OK schema-valid decisions: {report.schema_valid_count}/{report.total}")
    for field_name in ("category", "intent", "priority", "route", "assigned_team"):
        agree = report.agreement[field_name]
        typer.echo(f"OK agreement {field_name}: {agree}/{report.total}")

    typer.echo(f"MISMATCHES: {len(report.mismatches)}")
    for mismatch in report.mismatches:
        typer.echo(
            f"  {mismatch.message_id} {mismatch.field}: expected={mismatch.expected} actual={mismatch.actual}"
        )

    gates_passed = sum(1 for gate in report.gate_results if gate.passed)
    typer.echo(f"SAFETY GATES: {gates_passed}/{len(report.gate_results)} passed")
    for gate in report.gate_results:
        status = "PASS" if gate.passed else "FAIL"
        typer.echo(f"  {gate.gate_id} {status}: {gate.detail}")

    if report.all_gates_pass():
        typer.echo("EVALUATE COMPLETE (all safety gates passed)")
    else:
        typer.echo("EVALUATE COMPLETE (safety gate failure)")
        raise typer.Exit(code=1)


@app.command("demo")
def demo(app_root: AppRootOption = None) -> None:
    """Run the walkthrough / before-after / rollback demonstration (later phase)."""

    _ = app_root
    raise _not_yet_implemented("demo")


@app.command("kill-switch")
def kill_switch(app_root: AppRootOption = None) -> None:
    """Toggle the deterministic-only kill switch and record an audit event (later phase)."""

    _ = app_root
    raise _not_yet_implemented("kill-switch")


def main() -> int:
    """Console-script entry point."""

    try:
        app()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
