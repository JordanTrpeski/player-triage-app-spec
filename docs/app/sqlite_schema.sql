-- No table stores source subject/body, player_id, PAN/CVV, identity-document content or attachment bytes.
CREATE TABLE configuration_versions (version_id TEXT PRIMARY KEY, parent_version_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL, change_reason TEXT NOT NULL, manifest_json TEXT NOT NULL, activated_at TEXT);
CREATE TABLE runs (run_id TEXT PRIMARY KEY, configuration_version TEXT NOT NULL, mode TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL);
CREATE TABLE decisions (run_id TEXT NOT NULL, message_id TEXT NOT NULL, decision_json TEXT NOT NULL, audit_event_id TEXT NOT NULL, PRIMARY KEY (run_id, message_id));
CREATE TABLE audit_events (event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, message_id TEXT, event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, configuration_version TEXT NOT NULL, event_json TEXT NOT NULL);
CREATE TABLE human_overrides (event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, message_id TEXT NOT NULL, parent_event_id TEXT NOT NULL, reason_code TEXT NOT NULL, override_json TEXT NOT NULL);
CREATE TABLE evaluation_summaries (run_id TEXT PRIMARY KEY, configuration_version TEXT NOT NULL, summary_json TEXT NOT NULL, hard_gates_passed INTEGER NOT NULL);
CREATE TABLE artifact_metadata (run_id TEXT NOT NULL, artifact_name TEXT NOT NULL, relative_path TEXT NOT NULL, sha256 TEXT, record_count INTEGER NOT NULL, PRIMARY KEY (run_id, artifact_name));
