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
black . && isort . && flake8 .   # must pass: CI runs --check; .flake8 holds the flags
python -m uvicorn --factory app:create_app --port 5001 --reload             # needs .env (see .env.example)
```

CI (`.github/workflows/ci.yml`) runs on pushes to `main`/`develop`, `v*` tags, and PRs into `main` and `develop`. Jobs run in parallel: a separate `lint` job (black/isort/flake8 on Python 3.14), `test` (Python 3.11 and 3.14) with an app-only branch coverage gate (`[tool.coverage]` in `pyproject.toml`; `fail_under` is 97; new top-level packages must be added to coverage `source`), `docker-build` and `security-scan`. `docker-build` builds the `runtime` target through `build-push-action` (its own `smoke` gha cache scope), runs it with `PORT=8080` and requires the image `HEALTHCHECK` to report healthy, then runs a Trivy image scan. `security-scan` runs a Trivy fs scan. Both Trivy scans are report-only (SARIF uploads). CodeQL runs from `.github/workflows/codeql.yml` on `main` and `develop` (advanced setup, so it also covers Dependabot PRs; repo-level "default setup" must stay disabled or the uploads conflict). The multi-arch image (`docker-publish.yml`, a reusable workflow called as the `image` job) is built on PRs without pushing (the Dockerfile's `deps` stage resolves wheels natively for each target arch, so no QEMU pip), and is published to Docker Hub only from `main` / `v*` tags after all checks pass. The metadata step uses `flavor: latest=false`, so only `main` moves `latest`. `CI OK` is the single required status check. Dependabot patch PRs squash-merge automatically via a GitHub App token (secrets `AUTOMERGE_APP_ID`, `AUTOMERGE_APP_PRIVATE_KEY`) once `CI OK` passes.

## Code navigation & editing (Serena MCP)

The Serena MCP server is configured for this repo (project `up-to-ynab`, Python language server). Use it for `.py` files; use built-in tools for Markdown, YAML, TOML, Dockerfiles and shell scripts.

- **Start of a task:** call `initial_instructions` once. Then check `list_memories`. Memories already exist for `codebase_structure`, `style_and_conventions`, `suggested_commands` and `task_completion_checklist`. Read only the ones relevant to the task.
- **Reading code:** use `get_symbols_overview` on a file first, then `find_symbol` with `include_body=True` for just the methods you need (e.g. `Forwarder/handle`). The service files are about 200 lines each, so reading a whole file is fine if you need all of it. Don't re-read it symbolically afterwards.
- **Before changing a signature:** run `find_referencing_symbols`. High-traffic symbols:
  - `Ledger.record` (called by `Forwarder.handle`; `SqlLedger` and `InMemoryLedger` implement it)
  - `build_services` (the only place services are built; every constructor takes plain values or other services)
  - `UpClient` / `YnabClient` Protocols (the `Http*Client` adapters and `tests/fakes` implement them)
  - `translate` / `cleared_status` (`forwarding/translation.py`)
  - `build_budget_index` / `BudgetIndexHolder.current_for`
  - `plan_webhook_changes` (`webhooks.py`)
  - `UpTransaction` properties (`payee`, `amount_milliunits`, `account_id`, `transfer_account_id`)
- **Renames/deletes:** use `rename_symbol` and `safe_delete_symbol`. The language server does not update dotted paths in strings, so after any rename or move grep `tests/` for the old name and run `pytest`.
- **Edits:** use `replace_symbol_body` for whole methods. Use `replace_content` for a few lines inside a method. Use `replace_in_files` (with `dry_run` first) for the same change across files.
- **Memories:** if you change something a Serena memory describes (layout, commands, conventions), update that memory with `edit_memory` too. This file and the memories should not contradict each other.

## Layout

- `app.py` — composition root: module-level `VERSION` (3.0.0; feeds FastAPI metadata and `/health`, `pyproject.toml` kept in step, `tests/test_version.py` checks it), `Services` dataclass (incl. `webhook_secrets`), `build_services(settings, database, up, ynab)`, `open_services(settings)` (owns the DB, migrates it to head and both `httpx2.AsyncClient`s via one `AsyncExitStack`, builds real services, closes everything on exit), `reconcile_webhooks(up, secrets, webhook_url)` (lists hooks, executes `plan_webhook_changes` with `known_secret_ids` from the secret store: forgets secrets of unlisted hooks, deletes then drops the secret of each deleted hook, creates and saves the new hook's secret; warns "No webhook secret stored" if none remain; only `UpstreamError` is caught, so listing failure means no create/delete), `require_admin` (dependency on `/refresh` and later admin routes: with `ADMIN_TOKEN` set needs `Authorization: Bearer <token>`, constant-time compare, else 401; unset means open, with a startup warning). `/webhook` reads the raw body, verifies `X-Up-Authenticity-Signature` (401 otherwise), then parses it (422 on a bad body), `create_app(settings=None, services=None)` and its lifespan (webhook reconciliation + Budget Index build, then starts the 6-hourly rebuild task as `app.state.rebuild_task` and cancels it on shutdown before services close; owns services only when it built them). Routes read `app.state.services`. Start with `uvicorn --factory app:create_app`; there is no module-level `app`.
- `migrations/` — Alembic revisions, hand-written (`0001` = 3.0 `ledger_entries`, `0002` drops legacy tables, `0003` adds `webhook_secrets`, `0004` adds `ledger_entries.reason_code`). No `alembic.ini`; `env.py` runs on the connection passed in `config.attributes["connection"]`, never its own engine. A new revision needs `down_revision` set and a test in `tests/test_migrations.py`.
- `webhooks.py` — pure `plan_webhook_changes(registered_hooks, webhook_url, *, known_secret_ids) -> WebhookPlan(create, delete, warnings, forget)`: keeps the first hook at `WEBHOOK_URL` (normalised) whose secret is stored (one without a stored secret is deleted and replaced; a foreign one is left with a warning and ours created), deletes app-described duplicates and app-described same-host hooks at other paths, warns on app-described other-host hooks, never touches hooks without an app description; `forget` lists stored secret ids Up no longer lists. Also `sign(body, secret)` / `signature_valid(body, signature, secrets)` (HMAC-SHA256 hex of the raw body, constant-time, any current secret) and `SIGNATURE_HEADER`. Runs at startup and `/refresh`.
- `forwarding/` — `Forwarder` (webhook event → Ledger check → fetch from Up → translate → create in YNAB → record outcome; returns Forwarded / Skipped / Failed / Ignored / Settled / Deleted; `TRANSACTION_DELETED` on a forwarded row with a YNAB id fetches the YNAB copy: uncleared is DELETEd, cleared or reconciled is flagged red (warning logged), already gone (404 or `deleted`) counts as deleted; the `Deleted` outcome then marks the row `deleted` (final), and a YNAB failure returns Failed leaving the row forwarded; no entry, skipped or failed rows are Ignored, as is an already deleted one; `TRANSACTION_SETTLED` on a forwarded row fetches the YNAB copy (by id, or by `import_id` via `list_transactions` when the id is None), leaves `reconciled` ones, else PATCHes cleared and a differing amount and returns `Settled`; no entry or failed falls through to the normal create flow, skipped is Ignored; a settlement failure returns Failed without touching the Ledger; `cleared_status` is `cleared` for SETTLED, `uncleared` for HELD), `backfill.py` (`backfill(up, forwarder, since, limit=150)`: lists Up transactions via `UpClient.list_transactions(since)`, sorts oldest first, calls `Forwarder.backfill_one(tx)` (returns `BackfillStep(outcome, ynab_create_called)`; never re-fetches; handled rows are Ignored "already handled" except `backfill_retryable` ones: failed, or skipped with a `RETRYABLE_SKIP_CODES` code), stops after 150 YNAB create attempts (`more_remaining`); served by admin `POST /backfill?since=YYYY-MM-DD`, midnight Australian time, 502 if Up cannot be listed), `ledger.py` (`Skipped` carries a `reason_code` (`translate`'s `Skip.code`: `account_not_in_ynab`, `mirror_side`); `Deleted` outcome only changes a `forwarded` row; `Ledger` protocol (`record`, `is_handled`, `lookup` -> `LedgerState`), `SqlLedger` on `ledger_entries`), `translation.py` (pure `translate`; `cleared_status` is the single place cleared is decided; Transfer rule: recognised by `transferAccount`, and when both Up accounts are in YNAB the Originating side (amount <= 0, or the positive "Round Up" half) becomes a YNAB transfer via the other account's `transfer_payee_id` while the Mirror side is skipped; otherwise each half is ordinary), `budget_index.py` (pure `build_budget_index` matching Up to YNAB accounts by exact name and deriving the Category match per payee from all-time YNAB transactions (`since_date=1970-01-01`; transfers, splits, uncategorised, payee-less and deleted excluded; keyed by both `payee_name` and `import_payee_name`; one category per key across both sources, else none), immutable `BudgetIndex`, and `BudgetIndexHolder` which rebuilds at startup, on `/refresh`, every 6 hours via `rebuild_periodically` (injected sleep), and lazily (at most once a minute, injected clock) for an unknown Up account; raises `IndexUnavailable` if never built).
- `clients/` — `UpClient` / `YnabClient` Protocols, each with an `Http*Client` adapter on an injected `httpx2.AsyncClient` opened/closed by `open_services`. `YnabClient` also has `get_transaction` and `update_transaction` (bulk `PATCH /transactions` by id; amount omitted when unchanged, date never sent). `YnabClient` also has `delete_transaction` and `flag_transaction` (bulk PATCH of `flag_color`). Up has list/create/delete webhook (delete answers 204; `_request` returns None for empty bodies). Non-success, transport and parse errors raise `clients.errors.UpstreamError`; a YNAB 409 on create returns `AlreadyImported`. YNAB paths use `/plans/`. Adapters don't log.
- `database/` — SQLAlchemy 2.0 async models + `DatabaseManager(database_url, echo)` (no global instance) and the `SessionFactory` type that `SqlLedger` receives. `database/webhook_secrets.py` holds `WebhookSecretStore` / `SqlWebhookSecretStore` on `webhook_secrets` (webhook id -> Up's `secretKey`; `UpClient.create_webhook` returns `CreatedWebhook(id, secret_key)`). `DatabaseManager.migrate()` (in `database/migrate.py`) runs Alembic on the manager's own connection: an unversioned 3.0 database (has `ledger_entries`, no `alembic_version`) is stamped at 0001, then upgraded to head. Revision 0002 drops the legacy `payee_category_mappings` and `processed_transactions` tables.
- `models/` — Pydantic v2 models for Up and YNAB API payloads.
- `utils/config.py` — `pydantic-settings` `Settings`, built once in `create_app` (no cache, no getter). Required token/ID fields reject missing, empty and whitespace values; `hide_input_in_errors=True` keeps secrets out of validation errors.
- `utils/logging.py` — structlog setup (JSON in prod, console in debug) and `HealthCheckFilter`, which hides `/health` access logs when not in debug mode.

## Conventions

- Imports are absolute from repo root (`from clients.up import HttpUpClient`). No package install; run from repo root.
- Constructor injection: services take plain values (tokens, URLs, IDs) or other services; nothing but `build_services`/`create_app` reads `Settings`. A missing or empty required token fails startup with a `ValidationError` naming the field (never the value).
- Logging is `structlog` with keyword context: `logger.info("Message", transaction_id=..., payee=...)`. Never log or repr tokens, headers, webhook secrets or request bodies; parse a webhook body only after its signature is verified.
- Money is YNAB milliunits (int). Use `UpTransaction.amount_milliunits`, not the Up decimal string.
- YNAB `import_id` is the Up transaction id, unchanged (no prefix or hash).
- Clients raise `UpstreamError`; callers decide what a failure means (record it, retry, ignore).
- Every handled event for a transaction is recorded in the Ledger (`ledger_entries`, one row per `up_transaction_id`): forwarded / skipped are handled (a forwarded row later becomes `deleted`, final, when Up deletes the transaction); settlement records nothing; a skipped row with `reason_code` `account_not_in_ynab` is the one handled row `record()` may overwrite (by Forwarded or Skipped; a Failed is not recorded over it), only reached via backfill; other skips (including 3.0 rows with a null code) are final; failed is retried on Up redelivery (webhook answers 503). The legacy `processed_transactions` table is dropped by migration 0002.

## Testing

- Redacted real Up payloads live in `tests/fixtures/up/`.
- `tests/conftest.py` no longer touches env vars. `test_settings` is `Settings(..., _env_file=None)` over in-memory SQLite; the async `database` fixture (migrated to head) and `services` fixture (`build_services(test_settings, database)`) give real services. Build any other `Settings` in tests with `_env_file=None`.
- In-memory fakes live in `tests/fakes/` (`FakeUpClient`, `FakeYnabClient`, `InMemoryLedger`, `InMemoryWebhookSecretStore`, `FakeIndexHolder` holding a `BudgetIndex`); the `services` fixture wires them. Real adapters are tested with `httpx2.MockTransport`; never patch the HTTP client. API tests use `with TestClient(create_app(settings, make_services(up, ynab, holder, ledger)))` built from the fakes; webhook tests send `post_signed(client, data)` (the fake Up gives its n-th created hook the secret `webhook-n-secret`). DB tests use the real in-memory `database`; seed and assert in fresh `async with database.get_session()` blocks (a shared session goes stale). Don't patch `app.*`, settings, or the database manager.
- `asyncio_mode = "auto"` — async tests need no decorator.

## Dependencies

- `pyproject.toml`, `requirements.txt` and `requirements-dev.txt` all use exact `==` pins and must match (Dependabot bumps them together). Update all of them when adding or changing a dependency.
- `requirements.txt` is runtime-only and is what Docker installs. Docker installs wheels only (`--only-binary`), so a dependency without cp314 manylinux wheels for both amd64 and arm64 fails the build. A new top-level package must also be added to the `.dockerignore` allowlist (and coverage `source`). Alembic is a runtime dependency (pure Python; pulls Mako and MarkupSafe), and `migrations/` is in the `.dockerignore` allowlist and coverage `source`. Tests, coverage and lint tools (pytest*, black, isort, flake8) live in `requirements-dev.txt` (`-r requirements.txt` plus dev pins), which CI and `scripts/run-tests.sh` install.
- Python 3.11 is the minimum (`requires-python`, black target py311); code uses `datetime.UTC`. CI runs the test job on 3.11 and 3.14. Dockerfile uses 3.14.

## Known gaps (don't assume these work)

- `/refresh` and `/backfill` are open unless `ADMIN_TOKEN` is set.
- Category match is keyed by YNAB payee name and import payee name (pre-rename), so YNAB rename rules no longer break it; but when Up itself starts describing a merchant differently, the new description has no Category match until it is categorised in YNAB again.
- Only `TRANSACTION_CREATED`, `TRANSACTION_SETTLED` and `TRANSACTION_DELETED` are acted on.
- A `TRANSACTION_DELETED` for a transaction forwarded via the 409 path (no YNAB id) is ignored with a warning.
- A `TRANSACTION_DELETED` that arrives before its `TRANSACTION_CREATED` is ignored; the CREATED then fails (Up 404) and is retried until Up gives up.
- An Up account with no matching YNAB account is skipped (`reason_code` `account_not_in_ynab`); webhook redelivery won't retry it, but `POST /backfill` does. No automatic retry when an account becomes matched.

## Agent skills

### Issue tracker

Issues live as local markdown under `.scratch/` (gitignored, this clone only). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
