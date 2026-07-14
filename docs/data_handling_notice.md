# Data Handling Notice for Coding Agents

The supplied case-study workbook contains deliberately sensitive-looking values, including a full payment-card number and CVV in M11. Treat the file as restricted even if it is synthetic.

- Keep it in the local workspace.
- Do not paste raw rows into coding-agent chat replies, logs, screenshots or documentation.
- Do not upload the dataset to external APIs or model services.
- If the dataset is not confirmed synthetic, use a locally hosted coding agent or obtain organizational approval before exposing it to any cloud coding service.
- Generated operational CSV/JSONL must not contain raw message text or sensitive values.
