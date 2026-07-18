"""Phase 09 corrective patch: template, preview, progress/status, recent runs."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from openpyxl import Workbook

from player_triage.console_service import ConsoleService, ConsoleServiceError
from player_triage.import_ingestion import MAX_IMPORT_ROWS
from player_triage.ingestion import REQUIRED_COLUMNS


def _row(msg_id: str, **over: str) -> dict[str, str]:
    row = {
        "msg_id": msg_id,
        "received_utc": "2026-02-01T10:00:00Z",
        "channel": "email",
        "market": "Ontario",
        "player_id": "P-00001",
        "vip_tier": "none",
        "language": "en",
        "subject": "Withdrawal question about my pending payout request today",
        "body": "card 4111111111111111 and password hunter2",
    }
    row.update(over)
    return row


def _csv_bytes(rows: list[dict[str, str]], columns: list[str] | None = None) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=columns or list(REQUIRED_COLUMNS), lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in (columns or REQUIRED_COLUMNS)})
    return buffer.getvalue().encode("utf-8")


def _xlsx_bytes(rows: list[dict[str, str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(REQUIRED_COLUMNS))
    for row in rows:
        sheet.append([row[c] for c in REQUIRED_COLUMNS])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture()
def service(app_root: Path, tmp_path: Path) -> ConsoleService:
    return ConsoleService(
        app_root, state_root=tmp_path / "state", output_root=tmp_path / "out"
    )


# --------------------------------------------------------------------------
# downloadable template
# --------------------------------------------------------------------------


def test_template_matches_the_fixed_column_contract(service: ConsoleService) -> None:
    payload = service.import_template_csv()
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8"))))
    header = list(csv.reader(io.StringIO(payload.decode("utf-8"))))[0]

    assert header == list(REQUIRED_COLUMNS)
    assert len(rows) == 1, "template carries exactly one synthetic example row"


def test_template_contains_no_real_or_sensitive_data(service: ConsoleService) -> None:
    text = service.import_template_csv().decode("utf-8")
    assert "EXAMPLE ROW" in text
    assert "P-00000" in text  # obviously synthetic
    for forbidden in ("4111111111111111", "hunter2", "GB29NWBK"):
        assert forbidden not in text


def test_template_round_trips_through_the_importer(
    service: ConsoleService,
) -> None:
    """The template must import cleanly, or it is not a usable starting point.

    It uses the imported identifier form (M1), which the strict supplied-40
    benchmark loader deliberately rejects. The template targets the import
    path, not the benchmark.
    """

    result = service.run_import(
        service.import_template_csv(), display_name="template.csv"
    )
    assert result.status == "completed"
    assert result.rows_processed == 1
    assert result.model_calls == 0


# --------------------------------------------------------------------------
# preview
# --------------------------------------------------------------------------


def test_preview_reports_structure_without_processing(
    service: ConsoleService, tmp_path: Path
) -> None:
    payload = _csv_bytes([_row("M1"), _row("M2"), _row("M100")])

    preview = service.preview_import(payload, display_name="Player Export.csv")

    assert preview.display_name == "Player Export.csv"
    assert preview.detected_format == "csv"
    assert preview.row_count == 3
    assert preview.detected_columns == tuple(REQUIRED_COLUMNS)
    assert preview.columns_ok
    assert len(preview.sample_rows) == 3
    assert not preview.truncated
    # nothing was created
    assert not (tmp_path / "out").exists()


def test_preview_detects_xlsx(service: ConsoleService) -> None:
    preview = service.preview_import(
        _xlsx_bytes([_row("M1"), _row("M2")]), display_name="batch.xlsx"
    )
    assert preview.detected_format == "xlsx"
    assert preview.row_count == 2


def test_preview_reports_column_problems(service: ConsoleService) -> None:
    columns = [c for c in REQUIRED_COLUMNS if c != "market"] + ["extra_column"]
    preview = service.preview_import(
        _csv_bytes([_row("M1")], columns=columns), display_name="bad.csv"
    )

    assert not preview.columns_ok
    assert "market" in preview.missing_columns
    assert "extra_column" in preview.unexpected_columns


def test_preview_does_not_expose_bodies_and_truncates_subjects(
    service: ConsoleService,
) -> None:
    preview = service.preview_import(
        _csv_bytes([_row("M1")]), display_name="sensitive.csv"
    )

    sample = preview.sample_rows[0]
    assert "body" not in sample
    blob = " ".join(sample.values())
    assert "4111111111111111" not in blob
    assert "hunter2" not in blob
    assert "player_id" not in sample and "P-00001" not in blob
    assert sample["subject_preview"].endswith("…")
    assert sample["msg_id"] == "M1"
    assert sample["market"] == "Ontario"


def test_preview_limits_sample_and_flags_truncation(service: ConsoleService) -> None:
    preview = service.preview_import(
        _csv_bytes([_row(f"M{n}") for n in range(1, 21)]),
        display_name="big.csv",
        max_rows=5,
    )
    assert preview.row_count == 20
    assert len(preview.sample_rows) == 5
    assert preview.truncated is True


def test_preview_rejects_unsupported_format(service: ConsoleService) -> None:
    with pytest.raises(ConsoleServiceError):
        service.preview_import(b"nope", display_name="notes.txt")


def test_preview_sanitizes_the_display_name(service: ConsoleService) -> None:
    preview = service.preview_import(
        _csv_bytes([_row("M1")]), display_name="../../../../etc/evil.csv"
    )
    assert preview.display_name == "evil.csv"
    assert ".." not in preview.display_name


def test_preview_row_count_enables_over_limit_warning(service: ConsoleService) -> None:
    """The page compares preview.row_count with the configured limit."""

    preview = service.preview_import(_csv_bytes([_row("M1")]), display_name="a.csv")
    assert preview.row_count <= MAX_IMPORT_ROWS


# --------------------------------------------------------------------------
# recent runs
# --------------------------------------------------------------------------


def test_recent_runs_is_empty_before_any_import(service: ConsoleService) -> None:
    assert service.recent_imported_runs() == ()


def test_recent_runs_lists_completed_runs_newest_first(
    service: ConsoleService,
) -> None:
    first = service.run_import(_csv_bytes([_row("M1")]), display_name="one.csv")
    second = service.run_import(
        _csv_bytes([_row("M1"), _row("BAD")]), display_name="two.csv"
    )

    runs = service.recent_imported_runs()

    assert [r.run_id for r in runs] == [second.run_id, first.run_id]
    assert runs[0].status == "completed_with_errors"
    assert runs[1].status == "completed"
    assert runs[0].rows_rejected == 1
    assert runs[1].policy_version == "policy-3.3.1"
    assert runs[1].decision_digest


def test_recent_runs_exposes_only_safe_metadata(service: ConsoleService) -> None:
    service.run_import(_csv_bytes([_row("M1")]), display_name="sensitive.csv")

    run = service.recent_imported_runs()[0]
    blob = " ".join(str(v) for v in vars(run).values()) if hasattr(run, "__dict__") else (
        f"{run.run_id} {run.status} {run.started_at} {run.completed_at} "
        f"{run.source_filename_sanitized} {run.policy_version} {run.decision_digest}"
    )
    for forbidden in ("4111111111111111", "hunter2", "P-00001", "Withdrawal question"):
        assert forbidden not in blob


def test_recent_runs_honours_limit(service: ConsoleService) -> None:
    for _ in range(3):
        service.run_import(_csv_bytes([_row("M1")]), display_name="a.csv")
    assert len(service.recent_imported_runs(limit=2)) == 2


def test_recent_runs_skips_corrupt_manifests(
    service: ConsoleService, tmp_path: Path
) -> None:
    good = service.run_import(_csv_bytes([_row("M1")]), display_name="good.csv")
    broken_dir = (
        tmp_path / "out" / "imported_runs" / "irun-20260101T000000000Z-aaaaaaaaaaaa"
    )
    broken_dir.mkdir(parents=True)
    (broken_dir / "run_manifest.json").write_text("{ not json", encoding="utf-8")

    runs = service.recent_imported_runs()

    assert [r.run_id for r in runs] == [good.run_id]


def test_recent_run_artifacts_remain_downloadable(service: ConsoleService) -> None:
    service.run_import(_csv_bytes([_row("M1")]), display_name="a.csv")
    run = service.recent_imported_runs()[0]

    for filename in (
        "decisions.csv",
        "validation_errors.csv",
        "run_manifest.json",
        "processing_summary.json",
        "audit.jsonl",
    ):
        assert service.read_import_artifact(run.run_id, filename) is not None
