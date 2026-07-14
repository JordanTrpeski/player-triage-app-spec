"""The Python codebase must not restate classification-catalogue values.

The catalogues whose members are *classification decisions* — categories,
intents, priorities, routes, teams, auto-response policies, and template
IDs — live in ``policy/controlled_vocabularies.json``. Restating those in
source would let policy drift silently, so any string literal in
``src/player_triage/`` that matches one of those values is forbidden.

Catalogues whose members are the mechanical *outputs* of ingestion/detection
/eligibility (risk flags, reason codes, model-eligibility states, bypass
reasons, market overlay codes, etc.) legitimately appear as emitted string
constants in the code that produces those outputs. They are exempted here
because forcing them through a lookup would move the same identifiers into a
different source location without adding any protection against drift.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "player_triage"

# Only these catalogues are forbidden to appear as hard-coded string literals
# in the package. Adding a new decision catalogue in policy should extend this
# list.
FORBIDDEN_CATALOGUES = {
    "categories",
    "intents",
    "routes",
    "priorities",
    "teams",
    "auto_response_policies",
    "auto_response_template_ids",
}


@pytest.fixture(scope="module")
def controlled_values(app_root: Path) -> set[str]:
    vocab = json.loads((app_root / "policy" / "controlled_vocabularies.json").read_text(encoding="utf-8"))
    collected: set[str] = set()
    for name, values in vocab.items():
        if name not in FORBIDDEN_CATALOGUES:
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
