# Technology Stack

## Required
- Python 3.12
- Streamlit: local UI and controlled forms
- Typer: repeatable CLI commands
- jsonschema Draft 2020-12: structural validation
- sqlite3: internal state and audit index
- openpyxl: supplied XLSX import/verification
- pytest: unit, behavioural and integration tests
- standard-library `csv`, `json`, `re`, `hashlib`, `logging`, `pathlib`, `datetime`

## Recommended small dependencies
- `portalocker` for safe configuration-file activation on local systems
- `pandas` only in the Streamlit presentation layer

## Optional
- `llama-cpp-python` with an approved local GGUF model through the `ClassifierProvider` interface.

## Explicitly excluded
Hosted LLM APIs, FastAPI, external databases, vector stores, fine-tuning, attachment processing, account/payment integrations and autonomous actions.
