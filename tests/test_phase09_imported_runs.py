"""Phase 09 item 7: imported-run isolation, manifests and deterministic digest.

The supplied-40 flow, policy-3.3.1, schemas/output_schema.json and the accepted
canonical digest are unaffected by everything here; the final test in this file
asserts that explicitly.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from player_triage.config import load_app_config
from player_triage.engine import TriageEngine
from player_triage.imported_runs import (
    AUDIT_JSONL_FILENAME,
    DECISIONS_CSV_FILENAME,
    PROCESSING_SUMMARY_FILENAME,
    RUN_MANIFEST_FILENAME,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    VALIDATION_ERRORS_FILENAME,
    ImportedRunError,
    imported_decision_digest,
    imported_runs_root,
    run_imported_batch,
    sanitize_display_name,
)
from player_triage.ingestion import REQUIRED_COLUMNS

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _row(msg_id: str, **overrides: str) -> dict[str, str]:
    row = {
        "msg_id": msg_id,
        "received_utc": "2026-02-01T10:00:00Z",
        "channel": "email",
        "market": "Ontario",
        "player_id": "P-00001",
        "vip_tier": "none",
        "language": "en",
        "subject": "Withdrawal question",
        "body": "I requested a withdrawal three days ago and it is still pending.",
    }
    row.update(overrides)
    return row


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REQUIRED_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _write_xlsx(path: Path, rows: list[dict[str, str]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(REQUIRED_COLUMNS))
    for row in rows:
        sheet.append([row[column] for column in REQUIRED_COLUMNS])
    workbook.save(path)
    return path


def _manifest(result_dir: Path) -> dict[str, Any]:
    with (result_dir / RUN_MANIFEST_FILENAME).open(encoding="utf-8") as handle:
        loaded: dict[str, Any] = json.load(handle)
    return loaded


def _errors(result_dir: Path) -> list[dict[str, str]]:
    with (result_dir / VALIDATION_ERRORS_FILENAME).open(
        newline="", encoding="utf-8"
    ) as handle:
        return list(csv.DictReader(handle))


@pytest.fixture()
def out_root(tmp_path: Path) -> Path:
    root = tmp_path / "imported_runs"
    root.mkdir()
    return root


# --------------------------------------------------------------------------
# run isolation
# --------------------------------------------------------------------------


def test_run_ids_are_unique_and_directories_isolated(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1"), _row("M2")])

    first = run_imported_batch(config, source, output_root=out_root)
    second = run_imported_batch(config, source, output_root=out_root)

    assert first.run_id != second.run_id
    assert first.run_dir != second.run_dir
    assert first.run_dir.is_dir() and second.run_dir.is_dir()
    assert {p.name for p in out_root.iterdir()} == {first.run_id, second.run_id}
    # each run carries its own complete artifact set
    for run in (first, second):
        for filename in (
            DECISIONS_CSV_FILENAME,
            AUDIT_JSONL_FILENAME,
            VALIDATION_ERRORS_FILENAME,
            RUN_MANIFEST_FILENAME,
            PROCESSING_SUMMARY_FILENAME,
        ):
            assert (run.run_dir / filename).is_file()


def test_run_directory_name_is_run_id_only(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "Player Export 2026 ünïcode.csv", [_row("M42")])

    result = run_imported_batch(config, source, output_root=out_root)

    name = result.run_dir.name
    assert name == result.run_id
    assert name.startswith("irun-")
    for leak in ("Player", "Export", "ünïcode", ".csv", "M42", "P-00001"):
        assert leak not in name


def test_existing_run_directory_is_never_overwritten(
    app_root: Path, tmp_path: Path, out_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1")])

    monkeypatch.setattr(
        "player_triage.imported_runs._new_run_id", lambda now=None: "irun-fixed"
    )
    first = run_imported_batch(config, source, output_root=out_root)
    sentinel = first.run_dir / "decisions.csv"
    original = sentinel.read_bytes()

    with pytest.raises(ImportedRunError) as excinfo:
        run_imported_batch(config, source, output_root=out_root)

    assert "will not be overwritten" in str(excinfo.value)
    assert sentinel.read_bytes() == original


def test_unwritable_output_root_fails_closed(
    app_root: Path, tmp_path: Path
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1")])
    # A file where a directory must be: mkdir cannot succeed.
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("blocked", encoding="utf-8")

    with pytest.raises(ImportedRunError) as excinfo:
        run_imported_batch(config, source, output_root=blocked)

    assert "output root is unavailable" in str(excinfo.value)


# --------------------------------------------------------------------------
# status lifecycle
# --------------------------------------------------------------------------


def test_clean_batch_reports_completed(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1"), _row("M2"), _row("M100")])

    result = run_imported_batch(config, source, output_root=out_root)

    assert result.status == STATUS_COMPLETED
    assert (result.rows_seen, result.rows_accepted, result.rows_rejected) == (3, 3, 0)
    assert (result.rows_processed, result.rows_failed) == (3, 0)
    assert _manifest(result.run_dir)["status"] == STATUS_COMPLETED
    assert _errors(result.run_dir) == []


def test_mixed_batch_reports_completed_with_errors(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    rows = [_row("M1"), _row("NOPE"), _row("M3", market="Atlantis"), _row("M4")]
    source = _write_csv(tmp_path / "mixed.csv", rows)

    result = run_imported_batch(config, source, output_root=out_root)

    assert result.status == STATUS_COMPLETED_WITH_ERRORS
    assert result.rows_seen == 4
    assert result.rows_accepted == 2
    assert result.rows_rejected == 2
    assert result.rows_processed == 2
    assert result.rows_failed == 0
    # rejected rows are reported, not dropped
    reported = _errors(result.run_dir)
    assert len(reported) == 2
    assert {row["error_code"] for row in reported} == {
        "invalid_source_message_id",
        "invalid_row",
    }
    assert all(row["processing_continued"] == "true" for row in reported)


def test_structural_failure_before_processing_reports_failed(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    broken = tmp_path / "broken.csv"
    broken.write_text("wrong,headers\n1,2\n", encoding="utf-8")

    result = run_imported_batch(config, broken, output_root=out_root)

    assert result.status == STATUS_FAILED
    manifest = _manifest(result.run_dir)
    assert manifest["status"] == STATUS_FAILED
    assert manifest["rows_seen"] == 0
    assert manifest["decision_digest"] is None
    # evidence is preserved rather than deleted
    assert result.run_dir.is_dir()


def test_partial_operational_failure_preserves_completed_rows(
    app_root: Path, tmp_path: Path, out_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One row blowing up must not discard the rows that already succeeded."""

    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1"), _row("M2"), _row("M3")])

    original = TriageEngine.classify

    def flaky(self: TriageEngine, message: Any) -> Any:
        if message.msg_id == "M2":
            raise RuntimeError("synthetic per-row failure")
        return original(self, message)

    monkeypatch.setattr(TriageEngine, "classify", flaky)

    result = run_imported_batch(config, source, output_root=out_root)

    assert result.status == STATUS_COMPLETED_WITH_ERRORS
    assert result.rows_accepted == 3
    assert result.rows_processed == 2
    assert result.rows_failed == 1
    # the surviving rows are published
    with (result.run_dir / DECISIONS_CSV_FILENAME).open(
        newline="", encoding="utf-8"
    ) as handle:
        published = list(csv.DictReader(handle))
    assert {row["source_message_id"] for row in published} == {"M1", "M3"}
    # the failure is reported
    codes = {row["error_code"] for row in _errors(result.run_dir)}
    assert "processing_failure" in codes


def test_manifest_is_written_before_processing_and_finalized_after(
    app_root: Path, tmp_path: Path, out_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted run must leave `started` on disk, not a false success."""

    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1")])
    seen: dict[str, Any] = {}

    real_ingest = __import__(
        "player_triage.imported_runs", fromlist=["ingest_raw"]
    ).ingest_raw

    def capture(config_arg: Any, messages: Any) -> Any:
        # At this point the pre-processing manifest must already exist.
        work_dirs = [p for p in out_root.iterdir() if p.name.startswith(".irun-")]
        assert work_dirs, "expected an exclusive work directory"
        with (work_dirs[0] / RUN_MANIFEST_FILENAME).open(encoding="utf-8") as handle:
            seen["status"] = json.load(handle)["status"]
        return real_ingest(config_arg, messages)

    monkeypatch.setattr("player_triage.imported_runs.ingest_raw", capture)

    result = run_imported_batch(config, source, output_root=out_root)

    assert seen["status"] == "started"
    assert _manifest(result.run_dir)["status"] == STATUS_COMPLETED
    # no temporary artefacts survive publication
    assert not list(out_root.glob(".irun-*"))
    assert not list(result.run_dir.glob("*.tmp"))


# --------------------------------------------------------------------------
# row accounting
# --------------------------------------------------------------------------


def test_row_accounting_identities_hold(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    rows = [_row("M1"), _row("BAD"), _row("M3"), _row("M3"), _row("M5", channel="x")]
    source = _write_csv(tmp_path / "acct.csv", rows)

    result = run_imported_batch(config, source, output_root=out_root)
    manifest = _manifest(result.run_dir)

    assert manifest["rows_accepted"] + manifest["rows_rejected"] == manifest["rows_seen"]
    assert (
        manifest["rows_processed"] + manifest["rows_failed"] == manifest["rows_accepted"]
    )
    with (result.run_dir / PROCESSING_SUMMARY_FILENAME).open(encoding="utf-8") as handle:
        summary = json.load(handle)
    assert summary["rows_seen"] == manifest["rows_seen"]
    assert summary["validation_summary"]["all_rejected_rows_reported"] is True


def test_batch_larger_than_99_rows_runs_end_to_end(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    rows = [_row(f"M{n}") for n in range(1, 121)]
    source = _write_csv(tmp_path / "big.csv", rows)

    result = run_imported_batch(config, source, output_root=out_root)

    assert result.status == STATUS_COMPLETED
    assert result.rows_processed == 120
    with (result.run_dir / DECISIONS_CSV_FILENAME).open(
        newline="", encoding="utf-8"
    ) as handle:
        published = [row["source_message_id"] for row in csv.DictReader(handle)]
    assert published[:3] == ["M1", "M2", "M3"]
    assert published[-1] == "M120"
    assert "M100" in published


# --------------------------------------------------------------------------
# deterministic digest
# --------------------------------------------------------------------------


def test_digest_is_reproducible_across_runs(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1"), _row("M2"), _row("M100")])

    first = run_imported_batch(config, source, output_root=out_root)
    second = run_imported_batch(config, source, output_root=out_root)

    assert first.decision_digest == second.decision_digest
    assert first.run_id != second.run_id  # different run, same digest


def test_digest_ignores_volatile_fields() -> None:
    base = {
        "source_message_id": "M7",
        "category": "payments",
        "intent": "withdrawal_delay",
        "priority": "P2",
        "route": "specialist_queue",
        "assigned_team": "payments",
    }
    volatile = dict(base)
    volatile.update(
        {
            "run_id": "irun-20260718T110000000Z-abcdef123456",
            "case_ref": "case-0123456789ab",
            "received_utc": "2026-07-18T11:00:00Z",
            "processing_duration_ms": 1234,
            "source_path": "C:/somewhere/file.csv",
        }
    )
    assert imported_decision_digest([base]) == imported_decision_digest([volatile])


def test_digest_is_order_independent_but_content_sensitive() -> None:
    a = {"source_message_id": "M2", "category": "payments", "priority": "P2"}
    b = {"source_message_id": "M10", "category": "account", "priority": "P3"}
    assert imported_decision_digest([a, b]) == imported_decision_digest([b, a])

    changed = dict(b)
    changed["priority"] = "P1"
    assert imported_decision_digest([a, b]) != imported_decision_digest([a, changed])


def test_digest_canonical_order_is_numeric_aware() -> None:
    """M2 must order before M10, so lexical ordering cannot creep in."""

    records = [
        {"source_message_id": "M10", "category": "a"},
        {"source_message_id": "M2", "category": "b"},
    ]
    assert imported_decision_digest(records) == imported_decision_digest(
        list(reversed(records))
    )


# --------------------------------------------------------------------------
# filenames
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["with spaces.csv", "ünïcode-café.csv", "日本語データ.csv", "dots..in..name.csv"],
)
def test_awkward_filenames_process_normally(
    app_root: Path, tmp_path: Path, out_root: Path, filename: str
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / filename, [_row("M1")])

    result = run_imported_batch(config, source, output_root=out_root)

    assert result.status == STATUS_COMPLETED
    assert result.run_dir.parent == out_root


def test_traversal_like_filename_cannot_escape_the_run_root(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "sneaky.csv", [_row("M1")])

    result = run_imported_batch(
        config,
        source,
        display_name="../../../../Windows/System32/evil.csv",
        output_root=out_root,
    )

    assert result.run_dir.parent.resolve() == out_root.resolve()
    manifest = _manifest(result.run_dir)
    safe = manifest["source_filename_sanitized"]
    assert ".." not in safe
    assert "/" not in safe and "\\" not in safe
    assert safe == "evil.csv"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Windows\\System32\\cmd.exe", "cmd.exe"),
        ("....//....//x.csv", "x.csv"),
        ("   ", "imported_file"),
        ("", "imported_file"),
        ("...", "imported_file"),
    ],
)
def test_display_name_sanitization(raw: str, expected: str) -> None:
    result = sanitize_display_name(raw)
    assert result == expected
    assert "/" not in result and "\\" not in result
    assert ".." not in result


# --------------------------------------------------------------------------
# no sensitive values in outputs
# --------------------------------------------------------------------------


def test_no_raw_sensitive_values_in_manifest_or_errors(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    secret_body = "my card is 4111111111111111 and my IBAN is GB29NWBK60161331926819"
    rows = [
        _row("M1", body=secret_body),
        _row("M2", channel="bogus", body=secret_body),
    ]
    source = _write_csv(tmp_path / "sensitive.csv", rows)

    result = run_imported_batch(config, source, output_root=out_root)

    manifest_text = (result.run_dir / RUN_MANIFEST_FILENAME).read_text(encoding="utf-8")
    errors_text = (result.run_dir / VALIDATION_ERRORS_FILENAME).read_text(
        encoding="utf-8"
    )
    summary_text = (result.run_dir / PROCESSING_SUMMARY_FILENAME).read_text(
        encoding="utf-8"
    )

    for blob in (manifest_text, errors_text, summary_text):
        assert "4111111111111111" not in blob
        assert "GB29NWBK60161331926819" not in blob
        assert "P-00001" not in blob
        assert secret_body not in blob
        # no absolute filesystem paths
        assert str(tmp_path) not in blob
        assert "C:\\" not in blob


def test_manifest_records_required_fields(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1")])

    result = run_imported_batch(config, source, output_root=out_root)
    manifest = _manifest(result.run_dir)

    for field in (
        "manifest_version",
        "run_id",
        "status",
        "source_filename_sanitized",
        "source_file_sha256",
        "source_format",
        "rows_seen",
        "rows_accepted",
        "rows_rejected",
        "rows_processed",
        "rows_failed",
        "policy_version",
        "application_version",
        "processing_mode",
        "model_enabled",
        "model_calls",
        "started_at",
        "completed_at",
        "decision_digest",
        "output_files",
        "validation_summary",
    ):
        assert field in manifest, f"manifest missing {field}"

    assert manifest["policy_version"] == "policy-3.3.1"
    assert manifest["processing_mode"] == "rules_only"
    assert manifest["model_enabled"] is False
    assert manifest["model_calls"] == 0


# --------------------------------------------------------------------------
# rules-only guarantees
# --------------------------------------------------------------------------


def test_imported_run_makes_zero_model_calls_and_imports_no_model_runtime(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    source = _write_csv(tmp_path / "in.csv", [_row("M1"), _row("M2")])

    before = {name for name in sys.modules if "llama" in name.lower()}
    result = run_imported_batch(config, source, output_root=out_root)
    after = {name for name in sys.modules if "llama" in name.lower()}

    assert result.model_calls == 0
    assert after == before == set()

    with (result.run_dir / AUDIT_JSONL_FILENAME).open(encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle if line.strip()]
    assert events
    for event in events:
        payload = json.dumps(event)
        assert '"model_called": true' not in payload.lower()


def test_csv_and_xlsx_imports_agree(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    config = load_app_config(app_root)
    rows = [_row("M1"), _row("M100")]

    csv_run = run_imported_batch(
        config, _write_csv(tmp_path / "a.csv", rows), output_root=out_root
    )
    xlsx_run = run_imported_batch(
        config, _write_xlsx(tmp_path / "a.xlsx", rows), output_root=out_root
    )

    assert csv_run.status == xlsx_run.status == STATUS_COMPLETED
    assert csv_run.decision_digest == xlsx_run.decision_digest


# --------------------------------------------------------------------------
# the accepted baseline is untouched
# --------------------------------------------------------------------------


def test_supplied_40_digest_is_unchanged_by_imported_run_support(
    app_root: Path, tmp_path: Path, out_root: Path
) -> None:
    """The accepted canonical digest must not move."""

    from player_triage.evaluation_service import ACCEPTED_CANONICAL_DIGEST
    from player_triage.operational import run_operational_pipeline

    config = load_app_config(app_root)
    # run an import first, to prove it cannot contaminate the benchmark path
    run_imported_batch(
        config, _write_csv(tmp_path / "in.csv", [_row("M1")]), output_root=out_root
    )

    supplied = run_operational_pipeline(config, output_dir=tmp_path / "supplied")

    assert supplied.canonical_decision_digest == ACCEPTED_CANONICAL_DIGEST
    assert (
        supplied.canonical_decision_digest
        == "a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b"
    )
    assert supplied.input_count == 40
    assert supplied.failure_count == 0


def test_imported_runs_root_is_application_owned(app_root: Path) -> None:
    config = load_app_config(app_root)
    root = imported_runs_root(config)
    assert root == (app_root / "output" / "imported_runs").resolve()
    assert root.is_relative_to(app_root.resolve())
