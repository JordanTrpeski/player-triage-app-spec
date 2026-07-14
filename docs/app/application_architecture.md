# Application Architecture

## Components
1. **Input adapter** — CSV/XLSX validation and canonical message object.
2. **Linkage service** — local player/ticket linkage; emits only message references.
3. **Detection and redaction service** — sensitive-data flags, prompt-injection flag, attachment metadata, redacted text.
4. **Deterministic pre-model rules** — critical safety and bypass decisions.
5. **Semantic classifier interface** — rules-only baseline or optional local model.
6. **Deterministic post-semantic policy engine** — complaint, marketing, reopening, market overlays, priority/route/team finalization.
7. **Semantic validator** — cross-field invariants beyond JSON Schema.
8. **Rationale renderer** — renders approved text from reason codes; never model-generated.
9. **Audit writer** — append-only JSONL and SQLite audit index.
10. **Evaluation service** — ground-truth comparison, hard gates, metrics, latency, mismatch report.
11. **Configuration manager** — draft/version/validate/impact/activate/rollback.
12. **Streamlit UI and Typer CLI** — two interfaces over the same application services.

## Persistence
- Raw messages remain only in the input files.
- SQLite stores configuration versions, runs, decisions, audit indexes, overrides, and evaluation summaries; it does not store raw message bodies.
- CSV/JSONL are authoritative export artifacts.
- Active configuration is an immutable version bundle identified by hashes.

## Decision sequence
Input → validation → linkage → detection/redaction → pre-model rules → eligible semantic classifier → post-semantic rules → market overlay → semantic validation → rationale rendering → audit/export.
