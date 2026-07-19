"""Phase 09 release correction: consistent dataset context across pages.

The Dashboard already supported both the supplied-40 benchmark and completed
imported runs. Human Review remained hardwired to the benchmark, and the
Evaluation page presented agreement metrics without stating that agreement
exists only where there is ground truth.

These tests pin three things:

* Human Review works on an imported run, with corrections scoped to the
  run_id / case_ref / source_message_id triple and kept out of the supplied-40
  trail entirely.
* One shared session key carries the selected dataset between pages, so a run
  opened on the Dashboard survives navigation instead of silently reverting.
* Benchmark Evaluation says what it scores, and imported-run numbers are
  presented as operational diagnostics rather than accuracy.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from player_triage.console_service import (
    FALLBACK_TEAM,
    ConsoleService,
    ConsoleServiceError,
)
from player_triage.ingestion import REQUIRED_COLUMNS
from player_triage.ui.pages import (
    BENCHMARK_EVALUATION_LABEL,
    BENCHMARK_ONLY_NOTICE,
    SELECTED_DATASET_KEY,
    SUPPLIED_40_LABEL,
)

_CHANNELS = ("email", "chat")
_MARKETS = ("Ontario", "Malta", "Ireland", "India", "New Zealand")
_LANGUAGES = ("en", "de", "es")
_TIERS = ("none", "bronze", "silver", "gold")

_SYNTHETIC_PAN = "4111111111111111"
_SYNTHETIC_SUBJECT = "Withdrawal question about my pending payout"


def _row(index: int) -> dict[str, str]:
    return {
        "msg_id": f"M{index}",
        "received_utc": f"2026-03-{(index % 28) + 1:02d}T09:15:00Z",
        "channel": _CHANNELS[index % len(_CHANNELS)],
        "market": _MARKETS[index % len(_MARKETS)],
        "player_id": f"P-{index:05d}",
        "vip_tier": _TIERS[index % len(_TIERS)],
        "language": _LANGUAGES[index % len(_LANGUAGES)],
        "subject": f"{_SYNTHETIC_SUBJECT} (case {index})",
        "body": f"My payout has not arrived. Card {_SYNTHETIC_PAN}. Ref {index:04d}.",
    }


def _csv_bytes(count: int = 12) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(REQUIRED_COLUMNS), lineterminator="\n"
    )
    writer.writeheader()
    for index in range(1, count + 1):
        writer.writerow(_row(index))
    return buffer.getvalue().encode("utf-8")


@pytest.fixture()
def service(app_root: Path, tmp_path: Path) -> ConsoleService:
    return ConsoleService(
        app_root, state_root=tmp_path / "state", output_root=tmp_path / "out"
    )


# ---------------------------------------------------------------------------
# imported review queue
# ---------------------------------------------------------------------------


def test_imported_review_queue_is_empty_for_an_unknown_run(
    service: ConsoleService,
) -> None:
    """An unusable run degrades to an empty queue rather than raising."""

    for run_id in ("irun-20260101T000000000Z-aaaaaaaaaaaa", "../../policy", ""):
        assert service.imported_review_queue(run_id) == ()


def test_imported_review_queue_holds_review_routed_decisions(
    service: ConsoleService,
) -> None:
    run = service.run_import(_csv_bytes(), display_name="batch.csv")

    queue = service.imported_review_queue(run.run_id)
    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    assert queue, "the synthetic batch should route at least one case to review"
    assert len(queue) <= detail.rows_processed
    for item in queue:
        assert item.run_id == run.run_id
        assert item.route in {"human", "specialist"} or item.human_review_required


def test_imported_review_counts_match_the_selected_run(
    service: ConsoleService,
) -> None:
    """Two runs must not bleed into one another's queues."""

    first = service.run_import(_csv_bytes(6), display_name="first.csv")
    second = service.run_import(_csv_bytes(12), display_name="second.csv")

    first_queue = service.imported_review_queue(first.run_id)
    second_queue = service.imported_review_queue(second.run_id)

    assert {item.run_id for item in first_queue} == {first.run_id}
    assert {item.run_id for item in second_queue} == {second.run_id}
    assert len(second_queue) >= len(first_queue)


def test_imported_review_items_carry_the_correction_triple(
    service: ConsoleService,
) -> None:
    run = service.run_import(_csv_bytes(), display_name="batch.csv")

    queue = service.imported_review_queue(run.run_id)

    for item in queue:
        assert item.run_id == run.run_id
        assert item.case_ref.startswith("case-")
        assert item.source_message_id.startswith("M")
        assert item.parent_event_id


def test_imported_review_uses_source_message_ids(service: ConsoleService) -> None:
    """Imported identifiers, not benchmark M01-M40 identifiers."""

    run = service.run_import(_csv_bytes(), display_name="batch.csv")

    ids = {item.source_message_id for item in service.imported_review_queue(run.run_id)}

    assert ids
    assert all(identifier.startswith("M") for identifier in ids)
    # The benchmark's zero-padded two-digit form must not appear here.
    assert not any(len(identifier) == 3 and identifier[1] == "0" for identifier in ids)


def test_imported_review_exposes_no_raw_content(service: ConsoleService) -> None:
    run = service.run_import(_csv_bytes(), display_name="sensitive.csv")

    queue = service.imported_review_queue(run.run_id)
    blob = json.dumps(
        [
            {
                "ids": [item.run_id, item.case_ref, item.source_message_id],
                "decision": dict(item.decision),
            }
            for item in queue
        ]
    )

    for forbidden in (_SYNTHETIC_PAN, _SYNTHETIC_SUBJECT, "P-00001", "body"):
        assert forbidden not in blob, forbidden


# ---------------------------------------------------------------------------
# imported corrections
# ---------------------------------------------------------------------------


def _first_case(service: ConsoleService, run_id: str) -> Any:
    queue = service.imported_review_queue(run_id)
    assert queue, "no imported case available to correct"
    return queue[0]


def test_correction_is_scoped_to_run_case_and_message(
    service: ConsoleService,
) -> None:
    run = service.run_import(_csv_bytes(), display_name="batch.csv")
    item = _first_case(service, run.run_id)

    event_id = service.submit_imported_override(
        run.run_id,
        item.case_ref,
        item.source_message_id,
        {"priority": "high"},
        "PRIORITY_CORRECTION",
        "local-reviewer",
    )

    events = service.imported_audit_events(run.run_id)
    override = next(e for e in events if e.event_id == event_id)

    assert override.event_type == "human_override"
    assert override.run_id == run.run_id
    assert override.message_id == item.source_message_id
    assert override.payload["parent_event_id"] == item.parent_event_id
    assert override.payload["reason_code"] == "PRIORITY_CORRECTION"
    assert override.payload["after"]["decision_basis"] == "human_override"


def test_correction_rejects_a_mismatched_case_ref(service: ConsoleService) -> None:
    """The triple must agree, or the correction targets the wrong case."""

    run = service.run_import(_csv_bytes(), display_name="batch.csv")
    item = _first_case(service, run.run_id)

    with pytest.raises(ConsoleServiceError):
        service.submit_imported_override(
            run.run_id,
            "case-000000000000",
            item.source_message_id,
            {"priority": "high"},
            "PRIORITY_CORRECTION",
            "local-reviewer",
        )


def test_correction_rejects_an_unknown_message(service: ConsoleService) -> None:
    run = service.run_import(_csv_bytes(), display_name="batch.csv")
    item = _first_case(service, run.run_id)

    with pytest.raises(ConsoleServiceError):
        service.submit_imported_override(
            run.run_id,
            item.case_ref,
            "M999999",
            {"priority": "high"},
            "PRIORITY_CORRECTION",
            "local-reviewer",
        )


def test_correction_rejects_an_unsupported_field(service: ConsoleService) -> None:
    run = service.run_import(_csv_bytes(), display_name="batch.csv")
    item = _first_case(service, run.run_id)

    with pytest.raises(ConsoleServiceError):
        service.submit_imported_override(
            run.run_id,
            item.case_ref,
            item.source_message_id,
            {"model_called": True},
            "PRIORITY_CORRECTION",
            "local-reviewer",
        )


def test_correction_rejects_an_unapproved_reason_code(
    service: ConsoleService,
) -> None:
    run = service.run_import(_csv_bytes(), display_name="batch.csv")
    item = _first_case(service, run.run_id)

    with pytest.raises(ConsoleServiceError):
        service.submit_imported_override(
            run.run_id,
            item.case_ref,
            item.source_message_id,
            {"priority": "high"},
            "NOT_AN_APPROVED_CODE",
            "local-reviewer",
        )


def test_correction_does_not_overwrite_the_original_decision(
    service: ConsoleService,
) -> None:
    """The machine decision stays immutable; the correction sits beside it."""

    run = service.run_import(_csv_bytes(), display_name="batch.csv")
    item = _first_case(service, run.run_id)
    before = service.imported_run_detail(run.run_id)
    assert before is not None
    original_row = next(
        row
        for row in before.decisions
        if row["source_message_id"] == item.source_message_id
    )

    service.submit_imported_override(
        run.run_id,
        item.case_ref,
        item.source_message_id,
        {"priority": "high"},
        "PRIORITY_CORRECTION",
        "local-reviewer",
    )

    after = service.imported_run_detail(run.run_id)
    assert after is not None
    unchanged = next(
        row
        for row in after.decisions
        if row["source_message_id"] == item.source_message_id
    )
    assert unchanged == original_row
    assert after.decision_digest == before.decision_digest


def test_imported_corrections_stay_out_of_the_supplied_40_trail(
    service: ConsoleService,
) -> None:
    """The two datasets must not share a correction trail."""

    run = service.run_import(_csv_bytes(), display_name="batch.csv")
    item = _first_case(service, run.run_id)
    event_id = service.submit_imported_override(
        run.run_id,
        item.case_ref,
        item.source_message_id,
        {"priority": "high"},
        "PRIORITY_CORRECTION",
        "local-reviewer",
    )

    benchmark_event_ids = {event.event_id for event in service.audit_events()}

    assert event_id not in benchmark_event_ids
    assert event_id in {e.event_id for e in service.imported_audit_events(run.run_id)}


def test_correction_on_an_unavailable_run_is_refused(
    service: ConsoleService,
) -> None:
    with pytest.raises(ConsoleServiceError):
        service.submit_imported_override(
            "irun-20260101T000000000Z-aaaaaaaaaaaa",
            "case-000000000000",
            "M1",
            {"priority": "high"},
            "PRIORITY_CORRECTION",
            "local-reviewer",
        )


# ---------------------------------------------------------------------------
# imported diagnostics, explicitly not agreement
# ---------------------------------------------------------------------------


def test_diagnostics_report_operational_counts_only(
    service: ConsoleService,
) -> None:
    run = service.run_import(_csv_bytes(), display_name="batch.csv")

    diagnostics = service.imported_run_diagnostics(run.run_id)

    assert diagnostics is not None
    assert diagnostics["rows_processed"] == run.rows_processed
    assert diagnostics["rows_rejected"] == run.rows_rejected
    assert diagnostics["model_calls"] == 0
    assert diagnostics["policy_version"] == "policy-3.3.1"
    assert diagnostics["decision_digest"] == run.decision_digest
    assert sum(diagnostics["category_distribution"].values()) == run.rows_processed
    assert sum(diagnostics["priority_distribution"].values()) == run.rows_processed
    assert sum(diagnostics["route_distribution"].values()) == run.rows_processed
    assert diagnostics["fallback_to_general_count"] == diagnostics[
        "team_distribution"
    ].get(FALLBACK_TEAM, 0)


def test_diagnostics_never_claim_agreement_or_accuracy(
    service: ConsoleService,
) -> None:
    """An imported run has no labels, so no key may imply scoring against them."""

    run = service.run_import(_csv_bytes(), display_name="batch.csv")

    diagnostics = service.imported_run_diagnostics(run.run_id)

    assert diagnostics is not None
    for key in diagnostics:
        lowered = key.lower()
        for forbidden in ("agreement", "accuracy", "expected", "ground_truth", "match"):
            assert forbidden not in lowered, key


def test_diagnostics_for_an_unusable_run_are_none(service: ConsoleService) -> None:
    assert service.imported_run_diagnostics("irun-20260101T000000000Z-aaaaaaaaaaaa") is None


# ---------------------------------------------------------------------------
# the benchmark is untouched
# ---------------------------------------------------------------------------


def test_benchmark_review_queue_is_unaffected_by_imports(
    service: ConsoleService,
) -> None:
    before = [view.message_id for view in service.review_queue()]
    service.run_import(_csv_bytes(), display_name="batch.csv")
    after = [view.message_id for view in service.review_queue()]

    assert before == after


def test_supplied_40_digest_is_unchanged(app_root: Path, tmp_path: Path) -> None:
    from player_triage.config import load_app_config
    from player_triage.evaluation_service import ACCEPTED_CANONICAL_DIGEST
    from player_triage.operational import run_operational_pipeline

    supplied = run_operational_pipeline(
        load_app_config(app_root), output_dir=tmp_path / "supplied"
    )

    assert supplied.canonical_decision_digest == ACCEPTED_CANONICAL_DIGEST
    assert (
        supplied.canonical_decision_digest
        == "a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b"
    )


def test_imported_runs_stay_rules_only_on_policy_3_3_1(
    service: ConsoleService,
) -> None:
    run = service.run_import(_csv_bytes(), display_name="batch.csv")
    item = _first_case(service, run.run_id)
    service.submit_imported_override(
        run.run_id,
        item.case_ref,
        item.source_message_id,
        {"priority": "high"},
        "PRIORITY_CORRECTION",
        "local-reviewer",
    )

    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    assert detail.model_calls == 0
    assert detail.policy_version == "policy-3.3.1"
    assert all(row["model_called"] == "false" for row in detail.decisions)


# ---------------------------------------------------------------------------
# Streamlit pages
# ---------------------------------------------------------------------------


def _workspace(app_root: Path, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("policy", "schemas", "input"):
        shutil.copytree(app_root / name, workspace / name)
    return workspace


def _app(app_root: Path, workspace: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("PLAYER_TRIAGE_APP_ROOT", str(workspace))
    return AppTest.from_file(str(app_root / "src" / "player_triage" / "ui" / "app.py"))


def _visible_text(rendered: AppTest) -> str:
    chunks: list[str] = []
    for name in (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "info",
        "success",
        "warning",
        "error",
    ):
        try:
            group = getattr(rendered, name)
        except (AttributeError, KeyError):
            continue
        for element in group:
            value = getattr(element, "value", None)
            if isinstance(value, str):
                chunks.append(value)
    return "\n".join(chunks)


def _goto(rendered: AppTest, page: str) -> AppTest:
    rendered.sidebar.radio[0].set_value(page)
    return rendered.run(timeout=90)


@pytest.fixture()
def live(app_root: Path, tmp_path: Path) -> tuple[Path, str]:
    """A workspace with one completed imported run in it."""

    workspace = _workspace(app_root, tmp_path)
    service = ConsoleService(
        workspace, state_root=workspace / "state", output_root=workspace / "output"
    )
    run = service.run_import(_csv_bytes(), display_name="live.csv")
    return workspace, run.run_id


def test_human_review_defaults_to_the_supplied_benchmark(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _ = live
    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered = _goto(rendered, "Human Review")

    assert not rendered.exception
    selector = next(box for box in rendered.selectbox if box.label == "Dataset")
    assert selector.value == SUPPLIED_40_LABEL
    assert f"**Dataset:** {SUPPLIED_40_LABEL}" in _visible_text(rendered)


def test_human_review_can_select_a_completed_imported_run(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_id = live
    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered.session_state[SELECTED_DATASET_KEY] = run_id
    rendered = _goto(rendered, "Human Review")

    assert not rendered.exception
    text = _visible_text(rendered)
    assert run_id in text
    assert "live.csv" in text
    selector = next(box for box in rendered.selectbox if box.label == "Dataset")
    assert run_id in selector.value


def test_human_review_shows_imported_source_message_ids(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_id = live
    service = ConsoleService(
        workspace, state_root=workspace / "state", output_root=workspace / "output"
    )
    expected = [item.source_message_id for item in service.imported_review_queue(run_id)]

    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered.session_state[SELECTED_DATASET_KEY] = run_id
    rendered = _goto(rendered, "Human Review")

    assert not rendered.exception
    picker = next(
        box for box in rendered.selectbox if box.label == "Imported message"
    )
    assert list(picker.options) == expected


def test_human_review_counts_match_the_selected_run(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_id = live
    service = ConsoleService(
        workspace, state_root=workspace / "state", output_root=workspace / "output"
    )
    expected = len(service.imported_review_queue(run_id))

    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered.session_state[SELECTED_DATASET_KEY] = run_id
    rendered = _goto(rendered, "Human Review")

    metrics = {metric.label: metric.value for metric in rendered.metric}
    assert metrics["Cases requiring review"] == str(expected)


def test_dashboard_selection_persists_into_human_review(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported inconsistency: the run must not be dropped on navigation."""

    workspace, run_id = live
    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered.session_state[SELECTED_DATASET_KEY] = run_id

    rendered = _goto(rendered, "Dashboard")
    assert rendered.session_state[SELECTED_DATASET_KEY] == run_id

    for page in ("Human Review", "Messages", "Audit Explorer", "Dashboard"):
        rendered = _goto(rendered, page)
        assert not rendered.exception, page
        assert rendered.session_state[SELECTED_DATASET_KEY] == run_id, page
        assert run_id in _visible_text(rendered), page


def test_a_deleted_selected_run_warns_and_falls_back(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_id = live
    shutil.rmtree(workspace / "output" / "imported_runs" / run_id)

    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered.session_state[SELECTED_DATASET_KEY] = run_id
    rendered = _goto(rendered, "Human Review")

    assert not rendered.exception
    text = _visible_text(rendered)
    assert "no longer available" in text
    assert run_id in text
    assert SUPPLIED_40_LABEL in text
    assert rendered.session_state[SELECTED_DATASET_KEY] is None


def test_benchmark_evaluation_states_its_scope(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _ = live
    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered = _goto(rendered, BENCHMARK_EVALUATION_LABEL)

    assert not rendered.exception
    text = _visible_text(rendered)
    assert BENCHMARK_EVALUATION_LABEL in text
    assert BENCHMARK_ONLY_NOTICE in text
    assert "benchmark datasets only" in text


def test_benchmark_evaluation_page_is_named_in_the_navigation(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _ = live
    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)

    assert BENCHMARK_EVALUATION_LABEL in rendered.sidebar.radio[0].options
    assert "Evaluation" not in rendered.sidebar.radio[0].options


def test_imported_diagnostics_are_not_labelled_as_agreement(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_id = live
    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered.session_state[SELECTED_DATASET_KEY] = run_id
    rendered = _goto(rendered, BENCHMARK_EVALUATION_LABEL)

    assert not rendered.exception
    text = _visible_text(rendered)
    assert "Imported Run Diagnostics" in text
    assert "not accuracy, not agreement" in text

    labels = [metric.label for metric in rendered.metric]
    for label in labels:
        assert "agreement" not in label.lower()


def test_every_console_page_renders_with_an_imported_run_selected(
    app_root: Path, live: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_id = live
    rendered = _app(app_root, workspace, monkeypatch).run(timeout=90)
    rendered.session_state[SELECTED_DATASET_KEY] = run_id

    for page in rendered.sidebar.radio[0].options:
        rendered = _goto(rendered, page)
        assert not rendered.exception, page
