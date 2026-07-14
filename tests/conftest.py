"""Shared test fixtures.

The ``app_root`` fixture points at the real repository root. The ``mutated_app_root``
factory copies the whole ``policy/``, ``schemas/`` and ``input/`` tree into a
temporary directory so a test can mutate individual files without disturbing
the authoritative bundle. The fixture is deliberately verbose to make it
obvious that no test ever writes back into the real ``policy/`` directory.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Iterator

import pytest

from player_triage.paths import resolve_app_root


@pytest.fixture(scope="session")
def app_root() -> Path:
    return resolve_app_root()


@pytest.fixture()
def mutated_app_root(app_root: Path, tmp_path: Path) -> Iterator[Callable[[], Path]]:
    def _make() -> Path:
        destination = tmp_path / "app"
        destination.mkdir()
        for name in ("policy", "schemas", "input"):
            shutil.copytree(app_root / name, destination / name)
        return destination

    yield _make
