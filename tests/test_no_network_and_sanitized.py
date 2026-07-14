"""Guard tests: no network calls during ingestion; exceptions never echo raw text."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from player_triage.config import load_app_config
from player_triage.ingestion import IngestionError, load_csv
from player_triage.pipeline import ingest


@pytest.fixture()
def disable_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("network access is not permitted during Phase 02 ingestion")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def test_full_pipeline_makes_no_network_calls(
    app_root: Path, disable_network: None
) -> None:
    config = load_app_config(app_root)
    messages = ingest(config)
    assert len(messages) == 40


def test_ingestion_error_does_not_echo_row_body(tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    sensitive_body = "SUPER-SENSITIVE-BODY-TEXT-SHOULD-NEVER-APPEAR"
    header = "msg_id,received_utc,channel,market,player_id,vip_tier,language,subject,body"
    row = f"M99,not-a-timestamp,email,Ontario,P-99999,none,en,Synthetic subject,{sensitive_body}"
    source.write_text(f"{header}\n{row}\n", encoding="utf-8")

    with pytest.raises(IngestionError) as excinfo:
        load_csv(source)
    rendered = str(excinfo.value)
    assert sensitive_body not in rendered
    assert "P-99999" not in rendered


def test_pipeline_from_foreign_cwd(
    app_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLAYER_TRIAGE_APP_ROOT", raising=False)
    config = load_app_config(app_root)
    messages = ingest(config)
    assert {m.msg_id for m in messages} == {f"M{n:02d}" for n in range(1, 41)}
