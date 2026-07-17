"""Small, typed primitives for durable structured artifacts.

The operational and evaluation layers share these primitives so callers never
publish a final-looking partial file.  Content is written to a collision-safe
temporary sibling, flushed, synced and atomically renamed.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Mapping


def stable_json(value: object) -> str:
    """Return the canonical JSON representation used for digests."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, document: Mapping[str, object]) -> None:
    atomic_write_text(path, stable_json(document) + "\n")


def atomic_write_text(path: Path, content: str) -> None:
    """Durably replace *path* with text or leave no partial final artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

