"""Command-line skeleton for the player-triage application.

Only ``validate-policy`` performs real work in Phase 01. The other commands
exist so that downstream phases have stable entry points; they explicitly
refuse to run and exit non-zero, so nothing silently succeeds before its
functionality is implemented.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from .config import EXPECTED_CONFIGURATION_VERSION, load_app_config
from .console_service import ConsoleService
from .errors import ConfigurationError
from .evaluation_service import run_phase06_evaluation
from .operational import append_human_override, run_operational_pipeline
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
    mode: Annotated[
        str,
        typer.Option("--mode", help="Phase 05 production mode; only rules_only is approved."),
    ] = "rules_only",
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Output root. Defaults to output/ under the application root.",
            exists=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    fail_fast: Annotated[
        bool,
        typer.Option("--fail-fast", help="Abort after the first isolated message failure."),
    ] = False,
) -> None:
    """Run the Phase 05 rules-only pipeline and publish verified artifacts."""

    try:
        config = load_app_config(app_root)
        result = run_operational_pipeline(
            config,
            input_path=input_path,
            output_dir=output_dir,
            mode=mode,
            continue_safe=not fail_fast,
        )
    except ConfigurationError as exc:
        raise _fail(exc.component, str(exc)) from exc

    typer.echo(f"OK run_id: {result.run_id}")
    typer.echo(f"OK policy_version: {result.policy_version}")
    typer.echo(f"OK mode: {mode}")
    typer.echo(
        f"OK counts: input={result.input_count} success={result.success_count} "
        f"failure={result.failure_count} bypass={result.bypass_count}"
    )
    typer.echo(f"OK CSV: {result.artifacts.csv_path}")
    typer.echo(f"OK decisions JSONL: {result.artifacts.decisions_path}")
    typer.echo(f"OK audit events JSONL: {result.artifacts.audit_path}")
    typer.echo(f"OK SQLite: {result.artifacts.sqlite_path}")
    for filename, digest in sorted(result.artifacts.digests.items()):
        typer.echo(f"OK SHA256 {filename}: {digest}")
    typer.echo(f"OK canonical_decision_sha256: {result.canonical_decision_digest}")
    typer.echo(f"OK duration_ms: {result.duration_ms}")
    typer.echo(f"RUN COMPLETE ({mode})")


@app.command("override")
def override(
    run_dir: Annotated[
        Path,
        typer.Option(
            "--run-dir",
            help="Completed Phase 05 run directory.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    message_id: Annotated[str, typer.Option("--message-id")],
    reason_code: Annotated[str, typer.Option("--reason-code")],
    after_decision: Annotated[
        Path,
        typer.Option(
            "--after-decision",
            help="Complete sanitized replacement decision JSON.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    app_root: AppRootOption = None,
) -> None:
    """Append a governed human-override event; never replace the original decision."""

    try:
        config = load_app_config(app_root)
        event_id = append_human_override(
            config,
            run_dir=run_dir,
            message_id=message_id,
            reason_code=reason_code,
            after_decision_path=after_decision,
        )
    except (ConfigurationError, json.JSONDecodeError) as exc:
        component = exc.component if isinstance(exc, ConfigurationError) else "human_override"
        raise _fail(component, "override failed closed") from exc
    typer.echo(f"OK override_event_id: {event_id}")
    typer.echo("OVERRIDE APPENDED")


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
    mode: Annotated[
        str,
        typer.Option("--mode", help="Phase 06 accepted mode; only rules_only is allowed."),
    ] = "rules_only",
    datasets: Annotated[
        str,
        typer.Option(
            "--datasets",
            help="Comma-separated isolated datasets: supplied-40, holdout-v1, holdout-v2.",
        ),
    ] = "supplied-40,holdout-v1,holdout-v2",
    candidate_app_root: Annotated[
        Path | None,
        typer.Option(
            "--candidate-app-root",
            help="Validated candidate configuration root for non-activating impact analysis.",
            exists=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Evaluation artifact directory. Defaults to output/ under the app root.",
            exists=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    performance: Annotated[
        bool,
        typer.Option("--performance", help="Run warm-up plus repeated full-pipeline benchmark."),
    ] = False,
    safety_only: Annotated[
        bool,
        typer.Option("--safety-only", help="Print only the safety/activation summary."),
    ] = False,
) -> None:
    """Run Phase 06 metrics, locked gates, regression and impact analysis."""

    try:
        if mode != "rules_only":
            raise ConfigurationError(
                component="phase06_mode",
                message="Phase 06 evaluation permits rules_only mode only",
            )
        config = load_app_config(app_root)
        candidate = (
            load_app_config(candidate_app_root, strict_version=False)
            if candidate_app_root is not None
            else None
        )
        requested = tuple(
            value.strip() for value in datasets.split(",") if value.strip()
        )
        result = run_phase06_evaluation(
            config,
            output_dir=output_dir,
            input_path=input_path,
            datasets=requested,
            candidate_config=candidate,
            benchmark=performance,
        )
    except ConfigurationError as exc:
        raise _fail(exc.component, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise _fail("phase06_evaluation", "evaluation failed closed") from exc

    official = [gate for gate in result.safety_gates if gate.gate_id.startswith("S")]
    passed = sum(gate.passed for gate in official)
    typer.echo(f"OK dataset: {result.supplied_metrics.dataset_name}")
    typer.echo(f"OK policy_version: {result.policy_version}")
    typer.echo(
        f"SAFETY GATES: {passed}/{len(official)} passed; "
        f"locked={sum(g.passed for g in result.safety_gates)}/{len(result.safety_gates)}"
    )
    typer.echo(f"ACTIVATION: {result.activation['recommendation']}")
    if not safety_only:
        for item in result.dataset_metrics:
            typer.echo(
                f"OK {item.dataset_name}: messages={item.message_count} "
                f"category={item.agreement['category'].matches}/{item.agreement['category'].total} "
                f"intent={item.agreement['intent'].matches}/{item.agreement['intent'].total} "
                f"mismatches={len(item.mismatches)}"
            )
        typer.echo(f"MISMATCHES supplied-40: {len(result.supplied_metrics.mismatches)}")
        for mismatch in result.supplied_metrics.mismatches:
            typer.echo(
                f"  {mismatch.message_id} {mismatch.field}: "
                f"expected={mismatch.expected} actual={mismatch.actual}"
            )
        typer.echo(f"OK evaluation artifacts: {result.evaluation_artifacts.output_dir}")

    if all(gate.passed for gate in result.safety_gates):
        typer.echo("EVALUATE COMPLETE (all safety gates passed)")
    else:
        typer.echo("EVALUATE COMPLETE (safety gate failure)")
        raise typer.Exit(code=1)


@app.command("evaluate-semantic")
def evaluate_semantic(
    app_root: AppRootOption = None,
    mode: Annotated[
        str,
        typer.Option("--mode", help="Evaluation mode: both, rules_only, or local_model."),
    ] = "both",
    records: Annotated[
        bool,
        typer.Option("--records", help="Print sanitized per-case evidence records."),
    ] = False,
) -> None:
    """Compare rules-only and local-model modes on the frozen synthetic holdout."""

    from .semantic_evaluation import (
        SEMANTIC_FIELDS,
        SemanticModeReport,
        load_semantic_holdout,
        run_semantic_comparison,
        run_semantic_mode,
    )

    try:
        config = load_app_config(app_root)
        reports: tuple[SemanticModeReport, ...]
        if mode == "both":
            comparison = run_semantic_comparison(config)
            holdout_version = comparison.holdout_version
            holdout_sha256 = comparison.holdout_sha256
            reports = (comparison.rules_only, comparison.local_model)
        elif mode in {"rules_only", "local_model"}:
            holdout_version, _cases, holdout_sha256 = load_semantic_holdout(config)
            reports = (run_semantic_mode(config, mode=mode),)
        else:
            raise ValueError("mode must be both, rules_only, or local_model")
    except ConfigurationError as exc:
        raise _fail(exc.component, str(exc)) from exc
    except ValueError as exc:
        raise _fail("evaluate-semantic", str(exc)) from exc

    typer.echo(f"OK holdout: {holdout_version}")
    typer.echo(f"OK holdout_sha256: {holdout_sha256}")
    for report in reports:
        typer.echo(f"MODE {report.mode}: total={report.total}")
        for field_name in SEMANTIC_FIELDS:
            typer.echo(
                f"  agreement {field_name}: {report.agreement[field_name]}/{report.total}"
            )
        typer.echo(
            f"  fallback={report.fallback_count} schema_failure={report.schema_failure_count} "
            f"malformed={report.malformed_output_count} retries={report.retry_count} "
            f"unsafe_auto_response={report.unsafe_auto_response_count} "
            f"safety_regression={report.safety_regression_count} "
            f"model_calls={report.model_call_count} bypass={report.bypass_count}"
        )
        typer.echo(
            f"  median_ms={report.median_latency_ms:.1f} p95_ms={report.p95_latency_ms:.1f} "
            f"load_ms={report.load_time_ms:.1f} memory_delta_mb={report.memory_delta_mb}"
        )
        if records:
            for case_id in sorted(report.case_records):
                typer.echo(
                    "CASE "
                    + json.dumps(
                        asdict(report.case_records[case_id]),
                        ensure_ascii=True,
                        separators=(",", ":"),
                    )
                )
    typer.echo("SEMANTIC EVALUATION COMPLETE")


@app.command("demo")
def demo(
    app_root: AppRootOption = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Validate local console prerequisites without starting Streamlit.",
        ),
    ] = False,
) -> None:
    """Start the local-only rules console after a fail-closed preflight."""

    try:
        config = load_app_config(app_root)
        service = ConsoleService(config.app_root)
        snapshot = service.dashboard()
        if snapshot.latest_run_status == "no verified run":
            raise ConfigurationError(
                component="demo",
                message="a verified operational run is required before console startup",
            )
        if not service.evaluation_documents().get("safety"):
            raise ConfigurationError(
                component="demo",
                message="verified evaluation evidence is required before console startup",
            )
        settings = service.settings()
        if settings.get("runtime_mode") != "rules_only":
            raise ConfigurationError(
                component="demo", message="console startup requires rules-only mode"
            )
    except ConfigurationError as exc:
        raise _fail(exc.component, str(exc)) from exc

    typer.echo("OK console preflight: verified local artifacts")
    typer.echo("OK runtime mode: rules_only; model unavailable")
    typer.echo("URL http://127.0.0.1:8501")
    if dry_run:
        typer.echo("DEMO DRY RUN COMPLETE")
        return

    environment = os.environ.copy()
    environment["PLAYER_TRIAGE_APP_ROOT"] = str(config.app_root)
    application = Path(__file__).resolve().parent / "ui" / "app.py"
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(application),
        "--server.address=127.0.0.1",
        "--server.port=8501",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    try:
        completed = subprocess.run(command, env=environment, check=False)
    except OSError as exc:
        raise _fail("demo", "local console could not be started") from exc
    if completed.returncode not in (0, 130):
        raise _fail("demo", "local console stopped unexpectedly")


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
