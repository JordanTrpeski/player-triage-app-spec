"""Isolated, auditable runs over operator-imported datasets.

Each imported batch is processed into its own directory beneath an
application-owned root::

    output/imported_runs/<run_id>/
        decisions.csv
        audit.jsonl
        validation_errors.csv
        run_manifest.json
        processing_summary.json

Design constraints, all deliberate:

* **The directory name is the internally generated ``run_id`` only.** No
  uploaded filename, source identifier, player identifier, subject or message
  content ever becomes a path component.
* **Runs are never overwritten.** Work happens in an exclusive temporary
  directory that is atomically renamed into place; an existing destination
  aborts the run.
* **The manifest is written before processing and finalized after the output
  files are closed**, so an interrupted run leaves ``started`` on disk rather
  than a silently truncated success.
* **Rejected rows are reported, never dropped.** ``rows_accepted +
  rows_rejected == rows_seen`` and ``rows_processed + rows_failed ==
  rows_accepted`` are enforced before the run is published.
* **The imported decision digest is deterministic**: it covers substantive
  decision fields only and excludes timestamps, ``run_id``, ``case_ref``,
  paths and durations, so repeating a run over identical input reproduces it.

This module does not touch the supplied-40 flow. policy-3.3.1,
``schemas/output_schema.json``, the ground-truth contract and the accepted
canonical digest are all unaffected.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from .config import AppConfig
from .engine import TriageEngine
from .errors import ConfigurationError
from .import_ingestion import ImportResult, load_imported
from .imported_identifiers import COLLISION_MODE_ERROR
from .ingestion import IngestionError
from .operational import OperationalRunError, sha256_file
from .pipeline import ingest_raw
from .records import ValidationIssue

IMPORTED_RUNS_DIRNAME: Final[str] = "imported_runs"
DECISIONS_CSV_FILENAME: Final[str] = "decisions.csv"
AUDIT_JSONL_FILENAME: Final[str] = "audit.jsonl"
VALIDATION_ERRORS_FILENAME: Final[str] = "validation_errors.csv"
RUN_MANIFEST_FILENAME: Final[str] = "run_manifest.json"
PROCESSING_SUMMARY_FILENAME: Final[str] = "processing_summary.json"

IMPORTED_DECISION_SCHEMA: Final[str] = "imported_decision_schema.json"
IMPORTED_OUTPUT_SCHEMA: Final[str] = "imported_output_schema.json"
IMPORTED_AUDIT_SCHEMA: Final[str] = "imported_audit_event_schema.json"

MANIFEST_VERSION: Final[str] = "1.0.0"
RULES_ONLY_MODE: Final[str] = "rules_only"

STATUS_STARTED: Final[str] = "started"
STATUS_COMPLETED: Final[str] = "completed"
STATUS_COMPLETED_WITH_ERRORS: Final[str] = "completed_with_errors"
STATUS_FAILED: Final[str] = "failed"

#: Substantive decision fields covered by the imported decision digest, in
#: canonical order. Volatile or machine-specific values (timestamps, run_id,
#: case_ref, paths, durations) are deliberately excluded so the digest is
#: reproducible across runs and machines.
DIGEST_FIELDS: Final[tuple[str, ...]] = (
    "source_message_id",
    "category",
    "intent",
    "secondary_intents",
    "priority",
    "route",
    "assigned_team",
    "secondary_teams",
    "auto_response_policy",
    "auto_response_template_id",
    "model_eligibility",
    "model_called",
    "human_review_required",
    "processing_status",
    "risk_flags",
    "sensitive_data_types",
    "reason_codes",
    "policy_basis_ids",
    "decision_basis",
    "market_framework_status",
    "market_overlay_codes",
    "decision_limited_by_missing_context",
    "missing_context",
    "required_context",
)

#: CSV columns for the rejected-row report.
VALIDATION_ERROR_COLUMNS: Final[tuple[str, ...]] = (
    "source_row",
    "source_message_id",
    "error_code",
    "field",
    "explanation",
    "processing_continued",
)

_FORMULA_PREFIXES: Final[tuple[str, ...]] = ("=", "+", "-", "@")

# Maps a validation issue code to the input field it concerns. Used only to
# populate a sanitized report column; never derived from source content.
_ISSUE_FIELDS: Final[Mapping[str, str]] = {
    "invalid_source_message_id": "msg_id",
    "duplicate_source_message_id": "msg_id",
    "ambiguous_padded_id_collision": "msg_id",
    "invalid_row": "row",
}


class ImportedRunError(ConfigurationError):
    """Raised when an imported run cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ImportedRunResult:
    """Outcome of one imported run."""

    run_id: str
    status: str
    run_dir: Path
    policy_version: str
    rows_seen: int
    rows_accepted: int
    rows_rejected: int
    rows_processed: int
    rows_failed: int
    decision_digest: str
    model_calls: int

    @property
    def had_errors(self) -> bool:
        return self.status == STATUS_COMPLETED_WITH_ERRORS


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _new_run_id(now: str | None = None) -> str:
    stamp = (now or _utc_now()).replace("-", "").replace(":", "").replace(".", "")
    return f"irun-{stamp}-{secrets.token_hex(6)}"


def _new_case_ref() -> str:
    return f"case-{secrets.token_hex(6)}"


def sanitize_display_name(name: str) -> str:
    """Return a safe *display* name for an uploaded file.

    This value is recorded in the manifest for operator convenience only. It is
    never used as a path component: run directories are named from the
    internally generated ``run_id``. Directory separators, drive letters,
    traversal segments and control characters are stripped so that a hostile
    filename cannot survive into a path even if a future caller misuses it.
    """

    base = name.replace("\\", "/").split("/")[-1]
    base = base.replace("\x00", "")
    cleaned = "".join(
        char for char in base if char.isprintable() and char not in '<>:"|?*'
    )
    cleaned = cleaned.strip(". ")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    if not cleaned:
        return "imported_file"
    return cleaned[:120]


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def imported_decision_digest(decisions: Sequence[Mapping[str, Any]]) -> str:
    """Deterministic digest over substantive imported-decision fields.

    Canonical ordering is by ``source_message_id`` numeric value, then by exact
    identifier text — the same deterministic rule used for row ordering. Each
    record is reduced to :data:`DIGEST_FIELDS`, so timestamps, ``run_id``,
    ``case_ref``, filesystem paths and durations cannot influence the result.
    """

    def sort_key(record: Mapping[str, Any]) -> tuple[int, str]:
        raw = str(record.get("source_message_id", ""))
        digits = raw[1:] if raw[:1] == "M" else ""
        return (int(digits) if digits.isdigit() else 0, raw)

    reduced = [
        {field: record.get(field) for field in DIGEST_FIELDS}
        for record in sorted(decisions, key=sort_key)
    ]
    return hashlib.sha256(_stable_json(reduced).encode("utf-8")).hexdigest()


def _protect_csv_formula(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ";".join(_protect_csv_formula(str(item)) for item in value)
    return _protect_csv_formula(str(value))


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON via a temporary file and atomic replace.

    A crash mid-write leaves the previous manifest intact rather than a
    truncated document.
    """

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(tmp, path)


def _write_validation_errors(path: Path, issues: Sequence[ValidationIssue]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(VALIDATION_ERROR_COLUMNS)
        for issue in issues:
            writer.writerow(
                [
                    _csv_value(issue.source_row),
                    _csv_value(issue.msg_id),
                    _csv_value(issue.code),
                    _csv_value(_ISSUE_FIELDS.get(issue.code, "row")),
                    _csv_value(issue.detail),
                    "true",
                ]
            )


def _write_decisions_csv(path: Path, decisions: Sequence[Mapping[str, Any]]) -> None:
    columns = ["source_message_id", "case_ref", "run_id", *DIGEST_FIELDS[1:]]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for decision in decisions:
            writer.writerow([_csv_value(decision.get(column)) for column in columns])


def _write_audit_jsonl(path: Path, events: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(_stable_json(event) + "\n")


def _validate(config: AppConfig, schema_file: str, document: Mapping[str, Any]) -> None:
    schema_id = config.schema_registry.ids.get(schema_file)
    if schema_id is None:  # pragma: no cover - registry auto-discovers schemas
        raise ImportedRunError(
            component="imported_run", message=f"{schema_file} is not registered"
        )
    validator = config.schema_registry.validator(schema_id)
    errors = [error.message for error in validator.iter_errors(document)]
    if errors:
        raise ImportedRunError(
            component="imported_run",
            message=f"imported record failed {schema_file} validation",
        )


def imported_runs_root(config: AppConfig) -> Path:
    """The application-owned root for imported runs."""

    return (config.app_root / "output" / IMPORTED_RUNS_DIRNAME).resolve()


def _prepare_root(root: Path) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ImportedRunError(
            component="output_write_failure",
            message="imported-run output root is unavailable",
        ) from exc
    if not root.is_dir() or not os.access(root, os.W_OK):
        raise ImportedRunError(
            component="output_write_failure",
            message="imported-run output root is unavailable",
        )


def _claim_work_dir(root: Path, run_id: str) -> tuple[Path, Path]:
    """Reserve a run destination, failing rather than overwriting."""

    final_dir = root / run_id
    work_dir = root / f".{run_id}.tmp"
    if final_dir.exists() or work_dir.exists():
        raise ImportedRunError(
            component="replay_protection",
            message="run destination already exists; prior output will not be overwritten",
        )
    try:
        # exist_ok=False: exclusive creation is the collision guard.
        work_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ImportedRunError(
            component="replay_protection",
            message="run destination already exists; prior output will not be overwritten",
        ) from exc
    except OSError as exc:
        raise ImportedRunError(
            component="output_write_failure",
            message="imported-run output root is unavailable",
        ) from exc
    return work_dir, final_dir


def _base_manifest(
    config: AppConfig,
    *,
    run_id: str,
    status: str,
    started_at: str,
    display_name: str,
    source_digest: str,
    source_format: str,
) -> dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_id,
        "status": status,
        "source_filename_sanitized": display_name,
        "source_file_sha256": source_digest,
        "source_format": source_format,
        "rows_seen": 0,
        "rows_accepted": 0,
        "rows_rejected": 0,
        "rows_processed": 0,
        "rows_failed": 0,
        "policy_version": config.bundle_version,
        "application_version": _application_version(),
        "processing_mode": RULES_ONLY_MODE,
        "model_enabled": False,
        "model_calls": 0,
        "started_at": started_at,
        "completed_at": None,
        "decision_digest": None,
        "output_files": [],
        "validation_summary": {
            "rows_rejected": 0,
            "codes": {},
            "all_rejected_rows_reported": True,
        },
    }


def _application_version() -> str:
    from . import __version__  # local import keeps module import cheap

    return str(__version__)


def run_imported_batch(
    config: AppConfig,
    source_path: Path | str,
    *,
    display_name: str | None = None,
    collision_mode: str = COLLISION_MODE_ERROR,
    output_root: Path | None = None,
) -> ImportedRunResult:
    """Process one imported file into an isolated run directory.

    ``output_root`` exists for tests; it defaults to the application-owned
    ``output/imported_runs`` root. The UI never offers a destination chooser.
    """

    source = Path(source_path)
    root = (output_root or imported_runs_root(config)).resolve()
    _prepare_root(root)

    started_at = _utc_now()
    run_id = _new_run_id(started_at)
    work_dir, final_dir = _claim_work_dir(root, run_id)

    safe_name = sanitize_display_name(display_name or source.name)
    manifest_path = work_dir / RUN_MANIFEST_FILENAME

    try:
        source_digest = sha256_file(source) if source.is_file() else ""
        manifest = _base_manifest(
            config,
            run_id=run_id,
            status=STATUS_STARTED,
            started_at=started_at,
            display_name=safe_name,
            source_digest=source_digest,
            source_format=source.suffix.lower().lstrip("."),
        )
        # Written before any processing: an interrupted run leaves `started`.
        _atomic_write_json(manifest_path, manifest)

        try:
            imported = load_imported(source, collision_mode=collision_mode)
        except (IngestionError, ValueError) as exc:
            # Structural failure before row processing.
            manifest["status"] = STATUS_FAILED
            manifest["completed_at"] = _utc_now()
            manifest["failure_reason"] = _sanitized_reason(exc)
            _atomic_write_json(manifest_path, manifest)
            _write_validation_errors(work_dir / VALIDATION_ERRORS_FILENAME, ())
            _write_summary(work_dir, manifest)
            os.replace(work_dir, final_dir)
            return _result(manifest, final_dir, config)

        result = _process(
            config,
            imported,
            run_id=run_id,
            work_dir=work_dir,
            manifest=manifest,
            manifest_path=manifest_path,
        )
        os.replace(work_dir, final_dir)
        return _result(result, final_dir, config)
    except Exception as exc:
        # Preserve evidence where safe: keep the work directory's manifest by
        # publishing it as a failed run rather than deleting the trail.
        try:
            manifest = _read_manifest(manifest_path)
            manifest["status"] = STATUS_FAILED
            manifest["completed_at"] = _utc_now()
            manifest["failure_reason"] = _sanitized_reason(exc)
            _atomic_write_json(manifest_path, manifest)
            _write_summary(work_dir, manifest)
            if not final_dir.exists():
                os.replace(work_dir, final_dir)
        except Exception:  # pragma: no cover - best-effort evidence retention
            shutil.rmtree(work_dir, ignore_errors=True)
        if isinstance(exc, ConfigurationError):
            raise
        raise ImportedRunError(
            component="imported_run",
            message="imported run failed closed; see run manifest",
        ) from exc


def _sanitized_reason(exc: Exception) -> str:
    """Return a sanitized failure reason with no path or source content."""

    if isinstance(exc, ConfigurationError):
        return exc.message
    return exc.__class__.__name__


def _read_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loaded: dict[str, Any] = json.load(handle)
    return loaded


def _process(
    config: AppConfig,
    imported: ImportResult,
    *,
    run_id: str,
    work_dir: Path,
    manifest: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    ingested = ingest_raw(config, imported.messages)
    engine = TriageEngine.from_config(
        config,
        mode=RULES_ONLY_MODE,
        output_schema_file=IMPORTED_DECISION_SCHEMA,
    )

    published: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    failures: list[ValidationIssue] = []
    model_calls = 0

    try:
        for message in ingested:
            try:
                classified = engine.classify(message)
                decision = dict(classified.decision)
                if decision.get("model_called") is not False:
                    raise ImportedRunError(
                        component="model_gate",
                        message="imported runs are rules-only; a model call was reported",
                    )
                if not classified.schema_valid or classified.semantic_violations:
                    raise ImportedRunError(
                        component="semantic_validation",
                        message="row result failed imported-run validation",
                    )

                case_ref = _new_case_ref()
                record = dict(decision)
                record.pop("message_id", None)
                record["source_message_id"] = message.msg_id
                record["case_ref"] = case_ref
                record["run_id"] = run_id
                _validate(config, IMPORTED_OUTPUT_SCHEMA, record)
                published.append(record)

                event = engine.build_decision_audit_event(
                    classified, run_id=run_id, processing_time_ms=0
                )
                event["event_id"] = f"{run_id}-decision-{case_ref}"
                event["occurred_at"] = _utc_now()
                _validate(config, IMPORTED_AUDIT_SCHEMA, event)
                events.append(event)
            except Exception as exc:
                # Partial failure: this row fails, the batch continues, and the
                # failure is reported rather than dropped.
                failures.append(
                    ValidationIssue(
                        msg_id=message.msg_id,
                        source_row=None,
                        code="processing_failure",
                        detail=_sanitized_reason(exc),
                    )
                )
    finally:
        engine.close()

    all_issues = tuple(imported.issues) + tuple(failures)
    _write_decisions_csv(work_dir / DECISIONS_CSV_FILENAME, published)
    _write_audit_jsonl(work_dir / AUDIT_JSONL_FILENAME, events)
    _write_validation_errors(work_dir / VALIDATION_ERRORS_FILENAME, all_issues)

    digest = imported_decision_digest(published)
    rows_processed = len(published)
    rows_failed = len(failures)

    manifest.update(
        {
            "status": (
                STATUS_COMPLETED
                if not all_issues
                else STATUS_COMPLETED_WITH_ERRORS
            ),
            "rows_seen": imported.rows_seen,
            "rows_accepted": imported.accepted_count,
            "rows_rejected": imported.rejected_count,
            "rows_processed": rows_processed,
            "rows_failed": rows_failed,
            "model_calls": model_calls,
            "completed_at": _utc_now(),
            "decision_digest": digest,
            "output_files": sorted(
                [
                    DECISIONS_CSV_FILENAME,
                    AUDIT_JSONL_FILENAME,
                    VALIDATION_ERRORS_FILENAME,
                    RUN_MANIFEST_FILENAME,
                    PROCESSING_SUMMARY_FILENAME,
                ]
            ),
            "validation_summary": _validation_summary(all_issues),
        }
    )
    _assert_row_accounting(manifest)
    _atomic_write_json(manifest_path, manifest)
    _write_summary(work_dir, manifest)
    return manifest


def _validation_summary(issues: Sequence[ValidationIssue]) -> dict[str, Any]:
    codes: dict[str, int] = {}
    for issue in issues:
        codes[issue.code] = codes.get(issue.code, 0) + 1
    return {
        "rows_rejected": len(issues),
        "codes": dict(sorted(codes.items())),
        "all_rejected_rows_reported": True,
    }


def _assert_row_accounting(manifest: Mapping[str, Any]) -> None:
    seen = int(manifest["rows_seen"])
    accepted = int(manifest["rows_accepted"])
    rejected = int(manifest["rows_rejected"])
    processed = int(manifest["rows_processed"])
    failed = int(manifest["rows_failed"])
    if accepted + rejected != seen:
        raise ImportedRunError(
            component="row_accounting",
            message="rows_accepted + rows_rejected must equal rows_seen",
        )
    if processed + failed != accepted:
        raise ImportedRunError(
            component="row_accounting",
            message="rows_processed + rows_failed must equal rows_accepted",
        )


def _write_summary(work_dir: Path, manifest: Mapping[str, Any]) -> None:
    summary = {
        "run_id": manifest["run_id"],
        "status": manifest["status"],
        "rows_seen": manifest["rows_seen"],
        "rows_accepted": manifest["rows_accepted"],
        "rows_rejected": manifest["rows_rejected"],
        "rows_processed": manifest["rows_processed"],
        "rows_failed": manifest["rows_failed"],
        "decision_digest": manifest["decision_digest"],
        "policy_version": manifest["policy_version"],
        "processing_mode": manifest["processing_mode"],
        "model_calls": manifest["model_calls"],
        "validation_summary": manifest["validation_summary"],
    }
    _atomic_write_json(work_dir / PROCESSING_SUMMARY_FILENAME, summary)


def _result(
    manifest: Mapping[str, Any], run_dir: Path, config: AppConfig
) -> ImportedRunResult:
    return ImportedRunResult(
        run_id=str(manifest["run_id"]),
        status=str(manifest["status"]),
        run_dir=run_dir,
        policy_version=str(manifest["policy_version"]),
        rows_seen=int(manifest["rows_seen"]),
        rows_accepted=int(manifest["rows_accepted"]),
        rows_rejected=int(manifest["rows_rejected"]),
        rows_processed=int(manifest["rows_processed"]),
        rows_failed=int(manifest["rows_failed"]),
        decision_digest=str(manifest["decision_digest"] or ""),
        model_calls=int(manifest["model_calls"]),
    )
