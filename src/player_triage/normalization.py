"""Deterministic text normalization.

Two views are produced from every raw message:

* ``normalized_text`` — preserves language-specific characters and punctuation
  so downstream classification can rely on the full semantic content. Only
  formatting (unicode form, line endings, whitespace) is normalized.
* ``detector_view`` — a case-folded copy used *only* by detectors that need
  case-insensitive matching. Never sent to a model.

Normalization is:

* Unicode NFC.
* CRLF and CR are converted to LF.
* Byte-order marks and zero-width characters are stripped.
* Leading and trailing whitespace is removed from each line and the whole
  document.
* Repeated internal whitespace runs (space, tab, form-feed) collapse to a
  single space, but *newlines* are preserved so paragraph boundaries survive
  for classification.

The version string ``NORMALIZATION_VERSION`` is bumped whenever the algorithm
changes and is emitted in :class:`~player_triage.records.NormalizedMessage`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from .errors import InvalidConfigurationError
from .records import NormalizedMessage, RawMessage

NORMALIZATION_VERSION: Final[str] = "norm-1.0.0"

_ZERO_WIDTH: Final[str] = "​‌‍﻿⁠"
_ZERO_WIDTH_RE: Final[re.Pattern[str]] = re.compile(f"[{re.escape(_ZERO_WIDTH)}]")
_INLINE_WS_RE: Final[re.Pattern[str]] = re.compile(r"[ \t\f\v]+")
_TRAILING_WS_RE: Final[re.Pattern[str]] = re.compile(r"[ \t\f\v]+\n")


def _canonical(text: str) -> str:
    if not text:
        return ""
    canonical = unicodedata.normalize("NFC", text)
    canonical = canonical.replace("\r\n", "\n").replace("\r", "\n")
    canonical = _ZERO_WIDTH_RE.sub("", canonical)
    canonical = _INLINE_WS_RE.sub(" ", canonical)
    canonical = _TRAILING_WS_RE.sub("\n", canonical)
    return canonical.strip()


def normalize_text(text: str) -> str:
    """Return the canonical text used for classification (case-preserving)."""

    if not isinstance(text, str):
        raise InvalidConfigurationError(
            component="normalization",
            message="normalize_text received non-string input",
        )
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidConfigurationError(
            component="normalization",
            message=f"input is not UTF-8 compatible: {exc.reason}",
        ) from exc
    return _canonical(text)


def detector_view(text: str) -> str:
    """Return the case-folded view of ``normalize_text(text)``.

    ``str.casefold`` is used instead of ``str.lower`` so multilingual text
    normalises consistently.
    """

    return normalize_text(text).casefold()


def normalize_message(raw: RawMessage) -> NormalizedMessage:
    """Produce a :class:`NormalizedMessage` from a :class:`RawMessage`.

    ``player_id`` is deliberately dropped here — downstream types never see it.
    """

    normalized_subject = normalize_text(raw.subject)
    normalized_body = normalize_text(raw.body)
    combined = normalize_text(f"{normalized_subject}\n{normalized_body}")
    return NormalizedMessage(
        msg_id=raw.msg_id,
        received_utc=raw.received_utc,
        channel=raw.channel,
        market=raw.market,
        language=raw.language,
        normalized_subject=normalized_subject,
        normalized_body=normalized_body,
        detector_view=combined.casefold(),
        normalization_version=NORMALIZATION_VERSION,
    )


def is_idempotent(text: str) -> bool:
    """Convenience: assert ``normalize(normalize(text)) == normalize(text)``."""

    once = normalize_text(text)
    return normalize_text(once) == once
