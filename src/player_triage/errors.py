"""Sanitized configuration-error types.

Every error message identifies the offending artifact by relative path and
component name only. Raw dataset content, message bodies, sensitive tokens
and player identifiers must never appear in error messages, log lines or
test output.
"""

from __future__ import annotations

from pathlib import Path


class ConfigurationError(Exception):
    """Base class for all configuration failures raised by the loader."""

    def __init__(self, component: str, message: str, *, path: Path | None = None) -> None:
        self.component = component
        self.path_hint = str(path) if path is not None else None
        detail = f"[{component}] {message}"
        if self.path_hint is not None:
            detail = f"{detail} (source: {self.path_hint})"
        super().__init__(detail)


class MissingConfigurationError(ConfigurationError):
    """A required configuration file is not present on disk."""


class InvalidConfigurationError(ConfigurationError):
    """A configuration file exists but its contents are not valid JSON/JSONL."""


class SchemaValidationError(ConfigurationError):
    """A configuration file fails validation against its JSON Schema."""


class UnknownVersionError(ConfigurationError):
    """The configuration manifest reports a version this build does not support."""


class ControlledVocabularyError(ConfigurationError):
    """Controlled vocabulary is internally inconsistent (duplicates or missing keys)."""
