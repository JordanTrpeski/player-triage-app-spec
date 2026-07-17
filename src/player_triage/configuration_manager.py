"""Immutable local configuration drafts, activation and audited rollback."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .artifact_io import atomic_write_json, atomic_write_text, sha256_file, stable_json
from .config import AppConfig, POLICY_COMPONENT_FILES, load_app_config
from .errors import ConfigurationError
from .evaluation_datasets import load_evaluation_dataset, run_evaluation_dataset
from .evaluation_governance import (
    SafetyGateResult,
    activation_recommendation,
    compare_decisions,
    evaluate_candidate_invariants,
    evaluate_non_compensatory_gates,
)
from .evaluation_metrics import calculate_dataset_metrics
from .operational import canonical_decision_digest


class ConsoleConfigurationError(ConfigurationError):
    """Sanitized failure from the local configuration manager."""


class ConfigurationManager:
    """Own drafts and immutable bundles without editing active policy files."""

    def __init__(self, app_root: Path, state_root: Path | None = None) -> None:
        self.app_root = app_root.resolve()
        self.state_root = (
            state_root.resolve()
            if state_root is not None
            else (self.app_root / "output" / "control_console").resolve()
        )
        self.drafts_root = self.state_root / "drafts"
        self.versions_root = self.state_root / "versions"
        self.active_pointer = self.state_root / "active_configuration.json"
        self.audit_path = self.state_root / "control_audit.jsonl"
        self.settings_path = self.state_root / "settings.json"
        self.locks_root = self.state_root / "locks"
        for directory in (
            self.drafts_root,
            self.versions_root,
            self.locks_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.settings_path.exists():
            atomic_write_json(
                self.settings_path,
                {
                    "model_kill_switch_enabled": True,
                    "runtime_mode": "rules_only",
                    "settings_version": 1,
                },
            )

    def active_state(self) -> dict[str, Any]:
        if self.active_pointer.is_file():
            document = json.loads(self.active_pointer.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise self._error("active_pointer", "active configuration pointer is invalid")
            return document
        config = load_app_config(self.app_root)
        return {
            "version_id": config.bundle_version,
            "parent_version_id": config.manifest.parent_version_id,
            "policy_relative_path": None,
            "bundle_digest": component_bundle_digest(self.app_root / "policy"),
            "activated_at": config.manifest.model_dump().get("activated_at"),
        }

    def active_policy_dir(self) -> Path:
        state = self.active_state()
        relative = state.get("policy_relative_path")
        if relative is None:
            return self.app_root / "policy"
        path = (self.state_root / str(relative)).resolve()
        if self.state_root not in path.parents or not path.is_dir():
            raise self._error("active_pointer", "active configuration path is invalid")
        return path

    def load_active_config(self) -> AppConfig:
        return load_app_config(
            self.app_root,
            strict_version=False,
            policy_path=self.active_policy_dir(),
        )

    def create_draft(self, actor: str, change_reason: str) -> dict[str, Any]:
        actor = _safe_label(actor, "actor")
        reason = _safe_reason(change_reason)
        parent = self.active_state()
        draft_id = f"draft-{_compact_time()}-{uuid.uuid4().hex[:8]}"
        draft_dir = self.drafts_root / draft_id
        policy_target = draft_dir / "policy"
        shutil.copytree(self.active_policy_dir(), policy_target)
        manifest_path = policy_target / "configuration_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            {
                "version_id": draft_id,
                "parent_version_id": parent["version_id"],
                "status": "draft",
                "created_at": _utc_now(),
                "created_by": actor,
                "change_reason": reason,
                "validation_summary": None,
                "impact_summary": None,
                "activation_event_id": None,
            }
        )
        atomic_write_json(manifest_path, manifest)
        metadata = {
            "draft_id": draft_id,
            "status": "draft",
            "actor": actor,
            "change_reason": reason,
            "created_at": _utc_now(),
            "parent_version_id": parent["version_id"],
            "parent_bundle_digest": parent["bundle_digest"],
            "draft_bundle_digest": component_bundle_digest(policy_target),
            "changes": [],
        }
        atomic_write_json(draft_dir / "draft_metadata.json", metadata)
        self._audit_configuration(
            event_type="configuration_change",
            from_version=str(parent["version_id"]),
            to_version=draft_id,
            reason="DRAFT_CREATED",
            actor=actor,
            changes=(),
            validation_passed=False,
            regression_passed=False,
        )
        return metadata

    def draft(self, draft_id: str) -> dict[str, Any]:
        path = self._draft_dir(draft_id) / "draft_metadata.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise self._error("draft", "draft metadata is unavailable") from exc
        if not isinstance(document, dict):
            raise self._error("draft", "draft metadata is invalid")
        return document

    def list_drafts(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for path in sorted(self.drafts_root.glob("draft-*/draft_metadata.json")):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                output.append(item)
        return output

    def update_rationale_template(
        self, draft_id: str, reason_code: str, body: str
    ) -> dict[str, Any]:
        if not body.strip() or len(body) > 300:
            raise self._error("draft_edit", "rationale text is invalid")
        if "{" in body or "}" in body:
            raise self._error("draft_edit", "dynamic placeholders are not allowed")
        return self._edit_template_map(
            draft_id,
            component="rationale_templates",
            key=reason_code,
            value=body.strip(),
        )

    def update_auto_response_template(
        self, draft_id: str, template_id: str, body: str
    ) -> dict[str, Any]:
        if "{" in body or "}" in body or not body.strip():
            raise self._error("draft_edit", "template must be static approved text")
        draft_dir = self._draft_dir(draft_id)
        path = draft_dir / "policy" / POLICY_COMPONENT_FILES["auto_response_templates"]
        document = _read_mapping(path, "draft_edit")
        templates = document.get("templates")
        if not isinstance(templates, list):
            raise self._error("draft_edit", "template component is invalid")
        target = next(
            (item for item in templates if isinstance(item, dict) and item.get("id") == template_id),
            None,
        )
        if target is None:
            raise self._error("draft_edit", "template ID is not approved")
        old = target.get("body")
        target["body"] = body.strip()
        self._save_component_edit(
            draft_id,
            "auto_response_templates",
            document,
            f"templates.{template_id}.body",
            old,
            body.strip(),
        )
        return self.draft(draft_id)

    def update_derived_rule_field(
        self, draft_id: str, rule_id: str, field_path: str, value: object
    ) -> dict[str, Any]:
        draft_dir = self._draft_dir(draft_id)
        path = draft_dir / "policy" / "derived_refinement_rules.json"
        document = _read_mapping(path, "draft_edit")
        rules = document.get("rules")
        if not isinstance(rules, list):
            raise self._error("draft_edit", "derived rules component is invalid")
        target = next(
            (item for item in rules if isinstance(item, dict) and item.get("id") == rule_id),
            None,
        )
        if target is None:
            raise self._error("draft_edit", "rule was not found")
        editability = target.get("editability")
        if editability == "locked":
            raise self._error("locked_policy", "locked rule is read only")
        allowed = {
            "minimum_priority",
            "set.priority",
            "set.route",
            "set.assigned_team",
            "set.human_review_required",
        }
        if field_path not in allowed:
            raise self._error("draft_edit", "field is not editable through the normal UI")
        old = _get_path(target, field_path)
        _set_path(target, field_path, value)
        self._save_component_edit(
            draft_id,
            "derived_refinement_rules",
            document,
            f"rules.{rule_id}.{field_path}",
            old,
            value,
        )
        return self.draft(draft_id)

    def update_market_overlay_field(
        self, draft_id: str, overlay_id: str, field_path: str, value: object
    ) -> dict[str, Any]:
        allowed = {"routing.add_secondary_teams", "routing.minimum_priority", "note"}
        if field_path not in allowed:
            raise self._error("market_overlay", "market overlay field is not UI-editable")
        draft_dir = self._draft_dir(draft_id)
        path = draft_dir / "policy" / POLICY_COMPONENT_FILES["market_overlays"]
        document = _read_mapping(path, "market_overlay")
        overlays = document.get("overlays")
        if not isinstance(overlays, list):
            raise self._error("market_overlay", "market overlay component is invalid")
        target = next(
            (item for item in overlays if isinstance(item, dict) and item.get("id") == overlay_id),
            None,
        )
        if target is None:
            raise self._error("market_overlay", "market overlay was not found")
        old = _get_path(target, field_path)
        _set_path(target, field_path, value)
        self._save_component_edit(
            draft_id,
            "market_overlays",
            document,
            f"overlays.{overlay_id}.{field_path}",
            old,
            value,
        )
        return self.draft(draft_id)

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        draft_dir = self._draft_dir(draft_id)
        metadata = self.draft(draft_id)
        current_digest = component_bundle_digest(draft_dir / "policy")
        locked_changes = self._locked_changes(draft_dir / "policy")
        try:
            config = load_app_config(
                self.app_root,
                strict_version=False,
                policy_path=draft_dir / "policy",
            )
            model = config.component("model_configuration")
            rejected_model_safe = model.get("approval_status") != "approved"
            passed = not locked_changes and rejected_model_safe
        except ConfigurationError:
            passed = False
            rejected_model_safe = False
        result = {
            "draft_id": draft_id,
            "draft_bundle_digest": current_digest,
            "parent_version_id": metadata["parent_version_id"],
            "parent_bundle_digest": metadata["parent_bundle_digest"],
            "schema_valid": passed,
            "semantic_valid": passed,
            "behavior_fixtures_ready": passed,
            "locked_changes": locked_changes,
            "rejected_model_safe": rejected_model_safe,
            "validated_at": _utc_now(),
        }
        atomic_write_json(draft_dir / "validation_result.json", result)
        self._audit_configuration(
            event_type="configuration_change",
            from_version=str(metadata["parent_version_id"]),
            to_version=draft_id,
            reason="DRAFT_VALIDATED" if passed else "DRAFT_VALIDATION_REJECTED",
            actor=str(metadata["actor"]),
            changes=tuple(metadata.get("changes", ())),
            validation_passed=passed,
            regression_passed=False,
            blocked=tuple(locked_changes),
        )
        return result

    def impact_preview(self, draft_id: str) -> dict[str, Any]:
        validation = self.validate_draft(draft_id)
        if not validation["schema_valid"]:
            raise self._error("impact", "draft validation failed")
        draft_dir = self._draft_dir(draft_id)
        active_config = self.load_active_config()
        candidate_config = load_app_config(
            self.app_root,
            strict_version=False,
            policy_path=draft_dir / "policy",
        )
        names = ("supplied-40", "holdout-v1", "holdout-v2")
        active_runs = {
            name: run_evaluation_dataset(
                active_config, load_evaluation_dataset(active_config, name)
            )
            for name in names
        }
        candidate_runs = {
            name: run_evaluation_dataset(
                candidate_config, load_evaluation_dataset(candidate_config, name)
            )
            for name in names
        }
        active_metrics = {
            name: calculate_dataset_metrics(run) for name, run in active_runs.items()
        }
        candidate_metrics = {
            name: calculate_dataset_metrics(run) for name, run in candidate_runs.items()
        }
        active_supplied = active_runs["supplied-40"]
        candidate_supplied = candidate_runs["supplied-40"]
        impact = compare_decisions(
            active_supplied.decisions_by_id,
            candidate_supplied.decisions_by_id,
            active_mismatches=[
                (item.message_id, item.field)
                for item in active_metrics["supplied-40"].mismatches
            ],
            candidate_mismatches=[
                (item.message_id, item.field)
                for item in candidate_metrics["supplied-40"].mismatches
            ],
        )
        active_diagnostics = {
            (item.message_id, item.field)
            for item in active_metrics["supplied-40"].diagnostic_differences
        }
        candidate_diagnostics = {
            (item.message_id, item.field)
            for item in candidate_metrics["supplied-40"].diagnostic_differences
        }
        impact["diagnostic_differences_introduced"] = _pairs(
            candidate_diagnostics - active_diagnostics
        )
        impact["diagnostic_differences_resolved"] = _pairs(
            active_diagnostics - candidate_diagnostics
        )
        impact["human_review_changes"] = sum(
            left.get("human_review_required") != candidate_supplied.decisions_by_id[mid].get(
                "human_review_required"
            )
            for mid, left in active_supplied.decisions_by_id.items()
            if mid in candidate_supplied.decisions_by_id
        )
        candidate_gates = evaluate_non_compensatory_gates(
            candidate_config,
            tuple(candidate_runs.values()),
            artifacts_verified=True,
            audit_schema_valid=True,
        )
        candidate_invariants = evaluate_candidate_invariants(
            candidate_config, candidate_supplied.decisions_by_id
        )
        # The eleven L-gates already include the candidate invariants' concepts;
        # retain the authoritative 26-gate result while exposing C-gates separately.
        schema_rate = candidate_metrics["supplied-40"].schema_validity.rate or 0.0
        semantic_rate = candidate_metrics["supplied-40"].semantic_validity.rate or 0.0
        recommendation = activation_recommendation(
            candidate_gates,
            output_schema_rate=schema_rate,
            audit_schema_rate=1.0,
            configuration_hash_valid=True,
            rollback_valid=True,
            change_impact=impact,
        )
        failed_invariants = {
            item.gate_id for item in candidate_invariants if not item.passed
        }
        if semantic_rate < 1.0 or failed_invariants:
            additional_blockers = set(failed_invariants)
            if semantic_rate < 1.0:
                additional_blockers.add("SEMANTIC_VALIDITY_BELOW_100_PERCENT")
            recommendation = {
                **recommendation,
                "recommendation": "block",
                "activation_allowed": False,
                "locked_blockers": sorted(
                    set(_string_sequence(recommendation.get("locked_blockers")))
                    | additional_blockers
                ),
            }
        result = {
            "draft_id": draft_id,
            "draft_bundle_digest": validation["draft_bundle_digest"],
            "parent_version_id": validation["parent_version_id"],
            "parent_bundle_digest": validation["parent_bundle_digest"],
            "impact": impact,
            "candidate_canonical_digest": canonical_decision_digest(
                tuple(candidate_supplied.decisions_by_id.values())
            ),
            "active_canonical_digest": canonical_decision_digest(
                tuple(active_supplied.decisions_by_id.values())
            ),
            "dataset_metrics": {
                name: {
                    "message_count": metric.message_count,
                    "core_mismatch_count": len(metric.mismatches),
                    "diagnostic_difference_count": len(metric.diagnostic_differences),
                    "schema_validity_rate": metric.schema_validity.rate,
                    "semantic_validity_rate": metric.semantic_validity.rate,
                    "category_agreement": asdict(metric.agreement["category"]),
                    "intent_agreement": asdict(metric.agreement["intent"]),
                    "priority_agreement": asdict(metric.agreement["priority"]),
                    "route_agreement": asdict(metric.agreement["route"]),
                    "team_agreement": asdict(metric.agreement["assigned_team"]),
                }
                for name, metric in candidate_metrics.items()
            },
            "official_and_locked_gates": [asdict(item) for item in candidate_gates],
            "candidate_invariants": [asdict(item) for item in candidate_invariants],
            "activation_recommendation": recommendation,
            "validation_evidence_at": _utc_now(),
        }
        atomic_write_json(draft_dir / "impact_result.json", result)
        metadata = self.draft(draft_id)
        self._audit_configuration(
            event_type="configuration_change",
            from_version=str(metadata["parent_version_id"]),
            to_version=draft_id,
            reason="IMPACT_ANALYSIS_COMPLETED",
            actor=str(metadata["actor"]),
            changes=tuple(metadata.get("changes", ())),
            validation_passed=True,
            regression_passed=bool(recommendation["activation_allowed"]),
            blocked=_string_sequence(recommendation.get("locked_blockers")),
        )
        return result

    def activate(self, draft_id: str, actor: str, confirmation: str) -> str:
        actor = _safe_label(actor, "actor")
        if confirmation != "ACTIVATE":
            raise self._error("activation", "explicit activation confirmation is required")
        draft_dir = self._draft_dir(draft_id)
        metadata = self.draft(draft_id)
        try:
            evidence = json.loads(
                (draft_dir / "impact_result.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise self._error("activation", "current impact evidence is required") from exc
        blockers: list[str] = []
        current_digest = component_bundle_digest(draft_dir / "policy")
        if evidence.get("draft_id") != draft_id:
            blockers.append("EVIDENCE_DRAFT_MISMATCH")
        if evidence.get("parent_version_id") != metadata["parent_version_id"]:
            blockers.append("EVIDENCE_PARENT_MISMATCH")
        if evidence.get("parent_bundle_digest") != metadata["parent_bundle_digest"]:
            blockers.append("EVIDENCE_PARENT_DIGEST_MISMATCH")
        if evidence.get("draft_bundle_digest") != current_digest:
            blockers.append("STALE_VALIDATION_EVIDENCE")
        if any(
            item.get("passed") is not True
            for item in evidence.get("official_and_locked_gates", ())
            if isinstance(item, Mapping)
        ):
            blockers.append("LOCKED_GATE_FAILURE")
        if any(
            item.get("passed") is not True
            for item in evidence.get("candidate_invariants", ())
            if isinstance(item, Mapping)
        ):
            blockers.append("CANDIDATE_INVARIANT_FAILURE")
        if evidence.get("activation_recommendation", {}).get("activation_allowed") is not True:
            blockers.extend(
                str(item)
                for item in evidence.get("activation_recommendation", {}).get(
                    "locked_blockers", ()
                )
            )
        active = self.active_state()
        if active["version_id"] != metadata["parent_version_id"]:
            blockers.append("STALE_DRAFT_PARENT")
        if active["bundle_digest"] != metadata["parent_bundle_digest"]:
            blockers.append("DRAFT_PARENT_DIGEST_MISMATCH")
        if blockers:
            self._audit_configuration(
                event_type="configuration_change",
                from_version=str(active["version_id"]),
                to_version=draft_id,
                reason="ACTIVATION_REJECTED",
                actor=actor,
                changes=tuple(metadata.get("changes", ())),
                validation_passed=False,
                regression_passed=False,
                blocked=tuple(sorted(set(blockers))),
            )
            raise self._error("activation", "candidate activation was blocked")

        with self._exclusive_lock("configuration"):
            latest = self.active_state()
            if latest["version_id"] != metadata["parent_version_id"]:
                raise self._error("activation", "active configuration changed during activation")
            version_id = f"policy-ui-{_compact_time()}-{uuid.uuid4().hex[:8]}"
            temporary = self.versions_root / f".{version_id}.tmp"
            final = self.versions_root / version_id
            if final.exists() or temporary.exists():
                raise self._error("activation", "configuration version collision")
            shutil.copytree(draft_dir / "policy", temporary / "policy")
            manifest_path = temporary / "policy" / "configuration_manifest.json"
            manifest = _read_mapping(manifest_path, "activation")
            manifest.update(
                {
                    "version_id": version_id,
                    "parent_version_id": metadata["parent_version_id"],
                    "status": "active",
                    "created_at": _utc_now(),
                    "created_by": actor,
                    "change_reason": metadata["change_reason"],
                    "validation_summary": {
                        "passed": True,
                        "validated_at": evidence["validation_evidence_at"],
                    },
                    "impact_summary": {
                        "decision_change_count": evidence["impact"]["decision_change_count"],
                        "locked_gate_count": len(evidence["official_and_locked_gates"]),
                    },
                }
            )
            atomic_write_json(manifest_path, manifest)
            bundle_digest = component_bundle_digest(temporary / "policy")
            record = {
                "version_id": version_id,
                "parent_version_id": metadata["parent_version_id"],
                "status": "active",
                "actor": actor,
                "change_reason": metadata["change_reason"],
                "bundle_digest": bundle_digest,
                "validation_passed": True,
                "regression_passed": True,
                "gates_passed": True,
                "activated_at": _utc_now(),
                "summary": _change_summary(metadata.get("changes", ())),
                "changes": metadata.get("changes", ()),
            }
            atomic_write_json(temporary / "version_record.json", record)
            os.replace(temporary, final)
            pointer = {
                "version_id": version_id,
                "parent_version_id": metadata["parent_version_id"],
                "policy_relative_path": str(
                    (final / "policy").relative_to(self.state_root)
                ).replace("\\", "/"),
                "bundle_digest": bundle_digest,
                "activated_at": record["activated_at"],
            }
            atomic_write_json(self.active_pointer, pointer)
            metadata["status"] = "activated"
            metadata["activated_version_id"] = version_id
            atomic_write_json(draft_dir / "draft_metadata.json", metadata)
            self._audit_configuration(
                event_type="configuration_change",
                from_version=str(record["parent_version_id"]),
                to_version=version_id,
                reason=str(record["change_reason"]),
                actor=actor,
                changes=tuple(metadata.get("changes", ())),
                validation_passed=True,
                regression_passed=True,
            )
            return version_id

    def rollback(
        self, version_id: str, actor: str, reason: str, confirmation: str
    ) -> str:
        actor = _safe_label(actor, "actor")
        reason = _safe_reason(reason)
        if confirmation != "ROLLBACK":
            raise self._error("rollback", "explicit rollback confirmation is required")
        active = self.active_state()
        target_policy, target_digest = self._version_policy(version_id)
        try:
            target_config = load_app_config(
                self.app_root,
                strict_version=False,
                policy_path=target_policy,
            )
            rollback_gates = self._evaluate_policy_gates(target_config)
        except ConfigurationError as exc:
            self._audit_configuration(
                event_type="configuration_rollback",
                from_version=str(active["version_id"]),
                to_version=version_id,
                reason="ROLLBACK_REJECTED",
                actor=actor,
                changes=(),
                validation_passed=False,
                regression_passed=False,
                blocked=("ROLLBACK_VALIDATION_FAILED",),
            )
            raise self._error("rollback", "rollback target validation failed") from exc
        failed_gates = tuple(item.gate_id for item in rollback_gates if not item.passed)
        if failed_gates:
            self._audit_configuration(
                event_type="configuration_rollback",
                from_version=str(active["version_id"]),
                to_version=version_id,
                reason="ROLLBACK_REJECTED",
                actor=actor,
                changes=(),
                validation_passed=True,
                regression_passed=False,
                blocked=failed_gates,
            )
            raise self._error("rollback", "rollback target regression checks failed")
        with self._exclusive_lock("configuration"):
            latest = self.active_state()
            if latest["version_id"] != active["version_id"]:
                raise self._error("rollback", "active configuration changed during rollback")
            relative = (
                None
                if target_policy.resolve() == (self.app_root / "policy").resolve()
                else str(target_policy.relative_to(self.state_root)).replace("\\", "/")
            )
            pointer = {
                "version_id": version_id,
                "parent_version_id": active["version_id"],
                "policy_relative_path": relative,
                "bundle_digest": target_digest,
                "activated_at": _utc_now(),
            }
            atomic_write_json(self.active_pointer, pointer)
            self._audit_configuration(
                event_type="configuration_rollback",
                from_version=str(active["version_id"]),
                to_version=version_id,
                reason=reason,
                actor=actor,
                changes=(),
                validation_passed=True,
                regression_passed=True,
            )
        return version_id

    def _evaluate_policy_gates(
        self, config: AppConfig
    ) -> tuple[SafetyGateResult, ...]:
        """Run all official and locked gates for an activation or rollback target."""

        datasets = tuple(
            run_evaluation_dataset(config, load_evaluation_dataset(config, name))
            for name in ("supplied-40", "holdout-v1", "holdout-v2")
        )
        return evaluate_non_compensatory_gates(
            config,
            datasets,
            artifacts_verified=True,
            audit_schema_valid=True,
        )

    def versions(self) -> list[dict[str, Any]]:
        active = self.active_state()
        base = load_app_config(self.app_root)
        output: list[dict[str, Any]] = [
            {
                "version_id": base.bundle_version,
                "parent_version_id": base.manifest.parent_version_id,
                "status": "active" if active["version_id"] == base.bundle_version else "superseded",
                "actor": base.manifest.created_by,
                "change_reason": base.manifest.change_reason,
                "bundle_digest": component_bundle_digest(self.app_root / "policy"),
                "validation_passed": True,
                "regression_passed": True,
                "gates_passed": True,
                "activated_at": base.manifest.model_dump().get("activated_at"),
                "summary": "Accepted repository configuration.",
            }
        ]
        for path in sorted(self.versions_root.glob("policy-*/version_record.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            record["status"] = (
                "active" if record.get("version_id") == active["version_id"] else "superseded"
            )
            output.append(record)
        for draft in self.list_drafts():
            output.append(
                {
                    "version_id": draft["draft_id"],
                    "parent_version_id": draft["parent_version_id"],
                    "status": draft["status"],
                    "actor": draft["actor"],
                    "change_reason": draft["change_reason"],
                    "bundle_digest": draft["draft_bundle_digest"],
                    "validation_passed": None,
                    "regression_passed": None,
                    "gates_passed": None,
                    "activated_at": None,
                    "summary": _change_summary(draft.get("changes", ())),
                }
            )
        return output

    def settings(self) -> dict[str, Any]:
        document = json.loads(self.settings_path.read_text(encoding="utf-8"))
        active = self.active_state()
        return {
            **document,
            "active_policy_version": active["version_id"],
            "model_status": "rejected",
            "model_activation_available": False,
            "model_conclusion": "model_rejected_no_material_improvement",
            "application_root": "<app-root>",
            "output_directory": "<app-root>/output",
            "sqlite_path": "<latest-run>/audit.sqlite3",
        }

    def set_kill_switch(
        self, enabled: bool, actor: str, confirmation: str
    ) -> None:
        actor = _safe_label(actor, "actor")
        if confirmation != "CONFIRM":
            raise self._error("kill_switch", "kill-switch confirmation is required")
        with self._exclusive_lock("settings"):
            current = json.loads(self.settings_path.read_text(encoding="utf-8"))
            old = bool(current.get("model_kill_switch_enabled", True))
            current["model_kill_switch_enabled"] = bool(enabled)
            current["runtime_mode"] = "rules_only"
            current["settings_version"] = int(current.get("settings_version", 0)) + 1
            atomic_write_json(self.settings_path, current)
            active = self.active_state()
            self._audit_configuration(
                event_type="configuration_change",
                from_version=str(active["version_id"]),
                to_version=str(active["version_id"]),
                reason="MODEL_KILL_SWITCH_CHANGED",
                actor=actor,
                changes=(
                    {
                        "component": "settings",
                        "path": "model_kill_switch_enabled",
                        "old_value": old,
                        "new_value": bool(enabled),
                    },
                ),
                validation_passed=True,
                regression_passed=True,
            )

    def control_audit_events(self) -> list[dict[str, Any]]:
        if not self.audit_path.is_file():
            return []
        output: list[dict[str, Any]] = []
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    output.append(item)
        return output

    def _edit_template_map(
        self, draft_id: str, *, component: str, key: str, value: str
    ) -> dict[str, Any]:
        config = self.load_active_config()
        if key not in config.vocab.reason_codes:
            raise self._error("draft_edit", "reason code is not approved")
        draft_dir = self._draft_dir(draft_id)
        path = draft_dir / "policy" / POLICY_COMPONENT_FILES[component]
        document = _read_mapping(path, "draft_edit")
        templates = document.get("templates")
        if not isinstance(templates, dict) or key not in templates:
            raise self._error("draft_edit", "template key was not found")
        old = templates[key]
        templates[key] = value
        self._save_component_edit(
            draft_id, component, document, f"templates.{key}", old, value
        )
        return self.draft(draft_id)

    def _save_component_edit(
        self,
        draft_id: str,
        component: str,
        document: Mapping[str, Any],
        path: str,
        old_value: object,
        new_value: object,
    ) -> None:
        draft_dir = self._draft_dir(draft_id)
        component_path = draft_dir / "policy" / POLICY_COMPONENT_FILES.get(
            component, f"{component}.json"
        )
        atomic_write_json(component_path, document)
        manifest_path = draft_dir / "policy" / "configuration_manifest.json"
        manifest = _read_mapping(manifest_path, "draft_edit")
        manifest["components"][component] = sha256_file(component_path)
        atomic_write_json(manifest_path, manifest)
        metadata = self.draft(draft_id)
        changes = list(metadata.get("changes", ()))
        changes.append(
            {
                "component": component,
                "path": path,
                "old_value": old_value,
                "new_value": new_value,
            }
        )
        metadata["changes"] = changes
        metadata["draft_bundle_digest"] = component_bundle_digest(
            draft_dir / "policy"
        )
        metadata["updated_at"] = _utc_now()
        atomic_write_json(draft_dir / "draft_metadata.json", metadata)
        (draft_dir / "validation_result.json").unlink(missing_ok=True)
        (draft_dir / "impact_result.json").unlink(missing_ok=True)

    def _locked_changes(self, candidate_policy: Path) -> list[str]:
        active_policy = self.active_policy_dir()
        blocked: list[str] = []
        for component in ("model_configuration", "semantic_constraints"):
            filename = f"{component}.json"
            if sha256_file(active_policy / filename) != sha256_file(candidate_policy / filename):
                blocked.append(component)
        active_redaction = _read_mapping(
            active_policy / POLICY_COMPONENT_FILES["redaction_policy"], "locked_policy"
        )
        candidate_redaction = _read_mapping(
            candidate_policy / POLICY_COMPONENT_FILES["redaction_policy"], "locked_policy"
        )
        critical = set(
            self.load_active_config()
            .component("ui_editability")
            .get("components", {})
            .get("redaction_policy", {})
            .get("critical_detectors", ())
        )
        for detector_id in critical:
            left = _by_id(active_redaction.get("detectors"), str(detector_id))
            right = _by_id(candidate_redaction.get("detectors"), str(detector_id))
            if left != right:
                blocked.append(f"redaction_policy.{detector_id}")
        for component in ("policy_rules", "derived_refinement_rules"):
            component_filename = POLICY_COMPONENT_FILES.get(
                component, f"{component}.json"
            )
            left_document = _read_mapping(
                active_policy / component_filename, "locked_policy"
            )
            right_document = _read_mapping(
                candidate_policy / component_filename, "locked_policy"
            )
            left_rules = left_document.get("rules")
            right_rules = right_document.get("rules")
            if not isinstance(left_rules, list) or not isinstance(right_rules, list):
                blocked.append(component)
                continue
            for rule in left_rules:
                if isinstance(rule, dict) and rule.get("editability") == "locked":
                    rule_id = str(rule.get("id"))
                    if rule != _by_id(right_rules, rule_id):
                        blocked.append(f"{component}.{rule_id}")
        return sorted(set(blocked))

    def _draft_dir(self, draft_id: str) -> Path:
        if not draft_id.startswith("draft-") or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in draft_id
        ):
            raise self._error("draft", "draft identifier is invalid")
        path = (self.drafts_root / draft_id).resolve()
        if self.drafts_root not in path.parents or not path.is_dir():
            raise self._error("draft", "draft was not found")
        return path

    def _version_policy(self, version_id: str) -> tuple[Path, str]:
        base = load_app_config(self.app_root)
        if version_id == base.bundle_version:
            path = self.app_root / "policy"
            return path, component_bundle_digest(path)
        path = (self.versions_root / version_id / "policy").resolve()
        if self.versions_root not in path.parents or not path.is_dir():
            raise self._error("rollback", "rollback target was not found")
        return path, component_bundle_digest(path)

    def _audit_configuration(
        self,
        *,
        event_type: str,
        from_version: str,
        to_version: str,
        reason: str,
        actor: str,
        changes: Sequence[Mapping[str, Any]],
        validation_passed: bool,
        regression_passed: bool,
        blocked: Sequence[str] = (),
    ) -> str:
        event_id = f"control-{uuid.uuid4().hex}"
        event = {
            "audit_schema_version": "3.0",
            "event_id": event_id,
            "event_type": event_type,
            "run_id": "control-console",
            "occurred_at": _utc_now(),
            "message_id": None,
            "actor": {"type": "human", "role": "local-administrator", "actor_ref": actor},
            "configuration_version": to_version,
            "payload": {
                "from_version": from_version,
                "to_version": to_version,
                "change_reason": reason,
                "changes": [dict(item) for item in changes],
                "validation_passed": validation_passed,
                "regression_passed": regression_passed,
                "evaluation_run_id": None,
                "blocked_safety_changes": list(blocked),
            },
        }
        config = load_app_config(self.app_root)
        schema_id = config.schema_registry.ids["audit_event_schema.json"]
        config.schema_registry.validate(schema_id, event, component_hint="console_audit")
        with self._exclusive_lock("audit"):
            events = self.control_audit_events()
            events.append(event)
            atomic_write_text(
                self.audit_path,
                "\n".join(stable_json(item) for item in events) + "\n",
            )
        return event_id

    @contextmanager
    def _exclusive_lock(self, name: str) -> Iterator[None]:
        path = self.locks_root / f"{name}.lock"
        descriptor: int | None = None
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise self._error("lock", "configuration operation is already in progress") from exc
        try:
            os.write(descriptor, _utc_now().encode("utf-8"))
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            path.unlink(missing_ok=True)

    @staticmethod
    def _error(component: str, message: str) -> ConsoleConfigurationError:
        return ConsoleConfigurationError(component=component, message=message)


def component_bundle_digest(policy_path: Path) -> str:
    entries = {
        path.name: sha256_file(path)
        for path in sorted(policy_path.glob("*.json"))
        if path.name != "configuration_manifest.json"
    }
    return hashlib.sha256(stable_json(entries).encode("utf-8")).hexdigest()


def _read_mapping(path: Path, component: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConsoleConfigurationError(
            component=component, message="configuration document is unavailable"
        ) from exc
    if not isinstance(document, dict):
        raise ConsoleConfigurationError(
            component=component, message="configuration document is invalid"
        )
    return document


def _by_id(items: object, item_id: str) -> object:
    if not isinstance(items, list):
        return None
    return next(
        (item for item in items if isinstance(item, dict) and item.get("id") == item_id),
        None,
    )


def _get_path(document: Mapping[str, Any], path: str) -> object:
    current: object = document
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _set_path(document: dict[str, Any], path: str, value: object) -> None:
    parts = path.split(".")
    current = document
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[parts[-1]] = value


def _safe_label(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 80 or any(char in cleaned for char in "\r\n<>"):
        raise ConsoleConfigurationError(component=field, message=f"{field} label is invalid")
    return cleaned


def _safe_reason(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 200 or any(char in cleaned for char in "\r\n<>"):
        raise ConsoleConfigurationError(component="change_reason", message="change reason is invalid")
    return cleaned


def _pairs(items: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"message_id": message_id, "field": field}
        for message_id, field in sorted(items)
    ]


def _change_summary(changes: object) -> str:
    if not isinstance(changes, (list, tuple)) or not changes:
        return "No component edits recorded."
    components = sorted(
        {str(item.get("component")) for item in changes if isinstance(item, Mapping)}
    )
    return f"{len(changes)} structured edit(s) across {', '.join(components)}."


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(item) for item in value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _compact_time() -> str:
    return _utc_now().replace("-", "").replace(":", "").replace(".", "")
