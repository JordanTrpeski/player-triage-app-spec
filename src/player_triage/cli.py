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
