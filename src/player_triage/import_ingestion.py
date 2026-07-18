"""Fault-tolerant ingestion for operator-imported datasets.

This is the general import path. It is deliberately distinct from
:mod:`player_triage.ingestion`, which remains the strict, fail-fast loader for
the supplied-40 benchmark.

Two behavioural differences matter:

1. **Identifiers.** Rows carry ``source_message_id`` matching
   ``^M[0-9]{1,9}$`` rather than the benchmark's ``^M\\d{2}$``. The supplied
   value is preserved exactly; see :mod:`player_triage.imported_identifiers`.

2. **Invalid rows are reported, not fatal.** A malformed row does not abort the
   import. It is recorded as a sanitized :class:`~player_triage.records.
   ValidationIssue` and the remaining rows still process. Invalid rows are
   never silently discarded — every rejected row appears in the returned issue
   list and, downstream, in ``validation_errors.csv``.

Structural problems that make the file as a whole unusable (missing or
duplicated headers, an empty workbook, an unreadable file) remain fatal and
raise :class:`~player_triage.ingestion.IngestionError`: there is no meaningful
per-row result to report in those cases.

Every field other than the identifier is validated by exactly the same code as
the benchmark path, so import cannot drift from accepted validation semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterator

from .imported_identifiers import (
    COLLISION_MODE_ERROR,
    IMPORTED_MESSAGE_ID_PATTERN_TEXT,
    is_valid_imported_message_id,
    normalize_collision_mode,
    parse_imported_message_id,
)
from .ingestion import (
    IngestionError,
    _iter_csv_rows,
    _iter_xlsx_rows,
    _validate_and_build,
)
from .records import RawMessage, ValidationIssue

#: Upper bound on rows accepted from a single imported file. Well above the
#: supported batch sizes; guards against a pathological or corrupt workbook.
MAX_IMPORT_ROWS: Final[int] = 100_000

# Sanitized issue codes. These appear in validation_errors.csv and must never
# be derived from source content.
CODE_INVALID_SOURCE_MESSAGE_ID: Final[str] = "invalid_source_message_id"
CODE_DUPLICATE_SOURCE_MESSAGE_ID: Final[str] = "duplicate_source_message_id"
CODE_NUMERIC_COLLISION: Final[str] = "ambiguous_padded_id_collision"
CODE_INVALID_ROW: Final[str] = "invalid_row"


def _imported_message_id_error(msg_id: str) -> str | None:
    if not is_valid_imported_message_id(msg_id):
        return f"source_message_id must match {IMPORTED_MESSAGE_ID_PATTERN_TEXT}"
    return None


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Outcome of an imported-file load.

    ``messages`` holds the rows that validated, in numeric-aware
    ``source_message_id`` order. ``issues`` holds one sanitized entry per
    rejected row. ``rows_seen`` counts every data row encountered, so
    ``rows_seen == len(messages) + len(issues)`` always holds.
    """

    messages: tuple[RawMessage, ...]
    issues: tuple[ValidationIssue, ...]
    rows_seen: int
    source_format: str

    @property
    def accepted_count(self) -> int:
        return len(self.messages)

    @property
    def rejected_count(self) -> int:
        return len(self.issues)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    @property
    def is_empty(self) -> bool:
        """True when no row validated, regardless of how many were rejected."""

        return not self.messages


def _load_rows(
    rows: Iterator[tuple[int, dict[str, str]]],
    *,
    source: Path,
    source_format: str,
    collision_mode: str,
) -> ImportResult:
    mode = normalize_collision_mode(collision_mode)

    messages: list[RawMessage] = []
    issues: list[ValidationIssue] = []
    seen_text: set[str] = set()
    seen_numeric: dict[int, str] = {}
    rows_seen = 0

    for source_row, row in rows:
        rows_seen += 1
        if rows_seen > MAX_IMPORT_ROWS:
            raise IngestionError(
                component="import_ingestion",
                message=f"imported file exceeds {MAX_IMPORT_ROWS} rows",
                path=source,
            )

        raw_id = (row.get("msg_id") or "").strip()

        # Identifier shape is checked first so a malformed identifier is
        # reported as such rather than as a generic row failure.
        if not is_valid_imported_message_id(raw_id):
            issues.append(
                ValidationIssue(
                    msg_id=None,
                    source_row=source_row,
                    code=CODE_INVALID_SOURCE_MESSAGE_ID,
                    detail=(
                        "source_message_id must match "
                        f"{IMPORTED_MESSAGE_ID_PATTERN_TEXT}"
                    ),
                )
            )
            continue

        identifier = parse_imported_message_id(raw_id)

        if identifier.text in seen_text:
            issues.append(
                ValidationIssue(
                    msg_id=identifier.text,
                    source_row=source_row,
                    code=CODE_DUPLICATE_SOURCE_MESSAGE_ID,
                    detail=f"duplicate source_message_id {identifier.text}",
                )
            )
            continue

        # M99 and M099 are textually distinct but denote the same number.
        # Zero-padding is preserved rather than normalized, so this is reported
        # as a configurable collision instead of silently merging the rows.
        collided_with = seen_numeric.get(identifier.numeric)
        if collided_with is not None and mode == COLLISION_MODE_ERROR:
            issues.append(
                ValidationIssue(
                    msg_id=identifier.text,
                    source_row=source_row,
                    code=CODE_NUMERIC_COLLISION,
                    detail=(
                        f"source_message_id {identifier.text} collides "
                        f"numerically with {collided_with}"
                    ),
                )
            )
            continue

        try:
            message = _validate_and_build(
                row,
                source=source,
                source_row=source_row,
                source_format=source_format,
                seen_ids=seen_text,
                message_id_error=_imported_message_id_error,
            )
        except IngestionError as exc:
            # exc.message is already sanitized: it carries no subject, body,
            # player_id or filesystem path.
            issues.append(
                ValidationIssue(
                    msg_id=identifier.text,
                    source_row=source_row,
                    code=CODE_INVALID_ROW,
                    detail=exc.message,
                )
            )
            continue

        messages.append(message)
        seen_numeric.setdefault(identifier.numeric, identifier.text)

    ordered = tuple(
        sorted(
            messages,
            key=lambda message: (int(message.msg_id[1:]), message.msg_id),
        )
    )
    return ImportResult(
        messages=ordered,
        issues=tuple(issues),
        rows_seen=rows_seen,
        source_format=source_format,
    )


def load_imported_csv(
    path: Path | str, *, collision_mode: str = COLLISION_MODE_ERROR
) -> ImportResult:
    """Import a CSV, collecting per-row issues instead of failing fast."""

    source = Path(path)
    if not source.is_file():
        raise IngestionError(
            component="import_ingestion", message="CSV input not found", path=source
        )
    return _load_rows(
        _iter_csv_rows(source),
        source=source,
        source_format="csv",
        collision_mode=collision_mode,
    )


def load_imported_xlsx(
    path: Path | str, *, collision_mode: str = COLLISION_MODE_ERROR
) -> ImportResult:
    """Import an XLSX workbook, collecting per-row issues instead of failing fast."""

    source = Path(path)
    if not source.is_file():
        raise IngestionError(
            component="import_ingestion", message="XLSX input not found", path=source
        )
    return _load_rows(
        _iter_xlsx_rows(source),
        source=source,
        source_format="xlsx",
        collision_mode=collision_mode,
    )


def load_imported(
    path: Path | str, *, collision_mode: str = COLLISION_MODE_ERROR
) -> ImportResult:
    """Dispatch to the CSV or XLSX importer based on file suffix."""

    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return load_imported_csv(source, collision_mode=collision_mode)
    if suffix == ".xlsx":
        return load_imported_xlsx(source, collision_mode=collision_mode)
    raise IngestionError(
        component="import_ingestion",
        message=f"unsupported input format {suffix!r}",
        path=source,
    )
