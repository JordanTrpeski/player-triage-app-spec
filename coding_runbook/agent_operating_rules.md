# Coding Agent Operating Rules

1. Work one phase at a time. Do not continue to the next phase without the user's explicit instruction.
2. Read only the files listed by the current phase plus files they directly reference.
3. Treat `policy/` and `schemas/` as immutable unless the phase explicitly authorizes a policy correction. Application code must conform to them.
4. Never paste or echo raw player messages, PAN/CVV, identity values or player IDs in chat output, logs, tests or documentation.
5. Do not call external LLM APIs or upload the dataset. The selected runtime is local/provider-independent. Internet may be used only for dependency/model installation and official documentation, never for message processing.
6. Do not implement real account, payment, KYC, self-exclusion, regulator or communication integrations.
7. At the end of each phase, run the specified checks and write `docs/phase_reports/phase_<NN>.md` using the template.
8. Stop after the phase report. Summarize changed files, commands run, tests, known limitations and exact next-phase prerequisites.
9. Preserve working functionality. Do not rewrite unrelated files.
10. Fail closed: invalid input, redaction uncertainty, schema failure or model outage must route to human/specialist fallback.

Provider note: OpenAI/Codex was not selected as the runtime provider because of the public real-money-gambling restriction. If Codex is used as a coding assistant, use only the synthetic case-study repository, do not connect production systems, and do not send real player data without explicit organizational/provider approval.
