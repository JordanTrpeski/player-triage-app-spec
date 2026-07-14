# Master Handoff for Claude Code or Codex

Repository root assumptions:
- `input/` contains the supplied workbook and exact CSV export.
- `policy/` contains the frozen Stage 9 contract.
- `schemas/` contains JSON Schemas.
- `coding_runbook/prompts/` contains phase prompts.

Start with `coding_runbook/prompts/00_repository_audit.md`. Do not ask the agent to build the whole system in one prompt. After each phase, review the phase report and test output before pasting the next prompt.

The coding agent should use relative paths from repository root. It must not need the research transcripts to implement the system; policy traceability is already consolidated in `policy/research_traceability.json`.
