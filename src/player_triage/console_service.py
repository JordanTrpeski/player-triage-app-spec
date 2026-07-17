"""Sanitized read/review services for the local control console."""

from __future__ import annotations

import json
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Mapping, Sequence

from .configuration_manager import ConfigurationManager
from .console_contracts import AuditView, DashboardSnapshot, MessageView, VersionView
from .errors import ConfigurationError
from .operational import (
    AUDIT_FILENAME,
    DECISIONS_JSONL_FILENAME,
    MANIFEST_FILENAME,
    append_human_override_decision,
    verify_run_artifacts,
)
from .routing import load_routing_map


_ROUTING = load_routing_map()


class ConsoleServiceError(ConfigurationError):
    """Sanitized console read/review failure."""


class ConsoleService:
    """Single typed facade consumed by Streamlit pages."""

    def __init__(
        self,
        app_root: Path,
        *,
        state_root: Path | None = None,
        output_root: Path | None = None,
    ) -> None:
        self.app_root = app_root.resolve()
        self.output_root = (
            output_root.resolve()
            if output_root is not None
            else (self.app_root / "output").resolve()
        )
        self.configuration = ConfigurationManager(self.app_root, state_root)

    def dashboard(self) -> DashboardSnapshot:
        run_dir = self.latest_run_dir()
        if run_dir is None:
            settings = self.configuration.settings()
            return DashboardSnapshot(
                active_policy_version=str(settings["active_policy_version"]),
                application_version=_application_version(),
                runtime_mode="rules_only",
                model_status="rejected / disabled",
                model_calls=0,
                kill_switch_enabled=bool(settings["model_kill_switch_enabled"]),
                latest_run_id="none",
                latest_run_status="no verified run",
                canonical_digest="unavailable",
                counts={"input": 0, "success": 0, "failure": 0, "bypass": 0},
                distributions={},
                manual_review_rate=0.0,
                specialist_rate=0.0,
                official_gates_passed=0,
                official_gate_count=15,
                locked_gates_passed=0,
                locked_gate_count=26,
                core_mismatch_count=0,
                diagnostic_difference_count=0,
                p50_latency_ms=0.0,
                p95_latency_ms=0.0,
                messages_per_second=0.0,
                replay_900_seconds=0.0,
            )
        config = self.configuration.load_active_config()
        verify_run_artifacts(config, run_dir)
        manifest = _read_json(run_dir / MANIFEST_FILENAME)
        decisions = _read_jsonl(run_dir / DECISIONS_JSONL_FILENAME)
        evaluation = self._evaluation_documents()
        supplied = _supplied_result(evaluation.get("dataset_results", {}))
        safety = evaluation.get("safety", {})
        performance = evaluation.get("performance", {})
        capacity = evaluation.get("capacity", {})
        route_counts = _counts(decisions, "route")
        specialist = _ROUTING.constants.specialist
        manual_count = sum(
            decision.get("human_review_required") is True for decision in decisions
        )
        settings = self.configuration.settings()
        return DashboardSnapshot(
            active_policy_version=str(settings["active_policy_version"]),
            application_version=_application_version(),
            runtime_mode="rules_only",
            model_status="rejected / disabled",
            model_calls=sum(decision.get("model_called") is True for decision in decisions),
            kill_switch_enabled=bool(settings["model_kill_switch_enabled"]),
            latest_run_id=str(manifest.get("run_id", "unavailable")),
            latest_run_status=str(manifest.get("status", "unavailable")),
            canonical_digest=str(manifest.get("canonical_decision_sha256", "unavailable")),
            counts={
                "input": int(manifest.get("message_count", 0)),
                "success": int(manifest.get("success_count", 0)),
                "failure": int(manifest.get("failure_count", 0)),
                "bypass": int(manifest.get("bypass_count", 0)),
            },
            distributions={
                "category": _counts(decisions, "category"),
                "priority": _counts(decisions, "priority"),
                "route": route_counts,
                "assigned_team": _counts(decisions, "assigned_team"),
            },
            manual_review_rate=manual_count / len(decisions) if decisions else 0.0,
            specialist_rate=route_counts.get(specialist, 0) / len(decisions)
            if decisions
            else 0.0,
            official_gates_passed=sum(
                bool(item.get("passed"))
                for item in safety.get("results", [])
                if str(item.get("gate_id", "")).startswith("S")
            ),
            official_gate_count=15,
            locked_gates_passed=sum(
                bool(item.get("passed")) for item in safety.get("results", [])
            ),
            locked_gate_count=26,
            core_mismatch_count=len(supplied.get("mismatches", [])),
            diagnostic_difference_count=len(
                supplied.get("diagnostic_differences", [])
            ),
            p50_latency_ms=float(performance.get("per_message_median_latency_ms", 0)),
            p95_latency_ms=float(performance.get("per_message_p95_latency_ms", 0)),
            messages_per_second=float(performance.get("messages_per_second", 0)),
            replay_900_seconds=float(
                capacity.get("full_day_replay_seconds_at_measured_throughput", 0)
            ),
        )

    def messages(
        self, filters: Mapping[str, object] | None = None
    ) -> Sequence[MessageView]:
        run_dir = self.latest_run_dir()
        if run_dir is None:
            return ()
        decisions = _read_jsonl(run_dir / DECISIONS_JSONL_FILENAME)
        events = {
            str(item.get("message_id")): item
            for item in _read_jsonl(run_dir / AUDIT_FILENAME)
            if item.get("event_type") == "decision"
        }
        mismatch_records = self._mismatch_records()
        by_message: dict[str, list[dict[str, Any]]] = {}
        for item in mismatch_records:
            if item.get("dataset_name") == "supplied-40":
                by_message.setdefault(str(item.get("message_id")), []).append(item)
        manifest = _read_json(run_dir / MANIFEST_FILENAME)
        views: list[MessageView] = []
        for decision in decisions:
            message_id = str(decision.get("message_id"))
            differences = tuple(by_message.get(message_id, ()))
            event = events.get(message_id, {})
            view = MessageView(
                message_id=message_id,
                decision=decision,
                expected_actual=differences,
                core_mismatch=any(
                    item.get("adjudication_status") != "diagnostic_non_baseline_difference"
                    for item in differences
                ),
                diagnostic_difference=any(
                    item.get("adjudication_status") == "diagnostic_non_baseline_difference"
                    for item in differences
                ),
                rules_triggered=tuple(
                    str(value) for value in event.get("payload", {}).get("rules_triggered", ())
                ),
                decision_path=str(event.get("payload", {}).get("decision_path", "")),
                audit_event_id=str(event.get("event_id", "")),
                configuration_version=str(manifest.get("policy_bundle_version", "")),
            )
            if _matches_message_filters(view, filters or {}):
                views.append(view)
        return tuple(views)

    def review_queue(self) -> Sequence[MessageView]:
        return tuple(
            view
            for view in self.messages()
            if view.decision.get("human_review_required") is True
            or bool(view.decision.get("missing_context"))
            or view.core_mismatch
            or view.diagnostic_difference
        )

    def submit_override(
        self,
        message_id: str,
        proposed: Mapping[str, Any],
        reason_code: str,
        actor_label: str,
    ) -> str:
        run_dir = self.latest_run_dir()
        if run_dir is None:
            raise self._error("human_override", "no verified run is available")
        original = next(
            (view.decision for view in self.messages() if view.message_id == message_id),
            None,
        )
        if original is None:
            raise self._error("human_override", "message was not found")
        after = dict(original)
        allowed = {
            "category",
            "intent",
            "secondary_intents",
            "priority",
            "route",
            "assigned_team",
            "secondary_teams",
            "risk_flags",
            "reason_codes",
        }
        unknown = set(proposed) - allowed
        if unknown:
            raise self._error("human_override", "override contains an unsupported field")
        after.update(proposed)
        after["decision_basis"] = "human_override"
        return append_human_override_decision(
            self.configuration.load_active_config(),
            run_dir=run_dir,
            message_id=message_id,
            reason_code=reason_code,
            after=after,
            actor_label=actor_label,
        )

    def audit_events(
        self, filters: Mapping[str, object] | None = None
    ) -> Sequence[AuditView]:
        documents: list[dict[str, Any]] = []
        run_dir = self.latest_run_dir()
        if run_dir is not None:
            documents.extend(_read_jsonl(run_dir / AUDIT_FILENAME))
        documents.extend(self.configuration.control_audit_events())
        output: list[AuditView] = []
        for event in documents:
            view = AuditView(
                event_id=str(event.get("event_id", "")),
                run_id=str(event.get("run_id", "")),
                message_id=(
                    str(event["message_id"])
                    if event.get("message_id") is not None
                    else None
                ),
                event_type=str(event.get("event_type", "")),
                occurred_at=str(event.get("occurred_at", "")),
                configuration_version=str(event.get("configuration_version", "")),
                actor=dict(event.get("actor", {})),
                payload=dict(event.get("payload", {})),
            )
            if _matches_audit_filters(view, filters or {}):
                output.append(view)
        return tuple(sorted(output, key=lambda item: item.occurred_at, reverse=True))

    def versions(self) -> Sequence[VersionView]:
        active = self.configuration.active_state()["version_id"]
        return tuple(
            VersionView(
                version_id=str(item.get("version_id", "")),
                parent_version_id=(
                    str(item["parent_version_id"])
                    if item.get("parent_version_id") is not None
                    else None
                ),
                status=str(item.get("status", "")),
                actor=str(item.get("actor", "")),
                change_reason=str(item.get("change_reason", "")),
                bundle_digest=str(item.get("bundle_digest", "")),
                validation_passed=_optional_bool(item.get("validation_passed")),
                regression_passed=_optional_bool(item.get("regression_passed")),
                gates_passed=_optional_bool(item.get("gates_passed")),
                activated_at=(
                    str(item["activated_at"])
                    if item.get("activated_at") is not None
                    else None
                ),
                rollback_available=str(item.get("version_id")) != str(active)
                and str(item.get("status")) != "draft",
                summary=str(item.get("summary", "")),
            )
            for item in self.configuration.versions()
        )

    def settings(self) -> Mapping[str, Any]:
        return self.configuration.settings()

    def policy_components(self) -> Mapping[str, Any]:
        config = self.configuration.load_active_config()
        editability = config.component("ui_editability").get("components", {})
        output: dict[str, Any] = {}
        for component in (
            "policy_rules",
            "baseline_intent_rules",
            "derived_refinement_rules",
            "redaction_policy",
            "market_overlays",
            "auto_response_templates",
            "rationale_templates",
            "semantic_constraints",
            "model_configuration",
        ):
            document = dict(config.component(component))
            if component == "model_configuration":
                for key in ("local_path_reference", "approved_model_id", "sha256"):
                    document.pop(key, None)
            output[component] = {
                "version": document.get("version"),
                "digest": config.component_digest(component),
                "ui": editability.get(component, {"normal_ui": "read_only"}),
                "document": document,
            }
        return output

    def evaluation_documents(self) -> Mapping[str, Any]:
        return self._evaluation_documents()

    def safe_downloads(self) -> Mapping[str, bytes]:
        allowed = (
            "evaluation_summary.json",
            "mismatch_report.csv",
            "confusion_matrix.csv",
            "safety_gate_results.json",
            "performance_results.json",
            "capacity_estimate.json",
            "human_review_workload.json",
        )
        output: dict[str, bytes] = {}
        for name in allowed:
            path = self.output_root / name
            if path.is_file():
                output[name] = path.read_bytes()
        return output

    def latest_run_dir(self) -> Path | None:
        candidates: list[tuple[str, Path]] = []
        if not self.output_root.is_dir():
            return None
        for manifest_path in self.output_root.rglob(MANIFEST_FILENAME):
            directory = manifest_path.parent
            if not (directory / DECISIONS_JSONL_FILENAME).is_file():
                continue
            try:
                manifest = _read_json(manifest_path)
            except ConsoleServiceError:
                continue
            candidates.append((str(manifest.get("completed_at", "")), directory))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    def _evaluation_documents(self) -> dict[str, Any]:
        names = {
            "summary": "evaluation_summary.json",
            "dataset_results": "dataset_results.json",
            "safety": "safety_gate_results.json",
            "performance": "performance_results.json",
            "capacity": "capacity_estimate.json",
            "workload": "human_review_workload.json",
            "cost": "cost_estimate.json",
            "audit_reconstruction": "audit_reconstruction.json",
        }
        output: dict[str, Any] = {}
        for key, name in names.items():
            path = self.output_root / name
            if path.is_file():
                try:
                    output[key] = _read_json(path)
                except ConsoleServiceError:
                    continue
        return output

    def _mismatch_records(self) -> list[dict[str, Any]]:
        path = self.output_root / "mismatch_report.jsonl"
        return _read_jsonl(path) if path.is_file() else []

    @staticmethod
    def _error(component: str, message: str) -> ConsoleServiceError:
        return ConsoleServiceError(component=component, message=message)


def _matches_message_filters(view: MessageView, filters: Mapping[str, object]) -> bool:
    decision = view.decision
    scalar_fields = {
        "message_id": view.message_id,
        "market": decision.get("market"),
        "language": decision.get("language"),
        "category": decision.get("category"),
        "intent": decision.get("intent"),
        "priority": decision.get("priority"),
        "route": decision.get("route"),
        "assigned_team": decision.get("assigned_team"),
        "model_eligibility": decision.get("model_eligibility"),
        "model_bypass_reason": decision.get("model_bypass_reason"),
        "human_review_required": decision.get("human_review_required"),
        "configuration_version": view.configuration_version,
        "core_mismatch": view.core_mismatch,
        "diagnostic_difference": view.diagnostic_difference,
    }
    list_fields = {
        "secondary_team": decision.get("secondary_teams", ()),
        "risk_flag": decision.get("risk_flags", ()),
        "reason_code": decision.get("reason_codes", ()),
    }
    for key, expected in filters.items():
        if expected in (None, "", (), []):
            continue
        if key in scalar_fields and scalar_fields[key] != expected:
            return False
        if key in list_fields and expected not in list_fields[key]:
            return False
    return True


def _matches_audit_filters(view: AuditView, filters: Mapping[str, object]) -> bool:
    scalar = {
        "event_id": view.event_id,
        "run_id": view.run_id,
        "message_id": view.message_id,
        "event_type": view.event_type,
        "configuration_version": view.configuration_version,
    }
    serialized = json.dumps(asdict(view), sort_keys=True)
    for key, expected in filters.items():
        if expected in (None, ""):
            continue
        if key in scalar and scalar[key] != expected:
            return False
        if key in {"rule_id", "reason_code", "actor", "component"} and str(expected) not in serialized:
            return False
        if key == "date_from" and view.occurred_at < str(expected):
            return False
        if key == "date_to" and view.occurred_at > str(expected):
            return False
    return True


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConsoleServiceError(component="console_read", message="structured artifact is unavailable") from exc
    if not isinstance(document, dict):
        raise ConsoleServiceError(component="console_read", message="structured artifact is invalid")
    return document


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConsoleServiceError(component="console_read", message="structured artifact is unavailable") from exc
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConsoleServiceError(component="console_read", message="structured artifact is invalid") from exc
        if not isinstance(item, dict):
            raise ConsoleServiceError(component="console_read", message="structured artifact is invalid")
        output.append(item)
    return output


def _counts(decisions: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    output: dict[str, int] = {}
    for decision in decisions:
        key = str(decision.get(field))
        output[key] = output.get(key, 0) + 1
    return dict(sorted(output.items()))


def _supplied_result(document: Mapping[str, Any]) -> Mapping[str, Any]:
    return next(
        (
            item
            for item in document.get("results", ())
            if isinstance(item, Mapping) and item.get("dataset_name") == "supplied-40"
        ),
        {},
    )


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _application_version() -> str:
    try:
        return package_version("player_triage")
    except PackageNotFoundError:
        return "uninstalled"
