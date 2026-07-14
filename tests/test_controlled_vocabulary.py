"""Controlled-vocabulary duplicates or missing cross-references must fail closed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from player_triage.config import load_app_config
from player_triage.errors import ControlledVocabularyError


def _rewrite(root: Path, filename: str, document: object) -> None:
    (root / "policy" / filename).write_text(json.dumps(document), encoding="utf-8")


def test_duplicate_intent_in_vocab(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    vocab_path = root / "policy" / "controlled_vocabularies.json"
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    vocab["intents"].append(vocab["intents"][0])
    _rewrite(root, "controlled_vocabularies.json", vocab)

    with pytest.raises(ControlledVocabularyError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "controlled_vocabularies"
    assert "duplicate entry" in str(excinfo.value)


def test_vocab_missing_template_id_referenced_by_templates(
    mutated_app_root: Callable[[], Path],
) -> None:
    """Cross-check fires when the controlled vocabulary omits an ID that a template uses.

    The schemas embed the vocabulary as ``enum`` constraints, so the reverse
    direction (template file listing an unknown ID) fails schema validation
    first. This test targets the case the cross-check is specifically here to
    catch: the vocabulary and a component drift apart in favour of the
    component.
    """

    root = mutated_app_root()
    templates = json.loads((root / "policy" / "auto_response_templates.json").read_text(encoding="utf-8"))
    vocab_path = root / "policy" / "controlled_vocabularies.json"
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    dropped = templates["templates"][0]["id"]
    vocab["auto_response_template_ids"] = [v for v in vocab["auto_response_template_ids"] if v != dropped]
    _rewrite(root, "controlled_vocabularies.json", vocab)

    with pytest.raises(ControlledVocabularyError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "auto_response_templates"
    assert dropped in str(excinfo.value)


def test_vocab_missing_reason_code_used_by_rationale_templates(
    mutated_app_root: Callable[[], Path],
) -> None:
    """Same intent as the previous test but for rationale-template reason codes."""

    root = mutated_app_root()
    rationale = json.loads((root / "policy" / "rationale_templates.json").read_text(encoding="utf-8"))
    dropped = next(iter(rationale["templates"].keys()))
    vocab_path = root / "policy" / "controlled_vocabularies.json"
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    vocab["reason_codes"] = [v for v in vocab["reason_codes"] if v != dropped]
    _rewrite(root, "controlled_vocabularies.json", vocab)

    with pytest.raises(ControlledVocabularyError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "rationale_templates"
    assert dropped in str(excinfo.value)
