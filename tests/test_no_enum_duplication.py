"""The Python codebase must not restate any controlled-vocabulary value.

Enums live in ``policy/controlled_vocabularies.json``. Any string literal in
``src/player_triage/`` that matches a vocabulary value would create a second
source of truth that could drift from the policy. This test enforces the
single-source rule by scanning source files for such literals.

Structural policy identifiers (``version_id``, ``version``, ``rules``, …) are
allowed because they are field names, not vocabulary values. Only members of
controlled catalogues are checked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "player_triage"


@pytest.fixture(scope="module")
def controlled_values(app_root: Path) -> set[str]:
    vocab = json.loads((app_root / "policy" / "controlled_vocabularies.json").read_text(encoding="utf-8"))
    collected: set[str] = set()
    for name, values in vocab.items():
        if name == "version":
            continue
        if isinstance(values, list):
            collected.update(str(v) for v in values)
    return collected


def _iter_python_sources(package_root: Path) -> list[Path]:
    return [p for p in package_root.rglob("*.py") if p.is_file()]


def test_no_controlled_vocabulary_string_in_source(controlled_values: set[str]) -> None:
    forbidden = set(controlled_values)
    # Trivially short catalogue values ("low", "high") appear as common English words
    # and would generate false positives from module docstrings. Restrict the check
    # to catalogue values that are meaningful identifiers (>= 4 characters and
    # containing an underscore, or containing an uppercase letter, or containing
    # a space/ampersand — i.e., unambiguous vocabulary strings).
    def is_unambiguous(value: str) -> bool:
        if len(value) < 4:
            return False
        return (
            "_" in value
            or any(ch.isupper() for ch in value)
            or " " in value
            or "&" in value
        )

    literal_pattern = re.compile(r"([\"'])([^\"']+)\1")
    hits: list[tuple[Path, int, str]] = []
    for source in _iter_python_sources(PACKAGE_ROOT):
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for match in literal_pattern.finditer(line):
                value = match.group(2)
                if value in forbidden and is_unambiguous(value):
                    hits.append((source, line_number, value))

    assert not hits, (
        "controlled-vocabulary values must not be hard-coded in source: "
        + "; ".join(f"{p.relative_to(PACKAGE_ROOT.parent.parent)}:{n} {v!r}" for p, n, v in hits)
    )
