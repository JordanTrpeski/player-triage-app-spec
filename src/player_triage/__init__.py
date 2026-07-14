"""Player-contact triage prototype implementing the frozen Stage 9 policy contract."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("player_triage")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
