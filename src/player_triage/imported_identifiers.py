"""Identifier handling for imported datasets.

This module is deliberately separate from the supplied-40 benchmark contract.

The benchmark keeps ``msg_id`` with the two-digit pattern ``^M\\d{2}$``
(M01–M40), its ground truth, its policy validators and its canonical decision
digest. None of that is changed by import support.

Imported datasets instead carry ``source_message_id``, which accepts
``^M[0-9]{1,9}$``. The imported value is preserved **exactly** as supplied:
``M1``, ``M01`` and ``M001`` are three distinct source identifiers and are never
rewritten, zero-padded or truncated. Ordering is numeric-aware so that M2 sorts
before M10, which lexical ordering would get wrong.

Because zero-padding is preserved rather than normalized, two rows in the same
batch can carry textually distinct identifiers that denote the same number
(``M99`` and ``M099``). That is treated as a configurable *validation
collision*, reported against the offending row. It is never a reason to modify
the supplied-set policy contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Imported source identifiers. Deliberately wider than the benchmark's
#: ``^M\d{2}$``: accepts M1, M01, M001, M99, M099, M100, M1000 and so on, up to
#: nine digits. The bound guards against pathological input while comfortably
#: exceeding any realistic batch.
IMPORTED_MESSAGE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^M[0-9]{1,9}$")

#: Human-readable form of the pattern, used in sanitized error messages.
IMPORTED_MESSAGE_ID_PATTERN_TEXT: Final[str] = "^M[0-9]{1,9}$"

#: How to treat two identifiers that differ textually but denote the same
#: number (``M99`` / ``M099``) within one imported batch.
COLLISION_MODE_ERROR: Final[str] = "error"
COLLISION_MODE_ALLOW: Final[str] = "allow"
COLLISION_MODES: Final[frozenset[str]] = frozenset(
    {COLLISION_MODE_ERROR, COLLISION_MODE_ALLOW}
)
DEFAULT_COLLISION_MODE: Final[str] = COLLISION_MODE_ERROR


class ImportedIdentifierError(ValueError):
    """Raised when a value is not a usable imported source identifier."""


@dataclass(frozen=True, slots=True)
class ImportedMessageId:
    """A validated imported identifier.

    ``text`` is the exact value supplied by the source file and is what gets
    written to every output artifact. ``numeric`` is derived only for ordering
    and collision detection and is never substituted for ``text``.
    """

    text: str
    numeric: int

    def __str__(self) -> str:
        return self.text


def is_valid_imported_message_id(value: str) -> bool:
    """Return whether ``value`` is an acceptable imported source identifier."""

    return bool(IMPORTED_MESSAGE_ID_PATTERN.match(value))


def parse_imported_message_id(value: str) -> ImportedMessageId:
    """Validate an imported identifier, preserving its exact text.

    Raises :class:`ImportedIdentifierError` with a sanitized message when the
    value does not match :data:`IMPORTED_MESSAGE_ID_PATTERN`. The offending
    value is not echoed back, so this is safe to surface in operator-facing
    error reports.
    """

    if not is_valid_imported_message_id(value):
        raise ImportedIdentifierError(
            f"source_message_id must match {IMPORTED_MESSAGE_ID_PATTERN_TEXT}"
        )
    return ImportedMessageId(text=value, numeric=int(value[1:]))


def imported_id_sort_key(value: str) -> tuple[int, int, str]:
    """Numeric-aware sort key for imported identifiers.

    M2 sorts before M10. Identifiers denoting the same number are then ordered
    by their exact text, so ``M99`` and ``M099`` have a stable relative order.
    Values that do not match the imported pattern sort last, grouped together
    and ordered lexically, so an unparseable identifier can never crash a sort.
    """

    if not is_valid_imported_message_id(value):
        return (1, 0, value)
    return (0, int(value[1:]), value)


def sort_imported_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    """Return ``values`` in numeric-aware order."""

    return tuple(sorted(values, key=imported_id_sort_key))


def normalize_collision_mode(mode: str | None) -> str:
    """Validate and default the numeric-collision mode."""

    if mode is None:
        return DEFAULT_COLLISION_MODE
    if mode not in COLLISION_MODES:
        raise ImportedIdentifierError(
            f"collision mode must be one of {sorted(COLLISION_MODES)}"
        )
    return mode
