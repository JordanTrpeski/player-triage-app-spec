"""Phase 05 rules-only operational batch, exports, audit and SQLite index.

The module consumes :class:`IngestedMessage` records and the authoritative
classification engine.  It never receives a ``RawMessage`` and therefore
cannot export source text or player identity.  A complete run is assembled in
a hidden temporary directory and promoted atomically only after every artifact
has passed schema, digest, count and safety verification.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .config import AppConfig
from .engine import ClassificationResult, TriageEngine
from .errors import ConfigurationError
from .evaluation import SCORED_FIELDS, evaluate_gates, load_ground_truth
from .pipeline import ingest as run_ingest
from .records import IngestedMessage
from .routing import load_routing_map

RULES_ONLY_MODE = "rules_only"
MODEL_CONCLUSION = "model_rejected_no_material_improvement"
MODEL_APPROVAL_STATUS = "rejected"
MODEL_ENABLED = False

CSV_FILENAME = "decisions.csv"
AUDIT_FILENAME = "audit.jsonl"
SQLITE_FILENAME = "triage_audit.sqlite3"
MANIFEST_FILENAME = "run_manifest.json"

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_PLAYER_ID_RE = re.compile(r"\bP-\d{5}\b")
_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")
_POSIX_HOME_RE = re.compile(r"/(?:Users|home)/[^/\s]+")
_MODEL_PATH_RE = re.compile(r"(?i)\.(?:gguf|onnx|pth|pt)(?:\b|$)")


class OperationalRunError(ConfigurationError):
    """Sanitized fail-closed operational error."""


@dataclass(frozen=True, slots=True)
class ArtifactSet:
    csv_path: Path
    audit_path: Path
    sqlite_path: Path
    manifest_path: Path
    digests: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class OperationalRunResult:
    run_id: str
    policy_version: str
    input_count: int
    success_count: int
    failure_count: int
    bypass_count: int
    duration_ms: int
    canonical_decision_digest: str
    artifacts: ArtifactSet
    decisions: tuple[Mapping[str, Any], ...]


EngineFactory = Callable[[AppConfig], TriageEngine]


def run_operational_pipeline(
    config: AppConfig,
    *,
    input_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    mode: str = RULES_ONLY_MODE,
    continue_safe: bool = True,
    engine_factory: EngineFactory | None = None,
) -> OperationalRunResult:
    """Run the complete Phase 05 pipeline and atomically publish safe artifacts."""

    if mode != RULES_ONLY_MODE:
        raise OperationalRunError(
            component="phase05_mode",
            message="Phase 05 production runs permit rules_only mode only",
        )

    source = _resolve_input(config, input_path)
    if not source.is_file():
        raise OperationalRunError(
            component="ingestion", message="input file is unavailable", path=source
        )
    input_digest = sha256_file(source)
    output_root = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (config.app_root / "output").resolve()
    )
    output_root.mkdir(parents=True, exist_ok=True)

    started_at = _utc_now()
    started_clock = time.perf_counter()
    run_id = _new_run_id(started_at)
    final_dir = output_root / run_id
    work_dir = output_root / f".{run_id}.tmp"
    if final_dir.exists() or work_dir.exists():
        raise OperationalRunError(
            component="replay_protection",
            message="run destination already exists; prior output will not be overwritten",
        )
    work_dir.mkdir()

    try:
        messages = tuple(
            sorted(
                run_ingest(config, input_path=source),
                key=lambda item: (item.received_utc, item.msg_id),
            )
        )
        engine = (
            engine_factory(config)
            if engine_factory is not None
            else TriageEngine.from_config(config, mode=RULES_ONLY_MODE)
        )
        results, failures, decision_events, error_events, per_message_ms = _classify_messages(
            config,
            engine,
            messages,
            run_id=run_id,
            continue_safe=continue_safe,
        )
        decisions = tuple(result.decision for result in results)
        evaluation_summary = _build_evaluation_summary(
            config,
            run_id,
            messages,
            results,
            failures,
            per_message_ms,
        )
        completed_at = _utc_now()
        summary_event = _run_summary_event(
            config, run_id, completed_at, evaluation_summary
        )
        events = tuple(decision_events + error_events + [summary_event])

        csv_path = work_dir / CSV_FILENAME
        audit_path = work_dir / AUDIT_FILENAME
        sqlite_path = work_dir / SQLITE_FILENAME
        manifest_path = work_dir / MANIFEST_FILENAME

        _write_csv_atomic(config, csv_path, decisions)
        _write_audit_atomic(config, audit_path, events)
        _write_sqlite_atomic(
            config,
            sqlite_path,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            status="completed" if not failures else "completed_with_failures",
            decisions=decisions,
            events=events,
            evaluation_summary=evaluation_summary,
        )

        artifact_digests = {
            CSV_FILENAME: sha256_file(csv_path),
            AUDIT_FILENAME: sha256_file(audit_path),
            SQLITE_FILENAME: sha256_file(sqlite_path),
        }
        duration_ms = max(0, round((time.perf_counter() - started_clock) * 1000))
        canonical_digest = canonical_decision_digest(decisions)
        bypass_count = sum(
            1
            for decision in decisions
            if str(decision.get("model_eligibility", "")).startswith("bypass_")
        )
        manifest = _run_manifest(
            config,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            source=source,
            input_digest=input_digest,
            input_count=len(messages),
            success_count=len(decisions),
            failure_count=len(failures),
            bypass_count=bypass_count,
            duration_ms=duration_ms,
            canonical_digest=canonical_digest,
            artifact_digests=artifact_digests,
        )
        _atomic_write_json(manifest_path, manifest)
        verify_run_artifacts(config, work_dir)
        os.replace(work_dir, final_dir)

        final_artifacts = ArtifactSet(
            csv_path=final_dir / CSV_FILENAME,
            audit_path=final_dir / AUDIT_FILENAME,
            sqlite_path=final_dir / SQLITE_FILENAME,
            manifest_path=final_dir / MANIFEST_FILENAME,
            digests=artifact_digests,
        )
        return OperationalRunResult(
            run_id=run_id,
            policy_version=config.bundle_version,
            input_count=len(messages),
            success_count=len(decisions),
            failure_count=len(failures),
            bypass_count=bypass_count,
            duration_ms=duration_ms,
            canonical_decision_digest=canonical_digest,
            artifacts=final_artifacts,
            decisions=decisions,
        )
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        _write_failure_record(output_root, run_id, config.bundle_version, exc)
        if isinstance(exc, ConfigurationError):
            raise
        raise OperationalRunError(
            component=_failure_component(exc),
            message="operational run failed closed; see sanitized failure record",
        ) from exc


def _classify_messages(
    config: AppConfig,
    engine: TriageEngine,
    messages: Sequence[IngestedMessage],
    *,
    run_id: str,
    continue_safe: bool,
) -> tuple[
    list[ClassificationResult],
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[int],
]:
    results: list[ClassificationResult] = []
    failures: list[str] = []
    decisions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    latencies: list[int] = []
    try:
        for message in messages:
            started = time.perf_counter()
            try:
                result = engine.classify(message)
                processing_ms = max(0, round((time.perf_counter() - started) * 1000))
                if (
                    not result.schema_valid
                    or result.semantic_violations
                    or result.decision.get("model_called") is not False
                ):
                    raise OperationalRunError(
                        component="semantic_validation",
                        message="message result failed Phase 05 validation",
                    )
                event = engine.build_decision_audit_event(
                    result, run_id=run_id, processing_time_ms=processing_ms
                )
                event["event_id"] = f"{run_id}-decision-{message.msg_id}"
                event["occurred_at"] = _utc_now()
                _validate_audit(config, event)
                results.append(result)
                decisions.append(event)
                latencies.append(processing_ms)
            except Exception as exc:
                failures.append(message.msg_id)
                error = _message_failure_event(
                    config,
                    run_id=run_id,
                    message_id=message.msg_id,
                    stage=(
                        "semantic_validation"
                        if isinstance(exc, OperationalRunError)
                        else "rules"
                    ),
                )
                _validate_audit(config, error)
                errors.append(error)
                if not continue_safe:
                    raise OperationalRunError(
                        component="message_processing",
                        message="message processing failed in fail-fast mode",
                    ) from exc
    finally:
        engine.close()
    return results, failures, decisions, errors, latencies


def _build_evaluation_summary(
    config: AppConfig,
    run_id: str,
    messages: Sequence[IngestedMessage],
    results: Sequence[ClassificationResult],
    failures: Sequence[str],
    latencies: Sequence[int],
) -> dict[str, Any]:
    by_id = {result.message_id: result for result in results}
    truth = load_ground_truth(config)
    supplied_set = set(truth)
    result_set = set(by_id)
    complete_supplied = supplied_set == result_set and len(messages) == len(truth)
    gate_results = evaluate_gates(config, by_id) if complete_supplied else []
    hard_gate_failures = [gate.gate_id for gate in gate_results if not gate.passed]
    if not complete_supplied:
        hard_gate_failures.append("EVALUATION_NOT_APPLICABLE")

    agreement = {field: 0 for field in SCORED_FIELDS}
    mismatches: list[dict[str, object]] = []
    if complete_supplied:
        for message_id, result in sorted(by_id.items()):
            expected = truth[message_id]
            for field_name in SCORED_FIELDS:
                actual_value = result.decision.get(field_name)
                expected_value = expected.get(field_name)
                if actual_value == expected_value:
                    agreement[field_name] += 1
                else:
                    mismatches.append(
                        {
                            "message_id": message_id,
                            "field": field_name,
                            "expected": expected_value,
                            "actual": actual_value,
                        }
                    )

    total = len(messages)
    bypass_count = sum(
        1
        for result in results
        if str(result.decision.get("model_eligibility", "")).startswith("bypass_")
    )
    manual_count = sum(
        1 for result in results if result.decision.get("human_review_required") is True
    )
    metrics: dict[str, int | float | None] = {
        "success_count": len(results),
        "failure_count": len(failures),
        "bypass_count": bypass_count,
        "model_call_count": sum(
            1 for result in results if result.decision.get("model_called") is True
        ),
    }
    for field_name in SCORED_FIELDS:
        metrics[f"{field_name}_agreement"] = agreement[field_name]
        metrics[f"{field_name}_accuracy"] = (
            agreement[field_name] / total if complete_supplied and total else None
        )
    latency = sorted(latencies)
    latency_summary: dict[str, int | float] = {
        "minimum": latency[0] if latency else 0,
        "maximum": latency[-1] if latency else 0,
        "mean": sum(latency) / len(latency) if latency else 0,
    }
    summary = {
        "run_id": run_id,
        "configuration_version": config.bundle_version,
        "message_count": total,
        "terminal_count": sum(
            1 for result in results if result.model_trace.gate_reason == "SAFETY_TERMINAL"
        ),
        "schema_valid_count": len(results),
        "hard_gates_passed": complete_supplied and not hard_gate_failures,
        "hard_gate_failures": hard_gate_failures,
        "metrics": metrics,
        "mismatches": mismatches,
        "latency_ms": latency_summary,
        "bypass_rate": bypass_count / total if total else 0,
        "manual_review_rate": manual_count / total if total else 0,
    }
    _validate_evaluation_summary(config, summary)
    return summary


def _run_summary_event(
    config: AppConfig,
    run_id: str,
    completed_at: str,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    event = {
        "audit_schema_version": "3.0",
        "event_id": f"{run_id}-summary",
        "event_type": "run_summary",
        "run_id": run_id,
        "occurred_at": completed_at,
        "message_id": None,
        "actor": {"type": "system", "role": "pipeline-controller", "actor_ref": None},
        "configuration_version": config.bundle_version,
        "payload": dict(summary),
    }
    _validate_audit(config, event)
    return event


def _message_failure_event(
    config: AppConfig,
    *,
    run_id: str,
    message_id: str,
    stage: str,
) -> dict[str, Any]:
    event = {
        "audit_schema_version": "3.0",
        "event_id": f"{run_id}-failure-{message_id}",
        "event_type": "error_fallback",
        "run_id": run_id,
        "occurred_at": _utc_now(),
        "message_id": message_id,
        "actor": {"type": "system", "role": "pipeline-controller", "actor_ref": None},
        "configuration_version": config.bundle_version,
        "payload": {
            "stage": stage,
            "reason_code": "SEMANTIC_VALIDATION_FAILED",
            "fallback_route": load_routing_map().constants.human,
            "sanitized_error": "MESSAGE_PROCESSING_FAILED",
        },
    }
    return event


def _run_manifest(
    config: AppConfig,
    *,
    run_id: str,
    started_at: str,
    completed_at: str,
    source: Path,
    input_digest: str,
    input_count: int,
    success_count: int,
    failure_count: int,
    bypass_count: int,
    duration_ms: int,
    canonical_digest: str,
    artifact_digests: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "completed" if not failure_count else "completed_with_failures",
        "started_at": started_at,
        "completed_at": completed_at,
        "application_version": _application_version(),
        "policy_bundle_version": config.bundle_version,
        "configuration_component_versions": dict(sorted(config.component_versions().items())),
        "configuration_component_digests": dict(sorted(config.manifest.components.items())),
        "input_file_name": source.name,
        "input_file_sha256": input_digest,
        "processing_mode": RULES_ONLY_MODE,
        "model_enabled": MODEL_ENABLED,
        "model_approval_status": MODEL_APPROVAL_STATUS,
        "model_conclusion": MODEL_CONCLUSION,
        "message_count": input_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "bypass_count": bypass_count,
        "output_artifact_digests": dict(sorted(artifact_digests.items())),
        "canonical_decision_sha256": canonical_digest,
        "processing_duration_ms": duration_ms,
    }


def _write_csv_atomic(
    config: AppConfig, path: Path, decisions: Sequence[Mapping[str, Any]]
) -> None:
    contract = config.component("export_contract")
    columns = contract.get("csv_columns")
    if not isinstance(columns, list) or not all(isinstance(item, str) for item in columns):
        raise OperationalRunError(
            component="export_contract", message="CSV column contract is invalid"
        )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(columns),
        extrasaction="raise",
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for decision in decisions:
        writer.writerow(
            {column: _csv_value(decision.get(column)) for column in columns}
        )
    _atomic_write_text(path, stream.getvalue())
    _verify_csv(config, path, len(decisions))


def _write_audit_atomic(
    config: AppConfig, path: Path, events: Sequence[Mapping[str, Any]]
) -> None:
    lines: list[str] = []
    for event in events:
        _validate_audit(config, event)
        lines.append(_stable_json(event))
    _atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    _verify_audit(config, path)


def _write_sqlite_atomic(
    config: AppConfig,
    path: Path,
    *,
    run_id: str,
    started_at: str,
    completed_at: str,
    status: str,
    decisions: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    evaluation_summary: Mapping[str, Any],
) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    schema_path = config.app_root / "docs" / "app" / "sqlite_schema.sql"
    if not schema_path.is_file():
        raise OperationalRunError(
            component="sqlite", message="authoritative SQLite schema is unavailable"
        )
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        connection.executescript(_SQLITE_INDEXES)
        with connection:
            manifest = config.manifest.model_dump(mode="json")
            connection.execute(
                "INSERT INTO configuration_versions "
                "(version_id, parent_version_id, status, created_at, created_by, "
                "change_reason, manifest_json, activated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    config.manifest.version_id,
                    config.manifest.parent_version_id,
                    config.manifest.status,
                    config.manifest.created_at,
                    config.manifest.created_by,
                    config.manifest.change_reason,
                    _stable_json(manifest),
                    completed_at,
                ),
            )
            connection.execute(
                "INSERT INTO runs "
                "(run_id, configuration_version, mode, started_at, finished_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, config.bundle_version, RULES_ONLY_MODE, started_at, completed_at, status),
            )
            event_by_message = {
                str(event["message_id"]): str(event["event_id"])
                for event in events
                if event.get("event_type") == "decision"
            }
            for decision in decisions:
                message_id = str(decision["message_id"])
                connection.execute(
                    "INSERT INTO decisions "
                    "(run_id, message_id, decision_json, audit_event_id) VALUES (?, ?, ?, ?)",
                    (
                        run_id,
                        message_id,
                        _stable_json(decision),
                        event_by_message[message_id],
                    ),
                )
            for event in events:
                connection.execute(
                    "INSERT INTO audit_events "
                    "(event_id, run_id, message_id, event_type, occurred_at, "
                    "configuration_version, event_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event["event_id"],
                        run_id,
                        event.get("message_id"),
                        event["event_type"],
                        event["occurred_at"],
                        config.bundle_version,
                        _stable_json(event),
                    ),
                )
            connection.execute(
                "INSERT INTO evaluation_summaries "
                "(run_id, configuration_version, summary_json, hard_gates_passed) "
                "VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    config.bundle_version,
                    _stable_json(evaluation_summary),
                    int(bool(evaluation_summary["hard_gates_passed"])),
                ),
            )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise OperationalRunError(
                component="sqlite", message="SQLite integrity check failed"
            )
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
        if foreign_keys != (1,):
            raise OperationalRunError(
                component="sqlite", message="SQLite foreign keys are not enabled"
            )
        connection.close()
        connection = None
        _sync_file(temporary)
        os.replace(temporary, path)
    except Exception:
        if connection is not None:
            connection.rollback()
            connection.close()
        temporary.unlink(missing_ok=True)
        raise


_SQLITE_INDEXES = """
CREATE INDEX idx_runs_configuration ON runs(configuration_version);
CREATE INDEX idx_runs_started ON runs(started_at);
CREATE INDEX idx_decisions_message ON decisions(message_id);
CREATE INDEX idx_decisions_category ON decisions(json_extract(decision_json, '$.category'));
CREATE INDEX idx_decisions_priority ON decisions(json_extract(decision_json, '$.priority'));
CREATE INDEX idx_decisions_team ON decisions(json_extract(decision_json, '$.assigned_team'));
CREATE INDEX idx_audit_run ON audit_events(run_id);
CREATE INDEX idx_audit_message ON audit_events(message_id);
CREATE INDEX idx_audit_occurred ON audit_events(occurred_at);
CREATE INDEX idx_audit_configuration ON audit_events(configuration_version);
"""


def verify_run_artifacts(config: AppConfig, run_dir: Path | str) -> None:
    """Re-parse and cross-check every published artifact for a run."""

    directory = Path(run_dir)
    manifest_path = directory / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("processing_mode") != RULES_ONLY_MODE:
        raise OperationalRunError(
            component="artifact_verification", message="run mode is not approved"
        )
    if manifest.get("model_enabled") is not False:
        raise OperationalRunError(
            component="artifact_verification", message="model must be disabled"
        )
    if manifest.get("model_conclusion") != MODEL_CONCLUSION:
        raise OperationalRunError(
            component="artifact_verification", message="model conclusion is missing"
        )

    recorded = manifest.get("output_artifact_digests")
    if not isinstance(recorded, Mapping):
        raise OperationalRunError(
            component="artifact_verification", message="artifact digests are missing"
        )
    for filename in (CSV_FILENAME, AUDIT_FILENAME, SQLITE_FILENAME):
        expected = recorded.get(filename)
        if not isinstance(expected, str) or sha256_file(directory / filename) != expected:
            raise OperationalRunError(
                component="artifact_verification", message="artifact digest mismatch"
            )

    success_count = int(manifest["success_count"])
    csv_rows = _verify_csv(config, directory / CSV_FILENAME, success_count)
    events = _verify_audit(config, directory / AUDIT_FILENAME)
    decisions = [
        event["payload"]["result"]
        for event in events
        if event.get("event_type") == "decision"
    ]
    if len(decisions) != success_count or len(csv_rows) != success_count:
        raise OperationalRunError(
            component="artifact_verification", message="artifact counts disagree"
        )
    for decision in decisions:
        _validate_decision(config, decision)
        if decision.get("model_called") is not False:
            raise OperationalRunError(
                component="artifact_verification", message="model call found in Phase 05 output"
            )

    _verify_sqlite(
        directory / SQLITE_FILENAME,
        decision_count=success_count,
        event_count=len(events),
    )
    if canonical_decision_digest(decisions) != manifest.get("canonical_decision_sha256"):
        raise OperationalRunError(
            component="artifact_verification", message="canonical decision digest mismatch"
        )
    _scan_safe(config, manifest, csv_rows, events)


def append_human_override(
    config: AppConfig,
    *,
    run_dir: Path | str,
    message_id: str,
    reason_code: str,
    after_decision_path: Path | str,
) -> str:
    """Append a schema-valid override without mutating the original decision."""

    directory = Path(run_dir).resolve()
    verify_run_artifacts(config, directory)
    manifest_path = directory / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    events = _read_jsonl(directory / AUDIT_FILENAME)
    parent = next(
        (
            event
            for event in events
            if event.get("event_type") == "decision" and event.get("message_id") == message_id
        ),
        None,
    )
    if parent is None:
        raise OperationalRunError(
            component="human_override", message="parent decision event was not found"
        )
    after = json.loads(Path(after_decision_path).read_text(encoding="utf-8"))
    if not isinstance(after, dict) or after.get("message_id") != message_id:
        raise OperationalRunError(
            component="human_override", message="override decision message_id mismatch"
        )
    if after.get("decision_basis") != "human_override":
        raise OperationalRunError(
            component="human_override", message="override decision basis is invalid"
        )
    if reason_code not in config.vocab.human_override_reason_codes:
        raise OperationalRunError(
            component="human_override", message="override reason code is not approved"
        )
    _validate_decision(config, after)
    _scan_safe(config, after)

    event_id = f"{manifest['run_id']}-override-{uuid.uuid4().hex}"
    event = {
        "audit_schema_version": "3.0",
        "event_id": event_id,
        "event_type": "human_override",
        "run_id": manifest["run_id"],
        "occurred_at": _utc_now(),
        "message_id": message_id,
        "actor": {"type": "human", "role": "authorized-reviewer", "actor_ref": None},
        "configuration_version": config.bundle_version,
        "payload": {
            "parent_event_id": parent["event_id"],
            "before": parent["payload"]["result"],
            "after": after,
            "reason_code": reason_code,
            "note": None,
        },
    }
    _validate_audit(config, event)

    new_events = tuple(events + [event])
    _write_audit_atomic(config, directory / AUDIT_FILENAME, new_events)
    _append_override_sqlite_atomic(config, directory / SQLITE_FILENAME, event)
    manifest["output_artifact_digests"][AUDIT_FILENAME] = sha256_file(
        directory / AUDIT_FILENAME
    )
    manifest["output_artifact_digests"][SQLITE_FILENAME] = sha256_file(
        directory / SQLITE_FILENAME
    )
    manifest["last_override_at"] = event["occurred_at"]
    manifest["override_count"] = int(manifest.get("override_count", 0)) + 1
    _atomic_write_json(manifest_path, manifest)
    verify_run_artifacts(config, directory)
    return event_id


def _append_override_sqlite_atomic(
    config: AppConfig, path: Path, event: Mapping[str, Any]
) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(path, temporary)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary)
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute(
                "INSERT INTO audit_events "
                "(event_id, run_id, message_id, event_type, occurred_at, "
                "configuration_version, event_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event["event_id"],
                    event["run_id"],
                    event["message_id"],
                    event["event_type"],
                    event["occurred_at"],
                    config.bundle_version,
                    _stable_json(event),
                ),
            )
            connection.execute(
                "INSERT INTO human_overrides "
                "(event_id, run_id, message_id, parent_event_id, reason_code, override_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event["event_id"],
                    event["run_id"],
                    event["message_id"],
                    event["payload"]["parent_event_id"],
                    event["payload"]["reason_code"],
                    _stable_json(event["payload"]["after"]),
                ),
            )
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise OperationalRunError(
                component="sqlite", message="SQLite integrity check failed after override"
            )
        connection.close()
        connection = None
        _sync_file(temporary)
        os.replace(temporary, path)
    except Exception:
        if connection is not None:
            connection.rollback()
            connection.close()
        temporary.unlink(missing_ok=True)
        raise


def canonical_decision_digest(decisions: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(decisions, key=lambda item: str(item.get("message_id", "")))
    return hashlib.sha256(_stable_json(ordered).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protect_csv_formula(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ";".join(protect_csv_formula(str(item)) for item in value)
    return protect_csv_formula(str(value))


def _verify_csv(
    config: AppConfig, path: Path, expected_count: int
) -> list[dict[str, str]]:
    contract = config.component("export_contract")
    expected_columns = contract.get("csv_columns")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected_columns:
            raise OperationalRunError(
                component="csv_export", message="CSV columns do not match export contract"
            )
        rows = list(reader)
    if len(rows) != expected_count:
        raise OperationalRunError(
            component="csv_export", message="CSV row count is incorrect"
        )
    return rows


def _verify_audit(config: AppConfig, path: Path) -> list[dict[str, Any]]:
    events = _read_jsonl(path)
    for event in events:
        _validate_audit(config, event)
    return events


def _verify_sqlite(path: Path, *, decision_count: int, event_count: int) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise OperationalRunError(
                component="sqlite", message="SQLite integrity check failed"
            )
        counts = {
            "runs": 1,
            "configuration_versions": 1,
            "decisions": decision_count,
            "audit_events": event_count,
            "evaluation_summaries": 1,
        }
        for table, expected in counts.items():
            actual = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            if actual != (expected,):
                raise OperationalRunError(
                    component="sqlite", message="SQLite artifact count mismatch"
                )
    finally:
        connection.close()


def _scan_safe(config: AppConfig, *documents: object) -> None:
    forbidden_fields = {
        str(item).casefold()
        for item in config.component("export_contract").get("excluded_columns", [])
    }
    for document in documents:
        _scan_forbidden_keys(document, forbidden_fields)
    serialized = "\n".join(_stable_json(document) for document in documents)
    if (
        _PLAYER_ID_RE.search(serialized)
        or _WINDOWS_PATH_RE.search(serialized)
        or _POSIX_HOME_RE.search(serialized)
        or _MODEL_PATH_RE.search(serialized)
    ):
        raise OperationalRunError(
            component="safety_scan", message="forbidden identifier or path found in output"
        )
    for gate in config.component("safety_assertions").get("hard_gates", []):
        for pattern in gate.get("forbidden_output_patterns", []):
            try:
                compiled = re.compile(str(pattern))
            except re.error:
                compiled = re.compile(re.escape(str(pattern)))
            if compiled.search(serialized):
                raise OperationalRunError(
                    component="safety_scan", message="known sensitive fixture pattern found"
                )


def _scan_forbidden_keys(document: object, forbidden: set[str]) -> None:
    if isinstance(document, Mapping):
        for key, value in document.items():
            if str(key).casefold() in forbidden:
                raise OperationalRunError(
                    component="safety_scan", message="forbidden field found in output"
                )
            _scan_forbidden_keys(value, forbidden)
    elif isinstance(document, (list, tuple)):
        for item in document:
            _scan_forbidden_keys(item, forbidden)


def _validate_decision(config: AppConfig, decision: Mapping[str, Any]) -> None:
    schema_id = config.schema_registry.ids["output_schema.json"]
    config.schema_registry.validate(schema_id, decision, component_hint="phase05_decision")


def _validate_audit(config: AppConfig, event: Mapping[str, Any]) -> None:
    schema_id = config.schema_registry.ids["audit_event_schema.json"]
    config.schema_registry.validate(schema_id, event, component_hint="phase05_audit")


def _validate_evaluation_summary(config: AppConfig, summary: Mapping[str, Any]) -> None:
    schema_id = config.schema_registry.ids["evaluation_summary_schema.json"]
    config.schema_registry.validate(
        schema_id, summary, component_hint="phase05_evaluation_summary"
    )


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    _atomic_write_text(path, _stable_json(document) + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_failure_record(
    output_root: Path, run_id: str, configuration_version: str, exc: Exception
) -> None:
    failures = output_root / "failures"
    code = _failure_component(exc).upper()
    record = {
        "run_id": run_id,
        "status": "failed",
        "occurred_at": _utc_now(),
        "configuration_version": configuration_version,
        "failure_code": code,
        "sanitized_error": "RUN_FAILED_CLOSED",
    }
    try:
        _atomic_write_json(failures / f"{run_id}.json", record)
    except OSError:
        pass


def _failure_component(exc: Exception) -> str:
    if isinstance(exc, sqlite3.Error):
        return "database_failure"
    if isinstance(exc, OSError):
        return "output_write_failure"
    if isinstance(exc, ConfigurationError):
        return exc.component
    return "pipeline_failure"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise OperationalRunError(
                component="jsonl_export", message="JSONL line is not an object"
            )
        events.append(item)
    return events


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _resolve_input(config: AppConfig, input_path: Path | str | None) -> Path:
    if input_path is None:
        return (config.app_root / "input" / "dataset_player_messages.csv").resolve()
    return Path(input_path).resolve()


def _new_run_id(started_at: str) -> str:
    compact = started_at.replace("-", "").replace(":", "").replace(".", "")
    return f"run-{compact}-{uuid.uuid4().hex[:12]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _application_version() -> str:
    try:
        return package_version("player_triage")
    except PackageNotFoundError:  # pragma: no cover - editable install in normal use
        return "uninstalled"
