"""Unicode and multilingual preservation through normalization + detection."""

from __future__ import annotations

import unicodedata

import pytest

from player_triage.config import load_app_config
from player_triage.detection import DetectionEngine
from player_triage.normalization import normalize_text


@pytest.fixture(scope="module")
def engine(app_root):  # type: ignore[no-untyped-def]
    config = load_app_config(app_root)
    return DetectionEngine.from_policy(config.component("redaction_policy"))


def test_german_text_survives_normalization() -> None:
    text = "Grüß Gott — ich brauche eine Auskunft über meine Auszahlung."
    assert "ü" in normalize_text(text)
    assert "ß" in normalize_text(text)
    assert "—" in normalize_text(text)


def test_hindi_text_survives_normalization() -> None:
    text = "मेरा भुगतान लंबित है — कृपया मदद करें।"
    normalized = normalize_text(text)
    # Devanagari characters must remain intact.
    for character in "मेराभुगतान":
        assert character in normalized


def test_detectors_still_operate_on_multilingual_wrapper(engine: DetectionEngine) -> None:
    text = "Grüße — please check my card 4111 1111 1111 1111 charge."
    outcome = engine.scan(text)
    detected = {d.detector_id for d in outcome.detections if d.is_detected()}
    assert "PAN" in detected


def test_nfc_normalization_is_stable() -> None:
    decomposed = "über"
    normalized = normalize_text(decomposed)
    assert normalized == unicodedata.normalize("NFC", decomposed)
    assert normalize_text(normalized) == normalized
