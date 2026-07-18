"""Phase 09: imported-dataset identifiers and fault-tolerant import.

The supplied-40 benchmark contract (``^M\\d{2}$``, M01-M40, its ground truth,
its policy validators and its canonical digest) is unaffected by everything
here. These tests cover the separate imported-data path only.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from openpyxl import Workbook

from player_triage.import_ingestion import (
    CODE_DUPLICATE_SOURCE_MESSAGE_ID,
    CODE_INVALID_ROW,
    CODE_INVALID_SOURCE_MESSAGE_ID,
    CODE_NUMERIC_COLLISION,
    load_imported,
    load_imported_csv,
    load_imported_xlsx,
)
from player_triage.imported_identifiers import (
    COLLISION_MODE_ALLOW,
    ImportedIdentifierError,
    imported_id_sort_key,
    is_valid_imported_message_id,
    parse_imported_message_id,
    sort_imported_ids,
)
from player_triage.ingestion import REQUIRED_COLUMNS, IngestionError, load_csv

# --------------------------------------------------------------------------
# fixtures / helpers
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
        "subject": "Account question",
        "body": "I have a question about my account balance.",
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


# --------------------------------------------------------------------------
# identifier model
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["M1", "M01", "M001", "M99", "M099", "M100", "M1000", "M123456789"]
)
def test_required_imported_identifier_forms_are_accepted(value: str) -> None:
    assert is_valid_imported_message_id(value)
    assert parse_imported_message_id(value).text == value


@pytest.mark.parametrize(
    "value",
    ["", "M", "m01", "M-1", "M 1", "M01a", "MM1", "1M", "M1234567890", "P-00001"],
)
def test_malformed_imported_identifiers_are_rejected(value: str) -> None:
    assert not is_valid_imported_message_id(value)
    with pytest.raises(ImportedIdentifierError):
        parse_imported_message_id(value)


def test_imported_identifier_text_is_preserved_exactly() -> None:
    """Zero-padding is source data, not noise: M1, M01 and M001 stay distinct."""

    for value in ("M1", "M01", "M001"):
        parsed = parse_imported_message_id(value)
        assert parsed.text == value
        assert str(parsed) == value
        assert parsed.numeric == 1


def test_ordering_is_numeric_aware_not_lexical() -> None:
    unordered = ("M10", "M2", "M100", "M1", "M20")
    assert sort_imported_ids(unordered) == ("M1", "M2", "M10", "M20", "M100")
    # Lexical ordering would put M10 before M2; confirm we are not doing that.
    assert sorted(unordered) != list(sort_imported_ids(unordered))


def test_equal_numbers_order_stably_by_exact_text() -> None:
    """Same number, different padding: tie-break on exact text, ascending."""

    assert sort_imported_ids(("M99", "M099")) == ("M099", "M99")
    assert sort_imported_ids(("M1", "M001", "M01")) == ("M001", "M01", "M1")


def test_unparseable_identifiers_sort_last_without_raising() -> None:
    assert imported_id_sort_key("M5") < imported_id_sort_key("not-an-id")
    assert sort_imported_ids(("zzz", "M5")) == ("M5", "zzz")


# --------------------------------------------------------------------------
# import: identifier acceptance end to end
# --------------------------------------------------------------------------


def test_import_accepts_wide_identifiers_and_preserves_them(tmp_path: Path) -> None:
    """All required forms are accepted and written back exactly as supplied.

    M1, M01 and M001 denote the same number, so this batch needs the permissive
    collision mode; the default mode reports them, which
    ``test_numeric_collision_is_reported_by_default`` covers.
    """

    ids = ["M1", "M01", "M001", "M100", "M1000"]
    source = _write_csv(tmp_path / "in.csv", [_row(value) for value in ids])

    result = load_imported_csv(source, collision_mode=COLLISION_MODE_ALLOW)

    assert result.rejected_count == 0
    assert result.rows_seen == len(ids)
    # Ordering is numeric-first, then exact text within an equal number.
    assert [m.msg_id for m in result.messages] == [
        "M001",
        "M01",
        "M1",
        "M100",
        "M1000",
    ]
    # Every supplied form survives verbatim.
    assert {m.msg_id for m in result.messages} == set(ids)


def test_m99_and_m100_are_both_accepted(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "in.csv", [_row("M99"), _row("M100")])
    result = load_imported_csv(source)
    assert [m.msg_id for m in result.messages] == ["M99", "M100"]
    assert result.rejected_count == 0


# --------------------------------------------------------------------------
# import: batches larger than 99 rows
# --------------------------------------------------------------------------


def test_batch_larger_than_99_rows_processes_in_numeric_order(tmp_path: Path) -> None:
    ids = [f"M{n}" for n in range(1, 251)]
    source = _write_csv(tmp_path / "big.csv", [_row(value) for value in ids])

    result = load_imported_csv(source)

    assert result.rows_seen == 250
    assert result.accepted_count == 250
    assert result.rejected_count == 0
    assert [m.msg_id for m in result.messages] == ids
    # The three-digit boundary is where a two-digit assumption would break.
    assert "M100" in {m.msg_id for m in result.messages}
    assert "M250" in {m.msg_id for m in result.messages}


# --------------------------------------------------------------------------
# import: invalid rows are reported, never silently discarded
# --------------------------------------------------------------------------


def test_invalid_rows_are_reported_and_valid_rows_still_process(tmp_path: Path) -> None:
    rows = [
        _row("M1"),
        _row("BAD-ID"),
        _row("M3", channel="carrier-pigeon"),
        _row("M4", market="Atlantis"),
        _row("M5", received_utc="not-a-timestamp"),
        _row("M6", player_id="12345"),
        _row("M7", subject="", body="   "),
        _row("M8"),
    ]
    source = _write_csv(tmp_path / "mixed.csv", rows)

    result = load_imported_csv(source)

    assert [m.msg_id for m in result.messages] == ["M1", "M8"]
    assert result.rows_seen == 8
    # Every rejected row is accounted for: nothing is dropped in silence.
    assert result.accepted_count + result.rejected_count == result.rows_seen
    assert result.rejected_count == 6

    by_row = {issue.source_row: issue for issue in result.issues}
    assert by_row[3].code == CODE_INVALID_SOURCE_MESSAGE_ID
    for row_number in (4, 5, 6, 7, 8):
        assert by_row[row_number].code == CODE_INVALID_ROW


def test_reported_issues_carry_no_sensitive_values(tmp_path: Path) -> None:
    secret_subject = "card 4111111111111111"
    secret_body = "my password is hunter2"
    rows = [_row("M1", channel="bogus", subject=secret_subject, body=secret_body)]
    source = _write_csv(tmp_path / "sensitive.csv", rows)

    result = load_imported_csv(source)

    assert result.rejected_count == 1
    detail = result.issues[0].detail
    assert secret_subject not in detail
    assert secret_body not in detail
    assert "4111111111111111" not in detail
    assert "hunter2" not in detail
    assert "P-00001" not in detail
    # and no filesystem path leaks into operator-facing output
    assert str(source) not in detail
    assert "sensitive.csv" not in detail


def test_duplicate_source_message_id_is_reported(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "dupe.csv", [_row("M7"), _row("M7")])

    result = load_imported_csv(source)

    assert [m.msg_id for m in result.messages] == ["M7"]
    assert result.rejected_count == 1
    assert result.issues[0].code == CODE_DUPLICATE_SOURCE_MESSAGE_ID
    assert result.issues[0].source_row == 3


# --------------------------------------------------------------------------
# import: M99 / M099 numeric collision is configurable
# --------------------------------------------------------------------------


def test_numeric_collision_is_reported_by_default(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "collide.csv", [_row("M99"), _row("M099")])

    result = load_imported_csv(source)

    assert [m.msg_id for m in result.messages] == ["M99"]
    assert result.rejected_count == 1
    issue = result.issues[0]
    assert issue.code == CODE_NUMERIC_COLLISION
    assert issue.msg_id == "M099"


def test_numeric_collision_can_be_allowed(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "collide.csv", [_row("M99"), _row("M099")])

    result = load_imported_csv(source, collision_mode=COLLISION_MODE_ALLOW)

    assert [m.msg_id for m in result.messages] == ["M099", "M99"]
    assert result.rejected_count == 0


def test_invalid_collision_mode_is_rejected(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "in.csv", [_row("M1")])
    with pytest.raises(ImportedIdentifierError):
        load_imported_csv(source, collision_mode="sometimes")


# --------------------------------------------------------------------------
# import: CSV and XLSX parity, dispatch, structural failures
# --------------------------------------------------------------------------


def test_csv_and_xlsx_produce_equivalent_results(tmp_path: Path) -> None:
    rows = [_row("M1"), _row("M100"), _row("BAD")]
    csv_result = load_imported_csv(_write_csv(tmp_path / "a.csv", rows))
    xlsx_result = load_imported_xlsx(_write_xlsx(tmp_path / "a.xlsx", rows))

    assert [m.msg_id for m in csv_result.messages] == [
        m.msg_id for m in xlsx_result.messages
    ]
    assert [i.code for i in csv_result.issues] == [i.code for i in xlsx_result.issues]
    assert csv_result.source_format == "csv"
    assert xlsx_result.source_format == "xlsx"


def test_dispatch_by_suffix_and_unsupported_format(tmp_path: Path) -> None:
    assert load_imported(_write_csv(tmp_path / "a.csv", [_row("M1")])).accepted_count == 1
    assert load_imported(_write_xlsx(tmp_path / "a.xlsx", [_row("M1")])).accepted_count == 1

    stray = tmp_path / "notes.txt"
    stray.write_text("nope", encoding="utf-8")
    with pytest.raises(IngestionError):
        load_imported(stray)


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(IngestionError):
        load_imported_csv(tmp_path / "absent.csv")


def test_structural_header_failure_remains_fatal(tmp_path: Path) -> None:
    """A broken header means no row can be interpreted: fail, do not report."""

    broken = tmp_path / "broken.csv"
    broken.write_text("not,the,right,columns\n1,2,3,4\n", encoding="utf-8")
    with pytest.raises(IngestionError):
        load_imported_csv(broken)


def test_all_rows_invalid_yields_empty_result_not_exception(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "bad.csv", [_row("nope"), _row("also-nope")])

    result = load_imported_csv(source)

    assert result.is_empty
    assert result.accepted_count == 0
    assert result.rejected_count == 2


# --------------------------------------------------------------------------
# source filename handling
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "with spaces.csv",
        "ümlaut-café.csv",
        "日本語.csv",
        "..dots..in..name.csv",
        "..csv.csv",
    ],
)
def test_awkward_source_filenames_are_handled(tmp_path: Path, filename: str) -> None:
    source = _write_csv(tmp_path / filename, [_row("M1"), _row("M100")])
    result = load_imported_csv(source)
    assert [m.msg_id for m in result.messages] == ["M1", "M100"]


def test_traversal_like_filename_does_not_escape_directory(tmp_path: Path) -> None:
    """A traversal-looking *name* is just a name; it must not resolve upward."""

    nested = tmp_path / "sub"
    nested.mkdir()
    source = _write_csv(nested / "....__..__etc__passwd.csv", [_row("M1")])

    result = load_imported_csv(source)

    assert result.accepted_count == 1
    assert source.resolve().parent == nested.resolve()


# --------------------------------------------------------------------------
# the benchmark path is unchanged
# --------------------------------------------------------------------------


def test_benchmark_loader_still_rejects_wide_identifiers(tmp_path: Path) -> None:
    """The supplied-40 contract keeps ^M\\d{2}$ and stays fail-fast."""

    source = _write_csv(tmp_path / "b.csv", [_row("M001")])
    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "msg_id must match" in str(excinfo.value)


def test_benchmark_loader_still_fails_fast_on_first_bad_row(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "b.csv", [_row("M01"), _row("BAD"), _row("M03")])
    with pytest.raises(IngestionError):
        load_csv(source)
