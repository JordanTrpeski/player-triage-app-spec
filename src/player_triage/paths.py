"""Deterministic application-root resolution.

The application never resolves configuration paths from ``os.getcwd()``.
Resolution order:

1. Explicit ``app_root`` argument to :func:`resolve_app_root`.
2. ``PLAYER_TRIAGE_APP_ROOT`` environment variable.
3. Walk up from this module's directory until a directory containing
   ``policy/``, ``schemas/`` and ``input/`` is found. This handles both
   editable installs (repo checkout) and installed packages placed
   inside the repository.

If none of these succeed a :class:`~player_triage.errors.MissingConfigurationError`
is raised, sanitized to the search hint only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from .errors import MissingConfigurationError

_MARKER_DIRECTORIES: Final[tuple[str, ...]] = ("policy", "schemas", "input")
_ENV_VAR: Final[str] = "PLAYER_TRIAGE_APP_ROOT"


def _looks_like_app_root(candidate: Path) -> bool:
    return all((candidate / marker).is_dir() for marker in _MARKER_DIRECTORIES)


def _walk_up_from(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if _looks_like_app_root(candidate):
            return candidate
    return None


def resolve_app_root(app_root: Path | str | None = None) -> Path:
    """Return the absolute application root.

    Never consults :func:`os.getcwd`. Raises :class:`MissingConfigurationError`
    if no directory containing the required marker subdirectories can be found.
    """

    if app_root is not None:
        candidate = Path(app_root).resolve()
        if not _looks_like_app_root(candidate):
            raise MissingConfigurationError(
                component="app_root",
                message=(
                    "supplied app_root does not contain required marker "
                    f"directories {list(_MARKER_DIRECTORIES)}"
                ),
                path=candidate,
            )
        return candidate

    env_value = os.environ.get(_ENV_VAR)
    if env_value:
        candidate = Path(env_value).resolve()
        if not _looks_like_app_root(candidate):
            raise MissingConfigurationError(
                component="app_root",
                message=(
                    f"{_ENV_VAR} points to a directory that is missing required "
                    f"marker directories {list(_MARKER_DIRECTORIES)}"
                ),
                path=candidate,
            )
        return candidate

    module_dir = Path(__file__).resolve().parent
    discovered = _walk_up_from(module_dir)
    if discovered is not None:
        return discovered

    raise MissingConfigurationError(
        component="app_root",
        message=(
            "could not locate application root: no ancestor of the package "
            f"directory contains {list(_MARKER_DIRECTORIES)}. "
            f"Set {_ENV_VAR} or pass app_root explicitly."
        ),
        path=module_dir,
    )


def policy_dir(app_root: Path) -> Path:
    return app_root / "policy"


def schemas_dir(app_root: Path) -> Path:
    return app_root / "schemas"


def input_dir(app_root: Path) -> Path:
    return app_root / "input"


def config_versions_dir(app_root: Path) -> Path:
    return app_root / "policy" / "config_versions"
