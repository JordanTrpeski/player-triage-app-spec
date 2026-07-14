"""Text normalization behaviour and idempotence."""

from __future__ import annotations

import unicodedata

import pytest

from player_triage.normalization import (
    NORMALIZATION_VERSION,
    detector_view,
    is_idempotent,
    normalize_text,
)


def test_normalization_version_exposed() -> None:
    assert NORMALIZATION_VERSION.startswith("norm-")


def test_normalizes_line_endings() -> None:
    assert normalize_text("a\r\nb\rc\n\nd") == "a\nb\nc\n\nd"


def test_collapses_repeated_inline_whitespace_but_keeps_newlines() -> None:
    assert normalize_text("hello   world\n\n  next") == "hello world\n\n next"


def test_strips_zero_width_characters() -> None:
    zero_width = "​‌‍⁠﻿"
    assert normalize_text(f"a{zero_width}b") == "ab"


def test_nfc_composition() -> None:
    # Decomposed "é" (e + combining acute) becomes precomposed after NFC.
    decomposed = "café"
    canonical = normalize_text(decomposed)
    assert canonical == unicodedata.normalize("NFC", decomposed)
    assert canonical == "café"


def test_preserves_language_specific_characters() -> None:
    text = "das ist über schön — grüß gott"
    assert normalize_text(text) == text
    assert "ü" in normalize_text(text)


def test_detector_view_is_case_folded() -> None:
    text = "PLAYER ID P-12345"
    view = detector_view(text)
    assert view == view.casefold()
    assert "p-12345" in view


def test_idempotence_across_dataset(app_root):  # type: ignore[no-untyped-def]
    from player_triage.ingestion import load_csv

    messages = load_csv(app_root / "input" / "dataset_player_messages.csv")
    for message in messages:
        combined = f"{message.subject}\n{message.body}"
        assert is_idempotent(combined), f"normalization not idempotent on {message.msg_id}"


def test_rejects_non_string() -> None:
    with pytest.raises(Exception):
        normalize_text(123)  # type: ignore[arg-type]
