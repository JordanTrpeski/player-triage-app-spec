"""Phase 09 items 9-10: console import surface and walkthrough.

Covers the ConsoleService facade the Streamlit pages call. The UI itself is not
driven here; these tests pin the behaviour the pages depend on, including the
guarantee that the operator cannot choose a server-side destination and cannot
read outside the imported-run root.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from openpyxl import Workbook

from player_triage.console_service import ConsoleService, ConsoleServiceError
from player_triage.imported_runs import IMPORTED_RUNS_DIRNAME
from player_triage.ingestion import REQUIRED_COLUMNS
from player_triage.ui.pages import PAGE_RENDERERS


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
        "body": "My withdrawal has been pending for three days.",
    }
    row.update(overrides)
    return row


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(REQUIRED_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _xlsx_bytes(rows: list[dict[str, str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(REQUIRED_COLUMNS))
    for row in rows:
        sheet.append([row[column] for column in REQUIRED_COLUMNS])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture()
def service(app_root: Path, tmp_path: Path) -> ConsoleService:
    return ConsoleService(app_root, state_root=tmp_path / "state", output_root=tmp_path / "out")


def test_import_run_reports_counts_and_digest(service: ConsoleService) -> None:
    view = service.run_import(
        _csv_bytes([_row("M1"), _row("M2"), _row("M100")]),
        display_name="batch.csv",
    )

    assert view.status == "completed"
    assert (view.rows_seen, view.rows_accepted, view.rows_processed) == (3, 3, 3)
    assert view.rows_rejected == 0 and view.rows_failed == 0
    assert view.model_calls == 0
    assert view.policy_version == "policy-3.3.1"
    assert len(view.decision_digest) == 64
    assert view.rejected_rows == ()


def test_import_run_surfaces_rejected_rows(service: ConsoleService) -> None:
    view = service.run_import(
        _csv_bytes([_row("M1"), _row("NOPE"), _row("M3", market="Atlantis")]),
        display_name="mixed.csv",
    )

    assert view.status == "completed_with_errors"
    assert view.rows_rejected == 2
    assert len(view.rejected_rows) == 2
    for row in view.rejected_rows:
        assert set(row) >= {"source_row", "error_code", "explanation"}
        assert "P-00001" not in row["explanation"]


def test_import_accepts_xlsx(service: ConsoleService) -> None:
    view = service.run_import(_xlsx_bytes([_row("M1"), _row("M100")]), display_name="b.xlsx")
    assert view.status == "completed"
    assert view.rows_processed == 2


def test_padded_collision_is_opt_in(service: ConsoleService) -> None:
    payload = _csv_bytes([_row("M99"), _row("M099")])

    strict = service.run_import(payload, display_name="a.csv")
    assert strict.rows_rejected == 1
    assert strict.rejected_rows[0]["error_code"] == "ambiguous_padded_id_collision"

    permissive = service.run_import(payload, display_name="a.csv", collision_mode="allow")
    assert permissive.rows_rejected == 0
    assert permissive.rows_processed == 2


def test_exact_duplicate_is_an_error_even_in_allow_mode(service: ConsoleService) -> None:
    view = service.run_import(
        _csv_bytes([_row("M7"), _row("M7")]),
        display_name="dupe.csv",
        collision_mode="allow",
    )
    assert view.rows_rejected == 1
    assert view.rejected_rows[0]["error_code"] == "duplicate_source_message_id"


def test_unsupported_upload_format_is_rejected(service: ConsoleService) -> None:
    with pytest.raises(ConsoleServiceError):
        service.run_import(b"nope", display_name="notes.txt")


def test_runs_are_written_under_the_application_owned_root(
    service: ConsoleService, tmp_path: Path
) -> None:
    view = service.run_import(_csv_bytes([_row("M1")]), display_name="b.csv")
    root = tmp_path / "out" / IMPORTED_RUNS_DIRNAME
    assert (root / view.run_id).is_dir()


def test_artifacts_are_readable_by_run_id(service: ConsoleService) -> None:
    view = service.run_import(_csv_bytes([_row("M1")]), display_name="b.csv")

    decisions = service.read_import_artifact(view.run_id, "decisions.csv")
    manifest = service.read_import_artifact(view.run_id, "run_manifest.json")

    assert decisions is not None and b"source_message_id" in decisions
    assert manifest is not None and view.run_id.encode() in manifest


@pytest.mark.parametrize(
    "filename",
    ["../../../../Windows/System32/config/SAM", "..\\..\\secrets.txt", "policy_rules.json", ""],
)
def test_artifact_reads_are_restricted_to_an_allow_list(
    service: ConsoleService, filename: str
) -> None:
    view = service.run_import(_csv_bytes([_row("M1")]), display_name="b.csv")
    assert service.read_import_artifact(view.run_id, filename) is None


@pytest.mark.parametrize(
    "run_id",
    ["../../policy", "irun-../../x", "not-a-run-id", "", "irun-abc-zzzzzzzzzzzz"],
)
def test_artifact_reads_reject_crafted_run_ids(
    service: ConsoleService, run_id: str
) -> None:
    assert service.read_import_artifact(run_id, "decisions.csv") is None


def test_missing_artifact_returns_none(service: ConsoleService) -> None:
    view = service.run_import(_csv_bytes([_row("M1")]), display_name="b.csv")
    (Path(service.output_root) / IMPORTED_RUNS_DIRNAME / view.run_id / "audit.jsonl").unlink()
    assert service.read_import_artifact(view.run_id, "audit.jsonl") is None


def test_walkthrough_overview_states_the_delivered_runtime(
    service: ConsoleService,
) -> None:
    overview = service.walkthrough_overview()
    assert overview["processing_mode"] == "rules_only"
    assert overview["model_calls"] == 0
    assert overview["category_agreement"] == "40/40"
    assert overview["intent_agreement"] == "39/40"
    assert (
        overview["canonical_digest"]
        == "a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b"
    )


def test_console_exposes_import_and_walkthrough_pages() -> None:
    assert "Import" in PAGE_RENDERERS
    assert "Walkthrough" in PAGE_RENDERERS
    # the walkthrough is the first thing a reviewer lands on
    assert list(PAGE_RENDERERS)[0] == "Walkthrough"
