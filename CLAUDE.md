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
pip install -r requirements-dev.txt   # runtime + test + lint tools
pytest -q                          # full suite, ~1s, no network needed
pytest tests/test_forwarder.py -v
pytest -q --cov --cov-branch   # coverage gate
black . && isort . && flake8 --extend-ignore=E203,W503 .   # must pass: CI runs --check
python -m uvicorn --factory app:create_app --port 5001 --reload             # needs .env (see .env.example)
```

CI (`.github/workflows/ci.yml`) runs on pushes to `main`/`develop`, `v*` tags, and PRs into `main` and `develop`. It runs tests (Python 3.11 and 3.14) with an app-only branch coverage gate (`[tool.coverage]` in `pyproject.toml`; `fail_under` is currently 89, ratcheting to 90; new top-level packages must be added to coverage `source`) and black/isort/flake8 checks, a Docker build + `/health` smoke test, and Trivy. CodeQL runs from `.github/workflows/codeql.yml` (advanced setup, so it also covers Dependabot PRs; repo-level "default setup" must stay disabled or the uploads conflict). The multi-arch image (`docker-publish.yml`, a reusable workflow called as the `image` job) is built on PRs without pushing, and is published to Docker Hub only from `main` / `v*` tags after all checks pass. The metadata step uses `flavor: latest=false`, so only `main` moves `latest`. `CI OK` is the single required status check. Dependabot patch PRs auto-merge via a GitHub App token (secrets `AUTOMERGE_APP_ID`, `AUTOMERGE_APP_PRIVATE_KEY`) once `CI OK` passes.

## Code navigation & editing (Serena MCP)

The Serena MCP server is configured for this repo (project `up-to-ynab`, Python language server). Use it for `.py` files; use built-in tools for Markdown, YAML, TOML, Dockerfiles and shell scripts.

- **Start of a task:** call `initial_instructions` once. Then check `list_memories`. Memories already exist for `codebase_structure`, `style_and_conventions`, `suggested_commands` and `task_completion_checklist`. Read only the ones relevant to the task.
- **Reading code:** use `get_symbols_overview` on a file first, then `find_symbol` with `include_body=True` for just the methods you need (e.g. `Forwarder/handle`). The service files are about 200 lines each, so reading a whole file is fine if you need all of it. Don't re-read it symbolically afterwards.
- **Before changing a signature:** run `find_referencing_symbols`. High-traffic symbols:
  - `Ledger.record` (called by `Forwarder.handle`; `SqlLedger` and `InMemoryLedger` implement it)
  - `build_services` (the only place services are built; every constructor takes plain values or other services)
  - `UpTransaction` properties (`payee`, `amount_milliunits`, `date`)
- **Renames/deletes:** use `rename_symbol` and `safe_delete_symbol`. **Caveat:** the only string patches left in `tests/` are `patch("httpx2.AsyncClient")` (until ticket 04 injects the HTTP client); the language server does not update those strings. After any rename or move, grep `tests/` for the old dotted path and run `pytest`.
- **Edits:** use `replace_symbol_body` for whole methods. Use `replace_content` for a few lines inside a method. Use `replace_in_files` (with `dry_run` first) for the same change across files.
- **Memories:** if you change something a Serena memory describes (layout, commands, conventions), update that memory with `edit_memory` too. This file and the memories should not contradict each other.

## Layout

- `app.py` — composition root: `Services` dataclass, `build_services(settings, database, up, ynab)`, `open_services(settings)` (owns the DB and both `httpx2.AsyncClient`s via one `AsyncExitStack`, builds real services, closes everything on exit), `ping_webhook(up, url)`, `create_app(settings=None, services=None)` and its lifespan (webhook ping + category refresh; owns services only when it built them). Routes read `app.state.services`. Start with `uvicorn --factory app:create_app`; there is no module-level `app`.
- `forwarding/` — `Forwarder` (webhook event → Ledger check → fetch from Up → translate → create in YNAB → record outcome; returns Forwarded / Skipped / Failed / Ignored), `ledger.py` (`Ledger` protocol, `SqlLedger` on `ledger_entries`), `translation.py` (pure `translate`, `create_import_id`), `budget_index.py` (`LegacyIndexHolder` stand-in until ticket 06).
- `clients/` — `UpClient` / `YnabClient` Protocols, each with an `Http*Client` adapter on an injected `httpx2.AsyncClient` opened/closed by `open_services`. Non-success, transport and parse errors raise `clients.errors.UpstreamError`; a YNAB 409 on create returns `AlreadyImported`. YNAB paths use `/plans/`. Adapters don't log.
- `services/category_service.py` — DB access for payee→category mappings.
- `database/` — SQLAlchemy 2.0 async models + `DatabaseManager(database_url, echo)` (no global instance) and the `SessionFactory` type that `CategoryService` receives.
- `models/` — Pydantic v2 models for Up and YNAB API payloads.
- `utils/config.py` — `pydantic-settings` `Settings`, built once in `create_app` (no cache, no getter). Required token/ID fields reject missing, empty and whitespace values; `hide_input_in_errors=True` keeps secrets out of validation errors.
- `utils/filters.py` — internal-transfer filtering by payee substring; `TransactionFilter(internal_transfer_strings)` takes the strings, not settings.
- `utils/logging.py` — structlog setup (JSON in prod, console in debug) and `HealthCheckFilter`, which hides `/health` access logs when not in debug mode.

## Conventions

- Imports are absolute from repo root (`from clients.up import HttpUpClient`). No package install; run from repo root.
- Constructor injection: services take plain values (tokens, URLs, IDs) or other services; nothing but `build_services`/`create_app` reads `Settings`. A missing or empty required token fails startup with a `ValidationError` naming the field (never the value).
- Logging is `structlog` with keyword context: `logger.info("Message", transaction_id=..., payee=...)`. Never log tokens or headers.
- Money is YNAB milliunits (int). Use `UpTransaction.amount_milliunits`, not the Up decimal string.
- YNAB `import_id` max is 36 chars — see `forwarding.translation.create_import_id`.
- Clients raise `UpstreamError`; callers decide what a failure means (record it, retry, ignore).
- Every handled event for a transaction is recorded in the Ledger (`ledger_entries`, one row per `up_transaction_id`): forwarded / skipped are handled; failed is retried on Up redelivery (webhook answers 503). The old `processed_transactions` table is left unread.

## Testing

- Redacted real Up payloads live in `tests/fixtures/up/`.
- `tests/conftest.py` no longer touches env vars. `test_settings` is `Settings(..., _env_file=None)` over in-memory SQLite; the async `database` fixture and `services` fixture (`build_services(test_settings, database)`) give real services. Build any other `Settings` in tests with `_env_file=None`.
- In-memory fakes live in `tests/fakes/` (`FakeUpClient`, `FakeYnabClient`, `InMemoryLedger`, `FakeIndexHolder`); the `services` fixture wires them. Real adapters are tested with `httpx2.MockTransport`; never patch the HTTP client. API tests use `with TestClient(create_app(settings, make_services(up, ynab, holder, ledger)))` built from the fakes. DB tests use the real in-memory `database`; seed and assert in fresh `async with database.get_session()` blocks (a shared session goes stale). Don't patch `app.*`, settings, or the database manager.
- `asyncio_mode = "auto"` — async tests need no decorator.

## Dependencies

- `pyproject.toml`, `requirements.txt` and `requirements-dev.txt` all use exact `==` pins and must match (Dependabot bumps them together). Update all of them when adding or changing a dependency.
- `requirements.txt` is runtime-only and is what Docker installs. Tests, coverage and lint tools (pytest*, black, isort, flake8) live in `requirements-dev.txt` (`-r requirements.txt` plus dev pins), which CI and `scripts/run-tests.sh` install.
- Python 3.11 is the minimum (`requires-python`, black target py311); code uses `datetime.UTC`. CI runs the test job on 3.11 and 3.14. Dockerfile uses 3.14.

## Known gaps (don't assume these work)

- `CategoryService.sync_categories_from_ynab` is a TODO: it no longer fetches YNAB and never writes `payee_category_mappings`. Nothing calls `update_payee_category_mapping`, so every transaction currently goes to YNAB uncategorised.
- DB model timestamp defaults use `default=datetime.now(UTC)` (evaluated once at import), not a callable.
- No Alembic installed and no migrations; schema is created via `Base.metadata.create_all` on startup.
- `/refresh` and `/webhook` have no auth; webhook signature (`X-Up-Authenticity-Signature`) is not verified.

## Agent skills

### Issue tracker

Issues live as local markdown under `.scratch/` (gitignored, this clone only). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
