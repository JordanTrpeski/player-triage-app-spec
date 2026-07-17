"""Typed, validated configuration loader.

Design invariants
-----------------
* Every controlled enum surfaced to Python callers is read *at runtime* from
  ``policy/controlled_vocabularies.json``. This module never spells the vocabulary
  values as string literals — a second source of truth would drift.
* Loading is relative to the resolved application root (see
  :mod:`player_triage.paths`), never to the developer's working directory.
* On any failure the loader raises a subclass of
  :class:`player_triage.errors.ConfigurationError` with a sanitized message that
  identifies the component and — where applicable — the offending path within
  the document, but never dataset content.

Cross-component consistency is checked here at load time so that downstream
code can rely on:

* every ``auto_response_template_id`` in ``policy/auto_response_templates.json``
  being a member of ``controlled_vocabularies.auto_response_template_ids``;
* every rationale-template key being a member of
  ``controlled_vocabularies.reason_codes``;
* every controlled-vocabulary array being duplicate-free.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping

from pydantic import BaseModel, ConfigDict, Field

from .errors import (
    ControlledVocabularyError,
    HashIntegrityError,
    InvalidConfigurationError,
    MissingConfigurationError,
    SchemaValidationError,
    UnknownVersionError,
)
from .paths import policy_dir, resolve_app_root
from .schema import SchemaRegistry, build_schema_registry


EXPECTED_CONFIGURATION_VERSION: Final[str] = "policy-3.3.1"

# Manifest-declared optional policy component (introduced in policy-3.1.0). It is
# loaded, schema-validated and hash-verified only when the active manifest lists
# it. A manifest that omits it (e.g. a rollback to policy-3.0.0) simply loads no
# derived-refinement rules, restoring the earlier behaviour.
DERIVED_REFINEMENT_COMPONENT: Final[str] = "derived_refinement_rules"
DERIVED_REFINEMENT_SCHEMA: Final[str] = "derived_refinement_rules_schema.json"

# Optional Phase 04 local-model configuration. Older rollback bundles omit the
# component and remain valid rules-only configurations.
MODEL_CONFIGURATION_COMPONENT: Final[str] = "model_configuration"
MODEL_CONFIGURATION_SCHEMA: Final[str] = "model_configuration_schema.json"

# Component name → filename under ``policy/``. This is the ONLY place in source
# where these filenames live. Every downstream consumer reaches component data
# via :class:`AppConfig.component`.
POLICY_COMPONENT_FILES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "application_requirements": "application_requirements.json",
        "auto_response_templates": "auto_response_templates.json",
        "baseline_intent_rules": "baseline_intent_rules.json",
        "configuration_manifest": "configuration_manifest.json",
        "controlled_vocabularies": "controlled_vocabularies.json",
        "export_contract": "export_contract.json",
        "intents": "intents.json",
        "linkage_policy": "linkage_policy.json",
        "market_overlays": "market_overlays.json",
        "policy_rules": "policy_rules.json",
        "rationale_templates": "rationale_templates.json",
        "redaction_policy": "redaction_policy.json",
        "research_traceability": "research_traceability.json",
        "safety_assertions": "safety_assertions.json",
        "semantic_constraints": "semantic_constraints.json",
        "taxonomy": "taxonomy.json",
        "teams": "teams.json",
        "ui_editability": "ui_editability.json",
    }
)

# Component name → schema $id used to validate it. Components not listed here
# are still loaded but their shape is not schema-validated at Phase 01 (either
# no schema exists yet, or the schema is exercised by dedicated later phases).
POLICY_COMPONENT_SCHEMAS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "auto_response_templates": "auto_response_templates_schema.json",
        "baseline_intent_rules": "baseline_rules_schema.json",
        "configuration_manifest": "config_bundle_schema.json",
        "market_overlays": "market_overlays_schema.json",
        "policy_rules": "policy_rules_schema.json",
        "rationale_templates": "rationale_templates_schema.json",
        "redaction_policy": "redaction_policy_schema.json",
        "semantic_constraints": "semantic_constraints_schema.json",
    }
)


class ConfigurationManifest(BaseModel):
    """Typed view of ``policy/configuration_manifest.json``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version_id: str
    parent_version_id: str | None
    status: str
    created_at: str
    created_by: str
    change_reason: str
    components: Mapping[str, str]
    validation_summary: Mapping[str, Any] | None = None
    impact_summary: Mapping[str, Any] | None = None
    activation_event_id: str | None = None


class ControlledVocabularies(BaseModel):
    """Typed view of ``policy/controlled_vocabularies.json``.

    Every field is a duplicate-free tuple. All catalogues are loaded generically
    so that adding a new controlled catalogue in policy does not require code
    changes here beyond declaring the field.
    """

    # Two vocabulary field names (``model_eligibility`` and ``model_bypass_reasons``)
    # are frozen by the policy contract; disable pydantic's ``model_`` protected
    # namespace so declaring them is not a warning.
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    version: str
    categories: tuple[str, ...]
    priorities: tuple[str, ...]
    routes: tuple[str, ...]
    teams: tuple[str, ...]
    auto_response_policies: tuple[str, ...]
    auto_response_template_ids: tuple[str, ...]
    model_eligibility: tuple[str, ...]
    model_bypass_reasons: tuple[str, ...]
    decision_basis: tuple[str, ...]
    processing_statuses: tuple[str, ...]
    market_framework_status: tuple[str, ...]
    market_overlay_codes: tuple[str, ...]
    intents: tuple[str, ...]
    risk_flags: tuple[str, ...]
    reason_codes: tuple[str, ...]
    sensitive_data_types: tuple[str, ...]
    required_context_keys: tuple[str, ...]
    fallback_reason_codes: tuple[str, ...]
    human_override_reason_codes: tuple[str, ...]
    config_event_types: tuple[str, ...]
    rule_editability: tuple[str, ...]

    def catalogues(self) -> Mapping[str, tuple[str, ...]]:
        """Return every catalogue as an immutable mapping (excludes ``version``)."""

        return MappingProxyType(
            {name: value for name, value in self.model_dump().items() if name != "version"}
        )


@dataclass(frozen=True)
class AppConfig:
    """Central immutable handle to the loaded application contract."""

    app_root: Path
    manifest: ConfigurationManifest
    vocab: ControlledVocabularies
    components: Mapping[str, Mapping[str, Any]]
    schema_registry: SchemaRegistry

    @property
    def configuration_version(self) -> str:
        return self.manifest.version_id

    def component(self, name: str) -> Mapping[str, Any]:
        if name not in self.components:
            raise MissingConfigurationError(
                component=name,
                message="policy component was not loaded",
            )
        return self.components[name]

    def component_version(self, name: str) -> str:
        raw = self.component(name)
        version = raw.get("version")
        if not isinstance(version, str):
            raise SchemaValidationError(
                component=name,
                message="component is missing a top-level string 'version' field",
            )
        return version

    def component_versions(self) -> Mapping[str, str]:
        return MappingProxyType(
            {name: self.component_version(name) for name in self.components if "version" in self.components[name]}
        )

    def schema_ids(self) -> Mapping[str, str]:
        return self.schema_registry.ids

    @property
    def bundle_version(self) -> str:
        """The active policy-bundle version id from the manifest."""

        return self.manifest.version_id

    def has_component(self, name: str) -> bool:
        return name in self.components

    def component_digest(self, name: str) -> str | None:
        """The manifest-recorded SHA-256 digest for a component, if any."""

        return self.manifest.components.get(name)


def _read_json(path: Path, component: str) -> Any:
    if not path.is_file():
        raise MissingConfigurationError(
            component=component,
            message="required configuration file is not present",
            path=path,
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidConfigurationError(
            component=component,
            message=f"could not read file: {exc.strerror or 'io error'}",
            path=path,
        ) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidConfigurationError(
            component=component,
            message=f"file is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}",
            path=path,
        ) from exc


def _check_vocab_no_duplicates(vocab: ControlledVocabularies) -> None:
    for name, values in vocab.catalogues().items():
        seen: dict[str, int] = {}
        for index, value in enumerate(values):
            if value in seen:
                raise ControlledVocabularyError(
                    component="controlled_vocabularies",
                    message=(
                        f"catalogue {name!r} contains duplicate entry at index {index} "
                        f"(first occurrence at index {seen[value]})"
                    ),
                )
            seen[value] = index


def _check_cross_component_consistency(
    vocab: ControlledVocabularies,
    components: Mapping[str, Mapping[str, Any]],
) -> None:
    templates = components.get("auto_response_templates", {}).get("templates") or []
    template_ids: set[str] = {
        t["id"] for t in templates if isinstance(t, dict) and isinstance(t.get("id"), str)
    }
    vocab_template_ids = set(vocab.auto_response_template_ids)
    unknown_templates = sorted(template_ids - vocab_template_ids)
    if unknown_templates:
        raise ControlledVocabularyError(
            component="auto_response_templates",
            message=(
                "templates reference IDs not present in controlled vocabulary "
                f"auto_response_template_ids: {unknown_templates}"
            ),
        )
    missing_templates = sorted(vocab_template_ids - template_ids)
    if missing_templates:
        raise ControlledVocabularyError(
            component="auto_response_templates",
            message=(
                "controlled vocabulary declares template IDs that no template defines: "
                f"{missing_templates}"
            ),
        )

    vocab_teams = set(vocab.teams)
    unknown_owners = sorted(
        {
            t["owner"]
            for t in templates
            if isinstance(t, dict) and isinstance(t.get("owner"), str) and t["owner"] not in vocab_teams
        }
    )
    if unknown_owners:
        raise ControlledVocabularyError(
            component="auto_response_templates",
            message=f"template owner values not in controlled team catalogue: {unknown_owners}",
        )

    rationale = components.get("rationale_templates", {}).get("templates") or {}
    if not isinstance(rationale, dict):
        raise SchemaValidationError(
            component="rationale_templates",
            message="templates block is not a JSON object",
        )
    vocab_reason_codes = set(vocab.reason_codes)
    unknown_rationale = sorted(set(rationale.keys()) - vocab_reason_codes)
    if unknown_rationale:
        raise ControlledVocabularyError(
            component="rationale_templates",
            message=(
                "rationale templates reference reason codes not in controlled vocabulary: "
                f"{unknown_rationale}"
            ),
        )
    missing_rationale = sorted(vocab_reason_codes - set(rationale.keys()))
    if missing_rationale:
        raise ControlledVocabularyError(
            component="rationale_templates",
            message=(
                "controlled vocabulary declares reason codes without a rationale template: "
                f"{missing_rationale}"
            ),
        )


def _load_manifest_declared_component(
    directory: Path,
    manifest: "ConfigurationManifest",
    components: dict[str, Mapping[str, Any]],
    schema_registry: SchemaRegistry,
    *,
    component_name: str,
    schema_filename: str,
) -> None:
    """Load, schema-validate and hash-verify an optional manifest-declared component.

    A component is only loaded when the active manifest lists it under
    ``components`` (with its expected digest). Absence is a valid governed state
    (e.g. a rollback to a version that predates the component). When declared, a
    missing file, malformed JSON, schema failure or digest mismatch all fail
    closed.
    """

    expected_digest = manifest.components.get(component_name)
    if expected_digest is None:
        return  # component not part of the active bundle (rolled back / absent)

    path = directory / f"{component_name}.json"
    raw = _read_json(path, component_name)  # raises MissingConfigurationError if absent

    schema_id = schema_registry.ids.get(schema_filename)
    if schema_id is None:
        raise MissingConfigurationError(
            component=schema_filename,
            message="schema referenced by loader is not present under schemas/",
        )
    schema_registry.validate(schema_id, raw, component_hint=component_name)

    actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise HashIntegrityError(
            component=component_name,
            message="on-disk digest does not match the configuration manifest",
            path=path,
        )
    components[component_name] = raw


def _verify_manifest_declared_fixed_components(
    directory: Path,
    manifest: "ConfigurationManifest",
) -> None:
    """Hash-verify fixed components for bundles opting into full provenance.

    Policy-3.3.1 is the first bundle to declare the traceability/UI digests and
    therefore opts into this stricter check. Older archived manifests retain
    their historical loader behavior for reproducible rollback tests.
    """

    if "research_traceability" not in manifest.components:
        return
    for component_name, expected_digest in manifest.components.items():
        filename = POLICY_COMPONENT_FILES.get(component_name)
        if filename is None or component_name == "configuration_manifest":
            continue
        path = directory / filename
        if not path.is_file():
            raise MissingConfigurationError(
                component=component_name,
                message="manifest-declared policy component is missing",
                path=path,
            )
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise HashIntegrityError(
                component=component_name,
                message="on-disk digest does not match the configuration manifest",
                path=path,
            )


def load_app_config(
    app_root: Path | str | None = None,
    *,
    strict_version: bool = True,
    expected_version: str = EXPECTED_CONFIGURATION_VERSION,
) -> AppConfig:
    """Load, validate and return the frozen application configuration."""

    root = resolve_app_root(app_root)
    directory = policy_dir(root)
    if not directory.is_dir():
        raise MissingConfigurationError(
            component="policy",
            message="policy directory not found under application root",
            path=directory,
        )

    schema_registry = build_schema_registry(root)

    components: dict[str, Mapping[str, Any]] = {}
    for component_name, filename in POLICY_COMPONENT_FILES.items():
        components[component_name] = _read_json(directory / filename, component_name)

    for component_name, schema_filename in POLICY_COMPONENT_SCHEMAS.items():
        schema_id = schema_registry.ids.get(schema_filename)
        if schema_id is None:
            raise MissingConfigurationError(
                component=schema_filename,
                message="schema referenced by loader is not present under schemas/",
            )
        schema_registry.validate(
            schema_id,
            components[component_name],
            component_hint=component_name,
        )

    try:
        manifest = ConfigurationManifest.model_validate(components["configuration_manifest"])
    except Exception as exc:
        raise SchemaValidationError(
            component="configuration_manifest",
            message=f"manifest does not conform to typed model: {exc}",
        ) from exc

    if strict_version and manifest.version_id != expected_version:
        raise UnknownVersionError(
            component="configuration_manifest",
            message=(
                f"manifest version {manifest.version_id!r} does not match expected "
                f"application build {expected_version!r}"
            ),
        )

    _verify_manifest_declared_fixed_components(directory, manifest)

    try:
        vocab = ControlledVocabularies.model_validate(components["controlled_vocabularies"])
    except Exception as exc:
        raise SchemaValidationError(
            component="controlled_vocabularies",
            message=f"controlled vocabularies do not conform to typed model: {exc}",
        ) from exc

    _check_vocab_no_duplicates(vocab)
    _check_cross_component_consistency(vocab, components)

    _load_manifest_declared_component(
        directory,
        manifest,
        components,
        schema_registry,
        component_name=DERIVED_REFINEMENT_COMPONENT,
        schema_filename=DERIVED_REFINEMENT_SCHEMA,
    )
    _load_manifest_declared_component(
        directory,
        manifest,
        components,
        schema_registry,
        component_name=MODEL_CONFIGURATION_COMPONENT,
        schema_filename=MODEL_CONFIGURATION_SCHEMA,
    )

    return AppConfig(
        app_root=root,
        manifest=manifest,
        vocab=vocab,
        components=MappingProxyType(components),
        schema_registry=schema_registry,
    )
