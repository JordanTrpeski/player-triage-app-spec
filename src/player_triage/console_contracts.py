"""Typed service contracts for the local Streamlit control console."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    active_policy_version: str
    application_version: str
    runtime_mode: str
    model_status: str
    model_calls: int
    kill_switch_enabled: bool
    latest_run_id: str
    latest_run_status: str
    canonical_digest: str
    counts: Mapping[str, int]
    distributions: Mapping[str, Mapping[str, int]]
    manual_review_rate: float
    specialist_rate: float
    official_gates_passed: int
    official_gate_count: int
    locked_gates_passed: int
    locked_gate_count: int
    core_mismatch_count: int
    diagnostic_difference_count: int
    p50_latency_ms: float
    p95_latency_ms: float
    messages_per_second: float
    replay_900_seconds: float


@dataclass(frozen=True, slots=True)
class MessageView:
    message_id: str
    decision: Mapping[str, Any]
    expected_actual: tuple[Mapping[str, Any], ...]
    core_mismatch: bool
    diagnostic_difference: bool
    rules_triggered: tuple[str, ...]
    decision_path: str
    audit_event_id: str
    configuration_version: str


@dataclass(frozen=True, slots=True)
class AuditView:
    event_id: str
    run_id: str
    message_id: str | None
    event_type: str
    occurred_at: str
    configuration_version: str
    actor: Mapping[str, Any]
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ImportPreview:
    """Pre-processing view of an uploaded batch.

    Deliberately shallow: identifiers, routing-relevant metadata and a
    truncated subject only. Message bodies are never surfaced, and subjects are
    truncated, so the preview cannot become an unredacted content viewer.
    """

    display_name: str
    detected_format: str
    row_count: int
    detected_columns: tuple[str, ...]
    missing_columns: tuple[str, ...]
    unexpected_columns: tuple[str, ...]
    sample_rows: tuple[Mapping[str, str], ...]
    truncated: bool

    @property
    def columns_ok(self) -> bool:
        return not self.missing_columns and not self.unexpected_columns


@dataclass(frozen=True, slots=True)
class ImportedRunSummary:
    """Safe metadata for one previously completed imported run."""

    run_id: str
    status: str
    started_at: str
    completed_at: str | None
    source_filename_sanitized: str
    rows_seen: int
    rows_processed: int
    rows_rejected: int
    policy_version: str
    decision_digest: str | None


@dataclass(frozen=True, slots=True)
class ImportedRunDetail:
    """Dashboard-facing view of one completed imported run.

    Built from the run manifest and ``decisions.csv`` only. Those artifacts
    carry structured decision fields and internally generated identifiers, so
    no subject, body or player identifier can reach this contract. The run
    directory is deliberately absent: the console addresses runs by ``run_id``
    and never surfaces a filesystem path.
    """

    run_id: str
    status: str
    source_filename_sanitized: str
    started_at: str
    completed_at: str | None
    rows_seen: int
    rows_accepted: int
    rows_rejected: int
    rows_processed: int
    rows_failed: int
    policy_version: str
    model_calls: int
    decision_digest: str | None
    distributions: Mapping[str, Mapping[str, int]]
    decisions: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class ImportRunView:
    """Console-facing summary of one imported run.

    Carries counts, status and the deterministic decision digest only. No
    message content, player identifier or filesystem path is exposed to the
    UI layer. ``rejected_rows`` holds the sanitized validation-error report.
    """

    run_id: str
    status: str
    policy_version: str
    rows_seen: int
    rows_accepted: int
    rows_rejected: int
    rows_processed: int
    rows_failed: int
    decision_digest: str
    model_calls: int
    rejected_rows: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class VersionView:
    version_id: str
    parent_version_id: str | None
    status: str
    actor: str
    change_reason: str
    bundle_digest: str
    validation_passed: bool | None
    regression_passed: bool | None
    gates_passed: bool | None
    activated_at: str | None
    rollback_available: bool
    summary: str


class DashboardService(Protocol):
    def dashboard(self) -> DashboardSnapshot: ...


class MessageReviewService(Protocol):
    def messages(self, filters: Mapping[str, object] | None = None) -> Sequence[MessageView]: ...


class HumanOverrideService(Protocol):
    def submit_override(
        self,
        message_id: str,
        proposed: Mapping[str, Any],
        reason_code: str,
        actor_label: str,
    ) -> str: ...


class PolicyDraftService(Protocol):
    def create_draft(self, actor: str, change_reason: str) -> Mapping[str, Any]: ...

    def validate_draft(self, draft_id: str) -> Mapping[str, Any]: ...


class ImpactAnalysisService(Protocol):
    def impact_preview(self, draft_id: str) -> Mapping[str, Any]: ...


class ActivationGateService(Protocol):
    def activate(self, draft_id: str, actor: str, confirmation: str) -> str: ...


class ConfigurationVersionService(Protocol):
    def versions(self) -> Sequence[VersionView]: ...

    def rollback(self, version_id: str, actor: str, reason: str, confirmation: str) -> str: ...


class AuditQueryService(Protocol):
    def audit_events(self, filters: Mapping[str, object] | None = None) -> Sequence[AuditView]: ...


class SettingsService(Protocol):
    def settings(self) -> Mapping[str, Any]: ...

    def set_kill_switch(self, enabled: bool, actor: str, confirmation: str) -> None: ...

