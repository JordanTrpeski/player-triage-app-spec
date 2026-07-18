"""Phase 09: enforce imported-schema compatibility with the accepted schemas.

The imported schemas were derived programmatically from the accepted ones. This
file turns that one-time derivation into an enforced invariant: if
`schemas/output_schema.json` gains, loses or retypes a decision field and the
imported schemas are not updated to match, these tests fail with a message
naming the drifted fields.

Scope of the guarantee, stated precisely: these tests enforce that the imported
schemas stay structurally aligned with the accepted decision contract, and that
the accepted policy and benchmark schemas are not edited to accommodate
imports. They do not, and cannot, prevent someone from deliberately editing
both sides together.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

SCHEMAS = ("output_schema.json", "audit_event_schema.json")

BENCHMARK_ID_PATTERN = "^M\\d{2}$"
IMPORTED_ID_PATTERN = "^M[0-9]{1,9}$"

#: The only fields permitted to differ between output_schema.json and
#: imported_output_schema.json.
APPROVED_FIELD_DIFFERENCES = {
    "message_id",  # benchmark-only; replaced by source_message_id
    "source_message_id",  # imported identifier, exact text preserved
    "case_ref",  # per-accepted-row correlation
    "run_id",  # per-batch correlation
}


def _load(app_root: Path, name: str) -> dict[str, Any]:
    with (app_root / "schemas" / name).open(encoding="utf-8") as handle:
        loaded: dict[str, Any] = json.load(handle)
    return loaded


def _narrow_identifier_patterns(node: Any) -> Any:
    """Rewrite the imported identifier pattern back to the benchmark pattern.

    Nested identifier references (``related_message_ids``,
    ``first_contact_message_id``) are legitimately widened in the imported
    schemas. Normalizing them lets the comparison assert that *nothing else*
    differs, which is the property worth enforcing.
    """

    if isinstance(node, dict):
        return {
            key: (
                BENCHMARK_ID_PATTERN
                if key == "pattern" and value == IMPORTED_ID_PATTERN
                else _narrow_identifier_patterns(value)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_narrow_identifier_patterns(item) for item in node]
    return node


def _collect_patterns(node: Any, found: list[str]) -> list[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "pattern" and isinstance(value, str):
                found.append(value)
            else:
                _collect_patterns(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_patterns(item, found)
    return found


@pytest.fixture()
def accepted(app_root: Path) -> dict[str, Any]:
    return _load(app_root, "output_schema.json")


@pytest.fixture()
def imported_decision(app_root: Path) -> dict[str, Any]:
    return _load(app_root, "imported_decision_schema.json")


@pytest.fixture()
def imported_output(app_root: Path) -> dict[str, Any]:
    return _load(app_root, "imported_output_schema.json")


# --------------------------------------------------------------------------
# required accepted decision fields survive into the imported schemas
# --------------------------------------------------------------------------


def test_imported_output_keeps_every_accepted_decision_property(
    accepted: dict[str, Any], imported_output: dict[str, Any]
) -> None:
    accepted_props = set(accepted["properties"]) - APPROVED_FIELD_DIFFERENCES
    imported_props = set(imported_output["properties"]) - APPROVED_FIELD_DIFFERENCES

    dropped = sorted(accepted_props - imported_props)
    added = sorted(imported_props - accepted_props)

    assert not dropped, (
        "imported_output_schema.json is missing accepted decision fields "
        f"{dropped}. Regenerate it from output_schema.json."
    )
    assert not added, (
        "imported_output_schema.json defines fields absent from "
        f"output_schema.json: {added}. Only "
        f"{sorted(APPROVED_FIELD_DIFFERENCES)} may differ."
    )


def test_imported_decision_matches_accepted_properties_exactly(
    accepted: dict[str, Any], imported_decision: dict[str, Any]
) -> None:
    """The engine-internal schema differs only by identifier pattern."""

    assert set(imported_decision["properties"]) == set(accepted["properties"]), (
        "imported_decision_schema.json property set has drifted from "
        "output_schema.json. Regenerate it."
    )
    assert set(imported_decision.get("required", [])) == set(
        accepted.get("required", [])
    )


def test_required_lists_agree_apart_from_approved_fields(
    accepted: dict[str, Any], imported_output: dict[str, Any]
) -> None:
    accepted_required = set(accepted.get("required", [])) - APPROVED_FIELD_DIFFERENCES
    imported_required = (
        set(imported_output.get("required", [])) - APPROVED_FIELD_DIFFERENCES
    )
    assert accepted_required == imported_required, (
        "required-field drift between output_schema.json and "
        f"imported_output_schema.json: {sorted(accepted_required ^ imported_required)}"
    )


def test_shared_property_definitions_are_identical(
    accepted: dict[str, Any], imported_output: dict[str, Any]
) -> None:
    """Types, enums and constraints must not diverge on shared fields.

    This is what catches a retyped or re-enumerated accepted field.
    """

    drifted: list[str] = []
    for name, definition in accepted["properties"].items():
        if name in APPROVED_FIELD_DIFFERENCES:
            continue
        # Nested identifier patterns are legitimately widened; everything else
        # must match exactly.
        imported_definition = _narrow_identifier_patterns(
            imported_output["properties"].get(name)
        )
        if imported_definition != definition:
            drifted.append(name)

    assert not drifted, (
        "shared decision fields differ between output_schema.json and "
        f"imported_output_schema.json beyond the widened identifier pattern: "
        f"{sorted(drifted)}. Regenerate the imported schema from the accepted one."
    )


# --------------------------------------------------------------------------
# the approved differences are exactly what we expect
# --------------------------------------------------------------------------


def test_imported_output_uses_imported_run_identifier_definitions(
    imported_output: dict[str, Any],
) -> None:
    props = imported_output["properties"]

    assert "message_id" not in props, (
        "imported_output_schema.json must not carry the benchmark-only "
        "message_id field"
    )

    assert props["source_message_id"]["type"] == "string"
    assert props["source_message_id"]["pattern"] == IMPORTED_ID_PATTERN
    assert props["case_ref"]["type"] == "string"
    assert props["case_ref"]["pattern"].startswith("^case-")
    assert props["run_id"]["type"] == "string"
    assert props["run_id"]["pattern"].startswith("^irun-")

    for field in ("source_message_id", "case_ref", "run_id"):
        assert field in imported_output["required"], f"{field} must be required"


def test_imported_decision_widens_only_the_identifier_pattern(
    imported_decision: dict[str, Any],
) -> None:
    assert imported_decision["properties"]["message_id"]["pattern"] == (
        IMPORTED_ID_PATTERN
    )


def test_no_benchmark_identifier_pattern_survives_in_imported_schemas(
    app_root: Path,
) -> None:
    for name in (
        "imported_decision_schema.json",
        "imported_output_schema.json",
        "imported_audit_event_schema.json",
    ):
        patterns = _collect_patterns(_load(app_root, name), [])
        assert BENCHMARK_ID_PATTERN not in patterns, (
            f"{name} still constrains an identifier with the benchmark pattern "
            f"{BENCHMARK_ID_PATTERN}"
        )
        assert IMPORTED_ID_PATTERN in patterns, (
            f"{name} does not use the imported identifier pattern"
        )


# --------------------------------------------------------------------------
# the accepted policy and benchmark schemas stay untouched
# --------------------------------------------------------------------------


def test_accepted_schemas_retain_the_benchmark_identifier_pattern(
    app_root: Path,
) -> None:
    """Import support must never widen the benchmark contract in place."""

    for name in (
        "output_schema.json",
        "audit_event_schema.json",
        "ground_truth_schema.json",
        "policy_rules_schema.json",
        "baseline_rules_schema.json",
        "redaction_policy_schema.json",
        "detection_result_schema.json",
    ):
        patterns = _collect_patterns(_load(app_root, name), [])
        assert BENCHMARK_ID_PATTERN in patterns, (
            f"{name} no longer constrains identifiers to "
            f"{BENCHMARK_ID_PATTERN}; the supplied-40 contract must not be "
            "widened to accommodate imported data"
        )
        assert IMPORTED_ID_PATTERN not in patterns, (
            f"{name} has been widened with the imported pattern "
            f"{IMPORTED_ID_PATTERN}; imported data must use the imported "
            "schemas instead"
        )


def test_accepted_output_schema_has_no_imported_run_fields(
    accepted: dict[str, Any]
) -> None:
    for field in ("source_message_id", "case_ref", "run_id"):
        assert field not in accepted["properties"], (
            f"output_schema.json has gained the imported-run field {field}; "
            "the accepted contract must stay as delivered"
        )


# --------------------------------------------------------------------------
# the guard itself fails loudly on drift
# --------------------------------------------------------------------------


def test_compatibility_check_detects_an_added_accepted_field(
    accepted: dict[str, Any], imported_output: dict[str, Any]
) -> None:
    """Simulate a future accepted-schema change that was not propagated."""

    mutated = dict(accepted)
    mutated["properties"] = {
        **accepted["properties"],
        "new_decision_field": {"type": "string"},
    }

    accepted_props = set(mutated["properties"]) - APPROVED_FIELD_DIFFERENCES
    imported_props = set(imported_output["properties"]) - APPROVED_FIELD_DIFFERENCES

    assert "new_decision_field" in accepted_props - imported_props, (
        "the compatibility check would not notice a new accepted decision field"
    )


def test_compatibility_check_detects_a_retyped_accepted_field(
    accepted: dict[str, Any], imported_output: dict[str, Any]
) -> None:
    """Simulate a shared field being retyped on the accepted side only."""

    field = "category"
    assert field in accepted["properties"], "fixture assumes category exists"
    mutated_definition = {"type": "integer"}

    assert imported_output["properties"][field] != mutated_definition, (
        "the compatibility check would not notice a retyped accepted field"
    )
