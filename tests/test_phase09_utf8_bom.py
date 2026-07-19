"""Phase 09 release correction: UTF-8 BOM compatibility on the CSV import path.

Excel and several Windows editors write a UTF-8 BOM. It arrived as part of the
first header (U+FEFF followed by msg_id), so a structurally valid file failed the
required-column contract before any row was processed:

    missing required columns: ['msg_id']

The preview path already decoded ``utf-8-sig``; the loader did not. That split
is why the file previewed correctly and then failed at load, so these tests
pin both paths together.

The fix is confined to the decode step. Header validation stays strict: a BOM
file genuinely missing a required column must still fail, and no name is
rewritten beyond removing the byte-order mark itself.
"""

from __future__ import annotations

import csv
import io
from dataclasses import astuple
from pathlib import Path

import pytest
from openpyxl import Workbook

from player_triage.console_service import ConsoleService
from player_triage.import_ingestion import load_imported
from player_triage.ingestion import REQUIRED_COLUMNS, IngestionError, load_csv
from player_triage.records import RawMessage

#: The UTF-8 encoding of U+FEFF, as written by Excel.
BOM = b"\xef\xbb\xbf"

#: The same mark as a character. Spelled as an escape rather than embedded
#: literally, so it stays visible to a reviewer and survives editors that
#: strip invisible characters.
BOM_CHAR = "\ufeff"

_CHANNELS = ("email", "chat")
_MARKETS = ("Ontario", "Malta", "Ireland", "India", "New Zealand")
_LANGUAGES = ("en", "de", "es")
_TIERS = ("none", "bronze", "silver", "gold")


def _row(msg_id: str, index: int = 1) -> dict[str, str]:
    return {
        "msg_id": msg_id,
        "received_utc": f"2026-03-{(index % 28) + 1:02d}T09:15:00Z",
        "channel": _CHANNELS[index % len(_CHANNELS)],
        "market": _MARKETS[index % len(_MARKETS)],
        "player_id": f"P-{index:05d}",
        "vip_tier": _TIERS[index % len(_TIERS)],
        "language": _LANGUAGES[index % len(_LANGUAGES)],
        "subject": f"Withdrawal question (case {index})",
        "body": f"My payout has not arrived yet. Reference {index:04d}.",
    }


def _csv_text(rows: list[dict[str, str]], columns: list[str] | None = None) -> str:
    fields = columns or list(REQUIRED_COLUMNS)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fields})
    return buffer.getvalue()


def _write(path: Path, text: str, *, bom: bool) -> Path:
    """Write CSV bytes with or without a leading UTF-8 BOM."""

    payload = text.encode("utf-8")
    path.write_bytes(BOM + payload if bom else payload)
    return path


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
    return ConsoleService(
        app_root, state_root=tmp_path / "state", output_root=tmp_path / "out"
    )


# ---------------------------------------------------------------------------
# 1-2. both encodings are accepted
# ---------------------------------------------------------------------------


def test_csv_without_bom_is_accepted(tmp_path: Path) -> None:
    path = _write(tmp_path / "plain.csv", _csv_text([_row("M1")]), bom=False)

    result = load_imported(path)

    assert result.rows_seen == 1
    assert result.accepted_count == 1
    assert result.issues == ()


def test_csv_with_bom_is_accepted(tmp_path: Path) -> None:
    """The reported defect: this failed with missing required columns."""

    path = _write(tmp_path / "bom.csv", _csv_text([_row("M1")]), bom=True)

    result = load_imported(path)

    assert result.rows_seen == 1
    assert result.accepted_count == 1
    assert result.issues == ()


def test_bom_is_actually_present_in_the_fixture(tmp_path: Path) -> None:
    """Guards the tests themselves: a fixture without a BOM proves nothing."""

    path = _write(tmp_path / "bom.csv", _csv_text([_row("M1")]), bom=True)
    raw = path.read_bytes()

    assert raw.startswith(BOM)
    assert raw.decode("utf-8").startswith(BOM_CHAR)
    assert raw.decode("utf-8-sig").startswith("msg_id")


def test_first_header_is_msg_id_not_bom_prefixed(tmp_path: Path) -> None:
    path = _write(tmp_path / "bom.csv", _csv_text([_row("M1")]), bom=True)

    result = load_imported(path)

    assert result.messages[0].msg_id == "M1"
    assert BOM_CHAR not in result.messages[0].msg_id


# ---------------------------------------------------------------------------
# 3. equivalence of the two encodings
# ---------------------------------------------------------------------------


def _comparable(message: RawMessage) -> tuple[object, ...]:
    """Every field of the record, so no difference can slip past."""

    return astuple(message)


def test_bom_and_non_bom_produce_identical_rows(tmp_path: Path) -> None:
    text = _csv_text([_row(f"M{n}", n) for n in range(1, 11)])
    plain = load_imported(_write(tmp_path / "plain.csv", text, bom=False))
    bom = load_imported(_write(tmp_path / "bom.csv", text, bom=True))

    assert bom.rows_seen == plain.rows_seen == 10
    assert [_comparable(m) for m in bom.messages] == [
        _comparable(m) for m in plain.messages
    ]


def test_bom_and_non_bom_produce_the_same_decision_digest(
    service: ConsoleService, tmp_path: Path
) -> None:
    """Equivalent input must be indistinguishable downstream."""

    text = _csv_text([_row(f"M{n}", n) for n in range(1, 11)])

    plain = service.run_import(text.encode("utf-8"), display_name="plain.csv")
    bom = service.run_import(BOM + text.encode("utf-8"), display_name="bom.csv")

    assert plain.status == bom.status == "completed"
    assert plain.rows_processed == bom.rows_processed == 10
    assert plain.rows_rejected == bom.rows_rejected == 0
    assert bom.decision_digest == plain.decision_digest
    assert bom.model_calls == plain.model_calls == 0


def test_bom_file_previews_the_same_as_a_plain_file(
    service: ConsoleService,
) -> None:
    """Preview and load must agree; their disagreement was the original bug."""

    text = _csv_text([_row(f"M{n}", n) for n in range(1, 6)])

    plain = service.preview_import(text.encode("utf-8"), display_name="plain.csv")
    bom = service.preview_import(BOM + text.encode("utf-8"), display_name="bom.csv")

    assert bom.detected_columns == plain.detected_columns == tuple(REQUIRED_COLUMNS)
    assert bom.detected_columns[0] == "msg_id"
    assert bom.columns_ok and plain.columns_ok
    assert bom.missing_columns == () == plain.missing_columns
    assert bom.row_count == plain.row_count == 5
    assert bom.sample_rows == plain.sample_rows


# ---------------------------------------------------------------------------
# 4-5. validation stays strict, and the BOM affects only the first header
# ---------------------------------------------------------------------------


def test_bom_file_genuinely_missing_msg_id_still_fails(tmp_path: Path) -> None:
    """The fix must not become a way to smuggle a malformed header through."""

    columns = [c for c in REQUIRED_COLUMNS if c != "msg_id"]
    path = _write(
        tmp_path / "bom-missing.csv", _csv_text([_row("M1")], columns), bom=True
    )

    with pytest.raises(IngestionError) as caught:
        load_imported(path)

    assert "missing required columns" in str(caught.value)
    assert "msg_id" in str(caught.value)


def test_bom_file_with_an_unexpected_column_still_fails(tmp_path: Path) -> None:
    columns = [*REQUIRED_COLUMNS, "extra_column"]
    path = _write(tmp_path / "bom-extra.csv", _csv_text([_row("M1")], columns), bom=True)

    with pytest.raises(IngestionError) as caught:
        load_imported(path)

    assert "unexpected columns present" in str(caught.value)


def test_a_bom_shaped_name_on_a_later_column_is_not_stripped(
    tmp_path: Path,
) -> None:
    """Only a leading byte-order mark is removed; nothing else is rewritten.

    A U+FEFF inside a later header is a genuinely wrong column name and must
    still be rejected, or the fix would be silently renaming columns.
    """

    columns = [*REQUIRED_COLUMNS[:-1], BOM_CHAR + "body"]
    path = _write(tmp_path / "bom-later.csv", _csv_text([_row("M1")], columns), bom=True)

    with pytest.raises(IngestionError) as caught:
        load_imported(path)

    message = str(caught.value)
    assert "missing required columns" in message
    assert "body" in message


def test_only_one_bom_is_removed(tmp_path: Path) -> None:
    """A doubled BOM leaves a real U+FEFF, which is a malformed header."""

    path = tmp_path / "double-bom.csv"
    path.write_bytes(BOM + BOM + _csv_text([_row("M1")]).encode("utf-8"))

    with pytest.raises(IngestionError) as caught:
        load_imported(path)

    assert "missing required columns" in str(caught.value)


def test_duplicate_header_detection_survives_the_bom(tmp_path: Path) -> None:
    columns = ["msg_id", *REQUIRED_COLUMNS]
    path = _write(tmp_path / "dupe.csv", _csv_text([_row("M1")], columns), bom=True)

    with pytest.raises(IngestionError) as caught:
        load_imported(path)

    assert "duplicated header" in str(caught.value)


# ---------------------------------------------------------------------------
# 6. CSV and XLSX parity
# ---------------------------------------------------------------------------


def test_csv_bom_and_xlsx_produce_the_same_digest(
    service: ConsoleService,
) -> None:
    """XLSX handling is untouched, and all three inputs must still agree."""

    rows = [_row(f"M{n}", n) for n in range(1, 11)]
    text = _csv_text(rows)

    plain = service.run_import(text.encode("utf-8"), display_name="plain.csv")
    bom = service.run_import(BOM + text.encode("utf-8"), display_name="bom.csv")
    workbook = service.run_import(_xlsx_bytes(rows), display_name="batch.xlsx")

    assert workbook.rows_processed == 10
    assert workbook.decision_digest == plain.decision_digest == bom.decision_digest


def test_xlsx_import_is_unaffected(service: ConsoleService) -> None:
    result = service.run_import(
        _xlsx_bytes([_row("M1"), _row("M2", 2)]), display_name="batch.xlsx"
    )

    assert result.status == "completed"
    assert result.rows_processed == 2
    assert result.model_calls == 0


# ---------------------------------------------------------------------------
# 7. the 100-message smoke-test batch
# ---------------------------------------------------------------------------


def _smoke_rows() -> list[dict[str, str]]:
    return [_row(f"M{n}", n) for n in range(1, 101)]


def test_100_message_bom_csv_processes_every_row(service: ConsoleService) -> None:
    text = _csv_text(_smoke_rows())

    result = service.run_import(BOM + text.encode("utf-8"), display_name="smoke.csv")

    assert result.status == "completed"
    assert result.rows_seen == 100
    assert result.rows_accepted == 100
    assert result.rows_processed == 100
    assert result.rows_rejected == 0
    assert result.rows_failed == 0
    assert result.model_calls == 0


def test_100_message_batch_matches_across_encodings(
    service: ConsoleService,
) -> None:
    text = _csv_text(_smoke_rows())

    plain = service.run_import(text.encode("utf-8"), display_name="smoke.csv")
    bom = service.run_import(BOM + text.encode("utf-8"), display_name="smoke-bom.csv")

    assert bom.rows_processed == plain.rows_processed == 100
    assert bom.decision_digest == plain.decision_digest


def test_a_bom_run_is_selectable_on_the_dashboard(service: ConsoleService) -> None:
    text = _csv_text(_smoke_rows())
    run = service.run_import(BOM + text.encode("utf-8"), display_name="smoke-bom.csv")

    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    assert detail.rows_processed == 100
    assert detail.policy_version == "policy-3.3.1"
    assert detail.model_calls == 0
    assert len(detail.decisions) == 100


# ---------------------------------------------------------------------------
# 8-10. the accepted baseline is untouched
# ---------------------------------------------------------------------------


def test_supplied_40_benchmark_csv_has_no_bom(app_root: Path) -> None:
    """Establishes why the decode change cannot move the canonical digest."""

    raw = (app_root / "input" / "dataset_player_messages.csv").read_bytes()

    assert not raw.startswith(BOM)
    assert raw[:6].decode("utf-8") == "msg_id"


def test_supplied_40_still_loads_identically(app_root: Path) -> None:
    messages = load_csv(app_root / "input" / "dataset_player_messages.csv")

    assert len(messages) == 40
    assert messages[0].msg_id == "M01"
    assert messages[-1].msg_id == "M40"
    assert all(BOM_CHAR not in message.msg_id for message in messages)


def test_supplied_40_canonical_digest_is_unchanged(
    app_root: Path, tmp_path: Path
) -> None:
    """The accepted digest must not move for a decode-layer change."""

    from player_triage.config import load_app_config
    from player_triage.evaluation_service import ACCEPTED_CANONICAL_DIGEST
    from player_triage.operational import run_operational_pipeline

    supplied = run_operational_pipeline(
        load_app_config(app_root), output_dir=tmp_path / "supplied"
    )

    assert supplied.canonical_decision_digest == ACCEPTED_CANONICAL_DIGEST
    assert (
        supplied.canonical_decision_digest
        == "a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b"
    )
    assert supplied.input_count == 40
    assert supplied.failure_count == 0


def test_imported_runs_remain_rules_only_on_policy_3_3_1(
    service: ConsoleService,
) -> None:
    text = _csv_text([_row("M1")])
    result = service.run_import(BOM + text.encode("utf-8"), display_name="bom.csv")

    assert result.policy_version == "policy-3.3.1"
    assert result.model_calls == 0
