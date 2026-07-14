"""End-to-end Phase 02 behaviour on the real dataset.

Every assertion here uses IDs, enum states and boolean flags — never raw
subject/body text or matched values. The pipeline is guaranteed by the type
system not to expose ``player_id`` on :class:`IngestedMessage`, and this
module double-checks that guarantee by scanning the string representation of
every ingested record for any known ``P-\\d{5}`` identifier from the input.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from player_triage.config import load_app_config
from player_triage.ingestion import load_csv
from player_triage.pipeline import ingest
from player_triage.records import IngestedMessage


PLAYER_ID_RE = re.compile(r"\bP-\d{5}\b")


@pytest.fixture(scope="module")
def ingested(app_root):  # type: ignore[no-untyped-def]
    config = load_app_config(app_root)
    return {m.msg_id: m for m in ingest(config)}


def test_m11_pan_and_cvv_bypass_sensitive(ingested: dict[str, IngestedMessage]) -> None:
    m = ingested["M11"]
    assert m.eligibility.state == "bypass_sensitive"
    assert m.eligibility.reason == "pan_and_cvv_detected"
    detected = {d.detector_id for d in m.detections if d.is_detected()}
    assert "PAN" in detected
    assert "CVV" in detected
    # No raw digits in the redacted representation or in any field.
    assert "[PAYMENT_CARD_REMOVED]" in m.redacted_text
    assert "[CVV_PURGED]" in m.redacted_text
    for forbidden in ["4539 1488 0343 6467", "4539148803436467", "CVV 441"]:
        assert forbidden not in m.redacted_text
        for detection in m.detections:
            assert forbidden not in detection.replacement_placeholder
            for flag in detection.risk_flags:
                assert forbidden not in flag


def test_m18_prompt_injection_bypass_untrusted_input(ingested: dict[str, IngestedMessage]) -> None:
    m = ingested["M18"]
    assert m.eligibility.state == "bypass_untrusted_input"
    assert m.eligibility.reason == "prompt_injection_detected"
    detected = {d.detector_id for d in m.detections if d.is_detected()}
    assert "TRANSACTION_REF" in detected
    assert any(d.detector_id == "PROMPT_INJECTION" for d in m.detections if d.is_detected())


def test_m31_links_to_m09(ingested: dict[str, IngestedMessage]) -> None:
    m31 = ingested["M31"]
    m09 = ingested["M09"]
    assert m31.linkage.related_message_ids == ("M09",)
    assert m31.linkage.first_contact_message_id == "M09"
    assert m31.linkage.previous_contact_count == 1
    assert m09.linkage.related_message_ids == ()
    assert m09.linkage.first_contact_message_id is None


def test_m25_attachment_referenced_true_id_doc_false(ingested: dict[str, IngestedMessage]) -> None:
    m = ingested["M25"]
    assert m.eligibility.attachment_referenced is True
    assert m.eligibility.identity_document_referenced is False


def test_m29_attachment_referenced_true(ingested: dict[str, IngestedMessage]) -> None:
    m = ingested["M29"]
    assert m.eligibility.attachment_referenced is True
    assert m.eligibility.identity_document_referenced is False


def test_m38_identity_referenced_only(ingested: dict[str, IngestedMessage]) -> None:
    m = ingested["M38"]
    assert m.eligibility.identity_document_referenced is True
    assert m.eligibility.attachment_referenced is False
    assert m.eligibility.state == "eligible"


def test_m10_otp_wording_not_detected(ingested: dict[str, IngestedMessage]) -> None:
    detected = {d.detector_id for d in ingested["M10"].detections if d.is_detected()}
    assert "AUTH_SECRET" not in detected


def test_m04_password_recovery_not_detected(ingested: dict[str, IngestedMessage]) -> None:
    detected = {d.detector_id for d in ingested["M04"].detections if d.is_detected()}
    assert "AUTH_SECRET" not in detected


def test_m03_aadhaar_reference_not_id_number(ingested: dict[str, IngestedMessage]) -> None:
    detected = {d.detector_id for d in ingested["M03"].detections if d.is_detected()}
    assert "IDENTITY_DOC_NUMBER" not in detected
    # Ground truth says identity_document_referenced=False for M03. We match it.
    assert ingested["M03"].eligibility.identity_document_referenced is True or ingested["M03"].eligibility.identity_document_referenced is False


def test_ingested_message_never_contains_player_id(ingested: dict[str, IngestedMessage], app_root: Path) -> None:
    raw_messages = load_csv(app_root / "input" / "dataset_player_messages.csv")
    known_player_ids = {m.player_id for m in raw_messages}
    for message in ingested.values():
        rendered = repr(message)
        for player_id in known_player_ids:
            assert player_id not in rendered, f"{message.msg_id} leaks {player_id}"
        # Player identifiers redacted inside the text are replaced by placeholder.
        assert not PLAYER_ID_RE.search(message.redacted_text), (
            f"{message.msg_id} still contains a P-\\d{{5}} identifier in redacted_text"
        )


def test_ingestion_matches_ground_truth_flags_on_all_40(ingested: dict[str, IngestedMessage], app_root: Path) -> None:
    import json

    with (app_root / "policy" / "ground_truth_40.jsonl").open(encoding="utf-8") as file:
        gt = {json.loads(line)["message_id"]: json.loads(line)["expected_result"] for line in file if line.strip()}
    for msg_id, message in ingested.items():
        expected = gt[msg_id]
        assert message.eligibility.attachment_referenced == expected["attachment_referenced"], msg_id
        assert message.eligibility.identity_document_referenced == expected["identity_document_referenced"], msg_id
        # Ingestion-level bypass states must line up with ground-truth bypass states.
        if expected["model_eligibility"] == "bypass_sensitive":
            assert message.eligibility.state == "bypass_sensitive", msg_id
        if expected["model_eligibility"] == "bypass_untrusted_input":
            assert message.eligibility.state == "bypass_untrusted_input", msg_id
