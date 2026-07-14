# Export Contract

The main CSV is a readable operational view containing metadata, classification, routing, safety flags and decision provenance. It excludes subject/body text, player ID and sensitive values. Arrays are serialized as semicolon-delimited controlled values.

The JSONL audit file contains lifecycle events validated by `audit_event_schema.json`. Decision events include the complete final decision object; configuration and override events preserve before/after data without raw source content.
