"""Phase 09 release correction: cross-page import workflow.

The smoke-test defect was a UI-integration one: imported runs were written
correctly beneath ``output/imported_runs`` but were unreachable from the
dashboard, and the import page lost its staged upload whenever the operator
visited another page.

These tests pin the corrected behaviour at two levels:

* the console service, which now exposes imported runs as selectable datasets;
* the Streamlit pages, driven through ``AppTest``.

``st.file_uploader`` cannot be driven by ``AppTest``, which is precisely why the
page mirrors the upload into ordinary session state. Tests seed that state
directly — the same mechanism the fix relies on, so exercising it is exercising
the fix rather than working around it.
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

from player_triage.console_contracts import ImportRunView
from player_triage.console_service import (
    SELECTABLE_IMPORT_STATUSES,
    ConsoleService,
)
from player_triage.ingestion import REQUIRED_COLUMNS
from player_triage.ui.pages import (
    DASHBOARD_DATASET_KEY,
    IMPORT_STATE_KEY,
    SUPPLIED_40_LABEL,
    _blank_import_state,
    _stage_upload,
    dashboard_dataset_options,
)

# The sensitive-looking values below are synthetic: an industry test PAN and an
# obviously fake password. No dataset content appears in this file.
_SYNTHETIC_PAN = "4111111111111111"
_SYNTHETIC_PASSWORD = "hunter2"
_SYNTHETIC_PLAYER = "P-00001"
_SYNTHETIC_SUBJECT = "Withdrawal question about my pending payout request"


def _row(msg_id: str, **over: str) -> dict[str, str]:
    row = {
        "msg_id": msg_id,
        "received_utc": "2026-02-01T10:00:00Z",
        "channel": "email",
        "market": "Ontario",
        "player_id": _SYNTHETIC_PLAYER,
        "vip_tier": "none",
        "language": "en",
        "subject": _SYNTHETIC_SUBJECT,
        "body": f"card {_SYNTHETIC_PAN} and password {_SYNTHETIC_PASSWORD}",
    }
    row.update(over)
    return row


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(REQUIRED_COLUMNS), lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in REQUIRED_COLUMNS})
    return buffer.getvalue().encode("utf-8")


@pytest.fixture()
def service(app_root: Path, tmp_path: Path) -> ConsoleService:
    return ConsoleService(
        app_root, state_root=tmp_path / "state", output_root=tmp_path / "out"
    )


# ---------------------------------------------------------------------------
# service: imported runs as dashboard datasets
# ---------------------------------------------------------------------------


def test_completed_run_is_offered_as_a_dashboard_dataset(
    service: ConsoleService,
) -> None:
    run = service.run_import(_csv_bytes([_row("M1"), _row("M2")]), display_name="a.csv")

    options = dashboard_dataset_options(service)

    assert list(options)[0] == SUPPLIED_40_LABEL, "benchmark stays first"
    assert options[SUPPLIED_40_LABEL] is None
    assert run.run_id in options.values()


def test_dashboard_options_hold_only_the_benchmark_before_any_import(
    service: ConsoleService,
) -> None:
    assert dashboard_dataset_options(service) == {SUPPLIED_40_LABEL: None}


def test_selected_imported_run_reports_the_correct_counts(
    service: ConsoleService,
) -> None:
    payload = _csv_bytes([_row("M1"), _row("M2"), _row("M3")])
    run = service.run_import(payload, display_name="batch.csv")

    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    assert detail.run_id == run.run_id
    assert detail.status == "completed"
    assert detail.source_filename_sanitized == "batch.csv"
    assert detail.rows_seen == 3
    assert detail.rows_accepted == 3
    assert detail.rows_rejected == 0
    assert detail.rows_processed == 3
    assert detail.rows_failed == 0
    assert detail.policy_version == "policy-3.3.1"
    assert detail.model_calls == 0
    assert detail.decision_digest == run.decision_digest
    assert len(detail.decisions) == 3


def test_detail_counts_agree_with_the_run_result_when_rows_are_rejected(
    service: ConsoleService,
) -> None:
    run = service.run_import(
        _csv_bytes([_row("M1"), _row("BAD"), _row("M2")]), display_name="mixed.csv"
    )

    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    assert detail.status == "completed_with_errors"
    assert detail.rows_seen == run.rows_seen
    assert detail.rows_rejected == run.rows_rejected == 1
    assert detail.rows_processed == run.rows_processed == 2
    assert detail.rows_accepted + detail.rows_rejected == detail.rows_seen


def test_detail_distributions_cover_every_published_decision(
    service: ConsoleService,
) -> None:
    run = service.run_import(
        _csv_bytes([_row(f"M{n}") for n in range(1, 6)]), display_name="five.csv"
    )

    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    for field in ("category", "priority", "route", "assigned_team"):
        counts = detail.distributions[field]
        assert counts, f"{field} distribution is empty"
        assert sum(counts.values()) == detail.rows_processed


def test_imported_run_reports_zero_model_calls(service: ConsoleService) -> None:
    run = service.run_import(_csv_bytes([_row("M1")]), display_name="a.csv")

    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    assert detail.model_calls == 0
    assert all(row["model_called"] == "false" for row in detail.decisions)


def test_imported_run_keeps_policy_3_3_1(service: ConsoleService) -> None:
    run = service.run_import(_csv_bytes([_row("M1")]), display_name="a.csv")

    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    assert detail.policy_version == "policy-3.3.1"


# ---------------------------------------------------------------------------
# service: sanitization and fault tolerance
# ---------------------------------------------------------------------------


def test_dashboard_detail_exposes_no_raw_content_or_identifiers(
    service: ConsoleService,
) -> None:
    """Nothing derived from subject, body or player_id may reach the dashboard."""

    run = service.run_import(_csv_bytes([_row("M1")]), display_name="sensitive.csv")

    detail = service.imported_run_detail(run.run_id)
    assert detail is not None
    blob = json.dumps(
        {
            "meta": [
                detail.run_id,
                detail.status,
                detail.source_filename_sanitized,
                detail.started_at,
                detail.completed_at,
                detail.policy_version,
                detail.decision_digest,
            ],
            "distributions": {k: dict(v) for k, v in detail.distributions.items()},
            "decisions": [dict(row) for row in detail.decisions],
        }
    )

    for forbidden in (
        _SYNTHETIC_PAN,
        _SYNTHETIC_PASSWORD,
        _SYNTHETIC_PLAYER,
        _SYNTHETIC_SUBJECT,
        "subject",
        "body",
        "player_id",
    ):
        assert forbidden not in blob, forbidden


def test_dashboard_detail_exposes_no_filesystem_path(
    service: ConsoleService, tmp_path: Path
) -> None:
    run = service.run_import(_csv_bytes([_row("M1")]), display_name="a.csv")

    detail = service.imported_run_detail(run.run_id)

    assert detail is not None
    assert not hasattr(detail, "run_dir")
    assert str(tmp_path) not in json.dumps(
        [detail.run_id, detail.source_filename_sanitized]
    )


def test_corrupt_manifest_is_skipped_rather_than_raising(
    service: ConsoleService, tmp_path: Path
) -> None:
    good = service.run_import(_csv_bytes([_row("M1")]), display_name="good.csv")
    broken = "irun-20260101T000000000Z-aaaaaaaaaaaa"
    broken_dir = tmp_path / "out" / "imported_runs" / broken
    broken_dir.mkdir(parents=True)
    (broken_dir / "run_manifest.json").write_text("{ not json", encoding="utf-8")

    options = dashboard_dataset_options(service)

    assert good.run_id in options.values()
    assert broken not in options.values()
    assert service.imported_run_detail(broken) is None


def test_incomplete_manifest_is_skipped_rather_than_raising(
    service: ConsoleService, tmp_path: Path
) -> None:
    """A manifest missing its counts must not break the dashboard."""

    partial = "irun-20260101T000000001Z-bbbbbbbbbbbb"
    partial_dir = tmp_path / "out" / "imported_runs" / partial
    partial_dir.mkdir(parents=True)
    (partial_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": partial, "status": "started"}), encoding="utf-8"
    )

    assert service.imported_run_detail(partial) is None
    assert dashboard_dataset_options(service) == {SUPPLIED_40_LABEL: None}
    assert service.recent_imported_runs()[0].rows_seen == 0


def test_manifest_with_unusable_count_types_degrades_to_zero(
    service: ConsoleService, tmp_path: Path
) -> None:
    run_id = "irun-20260101T000000002Z-cccccccccccc"
    run_dir = tmp_path / "out" / "imported_runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "completed",
                "rows_seen": "not-a-number",
                "rows_processed": None,
                "policy_version": "policy-3.3.1",
            }
        ),
        encoding="utf-8",
    )

    detail = service.imported_run_detail(run_id)

    assert detail is not None
    assert detail.rows_seen == 0
    assert detail.rows_processed == 0


def test_unfinished_and_failed_runs_are_not_selectable(
    service: ConsoleService, tmp_path: Path
) -> None:
    for index, status in enumerate(("started", "failed")):
        run_id = f"irun-2026010{index}T000000000Z-dddddddddddd"
        run_dir = tmp_path / "out" / "imported_runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run_manifest.json").write_text(
            json.dumps({"run_id": run_id, "status": status}), encoding="utf-8"
        )
        assert service.imported_run_detail(run_id) is None

    assert dashboard_dataset_options(service) == {SUPPLIED_40_LABEL: None}
    assert service.selectable_imported_runs() == ()


def test_crafted_run_id_cannot_escape_the_imported_run_root(
    service: ConsoleService,
) -> None:
    for crafted in ("../../policy", "irun-x/../..", "", "irun-bad"):
        assert service.imported_run_detail(crafted) is None


def test_recent_runs_refresh_after_each_completion(service: ConsoleService) -> None:
    """No caching may hide a new run until the application restarts."""

    assert service.recent_imported_runs() == ()

    first = service.run_import(_csv_bytes([_row("M1")]), display_name="one.csv")
    assert [run.run_id for run in service.recent_imported_runs()] == [first.run_id]

    second = service.run_import(_csv_bytes([_row("M2")]), display_name="two.csv")
    assert [run.run_id for run in service.recent_imported_runs()] == [
        second.run_id,
        first.run_id,
    ]
    assert second.run_id in dashboard_dataset_options(service).values()


# ---------------------------------------------------------------------------
# import page state, independent of Streamlit's widget lifetime
# ---------------------------------------------------------------------------


def test_staging_records_the_upload_for_later_reruns() -> None:
    state = _blank_import_state()
    payload = _csv_bytes([_row("M1")])

    _stage_upload(state, "batch.csv", payload)

    assert state["filename"] == "batch.csv"
    assert state["payload"] == payload
    assert state["source_digest"]


def test_restaging_the_same_upload_does_not_discard_the_preview() -> None:
    state = _blank_import_state()
    payload = _csv_bytes([_row("M1")])
    _stage_upload(state, "batch.csv", payload)
    state["preview"] = "sentinel"

    _stage_upload(state, "batch.csv", payload)

    assert state["preview"] == "sentinel", "an unchanged rerun must not reset state"


def test_staging_a_different_file_replaces_the_previous_one() -> None:
    state = _blank_import_state()
    _stage_upload(state, "one.csv", _csv_bytes([_row("M1")]))
    first_digest = state["source_digest"]
    state["preview"] = "sentinel"

    _stage_upload(state, "two.csv", _csv_bytes([_row("M2")]))

    assert state["filename"] == "two.csv"
    assert state["source_digest"] != first_digest
    assert state["preview"] is None


def test_a_processed_batch_is_never_restaged(service: ConsoleService) -> None:
    """The duplicate-run guard: one upload yields at most one run.

    The uploader still reports the file on every rerun after processing, so
    without this guard a rerun would re-offer the batch and a second click
    would publish a duplicate run.
    """

    state = _blank_import_state()
    payload = _csv_bytes([_row("M1")])
    _stage_upload(state, "batch.csv", payload)

    result = service.run_import(payload, display_name="batch.csv")
    state.update(
        result=result,
        completed_run_id=result.run_id,
        completed_digest=state["source_digest"],
        payload=None,
    )

    _stage_upload(state, "batch.csv", payload)

    assert state["payload"] is None, "a completed batch must not be re-staged"
    assert state["completed_run_id"] == result.run_id
    assert len(service.recent_imported_runs()) == 1


def test_completion_clears_the_uploaded_bytes_but_keeps_the_run_id() -> None:
    state = _blank_import_state()
    _stage_upload(state, "batch.csv", _csv_bytes([_row("M1")]))
    state.update(
        completed_run_id="irun-20260101T000000000Z-aaaaaaaaaaaa",
        completed_digest=state["source_digest"],
        payload=None,
    )

    assert state["payload"] is None
    assert state["completed_run_id"]


def test_blank_state_carries_a_fresh_widget_nonce() -> None:
    assert _blank_import_state(3)["nonce"] == 3
    assert _blank_import_state()["payload"] is None


# ---------------------------------------------------------------------------
# Streamlit pages
# ---------------------------------------------------------------------------


def _app(app_root: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("PLAYER_TRIAGE_APP_ROOT", str(app_root))
    application = app_root / "src" / "player_triage" / "ui" / "app.py"
    return AppTest.from_file(str(application))


def _visible_text(rendered: AppTest) -> str:
    """Every string the page rendered, across the element types used here."""

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


def _staged_state(payload: bytes, name: str = "smoke.csv") -> dict[str, Any]:
    state = _blank_import_state()
    _stage_upload(state, name, payload)
    return state


def test_dashboard_labels_the_existing_view_as_the_supplied_40_benchmark(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = _goto(_app(app_root, monkeypatch).run(timeout=90), "Dashboard")

    assert not rendered.exception
    assert SUPPLIED_40_LABEL in _visible_text(rendered)

    selector = next(
        box for box in rendered.selectbox if box.label == "Dataset"
    )
    assert SUPPLIED_40_LABEL in selector.options
    assert selector.value == SUPPLIED_40_LABEL, "benchmark is the default dataset"


def test_dashboard_does_not_present_the_benchmark_as_the_latest_import(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = _goto(_app(app_root, monkeypatch).run(timeout=90), "Dashboard")

    text = _visible_text(rendered)
    assert "not the latest imported dataset" in text
    assert "fixed accepted regression baseline" in text


def test_import_page_keeps_the_staged_file_across_navigation(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported defect: leaving the page must not clear the upload."""

    payload = _csv_bytes([_row("M1"), _row("M2")])
    rendered = _app(app_root, monkeypatch).run(timeout=90)
    rendered.session_state[IMPORT_STATE_KEY] = _staged_state(payload)

    rendered = _goto(rendered, "Import")
    assert not rendered.exception
    assert "Preview" in _visible_text(rendered)

    rendered = _goto(rendered, "Dashboard")
    assert not rendered.exception

    rendered = _goto(rendered, "Import")
    assert not rendered.exception

    state = rendered.session_state[IMPORT_STATE_KEY]
    assert state["payload"] == payload, "the staged upload survived navigation"
    assert state["filename"] == "smoke.csv"
    assert state["preview"] is not None
    assert "Preview" in _visible_text(rendered)


def test_import_page_keeps_the_collision_setting_across_navigation(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = _app(app_root, monkeypatch).run(timeout=90)
    state = _staged_state(_csv_bytes([_row("M1")]))
    state["allow_padded"] = True
    rendered.session_state[IMPORT_STATE_KEY] = state

    rendered = _goto(rendered, "Import")
    rendered = _goto(rendered, "Dashboard")
    rendered = _goto(rendered, "Import")

    assert rendered.session_state[IMPORT_STATE_KEY]["allow_padded"] is True


def test_completed_run_id_survives_page_navigation(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "irun-20260101T000000000Z-aaaaaaaaaaaa"
    state = _blank_import_state()
    state.update(
        completed_run_id=run_id,
        completed_digest="d" * 64,
        result=ImportRunView(
            run_id=run_id,
            status="completed",
            policy_version="policy-3.3.1",
            rows_seen=2,
            rows_accepted=2,
            rows_rejected=0,
            rows_processed=2,
            rows_failed=0,
            decision_digest="a" * 64,
            model_calls=0,
            rejected_rows=(),
        ),
    )
    rendered = _app(app_root, monkeypatch).run(timeout=90)
    rendered.session_state[IMPORT_STATE_KEY] = state

    rendered = _goto(rendered, "Import")
    assert run_id in _visible_text(rendered)

    rendered = _goto(rendered, "Messages")
    rendered = _goto(rendered, "Import")

    assert not rendered.exception
    assert rendered.session_state[IMPORT_STATE_KEY]["completed_run_id"] == run_id
    assert run_id in _visible_text(rendered), "returning shows the completed run"


def test_a_completed_import_offers_no_process_button(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeating the processing action must not be possible after completion."""

    state = _blank_import_state()
    state.update(
        completed_run_id="irun-20260101T000000000Z-aaaaaaaaaaaa",
        completed_digest="d" * 64,
        result=ImportRunView(
            run_id="irun-20260101T000000000Z-aaaaaaaaaaaa",
            status="completed",
            policy_version="policy-3.3.1",
            rows_seen=1,
            rows_accepted=1,
            rows_rejected=0,
            rows_processed=1,
            rows_failed=0,
            decision_digest="a" * 64,
            model_calls=0,
            rejected_rows=(),
        ),
    )
    rendered = _app(app_root, monkeypatch).run(timeout=90)
    rendered.session_state[IMPORT_STATE_KEY] = state
    rendered = _goto(rendered, "Import")

    labels = [button.label for button in rendered.button]
    assert "Process batch" not in labels
    assert "Reset import" in labels
    assert "Open run on Dashboard" in labels


def test_reset_import_clears_the_staged_upload(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = _app(app_root, monkeypatch).run(timeout=90)
    rendered.session_state[IMPORT_STATE_KEY] = _staged_state(
        _csv_bytes([_row("M1")])
    )
    rendered = _goto(rendered, "Import")
    assert rendered.session_state[IMPORT_STATE_KEY]["payload"] is not None

    reset = next(
        button for button in rendered.button if button.label == "Reset import"
    )
    reset.click()
    rendered.run(timeout=90)

    state = rendered.session_state[IMPORT_STATE_KEY]
    assert state["payload"] is None
    assert state["preview"] is None
    assert state["result"] is None
    assert state["nonce"] == 1, "a fresh uploader widget is built"
    assert not rendered.exception


def test_opening_a_run_moves_to_the_dashboard_with_it_selected(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The completion action must land on the dashboard showing that run."""

    run_id = "irun-20260101T000000000Z-aaaaaaaaaaaa"
    state = _blank_import_state()
    state.update(
        completed_run_id=run_id,
        completed_digest="d" * 64,
        result=ImportRunView(
            run_id=run_id,
            status="completed",
            policy_version="policy-3.3.1",
            rows_seen=1,
            rows_accepted=1,
            rows_rejected=0,
            rows_processed=1,
            rows_failed=0,
            decision_digest="a" * 64,
            model_calls=0,
            rejected_rows=(),
        ),
    )
    rendered = _app(app_root, monkeypatch).run(timeout=90)
    rendered.session_state[IMPORT_STATE_KEY] = state
    rendered = _goto(rendered, "Import")

    open_button = next(
        button
        for button in rendered.button
        if button.label == "Open run on Dashboard"
    )
    open_button.click()
    rendered.run(timeout=90)

    assert not rendered.exception
    assert rendered.session_state["navigation"] == "Dashboard"
    # This fabricated run does not exist on disk, so the dashboard must say so
    # and fall back to the benchmark rather than raise or silently substitute
    # different data.
    text = _visible_text(rendered)
    assert "no longer available" in text
    assert run_id in text
    assert SUPPLIED_40_LABEL in text


def _workspace(app_root: Path, tmp_path: Path) -> Path:
    """A self-contained app root so the console can run over temporary data."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("policy", "schemas", "input"):
        shutil.copytree(app_root / name, workspace / name)
    return workspace


def test_selected_imported_run_is_displayed_on_the_dashboard(
    app_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: an imported run reaches the dashboard with its own counts.

    This is the reported defect stated positively — the dashboard previously
    showed only the supplied 40 no matter what had been imported.
    """

    workspace = _workspace(app_root, tmp_path)
    service = ConsoleService(
        workspace,
        state_root=workspace / "state",
        output_root=workspace / "output",
    )
    run = service.run_import(
        _csv_bytes([_row(f"M{n}") for n in range(1, 8)]), display_name="live.csv"
    )
    assert run.rows_processed == 7

    monkeypatch.setenv("PLAYER_TRIAGE_APP_ROOT", str(workspace))
    application = app_root / "src" / "player_triage" / "ui" / "app.py"
    rendered = AppTest.from_file(str(application)).run(timeout=90)
    rendered.session_state[DASHBOARD_DATASET_KEY] = run.run_id
    rendered = _goto(rendered, "Dashboard")

    assert not rendered.exception
    text = _visible_text(rendered)
    assert run.run_id in text

    metrics = {metric.label: metric.value for metric in rendered.metric}
    assert metrics["Source file"] == "live.csv"
    assert metrics["Rows seen"] == "7"
    assert metrics["Processed"] == "7"
    assert metrics["Rejected"] == "0"
    assert metrics["Model calls"] == "0"
    assert metrics["Policy"] == "policy-3.3.1"

    # The benchmark remains reachable alongside it.
    selector = next(box for box in rendered.selectbox if box.label == "Dataset")
    assert SUPPLIED_40_LABEL in selector.options
    assert len(selector.options) == 2

    # No raw content reached the page.
    for forbidden in (_SYNTHETIC_PAN, _SYNTHETIC_PASSWORD, _SYNTHETIC_PLAYER):
        assert forbidden not in text


def test_benchmark_remains_selectable_after_an_import(
    app_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing must never displace or alter the accepted benchmark view."""

    workspace = _workspace(app_root, tmp_path)
    service = ConsoleService(
        workspace,
        state_root=workspace / "state",
        output_root=workspace / "output",
    )
    service.run_import(_csv_bytes([_row("M1")]), display_name="live.csv")

    monkeypatch.setenv("PLAYER_TRIAGE_APP_ROOT", str(workspace))
    application = app_root / "src" / "player_triage" / "ui" / "app.py"
    rendered = AppTest.from_file(str(application)).run(timeout=90)
    rendered = _goto(rendered, "Dashboard")

    assert not rendered.exception
    selector = next(box for box in rendered.selectbox if box.label == "Dataset")
    assert selector.value == SUPPLIED_40_LABEL, "benchmark is still the default"
    assert SUPPLIED_40_LABEL in _visible_text(rendered)


def test_every_console_page_still_renders(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = _app(app_root, monkeypatch).run(timeout=90)
    for page in rendered.sidebar.radio[0].options:
        rendered = _goto(rendered, page)
        assert not rendered.exception, page


def test_selectable_statuses_are_the_documented_pair() -> None:
    assert SELECTABLE_IMPORT_STATUSES == ("completed", "completed_with_errors")
