"""Governed model-configuration resolution with portable local paths."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ..config import AppConfig, MODEL_CONFIGURATION_COMPONENT
from ..errors import InvalidConfigurationError, MissingConfigurationError
from .providers import (
    DisabledSemanticClassifier,
    LocalModelSemanticClassifier,
    LocalModelSettings,
)
from .validate import CandidateValidator

_PROMPT_FILE = "classifier_prompt.txt"


def resolve_model_path(component: Mapping[str, Any]) -> Path:
    """Resolve the approved portable path reference without repository storage."""

    reference = component.get("local_path_reference")
    if not isinstance(reference, Mapping):
        raise InvalidConfigurationError(
            component=MODEL_CONFIGURATION_COMPONENT,
            message="local_path_reference is not an object",
        )
    env_name = reference.get("environment_variable")
    filename = reference.get("filename")
    if not isinstance(env_name, str) or not isinstance(filename, str):
        raise InvalidConfigurationError(
            component=MODEL_CONFIGURATION_COMPONENT,
            message="local path reference is incomplete",
        )
    override = os.environ.get(env_name)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".player-triage" / "models" / filename).resolve()


def build_local_classifier(
    config: AppConfig,
) -> LocalModelSemanticClassifier | DisabledSemanticClassifier:
    """Build the governed adapter; runtime loading remains lazy until a call."""

    if not config.has_component(MODEL_CONFIGURATION_COMPONENT):
        return DisabledSemanticClassifier()
    raw = config.component(MODEL_CONFIGURATION_COMPONENT)
    if raw.get("enabled") is not True or raw.get("approval_status") not in {
        "evaluation_only",
        "approved_optional",
    }:
        return DisabledSemanticClassifier()
    generation = raw.get("generation")
    if not isinstance(generation, Mapping):
        raise InvalidConfigurationError(
            component=MODEL_CONFIGURATION_COMPONENT,
            message="generation settings are not an object",
        )
    settings = LocalModelSettings(
        model_path=resolve_model_path(raw),
        expected_sha256=_required_string(raw, "sha256"),
        model_id=_required_string(raw, "approved_model_id"),
        revision=_required_string(raw, "revision"),
        runtime_version=_required_string(raw, "runtime_version"),
        prompt_path=config.app_root / "policy" / _PROMPT_FILE,
        expected_prompt_version=_required_string(raw, "prompt_version"),
        expected_prompt_sha256=_required_string(raw, "prompt_sha256"),
        context_limit=_required_int(raw, "context_limit"),
        output_token_limit=_required_int(raw, "output_token_limit"),
        timeout_seconds=_required_number(raw, "timeout_seconds"),
        temperature=_required_number(generation, "temperature"),
        max_schema_retries=_required_int(generation, "max_schema_retries"),
    )
    return LocalModelSemanticClassifier(settings, CandidateValidator.from_config(config))


def _required_string(value: Mapping[str, Any], key: str) -> str:
    found = value.get(key)
    if not isinstance(found, str):
        raise MissingConfigurationError(
            component=MODEL_CONFIGURATION_COMPONENT,
            message=f"required string setting {key!r} is missing",
        )
    return found


def _required_int(value: Mapping[str, Any], key: str) -> int:
    found = value.get(key)
    if not isinstance(found, int) or isinstance(found, bool):
        raise MissingConfigurationError(
            component=MODEL_CONFIGURATION_COMPONENT,
            message=f"required integer setting {key!r} is missing",
        )
    return found


def _required_number(value: Mapping[str, Any], key: str) -> float:
    found = value.get(key)
    if not isinstance(found, (int, float)) or isinstance(found, bool):
        raise MissingConfigurationError(
            component=MODEL_CONFIGURATION_COMPONENT,
            message=f"required numeric setting {key!r} is missing",
        )
    return float(found)
