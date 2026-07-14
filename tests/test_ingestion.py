"""CSV/XLSX ingestion — header validation, duplicates, format equivalence."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest
from openpyxl import load_workbook

from player_triage.ingestion import IngestionError, load, load_csv, load_xlsx


DEFAULT_CSV = Path("input/dataset_player_messages.csv")
DEFAULT_XLSX = Path("input/dataset_player_messages.xlsx")


def test_csv_and_xlsx_produce_equivalent_records(app_root: Path) -> None:
    csv_messages = load_csv(app_root / DEFAULT_CSV)
    xlsx_messages = load_xlsx(app_root / DEFAULT_XLSX)
    assert [m.msg_id for m in csv_messages] == [m.msg_id for m in xlsx_messages]
    for csv_msg, xlsx_msg in zip(csv_messages, xlsx_messages):
        assert csv_msg.msg_id == xlsx_msg.msg_id
        assert csv_msg.channel == xlsx_msg.channel
        assert csv_msg.market == xlsx_msg.market
        assert csv_msg.language == xlsx_msg.language
        assert csv_msg.received_utc == xlsx_msg.received_utc


def test_load_dispatches_by_suffix(app_root: Path) -> None:
    csv_result = load(app_root / DEFAULT_CSV)
    xlsx_result = load(app_root / DEFAULT_XLSX)
    assert [m.msg_id for m in csv_result] == [m.msg_id for m in xlsx_result]


def test_missing_required_column_rejected(tmp_path: Path, app_root: Path) -> None:
    source = tmp_path / "missing_col.csv"
    body = (app_root / DEFAULT_CSV).read_text(encoding="utf-8").splitlines()
    header, *rows = body
    columns = header.split(",")
    body_index = columns.index("body")
    # Drop the body column from every row.
    trimmed = [",".join(part for i, part in enumerate(line.split(",")) if i != body_index) for line in [header] + rows]
    source.write_text("\n".join(trimmed), encoding="utf-8")

    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "missing required columns" in str(excinfo.value)


def test_unexpected_column_rejected(tmp_path: Path, app_root: Path) -> None:
    source = tmp_path / "extra_col.csv"
    body = (app_root / DEFAULT_CSV).read_text(encoding="utf-8").splitlines()
    header, *rows = body
    tampered_header = header + ",undocumented"
    tampered_rows = [row + ",oops" for row in rows]
    source.write_text("\n".join([tampered_header, *tampered_rows]), encoding="utf-8")

    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "unexpected columns present" in str(excinfo.value)


def test_duplicate_header_rejected(tmp_path: Path) -> None:
    source = tmp_path / "dup_header.csv"
    source.write_text(
        "msg_id,received_utc,channel,market,player_id,vip_tier,language,subject,body,body\n",
        encoding="utf-8",
    )
    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "duplicated header" in str(excinfo.value)


def _valid_row(msg_id: str = "M99", received_utc: str = "2026-06-15T08:00:00Z") -> str:
    return (
        f"{msg_id},{received_utc},email,Ontario,P-99999,none,en,"
        "Synthetic subject line,Synthetic body content"
    )


def _header() -> str:
    return "msg_id,received_utc,channel,market,player_id,vip_tier,language,subject,body"


def test_duplicate_msg_id_rejected(tmp_path: Path) -> None:
    source = tmp_path / "dup_id.csv"
    source.write_text(
        "\n".join([_header(), _valid_row("M91"), _valid_row("M91")]),
        encoding="utf-8",
    )
    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "duplicate msg_id" in str(excinfo.value)


def test_invalid_timestamp_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad_ts.csv"
    source.write_text(
        "\n".join([_header(), _valid_row("M92", received_utc="not-a-date")]),
        encoding="utf-8",
    )
    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "invalid received_utc" in str(excinfo.value)


def test_unsupported_channel_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad_channel.csv"
    source.write_text(
        _header() + "\n"
        "M93,2026-06-15T08:00:00Z,fax,Ontario,P-11111,none,en,Synthetic subject,Synthetic body",
        encoding="utf-8",
    )
    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "unsupported channel" in str(excinfo.value)


def test_unsupported_market_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad_market.csv"
    source.write_text(
        _header() + "\n"
        "M94,2026-06-15T08:00:00Z,email,Atlantis,P-11111,none,en,Synthetic subject,Synthetic body",
        encoding="utf-8",
    )
    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "unsupported market" in str(excinfo.value)


def test_empty_subject_and_body_rejected(tmp_path: Path) -> None:
    source = tmp_path / "empty_body.csv"
    source.write_text(
        _header() + "\n"
        "M95,2026-06-15T08:00:00Z,email,Ontario,P-11111,none,en,,",
        encoding="utf-8",
    )
    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    assert "empty subject and body" in str(excinfo.value)


def test_input_records_return_utc_timestamps(app_root: Path) -> None:
    messages = load_csv(app_root / DEFAULT_CSV)
    for message in messages:
        assert isinstance(message.received_utc, datetime)
        assert message.received_utc.tzinfo is not None
        assert message.received_utc.utcoffset() == timezone.utc.utcoffset(None)


def test_ingestion_produces_immutable_records(app_root: Path) -> None:
    messages = load_csv(app_root / DEFAULT_CSV)
    with pytest.raises(AttributeError):
        messages[0].player_id = "P-00000"  # type: ignore[misc]
