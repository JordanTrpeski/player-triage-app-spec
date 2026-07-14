"""Linkage rules — same-player follow-up and reference sharing.

Uses the real dataset only for M09/M31 (asserted by IDs). All other cases use
synthetic RawMessage objects built in-test so no dataset text or player_id
leaks into assertions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from player_triage.ingestion import load_csv
from player_triage.linkage import build_linkage
from player_triage.records import RawMessage


def _raw(
    msg_id: str,
    *,
    player_id: str,
    hours: int,
    subject: str = "",
    body: str = "",
) -> RawMessage:
    return RawMessage(
        msg_id=msg_id,
        received_utc=datetime(2026, 6, 15, hours, 0, 0, tzinfo=timezone.utc),
        channel="email",
        market="Ontario",
        language="en",
        subject=subject,
        body=body,
        player_id=player_id,
        source_format="synthetic",
        source_row=0,
    )


def test_m09_and_m31_linked_in_real_dataset(app_root: Path) -> None:
    messages = load_csv(app_root / "input" / "dataset_player_messages.csv")
    linkage = build_linkage(messages)
    result = linkage["M31"]
    assert result.related_message_ids == ("M09",)
    assert result.first_contact_message_id == "M09"
    assert result.previous_contact_count == 1
    m09 = linkage["M09"]
    assert m09.related_message_ids == ()
    assert m09.first_contact_message_id is None


def test_same_topic_different_players_not_linked() -> None:
    messages = [
        _raw("MA1", player_id="P-10001", hours=8, subject="Withdrawal", body="follow up on withdrawal"),
        _raw("MA2", player_id="P-20002", hours=9, subject="Withdrawal", body="follow up on withdrawal"),
    ]
    linkage = build_linkage(messages)
    for mid in ("MA1", "MA2"):
        assert linkage[mid].related_message_ids == ()


def test_same_player_unrelated_topics_not_linked() -> None:
    messages = [
        _raw("MB1", player_id="P-30003", hours=8, subject="Bonus terms", body="How does the bonus work?"),
        _raw("MB2", player_id="P-30003", hours=10, subject="Password reset", body="Please reset my password."),
    ]
    linkage = build_linkage(messages)
    assert linkage["MB2"].related_message_ids == ()
    assert linkage["MB1"].related_message_ids == ()


def test_same_player_followup_language_links() -> None:
    messages = [
        _raw("MC1", player_id="P-40004", hours=8, subject="Withdrawal", body="I placed a withdrawal."),
        _raw("MC2", player_id="P-40004", hours=10, subject="Withdrawal", body="Follow up: still no reply on my withdrawal."),
    ]
    linkage = build_linkage(messages)
    assert linkage["MC2"].related_message_ids == ("MC1",)
    assert linkage["MC2"].first_contact_message_id == "MC1"


def test_shared_transaction_reference_links_without_followup_words() -> None:
    messages = [
        _raw("MD1", player_id="P-50005", hours=8, subject="Withdrawal W-11111", body="I placed withdrawal W-11111."),
        _raw("MD2", player_id="P-50005", hours=9, subject="Withdrawal W-11111", body="Please give me an update on W-11111."),
    ]
    linkage = build_linkage(messages)
    assert linkage["MD2"].related_message_ids == ("MD1",)


def test_out_of_order_timestamps_still_produce_deterministic_result() -> None:
    messages = [
        _raw("ME2", player_id="P-60006", hours=10, subject="Follow up", body="Following up, no reply yet."),
        _raw("ME1", player_id="P-60006", hours=8, subject="Original", body="I have a question."),
    ]
    linkage = build_linkage(messages)
    assert linkage["ME2"].related_message_ids == ("ME1",)
    assert linkage["ME1"].related_message_ids == ()


def test_duplicate_ingestion_uses_message_id_only() -> None:
    # Two RawMessages sharing player_id but different msg_ids at the same UTC
    # timestamp: neither is "later" than the other, so they must not link.
    messages = [
        _raw("MF1", player_id="P-70007", hours=8, subject="Question", body="Just checking."),
        _raw("MF2", player_id="P-70007", hours=8, subject="Question", body="Just checking."),
    ]
    linkage = build_linkage(messages)
    assert linkage["MF1"].related_message_ids == ()
    assert linkage["MF2"].related_message_ids == ()


def test_linkage_output_contains_no_player_id(app_root: Path) -> None:
    messages = load_csv(app_root / "input" / "dataset_player_messages.csv")
    linkage = build_linkage(messages)
    seen_player_ids = {m.player_id for m in messages}
    for result in linkage.values():
        rendered = repr(result)
        for player_id in seen_player_ids:
            assert player_id not in rendered
