"""Phase 09 closeout: batch-size boundary coverage.

The audit matrix (1, 40, 99, 100, 101, 900, 1000, 10000, over-limit) was
verified by controlled runs. This file pins the boundaries that are cheap
enough to assert on every suite run, so a regression at the two- to
three-digit transition — where a two-digit identifier assumption would break —
fails automatically.

The very large sizes (10,000 and the 100,001-row over-limit case) are not run
here: generating and classifying them takes minutes and would dominate the
suite. The limit itself is exercised by monkeypatching MAX_IMPORT_ROWS down,
which tests the same code path deterministically and in milliseconds.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from player_triage import import_ingestion
from player_triage.config import load_app_config
from player_triage.import_ingestion import (
    MAX_IMPORT_ROWS,
    load_imported_csv,
)
from player_triage.imported_runs import STATUS_COMPLETED, STATUS_FAILED, run_imported_batch
from player_triage.ingestion import REQUIRED_COLUMNS


def _write(path: Path, count: int) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REQUIRED_COLUMNS))
        writer.writeheader()
        for n in range(1, count + 1):
            writer.writerow(
                {
                    "msg_id": f"M{n}",
                    "received_utc": "2026-02-01T10:00:00Z",
                    "channel": "email",
                    "market": "Ontario",
                    "player_id": f"P-{(n % 500):05d}",
                    "vip_tier": "none",
                    "language": "en",
                    "subject": "Withdrawal question",
                    "body": "My withdrawal has been pending for three days.",
                }
            )
    return path


@pytest.mark.parametrize("size", [1, 40, 99, 100, 101])
def test_boundary_batch_sizes_load_completely(tmp_path: Path, size: int) -> None:
    """No row is dropped at any boundary, and ordering stays numeric-aware."""

    result = load_imported_csv(_write(tmp_path / f"in_{size}.csv", size))

    assert result.rows_seen == size
    assert result.accepted_count == size
    assert result.rejected_count == 0
    assert result.accepted_count + result.rejected_count == result.rows_seen
    assert [m.msg_id for m in result.messages] == [f"M{n}" for n in range(1, size + 1)]


@pytest.mark.parametrize("size", [99, 100, 101])
def test_three_digit_transition_runs_end_to_end(tmp_path: Path, app_root: Path, size: int) -> None:
    """The 99/100/101 transition is where a two-digit assumption would break."""

    config = load_app_config(app_root)
    result = run_imported_batch(
        config, _write(tmp_path / "in.csv", size), output_root=tmp_path / "runs"
    )

    assert result.status == STATUS_COMPLETED
    assert result.rows_seen == size
    assert result.rows_accepted + result.rows_rejected == result.rows_seen
    assert result.rows_processed + result.rows_failed == result.rows_accepted
    assert result.rows_processed == size
    assert result.model_calls == 0


def test_configured_limit_is_documented_value() -> None:
    """Pin the limit so a change is deliberate and shows up in review."""

    assert MAX_IMPORT_ROWS == 100_000


def test_at_limit_is_accepted_and_over_limit_fails_before_processing(
    tmp_path: Path, app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real limit code path with a small stand-in limit."""

    monkeypatch.setattr(import_ingestion, "MAX_IMPORT_ROWS", 25)
    config = load_app_config(app_root)

    at_limit = run_imported_batch(
        config, _write(tmp_path / "at.csv", 25), output_root=tmp_path / "runs"
    )
    assert at_limit.status == STATUS_COMPLETED
    assert at_limit.rows_processed == 25

    over = run_imported_batch(
        config, _write(tmp_path / "over.csv", 26), output_root=tmp_path / "runs"
    )
    assert over.status == STATUS_FAILED
    # nothing was classified, and no partial result was published as success
    assert over.rows_seen == 0
    assert over.rows_processed == 0
    assert over.rows_failed == 0
    assert over.model_calls == 0


def test_over_limit_error_is_sanitized_and_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from player_triage.ingestion import IngestionError

    monkeypatch.setattr(import_ingestion, "MAX_IMPORT_ROWS", 10)
    source = _write(tmp_path / "over.csv", 11)

    with pytest.raises(IngestionError) as excinfo:
        load_imported_csv(source)

    message = excinfo.value.message
    # actionable: states the limit
    assert "exceeds 10 rows" in message
    # sanitized: no filesystem path, no row content
    assert str(tmp_path) not in message
    assert "over.csv" not in message
    assert "withdrawal" not in message.lower()
