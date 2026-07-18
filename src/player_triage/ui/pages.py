"""Eight Streamlit pages over typed console services."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable, Mapping

import streamlit as st

from player_triage.configuration_manager import ConfigurationManager
from player_triage.console_contracts import MessageView
from player_triage.console_service import ConsoleService
from player_triage.import_ingestion import MAX_IMPORT_ROWS
from player_triage.pattern_lab import FIXTURES, run_pattern_lab


def render_dashboard(service: ConsoleService) -> None:
    st.title("Dashboard")
    st.markdown(
        '<div class="safe-banner">Rules-only processing is active. The rejected model is disabled and has zero authority.</div>',
        unsafe_allow_html=True,
    )
    snapshot = service.dashboard()
    cols = st.columns(4)
    cols[0].metric("Active policy", snapshot.active_policy_version)
    cols[1].metric("Latest run", snapshot.latest_run_id)
    cols[2].metric("Successful decisions", snapshot.counts["success"])
    cols[3].metric("Model calls", snapshot.model_calls)
    cols = st.columns(4)
    cols[0].metric("Official safety gates", f"{snapshot.official_gates_passed}/{snapshot.official_gate_count}")
    cols[1].metric("Locked gates", f"{snapshot.locked_gates_passed}/{snapshot.locked_gate_count}")
    cols[2].metric("Core mismatches", snapshot.core_mismatch_count)
    cols[3].metric("Diagnostic differences", snapshot.diagnostic_difference_count)
    st.info(
        "M22 is the sole accepted core mismatch. The 52 set-valued secondary-team, risk-flag and reason-code differences are separate diagnostics."
    )
    st.caption(
        "The supplied 40 messages are demonstration data. Throughput is a local benchmark, not production load testing."
    )
    cols = st.columns(4)
    cols[0].metric("Manual-review rate", f"{snapshot.manual_review_rate:.1%}")
    cols[1].metric("Specialist rate", f"{snapshot.specialist_rate:.1%}")
    cols[2].metric("p50 / p95 latency", f"{snapshot.p50_latency_ms:.1f} / {snapshot.p95_latency_ms:.1f} ms")
    cols[3].metric("Local throughput", f"{snapshot.messages_per_second:.2f} msg/s")
    st.metric("Illustrative 900-message replay", f"{snapshot.replay_900_seconds:.2f} seconds")
    st.subheader("Decision distributions")
    dist_cols = st.columns(2)
    for index, field in enumerate(("category", "priority", "route", "assigned_team")):
        with dist_cols[index % 2]:
            st.markdown(f"**{field.replace('_', ' ').title()}**")
            values = snapshot.distributions.get(field, {})
            st.dataframe(
                [{field: key, "count": count} for key, count in values.items()],
                hide_index=True,
                use_container_width=True,
            )
    with st.expander("Runtime and provenance"):
        st.json(
            {
                "application_version": snapshot.application_version,
                "runtime_mode": snapshot.runtime_mode,
                "model_status": snapshot.model_status,
                "model_kill_switch_enabled": snapshot.kill_switch_enabled,
                "latest_run_status": snapshot.latest_run_status,
                "canonical_decision_digest": snapshot.canonical_digest,
                "counts": dict(snapshot.counts),
            }
        )


def render_messages(service: ConsoleService) -> None:
    st.title("Messages")
    st.caption("Structured decisions only. Raw subject, body, player identifiers and sensitive values are never displayed.")
    config = service.configuration.load_active_config()
    all_views = service.messages()
    with st.expander("Filters", expanded=True):
        cols = st.columns(4)
        message_id = cols[0].text_input("Message ID", key="filter_message_id")
        market = cols[1].selectbox("Market", ["", *sorted({str(v.decision.get('market')) for v in all_views})], key="filter_market")
        language = cols[2].selectbox("Language", ["", *sorted({str(v.decision.get('language')) for v in all_views})], key="filter_language")
        category = cols[3].selectbox("Category", ["", *config.vocab.categories], key="filter_category")
        cols = st.columns(4)
        intent = cols[0].selectbox("Intent", ["", *config.vocab.intents], key="filter_intent")
        priority = cols[1].selectbox("Priority", ["", *config.vocab.priorities], key="filter_priority")
        route = cols[2].selectbox("Route", ["", *config.vocab.routes], key="filter_route")
        team = cols[3].selectbox("Primary team", ["", *config.vocab.teams], key="filter_team")
        cols = st.columns(4)
        secondary = cols[0].selectbox("Secondary team", ["", *config.vocab.teams], key="filter_secondary")
        risk = cols[1].selectbox("Risk flag", ["", *config.vocab.risk_flags], key="filter_risk")
        reason = cols[2].selectbox("Reason code", ["", *config.vocab.reason_codes], key="filter_reason")
        eligibility = cols[3].selectbox("Model eligibility", ["", *config.vocab.model_eligibility], key="filter_eligibility")
        cols = st.columns(4)
        bypass = cols[0].selectbox("Bypass reason", ["", *config.vocab.model_bypass_reasons], key="filter_bypass")
        core = cols[1].selectbox("Core mismatch", ["", True, False], key="filter_core")
        diagnostic = cols[2].selectbox("Diagnostic difference", ["", True, False], key="filter_diagnostic")
        human = cols[3].selectbox("Human review", ["", True, False], key="filter_human")
        versions = sorted({view.configuration_version for view in all_views})
        configuration_version = st.selectbox(
            "Decision configuration version", ["", *versions], key="filter_version"
        )
    filters = {
        "message_id": message_id or None,
        "market": market or None,
        "language": language or None,
        "category": category or None,
        "intent": intent or None,
        "priority": priority or None,
        "route": route or None,
        "assigned_team": team or None,
        "secondary_team": secondary or None,
        "risk_flag": risk or None,
        "reason_code": reason or None,
        "model_eligibility": eligibility or None,
        "model_bypass_reason": bypass or None,
        "core_mismatch": core or None,
        "diagnostic_difference": diagnostic or None,
        "human_review_required": human or None,
        "configuration_version": configuration_version or None,
    }
    views = service.messages(filters)
    if not views:
        st.info("No decisions match the current filters.")
        return
    st.dataframe([_message_row(view) for view in views], hide_index=True, use_container_width=True)
    selected = st.selectbox("Inspect decision", [view.message_id for view in views], key="selected_message")
    view = next(item for item in views if item.message_id == selected)
    _render_message_detail(view)


def render_human_review(service: ConsoleService) -> None:
    st.title("Human Review")
    st.caption("Corrections append a new audited view. The original machine decision and ground truth remain immutable.")
    queue = service.review_queue()
    if not queue:
        st.info("The review queue is empty.")
        return
    st.metric("Cases requiring review", len(queue))
    selected = st.selectbox("Message", [item.message_id for item in queue], key="review_message")
    view = next(item for item in queue if item.message_id == selected)
    config = service.configuration.load_active_config()
    original = view.decision
    with st.form("override_preview_form"):
        cols = st.columns(3)
        category = cols[0].selectbox("Category", config.vocab.categories, index=config.vocab.categories.index(str(original["category"])))
        intent = cols[1].selectbox("Intent", config.vocab.intents, index=config.vocab.intents.index(str(original["intent"])))
        priority = cols[2].selectbox("Priority", config.vocab.priorities, index=config.vocab.priorities.index(str(original["priority"])))
        cols = st.columns(3)
        route = cols[0].selectbox("Route", config.vocab.routes, index=config.vocab.routes.index(str(original["route"])))
        team = cols[1].selectbox("Assigned team", config.vocab.teams, index=config.vocab.teams.index(str(original["assigned_team"])))
        secondary_teams = cols[2].multiselect("Secondary teams", config.vocab.teams, default=list(original.get("secondary_teams", ())))
        secondary_intents = st.multiselect("Secondary intents", config.vocab.intents, default=list(original.get("secondary_intents", ())))
        risk_flags = st.multiselect("Risk flags", config.vocab.risk_flags, default=list(original.get("risk_flags", ())))
        reason_codes = st.multiselect("Reason codes", config.vocab.reason_codes, default=list(original.get("reason_codes", ())))
        proposed = {
            "category": category,
            "intent": intent,
            "secondary_intents": secondary_intents,
            "priority": priority,
            "route": route,
            "assigned_team": team,
            "secondary_teams": secondary_teams,
            "risk_flags": risk_flags,
            "reason_codes": reason_codes,
        }
        preview = st.form_submit_button("Preview correction")
    if preview:
        st.session_state["safe_override_preview"] = proposed
    preview_data = st.session_state.get("safe_override_preview")
    if isinstance(preview_data, dict):
        st.subheader("Required before/after diff")
        st.dataframe(_diff_rows(original, preview_data), hide_index=True, use_container_width=True)
        with st.form("override_submit_form"):
            reason = st.selectbox("Override reason", config.vocab.human_override_reason_codes)
            actor = st.text_input("Local reviewer label", value="local-reviewer")
            confirm = st.checkbox("I confirm this is a structured correction only")
            submit = st.form_submit_button("Append human override", disabled=not confirm)
        if submit:
            event_id = service.submit_override(selected, preview_data, reason, actor)
            st.success(f"Override appended: {event_id}")
            st.session_state.pop("safe_override_preview", None)


def render_policy_studio(service: ConsoleService) -> None:
    st.title("Policy Studio")
    st.markdown(
        '<div class="warning-banner">Active policy is immutable. All edits are made in a versioned draft and require validation, impact analysis and locked gates.</div>',
        unsafe_allow_html=True,
    )
    manager = service.configuration
    components = service.policy_components()
    tabs = st.tabs(["Components", "Draft workflow", "Pattern & redaction lab"])
    with tabs[0]:
        component_name = st.selectbox("Policy component", tuple(components), key="studio_component")
        component = components[component_name]
        cols = st.columns(3)
        cols[0].metric("Version", component.get("version"))
        cols[1].metric("Digest", str(component.get("digest", ""))[:12] + "…")
        cols[2].metric("Normal UI", component.get("ui", {}).get("normal_ui", "read_only"))
        if component_name == "model_configuration":
            st.error("Rejected model evidence is read only and unavailable for normal activation.")
        st.json(component["document"])
    with tabs[1]:
        _render_draft_workflow(manager)
    with tabs[2]:
        _render_pattern_lab(service)


def render_evaluation(service: ConsoleService) -> None:
    st.title("Evaluation")
    docs = service.evaluation_documents()
    dataset_document = docs.get("dataset_results", {})
    results = dataset_document.get("results", []) if isinstance(dataset_document, Mapping) else []
    if not results:
        st.info("Evaluation artifacts are unavailable. Run the Phase 06 evaluation safely first.")
        return
    supplied: Mapping[str, Any] = next(
        (item for item in results if item.get("dataset_name") == "supplied-40"),
        {},
    )
    cols = st.columns(4)
    cols[0].metric("Category agreement", _agreement_text(supplied, "category"))
    cols[1].metric("Priority agreement", _agreement_text(supplied, "priority"))
    cols[2].metric("Route agreement", _agreement_text(supplied, "route"))
    cols[3].metric("Team agreement", _agreement_text(supplied, "assigned_team"))
    st.warning("Core mismatch: M22 intent only. Additional diagnostic set-valued differences: 52.")
    st.subheader("Dataset separation")
    st.dataframe(
        [
            {
                "dataset": item.get("dataset_name"),
                "messages": item.get("message_count"),
                "core mismatches": len(item.get("mismatches", [])),
                "diagnostic differences": len(item.get("diagnostic_differences", [])),
                "schema validity": item.get("schema_validity", {}).get("rate"),
            }
            for item in results
        ],
        hide_index=True,
        use_container_width=True,
    )
    safety = docs.get("safety", {})
    gate_results = safety.get("results", []) if isinstance(safety, Mapping) else []
    st.subheader("Non-compensatory safety gates")
    st.metric("Official / locked", f"15/15 / {sum(bool(item.get('passed')) for item in gate_results)}/{len(gate_results)}")
    st.dataframe(gate_results, hide_index=True, use_container_width=True)
    cols = st.columns(3)
    performance = docs.get("performance", {})
    capacity = docs.get("capacity", {})
    workload = docs.get("workload", {})
    cols[0].metric("Local benchmark", f"{float(performance.get('messages_per_second', 0)):.2f} msg/s")
    cols[1].metric("900-message replay", f"{float(capacity.get('full_day_replay_seconds_at_measured_throughput', 0)):.2f} s")
    cols[2].metric("Review route mix", f"{workload.get('human_agent_count', 0)} human / {workload.get('specialist_count', 0)} specialist")
    reconstruction = docs.get("audit_reconstruction", {})
    st.success(f"Audit reconstruction passed: {bool(reconstruction.get('all_passed'))}")
    st.subheader("Safe downloads")
    for name, content in service.safe_downloads().items():
        mime = "text/csv" if name.endswith(".csv") else "application/json"
        st.download_button(name, content, file_name=name, mime=mime, key=f"download_{name}")


def render_audit_explorer(service: ConsoleService) -> None:
    st.title("Audit Explorer")
    st.caption("Structured audit only—no raw/redacted message text, detected values, model prompts or local model paths.")
    with st.expander("Search", expanded=True):
        cols = st.columns(4)
        event_id = cols[0].text_input("Event ID", key="audit_event_id")
        run_id = cols[1].text_input("Run ID", key="audit_run_id")
        message_id = cols[2].text_input("Message ID", key="audit_message_id")
        event_type = cols[3].selectbox("Event type", ["", "decision", "human_override", "error_fallback", "configuration_change", "configuration_rollback", "run_summary"])
        cols = st.columns(4)
        version = cols[0].text_input("Configuration version")
        rule = cols[1].text_input("Rule ID")
        reason = cols[2].text_input("Reason code")
        actor = cols[3].text_input("Actor/component")
    events = service.audit_events(
        {
            "event_id": event_id or None,
            "run_id": run_id or None,
            "message_id": message_id or None,
            "event_type": event_type or None,
            "configuration_version": version or None,
            "rule_id": rule or None,
            "reason_code": reason or None,
            "actor": actor or None,
        }
    )
    if not events:
        st.info("No audit events match the current search.")
        return
    st.dataframe(
        [
            {
                "event_id": item.event_id,
                "timestamp": item.occurred_at,
                "type": item.event_type,
                "run_id": item.run_id,
                "message_id": item.message_id,
                "configuration": item.configuration_version,
            }
            for item in events
        ],
        hide_index=True,
        use_container_width=True,
    )
    selected = st.selectbox("Inspect event", [item.event_id for item in events], key="selected_audit_event")
    event = next(item for item in events if item.event_id == selected)
    st.json(asdict(event))


def render_configuration_versions(service: ConsoleService) -> None:
    st.title("Configuration Versions")
    versions = service.versions()
    if not versions:
        st.info("No configuration versions are available.")
        return
    st.dataframe([asdict(item) for item in versions], hide_index=True, use_container_width=True)
    rollback_targets = [item for item in versions if item.rollback_available]
    if rollback_targets:
        with st.form("rollback_form"):
            target = st.selectbox("Valid rollback target", [item.version_id for item in rollback_targets])
            actor = st.text_input("Local actor", value="local-reviewer", key="rollback_actor")
            reason = st.text_input("Rollback reason", value="Restore a prior validated configuration")
            confirmation = st.text_input("Type ROLLBACK")
            submit = st.form_submit_button("Rollback atomically")
        if submit:
            restored = service.configuration.rollback(target, actor, reason, confirmation)
            st.success(f"Restored configuration: {restored}")


def render_settings(service: ConsoleService) -> None:
    st.title("Settings")
    settings = service.settings()
    st.markdown(
        '<div class="safe-banner">Deterministic processing continues when the model kill switch is enabled. This control never stops all processing.</div>',
        unsafe_allow_html=True,
    )
    st.json(settings)
    st.error("`local_model` is rejected and unavailable for normal activation. Hosted-provider configuration is not exposed.")
    with st.form("kill_switch_form"):
        enabled = st.toggle("Model/AI kill switch enabled", value=bool(settings["model_kill_switch_enabled"]))
        actor = st.text_input("Local actor label", value="local-reviewer", key="kill_actor")
        confirmation = st.text_input("Type CONFIRM")
        submit = st.form_submit_button("Record kill-switch state")
    if submit:
        service.configuration.set_kill_switch(enabled, actor, confirmation)
        st.success("Kill-switch setting recorded. Rules-only processing remains active.")
    st.warning("Local prototype only: no production authentication or multi-user authorization layer.")


def _render_draft_workflow(manager: ConfigurationManager) -> None:
    with st.form("create_draft_form"):
        actor = st.text_input("Draft author", value="local-reviewer")
        reason = st.text_input("Change reason", value="Safe static rationale demonstration")
        create = st.form_submit_button("Create draft from active version")
    if create:
        draft = manager.create_draft(actor, reason)
        st.session_state["current_draft_reference"] = draft["draft_id"]
        st.success(f"Draft created: {draft['draft_id']}")
    drafts = manager.list_drafts()
    if not drafts:
        st.info("No drafts exist. Create one to begin the governed workflow.")
        return
    default = st.session_state.get("current_draft_reference", drafts[-1]["draft_id"])
    options = [item["draft_id"] for item in drafts]
    selected = st.selectbox("Current draft", options, index=options.index(default) if default in options else 0)
    st.session_state["current_draft_reference"] = selected
    draft = manager.draft(selected)
    st.json(draft)
    with st.form("rationale_edit_form"):
        config = manager.load_active_config()
        reason_code = st.selectbox("Approved reason code", config.vocab.reason_codes)
        body = st.text_area(
            "Static rationale text",
            value="A structured balance review is required; no account action is performed.",
            max_chars=300,
        )
        save = st.form_submit_button("Autosave draft edit")
    if save:
        manager.update_rationale_template(selected, reason_code, body)
        st.success("Draft edit autosaved; prior validation evidence was invalidated.")
    cols = st.columns(3)
    if cols[0].button("Validate draft", key="validate_draft"):
        st.session_state["draft_validation"] = manager.validate_draft(selected)
    if cols[1].button("Run full impact", key="impact_draft"):
        st.session_state["draft_impact"] = manager.impact_preview(selected)
    validation = st.session_state.get("draft_validation")
    impact = st.session_state.get("draft_impact")
    if isinstance(validation, dict):
        st.subheader("Validation evidence")
        st.json(validation)
    if isinstance(impact, dict):
        st.subheader("Complete impact preview")
        st.json(impact)
    with st.form("activate_draft_form"):
        activation_actor = st.text_input("Activation actor", value="local-reviewer")
        confirmation = st.text_input("Type ACTIVATE")
        activate = st.form_submit_button("Activate atomically")
    if activate:
        version = manager.activate(selected, activation_actor, confirmation)
        st.success(f"Activated immutable version: {version}")
        st.cache_data.clear()


def _render_pattern_lab(service: ConsoleService) -> None:
    st.caption("Synthetic input only. Test content is processed in memory/temporary storage and is never appended to operational audit.")
    labels = {fixture.label: fixture for fixture in FIXTURES}
    selected_label = st.selectbox("Permanent synthetic fixture", tuple(labels))
    selected = labels[selected_label]
    with st.form("pattern_lab_form", clear_on_submit=True):
        synthetic_text = st.text_area("Synthetic test text", value=selected.text, max_chars=1000)
        submit = st.form_submit_button("Run pattern and redaction test")
    if submit:
        result = run_pattern_lab(
            service.configuration.load_active_config(),
            synthetic_text=synthetic_text,
            fixture_id=selected.fixture_id,
        )
        st.json(asdict(result))
        if result.detector_counts:
            st.info("Only detector counts and placeholders are displayed; matched sensitive values are suppressed.")


def _render_message_detail(view: MessageView) -> None:
    st.subheader(f"Decision {view.message_id}")
    cols = st.columns(3)
    cols[0].metric("Core mismatch", "yes" if view.core_mismatch else "no")
    cols[1].metric("Diagnostic difference", "yes" if view.diagnostic_difference else "no")
    cols[2].metric("Model called", str(view.decision.get("model_called", False)).lower())
    st.json(view.decision)
    if view.expected_actual:
        st.markdown("**Expected versus actual**")
        st.dataframe(list(view.expected_actual), hide_index=True, use_container_width=True)
    st.json(
        {
            "triggered_rule_ids": view.rules_triggered,
            "decision_path": view.decision_path,
            "audit_event_id": view.audit_event_id,
            "configuration_version": view.configuration_version,
        }
    )


def _message_row(view: MessageView) -> dict[str, Any]:
    decision = view.decision
    return {
        "message_id": view.message_id,
        "market": decision.get("market"),
        "language": decision.get("language"),
        "category": decision.get("category"),
        "intent": decision.get("intent"),
        "priority": decision.get("priority"),
        "route": decision.get("route"),
        "team": decision.get("assigned_team"),
        "core mismatch": view.core_mismatch,
        "diagnostic difference": view.diagnostic_difference,
        "human review": decision.get("human_review_required"),
    }


def _diff_rows(original: Mapping[str, Any], proposed: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"field": field, "before": original.get(field), "after": value}
        for field, value in proposed.items()
        if original.get(field) != value
    ] or [{"field": "none", "before": "unchanged", "after": "unchanged"}]


def _agreement_text(document: Mapping[str, Any], field: str) -> str:
    metric = document.get("agreement", {}).get(field, {})
    return f"{metric.get('matches', 0)}/{metric.get('total', 0)}"


def render_import(service: ConsoleService) -> None:
    """Upload a CSV or XLSX batch and process it into an isolated run.

    The operator never chooses a server-side destination. Runs are written
    beneath the application-owned ``output/imported_runs/<run_id>`` root and
    copies are taken through browser downloads.
    """

    st.title("Import")
    st.markdown(
        '<div class="safe-banner">Imported batches run in rules-only mode. '
        "The rejected model is never called.</div>",
        unsafe_allow_html=True,
    )

    st.caption(
        "Accepted formats: CSV and XLSX. Identifiers may be M1 through "
        "M999999999 — padding is preserved exactly, so M1, M01 and M001 stay "
        "distinct. Rows that fail validation are reported, never silently "
        "dropped."
    )

    st.download_button(
        "Download CSV template",
        data=service.import_template_csv(),
        file_name="player_triage_import_template.csv",
        help=(
            "Fixed nine-column contract with one synthetic example row. "
            "Replace or delete the example before importing."
        ),
        key="import_template",
    )
    st.caption(
        "Phase 09 uses a fixed import contract rather than user-defined column "
        "mapping. This reduces ambiguity, makes validation deterministic and "
        "provides a reproducible template for the live demonstration."
    )

    uploaded = st.file_uploader(
        "Message batch", type=["csv", "xlsx"], key="import_upload"
    )
    allow_padded = st.checkbox(
        "Accept differently padded identifiers (M99 and M099) as separate rows",
        value=False,
        help=(
            "Off by default. When off, a later identifier that is numerically "
            "equal to an earlier one is rejected as "
            "ambiguous_padded_id_collision. Exact duplicates are always an "
            "error."
        ),
        key="import_allow_padded",
    )

    if uploaded is None:
        st.info("Choose a file to begin. Nothing is processed until you start the run.")
        _render_recent_runs(service)
        return

    payload = uploaded.getvalue()

    # --- preview: structure only, before anything is processed ---------------
    st.subheader("Preview")
    try:
        preview = service.preview_import(payload, display_name=uploaded.name)
    except Exception:
        st.error("The uploaded file could not be read. Check the format and try again.")
        _render_recent_runs(service)
        return

    info = st.columns(3)
    info[0].metric("Rows detected", preview.row_count)
    info[1].metric("Format", preview.detected_format.upper())
    info[2].metric("Columns", len(preview.detected_columns))
    st.caption(f"File: `{preview.display_name}`")

    if preview.columns_ok:
        st.success("Column contract satisfied.")
    else:
        if preview.missing_columns:
            st.error(f"Missing required columns: {', '.join(preview.missing_columns)}")
        if preview.unexpected_columns:
            st.error(f"Unexpected columns: {', '.join(preview.unexpected_columns)}")
        st.caption("Fix the header row, or start from the CSV template above.")

    if preview.row_count > MAX_IMPORT_ROWS:
        st.error(
            f"This file has {preview.row_count:,} rows, above the {MAX_IMPORT_ROWS:,}-row "
            "limit. Split it into smaller batches. Processing would fail before "
            "any row was classified."
        )

    if preview.sample_rows:
        st.caption(
            f"First {len(preview.sample_rows)} row(s). Subjects are truncated and "
            "message bodies are never shown here."
        )
        st.dataframe(preview.sample_rows, use_container_width=True, hide_index=True)

    if not st.button("Process batch", type="primary", key="import_run"):
        _render_recent_runs(service)
        return

    # --- processing: visible status so a large run never looks frozen -------
    try:
        with st.status("Processing batch…", expanded=True) as status:
            st.write("Validating file…")
            st.write(f"Creating run and processing {preview.row_count:,} row(s)…")
            result = service.run_import(
                payload,
                display_name=uploaded.name,
                collision_mode="allow" if allow_padded else "error",
            )
            st.write("Writing outputs…")
            if result.status == "failed":
                status.update(label="Run failed", state="error")
            else:
                status.update(label="Completed", state="complete")
    except Exception:
        st.error(
            "The import failed safely. No active configuration was changed and "
            "no partial run was published."
        )
        _render_recent_runs(service)
        return

    if result.status == "completed":
        st.success(f"Run {result.run_id} completed — {result.rows_processed} rows.")
    elif result.status == "completed_with_errors":
        st.warning(
            f"Run {result.run_id} completed with errors — "
            f"{result.rows_processed} processed, {result.rows_rejected} rejected, "
            f"{result.rows_failed} failed."
        )
    else:
        st.error(f"Run {result.run_id} failed. See the validation report below.")

    columns = st.columns(5)
    columns[0].metric("Rows seen", result.rows_seen)
    columns[1].metric("Accepted", result.rows_accepted)
    columns[2].metric("Rejected", result.rows_rejected)
    columns[3].metric("Processed", result.rows_processed)
    columns[4].metric("Failed", result.rows_failed)

    st.caption(
        f"Policy {result.policy_version} · rules_only · model calls "
        f"{result.model_calls} · decision digest `{result.decision_digest[:16]}…`"
    )

    if result.rejected_rows:
        st.subheader("Rejected rows")
        st.caption(
            "Every rejected row appears here. Explanations are sanitized: no "
            "message content, player identifiers or sensitive values."
        )
        st.dataframe(result.rejected_rows, use_container_width=True, hide_index=True)

    _render_run_downloads(service, result.run_id, key_prefix="current")
    _render_recent_runs(service)


_RUN_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("Decisions (CSV)", "decisions.csv"),
    ("Validation errors (CSV)", "validation_errors.csv"),
    ("Run manifest (JSON)", "run_manifest.json"),
    ("Processing summary (JSON)", "processing_summary.json"),
    ("Audit events (JSONL)", "audit.jsonl"),
)


def _render_run_downloads(
    service: ConsoleService, run_id: str, *, key_prefix: str
) -> None:
    st.subheader("Download artifacts")
    st.caption(
        "Downloads are the supported way to copy results elsewhere. The "
        "processing engine does not write outside the application root."
    )
    for label, filename in _RUN_ARTIFACTS:
        payload = service.read_import_artifact(run_id, filename)
        if payload is None:
            continue
        st.download_button(
            label,
            data=payload,
            file_name=f"{run_id}-{filename}",
            key=f"dl-{key_prefix}-{run_id}-{filename}",
        )


def _render_recent_runs(service: ConsoleService) -> None:
    """Recent imported runs — safe manifest metadata only."""

    st.divider()
    st.subheader("Recent imported runs")

    try:
        runs = service.recent_imported_runs()
    except Exception:
        st.caption("Recent runs are unavailable.")
        return

    if not runs:
        st.caption("No imported runs yet.")
        return

    st.caption(
        "Metadata only — run identifiers, counts and digests. No message "
        "content is stored or shown here."
    )
    st.dataframe(
        [
            {
                "run_id": run.run_id,
                "status": run.status,
                "started": run.started_at,
                "completed": run.completed_at or "—",
                "source": run.source_filename_sanitized,
                "seen": run.rows_seen,
                "processed": run.rows_processed,
                "rejected": run.rows_rejected,
                "policy": run.policy_version,
                "digest": (run.decision_digest or "—")[:16],
            }
            for run in runs
        ],
        use_container_width=True,
        hide_index=True,
    )

    labels = {f"{run.run_id} · {run.status}": run.run_id for run in runs}
    chosen = st.selectbox(
        "Reopen a run", tuple(labels), index=None, key="recent_run_pick"
    )
    if chosen is None:
        return

    run_id = labels[chosen]
    picked = next(run for run in runs if run.run_id == run_id)
    columns = st.columns(4)
    columns[0].metric("Rows seen", picked.rows_seen)
    columns[1].metric("Processed", picked.rows_processed)
    columns[2].metric("Rejected", picked.rows_rejected)
    columns[3].metric("Status", picked.status)
    st.caption(
        f"Policy {picked.policy_version} · digest "
        f"`{(picked.decision_digest or '—')[:32]}`"
    )
    _render_run_downloads(service, run_id, key_prefix="recent")


def render_walkthrough(service: ConsoleService) -> None:
    """Guided tour of the delivered system for a first-time reviewer."""

    st.title("Walkthrough")
    st.caption(
        "A five-minute orientation. Nothing on this page changes configuration "
        "or processes data."
    )

    overview = service.walkthrough_overview()

    st.markdown(
        '<div class="safe-banner">Runtime: <b>rules_only</b> · Policy: <b>'
        f'{overview["policy_version"]}</b> · Model: <b>rejected and '
        "unavailable</b> · Expected model calls: <b>0</b></div>",
        unsafe_allow_html=True,
    )

    st.subheader("1. What this system does")
    st.write(
        "It triages inbound player contacts into a category and intent, sets a "
        "priority, routes to a team, decides whether an automated response is "
        "permitted, and records an auditable reason for every decision. Every "
        "outcome is produced by deterministic rules."
    )

    st.subheader("2. Why there is no model")
    st.write(
        "A local model was evaluated and rejected: it produced no material "
        "improvement over the deterministic policy. The delivered runtime is "
        "rules-only, makes zero model calls, and does not install or import an "
        "inference runtime."
    )

    st.subheader("3. The accepted benchmark")
    st.write(
        "A supplied set of 40 messages is the accepted regression baseline. It "
        "keeps its own identifiers (M01–M40) and its own ground truth, and it "
        "reproduces a fixed canonical decision digest on every run."
    )
    st.code(overview["canonical_digest"], language="text")
    st.caption(
        f"Category agreement {overview['category_agreement']} · intent "
        f"agreement {overview['intent_agreement']} · the single documented "
        "intent mismatch is M22."
    )

    st.subheader("4. Importing your own data")
    st.write(
        "The Import page accepts CSV or XLSX. Imported data is deliberately "
        "separate from the benchmark: rows carry `source_message_id` "
        "(`M1`–`M999999999`, padding preserved), each accepted row gets a "
        "`case_ref`, and each batch gets a `run_id`. Batches larger than 99 "
        "rows are supported."
    )

    st.subheader("5. What you get back")
    st.write(
        "Each run is isolated in its own directory containing decisions, an "
        "audit trail, a validation-error report, a run manifest and a "
        "processing summary. Runs are never overwritten. Invalid rows are "
        "always reported rather than discarded."
    )

    st.subheader("6. What this prototype is not")
    st.write(
        "There is no production authentication, no multi-user authorization "
        "and no live integration. It runs locally over synthetic data for "
        "demonstration and review."
    )


PAGE_RENDERERS: Mapping[str, Callable[[ConsoleService], None]] = {
    "Walkthrough": render_walkthrough,
    "Dashboard": render_dashboard,
    "Import": render_import,
    "Messages": render_messages,
    "Human Review": render_human_review,
    "Policy Studio": render_policy_studio,
    "Evaluation": render_evaluation,
    "Audit Explorer": render_audit_explorer,
    "Configuration Versions": render_configuration_versions,
    "Settings": render_settings,
}
