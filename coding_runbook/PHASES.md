# Phased Coding Plan

Use the prompts in order. Paste only one prompt into Claude Code, Codex, or another coding agent at a time.

| Phase | Objective | Stop gate |
|---|---|---|
| 00 | Repository and policy-package audit | All package validators pass; no application code |
| 01 | Project scaffold, config/schema loaders, CLI skeleton | Unit tests load every config/schema |
| 02 | Dataset ingestion, normalization, linkage, sensitive detection/redaction | M11 redaction/bypass and M31 linkage tests pass |
| 03 | Deterministic policy engine and rules-only baseline | 40 terminal outputs; hard safety rules pass |
| 04 | Optional local-model adapter and feasibility benchmark | Provider interface works; safe fallback; no external API |
| 05 | End-to-end orchestration, CSV, JSONL, overrides and fallbacks | Outputs validate and contain no raw/sensitive text |
| 06 | Evaluation, regression, safety gates, latency and cost measurements | Evaluation bundle generated; hard gates pass |
| 07 | Walkthrough UI/CLI, kill switch, live change and rollback | Demonstrable before/after/rollback audit events |
| 08 | Documentation, two-page decision log and final packaging | One-command run and complete submission bundle |

Core-first rule: Phases 00–03 must pass before any UI or model expansion. The project remains valid in `rules_only` mode.
