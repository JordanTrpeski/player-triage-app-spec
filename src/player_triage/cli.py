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
from .errors import ConfigurationError
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
def run(app_root: AppRootOption = None) -> None:
    """Run the end-to-end triage pipeline over the input dataset (later phase)."""

    _ = app_root
    raise _not_yet_implemented("run")


@app.command("evaluate")
def evaluate(app_root: AppRootOption = None) -> None:
    """Run the evaluation and regression suite against the frozen ground truth (later phase)."""

    _ = app_root
    raise _not_yet_implemented("evaluate")


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
