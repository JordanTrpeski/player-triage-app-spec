"""JSON Schema registry.

Compiles every schema shipped in ``schemas/`` under Draft 2020-12 and exposes
precompiled validators for the four contract shapes we already care about in
Phase 01:

* ``output_schema.json`` — final triage decision
* ``audit_event_schema.json`` — audit events (references output_schema and
  evaluation_summary_schema)
* ``ground_truth_schema.json`` — the 40 authoritative expected results
* ``model_candidate_schema.json`` — proposals from the (future) local model

The registry uses ``$id`` values as the identifier so cross-schema ``$ref``
resolves without HTTP access and without duplicating any enum values in Python.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .errors import InvalidConfigurationError, MissingConfigurationError, SchemaValidationError
from .paths import schemas_dir


@dataclass(frozen=True)
class SchemaRegistry:
    """Holds the compiled schema registry and precompiled validators."""

    registry: Registry
    schemas: Mapping[str, Mapping[str, Any]]
    ids: Mapping[str, str]

    def validator(self, schema_id: str) -> Draft202012Validator:
        if schema_id not in self.schemas:
            raise MissingConfigurationError(
                component=schema_id,
                message="schema identifier is not registered",
            )
        return Draft202012Validator(dict(self.schemas[schema_id]), registry=self.registry)

    def validate(self, schema_id: str, document: Any, *, component_hint: str | None = None) -> None:
        validator = self.validator(schema_id)
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
        if errors:
            first = errors[0]
            path = "/".join(str(part) for part in first.absolute_path) or "<root>"
            raise SchemaValidationError(
                component=component_hint or schema_id,
                message=f"schema validation failed at {path}: {first.message}",
            )


def _read_schema_file(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MissingConfigurationError(
            component=path.name,
            message="schema file not found",
            path=path,
        ) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidConfigurationError(
            component=path.name,
            message=f"schema is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}",
            path=path,
        ) from exc


def build_schema_registry(app_root: Path) -> SchemaRegistry:
    """Load and compile every JSON Schema under ``schemas/``."""

    directory = schemas_dir(app_root)
    if not directory.is_dir():
        raise MissingConfigurationError(
            component="schemas",
            message="schemas directory not found",
            path=directory,
        )

    schemas: dict[str, Mapping[str, Any]] = {}
    ids: dict[str, str] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    for path in sorted(directory.glob("*.json")):
        document = _read_schema_file(path)
        try:
            Draft202012Validator.check_schema(document)
        except Exception as exc:
            raise SchemaValidationError(
                component=path.name,
                message=f"schema does not compile under Draft 2020-12: {exc}",
                path=path,
            ) from exc
        schema_id = document.get("$id", path.name)
        schemas[schema_id] = document
        ids[path.name] = schema_id
        resource: Resource[Any] = Resource.from_contents(dict(document))
        resources.append((schema_id, resource))

    registry: Registry[Any] = Registry().with_resources(resources)
    return SchemaRegistry(registry=registry, schemas=schemas, ids=ids)
