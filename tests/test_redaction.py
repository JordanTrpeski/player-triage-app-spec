"""Redaction determinism and idempotence."""

from __future__ import annotations

import pytest

from player_triage.config import load_app_config
from player_triage.detection import DetectionEngine
from player_triage.redaction import apply_redaction, is_idempotent, redact


@pytest.fixture(scope="module")
def engine(app_root):  # type: ignore[no-untyped-def]
    config = load_app_config(app_root)
    return DetectionEngine.from_policy(config.component("redaction_policy"))


def test_idempotent_on_synthetic_pan_cvv(engine: DetectionEngine) -> None:
    text = "My card 4111 1111 1111 1111 (CVV: 123) was charged twice."
    assert is_idempotent(text, engine)


def test_placeholders_present_after_redaction(engine: DetectionEngine) -> None:
    text = "OTP: 987654 was leaked. Card 4111 1111 1111 1111 CVV: 123."
    result = redact(text, engine)
    assert "[AUTH_SECRET_PURGED]" in result.redacted_text
    assert "[CVV_PURGED]" in result.redacted_text
    assert "[PAYMENT_CARD_REMOVED]" in result.redacted_text
    for forbidden in ["987654", "4111 1111 1111 1111", "CVV: 123"]:
        assert forbidden not in result.redacted_text


def test_redaction_output_never_contains_source_pan(engine: DetectionEngine) -> None:
    text = "Card 4111-1111-1111-1111 was charged."
    result = redact(text, engine)
    assert "4111-1111-1111-1111" not in result.redacted_text


def test_redaction_leaves_semantic_text(engine: DetectionEngine) -> None:
    text = "I would like a refund on my recent deposit please."
    result = redact(text, engine)
    assert "refund" in result.redacted_text
    assert "deposit" in result.redacted_text.lower()


def test_apply_redaction_no_matches_returns_text_unchanged(engine: DetectionEngine) -> None:
    text = "General thank-you note with no sensitive content."
    outcome = engine.scan(text)
    assert apply_redaction(text, outcome) == text
