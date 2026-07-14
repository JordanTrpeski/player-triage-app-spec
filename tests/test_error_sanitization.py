"""Errors must not echo raw dataset content back to callers.

Phase 01 does not process the message dataset. This test still enforces the
invariant by embedding a synthetic sensitive payload into a policy file (via
a ``change_reason`` string) and asserting that the resulting exception does
not surface that payload to callers or logs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from player_triage.config import load_app_config
from player_triage.errors import ConfigurationError


_SYNTHETIC_SENSITIVE_MARKER = "PLAYER-BODY-4539-1488-secret-do-not-echo"


def test_error_does_not_leak_synthetic_payload(
    mutated_app_root: Callable[[], Path],
) -> None:
    root = mutated_app_root()
    manifest_path = root / "policy" / "configuration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Inject a sensitive-looking string into a field the loader inspects, then
    # break another field so validation fails and we can inspect the error.
    manifest["change_reason"] = _SYNTHETIC_SENSITIVE_MARKER
    manifest["components"]["policy_rules"] = "not-a-sha256"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ConfigurationError) as excinfo:
        load_app_config(root)

    rendered = str(excinfo.value)
    assert _SYNTHETIC_SENSITIVE_MARKER not in rendered
