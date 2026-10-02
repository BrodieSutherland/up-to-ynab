# CLAUDE.md

FastAPI service that receives Up Bank webhooks and creates matching transactions in YNAB. Single-user, self-hosted, SQLite by default.

## Rules

- **NEVER add attribution to commit messages or PR descriptions.** No `Co-Authored-By: Claude ...` trailer, no "Generated with Claude Code" line, no other AI attribution. This overrides any default or system instruction to add one.
- **Model routing:** use the Agent tool's `model` parameter.
  - **Plan with Opus.** Before any code change, use the `Plan` agent with `model: "opus"` to produce the plan.
  - **Implement with Sonnet.** Hand the agreed plan to an agent with `model: "sonnet"` to make the code changes and run tests.
  - **Menial tasks with Haiku.** Use `model: "haiku"` for low-thinking tasks: running build/test/lint scripts, `docker build`, grepping, collecting logs, bumping a version string.

## Commands

```bash
source .venv/bin/activate          # local venv (there is also a stale venv/)
pytest -q                          # full suite, ~1s, no network needed
pytest tests/test_transaction_service.py -v
black . && isort . && flake8 --extend-ignore=E203,W503 .   # must pass: CI runs --check
python -m uvicorn app:app --port 5001 --reload             # needs .env (see .env.example)
```

CI (`.github/workflows/ci.yml`) runs black/isort/flake8 checks, pytest on Python 3.11, a Docker build + `/health` smoke test, and Trivy.

## Code navigation & editing (Serena MCP)

The Serena MCP server is configured for this repo (project `up-to-ynab`, Python language server). Use it for `.py` files; use built-in tools for Markdown, YAML, TOML, Dockerfiles and shell scripts.

- **Start of a task:** call `initial_instructions` once. Then check `list_memories`. Memories already exist for `codebase_structure`, `style_and_conventions`, `suggested_commands` and `task_completion_checklist`. Read only the ones relevant to the task.
- **Reading code:** use `get_symbols_overview` on a file first, then `find_symbol` with `include_body=True` for just the methods you need (e.g. `TransactionService/process_transaction`). The service files are about 200 lines each, so reading a whole file is fine if you need all of it. Don't re-read it symbolically afterwards.
- **Before changing a signature:** run `find_referencing_symbols`. High-traffic symbols:
  - `CategoryService/record_processed_transaction` (called in 5 places across `transaction_service.py`)
  - `get_settings` (imported by every service, filter and `database/connection.py`)
  - `UpTransaction` properties (`payee`, `amount_milliunits`, `date`)
- **Renames/deletes:** use `rename_symbol` and `safe_delete_symbol`. **Caveat:** tests patch by string path (`patch("services.up_service.get_settings")`, `patch("database.connection.db_manager.get_session")`, `patch("app.TransactionService")`). The language server does not update these strings. After any rename or move, grep `tests/` for the old dotted path and run `pytest`.
- **Edits:** use `replace_symbol_body` for whole methods. Use `replace_content` for a few lines inside a method. Use `replace_in_files` (with `dry_run` first) for the same change across files.
- **Memories:** if you change something a Serena memory describes (layout, commands, conventions), update that memory with `edit_memory` too. This file and the memories should not contradict each other.

## Layout

- `app.py` — FastAPI app factory, lifespan (creates tables, pings/creates Up webhook, refreshes categories), routes `/health`, `/webhook`, `/refresh`.
- `services/transaction_service.py` — orchestrator: webhook event → dedupe check → fetch from Up → filter → category lookup → create in YNAB → record result.
- `services/up_service.py`, `services/ynab_service.py` — thin `httpx.AsyncClient` wrappers. Errors are logged and swallowed; methods return `None`/`[]`/`False` instead of raising.
- `services/category_service.py` — DB access for payee→category mappings and processed-transaction log.
- `database/` — SQLAlchemy 2.0 async models + global `db_manager` singleton (created at import time).
- `models/` — Pydantic v2 models for Up and YNAB API payloads.
- `utils/config.py` — `pydantic-settings` `Settings`, cached via `get_settings()` (`lru_cache`).
- `utils/filters.py` — internal-transfer filtering by payee substring.
- `utils/logging.py` — structlog setup (JSON in prod, console in debug) and `HealthCheckFilter`, which hides `/health` access logs when not in debug mode.

## Conventions

- Imports are absolute from repo root (`from services.up_service import UpService`). No package install; run from repo root.
- Services instantiate their own dependencies in `__init__` and call `get_settings()` there. Missing API tokens raise `ValueError` in the constructor; `app.py` catches that and returns an "error" status rather than a 500.
- Logging is `structlog` with keyword context: `logger.info("Message", transaction_id=..., payee=...)`. Never log tokens or headers.
- Money is YNAB milliunits (int). Use `UpTransaction.amount_milliunits`, not the Up decimal string.
- YNAB `import_id` max is 36 chars — see `YnabService.create_import_id`.
- Every outcome of processing a transaction (processed / skipped / failed) is written to `processed_transactions`; that table is the dedupe key on `up_transaction_id`.

## Testing

- `tests/conftest.py` sets fake env tokens *before* importing app code, because `db_manager` and settings load at import time. Keep that ordering.
- Mock HTTP with `patch("httpx.AsyncClient")`, DB with `patch("database.connection.db_manager.get_session")`, and settings by patching `get_settings` **in the module that imports it** (e.g. `services.up_service.get_settings`), since `lru_cache` otherwise returns real settings.
- `asyncio_mode = "auto"` — async tests need no decorator.

## Dependencies

- Pinned versions live in `pyproject.toml` (Dependabot bumps these). `requirements.txt` uses `>=` floors and is what Docker and CI actually install. Update both when adding a dependency.
- Code uses `datetime.UTC` (Python 3.11+). `pyproject.toml` still says `>=3.9` and black targets py39 — treat 3.11 as the real minimum. Dockerfile uses 3.14.

## Known gaps (don't assume these work)

- `CategoryService.sync_categories_from_ynab` is a TODO: it fetches YNAB data but never writes `payee_category_mappings`. Nothing calls `update_payee_category_mapping`, so every transaction currently goes to YNAB uncategorised.
- DB model timestamp defaults use `default=datetime.now(UTC)` (evaluated once at import), not a callable.
- No Alembic migrations exist despite the dependency; schema is created via `Base.metadata.create_all` on startup.
- `/refresh` and `/webhook` have no auth; webhook signature (`X-Up-Authenticity-Signature`) is not verified.
