# Export Contract

The main CSV is a readable operational view containing metadata, classification, routing, safety flags and decision provenance. It excludes subject/body text, player ID and sensitive values. Arrays are serialized as semicolon-delimited controlled values.

`decisions.jsonl` contains exactly one complete `output_schema.json`-valid final decision per successful message. `audit_events.jsonl` is a separate lifecycle stream containing only `audit_event_schema.json`-valid events. Decision audit events retain the governed decision snapshot for reconstruction; configuration and override events preserve before/after structured data without raw source content.

`audit.sqlite3` indexes the approved run, decisions, audit events, evaluation summary and artifact metadata. `run_manifest.json` records relative artifact paths, record counts and SHA-256 digests. None of these artifacts contains source/redacted message text, player identifiers, detected sensitive values or attachment content.
